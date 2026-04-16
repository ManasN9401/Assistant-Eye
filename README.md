# EYE — AI Website Assistant Overlay

> ⚠️ **Active Development** — EYE is currently in active development. Core features are functional, but APIs and interfaces may change as we work toward a stable release.

A Python desktop assistant that connects to any website, responds to voice
and text commands, and can control the browser with hands, eyes, and sign language.

EYE runs as an always-on-top overlay that floats above your browser, providing real-time AI assistance while you browse.

---

## Key Features at a Glance

- **12+ Built-in Hand Gestures** — Scroll, click, drag, and navigate with natural hand motions
- **Custom Gesture Creator** — Design and save your own hand signatures to launch apps or trigger actions
- **Eye Tracking** — Webcam-based gaze estimation with dwell-click (no specialist hardware needed)
- **ASL Sign Recognition** — American Sign Language quick-actions (A, B, C, D, G, L, S, Y)
- **Gesture Remapping** — Reconfigure system gestures to your preferred actions
- **Voice Control** — Wake word detection, speech-to-text, and text-to-speech
- **AI-Powered** — Pluggable support for OpenAI, Anthropic, and local Ollama models
- **Browser Integration** — Chrome extension for DOM access and page-aware AI responses

---

## Overview

EYE combines several components to create an immersive hands-free browsing experience:

- **Desktop Overlay** — Floating pill-shaped overlay (always-on-top) with chat, status, and quick actions
- **Browser Extension** — Chrome/MV3 extension that bridges the desktop app to web pages via WebSocket
- **Voice Control** — Wake word detection, speech-to-text, and text-to-speech for full voice operation
- **Visual Tracking** — Hand gestures, eye gaze tracking, and ASL sign language recognition
- **AI Engine** — Pluggable support for OpenAI, Anthropic, and local Ollama models

---

## Quick start

```bash
python setup.py          # installs all deps, checks permissions, creates .env
cd test_website && python -m http.server 5500   # serve the test site
python main.py           # launch EYE
```

## Browser Extension

EYE includes a Chrome browser extension that enables communication between the desktop overlay and web pages:

| File | Purpose |
|---|---|
| `browser_extension/manifest.json` | Chrome MV3 extension manifest |
| `browser_extension/background.js` | WebSocket bridge to Python (port 8765) |
| `browser_extension/content.js` | Page helper utilities (`__aria.*`) |
| `browser_extension/popup.html` | Extension toolbar popup UI |

### Installing the Extension

1. Open Chrome and navigate to `chrome://extensions/`
2. Enable **Developer mode** (toggle in top-right)
3. Click **Load unpacked** and select the `browser_extension/` folder
4. The extension icon should appear in your toolbar

The extension connects the desktop EYE app to web pages, enabling:
- DOM access for website function execution
- Real-time page scraping for AI context
- Overlay-to-page communication via WebSocket

---

Using multiple terminals from PATH('.../assistant-eye/'):

```bash 1
cd test_website
python -m http.server 5500
```

```bash 2
python setup.py
python main.py

```
---

## Project Structure

