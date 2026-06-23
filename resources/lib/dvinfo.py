"""
dvinfo.py – Dolby Vision Content-Mapping version detection for TinyPPI.

Determines whether the playing Dolby Vision stream carries CM v2.9 or
CM v4.0 metadata by extracting the RPU with dovi_tool and reading its
summary line ("DM version"). The same summary is used for separate Level 6
and Level 5 metadata properties.

Kodi plays from VFS URLs (nfs://, smb://, http:// ...) which standalone
ffmpeg / dovi_tool cannot open.  We bridge that with xbmcvfs: the first
chunk of the stream is pulled through Kodi's VFS into special://temp/ and
the userspace tools run on that local chunk.  No OS-level mount required,
so it works for every TinyPPI user.

Detection runs once per file in a background thread and is cached, so the
polling loop in overlay.py never blocks.  The results are published through
the Dolby Vision properties in properties.py.  CoreELEC only.

Bundle the dovi_tool binary at:
    resources/bin/aarch64/dovi_tool
DV-capable Amlogic SoCs (S905X2/X4/X5, S922X) are all 64-bit, so aarch64
covers every realistic target.
"""

import os
import re
import subprocess
import threading

import xbmc
import xbmcaddon
import xbmcvfs

from utils import _info

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ADDON      = xbmcaddon.Addon()
_ADDON_PATH = _ADDON.getAddonInfo("path")

_TEMP_DIR   = xbmcvfs.translatePath("special://temp/")
_CHUNK_PATH = os.path.join(_TEMP_DIR, "tinyppi_dv.chunk")
_RPU_PATH   = os.path.join(_TEMP_DIR, "tinyppi_dv.rpu")

# 32 MiB comfortably holds the first GOP (keyframe + RPU) even at UHD Blu-ray
# bitrates; the frame cap keeps the work tiny and tolerant of the truncated
# chunk.  A single frame would already reveal the CM version.
_CHUNK_BYTES  = 32 * 1024 * 1024
_FRAMES       = 24
_MAX_ATTEMPTS = 3

_LABEL_FETCH = 32096
_LABEL_NA    = 32033

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

_result:    dict[str, dict[str, str]] = {}  # path -> DV metadata fields
_attempts:  dict[str, int] = {}     # path -> attempt count
_inflight:  set[str]       = set()  # paths currently being processed
_lock                      = threading.Lock()
_ffmpeg_cached: str | None = None   # "" once searched and not found

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _log(msg: str, level: int = xbmc.LOGINFO) -> None:
    xbmc.log(f"TinyPPI: {msg}", level)


def _localized(label_id: int, fallback: str) -> str:
    """Return an addon-localized label, falling back when Kodi has no string."""
    text = _ADDON.getLocalizedString(label_id)
    return text or fallback


def _fetch_label() -> str:
    """Return the localized label shown while DV metadata is being fetched."""
    return _localized(_LABEL_FETCH, "Fetching...")


def _na_label() -> str:
    """Return the localized label shown when DV metadata could not be fetched."""
    return _localized(_LABEL_NA, "N/A")


def is_status_label(value: str) -> bool:
    """Return True when a value is a localized DV metadata status label."""
    return value in (_fetch_label(), _na_label())


def _dovi_tool() -> str:
    """Return the bundled dovi_tool path, restoring the exec bit if needed."""
    arch = "aarch64"
    path = os.path.join(_ADDON_PATH, "resources", "bin", arch, "dovi_tool")
    if os.path.exists(path) and not os.access(path, os.X_OK):
        # The executable bit is frequently lost when an addon is packaged as a
        # zip and unpacked on install; restore it defensively.
        try:
            os.chmod(path, 0o755)
        except OSError:
            pass
    return path


def _ffmpeg() -> str | None:
    """Locate the ffmpeg binary provided by the tools.ffmpeg-tools addon."""
    global _ffmpeg_cached
    if _ffmpeg_cached is not None:
        return _ffmpeg_cached or None

    try:
        base = xbmcaddon.Addon("tools.ffmpeg-tools").getAddonInfo("path")
    except Exception:
        _ffmpeg_cached = ""
        return None

    candidates = [os.path.join(base, "bin", "ffmpeg"),
                  os.path.join(base, "ffmpeg")]
    if not any(os.path.exists(c) for c in candidates):
        for root, _dirs, files in os.walk(base):
            if "ffmpeg" in files:
                candidates.append(os.path.join(root, "ffmpeg"))
                break

    for cand in candidates:
        if os.path.exists(cand):
            _ffmpeg_cached = cand
            return cand

    _ffmpeg_cached = ""
    return None


