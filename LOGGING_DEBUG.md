# Visual Tracking Debug Logging

## Overview

The visual tracking modules (eye tracker, hand tracker, sign language) now include comprehensive debug logging to help diagnose camera detection and tracking issues.

## Log Levels

### Console Output (INFO level)
- Camera detection status
- Starting/stopping trackers
- High-level errors
- Model loading information

### Debug Log File (DEBUG level)
All console output PLUS:
- Individual camera properties (resolution, FPS)
- Detailed error messages
- Camera backend information
- Model loading details

## Log File Location

The debug log is saved to: **`eye_tracking_debug.log`** (in the current working directory)

This file is appended to on each run, so it accumulates logs from multiple sessions.

## Camera Detection Logging

When any tracker starts, it automatically logs:

```
Available cameras: [0, 1]
Camera 0 detected: 1920x1080 @ 30.0 FPS
Camera 1 detected: 1280x720 @ 15.0 FPS
Starting eye tracking on camera 0
Camera 0 properties:
  Resolution: 1920x1080
  FPS: 30.0
  Backend: (backend name)
```

## Using the Logs

1. **Check available cameras:**
   ```bash
   grep "Available cameras" eye_tracking_debug.log
   ```

2. **See all camera properties:**
   ```bash
   grep "detected:" eye_tracking_debug.log
   ```

3. **Troubleshoot startup issues:**
   ```bash
   tail -50 eye_tracking_debug.log
   ```

4. **Find errors:**
   ```bash
   grep "ERROR\|error" eye_tracking_debug.log
   ```

## Example Log Output

```
2026-04-05 14:32:15 - visual.logging_config - INFO - Logging initialized - Debug log: /path/to/eye_tracking_debug.log
2026-04-05 14:32:15 - visual.coordinator - INFO - VisualCoordinator initialized
2026-04-05 14:32:16 - visual.eye_tracker - INFO - Available cameras: [0, 1]
2026-04-05 14:32:16 - visual.eye_tracker - DEBUG - Camera 0 detected: 1920x1080 @ 30.0 FPS
2026-04-05 14:32:16 - visual.eye_tracker - DEBUG - Camera 1 detected: 1280x720 @ 15.0 FPS
2026-04-05 14:32:16 - visual.eye_tracker - INFO - Starting eye tracking on camera 0
2026-04-05 14:32:16 - visual.eye_tracker - DEBUG - Camera 0 properties:
2026-04-05 14:32:16 - visual.eye_tracker - DEBUG -   Resolution: 1920x1080
2026-04-05 14:32:16 - visual.eye_tracker - DEBUG -   FPS: 30.0
```

## Viewing Logs in Real-Time

On Linux/Mac:
```bash
tail -f eye_tracking_debug.log
```

On Windows (PowerShell):
```powershell
Get-Content eye_tracking_debug.log -Wait
```

## Log Configuration

To customize logging, edit `visual/logging_config.py`:
- Change `level=logging.DEBUG` to `logging.INFO` for less verbose output
- Modify the log file path
- Adjust the log format string
