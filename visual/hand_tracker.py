"""
Hand Tracking Engine — Phase 3
Uses MediaPipe Hands (runs fully local, no internet required).

Detects:
  - PINCH_SCROLL   : thumb + index pinch, hand moves up/down → scroll
  - PINCH_CLICK    : rapid pinch (< 200ms hold) → mouse click at gaze/cursor pos
  - POINT          : index extended, others curled → move cursor
  - OPEN_PALM      : all fingers extended → pause/stop assistant
  - THUMBS_UP      : confirm action
  - FIST           : cancel / dismiss overlay
  - SNAP (approx)  : middle finger + thumb pinch → open overlay
  - VICTORY        : index + middle extended → scroll up fast
  - CALL_ME        : thumb + pinky extended → open assistant

Gesture → Action mapping is configurable per-registry and globally.

All landmark processing runs in a QThread. The main thread only receives
high-level gesture events via Qt signals.
"""
from __future__ import annotations
import time
import logging
from enum import Enum, auto
from typing import Optional

import numpy as np
from PyQt6.QtCore import QObject, QThread, pyqtSignal
from PyQt6.QtGui import QImage


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


class Gesture(str, Enum):
    NONE         = "none"
    PINCH_START  = "pinch_start"
    PINCH_END    = "pinch_end"
    PINCH_SCROLL = "pinch_scroll"
    POINT        = "point"
    OPEN_PALM    = "open_palm"
    FIST         = "fist"
    THUMBS_UP    = "thumbs_up"
    CLAP         = "clap"
    BOTH_PALMS   = "both_palms"
    VICTORY      = "victory"
    CALL_ME      = "call_me"


# ── Landmark utilities ────────────────────────────────────────────────────────

def _dist(a, b) -> float:
    return float(np.linalg.norm(np.array([a.x - b.x, a.y - b.y])))


def _finger_extended(lms, tip_idx: int, pip_idx: int) -> bool:
    """True if fingertip is above (lower y) its PIP joint."""
    return lms[tip_idx].y < lms[pip_idx].y


def classify_gesture(hand_landmarks) -> Gesture:
    """
    Map MediaPipe hand landmarks → Gesture enum.
    hand_landmarks is a list of hand landmarks (each an array of 21 landmarks).
    """
    if not hand_landmarks: return Gesture.NONE

    # ── Two-Hand Gestures ──────────────────────────────────────────────
    if len(hand_landmarks) == 2:
        h1 = hand_landmarks[0]
        h2 = hand_landmarks[1]
        
        # CLAP: distance between hands is small (palm to palm / tip to tip)
        wrist_dist = _dist(h1[0], h2[0])
        mid_dist = _dist(h1[12], h2[12])
        if wrist_dist < 0.15 and mid_dist < 0.15:
            return Gesture.CLAP
            
        def _is_open_palm(lm):
            thumb_up   = lm[4].y < lm[3].y
            index_ext  = _finger_extended(lm, 8, 6)
            mid_ext    = _finger_extended(lm, 12, 10)
            ring_ext   = _finger_extended(lm, 16, 14)
            pinky_ext  = _finger_extended(lm, 20, 18)
            return index_ext and mid_ext and ring_ext and pinky_ext and thumb_up

        if _is_open_palm(h1) and _is_open_palm(h2):
            return Gesture.BOTH_PALMS

    # ── Single-Hand Gestures ───────────────────────────────────────────
    # For single hand evaluations, use the first dominant hand
    lm = hand_landmarks[0]

    # ── Pinch (thumb ↔ index distance) ───────────────────────
    pinch_dist = _dist(lm[4], lm[8])
    is_pinching = pinch_dist < 0.06

    # ── Finger extension flags ────────────────────────────────
    thumb_up   = lm[4].y < lm[3].y
    index_ext  = _finger_extended(lm, 8, 6)
    mid_ext    = _finger_extended(lm, 12, 10)
    ring_ext   = _finger_extended(lm, 16, 14)
    pinky_ext  = _finger_extended(lm, 20, 18)

    # ── Pinch (index + thumb) ─────────────────────────────────
    if is_pinching and not mid_ext and not ring_ext:
        return Gesture.PINCH_START

    # ── Open palm ─────────────────────────────────────────────
    if index_ext and mid_ext and ring_ext and pinky_ext and thumb_up:
        return Gesture.OPEN_PALM

    # ── Fist ──────────────────────────────────────────────────
    if not index_ext and not mid_ext and not ring_ext and not pinky_ext and not thumb_up:
        return Gesture.FIST

    # ── Thumbs up ─────────────────────────────────────────────
    if thumb_up and not index_ext and not mid_ext and not ring_ext and not pinky_ext:
        return Gesture.THUMBS_UP

    # ── Victory (index + middle only) ─────────────────────────
    if index_ext and mid_ext and not ring_ext and not pinky_ext:
        return Gesture.VICTORY

    # ── Call me (thumb + pinky) ───────────────────────────────
    if thumb_up and pinky_ext and not index_ext and not mid_ext and not ring_ext:
        return Gesture.CALL_ME

    # ── Point (index only) ────────────────────────────────────
    if index_ext and not mid_ext and not ring_ext and not pinky_ext:
        return Gesture.POINT

    return Gesture.NONE


