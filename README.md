# EYE — AI Website Assistant Overlay

> ⚠️ **Active Development** — EYE is currently in active development. Core features are functional, but APIs and interfaces may change as we work toward a stable release.

A Python desktop assistant that connects to any website, responds to voice
and text commands, and can control the browser with hands, eyes, and sign language.

EYE runs as an always-on-top overlay that floats above your browser, providing real-time AI assistance while you browse.

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

## Project structure

```
assistant-app/
├── main.py                          Entry point — wires everything together
├── setup.py                         Installer / setup checker
├── requirements.txt
│
├── core/
│   ├── settings.py                  JSON settings (~/.aria-assistant/settings.json)
│   ├── ai_engine.py                 OpenAI / Anthropic / Ollama abstraction
│   ├── function_registry.py         Website action registry system
│   └── hotkeys.py                   Global keyboard shortcuts
│
├── ui/
│   ├── control_panel.py             Main PyQt6 window (6 tabs)
│   ├── overlay.py                   Floating pill overlay (always-on-top)
│   ├── calibration_overlay.py       Fullscreen 9-point eye calibration UI
│   ├── voice_settings.py            Voice tab in control panel
│   ├── visual_settings.py           Visual tab in control panel
│   └── styles.py                    QSS dark industrial theme
│
├── voice/
│   ├── stt_engine.py                Speech-to-text (Whisper local or API)
│   ├── tts_engine.py                Text-to-speech (pyttsx3 / ElevenLabs)
│   ├── wake_word.py                 Wake word detection (Vosk or Porcupine)
│   └── coordinator.py              Orchestrates full voice pipeline
│
├── bridge/
│   ├── ws_server.py                 WebSocket server (port 8765) for Chrome ext
│   └── playwright_bridge.py         Playwright automation + ActionExecutor
│
├── visual/
│   ├── hand_tracker.py              MediaPipe hand gestures (scroll, click, snap)
│   ├── eye_tracker.py               MediaPipe iris gaze + dwell-click
│   ├── sign_language.py             ASL quick-actions + ONNX fingerspelling
│   └── coordinator.py              Combines all visual input + OS cursor control
│
├── browser_extension/
│   ├── manifest.json                Chrome MV3 extension
│   ├── background.js                WebSocket bridge to Python
│   ├── content.js                   Page helper utilities (__aria.*)
│   ├── popup.html / popup.js        Extension toolbar popup
│   └── icons/                       icon16/48/128.png
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

## Control panel tabs

| Tab | What it does |
|---|---|
| Dashboard | Chat interface, voice state, extension connection status |
| AI Models | Switch provider (OpenAI/Anthropic/Ollama), paste API keys |
| Voice | STT engine, TTS engine, wake word, test buttons |
| Visual | Hand/eye/sign toggles, sensitivity sliders, calibration |
| Functions | Load website registries, preview available actions |
| Settings | Assistant name, hotkeys, overlay opacity |

---

## Hotkeys (global, work when app is minimised)

| Shortcut | Action |
|---|---|
| `Ctrl+Space` | Toggle overlay |
| `Ctrl+Shift+Space` | One-shot listen (bypasses wake word) |

Change in Settings tab.

---

## Hand gestures

| Gesture | Action |
|---|---|
| SNAP (middle+thumb pinch) | Open overlay |
| FIST | Close overlay |
| THUMBS UP | Confirm |
| OPEN PALM | Stop TTS |
| PINCH + move up/down | Scroll page |
| Quick pinch (<250ms) | Click |
| POINT (index only) | Move OS cursor |
| CALL ME (thumb+pinky) | Cancel |

---

## Sign language quick-actions

| ASL sign | Action |
|---|---|
| A (fist, thumb side) | Confirm |
| B (flat hand up) | Stop speaking |
| C (curved hand) | Cancel |
| D (index up, thumb-mid touch) | Go to docs |
| G (index sideways) | Navigate |
| L (thumb+index 90°) | Listen |
| S (fist, thumb over) | Search |
| Y (thumb+pinky) | Open overlay |

---

## Adding a new website

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

## Linux setup notes

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
|---|---|---|
| Control Panel (PyQt6) | ✅ Functional | 6 tabs, full settings management |
| Overlay UI | ✅ Functional | Always-on-top, draggable, customizable |
| Voice Pipeline | ✅ Functional | STT, TTS, wake word detection |
| Browser Extension | ✅ Functional | Chrome MV3, WebSocket bridge |
| Hand Tracking | ✅ Functional | MediaPipe gestures (scroll, click, snap) |
| Eye Tracking | 🧪 Experimental | MediaPipe iris + dwell-click |
| Sign Language | 🧪 Experimental | ASL quick-actions (A, B, C, D, G, L, S, Y) |
| Global Hotkeys | ✅ Functional | Windows ctypes, Linux xlib |
| Website Functions | ✅ Functional | JSON registry system |

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
