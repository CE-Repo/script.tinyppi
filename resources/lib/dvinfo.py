"""
dvinfo.py – Dolby Vision Content-Mapping version detection for TinyPPI.

Determines whether the playing Dolby Vision stream carries CM v2.9 or
CM v4.0 metadata by extracting the RPU with dovi_tool and reading its
summary line ("DM version").

Kodi plays from VFS URLs (nfs://, smb://, http:// ...) which standalone
ffmpeg / dovi_tool cannot open.  We bridge that with xbmcvfs: the first
chunk of the stream is pulled through Kodi's VFS into special://temp/ and
the userspace tools run on that local chunk.  No OS-level mount required,
so it works for every TinyPPI user.

Detection runs once per file in a background thread and is cached, so the
polling loop in overlay.py never blocks.  The result is published through
properties.get_DoviCmVersionVar().  CoreELEC only.

Bundle the dovi_tool binary at:
    resources/bin/aarch64/dovi_tool
DV-capable Amlogic SoCs (S905X2/X4/X5, S922X) are all 64-bit, so aarch64
covers every realistic target.
"""

import os
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

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

_result:    dict[str, str] = {}     # path -> "CMv2.9" | "CMv4.0"
_attempts:  dict[str, int] = {}     # path -> attempt count
_inflight:  set[str]       = set()  # paths currently being processed
_lock                      = threading.Lock()
_ffmpeg_cached: str | None = None   # "" once searched and not found

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _log(msg: str, level: int = xbmc.LOGINFO) -> None:
    xbmc.log(f"TinyPPI: {msg}", level)


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


def _detect(path: str) -> str:
    """Return ``'CMv2.9'``, ``'CMv4.0'`` or ``''`` for the given playing path."""
    dovi   = _dovi_tool()
    ffmpeg = _ffmpeg()
    if not os.path.exists(dovi):
        _log(f"DV: dovi_tool binary missing ({dovi})", xbmc.LOGWARNING)
        return ""
    if not ffmpeg:
        _log("DV: tools.ffmpeg-tools not available", xbmc.LOGWARNING)
        return ""

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
            return ""

        out = subprocess.run(
            [dovi, "info", "-i", _RPU_PATH, "-s"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True).stdout

        for line in out.splitlines():
            if "DM version" in line:           # e.g. "DM version: 2 (CM v4.0)"
                return "CMv4.0" if "v4.0" in line else "CMv2.9"
        return ""
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
        ver = _detect(path)
    except Exception as exc:
        _log(f"DV CM detection failed: {exc}", xbmc.LOGWARNING)
        ver = ""
    with _lock:
        _inflight.discard(path)
        if ver:
            _result[path] = ver


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_cm_version() -> str:
    """
    Non-blocking.  Return the cached CM version for the currently playing file,
    kicking off detection in the background on first call.

    Returns ``''`` until the result is ready, when the source is not Dolby
    Vision, or after _MAX_ATTEMPTS failed attempts for the same file.
    """
    if "dolby" not in _info("VideoPlayer.HdrType").lower():
        return ""

    try:
        path = xbmc.Player().getPlayingFile()
    except RuntimeError:
        return ""
    if not path:
        return ""

    with _lock:
        if path in _result:
            return _result[path]
        if path in _inflight or _attempts.get(path, 0) >= _MAX_ATTEMPTS:
            return ""
        _inflight.add(path)
        _attempts[path] = _attempts.get(path, 0) + 1

    threading.Thread(target=_worker, args=(path,), daemon=True).start()
    return ""
