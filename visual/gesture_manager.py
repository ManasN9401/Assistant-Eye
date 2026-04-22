import os
import json
import logging
import threading

logger = logging.getLogger(__name__)

class SystemGestureManager:
    """Manages built-in gesture actions and enable/disable states."""
    
    def __init__(self, config_path: str = "core/system_gestures.json"):
        self.config_path = config_path
        self.mappings = {}
        self._lock = threading.Lock()
        self._save_timer = None
        self._dirty = False
        self.load()

    def load(self):
        with self._lock:
            if not os.path.exists(self.config_path):
                logger.warning(f"System gestures config not found at {self.config_path}, using defaults.")
                self.mappings = {}
                return

            try:
                with open(self.config_path, "r") as f:
                    self.mappings = json.load(f)
            except Exception as e:
                logger.error(f"Failed to load system gestures: {e}")
                self.mappings = {}

    def save_now(self):
        """Immediate blocking save."""
        with self._lock:
            try:
                os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
                with open(self.config_path, "w") as f:
                    json.dump(self.mappings, f, indent=2)
                self._dirty = False
                if self._save_timer:
                    self._save_timer.cancel()
                    self._save_timer = None
                logger.info(f"Saved system gestures to {self.config_path}")
            except Exception as e:
                logger.error(f"Failed to save system gestures: {e}")

    def save_lazy(self):
        """Schedules a save in 2 seconds."""
        with self._lock:
            self._dirty = True
            if self._save_timer is None:
                self._save_timer = threading.Timer(2.0, self.save_now)
                self._save_timer.daemon = True
                self._save_timer.start()

    def flush(self):
        if self._dirty:
            self.save_now()

    def get_action_for_gesture(self, gesture_name: str, hand_side: str = None) -> dict:
        """Returns {enabled: bool, action: str, params: dict} or None."""
        with self._lock:
            g_lower = gesture_name.lower()
            if hand_side:
                specific_key = f"{g_lower}_{hand_side.lower()}"
                if specific_key in self.mappings:
                    return self.mappings[specific_key]
            return self.mappings.get(g_lower)

    def update_mapping(self, gesture_name: str, enabled: bool, action: str, params: dict = None):
        with self._lock:
            self.mappings[gesture_name.lower()] = {
                "enabled": enabled,
                "action": action,
                "params": params or {}
            }
        self.save_lazy()
