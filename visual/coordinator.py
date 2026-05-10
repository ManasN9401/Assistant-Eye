"""
Visual Input Coordinator — Phase 3
Combines hand tracking, eye tracking, and sign language into a single
module that emits high-level actions the rest of the app can respond to.

Action routing:
  Hand gestures     → overlay toggle, scroll, click, confirm, cancel
  Eye gaze          → move OS cursor, dwell-click
  Sign language     → voice commands (routed through VoiceCoordinator)

OS cursor control uses platform-appropriate method:
  Windows: ctypes (no deps)
  Linux:   python-xlib or PyAutoGUI
"""
from __future__ import annotations
import platform
import sys
import logging
from typing import Optional

from PyQt6.QtCore import QObject, pyqtSignal, QTimer, Qt, QMutex, QMutexLocker
import time

from visual.hand_tracker import HandTracker
from visual.eye_tracker import EyeTracker
from visual.logging_config import setup_logging
from core.function_registry import FunctionRegistry
from ui.sign_ui import SignLanguageOverlay

# Initialize logging on module import
logger = logging.getLogger(__name__)


class CursorController:
    """Moves the OS mouse cursor to a normalised screen position."""

    def __init__(self):
        self._system = platform.system()
        self._screen_w, self._screen_h = self._get_screen_size()

    def _get_screen_size(self) -> tuple[int, int]:
        # Since QApplication is already created in main.py, we can use it safely.
        # This is more stable than calling user32.GetSystemMetrics directly.
        try:
            from PyQt6.QtWidgets import QApplication
            app = QApplication.instance()
            if app:
                screen = app.primaryScreen()
                if screen:
                    geo = screen.geometry()
                    w, h = geo.width(), geo.height()
                    if w > 0 and h > 0:
                        logger.debug(f"Screen size from PyQt: {w}x{h}")
                        return w, h
        except Exception as e:
            logger.warning(f"PyQt screen size detection failed: {e}")

        logger.warning("Using fallback screen size 1920x1080")
        return 1920, 1080

    def move_to(self, x_norm: float, y_norm: float):
        """Move cursor to normalised position (0–1, 0–1)."""
        px = int(x_norm * self._screen_w)
        px = int(x_norm * self._screen_w)
        py = int(y_norm * self._screen_h)
        self._set_pos(px, py)

    def move_rel(self, dx_norm: float, dy_norm: float):
        """Relative movement based on normalized screen fractions."""
        dx = int(dx_norm * self._screen_w)
        dy = int(dy_norm * self._screen_h)
        self._move_rel(dx, dy)

    def click_at(self, x_norm: float, y_norm: float):
        self.move_to(x_norm, y_norm)
        self._click()

    def click_current(self):
        """Click at the current OS cursor position."""
        self._click()

    def scroll(self, dy: float):
        """Scroll by dy wheel units (positive = down, negative = up).
        Windows WHEEL_DELTA = 120 per notch; we accept fractional values.
        """
        try:
            if self._system == "Windows":
                import ctypes
                amount = int(-dy)  # negate: positive dy = scroll down = negative wheel
                if amount != 0:
                    ctypes.windll.user32.mouse_event(0x0800, 0, 0, amount, 0)
            else:
                import pyautogui
                pyautogui.scroll(-int(dy / 120))  # pyautogui uses notch counts
        except Exception:
            pass

    def _set_pos(self, x: int, y: int):
        try:
            if self._system == "Windows":
                import ctypes
                ctypes.windll.user32.SetCursorPos(x, y)
            else:
                # Try xlib first, fall back to pyautogui
                try:
                    from Xlib import display
                    d = display.Display()
                    d.screen().root.warp_pointer(x, y)
                    d.flush()
                except Exception:
                    import pyautogui
                    pyautogui.moveTo(x, y, duration=0)
        except Exception:
            pass

    def _move_rel(self, dx: int, dy: int):
        try:
            if self._system == "Windows":
                import ctypes
                # 0x0001 = MOUSEEVENTF_MOVE
                ctypes.windll.user32.mouse_event(0x0001, dx, dy, 0, 0)
            else:
                import pyautogui
                pyautogui.moveRel(dx, dy, duration=0)
        except Exception:
            pass

    def _click(self):
        try:
            if self._system == "Windows":
                import ctypes
                ctypes.windll.user32.mouse_event(0x0002, 0, 0, 0, 0)
                ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0)
            else:
                import pyautogui
                pyautogui.click()
        except Exception:
            pass

    def set_mouse_pressed(self, down: bool):
        """Set the left mouse button to a pressed (down) or released (up) state."""
        try:
            if self._system == "Windows":
                import ctypes
                # 0x0002 = LEFTDOWN, 0x0004 = LEFTUP
                event = 0x0002 if down else 0x0004
                ctypes.windll.user32.mouse_event(event, 0, 0, 0, 0)
            else:
                import pyautogui
                if down:
                    pyautogui.mouseDown()
                else:
                    pyautogui.mouseUp()
        except Exception:
            pass