```
assistant-eye/
├── main.py                          Entry point — wires everything together
├── setup.py                         Installer / setup checker
├── requirements.txt
│
├── core/
│   ├── settings.py                  JSON settings (~/.aria-assistant/settings.json)
│   ├── ai_engine.py                 OpenAI / Anthropic / Ollama abstraction
│   ├── function_registry.py         Website action registry system
│   ├── hotkeys.py                   Global keyboard shortcuts
│   ├── custom_poses.json            User-created gesture templates
│   └── system_gestures.json         Built-in gesture remapping config
│
├── ui/
│   ├── control_panel.py             Main PyQt6 window (7 tabs)
│   ├── overlay.py                   Floating pill overlay (always-on-top)
│   ├── calibration_overlay.py       Fullscreen 9-point eye calibration UI
│   ├── voice_settings.py            Voice tab in control panel
│   ├── visual_settings.py           Visual tab in control panel
│   ├── gesture_lab.py               Custom pose capture + system gesture remap
│   └── styles.py                    QSS dark industrial theme
│
├── voice/
│   ├── stt_engine.py                Speech-to-text (Whisper local or API)
│   ├── tts_engine.py                Text-to-speech (pyttsx3 / ElevenLabs)
│   ├── wake_word.py                 Wake word detection (Vosk or Porcupine)
│   └── coordinator.py               Orchestrates full voice pipeline
│
├── bridge/
│   ├── ws_server.py                 WebSocket server (port 8765) for Chrome ext
│   └── playwright_bridge.py         Playwright automation + ActionExecutor
│
├── visual/
│   ├── hand_tracker.py              MediaPipe Hands — 12+ gestures, custom poses
│   ├── eye_tracker.py               MediaPipe FaceMesh — iris gaze + dwell-click
│   ├── gesture_manager.py           System gesture configuration loader
│   ├── pose_matcher.py              Vector-based custom pose matching
│   ├── platform_win.py              Windows-specific performance optimizations
│   └── coordinator.py               Combines all visual input + OS cursor control
│
├── browser_extension/
│   ├── manifest.json                Chrome MV3 extension
│   ├── background.js                WebSocket bridge to Python
│   ├── content.js                   Page helper utilities (__aria.*)
│   ├── popup.html / popup.js        Extension toolbar popup
│   └── icons/                       icon16/48/128.png
│
├── models/
│   ├── hand_landmarker.task         MediaPipe hand model (21 landmarks)
│   └── face_landmarker.task         MediaPipe face mesh (468 landmarks)
│
└── test_website/
    ├── index.html                   NovaSuite homepage
    └── pages/
        ├── pricing.html             Complex 30-row comparison table
        ├── docs.html                Long codebase documentation
        ├── onboarding.html          6-step wizard with form validation
        └── settings.html            Account settings (dark mode buried 3 levels deep)
```

---

## Control Panel Tabs

| Tab | What it does |
|-----|--------------|
| **Dashboard** | Chat interface, voice state, extension connection status |
| **AI Models** | Switch provider (OpenAI/Anthropic/Ollama), paste API keys |
| **Voice** | STT engine, TTS engine, wake word, test buttons |
| **Visual** | Hand/eye/sign toggles, sensitivity sliders, calibration, camera feed preview |
| **Gesture Lab** | Custom pose capture, system gesture remapping (see below) |
| **Functions** | Load website registries, preview available actions |
| **Settings** | Assistant name, hotkeys, overlay opacity |

---

## Hotkeys (global, work when app is minimised)

| Shortcut | Action |
|---|---|
| `Ctrl+Space` | Toggle overlay |
| `Ctrl+Shift+Space` | One-shot listen (bypasses wake word) |

Change in Settings tab.

---

## Hand Gestures

EYE recognises a comprehensive set of natural hand motions. All gestures work with either hand and can be remapped in the **Gesture Lab**.

### Primary Gestures

| Gesture | Detection | Action |
|---------|-----------|--------|
| **PINCH** | Thumb + Index tip distance < 0.05 | Scroll up/down by moving hand; quick tap (<250ms) = click |
| **MIDDLE_PINCH** | Thumb + Middle finger pinch | Drag/selection mode — holds mouse-down for highlighting text |
| **POINT** | Index extended, others curled | OS cursor control with adaptive smoothing |
| **OPEN_PALM** | All fingers extended | Stop text-to-speech |
| **FIST** | All fingers curled + thumb check | Close overlay / Dismiss |
| **THUMBS_UP** | Thumb only extended | Confirm action |
| **VICTORY** | Index + Middle extended | Fast scroll / Launch app (configurable) |
| **CALL_ME** | Thumb + Pinky extended (shaka) | Cancel / Launch app (configurable) |

### Two-Hand Gestures

| Gesture | Detection | Action |
|---------|-----------|--------|
| **CLAP** | Both hands close together (palm-to-palm) | Toggle overlay (enable in Gesture Lab) |
| **BOTH_PALMS** | Both hands open simultaneously | Toggle overlay |

### Gesture Customisation

- **Hold-to-trigger**: Gestures require a configurable hold duration (default 2.0s) to prevent accidental activation
- **System remapping**: Built-in gestures can be disabled or remapped to different actions
- **App launching**: Assign gestures to launch any application (.exe, .lnk, or command)

