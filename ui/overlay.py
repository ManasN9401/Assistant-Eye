"""
Overlay — always-on-top floating assistant widget.
Pill-shaped, draggable, expandable. Toggle with Ctrl+Space (Phase 2 hotkey).
"""
from __future__ import annotations

from PyQt6.QtCore import (
    Qt, QPoint, QRect, QSize, QTimer, QPropertyAnimation,
    QEasingCurve, pyqtSignal, QThread,
)
from PyQt6.QtGui import (
    QColor, QPainter, QPainterPath, QFont, QPen, QBrush,
    QLinearGradient, QMouseEvent,
)
from PyQt6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QSizePolicy, QTextEdit, QVBoxLayout, QWidget,
)

from core.settings import Settings
from core.ai_engine import AIEngine
from core.function_registry import FunctionRegistry


PILL_H = 52          # Collapsed height
PILL_W = 340         # Width
EXPANDED_H = 240     # Expanded height (shows response)
RADIUS = 26

AMBER = QColor("#e8a020")
BG    = QColor(14, 14, 17, 235)   # near-black, slightly transparent
BG2   = QColor(20, 20, 24, 235)
BORDER = QColor(40, 40, 50, 200)
TEXT  = QColor(209, 209, 216)
TEXT2 = QColor(113, 113, 122)


class OverlayWorker(QThread):
    token = pyqtSignal(str)
    done  = pyqtSignal()
    err   = pyqtSignal(str)

    def __init__(self, engine, msg, system):
        super().__init__()
        self.engine = engine
        self.msg = msg
        self.system = system

    def run(self):
        try:
            for t in self.engine.chat_stream(self.msg, self.system):
                self.token.emit(t)
            self.done.emit()
        except Exception as e:
            self.err.emit(str(e))


