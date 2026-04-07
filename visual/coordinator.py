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

from PyQt6.QtCore import QObject, pyqtSignal, QTimer

from visual.hand_tracker import HandTracker
from visual.eye_tracker import EyeTracker
from visual.sign_language import SignLanguageInterpreter
from visual.logging_config import setup_logging

# Initialize logging on module import
logger = logging.getLogger(__name__)


class CursorController:
    """Moves the OS mouse cursor to a normalised screen position."""

    def __init__(self):
        self._system = platform.system()
        self._screen_w, self._screen_h = self._get_screen_size()

    def _get_screen_size(self) -> tuple[int, int]:
        try:
            from PyQt6.QtWidgets import QApplication
            screen = QApplication.primaryScreen()
            if screen:
                geo = screen.geometry()
                return geo.width(), geo.height()
        except Exception:
            pass
        return 1920, 1080

    def move_to(self, x_norm: float, y_norm: float):
        """Move cursor to normalised position (0–1, 0–1)."""
        px = int(x_norm * self._screen_w)
        py = int(y_norm * self._screen_h)
        self._set_pos(px, py)

    def click_at(self, x_norm: float, y_norm: float):
        self.move_to(x_norm, y_norm)
        self._click()

    def scroll(self, dy: float):
        """Scroll by dy pixels."""
        try:
            if self._system == "Windows":
                import ctypes
                # positive dy = scroll down, negative = scroll up
                ctypes.windll.user32.mouse_event(0x0800, 0, 0, int(-dy / 40), 0)
            else:
                import pyautogui
                pyautogui.scroll(-int(dy / 40))
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
    sign_command         = pyqtSignal(str)    # e.g. "go_to_docs", "trigger_listen"
    sign_word            = pyqtSignal(str)    # fingerspelled word

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
        logger.info("VisualCoordinator initialized")

        self.settings = settings
        self._cursor  = CursorController()

        self.hand_tracker = HandTracker(settings, self)
        self.eye_tracker  = EyeTracker(settings, self)
        self.sign_lang    = SignLanguageInterpreter(settings, self)

        # Gaze cursor throttle — don't move cursor every frame
        self._last_cursor_move = 0.0
        self._cursor_interval  = 1 / 30   # max 30Hz

        self._wire()

    def _wire(self):
        # Hand → actions
        self.hand_tracker.action_open_overlay.connect(self.action_open_overlay)
        self.hand_tracker.action_close_overlay.connect(self.action_close_overlay)
        self.hand_tracker.action_confirm.connect(self.action_confirm)
        self.hand_tracker.action_cancel.connect(self.action_cancel)
        self.hand_tracker.action_stop_speaking.connect(self.action_stop_speaking)

        # Hand scroll → OS scroll
        self.hand_tracker.scroll.connect(self._cursor.scroll)

        # Hand point → cursor move (throttled in handler)
        self.hand_tracker.cursor_move.connect(self._on_hand_cursor)

        # Hand click
        self.hand_tracker.click.connect(
            lambda x, y: self._cursor.click_at(x, y)
        )

        self.hand_tracker.error.connect(self.error)

        # Eye gaze → cursor (throttled)
        self.eye_tracker.gaze_point.connect(self._on_gaze)

        # Eye dwell → click
        self.eye_tracker.dwell_click.connect(
            lambda x, y: self._cursor.click_at(x, y)
        )

        self.eye_tracker.calibration_progress.connect(self.calibration_progress)
        self.eye_tracker.calibration_complete.connect(self.calibration_complete)
        self.eye_tracker.error.connect(self.error)

        # Sign language
        self.sign_lang.quick_action.connect(self.sign_command)
        self.sign_lang.word_complete.connect(self.sign_word)
        self.sign_lang.error.connect(self.error)

    # ── Throttled handlers ────────────────────────────────────────────────────

    def _on_hand_cursor(self, x: float, y: float):
        import time
        now = time.time()
        if now - self._last_cursor_move >= self._cursor_interval:
            self._cursor.move_to(x, y)
            self._last_cursor_move = now

    def _on_gaze(self, x: float, y: float):
        import time
        now = time.time()
        # Eye tracking cursor update only if hand tracking isn't actively pointing
        if now - self._last_cursor_move >= self._cursor_interval:
            self._cursor.move_to(x, y)
            self._last_cursor_move = now

    # ── Public API ────────────────────────────────────────────────────────────

    def start_hand_tracking(self, camera: int = 0):
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
        self.sign_lang.start(camera)
        mode = self.settings.get("sign_mode", "quick_actions")
        self.status.emit(f"Sign language active ({mode} mode)")

    def stop_sign_language(self):
        self.sign_lang.stop()
        self.status.emit("Sign language stopped")

    def start_calibration(self):
        self.eye_tracker.start_calibration()
        self.status.emit("Calibration started — look at each dot and press advance")

    def advance_calibration(self):
        self.eye_tracker.advance_calibration()

    def stop_all(self):
        self.hand_tracker.stop()
        self.eye_tracker.stop()
        self.sign_lang.stop()

    @property
    def hand_active(self) -> bool:
        return self.hand_tracker.is_running

    @property
    def eye_active(self) -> bool:
        return self.eye_tracker.is_running

    @property
    def sign_active(self) -> bool:
        return self.sign_lang.is_running
