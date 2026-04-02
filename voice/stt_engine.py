"""
STT Engine — Speech-to-Text
Records audio from the default microphone and transcribes it.

Strategy:
  1. Use faster-whisper (CTranslate2 port) for fully local transcription.
  2. Fall back to OpenAI Whisper API if local model fails or isn't installed.
  3. Emit Qt signals so the UI can update in real time.

Recording approach:
  - sounddevice streams audio into a circular numpy buffer.
  - Recording starts on voice activity (simple energy threshold) or on
    explicit trigger from wake word / hotkey.
  - Recording stops after SILENCE_SECONDS of silence below threshold.
"""
from __future__ import annotations
import io
import threading
import time
import wave
from typing import Callable, Optional

import numpy as np
from PyQt6.QtCore import QObject, QThread, pyqtSignal


# ── Constants ─────────────────────────────────────────────────────────────────
SAMPLE_RATE   = 16000   # Whisper expects 16kHz mono
CHANNELS      = 1
BLOCK_SIZE    = 1024    # frames per sounddevice callback
SILENCE_SEC   = 1.5     # silence after speech triggers stop
ENERGY_THRESH = 0.015   # RMS energy for voice activity
MAX_SEC       = 30      # never record longer than this


# ── Audio recorder ────────────────────────────────────────────────────────────

class AudioRecorder:
    """
    Records audio from the mic until silence is detected.
    Thread-safe — can be called from any thread.
    """

    def __init__(self,
                 sample_rate: int = SAMPLE_RATE,
                 silence_sec: float = SILENCE_SEC,
                 energy_thresh: float = ENERGY_THRESH):
        self.sample_rate = sample_rate
        self.silence_sec = silence_sec
        self.energy_thresh = energy_thresh
        self._frames: list[np.ndarray] = []
        self._lock = threading.Lock()
        self._recording = False

    def record_until_silence(self,
                             on_start: Optional[Callable] = None,
                             on_stop: Optional[Callable] = None) -> bytes:
        """
        Blocks until recording completes.
        Returns raw WAV bytes (16-bit, 16kHz, mono).
        """
        import sounddevice as sd

        self._frames = []
        self._recording = True
        silence_frames = 0
        total_frames = 0
        max_frames = MAX_SEC * self.sample_rate
        speech_started = False
        silence_frames_needed = int(self.silence_sec * self.sample_rate / BLOCK_SIZE)

        def _callback(indata: np.ndarray, frames: int, time_info, status):
            nonlocal silence_frames, total_frames, speech_started
            chunk = indata[:, 0].copy()
            rms = float(np.sqrt(np.mean(chunk ** 2)))

            if rms > self.energy_thresh:
                if not speech_started:
                    speech_started = True
                    if on_start:
                        on_start()
                silence_frames = 0
                with self._lock:
                    self._frames.append(chunk)
            elif speech_started:
                silence_frames += 1
                with self._lock:
                    self._frames.append(chunk)
                if silence_frames >= silence_frames_needed:
                    raise sd.CallbackStop()

            total_frames += frames
            if total_frames >= max_frames:
                raise sd.CallbackStop()

        with sd.InputStream(
            samplerate=self.sample_rate,
            channels=CHANNELS,
            dtype="float32",
            blocksize=BLOCK_SIZE,
            callback=_callback,
        ):
            while self._recording:
                time.sleep(0.05)

        if on_stop:
            on_stop()

        return self._frames_to_wav()

    def stop(self):
        self._recording = False

    def _frames_to_wav(self) -> bytes:
        with self._lock:
            frames = list(self._frames)

        if not frames:
            return b""

        audio = np.concatenate(frames)
        pcm = (audio * 32767).clip(-32768, 32767).astype(np.int16)

        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(2)
            wf.setframerate(self.sample_rate)
            wf.writeframes(pcm.tobytes())
        return buf.getvalue()


# ── Transcription engines ─────────────────────────────────────────────────────

class LocalWhisper:
    """
    faster-whisper local transcription.
    Model is downloaded once to ~/.cache/huggingface/hub/.
    """

    def __init__(self, model_size: str = "base.en"):
        self._model = None
        self._model_size = model_size

    def _load(self):
        if self._model is None:
            from faster_whisper import WhisperModel
            self._model = WhisperModel(
                self._model_size,
                device="cpu",
                compute_type="int8",
            )

    def transcribe(self, wav_bytes: bytes) -> str:
        self._load()
        import io
        segments, _ = self._model.transcribe(
            io.BytesIO(wav_bytes),
            language="en",
            beam_size=5,
        )
        return " ".join(s.text.strip() for s in segments).strip()


class OpenAIWhisper:
    """Fallback: OpenAI Whisper API transcription."""

    def __init__(self, api_key: str):
        self._api_key = api_key

    def transcribe(self, wav_bytes: bytes) -> str:
        import openai
        client = openai.OpenAI(api_key=self._api_key)
        response = client.audio.transcriptions.create(
            model="whisper-1",
            file=("audio.wav", wav_bytes, "audio/wav"),
        )
        return response.text.strip()


# ── Qt worker thread for recording + transcription ────────────────────────────

class STTWorker(QThread):
    """
    Runs in a background thread:
      1. Records audio until silence
      2. Transcribes it
      3. Emits result
    """
    started_speaking  = pyqtSignal()
    finished_speaking = pyqtSignal()
    transcription     = pyqtSignal(str)
    error             = pyqtSignal(str)

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self._recorder = AudioRecorder(
            silence_sec=float(settings.get("stt_silence_sec", SILENCE_SEC)),
            energy_thresh=float(settings.get("stt_energy_thresh", ENERGY_THRESH)),
        )

    def run(self):
        try:
            wav = self._recorder.record_until_silence(
                on_start=self.started_speaking.emit,
                on_stop=self.finished_speaking.emit,
            )
            if not wav:
                return

            text = self._transcribe(wav)
            if text:
                self.transcription.emit(text)
        except Exception as e:
            self.error.emit(str(e))

    def _transcribe(self, wav_bytes: bytes) -> str:
        stt_engine = self.settings.get("stt_engine", "local_whisper")

        if stt_engine == "openai_whisper":
            key = self.settings.get("api_key", "")
            if not key:
                raise ValueError("OpenAI API key not set")
            return OpenAIWhisper(key).transcribe(wav_bytes)

        # Default: local faster-whisper
        model_size = self.settings.get("whisper_model", "base.en")
        return LocalWhisper(model_size).transcribe(wav_bytes)

    def stop(self):
        self._recorder.stop()


# ── STT Engine (public API) ───────────────────────────────────────────────────

class STTEngine(QObject):
    """
    High-level STT manager.  Call start_listening() to begin a recording.
    Connect to `transcription` signal to receive text.
    """
    transcription     = pyqtSignal(str)
    started_speaking  = pyqtSignal()
    finished_speaking = pyqtSignal()
    error             = pyqtSignal(str)

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self._worker: Optional[STTWorker] = None

    def start_listening(self):
        if self._worker and self._worker.isRunning():
            return
        self._worker = STTWorker(self.settings, self)
        self._worker.transcription.connect(self.transcription)
        self._worker.started_speaking.connect(self.started_speaking)
        self._worker.finished_speaking.connect(self.finished_speaking)
        self._worker.error.connect(self.error)
        self._worker.start()

    def stop_listening(self):
        if self._worker:
            self._worker.stop()

    @property
    def is_listening(self) -> bool:
        return bool(self._worker and self._worker.isRunning())
