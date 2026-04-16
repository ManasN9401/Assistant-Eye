import ctypes
import os
import logging

logger = logging.getLogger(__name__)

# ── Efficiency Mode (EcoQoS) ──────────────────────────────────────────────────
# Windows 11 throttles background processes. We must explicitly disable this.
PROCESS_POWER_THROTTLING_CURRENT_VERSION = 1
PROCESS_POWER_THROTTLING_EXECUTION_SPEED = 0x1
PROCESS_POWER_THROTTLING_IGNORE_TIMER_RESOLUTION = 0x4
ProcessPowerThrottling = 0x2

class PROCESS_POWER_THROTTLING_STATE(ctypes.Structure):
    _fields_ = [
        ("Version", ctypes.c_ulong),
        ("ControlMask", ctypes.c_ulong),
        ("StateMask", ctypes.c_ulong),
    ]

def disable_efficiency_mode():
    """
    Tells Windows 11 to NOT throttle this process even when minimized.
    Requires SetProcessInformation (Windows 10 1709+).
    """
    try:
        if os.name != "nt":
            return False

        kernel32 = ctypes.windll.kernel32
        pid = os.getpid()
        # PROCESS_SET_INFORMATION = 0x0200
        handle = kernel32.OpenProcess(0x0200, False, pid)
        if not handle:
            return False

        state = PROCESS_POWER_THROTTLING_STATE()
        state.Version = PROCESS_POWER_THROTTLING_CURRENT_VERSION
        # Control these two flags
        state.ControlMask = PROCESS_POWER_THROTTLING_EXECUTION_SPEED | PROCESS_POWER_THROTTLING_IGNORE_TIMER_RESOLUTION
        # Set them to 0 (Disable throttling)
        state.StateMask = 0

        res = kernel32.SetProcessInformation(
            handle,
            ProcessPowerThrottling,
            ctypes.byref(state),
            ctypes.sizeof(state)
        )
        kernel32.CloseHandle(handle)
        
        if res:
            logger.info("Windows: Efficiency Mode (Throttling) DISABLED for this process.")
            return True
        return False
    except Exception as e:
        logger.error(f"Failed to disable efficiency mode: {e}")
        return False

# ── Timer Resolution ──────────────────────────────────────────────────────────
# Windows default timer resolution is ~15ms. We need 1ms for smooth tracking.
def set_high_precision_timer(enable: bool):
    """Sets the system timer resolution to 1ms (True) or restores it (False)."""
    try:
        if os.name != "nt":
            return
        
        winmm = ctypes.windll.winmm
        if enable:
            # 1ms = 1 period
            res = winmm.timeBeginPeriod(1)
            if res == 0:
                logger.debug("Windows: System timer resolution set to 1ms.")
        else:
            winmm.timeEndPeriod(1)
            logger.debug("Windows: System timer resolution restored.")
    except Exception as e:
        logger.error(f"Failed to set timer resolution: {e}")