# ── Scroll calculator ─────────────────────────────────────────────────────────

class PinchScrollTracker:
    """Tracks pinch position over time to calculate scroll deltas."""

    def __init__(self, sensitivity: float = 1800.0):
        self._sensitivity = sensitivity
        self._last_y: Optional[float] = None
        self._pinch_start_time: Optional[float] = None

    def begin(self, y: float):
        self._last_y = y
        self._pinch_start_time = time.time()

    def update(self, y: float) -> float:
        """Returns scroll delta in pixels (negative = scroll up)."""
        if self._last_y is None:
            self._last_y = y
            return 0.0
        delta = (y - self._last_y) * self._sensitivity
        self._last_y = y
        return delta

    def end(self) -> bool:
        """Returns True if this was a quick tap (< 250ms) → treat as click."""
        if self._pinch_start_time:
            duration = time.time() - self._pinch_start_time
            self._last_y = None
            self._pinch_start_time = None
            return duration < 0.25
        return False

    def reset(self):
        self._last_y = None
        self._pinch_start_time = None


# ── Worker thread ─────────────────────────────────────────────────────────────

class HandTrackingWorker(QThread):
    # (gesture_name, x_norm, y_norm)
    gesture_detected = pyqtSignal(str, float, float)
    # (scroll_dy_pixels)
    scroll           = pyqtSignal(float)
    # (x_norm, y_norm) — for cursor control
    cursor_move      = pyqtSignal(float, float)
    # click at current position
    click            = pyqtSignal(float, float)
    error            = pyqtSignal(str)
    frame_processed  = pyqtSignal(object)  # Emits QImage

    def __init__(self, settings, camera_index: int = 0, parent=None):
        super().__init__(parent)
        self.settings     = settings
        self.camera_index = camera_index
        self._running     = False
        self._scroll_tracker = PinchScrollTracker(
            sensitivity=float(settings.get("hand_scroll_sensitivity", 1800))
        )
        self._was_pinching   = False
        self._last_discrete_gesture = Gesture.NONE
        self._gesture_buffer = []  # For temporal smoothing
        self._buffer_size_requirement = 5
        self._ema_x: Optional[float] = None
        self._ema_y: Optional[float] = None
        self._ema_alpha = 0.35

    def run(self):
        try:
            import cv2
            import mediapipe as mp
            from mediapipe.tasks.python.vision import HandLandmarker, HandLandmarkerOptions, RunningMode
            from mediapipe import Image, ImageFormat
        except ImportError as e:
            msg = f"Missing dependency: {e}. Run: pip install opencv-python mediapipe"
            logger.error(msg)
            self.error.emit(msg)
            return

        self._running = True

        # Detect and display available cameras
        available_cameras = detect_available_cameras()
        if self.camera_index not in available_cameras:
            msg = f"Camera {self.camera_index} not available. Available: {available_cameras}"
            logger.error(msg)
            self.error.emit(msg)
            return

        logger.info(f"Starting hand tracking on camera {self.camera_index}")

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
                num_hands=2,
                min_hand_detection_confidence=0.7,
                min_hand_presence_confidence=0.65,
            )
            landmarker = HandLandmarker.create_from_options(options)

            last_proc_time = 0.0
            while self._running:
                ok, frame = cap.read()
                if not ok:
                    continue

                now = time.time()
                # Frame skip to prevent lag (limit to ~20FPS)
                if now - last_proc_time < 0.05:
                    continue
                last_proc_time = now

                frame_rgb = cv2.cvtColor(cv2.flip(frame, 1), cv2.COLOR_BGR2RGB)
                image = Image(image_format=ImageFormat.SRGB, data=frame_rgb)
                results = landmarker.detect(image)

                if not results.hand_landmarks:
                    if self._was_pinching:
                        if self._scroll_tracker.end():  # quick tap = click
                            self.click.emit(0.5, 0.5)
                        self._was_pinching = False
                    
                    self._gesture_buffer.clear()
                    self._last_discrete_gesture = Gesture.NONE
                    h, w, ch = frame_rgb.shape
                    qimg = QImage(frame_rgb.data, w, h, ch * w, QImage.Format.Format_RGB888).copy()
                    self.frame_processed.emit(qimg)
                    continue

                # Parse first hand for 2D coords (for scrolling/pointing)
                hand = results.hand_landmarks[0]
                
                # We now pass the entire list of hands to support 2-hand gestures
                gesture = classify_gesture(results.hand_landmarks)
                
                ix = hand[8].x  # index tip x
                iy = hand[8].y  # index tip y
                
                cx, cy = int(ix * w), int(iy * h)

                # Draw landmarks for ALL detected hands over the camera feed output
                for h_lms in results.hand_landmarks:
                    for lm in h_lms:
                        jx, jy = int(lm.x * w), int(lm.y * h)
                        cv2.circle(frame_rgb, (jx, jy), 4, (200, 100, 255), -1)
                
                cv2.putText(frame_rgb, f"Gesture: {gesture.value}", (15, 40),
                            cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2, cv2.LINE_AA)
                
                qimg = QImage(frame_rgb.data, w, h, ch * w, QImage.Format.Format_RGB888).copy()
                self.frame_processed.emit(qimg)

                # Index tip normalised position (cursor anchor)
                ix = hand[8].x
                iy = hand[8].y

                # ── Pinch / scroll ────────────────────────────
                if gesture == Gesture.PINCH_START:
                    pinch_y = (hand[4].y + hand[8].y) / 2
                    if not self._was_pinching:
                        self._scroll_tracker.begin(pinch_y)
                        self._was_pinching = True
                    else:
                        delta = self._scroll_tracker.update(pinch_y)
                        if abs(delta) > 2:
                            self.scroll.emit(delta)
                    continue

                if self._was_pinching:
                    if self._scroll_tracker.end():
                        self.click.emit(ix, iy)
                    self._was_pinching = False

                # ── Point cursor move (with EMA smoothing) ────────────
                if gesture == Gesture.POINT:
                    if self._ema_x is None:
                        self._ema_x = ix
                        self._ema_y = iy
                    else:
                        self._ema_x = (self._ema_alpha * ix) + ((1 - self._ema_alpha) * self._ema_x)
                        self._ema_y = (self._ema_alpha * iy) + ((1 - self._ema_alpha) * self._ema_y)
                    self.cursor_move.emit(self._ema_x, self._ema_y)
                    continue
                else:
                    self._ema_x = None  # Reset EMA if gesture changes
                    self._ema_y = None

                # ── Discrete gestures (with temporal smoothing buffer) ──────────
                if gesture not in (Gesture.NONE, Gesture.POINT, Gesture.PINCH_START):
                    self._gesture_buffer.append(gesture)
                    if len(self._gesture_buffer) > self._buffer_size_requirement:
                        self._gesture_buffer.pop(0)
                        
                    # Only trigger if the buffer is full and entirely homogeneous 
                    if len(self._gesture_buffer) == self._buffer_size_requirement and all(g == gesture for g in self._gesture_buffer):
                        if gesture != self._last_discrete_gesture:
                            self._last_discrete_gesture = gesture
                            logger.debug(f"[HandTracker] Detected gesture: {gesture.value}")
                            self.gesture_detected.emit(gesture.value, ix, iy)
                else:
                    self._gesture_buffer.clear()
                    self._last_discrete_gesture = gesture

        finally:
            cap.release()
            if landmarker:
                landmarker.close()
            logger.info(f"Hand tracking stopped (camera {self.camera_index})")

    def stop(self):
        self._running = False


