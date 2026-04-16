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
import os
import time
import logging
from enum import Enum, auto
from typing import Optional, List, Dict

import numpy as np
from PyQt6.QtCore import QObject, QThread, pyqtSignal, Qt
from PyQt6.QtGui import QImage

from visual.pose_matcher import PoseMatcher
from visual.gesture_manager import SystemGestureManager
from visual.platform_win import disable_efficiency_mode, set_high_precision_timer

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
    MIDDLE_PINCH = "middle_pinch"


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
    is_pinching = pinch_dist < 0.05  # Tighter threshold: more deliberate pinch needed

    # ── Finger extension flags ────────────────────────────────
    thumb_up   = lm[4].y < lm[2].y  # tip above MCP joint (more reliable than PIP)
    index_ext  = _finger_extended(lm, 8, 6)
    mid_ext    = _finger_extended(lm, 12, 10)
    ring_ext   = _finger_extended(lm, 16, 14)
    pinky_ext  = _finger_extended(lm, 20, 18)

    # ── Double Pinch Check ──
    # Priority: Index Pinch (Scroll) > Middle Pinch (Drag/Selection)
    # This prevents 'accidental selection' when you just want to scroll.
    middle_pinch_dist = _dist(lm[4], lm[12])
    is_middle_pinching = middle_pinch_dist < 0.05
    
    if is_pinching and not mid_ext and not ring_ext:
        return Gesture.PINCH_START
    
    if is_middle_pinching and not ring_ext:
        # User is pinching with thumb + middle. 
        # If the index is also near, PINCH_START above would have caught it first.
        return Gesture.MIDDLE_PINCH

    # ── Open palm ─────────────────────────────────────────────
    if index_ext and mid_ext and ring_ext and pinky_ext and thumb_up:
        return Gesture.OPEN_PALM

    # ── Fist (all fingers curled, including thumb check via x-axis) ──
    # Use both y-axis and knuckle-tip distance for more robust detection
    index_curled = lm[8].y > lm[5].y   # tip below MCP
    mid_curled   = lm[12].y > lm[9].y
    ring_curled  = lm[16].y > lm[13].y
    pinky_curled = lm[20].y > lm[17].y
    thumb_curled = _dist(lm[4], lm[9]) < 0.2  # thumb tip near middle knuckle
    if index_curled and mid_curled and ring_curled and pinky_curled and thumb_curled:
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
    """Tracks pinch position over time to calculate scroll deltas and click events."""

    def __init__(self, sensitivity: float = 1800.0):
        self._sensitivity = sensitivity
        self._last_y: Optional[float] = None
        self._pinch_start_time: Optional[float] = None
        self._total_moved_px: float = 0.0

    def begin(self, y: float):
        self._last_y = y
        self._pinch_start_time = time.time()
        self._total_moved_px = 0.0

    def update(self, y: float, sensitivity: float = None) -> float:
        """Returns scroll delta in pixels (negative = scroll up)."""
        if self._last_y is None:
            self._last_y = y
            return 0.0
        sens = sensitivity if sensitivity is not None else self._sensitivity
        delta = (y - self._last_y) * sens
        self._last_y = y
        self._total_moved_px += abs(delta)
        return delta

    def end(self) -> bool:
        """
        Returns True if this was a quick tap (< 350ms) with minimal movement.
        """
        if self._pinch_start_time:
            duration = time.time() - self._pinch_start_time
            moved = self._total_moved_px
            self._last_y = None
            self._pinch_start_time = None
            self._total_moved_px = 0.0
            
            # Treat as click if short duration AND we didn't scroll much
            return duration < 0.25 and moved < 60
        return False

    def reset(self):
        self._last_y = None
        self._pinch_start_time = None
        self._total_moved_px = 0.0
        
    @property
    def total_moved(self) -> float:
        return self._total_moved_px


# ── One Euro Filter ───────────────────────────────────────────────────────────