def _local_source(path: str) -> tuple[str, bool]:
    """
    Return ``(local_path, is_temp)``.

    VFS URLs are partially copied into special://temp/ via xbmcvfs; real
    filesystem paths are used directly (ffmpeg only reads the first frames).
    """
    if path.startswith("/"):
        return path, False

    f = xbmcvfs.File(path)
    try:
        data = f.readBytes(_CHUNK_BYTES)
    finally:
        f.close()

    with open(_CHUNK_PATH, "wb") as out:
        out.write(data)
    return _CHUNK_PATH, True


def _compact_cm_version(line: str) -> str:
    """Return a compact CM version label from a dovi_tool DM version line."""
    lower = line.lower()
    has_29 = "2.9" in lower
    has_40 = "4.0" in lower

    if has_29 and has_40:
        return "CMv2.9/4.0"
    if has_40 or re.search(r"dm version:\s*2\b", lower):
        return "CMv4.0"
    if has_29 or re.search(r"dm version:\s*1\b", lower):
        return "CMv2.9"
    return ""


def _compact_l6_mdl(entry: str) -> str:
    """Return concise Level 6 mastering-display luminance."""
    mdl = re.search(
        r"Mastering display:\s*([0-9.]+)\s*/\s*([0-9.]+)\s*nits",
        entry,
        re.IGNORECASE,
    )

    if mdl:
        return f"{mdl.group(1)} | {mdl.group(2)}"

    return ""


def _compact_l6_max_cll_fall(entry: str) -> str:
    """Return concise Level 6 MaxCLL/MaxFALL metadata."""
    maxcll = re.search(r"MaxCLL:\s*([0-9.]+)\s*nits", entry, re.IGNORECASE)
    maxfall = re.search(r"MaxFALL:\s*([0-9.]+)\s*nits", entry, re.IGNORECASE)

    if maxcll and maxfall:
        return f"{maxcll.group(1)} | {maxfall.group(1)}"

    return ""


def _compact_l5_offsets(offsets: str) -> str:
    """Return compact Level 5 active-area offsets in L/R/T/B order."""
    matches = dict(re.findall(r"\b(top|bottom|left|right)=([^,\s]+)", offsets))

    if matches:
        def normalize(value: str) -> str:
            return "0" if value == "N/A" else value

        left = normalize(matches.get("left", "0"))
        right = normalize(matches.get("right", "0"))
        top = normalize(matches.get("top", "0"))
        bottom = normalize(matches.get("bottom", "0"))

        return f"{left} | {right} | {top} | {bottom}"

    return re.sub(r"\s+", " ", offsets).strip()


def _parse_summary(out: str) -> dict[str, str]:
    """Parse dovi_tool summary output into separate overlay fields."""
    cm_version = ""
    l6_entries: list[str] = []
    l5_offsets = ""
    lines = out.splitlines()

    idx = 0
    while idx < len(lines):
        stripped = lines[idx].strip()

        if stripped.startswith("DM version:"):
            cm_version = _compact_cm_version(stripped)
        elif stripped.startswith("L6 metadata"):
            rest = stripped[len("L6 metadata"):].strip()
            if rest.startswith(":"):
                rest = rest[1:].strip()
            if rest:
                l6_entries.append(rest)
            else:
                idx += 1
                while idx < len(lines):
                    continuation = lines[idx].strip()
                    if not continuation:
                        break
                    if re.match(
                        r"^(L\d+\s|RPU\s|Scene/shot|Profile|Frames|DM version:)",
                        continuation,
                    ):
                        idx -= 1
                        break
                    l6_entries.append(continuation)
                    idx += 1
        elif stripped.startswith("L5 offsets:"):
            l5_offsets = stripped.split(":", 1)[1].strip()

        idx += 1

    l6_mdl_values = [_compact_l6_mdl(entry) for entry in l6_entries]
    l6_max_values = [_compact_l6_max_cll_fall(entry) for entry in l6_entries]

    return {
        "cm_version": cm_version,
        "l5_offsets": _compact_l5_offsets(l5_offsets) if l5_offsets else "",
        "l6_mdl": "; ".join(value for value in l6_mdl_values if value),
        "l6_max_cll_fall": "; ".join(value for value in l6_max_values if value),
    }


