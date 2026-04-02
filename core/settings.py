import json
from pathlib import Path

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
            self.save()

    def save(self):
        with open(self.config_file, "w") as f:
            json.dump(self._data, f, indent=2)

    def get(self, key: str, default=None):
        return self._data.get(key, default)

    def set(self, key: str, value):
        self._data[key] = value
        self.save()

    def update(self, data: dict):
        self._data.update(data)
        self.save()

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
