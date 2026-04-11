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
import atexit
import logging
from typing import Callable, Optional

from PyQt6.QtCore import QObject, pyqtSignal

logger = logging.getLogger(__name__)

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
        
        # Ensure we cleanup hooks if Python exits unexpectedly
        atexit.register(self.stop)

    def start(self):
        if self._running:
            return
        logger.debug("Starting HotkeyManager thread")
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        """Unregister all hotkeys and stop the background thread."""
        logger.debug("Stopping HotkeyManager")
        self._running = False
        if self._kb:
            try:
                # unhook_all() usually triggers kb.wait() to return
                self._kb.unhook_all()
                logger.debug("All hotkeys unhooked")
            except Exception as e:
                logger.error(f"Error during hotkey unhook: {e}")
        
        # We don't join the thread here because this might be called from 
        # a signal handler or during exit, and we don't want to block.
        # Since it's a daemon thread, it will die with the process anyway.

    def _run(self):
        try:
            import keyboard as kb
            self._kb = kb
            
            overlay_hk = self.settings.get("overlay_hotkey", "ctrl+space")
            listen_hk  = self.settings.get("listen_hotkey", "ctrl+shift+space")

            logger.info(f"Registering hotkeys: overlay={overlay_hk}, listen={listen_hk}")
            
            # Use a wrapper to catch exceptions in callbacks
            def safe_emit(signal):
                try:
                    signal.emit()
                except Exception as e:
                    logger.error(f"Error emitting hotkey signal: {e}")

            kb.add_hotkey(overlay_hk, lambda: safe_emit(self.overlay_triggered), suppress=False)
            kb.add_hotkey(listen_hk,  lambda: safe_emit(self.listen_triggered),  suppress=False)

            while self._running:
                # kb.wait() blocks until all hooks are removed. 
                # Our stop() calls unhook_all(), which should break this.
                kb.wait()
                if not self._running:
                    break

        except ImportError:
            msg = "keyboard library not installed. Run: pip install keyboard"
            logger.error(msg)
            self.error.emit(msg)
        except Exception as e:
            logger.error(f"Global hotkey thread error: {e}")
            self.error.emit(f"Hotkey error: {e}")
        finally:
            self._running = False
            logger.debug("Hotkey thread exiting")

    def update_hotkeys(self):
        """Call after settings change to re-register with new key combos."""
        logger.info("Updating hotkeys...")
        self.stop()
        # Give it a tiny bit of time to settle if needed
        self.start()

