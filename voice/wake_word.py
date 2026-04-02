"""
Wake Word Detector
Listens continuously in the background and fires a signal when the
configured wake phrase is detected.

Two backends (selected automatically by what's installed):
  1. Porcupine (pvporcupine) — best accuracy, needs a free Picovoice API key.
     Built-in keywords: "hey google", "hey siri", "alexa", "ok google",
     "jarvis", "computer", "americano", "blueberry", "bumblebee",
     "grapefruit", "grasshopper", "picovoice", "porcupine", "terminator".
     Custom wake words can be trained for free at console.picovoice.ai.

  2. Vosk — fully offline, no key, uses keyword-spotting with a grammar.
     Less accurate but zero-dependency-on-cloud.

Settings keys used:
  wake_word_engine  : "porcupine" | "vosk"
  wake_word         : the phrase (e.g. "hey aria")
  picovoice_key     : Picovoice access key
  porcupine_keyword : built-in keyword name (e.g. "bumblebee")
"""
from __future__ import annotations
import threading
from typing import Optional

from PyQt6.QtCore import QObject, QThread, pyqtSignal


SAMPLE_RATE = 16000


# ── Porcupine backend ─────────────────────────────────────────────────────────

class PorcupineWakeWord:
    BUILT_IN_MAP = {
        "hey aria":     "americano",    # closest built-in to a custom name
        "hey computer": "computer",
        "jarvis":       "jarvis",
        "bumblebee":    "bumblebee",
        "porcupine":    "porcupine",
        "terminator":   "terminator",
        "blueberry":    "blueberry",
        "grapefruit":   "grapefruit",
        "grasshopper":  "grasshopper",
        "picovoice":    "picovoice",
        "americano":    "americano",
    }

    def __init__(self, access_key: str, wake_word: str):
        import pvporcupine
        keyword = self.BUILT_IN_MAP.get(wake_word.lower(), "bumblebee")
        self._porcupine = pvporcupine.create(
            access_key=access_key,
            keywords=[keyword],
        )
        self._frame_length = self._porcupine.frame_length

    @property
    def frame_length(self) -> int:
        return self._frame_length

    def process(self, pcm: list[int]) -> bool:
        return self._porcupine.process(pcm) >= 0

    def delete(self):
        self._porcupine.delete()


class PorcupineListener(QThread):
    detected = pyqtSignal()
    error    = pyqtSignal(str)

    def __init__(self, access_key: str, wake_word: str, parent=None):
        super().__init__(parent)
        self._key = access_key
        self._wake_word = wake_word
        self._running = False

    def run(self):
        import sounddevice as sd
        self._running = True
        try:
            detector = PorcupineWakeWord(self._key, self._wake_word)
        except Exception as e:
            self.error.emit(f"Porcupine init failed: {e}")
            return

        try:
            with sd.RawInputStream(
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="int16",
                blocksize=detector.frame_length,
            ) as stream:
                while self._running:
                    data, _ = stream.read(detector.frame_length)
                    pcm = list(data)
                    if detector.process(pcm):
                        self.detected.emit()
        except Exception as e:
            if self._running:
                self.error.emit(str(e))
        finally:
            detector.delete()

    def stop(self):
        self._running = False


# ── Vosk backend ──────────────────────────────────────────────────────────────

class VoskListener(QThread):
    """
    Vosk keyword spotting — no cloud, no key.
    Downloads a small model on first run.
    """
    detected = pyqtSignal()
    error    = pyqtSignal(str)

    MODEL_URL = "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip"

    def __init__(self, wake_word: str, parent=None):
        super().__init__(parent)
        self._wake_word = wake_word.lower()
        self._running = False

    def _ensure_model(self) -> str:
        from pathlib import Path
        import urllib.request
        import zipfile

        model_dir = Path.home() / ".aria-assistant" / "vosk-model"
        if model_dir.exists():
            return str(model_dir)

        zip_path = model_dir.parent / "vosk-model.zip"
        print("[VoskListener] Downloading Vosk model (one-time, ~50MB)…")
        urllib.request.urlretrieve(self.MODEL_URL, zip_path)
        with zipfile.ZipFile(zip_path, "r") as z:
            z.extractall(model_dir.parent)
        # rename extracted folder
        extracted = next(model_dir.parent.glob("vosk-model-small-en-us-*"))
        extracted.rename(model_dir)
        zip_path.unlink()
        return str(model_dir)

    def run(self):
        import json
        import sounddevice as sd
        self._running = True

        try:
            from vosk import Model, KaldiRecognizer
            model_path = self._ensure_model()
            model = Model(model_path)
            rec = KaldiRecognizer(model, SAMPLE_RATE)
            # Grammar mode — only recognise words in the wake phrase
            words = list(set(self._wake_word.split() + ["[unk]"]))
            rec = KaldiRecognizer(model, SAMPLE_RATE, json.dumps(words))
        except Exception as e:
            self.error.emit(f"Vosk init failed: {e}")
            return

        with sd.RawInputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="int16",
            blocksize=8000,
        ) as stream:
            while self._running:
                data, _ = stream.read(8000)
                if rec.AcceptWaveform(bytes(data)):
                    result = json.loads(rec.Result())
                    text = result.get("text", "").lower()
                    # Check if all words of wake phrase appear in transcript
                    if all(w in text for w in self._wake_word.split()):
                        self.detected.emit()

    def stop(self):
        self._running = False


# ── Wake Word Manager (public API) ────────────────────────────────────────────

class WakeWordEngine(QObject):
    """
    Manages wake word detection. Automatically chooses porcupine or vosk.
    Connect to `detected` to receive activation events.
    """
    detected = pyqtSignal()
    error    = pyqtSignal(str)
    status   = pyqtSignal(str)  # "listening" | "stopped" | "error"

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self._listener: Optional[QThread] = None

    def start(self):
        if self._listener and self._listener.isRunning():
            return

        engine = self.settings.get("wake_word_engine", "vosk")
        wake_word = self.settings.get("wake_word", "hey aria")

        if engine == "porcupine":
            key = self.settings.get("picovoice_key", "")
            if not key:
                self.error.emit("Picovoice API key not set. Using Vosk fallback.")
                engine = "vosk"
            else:
                self._listener = PorcupineListener(key, wake_word)

        if engine == "vosk":
            self._listener = VoskListener(wake_word)

        self._listener.detected.connect(self.detected)
        self._listener.error.connect(self._on_error)
        self._listener.start()
        self.status.emit("listening")

    def stop(self):
        if self._listener:
            self._listener.stop()
            self._listener.quit()
            self._listener.wait(2000)
            self._listener = None
        self.status.emit("stopped")

    def _on_error(self, msg: str):
        self.error.emit(msg)
        self.status.emit("error")

    @property
    def is_running(self) -> bool:
        return bool(self._listener and self._listener.isRunning())
