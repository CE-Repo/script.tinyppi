"""
helpers.py – Domain-specific helper functions for TinyPPI.

Covers FPS sampling, HDR/Dolby Vision log parsing, and UI positioning.
These are implementation details used by properties.py — not part of the
public addon API.
"""

import re
import time

import xbmc
import xbmcgui

from maps import _FPS

# ---------------------------------------------------------------------------
# FPS helpers
# ---------------------------------------------------------------------------

def _normalize_fps(fps_value) -> str:
    """
    Snap a raw FPS float to the nearest broadcast standard and return a
    display string.  Values that don't fall within ±0.5 Hz of a standard
    are returned as trimmed decimals.
    """
    try:
        fps = float(fps_value)
    except (TypeError, ValueError):
        return str(fps_value)

    standards = [23.976, 24.0, 25.0, 29.97, 30.0, 50.0, 59.94, 60.0, 100.0, 120.0]
    closest = min(standards, key=lambda x: abs(x - fps))

    if abs(closest - fps) > 0.5:
        return f"{fps:.3f}".rstrip("0").rstrip(".")

    _exact = {23.976: "23.976", 29.97: "29.97", 59.94: "59.94"}
    if closest in _exact:
        return _exact[closest]

    return str(int(closest)) if closest.is_integer() else str(closest)


def _format_fps(fps_value) -> str:
    """
    Format a raw FPS float for the VideoResolution display string.
    Snaps well-known fractional rates (23.976, 29.97, 59.94, 60.0) to their
    canonical representations; others are trimmed to 3 decimal places.
    """
    try:
        fps = float(fps_value)
    except (TypeError, ValueError):
        return ""

    targets = [(23.976, 0.02), (29.97, 0.02), (59.94, 0.02), (60.0, 0.01)]
    for target, tol in targets:
        if abs(fps - target) <= tol:
            fps = target
            break

    if fps == int(fps):
        return str(int(fps))
    return f"{fps:.3f}".rstrip("0").rstrip(".")


def _read_fps_sysfs() -> tuple[int, int] | None:
    """
    Read ``/sys/class/video/fps_info`` and return ``(input_fps, output_fps)``
    as integer fixed-point values, or ``None`` on failure.
    """
    try:
        with open("/sys/class/video/fps_info", encoding="utf-8", errors="ignore") as f:
            raw = f.read().strip()
    except OSError:
        return None

    in_m  = re.search(r"input_fps:0x([0-9a-fA-F]+)",  raw)
    out_m = re.search(r"output_fps:0x([0-9a-fA-F]+)", raw)
    if not in_m or not out_m:
        return None

    return int(in_m.group(1), 16), int(out_m.group(1), 16)


def _update_fps() -> None:
    """
    Sample the sysfs FPS node (rate-limited to once per 100 ms) and append
    to the rolling history in ``_FPS``.  Entries older than 1 second are
    pruned automatically.
    """
    now   = time.monotonic()
    state = _FPS

    if now - state["last_sample"] < 0.1:
        return
    state["last_sample"] = now

    result = _read_fps_sysfs()
    if result:
        in_fps, out_fps = result
        state["cached_in"]  = in_fps
        state["cached_out"] = out_fps
        state["valid"]      = True
        state["history"].append((in_fps, out_fps, now))

    state["history"] = [x for x in state["history"] if now - x[2] <= 1.0]


def get_fps_data() -> tuple[int, int, int]:
    """
    Return ``(avg_input_fps, avg_output_fps, avg_drop)`` averaged over the
    rolling 1-second history.  All values are integers.
    """
    _update_fps()
    state = _FPS

    if not state["history"]:
        return 0, 0, 0

    count   = len(state["history"])
    avg_in  = sum(x[0] for x in state["history"]) / count
    avg_out = sum(x[1] for x in state["history"]) / count
    drop    = max(0, avg_in - avg_out)

    return int(round(avg_in)), int(round(avg_out)), int(round(drop))


def format_fps() -> tuple[str, str]:
    """
    Return ``(info_text, output_fps_text)`` for the FPS display row.
    ``info_text`` is formatted as ``'NNN - DDD'`` (input minus drop).
    """
    in_fps, out_fps, drop = get_fps_data()
    return f"{in_fps:03d} - {drop:03d}", str(int(out_fps) if out_fps > 0 else 0)


# ---------------------------------------------------------------------------
# HDR / Dolby Vision helpers
# ---------------------------------------------------------------------------

_HDR_STATUS_PATH = "/sys/devices/virtual/amhdmitx/amhdmitx0/hdmi_hdr_status"
_KODI_LOG_PATH   = "/storage/.kodi/temp/kodi.log"
_DOVI_LOG_LINES  = 2000


def _read_hdr_status() -> str:
    """Return the raw content of the HDMI HDR status sysfs node (lowercased)."""
    try:
        with open(_HDR_STATUS_PATH, encoding="utf-8", errors="ignore") as f:
            return f.read().strip().lower()
    except OSError:
        return ""


def _read_last_dovi_log_line() -> str:
    """
    Scan the last ``_DOVI_LOG_LINES`` lines of the Kodi log and return the
    text of the most recent line that matches ``profile <n> …``.

    Returns an empty string when no matching line is found or the log cannot
    be read.
    """
    pattern = re.compile(r"profile\s.*")
    try:
        with open(_KODI_LOG_PATH, encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()[-_DOVI_LOG_LINES:]
    except OSError:
        return ""

    for line in reversed(lines):
        m = pattern.search(line)
        if m:
            return m.group(0)
    return ""


# ---------------------------------------------------------------------------
# UI helpers
# ---------------------------------------------------------------------------

def set_ui_position(window) -> None:
    """Adjust the overlay group position based on the active UI style setting."""
    ui_style = xbmcgui.Window(10000).getProperty("TinyPPI.UIStyle")
    left, top = (40, 575) if ui_style == "1" else (15, 600)
    window.getControl(9000).setPosition(left, top)