---

## Sign Language Quick-Actions

EYE recognises American Sign Language (ASL) letters for quick actions. These run parallel to geometric gestures and can be used interchangeably.

| ASL Sign | Hand Shape | Default Action |
|----------|------------|----------------|
| **A** | Fist, thumb on side | Confirm |
| **B** | Flat hand, fingers up | Stop speaking |
| **C** | Curved hand | Cancel |
| **D** | Index up, thumb touches middle | Go to docs |
| **G** | Index pointing sideways | Navigate |
| **L** | Thumb + index at 90° | Listen |
| **S** | Fist, thumb over fingers | Search |
| **Y** | Thumb + pinky extended | Open overlay |

---

## Gesture Lab — Custom Signature Creator

The **Gesture Lab** (in the Control Panel) lets you create and manage custom hand signatures:

### Creating a Custom Gesture

1. Open the **Gesture Lab** tab in the Control Panel
2. Enter a name for your gesture (e.g., `metal_sign`, `ok_shape`, `spider_man`)
3. Select an action type:
   - `launch_app` — Launch any application or executable
   - `none` — Trigger a custom event (for future extensions)
4. Enter the target path (e.g., `spotify.exe`, `calc`, `C:\Program Files\App\app.exe`)
5. Click **Learn Pose Signature**
6. A 3-second countdown starts — hold your hand shape steady in front of the camera
7. The pose is saved to `core/custom_poses.json`

### How Pose Matching Works

- **Vector representation**: Each pose is stored as a 63-value normalized vector (wrist-relative landmark positions)
- **Hysteresis confirmation**: Requires 3 consecutive frame matches to prevent false positives
- **Scaled Euclidean distance**: Templates are translated to origin and scaled; match threshold is 0.5
- **Multi-sample capture**: Records 20 frames during learning for robust averaging

### Example Custom Poses (from `core/custom_poses.json`)

```json
{
  "crossed_finger": {
    "vector": [0.0, 0.0, 0.0, -0.12, -0.13, ...],
    "action": "launch_app",
    "params": { "uri": "C:\\ProgramData\\Microsoft\\Windows\\Start Menu\\Programs\\Google Chrome.lnk" }
  },
  "open_spotify": {
    "vector": [0.0, 0.0, 0.0, 0.12, -0.14, ...],
    "action": "launch_app",
    "params": { "uri": "C:\\Users\\Manas\\AppData\\Local\\Microsoft\\WindowsApps\\Spotify.exe" }
  },
  "Malevolent Shrine": {
    "vector": [0.0, 0.0, 0.0, -0.13, -0.18, ...],
    "action": "launch_app",
    "params": { "uri": "calc" }
  }
}
```

### System Gesture Remapping

The **System Gestures** tab lets you toggle or remap built-in gestures:

| Gesture | Default Action | Can Remap To |
|---------|----------------|--------------|
| `clap` | Toggle overlay | launch_app, none |
| `both_palms` | Toggle overlay | launch_app, none |
| `fist` | Close overlay | launch_app, none |
| `thumbs_up` | Confirm | launch_app, none |
| `call_me` | Launch Discord | Any app |
| `victory` | Launch VS Code | Any app |
| `open_palm` | Stop speaking | launch_app, none |

Configuration is stored in `core/system_gestures.json`.

---

## Adding a New Website

Create `~/.aria-assistant/registries/mysite.json`:

```json
{
  "site": "https://mysite.com",
  "name": "My Site",
  "functions": [
    {
      "name": "toggle_dark_mode",
      "description": "Toggle dark mode",
      "params": {},
      "action_type": "js",
      "action": "document.documentElement.classList.toggle('dark')"
    },
    {
      "name": "search_docs",
      "description": "Search documentation for a query",
      "params": {"query": "string — what to search"},
      "action_type": "ai_reason",
      "action": "scrape_docs_and_reason"
    }
  ]
}
```

Action types: `js` · `navigate` · `ai_reason`

---

## Eye Tracking

Webcam-based gaze estimation — no specialist hardware required.

