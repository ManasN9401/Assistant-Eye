#!/usr/bin/env python3
"""
ARIA Assistant — Setup Script
Checks prerequisites, installs Python deps, and prints next steps.

Usage:
    python setup.py

Supports: Windows 10+, Ubuntu 20.04+, Debian 11+, Arch Linux
"""
import sys
import subprocess
import shutil
import platform
import os
from pathlib import Path


BOLD   = "\033[1m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
CYAN   = "\033[96m"
RESET  = "\033[0m"

OS = platform.system()  # "Windows" | "Linux" | "Darwin"


def header(text):
    print(f"\n{BOLD}{CYAN}{'─' * 58}{RESET}")
    print(f"{BOLD}{CYAN}  {text}{RESET}")
    print(f"{BOLD}{CYAN}{'─' * 58}{RESET}")


def ok(text):    print(f"  {GREEN}✓{RESET}  {text}")
def warn(text):  print(f"  {YELLOW}⚠{RESET}  {text}")
def err(text):   print(f"  {RED}✗{RESET}  {text}")
def info(text):  print(f"     {text}")


def run(cmd, check=True, capture=False):
    kwargs = dict(shell=True, check=check)
    if capture:
        kwargs["stdout"] = subprocess.PIPE
        kwargs["stderr"] = subprocess.PIPE
        kwargs["text"]   = True
    return subprocess.run(cmd, **kwargs)


def check_python():
    header("Python version")
    v = sys.version_info
    if v.major < 3 or (v.major == 3 and v.minor < 10):
        err(f"Python {v.major}.{v.minor} found — 3.10+ required")
        info("Download from https://python.org/downloads")
        sys.exit(1)
    ok(f"Python {v.major}.{v.minor}.{v.micro}")


def check_pip():
    header("pip")
    result = run("pip --version", check=False, capture=True)
    if result.returncode != 0:
        err("pip not found")
        info("Usually bundled with Python. Try: python -m ensurepip")
        sys.exit(1)
    ok(result.stdout.strip().split("\n")[0])


def install_deps(phase: str):
    header(f"Installing Python dependencies ({phase})")

    # Core + Phase 1–2 always
    core_deps = [
        "PyQt6", "openai", "anthropic", "playwright", "requests",
        "keyboard", "websockets", "python-dotenv",
        # Voice
        "sounddevice", "soundfile", "numpy", "pyttsx3",
    ]

    print("  Installing core deps (this may take a minute)…")
    run(f"pip install {' '.join(core_deps)} --quiet")
    ok("Core deps installed")

    # faster-whisper (optional but recommended)
    print("  Installing faster-whisper (local Whisper STT)…")
    result = run("pip install faster-whisper --quiet", check=False)
    if result.returncode == 0:
        ok("faster-whisper installed")
    else:
        warn("faster-whisper install failed — OpenAI Whisper API will be used instead")

    if phase in ("3", "all"):
        print("  Installing visual input deps (opencv, mediapipe)…")
        result = run("pip install opencv-python mediapipe onnxruntime --quiet", check=False)
        if result.returncode == 0:
            ok("Visual deps installed")
        else:
            warn("Visual deps install failed — hand/eye tracking will not work")

        if OS == "Linux":
            print("  Installing Linux cursor control deps…")
            result = run("pip install python-xlib pyautogui --quiet", check=False)
            if result.returncode == 0:
                ok("Linux cursor deps installed")
            else:
                warn("python-xlib install failed — pyautogui fallback will be used")


def install_playwright():
    header("Playwright browsers")
    result = run("playwright install chromium --quiet", check=False)
    if result.returncode == 0:
        ok("Chromium installed")
    else:
        warn("Playwright install failed — Playwright bridge won't work (extension mode still OK)")


def linux_input_group():
    if OS != "Linux":
        return
    header("Linux: keyboard input permissions")
    user = os.environ.get("USER", "")
    if not user:
        warn("Could not determine current user — skipping group check")
        return

    result = run("groups", check=False, capture=True)
    if "input" in result.stdout:
        ok(f"User '{user}' already in 'input' group — global hotkeys should work")
    else:
        warn(f"User '{user}' is not in the 'input' group")
        info("Global hotkeys (Ctrl+Space) require /dev/input access.")
        info("Run the following, then log out and back in:")
        info(f"  sudo usermod -aG input {user}")
        info("Alternatively, run ARIA with sudo (not recommended).")


def create_env_file():
    header("Environment file")
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        ok(".env already exists — skipping")
        return
    env_path.write_text(
        "# ARIA Assistant — API keys\n"
        "# These are read at startup if not set in the control panel settings.\n\n"
        "OPENAI_API_KEY=\n"
        "ANTHROPIC_API_KEY=\n"
        "ELEVENLABS_API_KEY=\n"
        "PICOVOICE_ACCESS_KEY=\n"
    )
    ok(f".env created at {env_path}")
    info("Edit it to add your API keys (optional — can also be set in the app UI)")


def print_next_steps():
    header("Setup complete — next steps")
    print(f"""
  {BOLD}1. Start the test website:{RESET}
     cd test_website
     python -m http.server 5500
     # → http://localhost:5500

  {BOLD}2. Launch ARIA:{RESET}
     python main.py

  {BOLD}3. Load the Chrome extension:{RESET}
     Chrome → chrome://extensions → Developer mode ON
     → Load unpacked → select the browser_extension/ folder

  {BOLD}4. Add your API key:{RESET}
     In the control panel → AI Models → paste your OpenAI or Anthropic key

  {BOLD}5. Load the NovaSuite registry:{RESET}
     Control panel → Functions → select NovaSuite → Load

  {BOLD}6. Try these commands:{RESET}
     • "Go to the pricing page"
     • "Turn on dark mode"
     • "What plan would suit a 10-person software team?"
     • "Search the docs for webhook setup"

  {BOLD}Voice (Phase 2):{RESET}
     Control panel → Voice → enable wake word → say "hey aria"

  {BOLD}Visual input (Phase 3):{RESET}
     Control panel → Visual → enable hand tracking
     SNAP gesture (middle+thumb pinch) opens the overlay

  {CYAN}Full docs in README.md{RESET}
""")


def main():
    print(f"\n{BOLD}ARIA Assistant — Setup{RESET}")
    print(f"Platform: {OS} {platform.machine()}")
    print(f"Python:   {sys.version.split()[0]}")

    phase = "all"
    if len(sys.argv) > 1:
        phase = sys.argv[1]   # "1", "2", "3", or "all"

    check_python()
    check_pip()
    install_deps(phase)
    install_playwright()
    if OS == "Linux":
        linux_input_group()
    create_env_file()
    print_next_steps()


if __name__ == "__main__":
    main()