class VisualCoordinator(QObject):
    """
    Manages all visual input sub-systems and translates their output
    into high-level signals for the assistant.
    """
    # Actions
    action_open_overlay  = pyqtSignal()
    action_close_overlay = pyqtSignal()
    action_confirm       = pyqtSignal()
    action_cancel        = pyqtSignal()
    action_stop_speaking = pyqtSignal()
    
    # Custom Pose Actions
    execute_custom_action = pyqtSignal(str, dict) # action_name, params
    frame_processed      = pyqtSignal(object) # QImage feed from cameras
    sign_language_active_changed = pyqtSignal(bool)

    # Status
    error  = pyqtSignal(str)
    status = pyqtSignal(str)  # human-readable status message

    # Calibration
    calibration_progress = pyqtSignal(int)
    calibration_complete = pyqtSignal()

    def __init__(self, settings, parent=None):
        super().__init__(parent)

        # Initialize logging
        setup_logging("eye_tracking_debug.log")
        logger.info("VisualCoordinator: setup_logging done")
        self._is_dragging = False

        self.settings = settings
        logger.info("VisualCoordinator: Initializing CursorController...")
        self._cursor  = CursorController()
        logger.info("VisualCoordinator: CursorController ready")

        logger.info("VisualCoordinator: Initializing HandTracker...")
        self.hand_tracker = HandTracker(settings, self)
        logger.info("VisualCoordinator: HandTracker ready")

        logger.info("VisualCoordinator: Initializing EyeTracker...")
        self.eye_tracker  = EyeTracker(settings, self)
        logger.info("VisualCoordinator: EyeTracker ready")

        # Gaze cursor throttle — don't move cursor every frame
        self._last_cursor_move = 0.0
        self._cursor_interval  = 1 / 30   # max 30Hz
        
        self.sign_language_active = False
        self._current_camera = self.settings.get("visual_camera", 0)
        self._cursor_lock = QMutex()
        
        # Sign Language UI
        self._sign_overlay = None

        self._wire()

    def _wire(self):
        # Hand → actions
        self.hand_tracker.action_open_overlay.connect(self.action_open_overlay)
        self.hand_tracker.action_close_overlay.connect(self.action_close_overlay)
        self.hand_tracker.action_confirm.connect(self.action_confirm)
        self.hand_tracker.action_cancel.connect(self.action_cancel)
        self.hand_tracker.action_stop_speaking.connect(self.action_stop_speaking)

        # Hand scroll → OS scroll
        self.hand_tracker.scroll.connect(self._cursor.scroll, Qt.ConnectionType.DirectConnection)

        # Hand point → cursor move (throttled in handler)
        self.hand_tracker.cursor_move.connect(self._on_hand_cursor, Qt.ConnectionType.DirectConnection)
        self.hand_tracker.cursor_rel_move.connect(self._on_hand_rel_cursor, Qt.ConnectionType.DirectConnection)

        # Hand click
        self.hand_tracker.click.connect(self._on_hand_click, Qt.ConnectionType.DirectConnection)
        self.hand_tracker.middle_pinch_move.connect(self._on_hand_drag, Qt.ConnectionType.DirectConnection)
        self.hand_tracker.middle_pinch_rel_move.connect(self._on_hand_rel_drag, Qt.ConnectionType.DirectConnection)

        self.hand_tracker.error.connect(self.error)
        self.hand_tracker.frame_processed.connect(self.frame_processed)
        self.hand_tracker.custom_gesture.connect(self._on_custom_gesture)

        # Eye gaze → cursor (throttled)
        self.eye_tracker.gaze_point.connect(self._on_gaze, Qt.ConnectionType.DirectConnection)

        # Eye dwell → click
        self.eye_tracker.dwell_click.connect(
            lambda x, y: self._cursor.click_at(x, y),
            Qt.ConnectionType.DirectConnection
        )

        self.eye_tracker.calibration_progress.connect(self.calibration_progress)
        self.eye_tracker.calibration_complete.connect(self.calibration_complete)
        self.eye_tracker.error.connect(self.error)

        # Sign Language → UI
        self.hand_tracker.sign_update.connect(self._on_sign_update)
        self.hand_tracker.hand_pos_update.connect(self._on_hand_pos_update)
        self.hand_tracker.mode_changed.connect(self._on_mode_changed)

    # ── Throttled handlers ────────────────────────────────────────────────────

    def _on_hand_cursor(self, x: float, y: float):
        now = time.time()
        with QMutexLocker(self._cursor_lock):
            if now - self._last_cursor_move < self._cursor_interval:
                return
            self._last_cursor_move = now
            
        self._cursor.move_to(x, y)

    def _on_hand_click(self, x: float, y: float):
        if self.settings.get("hand_relative_mode", False):
            self._cursor.click_current()
        else:
            self._cursor.click_at(x, y)

    def _on_hand_rel_cursor(self, dx: float, dy: float):
        self._cursor.move_rel(dx, dy)
        self._last_cursor_move = time.time()

    def _on_hand_drag(self, x: float, y: float, is_down: bool):
        """Handler for middle-pinch drag gesture."""
        # Selection/dragging requires high precision; always move
        self._cursor.move_to(x, y)
        
        # Only set mouse state if it has changed to avoid driver flooding
        if is_down and not self._is_dragging:
            self._cursor.set_mouse_pressed(True)
            self._is_dragging = True
            self.status.emit("Selecting...")
        elif not is_down and self._is_dragging:
            self._cursor.set_mouse_pressed(False)
            self._is_dragging = False

    def _on_hand_rel_drag(self, dx: float, dy: float, is_down: bool):
        """Handler for relative middle-pinch drag gesture."""
        self._cursor.move_rel(dx, dy)
        
        if is_down and not self._is_dragging:
            self._cursor.set_mouse_pressed(True)
            self._is_dragging = True
            self.status.emit("Selecting...")
        elif not is_down and self._is_dragging:
            self._cursor.set_mouse_pressed(False)
            self._is_dragging = False
            self.status.emit("Selection released")

    def _on_gaze(self, x: float, y: float):
        now = time.time()
        with QMutexLocker(self._cursor_lock):
            if now - self._last_cursor_move < self._cursor_interval:
                return
            self._last_cursor_move = now
            
        self._cursor.move_to(x, y)

    def _on_custom_gesture(self, name: str, action: str, params: dict):
        logger.info(f"[Coordinator] Custom pose recognized: {name} -> {action}")
        self.status.emit(f"Pose detected: {name}")
        self.execute_custom_action.emit(action, params)

    def _on_sign_update(self, full, word, letter, paused):
        if self._sign_overlay:
            self._sign_overlay.update_translation(full, word, letter, paused)

    def _on_hand_pos_update(self, x, y):
        # We no longer use a separate desktop-wide hand label overlay.
        # Hand position updates are still processed if needed by other components.
        pass

    def _on_mode_changed(self, new_mode: str):
        logger.info(f"VisualCoordinator: Mode changed to {new_mode}")
        self.status.emit(f"Mode: {new_mode}")
        
        # Handle Sign Language Overlay visibility
        if new_mode == "SYMBOL":
            if not self._sign_overlay:
                self._sign_overlay = SignLanguageOverlay()
            self._sign_overlay.show()
            self.sign_language_active = True
            self.sign_language_active_changed.emit(True)
        else:
            if self._sign_overlay: self._sign_overlay.hide()
            self.sign_language_active = False
            self.sign_language_active_changed.emit(False)

    # ── Public API ────────────────────────────────────────────────────────────

    def start_hand_tracking(self, camera: int = 0):
        self._current_camera = camera
        self.hand_tracker.start(camera)
        self.status.emit("Hand tracking active")

    def stop_hand_tracking(self):
        self.hand_tracker.stop()
        self.status.emit("Hand tracking stopped")

    def start_eye_tracking(self, camera: int = 0):
        self.eye_tracker.start(camera)
        self.status.emit("Eye tracking active — calibrate for best accuracy")

    def stop_eye_tracking(self):
        self.eye_tracker.stop()
        self.status.emit("Eye tracking stopped")

    def start_sign_language(self, camera: int = 0):
        self.sign_language_active = True
        self.start_hand_tracking(camera)
        self.hand_tracker.set_symbol_mode(True)
        
        if not self._sign_overlay:
            self._sign_overlay = SignLanguageOverlay()
            
        self._sign_overlay.show()
        self.sign_language_active_changed.emit(True)
        self.status.emit("Sign language translation active")

    def stop_sign_language(self):
        self.sign_language_active = False
        self.hand_tracker.set_symbol_mode(False)
        if self._sign_overlay: self._sign_overlay.hide()
        self.sign_language_active_changed.emit(False)
        self.status.emit("Sign language translation stopped")

    def start_calibration(self):
        self.eye_tracker.start_calibration()
        self.status.emit("Calibration started — look at each dot and press advance")

    def start_hand_calibration(self):
        self.hand_tracker.start_calibration()
        self.status.emit("Hand Tracking Calibration Active: Pinch top left then bottom right of your ideal target area.")

    def advance_calibration(self):
        self.eye_tracker.advance_calibration()

    def learn_pose(self, name: str, action: str = "none", params: dict = None):
        self.hand_tracker.learn_pose(name, action, params)
        self.status.emit(f"Learning pose: {name}. Hold still for 2 seconds...")

    def reload_system_gestures(self):
        self.hand_tracker.reload_system_gestures()

    def delete_pose(self, name: str):
        if self.hand_active:
            if name in self.hand_tracker._worker._pose_matcher.templates:
                del self.hand_tracker._worker._pose_matcher.templates[name]
                self.hand_tracker._worker._pose_matcher.save_templates("core/custom_poses.json")
                self.status.emit(f"Deleted pose: {name}")

    def stop_all(self):
        self.hand_tracker.stop()
        self.eye_tracker.stop()

    @property
    def hand_active(self) -> bool:
        return self.hand_tracker.is_running

    @property
    def eye_active(self) -> bool:
        return self.eye_tracker.is_running
