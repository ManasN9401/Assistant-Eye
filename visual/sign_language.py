"""
Sign Language Interpreter — Phase 3
Translates hand shapes into text commands using a two-tier approach:

Tier 1 — Quick-action signs (instant, no model needed):
  A small vocabulary of ASL-inspired static hand shapes that map directly
  to ARIA commands. Recognised purely from landmark geometry (same as
  hand_tracker.py gestures).

Tier 2 — Full ASL fingerspelling (optional, slower):
  Uses a lightweight CNN classifier trained on ASL alphabet images.
  Letters are accumulated over time into words.
  Requires: mediapipe + a small ONNX model (~2MB).

Settings:
  sign_mode : "quick_actions" | "fingerspelling" | "both"
  sign_model_path : path to .onnx alphabet model (optional)

Quick-action vocabulary (subset of ASL):
  A (fist, thumb side)    → confirm
  B (flat hand, fingers up, thumb folded) → stop / pause
  C (curved hand)         → cancel
  D (index up, others curl, thumb touches middle) → go to docs
  G (index points sideways, thumb up) → go to / navigate
  L (thumb up + index out at 90°) → listen
  S (closed fist, thumb over fingers) → search
  Y (thumb + pinky out) → call me / open assistant
"""
from __future__ import annotations
import time
import logging
from typing import Optional

import numpy as np
from PyQt6.QtCore import QObject, QThread, pyqtSignal


# ── Logging setup ─────────────────────────────────────────────────────────────

logger = logging.getLogger(__name__)


# ── Camera utilities ──────────────────────────────────────────────────────────

def detect_available_cameras(max_cameras: int = 5) -> list[int]:
    """Returns list of available camera indices."""
    import cv2
    available = []
    for i in range(max_cameras):
        cap = cv2.VideoCapture(i)
        if cap.isOpened():
            available.append(i)
            # Log camera properties
            width = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
            height = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
            fps = cap.get(cv2.CAP_PROP_FPS)
            logger.debug(f"Camera {i} detected: {int(width)}x{int(height)} @ {fps:.1f} FPS")
            cap.release()
        else:
            logger.debug(f"Camera {i} not available")
    logger.info(f"Available cameras: {available}")
    return available


# ── ASL quick-action classifier ───────────────────────────────────────────────

def _dist(a, b) -> float:
    return float(np.linalg.norm(np.array([a.x - b.x, a.y - b.y])))

def _finger_curled(lm, tip, pip) -> bool:
    return lm[tip].y > lm[pip].y   # tip below pip = curled


QUICK_ACTIONS: dict[str, str] = {
    "sign_confirm":   "confirm",
    "sign_stop":      "stop_speaking",
    "sign_cancel":    "cancel",
    "sign_docs":      "go_to_docs",
    "sign_navigate":  "navigate",
    "sign_listen":    "trigger_listen",
    "sign_search":    "open_search",
    "sign_assistant": "open_overlay",
}


def classify_asl_quick(lm) -> Optional[str]:
    """
    Attempt to classify hand landmark set into a quick-action ASL sign.
    Returns the sign name or None.
    """
    thumb_up   = lm[4].y < lm[3].y
    index_ext  = lm[8].y  < lm[6].y
    mid_ext    = lm[12].y < lm[10].y
    ring_ext   = lm[16].y < lm[14].y
    pinky_ext  = lm[20].y < lm[18].y

    # Thumb pointing sideways (x diff > y diff)
    thumb_side = abs(lm[4].x - lm[3].x) > abs(lm[4].y - lm[3].y)

    # Sign S: fist, thumb over fingers (thumb tip above index knuckle)
    if (not index_ext and not mid_ext and not ring_ext and not pinky_ext
            and lm[4].y < lm[5].y and not thumb_up):
        return "sign_search"

    # Sign A: fist, thumb to side
    if (not index_ext and not mid_ext and not ring_ext and not pinky_ext
            and thumb_side):
        return "sign_confirm"

    # Sign B: all fingers up, thumb folded across palm
    if (index_ext and mid_ext and ring_ext and pinky_ext and not thumb_up
            and lm[4].x > lm[5].x):
        return "sign_stop"

    # Sign Y: thumb + pinky extended
    if (thumb_up and pinky_ext and not index_ext and not mid_ext and not ring_ext):
        return "sign_assistant"

    # Sign L: thumb up + index pointing, others curled
    if (thumb_up and index_ext and not mid_ext and not ring_ext and not pinky_ext
            and abs(lm[4].x - lm[8].x) > 0.05):
        return "sign_listen"

    # Sign G: index points sideways, thumb up
    if (index_ext and thumb_up and not mid_ext and not ring_ext and not pinky_ext
            and abs(lm[8].x - lm[6].x) > abs(lm[8].y - lm[6].y)):
        return "sign_navigate"

    # Sign D: index up, thumb touches middle tip
    if (index_ext and not mid_ext and not ring_ext and not pinky_ext
            and _dist(lm[4], lm[12]) < 0.06):
        return "sign_docs"

    # Sign C: all fingers curve (tips above MCPs but below extension threshold)
    # approximation: mid flex
    if (not index_ext and not mid_ext and not ring_ext and not pinky_ext
            and thumb_side and _dist(lm[4], lm[20]) > 0.15):
        return "sign_cancel"

    return None


