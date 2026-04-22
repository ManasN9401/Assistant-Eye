import json
import threading
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_SETTINGS = {
    "assistant_name": "EYE",
    "wake_word": "hey eye",
    "ai_provider": "openai",
    "ai_model": "gpt-4o",
    "api_key": "",
    "anthropic_api_key": "",
    "tts_engine": "pyttsx3",
    "overlay_hotkey": "ctrl+space",
    "overlay_opacity": 92,
    "theme": "dark",
    "overlay_x": 80,
    "overlay_y": 80,
    "window_x": 200,
    "window_y": 120,
    "window_width": 960,
    "window_height": 680,
    "active_site_url": "",
    "active_site_registry": "",
    # Visual special effects
    "hand_fx_trails": True,
    "hand_fx_pulse": True,
    "hand_fx_hud": False,
}

AI_PROVIDERS = {
    "openai": {
        "label": "OpenAI",
        "models": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo"],
    },
    "anthropic": {
        "label": "Anthropic",
        "models": ["claude-opus-4-5", "claude-sonnet-4-5", "claude-haiku-4-5"],
    },
    "ollama": {
        "label": "Ollama (local)",
        "models": ["llama3", "mistral", "phi3", "gemma2"],
    },
}

class Settings:
    def __init__(self):
        self.config_dir = Path.home() / ".aria-assistant"
        self.config_file = self.config_dir / "settings.json"
        self._data: dict = {}
        self._lock = threading.Lock()
        self._save_timer: threading.Timer = None
        self._dirty = False
        self.load()

    def load(self):
        self.config_dir.mkdir(exist_ok=True)
        if self.config_file.exists():
            try:
                with open(self.config_file, "r") as f:
                    saved = json.load(f)
                self._data = {**DEFAULT_SETTINGS, **saved}
            except Exception:
                self._data = dict(DEFAULT_SETTINGS)
        else:
            self._data = dict(DEFAULT_SETTINGS)
            self.save_now() # Initial save is immediate

    def save_now(self):
        """Immediate blocking save."""
        with self._lock:
            try:
                with open(self.config_file, "w") as f:
                    json.dump(self._data, f, indent=2)
                self._dirty = False
                if self._save_timer:
                    self._save_timer.cancel()
                    self._save_timer = None
            except Exception as e:
                logger.error(f"Failed to save settings: {e}")

    def save_lazy(self):
        """Schedules a save in 2 seconds if not already scheduled."""
        with self._lock:
            self._dirty = True
            if self._save_timer is None:
                self._save_timer = threading.Timer(2.0, self.save_now)
                self._save_timer.daemon = True
                self._save_timer.start()

    def flush(self):
        """Force immediate save if dirty."""
        if self._dirty:
            self.save_now()

    def get(self, key: str, default=None):
        with self._lock:
            return self._data.get(key, default)

    def set(self, key: str, value):
        with self._lock:
            if self._data.get(key) == value:
                return
            self._data[key] = value
        self.save_lazy()

    def update(self, data: dict):
        with self._lock:
            self._data.update(data)
        self.save_lazy()

    # Convenience properties
    @property
    def assistant_name(self) -> str:
        return self._data.get("assistant_name", "EYE")

    @property
    def ai_provider(self) -> str:
        return self._data.get("ai_provider", "openai")

    @property
    def ai_model(self) -> str:
        return self._data.get("ai_model", "gpt-4o")
