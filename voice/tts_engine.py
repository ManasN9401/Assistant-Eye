"""
TTS Engine — Text-to-Speech
Two backends selectable from settings:
  - pyttsx3   : fully offline, uses OS voices (SAPI5 on Windows, espeak on Linux)
  - elevenlabs: cloud, high-quality neural voices

Both run in a background thread so they never block the UI.
"""
from __future__ import annotations
import threading
from typing import Optional

from PyQt6.QtCore import QObject, QThread, pyqtSignal


# ── pyttsx3 backend ───────────────────────────────────────────────────────────

class Pyttsx3TTS:
    """Wraps pyttsx3. Must be used from a single thread (engine is not thread-safe)."""

    def __init__(self, rate: int = 185, volume: float = 0.95):
        self._engine = None
        self._rate = rate
        self._volume = volume

    def _init(self):
        if self._engine is None:
            import pyttsx3
            self._engine = pyttsx3.init()
            self._engine.setProperty("rate", self._rate)
            self._engine.setProperty("volume", self._volume)

    def set_voice(self, voice_id: Optional[str] = None):
        self._init()
        if voice_id:
            self._engine.setProperty("voice", voice_id)

    def list_voices(self) -> list[dict]:
        self._init()
        voices = self._engine.getProperty("voices")
        return [{"id": v.id, "name": v.name, "lang": v.languages} for v in (voices or [])]

    def speak(self, text: str):
        self._init()
        self._engine.say(text)
        self._engine.runAndWait()

    def stop(self):
        if self._engine:
            self._engine.stop()


# ── ElevenLabs backend ────────────────────────────────────────────────────────

class ElevenLabsTTS:
    """Cloud TTS via ElevenLabs SDK. Streams audio and plays via sounddevice."""

    DEFAULT_VOICE = "Rachel"

    def __init__(self, api_key: str, voice: str = DEFAULT_VOICE):
        self._api_key = api_key
        self._voice = voice

    def speak(self, text: str):
        """Speak via ElevenLabs.

        This is designed to work across different versions of the elevenlabs SDK:
        - Old API: ElevenLabs.generate(...)
        - New API: top-level generate(...)
        - Fallback: ElevenLabs.text_to_speech(...)
        """
        import sounddevice as sd
        import numpy as np
        import io
        import soundfile as sf

        try:
            # Use top-level generate() if available (newer versions)
            from elevenlabs import generate
            audio_iter = generate(
                text=text,
                voice=self._voice,
                model="eleven_turbo_v2",
                stream=True,
            )
        except Exception:
            # Fallback to object API
            from elevenlabs import ElevenLabs
            client = ElevenLabs(api_key=self._api_key)
            if hasattr(client, "generate"):
                audio_iter = client.generate(
                    text=text,
                    voice=self._voice,
                    model="eleven_turbo_v2",
                    stream=True,
                )
            elif hasattr(client, "text_to_speech"):
                audio_iter = client.text_to_speech(
                    text=text,
                    voice=self._voice,
                    model="eleven_turbo_v2",
                    stream=True,
                )
            else:
                raise RuntimeError("Unsupported elevenlabs client API: cannot find generate/text_to_speech")

        audio_bytes = b"".join(audio_iter)
        data, sr = sf.read(io.BytesIO(audio_bytes), dtype="float32")
        sd.play(data, sr)
        sd.wait()

    def stop(self):
        import sounddevice as sd
        sd.stop()


# ── Worker thread ─────────────────────────────────────────────────────────────

class TTSWorker(QThread):
    started   = pyqtSignal()
    finished  = pyqtSignal()
    error     = pyqtSignal(str)

    def __init__(self, backend, text: str, parent=None):
        super().__init__(parent)
        self._backend = backend
        self._text = text

    def run(self):
        import sys
        if sys.platform == "win32":
            try:
                import pythoncom
                pythoncom.CoInitialize()
            except ImportError:
                pass
        
        self.started.emit()
        try:
            self._backend.speak(self._text)
        except Exception as e:
            self.error.emit(str(e))
        finally:
            self.finished.emit()


# ── TTS Engine (public API) ───────────────────────────────────────────────────

class TTSEngine(QObject):
    """
    High-level TTS manager.
    Call speak(text) to queue an utterance.
    Only one utterance plays at a time; calling speak() while busy
    cancels the current utterance and starts the new one.
    """
    started   = pyqtSignal()
    finished  = pyqtSignal()
    error     = pyqtSignal(str)

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self._worker: Optional[TTSWorker] = None
        self._pyttsx3: Optional[Pyttsx3TTS] = None
        self._elevenlabs: Optional[ElevenLabsTTS] = None

    def _get_backend(self):
        engine = self.settings.get("tts_engine", "pyttsx3")
        if engine == "elevenlabs":
            key = self.settings.get("elevenlabs_api_key", "")
            voice = self.settings.get("elevenlabs_voice", ElevenLabsTTS.DEFAULT_VOICE)
            try:
                # Validate the package and fallback to pyttsx3 if not present.
                from elevenlabs import ElevenLabs
            except ModuleNotFoundError:
                self.error.emit("ElevenLabs package not installed, falling back to pyttsx3")
                engine = "pyttsx3"
            else:
                if not self._elevenlabs or self._elevenlabs._api_key != key:
                    self._elevenlabs = ElevenLabsTTS(key, voice)
                return self._elevenlabs

        # Default / fallback: pyttsx3
        if self._pyttsx3 is None:
            self._pyttsx3 = Pyttsx3TTS(
                rate=int(self.settings.get("tts_rate", 185)),
                volume=float(self.settings.get("tts_volume", 0.95)),
            )
            voice_id = self.settings.get("tts_voice_id", None)
            if voice_id:
                self._pyttsx3.set_voice(voice_id)
        return self._pyttsx3

    def speak(self, text: str):
        if not text.strip():
            return
        if not self.settings.get("tts_enabled", True):
            self.finished.emit()
            return

        self.stop()
        backend = self._get_backend()
        self._worker = TTSWorker(backend, text, self)
        self._worker.started.connect(self.started)
        self._worker.finished.connect(self.finished)
        self._worker.error.connect(self.error)
        self._worker.start()

    def stop(self):
        if self._worker and self._worker.isRunning():
            try:
                backend = self._get_backend()
                backend.stop()
            except Exception:
                pass
            self._worker.quit()
            self._worker.wait(1000)

    def list_pyttsx3_voices(self) -> list[dict]:
        p = Pyttsx3TTS()
        return p.list_voices()

    @property
    def is_speaking(self) -> bool:
        return bool(self._worker and self._worker.isRunning())
