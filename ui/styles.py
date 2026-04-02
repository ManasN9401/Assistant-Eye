"""
Styles module — returns QSS stylesheet strings.
Theme: dark industrial / terminal aesthetic.
Accent: #e8a020 (amber)
"""

DARK_QSS = """
/* ── Global ─────────────────────────────────────────── */
QWidget {
    background-color: #0e0e11;
    color: #d1d1d8;
    font-family: "Segoe UI", "Ubuntu", sans-serif;
    font-size: 13px;
    border: none;
    outline: none;
}

QMainWindow {
    background-color: #0e0e11;
}

/* ── Sidebar ─────────────────────────────────────────── */
#sidebar {
    background-color: #09090b;
    border-right: 1px solid #1f1f26;
    min-width: 200px;
    max-width: 200px;
}

#sidebar-header {
    background-color: #09090b;
    border-bottom: 1px solid #1f1f26;
    padding: 20px 16px;
}

#app-name {
    font-size: 20px;
    font-weight: 700;
    color: #e8a020;
    letter-spacing: 4px;
    font-family: "Courier New", monospace;
}

#app-subtitle {
    font-size: 10px;
    color: #52525b;
    letter-spacing: 1px;
    margin-top: 2px;
}

/* ── Sidebar nav buttons ─────────────────────────────── */
#nav-btn {
    background: transparent;
    color: #71717a;
    text-align: left;
    padding: 10px 16px;
    border-radius: 0px;
    border-left: 2px solid transparent;
    font-size: 12px;
    letter-spacing: 0.5px;
}

#nav-btn:hover {
    background-color: #141418;
    color: #d1d1d8;
}

#nav-btn[active="true"] {
    background-color: #141418;
    color: #e8a020;
    border-left: 2px solid #e8a020;
}

/* ── Status bar ──────────────────────────────────────── */
#status-bar {
    background-color: #09090b;
    border-top: 1px solid #1f1f26;
    padding: 6px 16px;
}

#status-label {
    font-size: 11px;
    color: #3f3f46;
    font-family: "Courier New", monospace;
}

/* ── Main content area ───────────────────────────────── */
#content-area {
    background-color: #0e0e11;
    padding: 0px;
}

/* ── Cards ───────────────────────────────────────────── */
#card {
    background-color: #141418;
    border: 1px solid #1f1f26;
    border-radius: 8px;
    padding: 16px;
}

#card-title {
    font-size: 11px;
    font-weight: 600;
    color: #71717a;
    letter-spacing: 1.5px;
    font-family: "Courier New", monospace;
    margin-bottom: 8px;
    margin-top: 6px;
    text-transform: uppercase;
}

/* ── Section headings ────────────────────────────────── */
#section-title {
    font-size: 18px;
    font-weight: 600;
    color: #e4e4e7;
    margin-bottom: 4px;
}

#section-sub {
    font-size: 12px;
    color: #52525b;
    margin-bottom: 20px;
}

/* ── Status dot ──────────────────────────────────────── */
#status-dot-idle    { color: #3f3f46; font-size: 10px; }
#status-dot-ready   { color: #22c55e; font-size: 10px; }
#status-dot-thinking { color: #e8a020; font-size: 10px; }
#status-dot-error   { color: #ef4444; font-size: 10px; }

/* ── Inputs ──────────────────────────────────────────── */
QLineEdit, QTextEdit, QPlainTextEdit {
    background-color: #0a0a0d;
    border: 1px solid #27272a;
    border-radius: 6px;
    padding: 8px 12px;
    color: #d1d1d8;
    selection-background-color: #e8a02040;
    font-size: 13px;
    min-height: 32px;
}

QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {
    border-color: #e8a020;
}

QLineEdit[readOnly="true"] {
    color: #71717a;
    background-color: #0a0a0d;
}

/* ── Scroll areas ─────────────────────────────────────── */
QScrollArea {
    border: none;
    background-color: transparent;
}

QScrollArea > QWidget > QWidget {
    background-color: transparent;
}

/* ── Combo boxes ─────────────────────────────────────── */
QComboBox {
    background-color: #0a0a0d;
    border: 1px solid #27272a;
    border-radius: 6px;
    padding: 6px 36px 6px 12px;
    color: #d1d1d8;
    min-width: 180px;
    min-height: 32px;
    font-size: 13px;
}

QComboBox:hover { border-color: #3f3f46; }
QComboBox:focus { border-color: #e8a020; }

QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 32px;
    border-left: 1px solid #27272a;
    border-top-right-radius: 6px;
    border-bottom-right-radius: 6px;
    background-color: #141418;
}

QComboBox::down-arrow {
    image: none;
    width: 0;
    height: 0;
    border-left: 5px solid transparent;
    border-right: 5px solid transparent;
    border-top: 6px solid #a1a1aa;
}

QComboBox QAbstractItemView {
    background-color: #141418;
    border: 1px solid #3f3f46;
    border-radius: 4px;
    selection-background-color: #27272a;
    selection-color: #e8a020;
    color: #d1d1d8;
    padding: 4px;
    outline: none;
    font-size: 13px;
}

QComboBox QAbstractItemView::item {
    padding: 6px 12px;
    min-height: 28px;
    color: #d1d1d8;
}

QComboBox QAbstractItemView::item:selected {
    background-color: #27272a;
    color: #e8a020;
}

/* ── Buttons ─────────────────────────────────────────── */
QPushButton {
    background-color: #1a1a1f;
    color: #a1a1aa;
    border: 1px solid #27272a;
    border-radius: 6px;
    padding: 8px 16px;
    font-size: 12px;
    min-height: 32px;
}

QPushButton:hover {
    background-color: #1f1f26;
    color: #d1d1d8;
    border-color: #3f3f46;
}

QPushButton:pressed {
    background-color: #27272a;
}

#btn-accent {
    background-color: #e8a020;
    color: #0a0600;
    border: none;
    font-weight: 600;
    min-height: 34px;
}

#btn-accent:hover {
    background-color: #f5b030;
    color: #0a0600;
}

#btn-accent:pressed {
    background-color: #c98a18;
}

#btn-danger {
    background-color: transparent;
    color: #ef4444;
    border: 1px solid #3f1515;
    min-height: 32px;
}

#btn-danger:hover {
    background-color: #1a0808;
    border-color: #ef4444;
}

/* ── Checkboxes ───────────────────────────────────────── */
QCheckBox {
    font-size: 13px;
    color: #d1d1d8;
    spacing: 10px;
    min-height: 28px;
}

QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid #3f3f46;
    border-radius: 4px;
    background-color: #0a0a0d;
}

QCheckBox::indicator:hover {
    border-color: #e8a020;
}

QCheckBox::indicator:checked {
    background-color: #e8a020;
    border-color: #e8a020;
    image: none;
}

QCheckBox::indicator:unchecked:hover {
    background-color: #1a1a1f;
}

/* ── Labels ──────────────────────────────────────────── */
#label-field {
    font-size: 11px;
    color: #71717a;
    letter-spacing: 0.5px;
    margin-bottom: 4px;
}

#label-mono {
    font-family: "Courier New", monospace;
    font-size: 12px;
    color: #52525b;
}

/* ── Scrollbar ───────────────────────────────────────── */
QScrollBar:vertical {
    background: transparent;
    width: 6px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: #27272a;
    border-radius: 3px;
    min-height: 30px;
}
QScrollBar::handle:vertical:hover { background: #3f3f46; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }

/* ── Divider ─────────────────────────────────────────── */
#divider {
    background-color: #1f1f26;
    max-height: 1px;
    min-height: 1px;
}

/* ── Chat / response area ────────────────────────────── */
#chat-bubble-user {
    background-color: #1a1a22;
    border: 1px solid #27272a;
    border-radius: 8px;
    padding: 10px 14px;
    color: #d1d1d8;
}

#chat-bubble-assistant {
    background-color: #0f0f14;
    border: 1px solid #1f1f26;
    border-left: 2px solid #e8a020;
    border-radius: 8px;
    padding: 10px 14px;
    color: #d1d1d8;
}

/* ── Registry list ───────────────────────────────────── */
QListWidget {
    background-color: #0a0a0d;
    border: 1px solid #1f1f26;
    border-radius: 6px;
    padding: 4px;
    outline: none;
}

QListWidget::item {
    padding: 8px 12px;
    border-radius: 4px;
    color: #a1a1aa;
    border-bottom: 1px solid #141418;
}

QListWidget::item:selected {
    background-color: #1a1a22;
    color: #e8a020;
    border-left: 2px solid #e8a020;
}

QListWidget::item:hover {
    background-color: #141418;
    color: #d1d1d8;
}

/* ── Slider ──────────────────────────────────────────── */
QSlider::groove:horizontal {
    background: #1f1f26;
    height: 4px;
    border-radius: 2px;
}
QSlider::handle:horizontal {
    background: #e8a020;
    width: 14px;
    height: 14px;
    border-radius: 7px;
    margin: -5px 0;
}
QSlider::sub-page:horizontal {
    background: #e8a02060;
    border-radius: 2px;
}

/* ── Tooltip ─────────────────────────────────────────── */
QToolTip {
    background-color: #1a1a1f;
    color: #d1d1d8;
    border: 1px solid #27272a;
    padding: 6px 10px;
    border-radius: 4px;
    font-size: 12px;
}
"""
