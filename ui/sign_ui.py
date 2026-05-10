from PyQt6.QtCore import Qt, QTimer, QRect, QRectF, QPoint, pyqtSignal, QEasingCurve, QPropertyAnimation
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QFont, QPen, QBrush, QLinearGradient, QRegion
from PyQt6.QtWidgets import QWidget, QLabel, QVBoxLayout, QHBoxLayout, QApplication, QScrollArea

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
            Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        # UI State
        self.w, self.h = 800, 140
        self.is_minimized = False
        self.min_size = 60
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
        self.visibility_timer.start(500) # Check every 0.5s
        
        self.show()
        
    def toggle_minimize(self):
        self.is_minimized = not self.is_minimized
        if self.is_minimized:
            self.old_size = self.size()
            self.scroll.hide()
            self.scroll.setFixedSize(0, 0)
            self.layout.setContentsMargins(0, 0, 0, 0)
            self.setFixedSize(self.min_size, self.min_size)
            # WA_TranslucentBackground uses DWM alpha compositing on Windows.
            # SetWindowRgn (setMask) is IGNORED by DWM, so we clear any existing
            # mask and let the alpha channel in paintEvent create the circle shape.
            self.clearMask()
        else:
            self.scroll.setMinimumSize(0, 0)
            self.scroll.setMaximumSize(16777215, 16777215)
            self.setMinimumSize(0, 0)
            self.setMaximumSize(16777215, 16777215)
            self.resize(self.old_size)
            self.layout.setContentsMargins(20, 40, 20, 20)
            self.scroll.show()
        self.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.is_minimized:
            # No mask needed — WA_TranslucentBackground lets DWM alpha-composite
            # the window. Only the ellipse drawn in paintEvent is opaque;
            # everything outside it has alpha=0 and is invisible.
            self.clearMask()
        else:
            # For the expanded dialogue box, a rounded-rect mask clips mouse events
            # neatly to the visible area.
            path = QPainterPath()
            path.addRoundedRect(QRectF(self.rect()), 4, 4)
            self.setMask(QRegion(path.toFillPolygon().toPolygon()))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            # Check for minimize button (Top Right)
            if not self.is_minimized and event.pos().x() > self.width() - 40 and event.pos().y() < 40:
                self.toggle_minimize()
                return
            
            # Check for resizing (Bottom Right corner)
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
        import time
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        now = time.time()
        is_active = (now - self.last_update_time < self.idle_timeout)
        should_be_opaque = self.is_hovered or is_active
        
        # Set Global Window Opacity for simultaneous fading
        target_opacity = 0.95 if should_be_opaque else 0.2
        if abs(self.windowOpacity() - target_opacity) > 0.01:
            # We could animate this, but for now just jump
            self.setWindowOpacity(target_opacity)

        if self.is_minimized:
            # Circle
            painter.setBrush(QBrush(QColor(30, 32, 38, 240)))
            col = QColor(255, 80, 80) if self.is_paused else QColor(100, 255, 200)
            painter.setPen(QPen(col, 2))
            
            # Draw on the masked area
            r = self.rect().adjusted(2, 2, -2, -2)
            painter.drawEllipse(r)
            
            painter.setPen(Qt.GlobalColor.white)
            painter.setFont(QFont("Outfit", 11, QFont.Weight.Bold))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "ASL")
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

        # ── 2. Floating Letter (Near Hand) ───────────────────
        # Note: We need to draw this in a separate window or handle global coords
        # Since this widget is at the bottom, we can't draw near the hand if the hand is high.
        # So we'll use a separate tiny overlay for the "Hand Label".
        pass

class HandLabelOverlay(QWidget):
    """
    Small floating label that follows the hand.
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
        self.resize(100, 60)
        self.text = ""
        self.active = False
        
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
        
        # Bubble
        rect = QRectF(5, 5, 90, 50)
        path = QPainterPath()
        path.addRoundedRect(rect, 10, 10)
        
        col = QColor(34, 197, 94, 220) if self.active else QColor(100, 100, 255, 200)
        painter.fillPath(path, QBrush(QColor(20, 20, 30, 200)))
        painter.setPen(QPen(col, 2))
        painter.drawPath(path)
        
        # Letter
        painter.setPen(Qt.GlobalColor.white)
        painter.setFont(QFont("Outfit", 24, QFont.Weight.Bold))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self.text)
