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
import math
import random
import logging
from enum import Enum, auto
from typing import Optional, List, Dict
from collections import deque, Counter

import numpy as np
from PyQt6.QtCore import QObject, QThread, pyqtSignal, Qt
from PyQt6.QtGui import QImage

from visual.pose_matcher import PoseMatcher
from visual.gesture_manager import SystemGestureManager
from visual.platform_win import disable_efficiency_mode, set_high_precision_timer, set_high_priority


logger = logging.getLogger(__name__)


def detect_available_cameras(max_cameras: int = 5) -> list[int]:
    """Returns list of available camera indices."""
    import cv2
    available = []
    for i in range(max_cameras):
        cap = cv2.VideoCapture(i)
        if cap.isOpened():
            available.append(i)
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


class HandState:
    """Discrete state tracker for a single hand (Left or Right)"""
    def __init__(self):
        self.gesture_buffer = deque(maxlen=5)
        self.last_raw_pose = None
        self.pose_confirm_count = 0
        self.hold_gesture = Gesture.NONE
        self.hold_fired = False
        self.last_discrete_gesture = Gesture.NONE
        
        # Per-hand persistence
        self.last_landmarks = None
        self.last_seen_time = 0.0
        
        # Visual FX state
        self.trail = deque(maxlen=20)   # Primary index trail
        # Secondary trails for Thumb (4), Middle (12), Ring (16), Pinky (20)
        self.multi_trails = {i: deque(maxlen=20) for i in [4, 12, 16, 20]}
        self.skeleton_trail = deque(maxlen=12) # Full hand ghosts for Deep Overload
        self.pulse_start = 0.0          # time a pulse was triggered (0 = none)
        self.pulse_radius = 0           # current drawn radius

    def reset(self):
        self.gesture_buffer.clear()
        self.last_raw_pose = None
        self.pose_confirm_count = 0
        self.hold_gesture = Gesture.NONE
        self.hold_start = 0.0
        self.hold_fired = False
        self.last_discrete_gesture = Gesture.NONE
        self.last_landmarks = None
        self.last_seen_time = 0.0
        self.trail.clear()
        for t in self.multi_trails.values(): t.clear()
        self.skeleton_trail.clear()
        self.pulse_start = 0.0
        self.pulse_radius = 0


# ── Worker thread ─────────────────────────────────────────────────────────────

