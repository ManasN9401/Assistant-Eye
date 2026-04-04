"""
EYE — AI Website Assistant (Phase 4 — complete)
"""
import logging
import sys
from PyQt6.QtWidgets import QApplication, QSystemTrayIcon, QMenu
from PyQt6.QtGui import QIcon, QColor, QPixmap, QPainter, QBrush
from PyQt6.QtCore import Qt

from core.settings import Settings
from core.ai_engine import AIEngine
from core.function_registry import FunctionRegistry
from core.hotkeys import HotkeyManager
from ui.control_panel import ControlPanel
from ui.overlay import Overlay
from ui.calibration_overlay import CalibrationOverlay
from ui.styles import DARK_QSS
from voice.coordinator import VoiceCoordinator
from bridge.ws_server import BrowserBridgeThread
from bridge.playwright_bridge import PlaywrightBridge, ActionExecutor
from visual.coordinator import VisualCoordinator


def _tray_icon(color="#e8a020") -> QIcon:
    px = QPixmap(22, 22)
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QBrush(QColor(color)))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(3, 3, 16, 16)
    p.end()
    return QIcon(px)


def main():
    logging.basicConfig(
        level=logging.DEBUG,
        format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    log = logging.getLogger("main")

    app = QApplication(sys.argv)
    app.setApplicationName("EYE")
    app.setQuitOnLastWindowClosed(False)
    app.setStyleSheet(DARK_QSS)
    log.debug("Starting EYE assistant application")

    # ── Core ──────────────────────────────────────────────────────────────────
    settings = Settings()
    engine   = AIEngine(settings)
    registry = FunctionRegistry(settings)
    
    # Auto-load the builtin registry if available
    registries = registry.list_registries()
    if registries:
        registry.load(registries[0]["file"])
        log.debug("Auto-loaded registry: %s", registries[0]["name"])
    
    log.debug("Core initialized: settings=%s, registry=%s", settings, registry)

    # ── Browser bridge ────────────────────────────────────────────────────────
    browser_bridge = BrowserBridgeThread(settings)
    browser_bridge.start()
    log.debug("Browser bridge thread started")
    playwright = PlaywrightBridge(settings, engine)
    executor   = ActionExecutor(settings, engine, playwright, browser_bridge)
    log.debug("Action executor created")

    # ── Voice ─────────────────────────────────────────────────────────────────
    voice = VoiceCoordinator(settings, engine, registry)
    log.debug("Voice coordinator initialized")

    # ── Visual ────────────────────────────────────────────────────────────────
    visual = VisualCoordinator(settings)

    # ── UI ────────────────────────────────────────────────────────────────────
    overlay   = Overlay(settings, engine, registry)
    calib_win = CalibrationOverlay()
    panel     = ControlPanel(settings, registry, engine, voice,
                             browser_bridge, executor, visual)

    # ── Hotkeys ───────────────────────────────────────────────────────────────
    hotkeys = HotkeyManager(settings)
    hotkeys.overlay_triggered.connect(overlay.toggle)
    hotkeys.listen_triggered.connect(voice.trigger_listen)
    hotkeys.error.connect(lambda m: print(f"[hotkey] {m}"))
    hotkeys.start()
    # Re-register when settings change
    panel._settings_page.settings_changed.connect(hotkeys.update_hotkeys)

    # ── Calibration overlay wiring ────────────────────────────────────────────
    # Visual settings page "Start calibration" → show calibration overlay
    panel._visual_page.start_calibration.disconnect()   # disconnect old signal
    panel._visual_page.start_calibration.connect(calib_win.start)
    panel._visual_page.advance_calibration.disconnect()
    panel._visual_page.advance_calibration.connect(calib_win._advance)

    # Calibration overlay → eye tracker
    calib_win.point_advanced.connect(lambda _: visual.eye_tracker.advance_calibration())
    calib_win.calibration_complete.connect(visual.eye_tracker.advance_calibration)
    calib_win.calibration_complete.connect(
        lambda: panel._visual_page.set_calibration_status("Calibrated ✓"))
    calib_win.cancelled.connect(
        lambda: panel._visual_page.set_calibration_status("Calibration cancelled"))

    visual.calibration_progress.connect(
        lambda n: panel._visual_page.set_calibration_status(
            f"Calibrating — point {n + 1} of 9 collected…"))
    visual.calibration_complete.connect(
        lambda: panel._visual_page.set_calibration_status("Eye tracking calibrated ✓"))

    # ── Wire: Voice ───────────────────────────────────────────────────────────
    voice.state_changed.connect(overlay.set_voice_state)
    voice.transcription.connect(overlay.show_transcription)
    voice.response_token.connect(overlay.append_token)
    voice.response_complete.connect(lambda _: overlay.end_response())
    
    # Show AI or Wake word errors visibly instead of swallowing them
    voice.error.connect(lambda msg: log.error("Voice error: %s", msg))
    voice.error.connect(overlay._on_err)
    voice.error.connect(lambda msg: panel._dashboard.append_token(f"\n[ERROR] {msg}\n"))
    
    def _on_action_detected(fn_def, params):
        log.debug("Action detected: %s %s", fn_def.get('name'), params)
        result = executor.execute_action(fn_def, params)
        log.debug("Action execution result: %s", result)
        voice.tts.speak(result)

    voice.action_detected.connect(_on_action_detected)
    browser_bridge.page_changed.connect(panel.on_page_changed)
    browser_bridge.user_command.connect(voice.send_text)
    overlay.command_entered.connect(voice.send_text)

    # ── Wire: Visual → Overlay / Voice ────────────────────────────────────────
    visual.action_open_overlay.connect(overlay.toggle)
    visual.action_close_overlay.connect(overlay.hide)
    visual.action_stop_speaking.connect(voice.tts.stop)
    visual.action_confirm.connect(lambda: voice.send_text("yes, confirm"))
    visual.action_cancel.connect(lambda: voice.send_text("cancel"))

    def _on_sign_command(action: str):
        sign_map = {
            "trigger_listen":  voice.trigger_listen,
            "open_overlay":    overlay.show,
            "stop_speaking":   voice.tts.stop,
            "confirm":         lambda: voice.send_text("confirm"),
            "cancel":          voice.stop,
            "go_to_docs":      lambda: voice.send_text("go to the docs page"),
            "open_search":     lambda: voice.send_text("open search"),
            "navigate":        overlay.show,
        }
        fn = sign_map.get(action)
        if fn:
            fn()

    visual.sign_command.connect(_on_sign_command)
    visual.sign_word.connect(voice.send_text)

    # Settings refresh
    panel._settings_page.settings_changed.connect(overlay.refresh_name)
    panel._settings_page.settings_changed.connect(
        lambda: browser_bridge.send_assistant_name(settings.assistant_name)
    )
    panel._functions.registry_loaded.connect(lambda: overlay.set_voice_state("idle"))

    # ── Auto-start ────────────────────────────────────────────────────────────
    cam = settings.get("visual_camera", 0)
    if settings.get("hand_tracking_active", False):
        visual.start_hand_tracking(cam)
    if settings.get("eye_tracking_active", False):
        visual.start_eye_tracking(cam)
    if settings.get("sign_language_active", False):
        visual.start_sign_language(cam)
    if settings.get("wake_word_active", False):
        voice.start_wake_word()

    # ── System tray ───────────────────────────────────────────────────────────
    tray = QSystemTrayIcon(_tray_icon(), app)
    menu = QMenu()
    menu.addAction("Open control panel").triggered.connect(
        lambda: (panel.show(), panel.raise_()))
    menu.addAction("Toggle overlay").triggered.connect(overlay.toggle)
    menu.addAction("Listen now").triggered.connect(voice.trigger_listen)
    menu.addAction("Calibrate eye tracker").triggered.connect(calib_win.start)
    menu.addSeparator()
    menu.addAction("Quit EYE").triggered.connect(app.quit)
    tray.setContextMenu(menu)
    tray.setToolTip("EYE Assistant")
    tray.activated.connect(
        lambda r: overlay.toggle()
        if r == QSystemTrayIcon.ActivationReason.Trigger else None)
    tray.show()

    # ── Cleanup ───────────────────────────────────────────────────────────────
    def _cleanup():
        hotkeys.stop()
        voice.stop()
        visual.stop_all()
        browser_bridge.stop()
        browser_bridge.wait(2000)

    app.aboutToQuit.connect(_cleanup)

    panel.show()
    overlay.show()
    log.debug("Main UI shown")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
