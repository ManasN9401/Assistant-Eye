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
    QListWidgetItem, QStackedWidget, QTabWidget, QCheckBox
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
    system_gestures_updated = pyqtSignal()
    request_main_tab = pyqtSignal(int)

    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self._poses_path = "core/custom_poses.json"
        self._sys_gestures_path = "core/system_gestures.json"
        self._build()
        self._load_poses()
        self._load_system_gestures()

    def _build(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        
        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_custom_tab(), "Custom Poses")
        self._tabs.addTab(self._build_system_tab(), "System Gestures")
        main_layout.addWidget(self._tabs)

    def _build_custom_tab(self):
        page = QWidget()
        # ── Setup Scroll Area ─────────────────────────────────
        top_layout = QVBoxLayout(page)
        top_layout.setContentsMargins(0, 0, 0, 0)
        
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        
        container = QWidget()
        container.setObjectName("scroll-container")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(20)

        # ── Page Header ───────────────────────────────────────
        layout.addWidget(_label("Custom Signature Lab", "section-title"))
        layout.addWidget(_label(
            "Teach the assistant new hand shapes from your camera feed.",
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

        layout.addWidget(capture_card)
        layout.addWidget(_divider())

        # ── Saved Poses List ──────────────────────────────────
        layout.addWidget(_label("Saved Custom Signatures", "card-title"))
        
        self._pose_list = QListWidget()
        self._pose_list.setObjectName("pose-list")
        self._pose_list.setMinimumHeight(200)
        layout.addWidget(self._pose_list)

        actions_row = QHBoxLayout()
        self._delete_btn = QPushButton("Remove Selected")
        self._delete_btn.clicked.connect(self._on_delete)
        actions_row.addWidget(self._delete_btn)
        actions_row.addStretch()
        layout.addLayout(actions_row)
        
        layout.addStretch()
        
        # ── Tab Navigation ────────────────────────────────────
        nav_row = QHBoxLayout()
        go_sys_btn = QPushButton("Go to System Gestures →")
        go_sys_btn.setObjectName("btn-subtle")
        go_sys_btn.clicked.connect(lambda: self._tabs.setCurrentIndex(1))
        nav_row.addStretch()
        nav_row.addWidget(go_sys_btn)
        layout.addLayout(nav_row)
        
        scroll.setWidget(container)
        top_layout.addWidget(scroll)
        return page

    def _build_system_tab(self):
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        
        container = QWidget()
        container.setObjectName("scroll-container")
        self._sys_layout = QVBoxLayout(container)
        self._sys_layout.setContentsMargins(28, 28, 28, 28)
        self._sys_layout.setSpacing(15)
        
        self._sys_layout.addWidget(_label("System Gesture Configuration", "section-title"))
        self._sys_layout.addWidget(_label(
            "Toggle or remap the assistant's built-in hand shapes.",
            "section-sub"
        ))
        
        self._sys_rows = []
        
        self._sys_scroll_content = container
        scroll.setWidget(container)
        outer.addWidget(scroll)
        
        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(28, 0, 28, 28)
        save_btn = QPushButton("Save System Mappings")
        save_btn.setObjectName("btn-accent")
        save_btn.clicked.connect(self._on_save_system)
        btn_row.addWidget(save_btn)
        btn_row.addStretch()
        outer.addLayout(btn_row)
        
        # ── Tab Navigation ────────────────────────────────────
        nav_row = QHBoxLayout()
        nav_row.setContentsMargins(28, 0, 28, 28)
        go_custom_btn = QPushButton("← Back to Custom Signature Lab")
        go_custom_btn.setObjectName("btn-subtle")
        go_custom_btn.clicked.connect(lambda: self._tabs.setCurrentIndex(0))
        nav_row.addWidget(go_custom_btn)
        nav_row.addStretch()
        outer.addLayout(nav_row)
        
        return page

    def _load_system_gestures(self):
        # Clear existing rows
        for row in self._sys_rows:
            for i in reversed(range(row["layout"].count())): 
                row["layout"].itemAt(i).widget().setParent(None)
            self._sys_layout.removeItem(row["layout"])
        self._sys_rows = []

        # Load from config
        data = {}
        if os.path.exists(self._sys_gestures_path):
            try:
                with open(self._sys_gestures_path, "r") as f:
                    data = json.load(f)
            except: pass
            
        gestures = ["clap", "both_palms", "fist", "thumbs_up", "call_me", "open_palm", "victory"]
        
        for g in gestures:
            row_layout = QHBoxLayout()
            row_layout.setSpacing(15)
            
            enable_cb = QCheckBox(g.replace("_", " ").title())
            enable_cb.setChecked(data.get(g, {}).get("enabled", True))
            row_layout.addWidget(enable_cb, 2)
            
            action_cb = QComboBox()
            action_cb.addItems(["system_default", "launch_app", "none"])
            current_action = data.get(g, {}).get("action", "system_default")
            # Migration helper: some old configs might use specific names
            if current_action in ["toggle_overlay", "close_overlay", "confirm", "cancel", "stop_speaking"]:
                current_action = "system_default"
            action_cb.setCurrentText(current_action)
            row_layout.addWidget(action_cb, 2)
            
            params_edit = QLineEdit()
            params_edit.setPlaceholderText("Param (e.g. notepad.exe)")
            params_edit.setText(data.get(g, {}).get("params", {}).get("uri", ""))
            params_edit.setVisible(current_action == "launch_app")
            action_cb.currentTextChanged.connect(lambda text, p=params_edit: p.setVisible(text == "launch_app"))
            row_layout.addWidget(params_edit, 3)
            
            self._sys_layout.addLayout(row_layout)
            self._sys_rows.append({
                "name": g,
                "layout": row_layout,
                "enable": enable_cb,
                "action": action_cb,
                "params": params_edit
            })
            
        self._sys_layout.addStretch()

    def _on_save_system(self):
        new_data = {}
        # We need to recover the 'correct' system_default action logic 
        # because the internal mapper uses specific strings like 'toggle_overlay'
        defaults = {
            "clap": "toggle_overlay",
            "both_palms": "toggle_overlay",
            "fist": "close_overlay",
            "thumbs_up": "confirm",
            "call_me": "cancel",
            "open_palm": "stop_speaking",
            "victory": "none"
        }
        
        for row in self._sys_rows:
            g = row["name"]
            action = row["action"].currentText()
            if action == "system_default":
                action = defaults.get(g, "none")
                
            new_data[g] = {
                "enabled": row["enable"].isChecked(),
                "action": action,
                "params": {"uri": row["params"].text()} if action == "launch_app" else {}
            }
            
        try:
            with open(self._sys_gestures_path, "w") as f:
                json.dump(new_data, f, indent=2)
            self._status_lbl.setText("System mappings saved!")
            self._status_lbl.setStyleSheet("color: #00ff00;")
            self.system_gestures_updated.emit()
            logger.info("System gestures saved to JSON.")
        except Exception as e:
            logger.error(f"Failed to save system gestures: {e}")

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
            
        # Switch to Camera Feed so user can see themselves
        self.request_main_tab.emit(7) 

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