# ── HandTracker (public API) ──────────────────────────────────────────────────

class HandTracker(QObject):
    """
    High-level hand tracking manager.
    Translates raw gestures into assistant actions.
    """
    gesture          = pyqtSignal(str, float, float)
    scroll           = pyqtSignal(float)
    cursor_move      = pyqtSignal(float, float)
    click            = pyqtSignal(float, float)
    error            = pyqtSignal(str)

    # High-level action signals
    action_open_overlay  = pyqtSignal()
    action_close_overlay = pyqtSignal()
    action_confirm       = pyqtSignal()
    action_cancel        = pyqtSignal()
    action_stop_speaking = pyqtSignal()
    frame_processed      = pyqtSignal(object)

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self._worker: Optional[HandTrackingWorker] = None

    def start(self, camera_index: int = 0):
        if self._worker:
            if self._worker.isRunning():
                return
            self._worker.deleteLater()
            
        self._worker = HandTrackingWorker(self.settings, camera_index, self)
        self._worker.gesture_detected.connect(self._on_gesture)
        self._worker.scroll.connect(self.scroll)
        self._worker.cursor_move.connect(self.cursor_move)
        self._worker.click.connect(self.click)
        self._worker.error.connect(self.error)
        self._worker.frame_processed.connect(self.frame_processed)
        self._worker.start()

    def stop(self):
        if self._worker:
            self._worker.stop()
            self._worker.quit()
            if not self._worker.wait(2000):
                if not hasattr(self, "_zombies"):
                    self._zombies = []
                self._zombies.append(self._worker)
                import logging
                logging.getLogger(__name__).warning("HandTrackingWorker failed to exit cleanly; moving to zombies.")
            else:
                self._worker.deleteLater()
            self._worker = None

    @property
    def is_running(self) -> bool:
        return bool(self._worker and self._worker.isRunning())

    def _on_gesture(self, gesture_str: str, x: float, y: float):
        self.gesture.emit(gesture_str, x, y)

        # Map gestures to high-level actions
        mapping = {
            Gesture.CLAP.value:      self.action_open_overlay,
            Gesture.BOTH_PALMS.value: self.action_open_overlay, # optional alias
            Gesture.FIST.value:      self.action_close_overlay,
            Gesture.THUMBS_UP.value: self.action_confirm,
            Gesture.CALL_ME.value:   self.action_cancel,
            Gesture.OPEN_PALM.value: self.action_stop_speaking,
        }
        signal = mapping.get(gesture_str)
        if signal:
            signal.emit()