def _detect(path: str) -> dict[str, str]:
    """Return compact Dolby Vision metadata for the given playing path."""
    dovi   = _dovi_tool()
    ffmpeg = _ffmpeg()
    if not os.path.exists(dovi):
        _log(f"DV: dovi_tool binary missing ({dovi})", xbmc.LOGWARNING)
        return {}
    if not ffmpeg:
        _log("DV: tools.ffmpeg-tools not available", xbmc.LOGWARNING)
        return {}

    src, is_temp = _local_source(path)
    try:
        # ffmpeg copies the first _FRAMES video frames as Annex-B HEVC and
        # pipes them into dovi_tool, which writes the parsed RPU.  A truncated
        # chunk may make dovi_tool log an error on the final frame, so the
        # exit code is ignored and only a non-empty RPU is required.
        ff = subprocess.Popen(
            [ffmpeg, "-loglevel", "error", "-i", src, "-map", "0:v:0",
             "-c:v", "copy", "-frames:v", str(_FRAMES),
             "-bsf:v", "hevc_mp4toannexb", "-f", "hevc", "-"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        subprocess.run([dovi, "extract-rpu", "-", "-o", _RPU_PATH],
                       stdin=ff.stdout,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if ff.stdout:
            ff.stdout.close()
        ff.wait()

        if not os.path.exists(_RPU_PATH) or os.path.getsize(_RPU_PATH) == 0:
            return {}

        out = subprocess.run(
            [dovi, "info", "-i", _RPU_PATH, "-s"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True).stdout

        return _parse_summary(out)
    finally:
        for tmp in (_RPU_PATH, _CHUNK_PATH if is_temp else None):
            if tmp and os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass


def _worker(path: str) -> None:
    """Background detection job; caches only positive results."""
    try:
        info = _detect(path)
    except Exception as exc:
        _log(f"DV CM detection failed: {exc}", xbmc.LOGWARNING)
        info = {}
    with _lock:
        _inflight.discard(path)
        if any(info.values()):
            _result[path] = info


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _get_info_status_value(key: str) -> tuple[str, str]:
    """
    Non-blocking.  Return one cached DV metadata field for the current file,
    kicking off detection in the background on first call.

    Returns ``(value, status)`` where status is ``''`` for non-DV/no-file,
    ``'fetching'`` while detection is running, ``'ready'`` once a field has
    been found, and ``'failed'`` once the field cannot be determined.
    """
    if (key == "cm_version" and "dolby" not in _info("VideoPlayer.HdrType").lower()):
        return "", ""

    try:
        path = xbmc.Player().getPlayingFile()
    except RuntimeError:
        return "", ""
    if not path:
        return "", ""

    with _lock:
        if path in _result:
            value = _result[path].get(key, "")
            return value, "ready" if value else "failed"
        if path in _inflight or _attempts.get(path, 0) >= _MAX_ATTEMPTS:
            if path in _inflight:
                return "", "fetching"
            return "", "failed"
        _inflight.add(path)
        _attempts[path] = _attempts.get(path, 0) + 1

    threading.Thread(target=_worker, args=(path,), daemon=True).start()
    return "", "fetching"


def _get_info_value(key: str) -> str:
    """Return a display-ready DV metadata field or localized status label."""
    value, status = _get_info_status_value(key)
    if value:
        return value
    if status == "fetching":
        return _fetch_label()
    if status == "failed":
        return _na_label()
    return ""


def _get_level_info_value(key: str) -> str:
    """Return a Level 5/6 display value, falling back to localized N/A."""
    return _get_info_value(key) or _na_label()


def get_cm_version() -> str:
    """Return the source Dolby Vision Content-Mapping version."""
    return _get_info_value("cm_version")


def get_l5_offsets() -> str:
    """Return Dolby Vision Level 5 active-area offsets."""
    return _get_level_info_value("l5_offsets")


def get_l6_rpu_mdl() -> str:
    """Return Dolby Vision Level 6 RPU mastering-display luminance."""
    return _get_level_info_value("l6_mdl")


def get_l6_rpu_max_cll_fall() -> str:
    """Return Dolby Vision Level 6 RPU MaxCLL/MaxFALL."""
    return _get_level_info_value("l6_max_cll_fall")
