from PyQt6.QtCore import Qt, QTimer, QRect, QRectF, QPoint, QPointF, QSize, pyqtSignal, QEasingCurve, QPropertyAnimation
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QFont, QPen, QBrush, QLinearGradient, QRadialGradient, QRegion
from PyQt6.QtWidgets import QWidget, QLabel, QVBoxLayout, QHBoxLayout, QApplication, QScrollArea
import time
import math
import random

class SignLanguageOverlay(QWidget):
    """
    A premium, video game-like dialogue box for sign language translation.
    Positions itself at the bottom middle of the screen.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.NoDropShadowWindowHint |
            Qt.WindowType.ToolTip
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        
        # UI State
        self.w, self.h = 800, 140
        self.is_minimized = False
        self.min_size = 160
        self._dragging = False
        self._resizing = False
        self._drag_pos = QPoint()
        self.last_update_time = 0
        self.idle_timeout = 3.0 # seconds
        
        self.setStyleSheet("background: transparent; border: none;")
        self.resize(self.w, self.h)
        
        # Center bottom
        screen = QApplication.primaryScreen().geometry()
        self.move((screen.width() - self.w) // 2, screen.height() - self.h - 80)
        
        # Layout and Scroll Area
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(20, 40, 20, 20)
        
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet("background: transparent; border: none;")
        
        self.content = QLabel()
        self.content.setWordWrap(True)
        self.content.setStyleSheet("color: #DCDDEB; background: transparent;")
        self.content.setFont(QFont("Outfit", 18))
        self.content.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        
        self.scroll.setWidget(self.content)
        self.layout.addWidget(self.scroll)
        
        self.full_text = ""
        self.current_word = ""
        self.is_paused = False
        self.is_hovered = False
        
        # Idle/Visibility timer
        self.visibility_timer = QTimer(self)
        self.visibility_timer.timeout.connect(self.update)
        self.visibility_timer.start(30) # High frequency for animations
        
        self.show()
        
    def toggle_minimize(self):
        self.is_minimized = not self.is_minimized
        
        # Animate size change
        self.anim = QPropertyAnimation(self, b"size")
        self.anim.setDuration(400)
        self.anim.setEasingCurve(QEasingCurve.Type.InOutQuart)
        
        if self.is_minimized:
            self.old_size = self.size()
            self.scroll.hide()
            self.layout.setContentsMargins(0, 0, 0, 0)
            self.anim.setEndValue(QSize(self.min_size, self.min_size))
            self.anim.finished.connect(lambda: self.setFixedSize(self.min_size, self.min_size))
            self.clearMask()
        else:
            self.setMinimumSize(0, 0)
            self.setMaximumSize(16777215, 16777215)
            self.scroll.show()
            self.layout.setContentsMargins(20, 40, 20, 20)
            self.anim.setEndValue(self.old_size)
        
        self.anim.start()
        
        if self.is_minimized:
            self.visibility_timer.setInterval(30)
        else:
            self.visibility_timer.setInterval(500)
        self.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.clearMask()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if not self.is_minimized and event.pos().x() > self.width() - 40 and event.pos().y() < 40:
                self.toggle_minimize()
                return
            
            if not self.is_minimized and event.pos().x() > self.width() - 20 and event.pos().y() > self.height() - 20:
                self._resizing = True
            else:
                self._dragging = True
                self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._dragging:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()
        elif self._resizing:
            new_w = max(200, event.pos().x())
            new_h = max(100, event.pos().y())
            self.resize(new_w, new_h)
            self.w, self.h = new_w, new_h
            event.accept()

    def mouseReleaseEvent(self, event):
        self._dragging = False
        self._resizing = False

    def mouseDoubleClickEvent(self, event):
        if self.is_minimized:
            self.toggle_minimize()

    def enterEvent(self, event):
        self.is_hovered = True
        self.update()

    def leaveEvent(self, event):
        self.is_hovered = False
        self.update()

    def update_translation(self, full: str, word: str, letter: str = "", paused: bool = False):
        import time
        self.last_update_time = time.time()
        self.full_text = full
        self.current_word = word
        self.is_paused = paused
        
        display_text = self.full_text
        if self.current_word:
             display_text += (" " if display_text else "") + self.current_word
        
        if self.is_paused:
             self.content.setText(display_text + " [PAUSED]")
        else:
             self.content.setText(display_text)
             
        QTimer.singleShot(10, lambda: self.scroll.verticalScrollBar().setValue(
            self.scroll.verticalScrollBar().maximum()
        ))
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        now = time.time()
        is_active = (now - self.last_update_time < self.idle_timeout)
        should_be_opaque = self.is_hovered or is_active
        
        # Pulse phase (0 to 1.0)
        pulse = (math.sin(now * 3) + 1) / 2

        target_opacity = 0.95 if should_be_opaque else 0.2
        if abs(self.windowOpacity() - target_opacity) > 0.01:
            self.setWindowOpacity(target_opacity)

        if self.is_minimized:
            # Minimalistic Holo Circle
            rect = QRectF(self.rect())
            center = rect.center()
            core_radius = 28
            base_col = QColor(255, 110, 40) if self.is_paused else QColor(100, 255, 200)

            # Core Background
            painter.setBrush(QBrush(QColor(18, 18, 24, 230)))
            painter.setPen(QPen(base_col, 2))
            painter.drawEllipse(center, core_radius, core_radius)

            # Subtle pulsing outer ring
            glow_radius = core_radius + 4 + (3 * pulse)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(base_col.red(), base_col.green(), base_col.blue(), 100), 1))
            painter.drawEllipse(center, glow_radius, glow_radius)

            # Text Label
            painter.setFont(QFont("Outfit", 12, QFont.Weight.Bold))
            painter.setPen(base_col)
            painter.drawText(int(center.x() - 20), int(center.y() - 10), 40, 20, Qt.AlignmentFlag.AlignCenter, "ASL")
            return

        # ── Expanded Mode ──────────────────
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), 4, 4)
        
        painter.fillPath(path, QBrush(QColor(30, 32, 38, 230)))
        painter.setPen(QPen(QColor(70, 75, 85, 255), 1))
        painter.drawPath(path)
        
        painter.setPen(QColor(150, 155, 170))
        painter.setFont(QFont("Outfit", 9, QFont.Weight.Bold))
        painter.drawText(20, 25, "TRANSLATION")
        
        if self.is_paused:
            painter.setPen(QColor(255, 100, 100))
            painter.drawText(120, 25, "• PAUSED  (Hold Left Fist to cycle mode)")
        
        # Minimize Button (X)
        painter.setPen(QColor(200, 80, 80))
        painter.drawText(self.width() - 30, 25, "—")
        
        # Resize Handle (Visual hint)
        painter.setPen(QColor(100, 100, 110))
        painter.drawLine(self.width()-5, self.height()-15, self.width()-15, self.height()-5)
        painter.drawLine(self.width()-5, self.height()-10, self.width()-10, self.height()-5)

class HandLabelOverlay(QWidget):
    """
    Small floating label that follows the hand with a premium 'orb' aesthetic.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool |
            Qt.WindowType.WindowTransparentForInput
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.resize(120, 70)
        self.text = ""
        self.active = False
        
        # Animation timer
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update)
        self.timer.start(30)
        
    def set_letter(self, text, active=False):
        self.text = text
        self.active = active
        self.update()
        
    def move_to(self, x, y):
        self.move(x + 20, y - 40)

    def paintEvent(self, event):
        if not self.text: return
        
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        now = time.time()
        pulse = (math.sin(now * 4) + 1) / 2
        
        # Bubble / Orb Background
        rect = QRectF(5, 5, 110, 60)
        center = rect.center()
        
        # 1. Outer Glow
        glow_grad = QRadialGradient(center, rect.width()/2)
        base_col = QColor(0, 255, 180) if self.active else QColor(255, 110, 40)
        
        glow_grad.setColorAt(0.0, base_col)
        glow_grad.setColorAt(1.0, QColor(base_col.red(), base_col.green(), base_col.blue(), 0))
        
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(glow_grad))
        painter.drawEllipse(rect)
        
        # 2. Dense Core
        core_grad = QRadialGradient(center, rect.width()/2.5)
        core_grad.setColorAt(0.0, QColor(30, 30, 40, 240))
        core_grad.setColorAt(0.8, QColor(20, 20, 30, 220))
        core_grad.setColorAt(1.0, base_col)
        
        painter.setBrush(QBrush(core_grad))
        painter.drawRoundedRect(rect.adjusted(5, 5, -5, -5), 15, 15)
        
        # 3. Highlight
        painter.setPen(QPen(base_col.lighter(150), 1 + pulse))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect.adjusted(8, 8, -8, -8), 12, 12)
        
        # Letter Text
        painter.setPen(Qt.GlobalColor.white)
        painter.setFont(QFont("Outfit", 26, QFont.Weight.ExtraBold))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self.text)
