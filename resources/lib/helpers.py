"""
helpers.py – Domain-specific helper functions for TinyPPI.

Covers FPS sampling and HDR/Dolby Vision log parsing.  These are
implementation details used by properties.py — not part of the public
addon API.
"""

import os
import re
import time

# ---------------------------------------------------------------------------
# FPS helpers
# ---------------------------------------------------------------------------

_FPS_STANDARDS = (
    23.976, 24.0, 25.0, 29.97, 30.0, 50.0, 59.94, 60.0, 100.0, 120.0,
)
_EXACT_FPS_LABELS = {23.976: "23.976", 29.97: "29.97", 59.94: "59.94"}
_FORMAT_FPS_TARGETS = (
    (23.976, 0.02),
    (29.97, 0.02),
    (59.94, 0.02),
    (60.0, 0.01),
)
_FPS_SAMPLE_INTERVAL = 0.1
_FPS_HISTORY_SECONDS = 1.0

# Rolling AML FPS state (mutated by _update_fps).
_FPS = {
    "history":     [],
    "last_sample": 0.0,
}


def normalize_fps(fps_value) -> str:
    """
    Snap a raw FPS float to the nearest broadcast standard and return a
    display string.  Values that don't fall within ±0.5 Hz of a standard
    are returned as trimmed decimals.
    """
    try:
        fps = float(fps_value)
    except (TypeError, ValueError):
        return str(fps_value)

    closest = min(_FPS_STANDARDS, key=lambda x: abs(x - fps))

    if abs(closest - fps) > 0.5:
        return f"{fps:.3f}".rstrip("0").rstrip(".")

    if closest in _EXACT_FPS_LABELS:
        return _EXACT_FPS_LABELS[closest]

    return str(int(closest)) if closest.is_integer() else str(closest)


def format_fps(fps_value) -> str:
    """
    Format a raw FPS float for the VideoResolution display string.
    Snaps well-known fractional rates (23.976, 29.97, 59.94, 60.0) to their
    canonical representations; others are trimmed to 3 decimal places.
    """
    try:
        fps = float(fps_value)
    except (TypeError, ValueError):
        return ""

    for target, tol in _FORMAT_FPS_TARGETS:
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

    in_m  = re.search(r"input_fps:0x([0-9a-fA-F]+)", raw)
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

    if now - state["last_sample"] < _FPS_SAMPLE_INTERVAL:
        return
    state["last_sample"] = now

    result = _read_fps_sysfs()
    if result:
        in_fps, out_fps = result
        state["history"].append((in_fps, out_fps, now))

    state["history"] = [
        x for x in state["history"]
        if now - x[2] <= _FPS_HISTORY_SECONDS
    ]


def get_fps_data() -> tuple[int, int, int]:
    """
    Return ``(avg_input_fps, avg_output_fps, avg_drop)`` averaged over the
    rolling 1-second history.  All values are integers.
    """
    _update_fps()
    history = _FPS["history"]

    if not history:
        return 0, 0, 0

    count   = len(history)
    avg_in  = sum(x[0] for x in history) / count
    avg_out = sum(x[1] for x in history) / count
    drop    = max(0, avg_in - avg_out)

    return int(round(avg_in)), int(round(avg_out)), int(round(drop))


def fps_display_texts() -> tuple[str, str]:
    """
    Return ``(info_text, output_fps_text)`` for the FPS display row.
    ``info_text`` is formatted as ``'NNN - DDD'`` (input minus drop).
    """
    in_fps, out_fps, drop = get_fps_data()
    return f"{in_fps:03d} - {drop:03d}", str(out_fps if out_fps > 0 else 0)


# ---------------------------------------------------------------------------
# HDR / Dolby Vision helpers
# ---------------------------------------------------------------------------

_HDR_STATUS_PATH = "/sys/devices/virtual/amhdmitx/amhdmitx0/hdmi_hdr_status"
_KODI_LOG_PATH   = "/storage/.kodi/temp/kodi.log"
_DOVI_LOG_LINES  = 2000

# The Kodi log grows unbounded during a session; reading it in full every
# polling cycle gets progressively slower.  256 KiB comfortably covers the
# last _DOVI_LOG_LINES lines, so only that tail is read.
_DOVI_LOG_TAIL_BYTES = 256 * 1024

_DOVI_PROFILE_RE = re.compile(r"profile\s.*")


def read_hdr_status() -> str:
    """Return the raw content of the HDMI HDR status sysfs node (lowercased)."""
    try:
        with open(_HDR_STATUS_PATH, encoding="utf-8", errors="ignore") as f:
            return f.read().strip().lower()
    except OSError:
        return ""


def read_last_dovi_log_line() -> str:
    """
    Scan the last ``_DOVI_LOG_LINES`` lines of the Kodi log and return the
    text of the most recent line that matches ``profile <n> …``.

    Returns an empty string when no matching line is found or the log cannot
    be read.
    """
    try:
        with open(_KODI_LOG_PATH, "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - _DOVI_LOG_TAIL_BYTES))
            tail = f.read().decode("utf-8", errors="ignore")
    except OSError:
        return ""

    for line in reversed(tail.splitlines()[-_DOVI_LOG_LINES:]):
        m = _DOVI_PROFILE_RE.search(line)
        if m:
            return m.group(0)
    return ""
