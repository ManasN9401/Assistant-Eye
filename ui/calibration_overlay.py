"""
Eye Calibration Window
A borderless, always-on-top fullscreen window that guides the user through
the 9-point gaze calibration sequence.

Flow:
  1. Show fullscreen dark overlay.
  2. Display instructions, then a bright amber dot at each of 9 positions.
  3. User looks at the dot; after HOLD_SEC the dot fills → auto-advance,
     OR the user presses Space/Enter to advance manually.
  4. On completion, hide and emit calibration_complete.
"""
from __future__ import annotations
import math

from PyQt6.QtCore import (
    Qt, QPoint, QRect, QTimer, QPropertyAnimation,
    QEasingCurve, pyqtSignal, QRectF,
)
from PyQt6.QtGui import (
    QColor, QPainter, QPainterPath, QFont, QPen, QBrush,
    QKeyEvent,
)
from PyQt6.QtWidgets import QApplication, QWidget

AMBER   = QColor("#e8a020")
AMBER_D = QColor("#7a5010")
WHITE   = QColor("#e4e4e7")
BG      = QColor(10, 10, 14, 230)
GREEN   = QColor("#22c55e")

DOT_R      = 14    # dot radius px
RING_R     = 32    # growing ring radius
HOLD_MS    = 1200  # ms to hold before auto-advance
GRID_NORM  = [     # normalised positions (matches GazeCalibration.GRID_POINTS)
    (0.1, 0.1), (0.5, 0.1), (0.9, 0.1),
    (0.1, 0.5), (0.5, 0.5), (0.9, 0.5),
    (0.1, 0.9), (0.5, 0.9), (0.9, 0.9),
]