# ── Fingerspelling classifier (ONNX) ─────────────────────────────────────────

class FingerspellingClassifier:
    """
    Classifies hand landmarks into ASL alphabet letters using an ONNX model.
    The model takes a flattened 21×3 landmark vector (63 floats, normalised).
    
    Pre-trained model download: included in assets/asl_landmarks.onnx
    Trained on the Kaggle ASL Alphabet dataset, landmark-extracted.
    """

    LETTERS = list("ABCDEFGHIJKLMNOPQRSTUVWXYZ") + ["del", "nothing", "space"]

    def __init__(self, model_path: str):
        import onnxruntime as ort
        self._sess = ort.InferenceSession(model_path)
        self._input_name = self._sess.get_inputs()[0].name

    def predict(self, hand_landmarks) -> tuple[str, float]:
        """Returns (letter, confidence)."""
        # hand_landmarks is now a list of NormalizedLandmark objects
        lm = hand_landmarks
        vec = np.array([[l.x, l.y, l.z] for l in lm], dtype=np.float32).flatten()

        # Normalise: subtract wrist, scale by hand size
        wrist = vec[:3]
        vec = vec - np.tile(wrist, 21)
        scale = float(np.linalg.norm(vec)) + 1e-8
        vec /= scale
        vec = vec.reshape(1, -1)

        out = self._sess.run(None, {self._input_name: vec})[0][0]
        idx = int(np.argmax(out))
        return self.LETTERS[idx], float(out[idx])


# ── Letter buffer (debounces and accumulates) ─────────────────────────────────

class LetterBuffer:
    """
    Accumulates classified letters into words with debouncing.
    - A letter must be held stable for HOLD_SEC before being accepted.
    - SPACE sign inserts a word boundary.
    - DEL sign removes last character.
    """
    HOLD_SEC   = 0.8
    CONF_THRESHOLD = 0.75

    def __init__(self):
        self._text   = ""
        self._last   = ""
        self._held_since: Optional[float] = None

    def update(self, letter: str, confidence: float) -> Optional[str]:
        """Returns newly committed letter/control or None."""
        if confidence < self.CONF_THRESHOLD:
            self._last = ""
            self._held_since = None
            return None

        if letter != self._last:
            self._last = letter
            self._held_since = time.time()
            return None

        if time.time() - (self._held_since or 0) >= self.HOLD_SEC:
            self._held_since = time.time() + 10   # prevent re-fire until new letter
            if letter == "del":
                self._text = self._text[:-1]
                return "DEL"
            elif letter == "space":
                self._text += " "
                return "SPACE"
            elif letter != "nothing":
                self._text += letter
                return letter

        return None

    @property
    def current_word(self) -> str:
        return self._text

    def clear(self):
        self._text = ""
        self._last = ""
        self._held_since = None


# ── Worker thread ─────────────────────────────────────────────────────────────

