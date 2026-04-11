"""
Visual Input Settings page — Phase 3 addition to the control panel.
Controls hand tracking, eye tracking, and sign language.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QScrollArea, QSizePolicy, QSlider,
    QSpacerItem, QTextEdit, QVBoxLayout, QWidget,
)

from core.settings import Settings


class NoScrollSlider(QSlider):
    """A QSlider that ignores mouse-wheel events so the page can scroll normally."""
    def wheelEvent(self, event):
        event.ignore()  # Pass scroll event to the parent (scroll area)


def _label(text, obj_name=""):
    l = QLabel(text)
    if obj_name: l.setObjectName(obj_name)
    return l

def _divider():
    d = QFrame()
    d.setObjectName("divider")
    d.setFrameShape(QFrame.Shape.HLine)
    return d

def _spacer(h=False):
    p = QSizePolicy.Policy.Expanding
    return QSpacerItem(0, 0, p if h else QSizePolicy.Policy.Minimum,
                       QSizePolicy.Policy.Minimum if h else p)


class VisualSettingsPage(QWidget):
    # Signals to main window
    toggle_hand_tracking = pyqtSignal(bool)
    toggle_eye_tracking  = pyqtSignal(bool)
    start_calibration    = pyqtSignal()
    start_hand_calibration = pyqtSignal()
    advance_calibration  = pyqtSignal()
    settings_changed     = pyqtSignal()

    def __init__(self, settings: Settings):
        super().__init__()
        self.settings = settings
        self._build()

    def _build(self):
        # Outer layout holds a scroll area (prevents clipping on small/Windows windows)
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

        vb.addWidget(_label("Visual Input", "section-title"))
        vb.addWidget(_label(
            "Camera-based hand tracking and eye tracking.",
            "section-sub"
        ))

        # ── Camera selection ──────────────────────────────────
        vb.addWidget(_label("Camera index", "label-field"))
        cam_row = QHBoxLayout()
        self._cam_index = QComboBox()
        for i in range(4):
            self._cam_index.addItem(f"Camera {i}", i)
        self._cam_index.setCurrentIndex(self.settings.get("visual_camera", 0))
        cam_row.addWidget(self._cam_index)
        cam_row.addSpacerItem(_spacer(h=True))
        vb.addLayout(cam_row)

        vb.addWidget(_divider())

        # ── Hand tracking ─────────────────────────────────────
        vb.addWidget(_label("Hand Tracking", "card-title"))

        self._hand_enable = QCheckBox("Enable hand tracking")
        self._hand_enable.setChecked(self.settings.get("hand_tracking_active", False))
        self._hand_enable.toggled.connect(self.toggle_hand_tracking)
        vb.addWidget(self._hand_enable)

        vb.addWidget(_label("Scroll sensitivity", "label-field"))
        sens_row = QHBoxLayout()
        self._scroll_sens = NoScrollSlider(Qt.Orientation.Horizontal)
        self._scroll_sens.setRange(5, 120)  # wheel-delta units: ~5 (slow) to 120 (1 notch per tiny move)
        self._scroll_sens.setValue(int(self.settings.get("hand_scroll_sensitivity", 15)))
        self._sens_lbl = QLabel(str(self._scroll_sens.value()))
        self._sens_lbl.setObjectName("label-mono")
        self._sens_lbl.setFixedWidth(40)
        self._scroll_sens.valueChanged.connect(lambda v: self._sens_lbl.setText(str(v)))
        sens_row.addWidget(self._scroll_sens)
        sens_row.addWidget(self._sens_lbl)
        vb.addLayout(sens_row)

        vb.addWidget(_label("Gesture hold duration (seconds)", "label-field"))
        hold_row = QHBoxLayout()
        self._hold_dur = NoScrollSlider(Qt.Orientation.Horizontal)
        self._hold_dur.setRange(5, 50)   # 0.5s – 5.0s in tenths
        self._hold_dur.setValue(int(self.settings.get("gesture_hold_seconds", 2.0) * 10))
        self._hold_lbl = QLabel(f"{self._hold_dur.value() / 10:.1f}s")
        self._hold_lbl.setObjectName("label-mono")
        self._hold_lbl.setFixedWidth(36)
        self._hold_dur.valueChanged.connect(lambda v: self._hold_lbl.setText(f"{v/10:.1f}s"))
        hold_row.addWidget(self._hold_dur)
        hold_row.addWidget(self._hold_lbl)
        vb.addLayout(hold_row)

        vb.addWidget(_label("Pointer Active Area", "label-field"))
        self._hx = NoScrollSlider(Qt.Orientation.Horizontal); self._hx.setRange(0, 50); self._hx.setValue(int(self.settings.get("hand_point_x", 0.2) * 100))
        self._hy = NoScrollSlider(Qt.Orientation.Horizontal); self._hy.setRange(0, 50); self._hy.setValue(int(self.settings.get("hand_point_y", 0.2) * 100))
        self._hw = NoScrollSlider(Qt.Orientation.Horizontal); self._hw.setRange(20, 100); self._hw.setValue(int(self.settings.get("hand_point_w", 0.6) * 100))
        self._hh = NoScrollSlider(Qt.Orientation.Horizontal); self._hh.setRange(20, 100); self._hh.setValue(int(self.settings.get("hand_point_h", 0.6) * 100))

        def add_slider(name, slider):
            lbl = QLabel(f"{slider.value()}%")
            lbl.setObjectName("label-mono")
            lbl.setFixedWidth(40)
            slider.valueChanged.connect(lambda v: lbl.setText(f"{v}%"))
            r = QHBoxLayout()
            r.addWidget(QLabel(name))
            r.addWidget(slider)
            r.addWidget(lbl)
            vb.addLayout(r)

        add_slider("X Offset", self._hx)
        add_slider("Y Offset", self._hy)
        add_slider("Width scale", self._hw)
        add_slider("Height scale", self._hh)

        calib_hand_btn = QPushButton("Auto-Calibrate Zone bounds")
        calib_hand_btn.clicked.connect(self.start_hand_calibration)
        vb.addWidget(calib_hand_btn)


        # Gesture reference
        vb.addWidget(_label("Quick gesture reference", "label-field"))
        gesture_info = QTextEdit()
        gesture_info.setReadOnly(True)
        gesture_info.setMaximumHeight(130)
        gesture_info.setStyleSheet(
            "QTextEdit { background:#0a0a0d; border:1px solid #1f1f26; "
            "color:#71717a; font-size:11px; font-family:'Courier New',monospace; }"
        )
        gesture_info.setPlainText(
            "SNAP (middle+thumb pinch)  → Confirm action\n"
            "CLAP (both hands clap)     → Open/Close overlay\n"
            "OPEN PALM                  → Stop speaking\n"
            "CALL ME (thumb+pinky)      → Cancel\n"
            "PINCH + move up/down       → Scroll page\n"
            "QUICK PINCH                → Click\n"
            "POINT (index only)         → Move cursor"
        )
        vb.addWidget(gesture_info)

        vb.addWidget(_divider())

        # ── Eye tracking ──────────────────────────────────────
        vb.addWidget(_label("Eye Tracking", "card-title"))

        self._eye_enable = QCheckBox("Enable eye tracking")
        self._eye_enable.setChecked(self.settings.get("eye_tracking_active", False))
        self._eye_enable.toggled.connect(self.toggle_eye_tracking)
        vb.addWidget(self._eye_enable)

        vb.addWidget(_label("Dwell time to click (seconds)", "label-field"))
        dwell_row = QHBoxLayout()
        self._dwell = NoScrollSlider(Qt.Orientation.Horizontal)
        self._dwell.setRange(5, 30)   # 0.5s – 3.0s in tenths
        self._dwell.setValue(int(self.settings.get("eye_dwell_sec", 1.2) * 10))
        self._dwell_lbl = QLabel(f"{self._dwell.value() / 10:.1f}s")
        self._dwell_lbl.setObjectName("label-mono")
        self._dwell_lbl.setFixedWidth(36)
        self._dwell.valueChanged.connect(lambda v: self._dwell_lbl.setText(f"{v/10:.1f}s"))
        dwell_row.addWidget(self._dwell)
        dwell_row.addWidget(self._dwell_lbl)
        vb.addLayout(dwell_row)

        # Calibration controls
        self._calib_status = _label("Not calibrated — accuracy may be lower", "label-mono")
        vb.addWidget(self._calib_status)

        calib_row = QHBoxLayout()
        start_calib = QPushButton("Start calibration")
        start_calib.clicked.connect(self.start_calibration)
        adv_calib = QPushButton("Next point →")
        adv_calib.setObjectName("btn-accent")
        adv_calib.clicked.connect(self.advance_calibration)
        calib_row.addWidget(start_calib)
        calib_row.addWidget(adv_calib)
        calib_row.addSpacerItem(_spacer(h=True))
        vb.addLayout(calib_row)

        vb.addWidget(_divider())

        vb.addWidget(_divider())

        save_btn = QPushButton("Save Visual Settings")
        save_btn.setObjectName("btn-accent")
        save_btn.setFixedWidth(190)
        save_btn.clicked.connect(self._save)
        vb.addWidget(save_btn)

        vb.addSpacerItem(_spacer(h=False))

    def _save(self):
        self.settings.update({
            "visual_camera":          self._cam_index.currentData(),
            "hand_scroll_sensitivity": self._scroll_sens.value(),
            "hand_tracking_active":   self._hand_enable.isChecked(),
            "eye_tracking_active":    self._eye_enable.isChecked(),
            "eye_dwell_sec":          self._dwell.value() / 10.0,
            "hand_point_x":           self._hx.value() / 100.0,
            "hand_point_y":           self._hy.value() / 100.0,
            "hand_point_w":           self._hw.value() / 100.0,
            "hand_point_h":           self._hh.value() / 100.0,
            "gesture_hold_seconds":   self._hold_dur.value() / 10.0,
        })
        self.settings_changed.emit()

    def set_calibration_status(self, msg: str):
        self._calib_status.setText(msg)
