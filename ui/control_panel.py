"""
Control Panel — main application window. Phase 2 update.
Tabs: Dashboard · AI Models · Voice · Functions · Settings
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSize
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QApplication, QComboBox, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMainWindow,
    QPlainTextEdit, QPushButton, QSizePolicy, QSlider,
    QSpacerItem, QStackedWidget, QTextEdit, QVBoxLayout, QWidget,
)

from core.settings import Settings, AI_PROVIDERS
from core.ai_engine import AIEngine
from core.function_registry import FunctionRegistry
from ui.voice_settings import VoiceSettingsPage
from ui.visual_settings import VisualSettingsPage


# ── Worker thread for AI calls ────────────────────────────────────────────────

class ChatWorker(QThread):
    token_received = pyqtSignal(str)
    finished       = pyqtSignal()
    error          = pyqtSignal(str)

    def __init__(self, engine, message, system):
        super().__init__()
        self.engine  = engine
        self.message = message
        self.system  = system

    def run(self):
        try:
            for token in self.engine.chat_stream(self.message, self.system):
                self.token_received.emit(token)
            self.finished.emit()
        except Exception as e:
            self.error.emit(str(e))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _label(text, obj_name=""):
    lbl = QLabel(text)
    if obj_name:
        lbl.setObjectName(obj_name)
    return lbl

def _spacer(h=True):
    p = QSizePolicy.Policy.Expanding
    return QSpacerItem(0, 0, p if h else QSizePolicy.Policy.Minimum,
                       QSizePolicy.Policy.Minimum if h else p)

def _divider():
    d = QFrame()
    d.setObjectName("divider")
    d.setFrameShape(QFrame.Shape.HLine)
    return d


# ── Pages ─────────────────────────────────────────────────────────────────────

class DashboardPage(QWidget):
    send_command = pyqtSignal(str)

    def __init__(self, settings, registry):
        super().__init__()
        self.settings = settings
        self.registry = registry
        self._build()

    def _build(self):
        vb = QVBoxLayout(self)
        vb.setContentsMargins(28, 28, 28, 28)
        vb.setSpacing(16)

        self._name_label = _label(self.settings.assistant_name, "section-title")
        vb.addWidget(self._name_label)
        vb.addWidget(_label("Control Panel  ·  Phase 2", "section-sub"))

        # Status row
        row = QWidget()
        rh  = QHBoxLayout(row)
        rh.setContentsMargins(0, 0, 0, 0)
        rh.setSpacing(24)
        self._status_dot  = QLabel("●")
        self._status_dot.setObjectName("status-dot-idle")
        self._status_text = QLabel("Idle")
        self._status_text.setObjectName("label-mono")
        self._voice_state = QLabel("Voice: off")
        self._voice_state.setObjectName("label-mono")
        rh.addWidget(self._status_dot)
        rh.addWidget(self._status_text)
        rh.addWidget(QLabel(" | "))
        rh.addWidget(self._voice_state)
        rh.addSpacerItem(_spacer())
        vb.addWidget(row)

        vb.addWidget(_divider())

        # Site row
        sr = QHBoxLayout()
        self._site_label = QLabel("No registry loaded")
        self._site_label.setObjectName("label-mono")
        sr.addWidget(QLabel("Site:"))
        sr.addWidget(self._site_label)
        sr.addSpacerItem(_spacer())

        # Extension status
        self._ext_dot = QLabel("●")
        self._ext_dot.setObjectName("status-dot-idle")
        self._ext_label = QLabel("Extension: disconnected")
        self._ext_label.setObjectName("label-mono")
        sr.addWidget(self._ext_dot)
        sr.addWidget(self._ext_label)
        vb.addLayout(sr)

        # Chat area
        self._chat = QTextEdit()
        self._chat.setReadOnly(True)
        self._chat.setMinimumHeight(260)
        self._chat.setPlaceholderText("Responses will appear here…")
        vb.addWidget(self._chat)

        # Input row
        ir = QHBoxLayout()
        self._input = QLineEdit()
        self._input.setPlaceholderText("Type a command or question…")
        self._input.returnPressed.connect(self._on_send)
        self._send_btn = QPushButton("Send")
        self._send_btn.setObjectName("btn-accent")
        self._send_btn.setFixedWidth(80)
        self._send_btn.clicked.connect(self._on_send)
        self._mic_btn = QPushButton("🎙")
        self._mic_btn.setFixedWidth(40)
        self._mic_btn.setToolTip("Click to listen (or say wake word)")
        ir.addWidget(self._input)
        ir.addWidget(self._mic_btn)
        ir.addWidget(self._send_btn)
        vb.addLayout(ir)

    def refresh(self):
        reg = self.registry.get_active()
        if reg:
            self._site_label.setText(f"{reg['name']}  ({reg['site']})")
            self._set_dot(self._status_dot, "ready")
            self._status_text.setText("Ready")
        else:
            self._site_label.setText("No registry loaded")
            self._set_dot(self._status_dot, "idle")
            self._status_text.setText("Idle — no site connected")

    def refresh_name(self):
        '''Update the dashboard heading when assistant name changes.'''
        self._name_label.setText(self.settings.assistant_name)

    def set_voice_state(self, state):
        labels = {"idle": "Voice: idle", "recording": "Voice: listening…",
                  "thinking": "Voice: thinking…", "speaking": "Voice: speaking"}
        self._voice_state.setText(labels.get(state, f"Voice: {state}"))

    def set_extension_status(self, connected: bool):
        if connected:
            self._set_dot(self._ext_dot, "ready")
            self._ext_label.setText("Extension: connected")
        else:
            self._set_dot(self._ext_dot, "idle")
            self._ext_label.setText("Extension: disconnected")

    def _set_dot(self, dot, state):
        mapping = {"idle": "status-dot-idle", "ready": "status-dot-ready",
                   "thinking": "status-dot-thinking", "error": "status-dot-error"}
        dot.setObjectName(mapping.get(state, "status-dot-idle"))
        dot.style().unpolish(dot)
        dot.style().polish(dot)

    def _on_send(self):
        text = self._input.text().strip()
        if not text:
            return
        self._input.clear()
        self._append_user(text)
        self.send_command.emit(text)

    def _append_user(self, text):
        self._chat.append(
            f'<span style="color:#71717a;font-size:11px;font-family:monospace">YOU</span><br>'
            f'<span style="color:#d1d1d8">{text}</span><br>'
        )

    def begin_assistant_response(self):
        name = "ASSISTANT"
        self._chat.append(
            f'<span style="color:#e8a020;font-size:11px;font-family:monospace">{name}</span><br>'
        )

    def append_token(self, token):
        self._chat.moveCursor(self._chat.textCursor().MoveOperation.End)
        self._chat.insertPlainText(token)

    def end_response(self):
        self._chat.append("")

    def show_transcription(self, text):
        self._append_user(f"[heard] {text}")


class ModelsPage(QWidget):
    settings_changed = pyqtSignal()

    def __init__(self, settings):
        super().__init__()
        self.settings = settings
        self._build()

    def _build(self):
        vb = QVBoxLayout(self)
        vb.setContentsMargins(28, 28, 28, 28)
        vb.setSpacing(14)
        vb.addWidget(_label("AI Models", "section-title"))
        vb.addWidget(_label("Select provider and model. Keys stored locally.", "section-sub"))

        vb.addWidget(_label("Provider", "label-field"))
        self._provider = QComboBox()
        for k, m in AI_PROVIDERS.items():
            self._provider.addItem(m["label"], k)
        self._provider.setCurrentIndex(max(0, self._provider.findData(self.settings.ai_provider)))
        self._provider.currentIndexChanged.connect(self._refresh_models)
        vb.addWidget(self._provider)

        vb.addWidget(_label("Model", "label-field"))
        self._model = QComboBox()
        self._refresh_models()
        vb.addWidget(self._model)

        vb.addWidget(_divider())

        for key_name, placeholder, label in [
            ("api_key",           "sk-…",       "OpenAI API Key"),
            ("anthropic_api_key", "sk-ant-…",   "Anthropic API Key"),
        ]:
            vb.addWidget(_label(label, "label-field"))
            field = QLineEdit(self.settings.get(key_name, ""))
            field.setEchoMode(QLineEdit.EchoMode.Password)
            field.setPlaceholderText(placeholder)
            setattr(self, f"_field_{key_name}", field)
            vb.addWidget(field)

        vb.addWidget(_divider())
        btn = QPushButton("Save Model Settings")
        btn.setObjectName("btn-accent")
        btn.setFixedWidth(180)
        btn.clicked.connect(self._save)
        vb.addWidget(btn)
        vb.addSpacerItem(_spacer(h=False))

    def _refresh_models(self):
        provider = self._provider.currentData()
        self._model.clear()
        for m in AI_PROVIDERS.get(provider, {}).get("models", []):
            self._model.addItem(m)
        idx = self._model.findText(self.settings.ai_model)
        if idx >= 0:
            self._model.setCurrentIndex(idx)

    def _save(self):
        self.settings.update({
            "ai_provider":        self._provider.currentData(),
            "ai_model":           self._model.currentText(),
            "api_key":            self._field_api_key.text(),
            "anthropic_api_key":  self._field_anthropic_api_key.text(),
        })
        self.settings_changed.emit()


class FunctionsPage(QWidget):
    registry_loaded = pyqtSignal()

    def __init__(self, settings, registry):
        super().__init__()
        self.settings  = settings
        self.registry  = registry
        self._registries = []
        self._build()

    def _build(self):
        vb = QVBoxLayout(self)
        vb.setContentsMargins(28, 28, 28, 28)
        vb.setSpacing(14)
        vb.addWidget(_label("Website Registries", "section-title"))
        vb.addWidget(_label("Load a registry to give the assistant actions on a site.", "section-sub"))

        vb.addWidget(_label("Available Registries", "label-field"))
        self._list = QListWidget()
        self._list.setMinimumHeight(140)
        self._list.currentRowChanged.connect(self._on_select)
        vb.addWidget(self._list)

        br = QHBoxLayout()
        load_btn = QPushButton("Load Selected")
        load_btn.setObjectName("btn-accent")
        load_btn.clicked.connect(self._load)
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.refresh)
        br.addWidget(load_btn)
        br.addWidget(refresh_btn)
        br.addSpacerItem(_spacer())
        vb.addLayout(br)

        vb.addWidget(_divider())
        vb.addWidget(_label("Function Preview", "label-field"))
        self._preview = QPlainTextEdit()
        self._preview.setReadOnly(True)
        self._preview.setMinimumHeight(160)
        self._preview.setFont(QFont("Courier New", 11))
        self._preview.setPlaceholderText("Select a registry to preview…")
        vb.addWidget(self._preview)
        vb.addSpacerItem(_spacer(h=False))
        self.refresh()

    def refresh(self):
        self._list.clear()
        self._registries = self.registry.list_registries()
        for r in self._registries:
            self._list.addItem(f"  {r['name']}  —  {r['site']}")

    def _on_select(self, idx):
        if idx < 0 or idx >= len(self._registries):
            return
        import json
        from pathlib import Path
        try:
            data = json.loads(Path(self._registries[idx]["file"]).read_text())
            lines = []
            for fn in data.get("functions", []):
                params = ", ".join(fn.get("params", {}).keys())
                lines += [f"{fn['name']}({params})", f"  → {fn['description']}", ""]
            self._preview.setPlainText("\n".join(lines))
        except Exception as e:
            self._preview.setPlainText(f"Error: {e}")

    def _load(self):
        idx = self._list.currentRow()
        if 0 <= idx < len(self._registries):
            if self.registry.load(self._registries[idx]["file"]):
                self.registry_loaded.emit()


class SettingsPage(QWidget):
    settings_changed = pyqtSignal()

    def __init__(self, settings):
        super().__init__()
        self.settings = settings
        self._build()

    def _build(self):
        vb = QVBoxLayout(self)
        vb.setContentsMargins(28, 28, 28, 28)
        vb.setSpacing(14)
        vb.addWidget(_label("Settings", "section-title"))
        vb.addWidget(_label("Personalise your assistant.", "section-sub"))

        vb.addWidget(_label("Assistant Name", "label-field"))
        self._name = QLineEdit(self.settings.assistant_name)
        vb.addWidget(self._name)

        vb.addWidget(_label("Overlay Hotkey", "label-field"))
        self._hotkey = QLineEdit(self.settings.get("overlay_hotkey", "ctrl+space"))
        vb.addWidget(self._hotkey)

        vb.addWidget(_label("Overlay Opacity", "label-field"))
        row = QHBoxLayout()
        self._opacity = QSlider(Qt.Orientation.Horizontal)
        self._opacity.setRange(40, 100)
        self._opacity.setValue(self.settings.get("overlay_opacity", 92))
        self._op_lbl  = QLabel(f"{self._opacity.value()}%")
        self._op_lbl.setObjectName("label-mono")
        self._op_lbl.setFixedWidth(36)
        self._opacity.valueChanged.connect(lambda v: self._op_lbl.setText(f"{v}%"))
        row.addWidget(self._opacity)
        row.addWidget(self._op_lbl)
        vb.addLayout(row)

        vb.addWidget(_divider())
        btn = QPushButton("Save Settings")
        btn.setObjectName("btn-accent")
        btn.setFixedWidth(140)
        btn.clicked.connect(self._save)
        vb.addWidget(btn)
        vb.addSpacerItem(_spacer(h=False))

    def _save(self):
        self.settings.update({
            "assistant_name":  self._name.text().strip() or self.settings.assistant_name,
            "overlay_hotkey":  self._hotkey.text().strip(),
            "overlay_opacity": self._opacity.value(),
        })
        self.settings_changed.emit()


# ── Main Window ───────────────────────────────────────────────────────────────

class ControlPanel(QMainWindow):
    def __init__(self, settings: Settings, registry: FunctionRegistry,
                 engine: AIEngine, voice=None, browser_bridge=None, executor=None, visual=None):
        super().__init__()
        self.settings       = settings
        self.registry       = registry
        self.engine         = engine
        self.voice          = voice
        self.browser_bridge = browser_bridge
        self.executor       = executor
        self.visual         = visual
        self._worker: ChatWorker | None = None
        self._build_ui()
        self._restore_geometry()

        # Poll extension connection every 2s
        from PyQt6.QtCore import QTimer
        self._ext_timer = QTimer(self)
        self._ext_timer.setInterval(2000)
        self._ext_timer.timeout.connect(self._poll_extension)
        self._ext_timer.start()

    def _build_ui(self):
        self.setWindowTitle(f"{self.settings.assistant_name} — Control Panel")
        self.setMinimumSize(880, 600)

        root = QWidget()
        rl   = QHBoxLayout(root)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(0)
        self.setCentralWidget(root)

        # ── Sidebar ───────────────────────────────────────────
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sv = QVBoxLayout(sidebar)
        sv.setContentsMargins(0, 0, 0, 0)
        sv.setSpacing(0)

        header = QWidget()
        header.setObjectName("sidebar-header")
        hv = QVBoxLayout(header)
        hv.setContentsMargins(16, 20, 16, 20)
        hv.setSpacing(2)
        self._sidebar_name = _label(self.settings.assistant_name.upper(), "app-name")
        hv.addWidget(self._sidebar_name)
        sv.addWidget(header)

        nav_items = [
            ("Dashboard", 0), ("AI Models", 1), ("Voice", 2),
            ("Visual", 3), ("Functions", 4), ("Settings", 5),
        ]
        self._nav_buttons = []
        for label, idx in nav_items:
            btn = QPushButton(f"  {label}")
            btn.setObjectName("nav-btn")
            btn.setProperty("active", "false")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _, i=idx: self._switch_page(i))
            sv.addWidget(btn)
            self._nav_buttons.append(btn)

        sv.addSpacerItem(_spacer(h=False))
        ver = _label("PHASE 3  ·  VOICE + VISUAL", "label-mono")
        ver.setContentsMargins(16, 8, 16, 16)
        sv.addWidget(ver)
        rl.addWidget(sidebar)

        # ── Content stack ─────────────────────────────────────
        cw = QWidget()
        cw.setObjectName("content-area")
        cw_vb = QVBoxLayout(cw)
        cw_vb.setContentsMargins(0, 0, 0, 0)
        cw_vb.setSpacing(0)

        self._stack         = QStackedWidget()
        self._dashboard     = DashboardPage(self.settings, self.registry)
        self._models        = ModelsPage(self.settings)
        self._voice_page    = VoiceSettingsPage(self.settings)
        self._visual_page   = VisualSettingsPage(self.settings)
        self._functions     = FunctionsPage(self.settings, self.registry)
        self._settings_page = SettingsPage(self.settings)

        for page in [self._dashboard, self._models, self._voice_page,
                     self._visual_page, self._functions, self._settings_page]:
            self._stack.addWidget(page)

        cw_vb.addWidget(self._stack)

        # Status bar
        sb = QWidget()
        sb.setObjectName("status-bar")
        sbh = QHBoxLayout(sb)
        sbh.setContentsMargins(16, 6, 16, 6)
        self._sb_label = _label("", "status-label")
        self._update_status_bar()
        sbh.addWidget(self._sb_label)
        cw_vb.addWidget(sb)

        rl.addWidget(cw)

        # ── Wire signals ──────────────────────────────────────
        self._dashboard.send_command.connect(self._on_command)
        self._models.settings_changed.connect(self._on_settings_changed)
        self._settings_page.settings_changed.connect(self._on_settings_changed)
        self._functions.registry_loaded.connect(self._on_registry_loaded)

        if self.voice:
            self._dashboard._mic_btn.clicked.connect(self.voice.trigger_listen)
            self._voice_page.test_tts.connect(lambda t: self.voice.tts.speak(t))
            self._voice_page.toggle_wake_word.connect(self._on_toggle_wake_word)
            self._voice_page.trigger_listen.connect(self.voice.trigger_listen)
            self._voice_page.settings_changed.connect(self._on_settings_changed)
            self.voice.state_changed.connect(self._dashboard.set_voice_state)
            self.voice.transcription.connect(self._dashboard.show_transcription)
            self.voice.response_token.connect(self._dashboard.append_token)
            self.voice.response_complete.connect(lambda _: self._dashboard.end_response())
            self.voice.response_complete.connect(
                lambda _: self._dashboard.begin_assistant_response() or None
            )

        if self.visual:
            self._visual_page.toggle_hand_tracking.connect(
                lambda on: self.visual.start_hand_tracking(self.settings.get("visual_camera", 0)) if on
                else self.visual.stop_hand_tracking()
            )
            self._visual_page.toggle_eye_tracking.connect(
                lambda on: self.visual.start_eye_tracking(self.settings.get("visual_camera", 0)) if on
                else self.visual.stop_eye_tracking()
            )
            self._visual_page.toggle_sign_language.connect(
                lambda on: self.visual.start_sign_language(self.settings.get("visual_camera", 0)) if on
                else self.visual.stop_sign_language()
            )
            self._visual_page.start_calibration.connect(self.visual.start_calibration)
            self._visual_page.advance_calibration.connect(self.visual.advance_calibration)
            self.visual.calibration_progress.connect(
                lambda n: self._visual_page.set_calibration_status(
                    f"Calibrating — point {n+1} of {9} collected"
                )
            )
            self.visual.calibration_complete.connect(
                lambda: self._visual_page.set_calibration_status("Calibrated ✓")
            )
            self.visual.error.connect(
                lambda m: self._visual_page.set_calibration_status(f"Error: {m}")
            )
            self._visual_page.settings_changed.connect(self._on_settings_changed)

        self._switch_page(0)

    def _switch_page(self, idx):
        self._stack.setCurrentIndex(idx)
        for i, btn in enumerate(self._nav_buttons):
            btn.setProperty("active", "true" if i == idx else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def _on_settings_changed(self):
        self.setWindowTitle(f"{self.settings.assistant_name} — Control Panel")
        self._sidebar_name.setText(self.settings.assistant_name.upper())
        self._dashboard.refresh_name()
        self._update_status_bar()
        self._dashboard.refresh()

    def _on_registry_loaded(self):
        self._dashboard.refresh()
        self._switch_page(0)

    def _update_status_bar(self):
        self._sb_label.setText(
            f"Provider: {self.settings.ai_provider}  ·  "
            f"Model: {self.settings.ai_model}  ·  "
            f"Bridge: ws://localhost:8765  ·  Config: ~/.aria-assistant/"
        )

    def _on_command(self, text):
        if self.voice:
            self.voice.send_text(text)
            self._dashboard.begin_assistant_response()
        else:
            if self._worker and self._worker.isRunning():
                return
            system = self.registry.get_system_prompt() or ""
            self._dashboard.begin_assistant_response()
            self._worker = ChatWorker(self.engine, text, system)
            self._worker.token_received.connect(self._dashboard.append_token)
            self._worker.finished.connect(self._dashboard.end_response)
            self._worker.error.connect(lambda m: self._dashboard.append_token(f"[Error: {m}]"))
            self._worker.start()

    def _on_toggle_wake_word(self, enabled):
        if not self.voice:
            return
        if enabled:
            self.voice.start_wake_word()
        else:
            self.voice.stop_wake_word()
        self.voice.wake.status.connect(self._voice_page.set_wake_status)

    def _poll_extension(self):
        if self.browser_bridge:
            connected = self.browser_bridge.server.is_connected
            self._dashboard.set_extension_status(connected)

    def on_page_changed(self, url, title):
        self._sb_label.setText(
            f"Page: {title[:40]}  ·  {url[:50]}"
        )

    def _restore_geometry(self):
        self.setGeometry(
            self.settings.get("window_x", 200), self.settings.get("window_y", 120),
            self.settings.get("window_width", 980), self.settings.get("window_height", 700),
        )

    def closeEvent(self, event):
        g = self.geometry()
        self.settings.update({
            "window_x": g.x(), "window_y": g.y(),
            "window_width": g.width(), "window_height": g.height(),
        })
        super().closeEvent(event)