class SignLanguageWorker(QThread):
    quick_action  = pyqtSignal(str)          # action name from QUICK_ACTIONS
    letter_added  = pyqtSignal(str)          # single letter committed
    word_complete = pyqtSignal(str)          # full word when space/pause
    error         = pyqtSignal(str)

    def __init__(self, settings, camera_index: int = 0, parent=None):
        super().__init__(parent)
        self.settings     = settings
        self.camera_index = camera_index
        self._running     = False
        self._mode        = settings.get("sign_mode", "quick_actions")
        self._model_path  = settings.get("sign_model_path", "")
        self._buffer      = LetterBuffer()
        self._classifier: Optional[FingerspellingClassifier] = None
        self._cooldown:   dict[str, float] = {}

    def run(self):
        try:
            import cv2
            import mediapipe as mp
            from mediapipe.tasks.python.vision import HandLandmarker, HandLandmarkerOptions, RunningMode
            from mediapipe import Image, ImageFormat
        except ImportError as e:
            msg = f"Missing: {e}. Run: pip install opencv-python mediapipe"
            logger.error(msg)
            self.error.emit(msg)
            return

        if self._mode in ("fingerspelling", "both") and self._model_path:
            try:
                self._classifier = FingerspellingClassifier(self._model_path)
                logger.info(f"ONNX model loaded: {self._model_path}")
            except Exception as e:
                msg = f"ONNX model load failed: {e}. Using quick-actions only."
                logger.warning(msg)
                self.error.emit(msg)
                self._mode = "quick_actions"

        self._running = True
        logger.info(f"Starting sign language ({self._mode}) on camera {self.camera_index}")

        # Detect and display available cameras
        available_cameras = detect_available_cameras()
        if self.camera_index not in available_cameras:
            msg = f"Camera {self.camera_index} not available. Available: {available_cameras}"
            logger.error(msg)
            self.error.emit(msg)
            return

        cap = cv2.VideoCapture(self.camera_index)
        if not cap.isOpened():
            msg = f"Cannot open camera {self.camera_index}"
            logger.error(msg)
            self.error.emit(msg)
            return

        # Log camera properties
        logger.debug(f"Camera {self.camera_index} properties:")
        logger.debug(f"  Resolution: {int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))}x{int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))}")
        logger.debug(f"  FPS: {cap.get(cv2.CAP_PROP_FPS)}")

        landmarker = None
        try:
            options = HandLandmarkerOptions(
                base_options=mp.tasks.BaseOptions(model_asset_path="models/hand_landmarker.task"),
                running_mode=RunningMode.IMAGE,
                num_hands=1,
                min_hand_detection_confidence=0.75,
                min_hand_presence_confidence=0.7,
            )
            landmarker = HandLandmarker.create_from_options(options)

            while self._running:
                ok, frame = cap.read()
                if not ok:
                    continue

                rgb     = cv2.cvtColor(cv2.flip(frame, 1), cv2.COLOR_BGR2RGB)
                image = Image(image_format=ImageFormat.SRGB, data=rgb)
                results = landmarker.detect(image)

                if not results.hand_landmarks:
                    self._buffer.clear()
                    continue

                hand = results.hand_landmarks[0]

                # ── Tier 1: quick-action signs ────────────────
                if self._mode in ("quick_actions", "both"):
                    sign = classify_asl_quick(hand)
                    if sign:
                        now  = time.time()
                        last = self._cooldown.get(sign, 0)
                        if now - last > 1.2:
                            self._cooldown[sign] = now
                            action = QUICK_ACTIONS.get(sign, sign)
                            self.quick_action.emit(action)
                        continue

                # ── Tier 2: fingerspelling ────────────────────
                if self._mode in ("fingerspelling", "both") and self._classifier:
                    letter, conf = self._classifier.predict(hand)
                    committed = self._buffer.update(letter, conf)
                    if committed:
                        if committed == "SPACE":
                            word = self._buffer.current_word.strip()
                            if word:
                                self.word_complete.emit(word)
                            self._buffer.clear()
                        elif committed != "DEL":
                            self.letter_added.emit(committed)

        finally:
            cap.release()
            if landmarker:
                landmarker.close()
            logger.info(f"Sign language stopped (camera {self.camera_index})")

    def stop(self):
        self._running = False


# ── SignLanguageInterpreter (public API) ──────────────────────────────────────

class SignLanguageInterpreter(QObject):
    """
    Listens to the camera and translates sign language.
    Connect to quick_action, letter_added, word_complete.
    """
    quick_action  = pyqtSignal(str)
    letter_added  = pyqtSignal(str)
    word_complete = pyqtSignal(str)
    error         = pyqtSignal(str)

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self._worker: Optional[SignLanguageWorker] = None

    def start(self, camera_index: int = 0):
        if self._worker and self._worker.isRunning():
            return
        self._worker = SignLanguageWorker(self.settings, camera_index, self)
        self._worker.quick_action.connect(self.quick_action)
        self._worker.letter_added.connect(self.letter_added)
        self._worker.word_complete.connect(self.word_complete)
        self._worker.error.connect(self.error)
        self._worker.start()

    def stop(self):
        if self._worker:
            self._worker.stop()
            self._worker.quit()
            self._worker.wait(2000)

    @property
    def is_running(self) -> bool:
        return bool(self._worker and self._worker.isRunning())