class Overlay(QWidget):
    """Frameless, always-on-top pill widget. Phase 2: voice state + external tokens."""

    command_entered = pyqtSignal(str)

    def __init__(self, settings: Settings, engine: AIEngine, registry: FunctionRegistry):
        super().__init__()
        self.settings = settings
        self.engine = engine
        self.registry = registry
        self._drag_pos: QPoint | None = None
        self._expanded = False
        self._worker: OverlayWorker | None = None
        self._response_text = ""
        self._blink_on = True

        self._setup_window()
        self._build_ui()
        self._restore_position()

        # Blink timer for the status dot while thinking
        self._blink_timer = QTimer(self)
        self._blink_timer.setInterval(500)
        self._blink_timer.timeout.connect(self._blink)

    def _setup_window(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedWidth(PILL_W)
        self.setFixedHeight(PILL_H)

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── Pill container ────────────────────────────────────
        self._pill = QWidget(self)
        self._pill.setFixedWidth(PILL_W)
        self._pill.setFixedHeight(PILL_H)
        outer.addWidget(self._pill)

        pill_layout = QHBoxLayout(self._pill)
        pill_layout.setContentsMargins(14, 0, 10, 0)
        pill_layout.setSpacing(8)

        # Status dot
        self._dot = QLabel("●")
        self._dot.setFixedWidth(12)
        self._dot.setFont(QFont("Arial", 8))
        self._dot.setStyleSheet("color: #52525b;")
        pill_layout.addWidget(self._dot)

        # Assistant name tag
        self._name_lbl = QLabel(self.settings.assistant_name.upper())
        self._name_lbl.setFont(QFont("Courier New", 10, QFont.Weight.Bold))
        self._name_lbl.setStyleSheet("color: #e8a020; letter-spacing: 3px;")
        self._name_lbl.setFixedWidth(70)
        pill_layout.addWidget(self._name_lbl)

        # Sign Language Indicator
        self._sign_icon = QLabel("🤟")
        self._sign_icon.setFont(QFont("Segoe UI Emoji", 12))
        self._sign_icon.setStyleSheet("color: #22c55e;")
        self._sign_icon.setVisible(False)
        pill_layout.addWidget(self._sign_icon)

        # Separator
        sep = QLabel("|")
        sep.setStyleSheet("color: #27272a;")
        pill_layout.addWidget(sep)

        # Text input
        self._input = QLineEdit()
        self._input.setPlaceholderText("Ask me anything…")
        self._input.setStyleSheet("""
            QLineEdit {
                background: transparent;
                border: none;
                color: #d1d1d8;
                font-size: 13px;
                padding: 0px;
            }
        """)
        self._input.returnPressed.connect(self._on_send)
        pill_layout.addWidget(self._input)

        # Send button
        self._send_btn = QPushButton("→")
        self._send_btn.setFixedSize(28, 28)
        self._send_btn.setStyleSheet("""
            QPushButton {
                background: #1a1a22;
                color: #e8a020;
                border: 1px solid #27272a;
                border-radius: 14px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover { background: #27272a; }
        """)
        self._send_btn.clicked.connect(self._on_send)
        pill_layout.addWidget(self._send_btn)

        # Close / collapse button
        self._close_btn = QPushButton("×")
        self._close_btn.setFixedSize(22, 22)
        self._close_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #3f3f46;
                border: none;
                font-size: 16px;
            }
            QPushButton:hover { color: #ef4444; }
        """)
        self._close_btn.clicked.connect(self.hide)
        pill_layout.addWidget(self._close_btn)

        # ── Expansion panel ───────────────────────────────────
        self._expansion = QWidget(self)
        self._expansion.setFixedWidth(PILL_W)
        self._expansion.setFixedHeight(0)  # starts collapsed
        self._expansion.setVisible(False)
        outer.addWidget(self._expansion)

        exp_layout = QVBoxLayout(self._expansion)
        exp_layout.setContentsMargins(14, 10, 14, 14)
        exp_layout.setSpacing(0)

        self._response = QTextEdit()
        self._response.setReadOnly(True)
        self._response.setStyleSheet("""
            QTextEdit {
                background: transparent;
                border: none;
                color: #d1d1d8;
                font-size: 12px;
                line-height: 1.5;
            }
            QScrollBar:vertical { width: 4px; background: transparent; }
            QScrollBar::handle:vertical { background: #27272a; border-radius: 2px; }
        """)
        exp_layout.addWidget(self._response)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        total_h = PILL_H + (self._expansion.height() if self._expanded else 0)
        rect = QRect(0, 0, PILL_W, total_h)

        path = QPainterPath()
        path.addRoundedRect(0, 0, PILL_W, total_h, RADIUS, RADIUS)

        # Background
        painter.fillPath(path, QBrush(BG))

        # Border
        painter.setPen(QPen(BORDER, 1))
        painter.drawPath(path)

        # Subtle amber line at top
        accent_path = QPainterPath()
        accent_path.moveTo(RADIUS, 0)
        accent_path.lineTo(PILL_W - RADIUS, 0)
        pen = QPen(AMBER, 1.5)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawPath(accent_path)

    # ── Dragging ──────────────────────────────────────────────────────────────

    def mousePressEvent(self, e: QMouseEvent):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e: QMouseEvent):
        if self._drag_pos and e.buttons() == Qt.MouseButton.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, e: QMouseEvent):
        if self._drag_pos:
            pos = self.pos()
            self.settings.update({"overlay_x": pos.x(), "overlay_y": pos.y()})
            self._drag_pos = None

    # ── State management ──────────────────────────────────────────────────────

    def _set_state(self, state: str):
        """state: idle | ready | thinking | error"""
        colors = {
            "idle":     "#52525b",
            "ready":    "#22c55e",
            "thinking": "#e8a020",
            "error":    "#ef4444",
        }
        self._dot.setStyleSheet(f"color: {colors.get(state, '#52525b')};")

    def _expand(self):
        if self._expanded:
            return
        self._expanded = True
        self._expansion.setVisible(True)
        self.setFixedHeight(PILL_H + EXPANDED_H)
        self._expansion.setFixedHeight(EXPANDED_H)
        self.update()

    def _collapse(self):
        if not self._expanded:
            return
        self._expanded = False
        self._expansion.setFixedHeight(0)
        self._expansion.setVisible(False)
        self.setFixedHeight(PILL_H)
        self.update()

    def _blink(self):
        self._blink_on = not self._blink_on
        color = "#e8a020" if self._blink_on else "#52525b"
        self._dot.setStyleSheet(f"color: {color};")

    # ── Chat logic ────────────────────────────────────────────────────────────

    def _on_send(self):
        text = self._input.text().strip()
        if not text:
            return
        self._input.clear()
        self._response_text = ""
        self._response.clear()
        self._expand()
        self._set_state("thinking")
        self._blink_timer.start()
        # Route through VoiceCoordinator (main.py wires command_entered → voice.send_text)
        self.command_entered.emit(text)

    def _on_send_direct(self, text: str):
        """Used when no VoiceCoordinator is available (standalone mode)."""
        system = self.registry.get_system_prompt() or ""
        if self._worker and self._worker.isRunning():
            return
        self._worker = OverlayWorker(self.engine, text, system)
        self._worker.token.connect(self._on_token)
        self._worker.done.connect(self._on_done)
        self._worker.err.connect(self._on_err)
        self._worker.start()

    def _on_token(self, token: str):
        self._response_text += token
        self._response.setPlainText(self._response_text)
        self._response.verticalScrollBar().setValue(
            self._response.verticalScrollBar().maximum()
        )

    def _on_done(self):
        self._blink_timer.stop()
        self._set_state("ready")

    def _on_err(self, msg: str):
        self._blink_timer.stop()
        self._set_state("error")
        self._response.setPlainText(f"Error: {msg}")

    # ── Public API ────────────────────────────────────────────────────────────

    def refresh_name(self):
        self._name_lbl.setText(self.settings.assistant_name.upper())

    def toggle(self):
        if self.isVisible():
            self.hide()
        else:
            self._collapse()
            self._set_state("ready" if self.registry.get_active() else "idle")
            self.show()

    # ── Phase 2 public API (called by VoiceCoordinator) ─────────────────────

    def set_voice_state(self, state: str):
        """Reflect voice pipeline state in the dot indicator."""
        state_map = {
            "idle":      "idle",
            "recording": "ready",
            "thinking":  "thinking",
            "speaking":  "ready",
        }
        self._set_state(state_map.get(state, "idle"))
        if state == "thinking":
            self._blink_timer.start()
        else:
            self._blink_timer.stop()
            self._blink_on = True
            colors = {"idle":"#52525b","ready":"#22c55e","thinking":"#e8a020"}
            col = colors.get(state_map.get(state,"idle"), "#52525b")
            self._dot.setStyleSheet(f"color: {col};")

    def set_sign_language_mode(self, active: bool):
        """Show or hide the sign language indicator."""
        self._sign_icon.setVisible(active)

    def show_transcription(self, text: str):
        """Display what was heard above the response."""
        self._expand()
        self._response.setPlainText(f"[heard] {text}\n")
        self._response_text = ""

    def append_token(self, token: str):
        """Stream AI response tokens into the expansion panel."""
        if not self._expanded:
            self._expand()
        self._response_text += token
        self._response.setPlainText(self._response_text)
        self._response.verticalScrollBar().setValue(
            self._response.verticalScrollBar().maximum()
        )

    def end_response(self):
        self._blink_timer.stop()
        self._set_state("ready")

    def _restore_position(self):
        x = self.settings.get("overlay_x", 80)
        y = self.settings.get("overlay_y", 80)
        self.move(x, y)