class CalibrationOverlay(QWidget):
    """Fullscreen calibration overlay. Call start() to begin."""

    calibration_complete = pyqtSignal()
    point_advanced       = pyqtSignal(int)   # index of point just confirmed
    cancelled            = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._point    = 0
        self._phase    = "intro"   # "intro" | "calibrating" | "done"
        self._progress = 0.0       # 0–1 fill ring
        self._dot_pos  = QPoint(0, 0)

        # Timer for auto-advance ring fill
        self._hold_timer = QTimer(self)
        self._hold_timer.setInterval(30)   # 30ms ticks → smooth ring
        self._hold_timer.timeout.connect(self._tick_hold)
        self._elapsed_ms = 0

        self._setup_window()
        self._update_dot_pos()

    def _setup_window(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        screen = QApplication.primaryScreen().geometry()
        self.setGeometry(screen)

    def start(self):
        self._point    = 0
        self._phase    = "intro"
        self._progress = 0.0
        self._elapsed_ms = 0
        self.show()
        self.update()
        # Auto-advance from intro after 2.5s
        QTimer.singleShot(2500, self._begin_calibration)

    def _begin_calibration(self):
        self._phase = "calibrating"
        self._update_dot_pos()
        self._hold_timer.start()
        self.update()

    def _update_dot_pos(self):
        if self._point >= len(GRID_NORM):
            return
        nx, ny  = GRID_NORM[self._point]
        geo     = self.geometry()
        margin  = 60
        x = int(margin + nx * (geo.width()  - 2 * margin))
        y = int(margin + ny * (geo.height() - 2 * margin))
        self._dot_pos = QPoint(x, y)

    def _tick_hold(self):
        self._elapsed_ms += 30
        self._progress    = min(1.0, self._elapsed_ms / HOLD_MS)
        self.update()
        if self._elapsed_ms >= HOLD_MS:
            self._advance()

    def _advance(self):
        self._hold_timer.stop()
        self._elapsed_ms = 0
        self._progress   = 0.0
        self.point_advanced.emit(self._point)
        self._point += 1

        if self._point >= len(GRID_NORM):
            self._phase = "done"
            self.update()
            QTimer.singleShot(1200, self._finish)
        else:
            self._update_dot_pos()
            self.update()
            self._hold_timer.start()

    def _finish(self):
        self.hide()
        self.calibration_complete.emit()

    # ── Keyboard control ──────────────────────────────────────────────────────

    def keyPressEvent(self, e: QKeyEvent):
        if e.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if self._phase == "intro":
                self._begin_calibration()
                self._hold_timer.stop()
            elif self._phase == "calibrating":
                self._hold_timer.stop()
                self._advance()
        elif e.key() == Qt.Key.Key_Escape:
            self._hold_timer.stop()
            self.hide()
            self.cancelled.emit()

    # ── Paint ─────────────────────────────────────────────────────────────────

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        geo = self.rect()

        # Full-screen semi-transparent background
        painter.fillRect(geo, BG)

        if self._phase == "intro":
            self._paint_intro(painter, geo)
        elif self._phase == "calibrating":
            self._paint_calibration(painter, geo)
        elif self._phase == "done":
            self._paint_done(painter, geo)

    def _paint_intro(self, p: QPainter, geo: QRect):
        cx = geo.width() // 2
        cy = geo.height() // 2

        p.setPen(QPen(AMBER, 1))
        f = QFont("Courier New", 13)
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 3)
        p.setFont(f)
        p.setPen(AMBER)
        p.drawText(QRect(cx - 300, cy - 100, 600, 40),
                   Qt.AlignmentFlag.AlignHCenter, "EYE TRACKING CALIBRATION")

        p.setPen(QPen(WHITE, 1))
        p.setFont(QFont("Segoe UI", 14))
        p.drawText(QRect(cx - 300, cy - 40, 600, 30),
                   Qt.AlignmentFlag.AlignHCenter,
                   "Look at each amber dot as it appears.")
        p.drawText(QRect(cx - 300, cy + 0, 600, 30),
                   Qt.AlignmentFlag.AlignHCenter,
                   "Hold your gaze still — it will advance automatically.")
        p.drawText(QRect(cx - 300, cy + 40, 600, 30),
                   Qt.AlignmentFlag.AlignHCenter,
                   "Press Space/Enter to advance manually.  Esc to cancel.")

        p.setPen(QPen(QColor("#3f3f46"), 1))
        p.setFont(QFont("Courier New", 11))
        p.drawText(QRect(cx - 200, cy + 100, 400, 24),
                   Qt.AlignmentFlag.AlignHCenter, "Starting in a moment…")

    def _paint_calibration(self, p: QPainter, geo: QRect):
        total = len(GRID_NORM)
        cx = geo.width() // 2

        # Progress indicator
        p.setPen(QPen(QColor("#3f3f46"), 1))
        p.setFont(QFont("Courier New", 11))
        p.drawText(
            QRect(cx - 200, 20, 400, 24),
            Qt.AlignmentFlag.AlignHCenter,
            f"Point {self._point + 1} of {total}  —  Press Space to advance"
        )

        # All past dots (muted)
        for i in range(self._point):
            nx, ny  = GRID_NORM[i]
            margin  = 60
            x = int(margin + nx * (geo.width()  - 2 * margin))
            y = int(margin + ny * (geo.height() - 2 * margin))
            p.setBrush(QBrush(QColor("#1f1f26")))
            p.setPen(QPen(QColor("#27272a"), 0.5))
            p.drawEllipse(QPoint(x, y), DOT_R // 2, DOT_R // 2)
            # Tick mark
            p.setPen(QPen(GREEN, 1.5))
            p.setFont(QFont("Arial", 8))
            p.drawText(QRect(x - 8, y - 8, 16, 16),
                       Qt.AlignmentFlag.AlignCenter, "✓")

        # Current dot — growing fill ring
        cx_d, cy_d = self._dot_pos.x(), self._dot_pos.y()

        # Pulsing outer ring
        ring_r = DOT_R + int(RING_R * (1 - self._progress))
        pen = QPen(QColor(232, 160, 32, int(80 * (1 - self._progress))), 1.5)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPoint(cx_d, cy_d), ring_r, ring_r)

        # Progress arc (fill ring)
        arc_r = DOT_R + 8
        p.setPen(QPen(AMBER, 2.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.setBrush(Qt.BrushStyle.NoBrush)
        rect = QRectF(cx_d - arc_r, cy_d - arc_r, arc_r * 2, arc_r * 2)
        p.drawArc(rect, 90 * 16, int(-360 * 16 * self._progress))

        # Solid dot centre
        dot_color = AMBER if self._progress < 1.0 else GREEN
        p.setBrush(QBrush(dot_color))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPoint(cx_d, cy_d), DOT_R, DOT_R)

        # Small crosshair in dot centre
        p.setPen(QPen(QColor(10, 10, 14), 1))
        p.drawLine(cx_d - 5, cy_d, cx_d + 5, cy_d)
        p.drawLine(cx_d, cy_d - 5, cx_d, cy_d + 5)

    def _paint_done(self, p: QPainter, geo: QRect):
        cx = geo.width() // 2
        cy = geo.height() // 2
        p.setPen(GREEN)
        p.setFont(QFont("Courier New", 16))
        p.drawText(QRect(cx - 300, cy - 30, 600, 40),
                   Qt.AlignmentFlag.AlignHCenter, "CALIBRATION COMPLETE")
        p.setPen(WHITE)
        p.setFont(QFont("Segoe UI", 13))
        p.drawText(QRect(cx - 300, cy + 20, 600, 30),
                   Qt.AlignmentFlag.AlignHCenter, "Eye tracking is now active.")
