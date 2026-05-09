from PyQt6.QtCore import Qt, QTimer, QRect, QRectF, QPoint, pyqtSignal, QEasingCurve, QPropertyAnimation
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QFont, QPen, QBrush, QLinearGradient
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
            Qt.WindowType.Tool |
            Qt.WindowType.WindowTransparentForInput
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        self.w, self.h = 800, 140
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
        self.show()
        
    def update_translation(self, full: str, word: str, letter: str = ""):
        self.full_text = full
        self.current_word = word
        
        display_text = self.full_text
        if self.current_word:
             display_text += (" " if display_text else "") + self.current_word
        
        self.content.setText(display_text)
        # Auto-scroll to bottom
        QTimer.singleShot(10, lambda: self.scroll.verticalScrollBar().setValue(
            self.scroll.verticalScrollBar().maximum()
        ))
        self.update()

    def update_hand_pos(self, x_norm, y_norm):
        screen = QApplication.primaryScreen().geometry()
        self.hand_pos = QPoint(int(x_norm * screen.width()), int(y_norm * screen.height()))
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # ── 1. The Main Dialogue Box (Bottom) ──────────────────
        path = QPainterPath()
        path.addRoundedRect(0, 0, self.w, self.h, 4, 4) # Shaper corners for minimalism
        
        # Muted Slate palette
        painter.fillPath(path, QBrush(QColor(30, 32, 38, 230)))
        
        # Thin, subtle border
        painter.setPen(QPen(QColor(70, 75, 85, 255), 1))
        painter.drawPath(path)
        
        # Label "TRANSLATION"
        painter.setPen(QColor(150, 155, 170))
        painter.setFont(QFont("Outfit", 9, QFont.Weight.Bold))
        painter.drawText(20, 25, "TRANSLATION")

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
