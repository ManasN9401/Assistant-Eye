"""
Gesture Lab — Capture and map custom hand poses to native actions.
"""
from __future__ import annotations
import os
import json
import logging
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QComboBox, QFrame, QScrollArea, QListWidget,
    QListWidgetItem, QStackedWidget
)

from core.settings import Settings

logger = logging.getLogger(__name__)

def _label(text, obj_name=""):
    l = QLabel(text)
    if obj_name: l.setObjectName(obj_name)
    return l

def _divider():
    d = QFrame()
    d.setObjectName("divider")
    d.setFrameShape(QFrame.Shape.HLine)
    return d

class GestureLabPage(QWidget):
    # Signals sent to VisualCoordinator/HandTracker
    learn_pose_requested = pyqtSignal(str, str, dict) # name, action, params
    delete_pose_requested = pyqtSignal(str)

    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self._poses_path = "core/custom_poses.json"
        self._build()
        self._load_poses()

    def _build(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(28, 28, 28, 28)
        main_layout.setSpacing(20)

        main_layout.addWidget(_label("Gesture Lab", "section-title"))
        main_layout.addWidget(_label(
            "Teach the assistant custom hand shapes and bind them to native apps or commands.",
            "section-sub"
        ))

        # ── Capture New Pose Card ─────────────────────────────
        capture_card = QFrame()
        capture_card.setObjectName("card")
        cv = QVBoxLayout(capture_card)
        cv.setContentsMargins(20, 20, 20, 20)
        cv.setSpacing(12)

        cv.addWidget(_label("Record New Signature", "card-title"))
        
        row1 = QHBoxLayout()
        self._new_name = QLineEdit()
        self._new_name.setPlaceholderText("Pose name (e.g. metal_sign, l_shape)")
        row1.addWidget(self._new_name)
        
        self._action_type = QComboBox()
        self._action_type.addItems(["launch_app", "none"])
        row1.addWidget(self._action_type)
        cv.addLayout(row1)

        self._new_params = QLineEdit()
        self._new_params.setPlaceholderText("Target (e.g. spotify:, calc:, C:\\Program Files\\...)")
        cv.addWidget(self._new_params)

        btn_row = QHBoxLayout()
        self._learn_btn = QPushButton("Learn Pose Signature")
        self._learn_btn.setObjectName("btn-accent")
        self._learn_btn.clicked.connect(self._on_learn)
        btn_row.addWidget(self._learn_btn)
        
        self._status_lbl = _label("Idle", "label-mono")
        self._status_lbl.setStyleSheet("color: #777;")
        btn_row.addWidget(self._status_lbl)
        btn_row.addStretch()
        cv.addLayout(btn_row)

        cv.addWidget(_label("Tip: Open the 'Camera Feed' tab to see yourself during recording.", "section-sub"))

        main_layout.addWidget(capture_card)
        main_layout.addWidget(_divider())

        # ── Saved Poses List ──────────────────────────────────
        main_layout.addWidget(_label("Saved Custom Signatures", "card-title"))
        
        self._pose_list = QListWidget()
        self._pose_list.setObjectName("pose-list")
        self._pose_list.setMinimumHeight(200)
        main_layout.addWidget(self._pose_list)

        actions_row = QHBoxLayout()
        self._delete_btn = QPushButton("Remove Selected")
        self._delete_btn.clicked.connect(self._on_delete)
        actions_row.addWidget(self._delete_btn)
        actions_row.addStretch()
        main_layout.addLayout(actions_row)

    def _load_poses(self):
        self._pose_list.clear()
        if not os.path.exists(self._poses_path):
            return
        try:
            with open(self._poses_path, "r") as f:
                data = json.load(f)
                for name, d in data.items():
                    action = d.get("action", "none")
                    target = d.get("params", {}).get("uri", "")
                    item = QListWidgetItem(f"{name}  →  {action} ({target})")
                    self._pose_list.addItem(item)
        except Exception as e:
            logger.error(f"Error loading poses for UI: {e}")

    def _on_learn(self):
        name = self._new_name.text().strip()
        action = self._action_type.currentText()
        target = self._new_params.text().strip()

        if not name:
            self._status_lbl.setText("Error: Enter a name")
            return

        # Start countdown
        self._learn_btn.setEnabled(False)
        self._countdown = 3
        self._update_countdown(name, action, target)

    def _update_countdown(self, name, action, target):
        if self._countdown > 0:
            self._status_lbl.setText(f"Get ready... {self._countdown}")
            self._status_lbl.setStyleSheet("color: #ffa500;")
            self._countdown -= 1
            QTimer.singleShot(1000, lambda: self._update_countdown(name, action, target))
        else:
            self._status_lbl.setText("Recording... HOLD STILL!")
            self._status_lbl.setStyleSheet("color: #00ff00; font-weight: bold;")
            
            # Request learn + metadata in one go
            self.learn_pose_requested.emit(name, action, {"uri": target})
            
            # Reset UI after 2 seconds
            QTimer.singleShot(2000, self._on_learn_finished)

    def _on_learn_finished(self):
        self._status_lbl.setText("Saved!")
        self._status_lbl.setStyleSheet("color: #00ff00;")
        self._learn_btn.setEnabled(True)
        self._load_poses()
        QTimer.singleShot(2000, lambda: self._status_lbl.setText("Idle"))

    def _on_delete(self):
        selected = self._pose_list.currentItem()
        if not selected:
            return
        # Parse name from text "name  →  action"
        name = selected.text().split("  →")[0]
        self.delete_pose_requested.emit(name)
        self._load_poses()
