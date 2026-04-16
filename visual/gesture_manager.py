import os
import json
import logging

logger = logging.getLogger(__name__)

class SystemGestureManager:
    """Manages built-in gesture actions and enable/disable states."""
    
    def __init__(self, config_path: str = "core/system_gestures.json"):
        self.config_path = config_path
        self.mappings = {}
        self.load()

    def load(self):
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

    def save(self):
        try:
            os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
            with open(self.config_path, "w") as f:
                json.dump(self.mappings, f, indent=2)
            logger.info(f"Saved system gestures to {self.config_path}")
        except Exception as e:
            logger.error(f"Failed to save system gestures: {e}")

    def get_action_for_gesture(self, gesture_name: str) -> dict:
        """Returns {enabled: bool, action: str, params: dict} or None."""
        return self.mappings.get(gesture_name.lower())

    def update_mapping(self, gesture_name: str, enabled: bool, action: str, params: dict = None):
        self.mappings[gesture_name.lower()] = {
            "enabled": enabled,
            "action": action,
            "params": params or {}
        }
        self.save()