| Feature | Description |
|---------|-------------|
| **Gaze Estimation** | MediaPipe FaceMesh + Iris landmarks (468 facial landmarks) |
| **Dwell Click** | Fixate for 1.2s (configurable) within a 0.06 normalized radius to trigger click |
| **9-Point Calibration** | Polynomial regression (degree 2) maps raw gaze to screen coordinates |
| **Kalman Filter** | 2D Kalman filter + EMA smoothing suppresses jitter |
| **Accuracy** | ±2–4° (~50–100px on 1080p display at 60cm distance) |

### Calibration Process

1. Open the **Visual** tab in Control Panel
2. Click **Calibrate Eye Tracking**
3. A fullscreen overlay shows 9 calibration points in a grid
4. Fixate on each point and press a key to capture
5. Calibration completes when all 9 points are collected

### Limitations

- Requires recalibration if head position moves significantly
- Accuracy depends on lighting and camera quality
- Works best at 60–80cm viewing distance

---

## Technical Highlights

### Performance Optimisations

- **One Euro Filter**: Adaptive smoothing for pointer movement — heavy smoothing when still, minimal during fast motion
- **DirectConnection Signals**: Bypasses Qt UI thread throttling for 30Hz cursor updates
- **High Precision Timers**: Windows-specific optimizations for consistent frame timing
- **Target 30 FPS**: Both hand and eye tracking aim for 30Hz updates

### Active Zone Calibration

Users can define a custom rectangular zone for pointer mapping:
1. Pinch in the top-left corner
2. Pinch in the bottom-right corner
3. The calibrated zone is saved and used for all subsequent pointer movements

This allows precise control even with limited hand movement range.

### Hold-to-Trigger Safety

Discrete gestures (FIST, THUMBS_UP, etc.) require a configurable hold duration (default 2.0s) before triggering. This prevents accidental activations from transient hand positions.

### Multi-Camera Support

Both hand and eye tracking can detect and list available cameras:
```python
# Detects cameras 0–4 and logs resolution/FPS
available_cameras = detect_available_cameras(max_cameras=5)
```

---

## Linux Setup Notes

```bash
# Cursor / scroll control
sudo apt install python3-xlib
# OR: pip install pyautogui

# Global hotkeys — add user to input group, then re-login
sudo usermod -aG input $USER

# PyQt6 on some distros needs
sudo apt install libxcb-cursor0
```

---

## Development Status

| Component | Status | Notes |
|-----------|--------|-------|
| Control Panel (PyQt6) | ✅ Functional | 7 tabs including Gesture Lab |
| Overlay UI | ✅ Functional | Always-on-top, draggable, customizable |
| Voice Pipeline | ✅ Functional | STT, TTS, wake word detection |
| Browser Extension | ✅ Functional | Chrome MV3, WebSocket bridge |
| Hand Tracking | ✅ Functional | 12+ gestures, custom pose learning |
| Eye Tracking | 🧪 Experimental | 9-point calibration, dwell-click |
| Sign Language | 🧪 Experimental | ASL letters A, B, C, D, G, L, S, Y |
| Global Hotkeys | ✅ Functional | Windows ctypes, Linux xlib |
| Website Functions | ✅ Functional | JSON registry system |
| Custom Gestures | ✅ Functional | Vector-based pose matching with hysteresis |
| System Gesture Remap | ✅ Functional | Toggle/remap built-in gestures via JSON |

### What's Next

- [ ] Multi-browser support (Firefox, Edge)
- [ ] Improved eye tracking calibration
- [ ] Expanded ASL vocabulary
- [ ] Mobile companion app
- [ ] Cloud sync for settings

---

## Platform support

| Feature | Windows | Linux |
|---|---|---|
| Control panel | ✅ | ✅ |
| Overlay | ✅ | ✅ |
| Voice (STT/TTS) | ✅ | ✅ |
| Wake word (Vosk) | ✅ | ✅ |
| Chrome extension | ✅ | ✅ |
| Hand tracking | ✅ | ✅ |
| Eye tracking | ✅ | ✅ |
| Sign language | ✅ | ✅ |
| Global hotkeys | ✅ | ✅ (needs input group) |
| Cursor control | ctypes | xlib / pyautogui |

---

## License

MIT
