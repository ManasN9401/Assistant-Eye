"""
Voice Coordinator
Orchestrates the full voice pipeline:
  Wake word → STT recording → AI response → TTS playback

States:
  idle        → listening for wake word (if enabled)
  recording   → capturing user speech
  thinking    → AI request in flight
  speaking    → TTS playing back response
  
Emits Qt signals so the UI (overlay + control panel) can react to state changes.
"""
from __future__ import annotations
import re
from typing import Optional

from PyQt6.QtCore import QObject, pyqtSignal, QThread

from core.settings import Settings
from core.ai_engine import AIEngine
from core.function_registry import FunctionRegistry
from voice.stt_engine import STTEngine
from voice.tts_engine import TTSEngine
from voice.wake_word import WakeWordEngine


State = str  # "idle" | "recording" | "thinking" | "speaking"


class AIStreamWorker(QThread):
    token    = pyqtSignal(str)
    done     = pyqtSignal(str)   # full text
    error    = pyqtSignal(str)

    def __init__(self, engine, text, system, parent=None):
        super().__init__(parent)
        self._engine = engine
        self._text = text
        self._system = system

    def run(self):
        try:
            full = []
            for tok in self._engine.chat_stream(self._text, self._system):
                self.token.emit(tok)
                full.append(tok)
            self.done.emit("".join(full))
        except Exception as e:
            self.error.emit(str(e))


class VoiceCoordinator(QObject):
    # UI signals
    state_changed     = pyqtSignal(str)         # State name
    transcription     = pyqtSignal(str)         # what user said
    response_token    = pyqtSignal(str)         # streamed AI response
    response_complete = pyqtSignal(str)         # full response
    action_detected   = pyqtSignal(dict, dict)  # (action_def, params)
    error             = pyqtSignal(str)

    def __init__(
        self,
        settings: Settings,
        engine: AIEngine,
        registry: FunctionRegistry,
        parent=None,
    ):
        super().__init__(parent)
        self.settings = settings
        self.ai_engine = engine
        self.registry = registry

        self._state: State = "idle"
        self._ai_worker: Optional[AIStreamWorker] = None

        # Sub-engines
        self.stt = STTEngine(settings, self)
        self.tts = TTSEngine(settings, self)
        self.wake = WakeWordEngine(settings, self)

        # Wire up
        self.wake.detected.connect(self._on_wake)
        self.wake.error.connect(lambda m: self.error.emit(f"Wake word: {m}"))

        self.stt.transcription.connect(self._on_transcription)
        self.stt.started_speaking.connect(lambda: self._set_state("recording"))
        self.stt.error.connect(lambda m: self.error.emit(f"STT: {m}"))

        self.tts.finished.connect(self._on_tts_finished)
        self.tts.error.connect(lambda m: self.error.emit(f"TTS: {m}"))

    # ── State machine ─────────────────────────────────────────────────────────

    def _set_state(self, state: State):
        self._state = state
        self.state_changed.emit(state)

    @property
    def state(self) -> State:
        return self._state

    # ── Public API ────────────────────────────────────────────────────────────

    def start_wake_word(self):
        """Begin continuous background wake word listening."""
        self.wake.start()
        self._set_state("idle")

    def stop_wake_word(self):
        self.wake.stop()
        self._set_state("idle")

    def trigger_listen(self):
        """Manually trigger a recording session (hotkey or button press)."""
        if self._state in ("recording", "thinking"):
            return
        self.tts.stop()
        self._set_state("recording")
        self.stt.start_listening()

    def send_text(self, text: str):
        """Send a text command directly (bypasses STT)."""
        self._on_transcription(text)

    def stop(self):
        self.wake.stop()
        self.stt.stop_listening()
        self.tts.stop()
        self._set_state("idle")

    # ── Internal pipeline ─────────────────────────────────────────────────────

    def _on_wake(self):
        if self._state == "idle":
            self.trigger_listen()

    def _on_transcription(self, text: str):
        self.transcription.emit(text)
        self._set_state("thinking")
        system = self.registry.get_system_prompt() or (
            f"You are {self.settings.assistant_name}, a helpful assistant. Be concise."
        )
        self._ai_worker = AIStreamWorker(self.ai_engine, text, system, self)
        self._ai_worker.token.connect(self.response_token)
        self._ai_worker.done.connect(self._on_ai_done)
        self._ai_worker.error.connect(self._on_ai_error)
        self._ai_worker.start()

    def _on_ai_done(self, full_text: str):
        self.response_complete.emit(full_text)
        self._set_state("speaking")

        # Check for action JSON
        action, speech = self._parse_action(full_text)
        if action:
            fn_name = action.get("action", "")
            params  = action.get("params", {})
            fn_def  = self._find_function(fn_name)
            if fn_def:
                self.action_detected.emit(fn_def, params)

        # Speak the non-JSON part
        clean = speech.strip() or full_text.strip()
        if self.settings.get("tts_enabled", True):
            self.tts.speak(clean)
        else:
            self._on_tts_finished()

    def _on_ai_error(self, msg: str):
        self.error.emit(f"AI: {msg}")
        self._on_tts_finished()

    def _on_tts_finished(self):
        # Resume wake word listening if it was running
        self._set_state("idle")

    @staticmethod
    def _parse_action(text: str) -> tuple[Optional[dict], str]:
        """
        Extract the first JSON action block from the AI response.
        Returns (action_dict | None, remaining_text).
        """
        import json
        pattern = r'\{[^{}]*"action"[^{}]*\}'
        match = re.search(pattern, text)
        if not match:
            return None, text
        try:
            action = json.loads(match.group())
            remainder = text[:match.start()] + text[match.end():]
            return action, remainder.strip()
        except json.JSONDecodeError:
            return None, text

    def _find_function(self, name: str) -> Optional[dict]:
        reg = self.registry.get_active()
        if not reg:
            return None
        for fn in reg.get("functions", []):
            if fn["name"] == name:
                return fn
        return None
