"""FPS sampling and formatting helpers, used by properties.py."""

import re

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


def normalize_fps(fps_value) -> str:
    """Snap a raw FPS to the nearest broadcast standard (within ±0.5 Hz),
    else return it as a trimmed decimal."""
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
    """Format a raw FPS for the VideoResolution string: snap known fractional
    rates (23.976, 29.97, 59.94, 60.0) to canonical form, else trim to 3 dp."""
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
    """Read /sys/class/video/fps_info as (input_fps, output_fps), or None."""
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


def get_fps_data() -> tuple[int, int, int]:
    """Return the current (input_fps, output_fps, drop) from the sysfs node,
    or zeroes when it can't be read."""
    result = _read_fps_sysfs()
    if not result:
        return 0, 0, 0

    in_fps, out_fps = result
    return in_fps, out_fps, max(0, in_fps - out_fps)


def fps_display_texts() -> tuple[str, str]:
    """Return (info_text, output_fps_text) for the FPS row; info_text is
    'NNN - DDD' (input - drop)."""
    in_fps, out_fps, drop = get_fps_data()
    return f"{in_fps:03d} - {drop:03d}", str(out_fps if out_fps > 0 else 0)