class _LowPassFilter:
    """Single-pole low-pass filter used by OneEuroFilter."""
    def __init__(self):
        self._value: Optional[float] = None

    def filter(self, x: float, alpha: float) -> float:
        if self._value is None:
            self._value = x
        else:
            self._value = alpha * x + (1.0 - alpha) * self._value
        return self._value

    def last(self) -> Optional[float]:
        return self._value

    def reset(self):
        self._value = None


class OneEuroFilter:
    """
    One Euro Filter — adaptive smoothing filter for noisy pointer input.

    At low speeds: heavy smoothing (reduces jitter when hand is still).
    At high speeds: minimal smoothing (keeps up with fast hand movements).

    Parameters:
        min_cutoff: Smoothing strength at rest. Lower = smoother but laggier. (default 1.0 Hz)
        beta:       Speed coefficient. Higher = less lag during fast movement. (default 0.007)
        d_cutoff:   Derivative smoothing frequency (default 1.0 Hz, rarely needs tuning).
    """
    def __init__(self, min_cutoff: float = 1.0, beta: float = 0.007, d_cutoff: float = 1.0):
        self._min_cutoff = min_cutoff
        self._beta = beta
        self._d_cutoff = d_cutoff
        self._x_filter = _LowPassFilter()
        self._dx_filter = _LowPassFilter()

    def _alpha(self, cutoff: float, dt: float) -> float:
        tau = 1.0 / (2.0 * 3.14159265 * cutoff)
        return 1.0 / (1.0 + tau / max(dt, 1e-6))

    def filter(self, x: float, dt: float) -> float:
        """Apply filter to value x with time delta dt (seconds)."""
        d_alpha = self._alpha(self._d_cutoff, dt)
        prev = self._x_filter.last()
        dx = (x - prev) / max(dt, 1e-6) if prev is not None else 0.0
        edx = self._dx_filter.filter(dx, d_alpha)
        cutoff = self._min_cutoff + self._beta * abs(edx)
        return self._x_filter.filter(x, self._alpha(cutoff, dt))

    def reset(self):
        self._x_filter.reset()
        self._dx_filter.reset()


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
    custom_pose_detected = pyqtSignal(str) # Emits pose name
    # (x, y, is_pressed)
    middle_pinch_move = pyqtSignal(float, float, bool)

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
        # One Euro Filter for pointer smoothing
        # min_cutoff: higher = less lag. 90.0+ is near-instant.
        # beta: higher = adapts faster to motion. 1.5 is very aggressive.
        self._oef_x = OneEuroFilter(min_cutoff=90.0, beta=1.5)
        self._oef_y = OneEuroFilter(min_cutoff=90.0, beta=1.5)
        self._oef_active = False
        self._last_sx, self._last_sy = 0.5, 0.5
        self._scroll_suppressed_until = 0.0
        self._calib_state = 0  # 0=idle, 1=top-left, 2=bottom-right
        self._calib_tl = (0.0, 0.0)
        self._last_preview_time = 0.0
        # Hold-to-trigger: tracks when the current discrete gesture started
        self._hold_gesture: Gesture = Gesture.NONE
        self._hold_start: float = 0.0
        self._hold_fired: bool = False  # ensures we only fire once per hold
        self._pose_matcher = PoseMatcher()
        self._last_raw_pose = None
        self._pose_confirm_count = 0 
        self._last_gesture = Gesture.NONE
        self._last_point_time = 0.0
        self._transition_clicked = False
        self._was_middle_pinching = False
        self._capture_name: Optional[str] = None
        self._capture_buffer: List[List[Dict[str, float]]] = []

    def trigger_calibration(self):
        self._calib_state = 1

    def learn_pose(self, name: str, action: str = "none", params: dict = None):
        """Triggers recording of the current hand shape."""
        self._capture_name = name
        self._capture_action = action
        self._capture_params = params
        self._capture_buffer = []
        logger.info(f"Started learning pose: {name} (Action: {action})")

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

            # Load custom poses
            custom_poses_path = "core/custom_poses.json"
            if os.path.exists(custom_poses_path):
                self._pose_matcher.load_templates(custom_poses_path)

            disable_efficiency_mode()
            set_high_precision_timer(True)
            
            target_period = 0.033  # 30 FPS for liquid smooth performance
            last_proc_time = time.time()
            
            while self._running:
                ok, frame = cap.read()
                if not ok:
                    continue

                now = time.time()
                dt = now - last_proc_time
                if dt < target_period:
                    time.sleep(max(0, target_period - dt - 0.001))
                    continue
                last_proc_time = now

                frame_rgb = cv2.cvtColor(cv2.flip(frame, 1), cv2.COLOR_BGR2RGB)
                h, w, ch = frame_rgb.shape
                image = Image(image_format=ImageFormat.SRGB, data=frame_rgb)
                results = landmarker.detect(image)

                if not results.hand_landmarks:
                    if self._was_pinching:
                        if self._scroll_tracker.end():  # quick tap = click
                            self.click.emit(0.5, 0.5)
                        self._was_pinching = False
                    
                    self._gesture_buffer.clear()
                    self._last_discrete_gesture = Gesture.NONE
                    self._last_raw_pose = None # Reset hysteresis
                    self._pose_confirm_count = 0
                    
                    qimg = QImage(frame_rgb.data, w, h, ch * w, QImage.Format.Format_RGB888).copy()
                    self.frame_processed.emit(qimg)
                    continue

                # Parse first hand for 2D coords (for scrolling/pointing)
                hand = results.hand_landmarks[0]
                
                # 1. Custom Pose Matching with Hysteresis (Confirm over 3 frames)
                raw_pose = self._pose_matcher.match(hand)
                if raw_pose == self._last_raw_pose and raw_pose is not None:
                    self._pose_confirm_count += 1
                else:
                    self._last_raw_pose = raw_pose
                    self._pose_confirm_count = 0
                
                pose_match = raw_pose if self._pose_confirm_count >= 3 else None

                # 2. Built-in Geometric Classification
                gesture = classify_gesture(results.hand_landmarks)

                # 3. Priority Resolution:
                if gesture not in [Gesture.PINCH_START, Gesture.POINT]:
                    if pose_match:
                        gesture = pose_match

                # Active zone boundaries for mapping/viz
                zx = self.settings.get("hand_point_x", 0.1)
                zy = self.settings.get("hand_point_y", 0.1)
                zw = self.settings.get("hand_point_w", 0.8)
                zh = self.settings.get("hand_point_h", 0.8)
                
                ix = hand[8].x  # index tip x
                iy = hand[8].y  # index tip y

                nx = max(0.0, min(1.0, (ix - zx) / max(0.001, zw)))
                ny = max(0.0, min(1.0, (iy - zy) / max(0.001, zh)))

                for h_lms in results.hand_landmarks:
                    for lm in h_lms:
                        jx, jy = int(lm.x * w), int(lm.y * h)
                        cv2.circle(frame_rgb, (jx, jy), 4, (200, 100, 255), -1)
                
                g_display = gesture if isinstance(gesture, str) else gesture.value
                cv2.putText(frame_rgb, f"Gesture: {g_display}", (15, 40),
                            cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2, cv2.LINE_AA)

                if self._capture_name:
                    cv2.putText(frame_rgb, f"RECORDING: {self._capture_name}", (15, 80),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2, cv2.LINE_AA)
                    cv2.putText(frame_rgb, "HOLD STILL...", (15, 110),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 1, cv2.LINE_AA)

                # ── Draw Configured Active Display Zone ──────────────
                rect_x1, rect_y1 = int(zx * w), int(zy * h)
                rect_x2, rect_y2 = int((zx + zw) * w), int((zy + zh) * h)
                
                if self._calib_state == 1:
                    cv2.putText(frame_rgb, "Calibration: Pinch in the TOP-LEFT", (15, 80),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 165, 255), 2, cv2.LINE_AA)
                elif self._calib_state == 2:
                    cv2.rectangle(frame_rgb, (int(self._calib_tl[0]*w), int(self._calib_tl[1]*h)), (int(ix*w), int(iy*h)), (0, 165, 255), 2)
                    cv2.putText(frame_rgb, "Calibration: Pinch in the BOTTOM-RIGHT", (15, 80),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 165, 255), 2, cv2.LINE_AA)
                else:
                    cv2.rectangle(frame_rgb, (rect_x1, rect_y1), (rect_x2, rect_y2), (0, 255, 100), 2)
                
                if now - self._last_preview_time > 0.1:
                    qimg = QImage(frame_rgb.data, w, h, ch * w, QImage.Format.Format_RGB888).copy()
                    if not qimg.isNull():
                        self.frame_processed.emit(qimg)
                    self._last_preview_time = now

                # ── Selection / Drag (Middle Pinch) ──────────────────
                if gesture == Gesture.MIDDLE_PINCH:
                    dt_proc = max(now - last_proc_time, 0.001)
                    if not self._oef_active:
                        self._oef_x.reset(); self._oef_y.reset(); self._oef_active = True
                    sx = self._oef_x.filter(nx, dt_proc)
                    sy = self._oef_y.filter(ny, dt_proc)
                    self._last_sx, self._last_sy = sx, sy
                    
                    # Emit 'is_down=True' continuously; the coordinator will filter 
                    # out redundant OS mouse-down commands.
                    self.middle_pinch_move.emit(sx, sy, True) 
                    self._was_middle_pinching = True
                    continue

                if self._was_middle_pinching:
                    # Release the mouse button
                    self.middle_pinch_move.emit(self._last_sx, self._last_sy, False)
                    self._was_middle_pinching = False

                # ── Calibration ──────────────────────────
                if self._calib_state > 0 and gesture == Gesture.PINCH_START:
                    if self._calib_state == 1:
                        self._calib_tl = (ix, iy)
                        self._calib_state = 2
                        time.sleep(0.5)
                    elif self._calib_state == 2:
                        tl_x, tl_y = self._calib_tl
                        bx, by = max(tl_x, ix), max(tl_y, iy)
                        tx, ty = min(tl_x, ix), min(tl_y, iy)
                        self.settings.update({
                            "hand_point_x": tx, "hand_point_y": ty,
                            "hand_point_w": max(0.1, bx - tx), "hand_point_h": max(0.1, by - ty)
                        })
                        self._calib_state = 0
                        time.sleep(0.5)
                    continue

                # ── Scroll / Click ──────────────────────────────
                if gesture == Gesture.PINCH_START:
                    pinch_y = (hand[4].y + hand[8].y) / 2
                    if not self._was_pinching:
                        self._scroll_tracker.begin(pinch_y)
                        self._was_pinching = True
                        # Click logic simplified: always handle on release
                    else:
                        live_sensitivity = float(self.settings.get("hand_scroll_sensitivity", 2500))
                        delta = self._scroll_tracker.update(pinch_y, sensitivity=live_sensitivity)
                        if self._scroll_tracker.total_moved > 15:
                            if abs(delta) > 0.5: self.scroll.emit(delta)
                    continue

                if self._was_pinching:
                    if self._scroll_tracker.end():
                        # Standard release-to-click. Window is 250ms for snappiness.
                        if (now - self._last_point_time) < 0.35:
                            self.click.emit(self._last_sx, self._last_sy)
                        else:
                            self.click.emit(ix, iy)
                    self._was_pinching = False

                # ── Point ──────────
                if gesture == Gesture.POINT:
                    self._last_point_time = now
                    dt_proc = max(now - last_proc_time, 0.001)
                    if not self._oef_active:
                        self._oef_x.reset(); self._oef_y.reset(); self._oef_active = True
                    sx = self._oef_x.filter(nx, dt_proc)
                    sy = self._oef_y.filter(ny, dt_proc)
                    self._last_sx, self._last_sy = sx, sy
                    self.cursor_move.emit(sx, sy)
                    continue
                else:
                    self._oef_active = False

                # ── Custom Pose Learning ────────────────────────────
                if self._capture_name and results.hand_landmarks:
                    self._capture_buffer.append(results.hand_landmarks[0])
                    if len(self._capture_buffer) >= 20:
                        self._pose_matcher.add_template(self._capture_name, self._capture_buffer[0], self._capture_action, self._capture_params)
                        self._pose_matcher.save_templates("core/custom_poses.json")
                        self._capture_name = None; self._capture_buffer = []

                # ── Discrete gestures ────────────────────────
                if gesture not in (Gesture.NONE, Gesture.POINT, Gesture.PINCH_START):
                    hold_duration = float(self.settings.get("gesture_hold_seconds", 2.0))
                    if gesture != self._hold_gesture:
                        self._hold_gesture = gesture; self._hold_start = now; self._hold_fired = False
                    elif not self._hold_fired:
                        if (now - self._hold_start) >= hold_duration:
                            gname = gesture if isinstance(gesture, str) else gesture.value
                            self.gesture_detected.emit(gname, nx, ny)
                            self._hold_fired = True
                else:
                    if gesture != self._hold_gesture:
                        self._hold_gesture = gesture; self._hold_fired = False
                
                self._last_gesture = gesture

        finally:
            cap.release()
            if landmarker:
                landmarker.close()
            set_high_precision_timer(False)
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
    custom_gesture       = pyqtSignal(str, str, dict) # name, action, params
    frame_processed      = pyqtSignal(object)
    # Selection/Drag: (x, y, is_down)
    middle_pinch_move    = pyqtSignal(float, float, bool)

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self._sys_manager = SystemGestureManager()
        self._worker: Optional[HandTrackingWorker] = None

    def reload_system_gestures(self):
        self._sys_manager.load()
        logger.info("HandTracker: Reloaded system gesture mappings.")

    def start(self, camera_index: int = 0):
        if self._worker:
            if self._worker.isRunning():
                return
            self._worker.deleteLater()
            
        self._worker = HandTrackingWorker(self.settings, camera_index, self)
        self._worker.gesture_detected.connect(self._on_gesture)
        
        # Use DirectConnection for performance-critical signals to bypass UI thread throttling
        self._worker.scroll.connect(self.scroll, Qt.ConnectionType.DirectConnection)
        self._worker.cursor_move.connect(self.cursor_move, Qt.ConnectionType.DirectConnection)
        self._worker.click.connect(self.click, Qt.ConnectionType.DirectConnection)
        self._worker.middle_pinch_move.connect(self.middle_pinch_move, Qt.ConnectionType.DirectConnection)
        self._worker.error.connect(self.error)
        self._worker.frame_processed.connect(self.frame_processed)
        self._worker.start(QThread.Priority.HighPriority)
        logger.info(f"HandTracker: Worker started (Priority: High)")

    def start_calibration(self):
        if self._worker:
            self._worker.trigger_calibration()

    def learn_pose(self, name: str, action: str = "none", params: dict = None):
        if self._worker:
            self._worker.learn_pose(name, action, params)

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
        
        # 1. Check System Gesture Mapping
        sys_data = self._sys_manager.get_action_for_gesture(gesture_str)
        if sys_data and sys_data.get("enabled", True):
            action = sys_data.get("action", "none")
            params = sys_data.get("params", {})
            
            # Map system actions to high-level signals
            if action == "toggle_overlay":
                self.action_open_overlay.emit()
            elif action == "close_overlay":
                self.action_close_overlay.emit()
            elif action == "confirm":
                self.action_confirm.emit()
            elif action == "cancel":
                self.action_cancel.emit()
            elif action == "stop_speaking":
                self.action_stop_speaking.emit()
            elif action == "launch_app":
                self.custom_gesture.emit(gesture_str, action, params)
            
            # If we handled it as a system gesture, we're done
            if action != "none":
                return

        # 2. Check Custom Pose Library (only if no system action was defined/enabled)
        if self._worker and self._worker.isRunning():
            pose_data = self._worker._pose_matcher.get_action_for_pose(gesture_str)
            if pose_data:
                action = pose_data.get("action", "none")
                params = pose_data.get("params", {})
                self.custom_gesture.emit(gesture_str, action, params)
