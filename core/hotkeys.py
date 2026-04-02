"""
Hotkey Manager
Registers global keyboard shortcuts that work even when the app is not focused.

Hotkeys (configurable in settings):
  overlay_hotkey  : default "ctrl+space" — toggle the overlay pill
  listen_hotkey   : default "ctrl+shift+space" — trigger one-shot listen

Implementation:
  Uses the `keyboard` library (cross-platform, works on Windows + Linux with X11).
  On Linux, requires running as a user with /dev/input access OR the keyboard
  library's uinput fallback. No root required if user is in the `input` group:
    sudo usermod -aG input $USER

Runs in a background thread — signals are emitted safely to the Qt main thread
via QMetaObject.invokeMethod / pyqtSignal.
"""
from __future__ import annotations
import threading
from typing import Callable, Optional

from PyQt6.QtCore import QObject, pyqtSignal


class HotkeyManager(QObject):
    overlay_triggered = pyqtSignal()
    listen_triggered  = pyqtSignal()
    error             = pyqtSignal(str)

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings   = settings
        self._running   = False
        self._thread:   Optional[threading.Thread] = None
        self._kb        = None   # keyboard module, imported lazily

    def start(self):
        if self._running:
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._kb:
            try:
                self._kb.unhook_all()
            except Exception:
                pass

    def _run(self):
        try:
            import keyboard as kb
            self._kb     = kb
            self._running = True

            overlay_hk = self.settings.get("overlay_hotkey", "ctrl+space")
            listen_hk  = self.settings.get("listen_hotkey", "ctrl+shift+space")

            kb.add_hotkey(overlay_hk, self.overlay_triggered.emit, suppress=False)
            kb.add_hotkey(listen_hk,  self.listen_triggered.emit,  suppress=False)

            while self._running:
                kb.wait()   # blocks until all hooks are unregistered

        except ImportError:
            self.error.emit(
                "keyboard library not installed. "
                "Run: pip install keyboard\n"
                "On Linux also: sudo usermod -aG input $USER  (then re-login)"
            )
        except Exception as e:
            self.error.emit(f"Hotkey error: {e}")

    def update_hotkeys(self):
        """Call after settings change to re-register with new key combos."""
        self.stop()
        self.start()