class HandTrackingWorker(QThread):
    # (gesture_name, x_norm, y_norm, hand_side)
    gesture_detected = pyqtSignal(str, float, float, str)
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
    # (dx, dy, is_pressed)
    middle_pinch_rel_move = pyqtSignal(float, float, bool)
    # (dx, dy) - for trackpad-style relative movement
    cursor_rel_move = pyqtSignal(float, float)

    def __init__(self, settings, camera_index: int = 0, parent=None):
        super().__init__(parent)
        self.settings     = settings
        self.camera_index = camera_index
        self._running     = False
        self._scroll_tracker = PinchScrollTracker(
            sensitivity=float(settings.get("hand_scroll_sensitivity", 1800))
        )
        self._was_pinching   = False
        
        self._hand_states = {
            "Left": HandState(),
            "Right": HandState()
        }
        self._buffer_size_requirement = 5
        self._fps_history = deque(maxlen=30)    # Rolling FPS tracker
        self._snap_coords = (0.5, 0.5)          # Saved coords for pinch-snapping
        self._tracking_paused = False           # Toggled by System Gesture
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
        # Hold-to-trigger is now in HandState
        self._pose_matcher = PoseMatcher()
        self._last_point_time = 0.0
        self._transition_clicked = False
        self._was_middle_pinching = False
        self._capture_name: Optional[str] = None
        self._capture_buffer: List[List[Dict[str, float]]] = []
        
        # Stability & Persistence
        self._last_results = None
        self._last_results_time = 0.0
        # Default 100ms (0.1s); can be tuned in UI
        self._persistence_threshold = float(self.settings.get("hand_persistence_seconds", 0.1))
        self._is_point_anchored = False
        self._synergy_start_time = 0.0
        self._synergy_trail = deque(maxlen=30)
        self._last_synergy_dur = 0.0
        self._explosion_start = 0.0
        self._explosion_origin = (0, 0)
        self._overload_end = 0.0
        
        # ── Spatial Sketch Mode ──
        self._sketch_mode = False       # Toggled by Left Fist
        self._drawing_active = False    # Controlled by Right Pinch
        self._drawings = []             # List of {"color": (B,G,R), "pts": [(x,y), ...]}
        self._active_stroke = []        # Points in current stroke
        self._sketch_colors = [
            ("Red", (255, 50, 50)),
            ("Green", (50, 255, 50)),
            ("Blue", (50, 50, 255)),
            ("Yellow", (255, 255, 50)),
            ("Purple", (255, 50, 255)),
            ("Black", (20, 20, 20))
        ]
        self._color_idx = 0
        self._last_toggle_time = 0.0    # Debounce for mode/palette
        self._calib_state = 0
        # Rendering Caches
        self._v_shadow_cache = None     # (mask, res_w, res_h)
        self._v_ripple_cache = None     # (mask, res_w, res_h)

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

        # Set target FPS on camera hardware (driver level)
        target_fps = int(self.settings.get("tracking_fps", 30))
        cap.set(cv2.CAP_PROP_FPS, target_fps)

        # Log camera properties
        logger.debug(f"Camera {self.camera_index} properties:")
        logger.debug(f"  Resolution: {int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))}x{int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))}")
        logger.debug(f"  Requested FPS: {target_fps} (Hardware Actual: {cap.get(cv2.CAP_PROP_FPS)})")

        landmarker = None
        try:
            options = HandLandmarkerOptions(
                base_options=mp.tasks.BaseOptions(model_asset_path="models/hand_landmarker.task"),
                running_mode=RunningMode.VIDEO,
                num_hands=2,
                min_hand_detection_confidence=0.50,
                min_hand_presence_confidence=0.50,
                min_tracking_confidence=0.50,
            )
            landmarker = HandLandmarker.create_from_options(options)

            # Load custom poses
            custom_poses_path = "core/custom_poses.json"
            if os.path.exists(custom_poses_path):
                self._pose_matcher.load_templates(custom_poses_path)

            disable_efficiency_mode()
            set_high_precision_timer(True)
            set_high_priority()
            
            # FPS and Timing State
            last_proc_time = time.time()
            fps_val = 0.0
            
            while self._running:
                # Dynamic FPS Limit from Settings
                target_fps = int(self.settings.get("tracking_fps", 30))
                target_period = 1.0 / target_fps
                
                # Fetch persistence threshold dynamically
                self._persistence_threshold = float(self.settings.get("hand_persistence_seconds", 0.1))

                # ── Timing & FPS ──
                now = time.time()
                dt = now - last_proc_time
                if dt < target_period:
                    time.sleep(max(0, target_period - dt - 0.001))
                    continue
                
                # Real processing FPS (not just target)
                proc_dt = now - last_proc_time
                if proc_dt > 0:
                    self._fps_history.append(1.0 / proc_dt)
                    fps_val = sum(self._fps_history) / len(self._fps_history)
                last_proc_time = now

                ok, frame = cap.read()
                if not ok: continue
                
                frame_rgb = cv2.cvtColor(cv2.flip(frame, 1), cv2.COLOR_BGR2RGB)
                h, w, ch = frame_rgb.shape
                
                # Draw FPS — frosted pill, top-right
                fps_label = f"{int(fps_val):>3} fps"
                _font, _sc, _th = cv2.FONT_HERSHEY_SIMPLEX, 0.46, 1
                (fw, fh), _bl = cv2.getTextSize(fps_label, _font, _sc, _th)
                fx, fy = w - fw - 18, 12
                # Frosted background via local overlay
                hud_x1, hud_y1, hud_x2, hud_y2 = fx - 8, fy, fx + fw + 8, fy + fh + 10
                sub = frame_rgb[hud_y1:hud_y2, hud_x1:hud_x2]
                rect = sub.copy()
                cv2.rectangle(rect, (0,0), (hud_x2-hud_x1, hud_y2-hud_y1), (18, 20, 25), -1)
                cv2.addWeighted(rect, 0.5, sub, 0.5, 0, sub)
                cv2.putText(frame_rgb, fps_label, (fx, fy + fh + 3),
                            _font, _sc, (220, 230, 240), _th, cv2.LINE_AA)

                h, w, ch = frame_rgb.shape
                image = Image(image_format=ImageFormat.SRGB, data=frame_rgb)
                results = landmarker.detect_for_video(image, int(now * 1000))

                # Identify currently detected sides
                active_hands = {}
                if results.hand_landmarks:
                    for i, lm in enumerate(results.hand_landmarks):
                        try:
                            mp_side = results.handedness[i][0].category_name
                            # Invert due to camera mirroring
                            side = "Left" if mp_side == "Right" else "Right"
                        except:
                            side = "Right"
                            
                        # Prevent duplicate sides from destroying the second hand
                        if side in active_hands:
                            side = "Right" if side == "Left" else "Left"
                            
                        active_hands[side] = lm
                
                # Update HandStates with detected hands
                for side, lm in active_hands.items():
                    state = self._hand_states[side]
                    state.last_landmarks = lm
                    state.last_seen_time = now
                
                # Check for ghosts for missing hands
                processed_hands = []
                for side, state in self._hand_states.items():
                    lm = active_hands.get(side)
                    is_ghost = False
                    
                    if not lm and state.last_landmarks is not None:
                        # Ghost candidate: check if any real hand is currently 'occupying' this space
                        # (prevents handedness-flips from creating overlapping red/blue ghosts)
                        too_close_to_real = False
                        for r_side, r_lm in active_hands.items():
                            # Check distance between palm (index 0) of ghost and real hands
                            dist = ((r_lm[0].x - state.last_landmarks[0].x)**2 + 
                                    (r_lm[0].y - state.last_landmarks[0].y)**2)**0.5
                            if dist < 0.12: # suppress if within 12% of screen width
                                too_close_to_real = True
                                break

                        if not too_close_to_real and (now - state.last_seen_time) < self._persistence_threshold:
                            lm = state.last_landmarks
                            is_ghost = True
                        else:
                            state.reset()
                    
                    if lm:
                        processed_hands.append((side, lm, is_ghost))

                if not processed_hands:
                    if self._was_pinching:
                        if self._scroll_tracker.end() and not self._tracking_paused:  # quick tap = click
                            self.click.emit(self._last_sx, self._last_sy)
                        self._was_pinching = False
                    
                    self._oef_active = False
                    self._is_point_anchored = False
                    
                    qimg = QImage(frame_rgb.data, w, h, ch * w, QImage.Format.Format_RGB888).copy()
                    self.frame_processed.emit(qimg)
                    continue

                # ── Energy Synergy & Proximity ──
                synergy_active = False
                if len(processed_hands) == 2:
                    # Check index tip proximity
                    h1_lms = processed_hands[0][1]
                    h2_lms = processed_hands[1][1]
                    dist_tips = ((h1_lms[8].x - h2_lms[8].x)**2 + (h1_lms[8].y - h2_lms[8].y)**2)**0.5
                    if dist_tips < 0.1: # 10% screen width
                        # Block fusion if in post-explosion Overload, if in Sketch Mode, or if trails are disabled
                        is_overload = now < self._overload_end
                        fx_enabled = self.settings.get("hand_fx_trails", True)
                        is_sketch = self._sketch_mode
                        if not is_overload and not is_sketch and fx_enabled:
                            synergy_active = True
                
                if synergy_active:
                    if self._synergy_start_time == 0.0:
                        self._synergy_start_time = now
                else:
                    self._synergy_start_time = 0.0
                
                synergy_dur = (now - self._synergy_start_time) if self._synergy_start_time > 0 else 0
                
                # Check for Release Explosion Trigger
                if synergy_dur == 0 and self._last_synergy_dur > 5.0:
                    if self._synergy_trail:
                        lx, ly, _ = self._synergy_trail[-1]
                        self._explosion_start = now
                        self._explosion_origin = (lx, ly)
                        self._overload_end = now + 9.0 # 3s Skel + 3s Tips + 3s Decay
                self._last_synergy_dur = synergy_dur

                # Growth: Logarithmic (starts at 0.5x, caps at 1.5x)
                synergy_growth = 0.5 + min(math.log1p(synergy_dur * 0.8) * 0.6, 1.0) if synergy_dur > 0 else 1.0
                # Pulse: slower, rhythmic beat
                synergy_pulse = (math.sin(now * 6.0) + 1.0) / 2.0 if synergy_dur > 0 else 0.0

                # Midpoint calculation for Fusion
                fused_lms = None
                if synergy_dur > 0 and len(processed_hands) == 2:
                    fused_lms = []
                    h1 = processed_hands[0][1]
                    h2 = processed_hands[1][1]
                    for idx in range(len(h1)):
                        mx = (h1[idx].x + h2[idx].x) / 2
                        my = (h1[idx].y + h2[idx].y) / 2
                        fused_lms.append(type('MockLM', (object,), {'x': mx, 'y': my, 'z': 0.0}))
                    
                    # Track fusion trail (tip 8)
                    self._synergy_trail.append((int(fused_lms[8].x * w), int(fused_lms[8].y * h), now))
                else:
                    self._synergy_trail.clear()

                # (Keep global UI variables for later drawing)
                last_ix, last_iy = 0.5, 0.5 
                global_gesture = None
                # Allow ghosts to participate in global gestures for stability (e.g. BOTH_PALMS)
                raw_lms = [h[1] for h in processed_hands] 
                if len(raw_lms) == 2:
                    global_gesture = classify_gesture(raw_lms)
                    if global_gesture not in [Gesture.CLAP, Gesture.BOTH_PALMS]:
                        global_gesture = None

                for i, (side, hand, is_ghost) in enumerate(processed_hands):
                    state = self._hand_states.get(side)
                    if not state:
                        continue
                    
                    # 1. Custom Pose Matching with Hysteresis
                    raw_pose = self._pose_matcher.match(hand)
                    if raw_pose == state.last_raw_pose and raw_pose is not None:
                        state.pose_confirm_count += 1
                    else:
                        state.last_raw_pose = raw_pose
                        state.pose_confirm_count = 0
                    
                    pose_match = raw_pose if state.pose_confirm_count >= 3 else None

                    # 2. Built-in Geometric Classification
                    raw_gesture = classify_gesture([hand]) if not global_gesture else global_gesture

                    # 3. Priority Resolution:
                    final_raw = raw_gesture
                    if raw_gesture not in [Gesture.PINCH_START, Gesture.POINT] and pose_match:
                        final_raw = pose_match
                    
                    # ── SKETCH MODE CONTROLS ──
                    if self.settings.get("hand_fx_trails", True):
                        # Toggle Mode: Left Fist
                        if side == "Left" and final_raw == Gesture.FIST:
                            if now - self._last_toggle_time > 1.2:
                                self._sketch_mode = not self._sketch_mode
                                self._last_toggle_time = now
                                self._palette_open = False
                                logger.info(f"Sketch Mode: {'ON' if self._sketch_mode else 'OFF'}")
                        
                        if self._sketch_mode:
                            # Clear Workspace: Left Pinch
                            if side == "Left" and final_raw == Gesture.PINCH_START:
                                self._drawings.clear()
                                self._active_stroke = []
                            # Cycle Color: Left Victory
                            if side == "Left" and final_raw == Gesture.VICTORY:
                                if now - self._last_toggle_time > 0.8:
                                    self._color_idx = (self._color_idx + 1) % len(self._sketch_colors)
                                    self._last_toggle_time = now
                                    logger.info(f"Sketch Color: {self._sketch_colors[self._color_idx][0]}")

                    # 4. Consensus Voting (Majority Vote over 5 frames)
                    state.gesture_buffer.append(final_raw)
                    if len(state.gesture_buffer) >= self._buffer_size_requirement:
                        gesture = Counter(state.gesture_buffer).most_common(1)[0][0]
                    else:
                        gesture = final_raw

                    # Active zone boundaries for mapping/viz
                    zx = self.settings.get("hand_point_x", 0.1)
                    zy = self.settings.get("hand_point_y", 0.1)
                    zw = self.settings.get("hand_point_w", 0.8)
                    zh = self.settings.get("hand_point_h", 0.8)
                    
                    ix = hand[8].x  # index tip x
                    iy = hand[8].y  # index tip y

                    is_rel_mode = self.settings.get("hand_relative_mode", False)
                    if is_rel_mode:
                        # In Trackpad Mode, we use the FULL frame to calculate deltas
                        nx, ny = ix, iy
                    else:
                        # In Absolute Mode, we map to the calibrated Active Zone
                        nx = max(0.0, min(1.0, (ix - zx) / max(0.001, zw)))
                        ny = max(0.0, min(1.0, (iy - zy) / max(0.001, zh)))

                    # 5. Smooth coordinates (Primary tracking hand)
                    dt_proc = max(now - last_proc_time, 0.001)
                    if side == "Right":
                        if not self._oef_active:
                            self._oef_x.reset(); self._oef_y.reset(); self._oef_active = True
                        sx = self._oef_x.filter(nx, dt_proc)
                        sy = self._oef_y.filter(ny, dt_proc)
                    else:
                        sx, sy = nx, ny  # Fallback for left hand (not used for cursor)

                    if not is_ghost:
                        # ── Base landmarks (Transparent) ─────────────────────
                        # HIDE individual landmarks if synergy is active (Fusion) OR during Overload
                        is_overload = now < self._overload_end
                        if synergy_dur <= 0 and not is_overload:
                            if self._sketch_mode and side == "Right":
                                base_color = self._sketch_colors[self._color_idx][1]
                            else:
                                base_color = (220, 55, 55) if side == "Right" else (55, 100, 220)
                            overlay = frame_rgb.copy()
                            for lm in hand:
                                # Skip drawing landmarks if they are extremely close to the cursor/index to prevent "double markers"
                                jx, jy = int(lm.x * w), int(lm.y * h)
                                cv2.circle(overlay, (jx, jy), 5, tuple(int(c * 0.3) for c in base_color), -1, cv2.LINE_AA)
                                cv2.circle(overlay, (jx, jy), 2, base_color, -1, cv2.LINE_AA)
                            cv2.addWeighted(overlay, 0.4, frame_rgb, 0.6, 0, frame_rgb)
                        
                        # ── PLASMA ORB V4 (Advanced Blending) ───────────────
                        if synergy_dur > 0 and side == "Right" and fused_lms:
                            avg_fx = sum(lm.x for lm in fused_lms) / len(fused_lms)
                            avg_fy = sum(lm.y for lm in fused_lms) / len(fused_lms)
                            cx, cy = int(avg_fx * w), int(avg_fy * h)
                            
                            radius = int(25 * synergy_growth + (synergy_pulse * 12))
                            
                            # 1. Create a Blur ROI for the soft atmosphere
                            roi_size = int(radius * 4.5)
                            rx1, ry1 = max(0, cx - roi_size // 2), max(0, cy - roi_size // 2)
                            rx2, ry2 = min(w, cx + roi_size // 2), min(h, cy + roi_size // 2)
                            
                            if (rx2 - rx1) > 10 and (ry2 - ry1) > 10:
                                orb_roi = frame_rgb[ry1:ry2, rx1:rx2].copy()
                                glow_mask = np.zeros_like(orb_roi)
                                local_cx, local_cy = cx - rx1, cy - ry1
                                
                                # Atmosphere (Deep Purple)
                                cv2.circle(glow_mask, (local_cx, local_cy), int(radius * 2.0), (140, 40, 180), -1, cv2.LINE_AA)
                                cv2.circle(glow_mask, (local_cx, local_cy), int(radius * 1.4), (200, 60, 240), -1, cv2.LINE_AA)
                                
                                # Soften the mask
                                blur_k = int(radius * 0.8) | 1 # Must be odd
                                glow_mask = cv2.GaussianBlur(glow_mask, (blur_k, blur_k), 0)
                                cv2.addWeighted(orb_roi, 1.0, glow_mask, 0.6, 0, orb_roi)
                                
                                # 2. Hot Core (Layered white for "Bloom")
                                cv2.circle(orb_roi, (local_cx, local_cy), int(radius * 0.7), (240, 150, 255), -1, cv2.LINE_AA)
                                core_r = int(radius * (0.35 + synergy_pulse * 0.2))
                                cv2.circle(orb_roi, (local_cx, local_cy), int(core_r * 1.4), (255, 200, 255), -1, cv2.LINE_AA)
                                cv2.circle(orb_roi, (local_cx, local_cy), core_r, (255, 255, 255), -1, cv2.LINE_AA)
                                
                                # 3. Plasma Arcs (Lightning)
                                # Generate 3-4 wiggly lines from core to edge
                                num_arcs = 3 + int(synergy_pulse * 2)
                                for _ in range(num_arcs):
                                    arc_pts = []
                                    angle = random.uniform(0, 2 * math.pi)
                                    length = radius * random.uniform(1.2, 1.8)
                                    segments = 5
                                    for seg in range(segments + 1):
                                        seg_r = (seg / segments) * length
                                        # Add noise/wiggle
                                        wiggle = radius * 0.2 * (1.0 - (seg/segments)) if seg < segments else 0
                                        ax = local_cx + int(math.cos(angle) * seg_r) + random.randint(-int(wiggle+1), int(wiggle+1))
                                        ay = local_cy + int(math.sin(angle) * seg_r) + random.randint(-int(wiggle+1), int(wiggle+1))
                                        arc_pts.append([ax, ay])
                                    
                                    pts_np = np.array(arc_pts, np.int32).reshape((-1, 1, 2))
                                    # Electric glow pass
                                    cv2.polylines(orb_roi, [pts_np], False, (255, 220, 255), 2, cv2.LINE_AA)
                                    cv2.polylines(orb_roi, [pts_np], False, (255, 255, 255), 1, cv2.LINE_AA)

                                frame_rgb[ry1:ry2, rx1:rx2] = orb_roi

                            # Global Screen Ripple (Enhanced Impact - Vignette Style)
                            if synergy_dur > 3.5 and synergy_pulse > 0.85:
                                # Optimized Ripple: Use cache if resolution matches
                                if self._v_ripple_cache is None or self._v_ripple_cache[1] != w or self._v_ripple_cache[2] != h:
                                    ripple_mask = np.zeros((h, w, 3), dtype=np.uint8)
                                    cv2.rectangle(ripple_mask, (0,0), (w,h), (180, 160, 200), -1)
                                    cutout_r = int(radius * 1.5)
                                    cv2.circle(ripple_mask, (cx, cy), cutout_r, (0, 0, 0), -1, cv2.LINE_AA)
                                    ripple_mask = cv2.GaussianBlur(ripple_mask, (w//5|1, h//5|1), 0)
                                    self._v_ripple_cache = (ripple_mask, w, h)
                                
                                # Additive blend (Light vignette)
                                cv2.addWeighted(frame_rgb, 1.0, self._v_ripple_cache[0], 0.4, 0, frame_rgb)

                                shock_r = int(((now * 2.0) % 1.0) * w * 1.5)
                                cv2.circle(frame_rgb, (cx, cy), shock_r, (255, 255, 255), 2, cv2.LINE_AA)

                        g_display = gesture if isinstance(gesture, str) else gesture.value
                        label = f"{side[0].upper()}  {g_display}"
                        l_font, l_sc, l_th = cv2.FONT_HERSHEY_SIMPLEX, 0.48, 1
                        (tw, th), baseline = cv2.getTextSize(label, l_font, l_sc, l_th)
                        lx, ly = 18, 12
                        if i > 0: ly += 30 # Offset subsequent hand labels vertically
                        
                        # Frosted background
                        hx1, hy1, hx2, hy2 = lx - 8, ly, lx + tw + 8, ly + th + 10
                        sub_l = frame_rgb[hy1:hy2, hx1:hx2]
                        rect_l = sub_l.copy()
                        cv2.rectangle(rect_l, (0,0), (hx2-hx1, hy2-hy1), (18, 20, 25), -1)
                        cv2.addWeighted(rect_l, 0.5, sub_l, 0.5, 0, sub_l)
                        
                        cv2.putText(frame_rgb, label, (lx, ly + th + 3),
                                    l_font, l_sc, (220, 230, 240), l_th, cv2.LINE_AA)

                        tip_px = int(hand[8].x * w)
                        tip_py = int(hand[8].y * h)

                        # ── PARTICLE TRAILS ──────────────
                        if self.settings.get("hand_fx_trails", True):
                            # In Fusion mode, we use a separate centralized trail logic
                            if synergy_dur > 0:
                                # We only draw this ONCE when on the Right hand pass to avoid duplicates
                                if side == "Right" and len(self._synergy_trail) > 1:
                                    s_pts = list(self._synergy_trail)
                                    overlay_t = frame_rgb.copy()
                                    tr = (240, 80, 255)
                                    t_scale = synergy_growth * (1.0 + synergy_pulse * 0.15)
                                    brightness_mod = 0.8 + (synergy_pulse * 0.2)
                                    
                                    for ti in range(1, len(s_pts)):
                                        age = now - s_pts[ti][2]
                                        if age > 0.6: continue
                                        alpha = max(0.0, 1.0 - age / 0.6)
                                        p1, p2 = (s_pts[ti-1][0], s_pts[ti-1][1]), (s_pts[ti][0], s_pts[ti][1])
                                        
                                        # Passes on overlay
                                        c1 = tuple(int(c * alpha * 0.25) for c in tr)
                                        cv2.line(overlay_t, p1, p2, c1, max(1, int(20 * t_scale * alpha)), cv2.LINE_AA)
                                        c2 = tuple(int(c * alpha * 0.60 * brightness_mod) for c in tr)
                                        cv2.line(overlay_t, p1, p2, c2, max(1, int(10 * t_scale * alpha)), cv2.LINE_AA)
                                        c3 = tuple(int(min(255, c * brightness_mod * 1.5)) for c in tr)
                                        cv2.line(overlay_t, p1, p2, c3, max(1, int(4 * t_scale * alpha)), cv2.LINE_AA)
                                        if synergy_pulse > 0.6:
                                            cv2.line(overlay_t, p1, p2, (255, 200, 255), 1, cv2.LINE_AA)
                                    
                                    cv2.addWeighted(overlay_t, 0.5, frame_rgb, 0.5, 0, frame_rgb)
                            else:
                                state.trail.append((tip_px, tip_py, now))
                                pts = list(state.trail)
                                tr = (220, 55, 55) if side == "Right" else (55, 100, 220)
                                
                                # ── STANDARD TRAIL (SUPPRESSED DURING OVERLOAD) ──
                                is_overload = now < self._overload_end
                                if not is_overload:
                                    overlay_st = frame_rgb.copy()
                                    for ti in range(1, len(pts)):
                                        age = now - pts[ti][2]
                                        if age > 0.55: continue
                                        alpha = max(0.0, 1.0 - age / 0.55)
                                        p1, p2 = (pts[ti-1][0], pts[ti-1][1]), (pts[ti][0], pts[ti][1])
                                        cv2.line(overlay_st, p1, p2, tuple(int(c * alpha * 0.25) for c in tr), max(1, int(15 * alpha)), cv2.LINE_AA)
                                        cv2.line(overlay_st, p1, p2, tuple(int(c * alpha) for c in tr), max(1, int(3 * alpha)), cv2.LINE_AA)
                                    cv2.addWeighted(overlay_st, 0.5, frame_rgb, 0.5, 0, frame_rgb)
                                
                                # ── POST-EXPLOSION OVERLOAD (Deep Lifecycle) ──────
                                is_overload = now < self._overload_end
                                if is_overload:
                                    time_left = self._overload_end - now # 9.0 -> 0.0
                                    overlay_ol = frame_rgb.copy()
                                    target_tr = (220, 55, 55) if side == "Right" else (55, 100, 220)
                                    purple_tr = (240, 80, 255)
                                    
                                    # PHASE 1: MASSIVE ENERGY VOLUME (Convex Hull + Blur)
                                    if time_left > 5.5:
                                        skel_pts = [(int(lm.x * w), int(lm.y * h)) for lm in hand]
                                        state.skeleton_trail.append((skel_pts, now))
                                        p1_fade = min(1.0, max(0.0, (time_left - 5.5) / 1.0))
                                        
                                        ghosts = list(state.skeleton_trail)
                                        # Dedicated overlay for smoky volume
                                        vol_overlay = np.zeros_like(frame_rgb)
                                        vibrant_p = (255, 0, 255)
                                        
                                        for gi in range(len(ghosts)):
                                            g_pts, g_time = ghosts[gi]
                                            g_age = now - g_time
                                            if g_age > 0.4: continue
                                            g_alpha = max(0.0, (1.0 - g_age / 0.4) * p1_fade)
                                            
                                            # 1. Massive Hull Volume (Brighter & More Opaque)
                                            hull = cv2.convexHull(np.array(g_pts, np.int32))
                                            # Increased opacity (0.5 instead of 0.2)
                                            cv2.fillPoly(vol_overlay, [hull], tuple(int(c * g_alpha * 0.5) for c in vibrant_p))
                                            cv2.polylines(vol_overlay, [hull], True, tuple(int(c * g_alpha * 0.7) for c in vibrant_p), 3, cv2.LINE_AA)
                                            
                                            # 2. Spectral Skeleton (Vibrant Detail)
                                            connections = [
                                                (0,1), (1,2), (2,3), (3,4), # Thumb
                                                (0,5), (5,6), (6,7), (7,8), # Index
                                                (0,9), (9,10), (10,11), (11,12), # Middle
                                                (0,13), (13,14), (14,15), (15,16), # Ring
                                                (0,17), (17,18), (18,19), (19,20), # Pinky
                                                (5,9), (9,13), (13,17) # Knuckles
                                            ]
                                            # Consistent Vibrant Purple (vibrant_p)
                                            for p1_i, p2_i in connections:
                                                cv2.line(vol_overlay, g_pts[p1_i], g_pts[p2_i], tuple(int(c * g_alpha * 0.5) for c in vibrant_p), 2, cv2.LINE_AA)
                                        
                                        # Apply smoky blur to the volume
                                        vol_overlay = cv2.GaussianBlur(vol_overlay, (21, 21), 0)
                                        cv2.addWeighted(frame_rgb, 1.0, vol_overlay, 0.85, 0, frame_rgb)
                                    
                                    # PHASE 2 & 3: THICKER TIP TRAILS
                                    if time_left < 6.5:
                                        tip_fade = min(1.0, max(0.0, 1.0 - (time_left - 5.5) / 1.0))
                                        morph = 1.0
                                        if time_left < 3.0: morph = time_left / 3.0
                                        
                                        current_tr = (
                                            int(240 * morph + target_tr[0] * (1-morph)),
                                            int(80  * morph + target_tr[1] * (1-morph)),
                                            int(255 * morph + target_tr[2] * (1-morph))
                                        )
                                        
                                        # 5 Finger Tips (Thicker trails with dynamic decay)
                                        for t_idx in [4, 8, 12, 16, 20]:
                                            # Fade extra fingers away (4, 12, 16, 20)
                                            extra_fade = 1.0
                                            if t_idx != 8 and time_left < 3.0:
                                                extra_fade = time_left / 3.0
                                            
                                            tip_lm = hand[t_idx]
                                            t_px, t_py = int(tip_lm.x * w), int(tip_lm.y * h)
                                            if t_idx == 8:
                                                f_pts = list(state.trail)
                                            else:
                                                state.multi_trails[t_idx].append((t_px, t_py, now))
                                                f_pts = list(state.multi_trails[t_idx])
                                            
                                            # Thickness Morph: 15px -> 3px
                                            base_w = 15
                                            if time_left < 3.0:
                                                base_w = 3 + (12 * (time_left / 3.0))
                                            
                                            for ti in range(1, len(f_pts)):
                                                p1, p2 = (f_pts[ti-1][0], f_pts[ti-1][1]), (f_pts[ti][0], f_pts[ti][1])
                                                age = now - f_pts[ti][2]
                                                if age > 0.45: continue
                                                f_alpha = max(0.0, (1.0 - age / 0.45) * tip_fade * extra_fade)
                                                if f_alpha < 0.02: continue
                                                
                                                # Thick Glowy Trails (Morphing thickness)
                                                cv2.line(frame_rgb, p1, p2, current_tr, max(1, int(base_w * f_alpha)), cv2.LINE_AA)
                                                # Only draw core if thickness permits
                                                if base_w > 6:
                                                    cv2.line(frame_rgb, p1, p2, (255, 255, 255), max(1, int(4 * (base_w/15.0) * f_alpha)), cv2.LINE_AA)
                                        
                                    # Phase out Global Overlay Weight: 0.45 -> 0.0 in final second
                                    ol_weight = 0.45
                                    if time_left < 1.0:
                                        ol_weight = 0.45 * (time_left / 1.0)
                                    if ol_weight > 0.01:
                                        cv2.addWeighted(overlay_ol, ol_weight, frame_rgb, 1.0 - ol_weight, 0, frame_rgb)

                        # ── FOCUS PULSE ───────────────
                        if self.settings.get("hand_fx_pulse", True):
                            # Trigger a pulse on pinch start (transition into PINCH_START)
                            if gesture == Gesture.PINCH_START and state.pulse_start == 0.0:
                                state.pulse_start = now
                            elif gesture != Gesture.PINCH_START:
                                state.pulse_start = 0.0

                            if state.pulse_start > 0.0:
                                elapsed = now - state.pulse_start
                                max_r = 55
                                r = int(max_r * min(elapsed / 0.5, 1.0))
                                alpha_fade = max(0.0, 1.0 - elapsed / 0.5)
                                pulse_col = (
                                    int(255 * alpha_fade),
                                    int(200 * alpha_fade),
                                    int(80 * alpha_fade)
                                )
                                if r > 0 and alpha_fade > 0.05:
                                    pinch_cx = int((hand[4].x + hand[8].x) / 2 * w)
                                    pinch_cy = int((hand[4].y + hand[8].y) / 2 * h)
                                    cv2.circle(frame_rgb, (pinch_cx, pinch_cy), r, pulse_col, 2, cv2.LINE_AA)

                        # ── HOLO HUD ────────────────
                        if self.settings.get("hand_fx_hud", False):
                            # Bounding box around hand
                            xs = [int(lm.x * w) for lm in hand]
                            ys = [int(lm.y * h) for lm in hand]
                            bx1, by1 = max(0, min(xs) - 18), max(0, min(ys) - 18)
                            bx2, by2 = min(w, max(xs) + 18), min(h, max(ys) + 18)
                            hud_col = (100, 255, 200)
                            bracket = 16
                            # TL
                            cv2.line(frame_rgb, (bx1, by1), (bx1 + bracket, by1), hud_col, 2)
                            cv2.line(frame_rgb, (bx1, by1), (bx1, by1 + bracket), hud_col, 2)
                            # TR
                            cv2.line(frame_rgb, (bx2, by1), (bx2 - bracket, by1), hud_col, 2)
                            cv2.line(frame_rgb, (bx2, by1), (bx2, by1 + bracket), hud_col, 2)
                            # BL
                            cv2.line(frame_rgb, (bx1, by2), (bx1 + bracket, by2), hud_col, 2)
                            cv2.line(frame_rgb, (bx1, by2), (bx1, by2 - bracket), hud_col, 2)
                            # BR
                            cv2.line(frame_rgb, (bx2, by2), (bx2 - bracket, by2), hud_col, 2)
                            cv2.line(frame_rgb, (bx2, by2), (bx2, by2 - bracket), hud_col, 2)
                            
                            # Side label (gesture + mode)
                            mode_label = "SKETCH" if self._sketch_mode else "STASIS"
                            hud_text = f"{side[0]}: {g_display} [{mode_label}]"
                            cv2.putText(frame_rgb, hud_text, (bx1, max(12, by1 - 6)),
                                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, hud_col, 1, cv2.LINE_AA)
                                        
                            # Left Hand Mode Hint
                            if side == "Left":
                                cv2.putText(frame_rgb, "LFist: Toggle Mode", (bx1, by2 + 16),
                                            cv2.FONT_HERSHEY_SIMPLEX, 0.38, (180, 200, 220), 1, cv2.LINE_AA)
                                        
                            # Sketch-Specific HUD (Contextual Hints on Right Hand)
                            if self._sketch_mode and side == "Right":
                                draw_color_name = self._sketch_colors[self._color_idx][0]
                                draw_color_bgr = self._sketch_colors[self._color_idx][1]
                                
                                # Hints Label
                                hints_label = "Tips: LVictory (Color) | LPinch (Clear)"
                                cv2.putText(frame_rgb, hints_label, (bx1, by2 + 16),
                                            cv2.FONT_HERSHEY_SIMPLEX, 0.38, (180, 200, 220), 1, cv2.LINE_AA)
                                # Color Label
                                color_label = f"Color: {draw_color_name}"
                                cv2.putText(frame_rgb, color_label, (bx1, by2 + 32),
                                            cv2.FONT_HERSHEY_SIMPLEX, 0.42, draw_color_bgr, 1, cv2.LINE_AA)

                    else:
                        # Ghost tracking indicator
                        cv2.putText(frame_rgb, f"{side[0]}  ghost", (14, 36 + i * 28),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (90, 100, 110), 1, cv2.LINE_AA)
                    
                    # Store variables for global UI drawing outside loop
                    last_ix, last_iy = ix, iy

                    # ── Right Hand Exclusives ──
                    if side == "Right":
                        # ── SKETCH INTERACTION (PRECEDENCE) ──
                        if self._sketch_mode:
                            # 1. Drawing Engine
                            if gesture == Gesture.PINCH_START:
                                self._active_stroke.append((int(ix * w), int(iy * h)))
                                self._drawing_active = True
                                # Continue to skip other Right Hand actions
                                self._last_sx, self._last_sy = sx, sy
                                continue 
                            elif self._drawing_active:
                                # Commit stroke
                                if len(self._active_stroke) > 2:
                                    self._drawings.append({
                                        "color": self._sketch_colors[self._color_idx][1],
                                        "pts": self._active_stroke.copy()
                                    })
                                self._active_stroke = []
                                self._drawing_active = False

                        # ── Selection / Drag (Middle Pinch) ──────────────────
                        if gesture == Gesture.MIDDLE_PINCH:
                            if not self._tracking_paused:
                                if self.settings.get("hand_relative_mode", False):
                                    if not self._is_point_anchored:
                                        self._is_point_anchored = True
                                    else:
                                        sens = float(self.settings.get("hand_relative_sensitivity", 2.0))
                                        dx = (sx - self._last_sx) * sens
                                        dy = (sy - self._last_sy) * sens
                                        self.middle_pinch_rel_move.emit(dx, dy, True)
                                else:
                                    self._is_point_anchored = False
                                    self.middle_pinch_move.emit(sx, sy, True) 

                            self._last_sx, self._last_sy = sx, sy
                            self._was_middle_pinching = True
                            continue

                        if self._was_middle_pinching:
                            if not self._tracking_paused:
                                if self.settings.get("hand_relative_mode", False):
                                    self.middle_pinch_rel_move.emit(0, 0, False)
                                else:
                                    self.middle_pinch_move.emit(self._last_sx, self._last_sy, False)
                            self._was_middle_pinching = False
                            self._is_point_anchored = False # Reset anchor on release

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
                            else:
                                live_sensitivity = float(self.settings.get("hand_scroll_sensitivity", 2500))
                                delta = self._scroll_tracker.update(pinch_y, sensitivity=live_sensitivity)
                                if self._scroll_tracker.total_moved > 15:
                                    if abs(delta) > 0.5 and not self._tracking_paused: 
                                        self.scroll.emit(delta)
                            self._last_sx, self._last_sy = sx, sy
                            continue

                        if self._was_pinching:
                            if self._scroll_tracker.end():
                                if not self._tracking_paused:
                                    if (now - self._last_point_time) < 0.35:
                                        self.click.emit(self._last_sx, self._last_sy)
                                    else:
                                        self.click.emit(ix, iy)
                            self._was_pinching = False


                        # ── Point ──────────
                        if gesture == Gesture.POINT:
                            self._last_point_time = now
                            
                            # Relative Mode Logic
                            if self.settings.get("hand_relative_mode", False):
                                if not self._is_point_anchored:
                                    self._is_point_anchored = True
                                    # Don't move on first frame, just set anchor
                                else:
                                    # nx/ny are 0..1, convert distance to pixels via sensitivity
                                    sens = float(self.settings.get("hand_relative_sensitivity", 2.0))
                                    dx = (sx - self._last_sx) * sens
                                    dy = (sy - self._last_sy) * sens
                                    if not self._tracking_paused:
                                        self.cursor_rel_move.emit(dx, dy)
                            else:
                                self._is_point_anchored = False
                                if not self._tracking_paused:
                                    self.cursor_move.emit(sx, sy)
                                    
                            self._last_sx, self._last_sy = sx, sy
                            continue
                        else:
                            self._is_point_anchored = False

                # ── Global UI Drawing & Preview Emission (Outside Loop) ──
                
                # ── SPATIAL SKETCH RENDERING ──
                if self._sketch_mode:
                    # 1. Render Persistent Strokes
                    for stroke in self._drawings:
                        if len(stroke["pts"]) > 1:
                            pts_arr = np.array(stroke["pts"], np.int32)
                            cv2.polylines(frame_rgb, [pts_arr], False, stroke["color"], 2, cv2.LINE_AA)
                    
                    # 2. Render Active Stroke
                    if self._active_stroke and len(self._active_stroke) > 1:
                        pts_arr = np.array(self._active_stroke, np.int32)
                        cv2.polylines(frame_rgb, [pts_arr], False, self._sketch_colors[self._color_idx][1], 3, cv2.LINE_AA)

                if self._tracking_paused:
                    banner = "  TRACKING PAUSED  "
                    _f, _s, _t = cv2.FONT_HERSHEY_SIMPLEX, 0.52, 1
                    (bw, bh), _ = cv2.getTextSize(banner, _f, _s, _t)
                    bx, by = (w - bw) // 2, 12
                    # Frosted background
                    hx1, hy1, hx2, hy2 = bx - 10, by, bx + bw + 10, by + bh + 10
                    sub_p = frame_rgb[hy1:hy2, hx1:hx2]
                    rect_p = sub_p.copy()
                    cv2.rectangle(rect_p, (0,0), (hx2-hx1, hy2-hy1), (22, 18, 14), -1)
                    cv2.addWeighted(rect_p, 0.6, sub_p, 0.4, 0, sub_p)
                    
                    cv2.putText(frame_rgb, banner, (bx, by + bh + 4),
                                _f, _s, (210, 150, 70), _t, cv2.LINE_AA)

                # ── GLOBAL EXPLOSION RENDERING ───────────────────
                if now < self._explosion_start + 0.6:
                    ex_age = now - self._explosion_start
                    ex_alpha = max(0.0, 1.0 - ex_age / 0.6)
                    ex_cx, ex_cy = self._explosion_origin
                    
                    # Expanding shockwave rings
                    num_rings = 4
                    for r_i in range(num_rings):
                        r_offset = r_i * 0.12
                        if ex_age > r_offset:
                            r_progress = (ex_age - r_offset) / 0.4
                            if r_progress < 1.0:
                                r_current = int(r_progress * w * 0.6)
                                r_alpha = (1.0 - r_progress) * ex_alpha
                                # Draw shockwave on overlay
                                ex_overlay = frame_rgb.copy()
                                cv2.circle(ex_overlay, (ex_cx, ex_cy), r_current, (255, 230, 255), 3 + r_i, cv2.LINE_AA)
                                cv2.addWeighted(ex_overlay, r_alpha, frame_rgb, 1.0 - r_alpha, 0, frame_rgb)
                    
                    # Screen flash (Softer explosion)
                    if ex_age < 0.15:
                        flash_alpha = (1.0 - ex_age / 0.15) * 0.25
                        screen_flash = frame_rgb.copy()
                        cv2.rectangle(screen_flash, (0,0), (w,h), (255, 255, 255), -1)
                        cv2.addWeighted(screen_flash, flash_alpha, frame_rgb, 1.0 - flash_alpha, 0, frame_rgb)

                # ── GLOBAL OVERLOAD VIGNETTE ──
                if now < self._overload_end:
                    time_left = self._overload_end - now
                    v_alpha = 1.0
                    if time_left > 8.5: v_alpha = (9.0 - time_left) / 0.5
                    elif time_left < 1.0: v_alpha = time_left / 1.0
                    
                    if v_alpha > 0.05:
                        # Optimized Shadow: Use cache if resolution matches
                        if self._v_shadow_cache is None or self._v_shadow_cache[1] != w or self._v_shadow_cache[2] != h:
                            shadow_mask = np.zeros_like(frame_rgb)
                            sh_thickness = int(w * 0.08)
                            cv2.rectangle(shadow_mask, (0,0), (w,h), (40, 25, 50), sh_thickness)
                            shadow_mask = cv2.GaussianBlur(shadow_mask, (w//4|1, h//4|1), 0)
                            self._v_shadow_cache = (shadow_mask, w, h)
                        
                        # Subtraction intensity
                        v_shadow_final = (self._v_shadow_cache[0] * (v_alpha * 0.5)).astype(np.uint8)
                        frame_rgb = cv2.subtract(frame_rgb, v_shadow_final)

                if self._capture_name:
                    rec_label = f"  REC  {self._capture_name}  "
                    (rw, rh), _ = cv2.getTextSize(rec_label, cv2.FONT_HERSHEY_SIMPLEX, 0.52, 1)
                    rx = (w - rw) // 2
                    cv2.rectangle(frame_rgb, (rx - 6, 52), (rx + rw + 6, 52 + rh + 10), (22, 12, 12), cv2.FILLED)
                    cv2.putText(frame_rgb, rec_label, (rx, 52 + rh + 2),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.52, (210, 90, 80), 1, cv2.LINE_AA)
                    cv2.putText(frame_rgb, "hold still", (rx, 52 + rh + 22),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.38, (140, 80, 70), 1, cv2.LINE_AA)

                # Fetch active zone for drawing
                zx = self.settings.get("hand_point_x", 0.1)
                zy = self.settings.get("hand_point_y", 0.1)
                zw = self.settings.get("hand_point_w", 0.8)
                zh = self.settings.get("hand_point_h", 0.8)
                rect_x1, rect_y1 = int(zx * w), int(zy * h)
                rect_x2, rect_y2 = int((zx + zw) * w), int((zy + zh) * h)

                if self._calib_state == 1:
                    cv2.putText(frame_rgb, "pinch  →  top-left", (14, 82),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.50, (160, 190, 210), 1, cv2.LINE_AA)
                elif self._calib_state == 2:
                    cv2.rectangle(frame_rgb,
                                  (int(self._calib_tl[0]*w), int(self._calib_tl[1]*h)),
                                  (int(last_ix*w), int(last_iy*h)),
                                  (80, 130, 160), 1)
                    cv2.putText(frame_rgb, "pinch  →  bottom-right", (14, 82),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.50, (160, 190, 210), 1, cv2.LINE_AA)
                else:
                    # Subtle zone border — hide if in Sketch Mode OR Trackpad Mode
                    is_rel = self.settings.get("hand_relative_mode", False)
                    if not self._sketch_mode and not is_rel:
                        cv2.rectangle(frame_rgb, (rect_x1, rect_y1), (rect_x2, rect_y2), (55, 65, 75), 1)

                # Emit final frame with ALL hands and ALL UI drawn
                # Throttle preview slightly lower than tracking target to avoid UI congestion
                preview_throttle = 1.0 / (target_fps + 5) 
                if now - self._last_preview_time >= preview_throttle:
                    qimg = QImage(frame_rgb.data, w, h, ch * w, QImage.Format.Format_RGB888).copy()
                    if not qimg.isNull():
                        self.frame_processed.emit(qimg)
                    self._last_preview_time = now

                # ── Custom Pose Learning ──────────
                if self._capture_name and results.hand_landmarks:
                    self._capture_buffer.append(results.hand_landmarks[0])
                    if len(self._capture_buffer) >= 20:
                        self._pose_matcher.add_template(self._capture_name, self._capture_buffer[0], self._capture_action, self._capture_params)
                        self._pose_matcher.save_templates("core/custom_poses.json")
                        self._capture_name = None; self._capture_buffer = []

                # ── Discrete gestures ────────────────────────
                if gesture not in (Gesture.NONE, Gesture.POINT, Gesture.PINCH_START):
                    hold_duration = float(self.settings.get("gesture_hold_seconds", 2.0))
                    if gesture != state.hold_gesture:
                        state.hold_gesture = gesture; state.hold_start = now; state.hold_fired = False
                    elif not state.hold_fired:
                        if (now - state.hold_start) >= hold_duration:
                            gname = gesture if isinstance(gesture, str) else gesture.value
                            self.gesture_detected.emit(gname, nx, ny, side)
                            state.hold_fired = True
                else:
                    if gesture != state.hold_gesture:
                        state.hold_gesture = gesture; state.hold_fired = False
                
                    state.last_discrete_gesture = gesture
                    self._last_gesture = gesture

                last_proc_time = now


        finally:
            cap.release()
            if landmarker:
                landmarker.close()
            set_high_precision_timer(False)
            self.settings.flush() # Force save any pending changes
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
    middle_pinch_rel_move = pyqtSignal(float, float, bool)
    # Relative movement: (dx, dy)
    cursor_rel_move      = pyqtSignal(float, float)

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
        self._worker.cursor_rel_move.connect(self.cursor_rel_move, Qt.ConnectionType.DirectConnection)
        self._worker.middle_pinch_move.connect(self.middle_pinch_move, Qt.ConnectionType.DirectConnection)
        self._worker.middle_pinch_rel_move.connect(self.middle_pinch_rel_move, Qt.ConnectionType.DirectConnection)
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
        
        # Flush managers
        self._sys_manager.flush()
        self.settings.flush()

    @property
    def is_running(self) -> bool:
        return bool(self._worker and self._worker.isRunning())

    def _on_gesture(self, gesture_str: str, x: float, y: float, side: str = ""):
        self.gesture.emit(gesture_str, x, y)
        
        # 1. Check System Gesture Mapping
        sys_data = self._sys_manager.get_action_for_gesture(gesture_str, side)
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
            elif action == "toggle_hand_tracking":
                if self._worker:
                    self._worker._tracking_paused = not self._worker._tracking_paused
            elif action in ("launch_app", "ai_command"):
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
