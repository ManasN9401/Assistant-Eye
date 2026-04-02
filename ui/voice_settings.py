"""
Voice Settings page — added to the control panel in Phase 2.
Configures STT, TTS, wake word, and shows live voice status.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QScrollArea, QSizePolicy, QSlider, QSpacerItem,
    QVBoxLayout, QWidget,
)

from core.settings import Settings


def _label(text: str, obj_name: str = "") -> QLabel:
    lbl = QLabel(text)
    if obj_name:
        lbl.setObjectName(obj_name)
    return lbl


def _divider():
    from PyQt6.QtWidgets import QFrame
    d = QFrame()
    d.setObjectName("divider")
    d.setFrameShape(QFrame.Shape.HLine)
    return d


def _spacer(h=False):
    p = QSizePolicy.Policy.Expanding
    return QSpacerItem(0, 0, p if h else QSizePolicy.Policy.Minimum,
                       QSizePolicy.Policy.Minimum if h else p)


class VoiceSettingsPage(QWidget):
    settings_changed = pyqtSignal()
    test_tts         = pyqtSignal(str)   # text to speak
    toggle_wake_word = pyqtSignal(bool)  # True = start, False = stop
    trigger_listen   = pyqtSignal()

    def __init__(self, settings: Settings):
        super().__init__()
        self.settings = settings
        self._build()

    def _build(self):
        # Outer layout just holds the scroll area
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        inner = QWidget()
        vb = QVBoxLayout(inner)
        vb.setContentsMargins(28, 28, 28, 28)
        vb.setSpacing(14)

        scroll.setWidget(inner)
        outer.addWidget(scroll)

        vb.addWidget(_label("Voice Settings", "section-title"))
        vb.addWidget(_label("Configure speech recognition, text-to-speech, and wake word.", "section-sub"))

        # ── STT ──────────────────────────────────────────────
        vb.addWidget(_label("Speech Recognition (STT)", "card-title"))

        vb.addWidget(_label("Engine", "label-field"))
        self._stt_engine = QComboBox()
        self._stt_engine.addItem("Local Whisper (offline)", "local_whisper")
        self._stt_engine.addItem("OpenAI Whisper API", "openai_whisper")
        idx = self._stt_engine.findData(self.settings.get("stt_engine", "local_whisper"))
        self._stt_engine.setCurrentIndex(max(0, idx))
        vb.addWidget(self._stt_engine)

        vb.addWidget(_label("Whisper model size (local only)", "label-field"))
        self._whisper_model = QComboBox()
        for m in ["tiny.en", "base.en", "small.en", "medium.en"]:
            self._whisper_model.addItem(m)
        self._whisper_model.setCurrentText(self.settings.get("whisper_model", "base.en"))
        vb.addWidget(self._whisper_model)

        # Test listen button
        listen_btn = QPushButton("▶  Test Microphone")
        listen_btn.clicked.connect(self.trigger_listen)
        vb.addWidget(listen_btn)

        vb.addWidget(_divider())

        # ── TTS ──────────────────────────────────────────────
        vb.addWidget(_label("Text-to-Speech (TTS)", "card-title"))

        self._tts_enabled = QCheckBox("Enable voice responses")
        self._tts_enabled.setChecked(self.settings.get("tts_enabled", True))
        vb.addWidget(self._tts_enabled)

        vb.addWidget(_label("Engine", "label-field"))
        self._tts_engine = QComboBox()
        self._tts_engine.addItem("pyttsx3 (offline)", "pyttsx3")
        self._tts_engine.addItem("ElevenLabs (cloud)", "elevenlabs")
        idx = self._tts_engine.findData(self.settings.get("tts_engine", "pyttsx3"))
        self._tts_engine.setCurrentIndex(max(0, idx))
        vb.addWidget(self._tts_engine)

        vb.addWidget(_label("ElevenLabs API Key (cloud only)", "label-field"))
        self._el_key = QLineEdit(self.settings.get("elevenlabs_api_key", ""))
        self._el_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._el_key.setPlaceholderText("xi-…")
        vb.addWidget(self._el_key)

        vb.addWidget(_label("Speech rate", "label-field"))
        rate_row = QHBoxLayout()
        self._tts_rate = QSlider(Qt.Orientation.Horizontal)
        self._tts_rate.setRange(100, 280)
        self._tts_rate.setValue(self.settings.get("tts_rate", 185))
        self._rate_lbl = QLabel(str(self._tts_rate.value()))
        self._rate_lbl.setObjectName("label-mono")
        self._rate_lbl.setFixedWidth(36)
        self._tts_rate.valueChanged.connect(lambda v: self._rate_lbl.setText(str(v)))
        rate_row.addWidget(self._tts_rate)
        rate_row.addWidget(self._rate_lbl)
        vb.addLayout(rate_row)

        test_row = QHBoxLayout()
        self._tts_test_input = QLineEdit()
        self._tts_test_input.setPlaceholderText("Text to test…")
        self._tts_test_input.setText(f"Hello, I am {self.settings.assistant_name}.")
        test_btn = QPushButton("▶  Speak")
        test_btn.setFixedWidth(80)
        test_btn.clicked.connect(lambda: self.test_tts.emit(self._tts_test_input.text()))
        test_row.addWidget(self._tts_test_input)
        test_row.addWidget(test_btn)
        vb.addLayout(test_row)

        vb.addWidget(_divider())

        # ── Wake word ─────────────────────────────────────────
        vb.addWidget(_label("Wake Word", "card-title"))

        self._wake_enabled = QCheckBox("Enable wake word detection")
        self._wake_enabled.setChecked(self.settings.get("wake_word_active", False))
        self._wake_enabled.toggled.connect(self.toggle_wake_word)
        vb.addWidget(self._wake_enabled)

        vb.addWidget(_label("Wake phrase", "label-field"))
        self._wake_word = QLineEdit(self.settings.get("wake_word", "hey aria"))
        vb.addWidget(self._wake_word)

        vb.addWidget(_label("Engine", "label-field"))
        self._wake_engine = QComboBox()
        self._wake_engine.addItem("Vosk (offline, no key needed)", "vosk")
        self._wake_engine.addItem("Porcupine (accurate, free key)", "porcupine")
        idx = self._wake_engine.findData(self.settings.get("wake_word_engine", "vosk"))
        self._wake_engine.setCurrentIndex(max(0, idx))
        vb.addWidget(self._wake_engine)

        vb.addWidget(_label("Picovoice key (Porcupine only)", "label-field"))
        self._pico_key = QLineEdit(self.settings.get("picovoice_key", ""))
        self._pico_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._pico_key.setPlaceholderText("Get free key at console.picovoice.ai")
        vb.addWidget(self._pico_key)

        # Wake status indicator
        self._wake_status = _label("Wake word: inactive", "label-mono")
        vb.addWidget(self._wake_status)

        vb.addWidget(_divider())

        save_btn = QPushButton("Save Voice Settings")
        save_btn.setObjectName("btn-accent")
        save_btn.setFixedWidth(180)
        save_btn.clicked.connect(self._save)
        vb.addWidget(save_btn)

        vb.addSpacerItem(_spacer(h=False))

    def _save(self):
        self.settings.update({
            "stt_engine":          self._stt_engine.currentData(),
            "whisper_model":       self._whisper_model.currentText(),
            "tts_enabled":         self._tts_enabled.isChecked(),
            "tts_engine":          self._tts_engine.currentData(),
            "elevenlabs_api_key":  self._el_key.text(),
            "tts_rate":            self._tts_rate.value(),
            "wake_word":           self._wake_word.text().strip().lower(),
            "wake_word_engine":    self._wake_engine.currentData(),
            "picovoice_key":       self._pico_key.text(),
            "wake_word_active":    self._wake_enabled.isChecked(),
        })
        self.settings_changed.emit()

    def set_wake_status(self, status: str):
        labels = {
            "listening": "Wake word: listening…",
            "stopped":   "Wake word: inactive",
            "error":     "Wake word: error — check settings",
        }
        self._wake_status.setText(labels.get(status, status))

    def set_voice_state(self, state: str):
        """Update display based on voice coordinator state."""
        colors = {
            "idle":      "#52525b",
            "recording": "#22c55e",
            "thinking":  "#e8a020",
            "speaking":  "#6366f1",
        }
