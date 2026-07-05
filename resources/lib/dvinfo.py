"""
dvinfo.py – Dolby Vision Content-Mapping version detection for TinyPPI.

Determines whether the playing Dolby Vision stream carries CM v2.9 or
CM v4.0 metadata by inspecting it with hdrprobe and reading the
``dolby_vision`` block of its JSON report.  The same report supplies the
separate Level 6 and Level 5 metadata properties.

The video bit depth is reported too: FEL Dolby Vision streams reconstruct a
12-bit signal from a 10-bit base layer, so 12-bit is reported for them; every
other format uses hdrprobe's container bit depth.

Kodi plays from VFS URLs (nfs://, smb://, http:// ...) which standalone
hdrprobe cannot open.  We bridge that with xbmcvfs: the first chunk of the
stream is pulled through Kodi's VFS into special://temp/ and hdrprobe runs on
that local chunk.  No OS-level mount required, so it works for every TinyPPI
user.

Detection runs once per file in a background thread and is cached, so the
polling loop in overlay.py never blocks.  The results are published through
the Dolby Vision properties in properties.py.  CoreELEC only.

The hdrprobe binary is provided by the tools.tinyppi addon at:
    tools/hdrprobe/hdrprobe
The bundled binary is an aarch64 build; DV-capable Amlogic SoCs
(S905X2/X4/X5, S922X) are all 64-bit, so it covers every realistic target.
"""

import json
import os
import subprocess
import threading
import uuid

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs

from utils import _info

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ADDON      = xbmcaddon.Addon()

_TEMP_DIR   = xbmcvfs.translatePath("special://temp/")
_CHUNK_PATH = os.path.join(_TEMP_DIR, "tinyppi_dv.chunk")

# 32 MiB comfortably holds the first GOP (keyframe + RPU) even at UHD Blu-ray
# bitrates, so hdrprobe finds Dolby Vision RPUs to sample.  hdrprobe tolerates
# the truncated chunk, parsing the regions that are present.
_CHUNK_BYTES  = 32 * 1024 * 1024

_LABEL_FETCH = 32096
_LABEL_NA    = 32033

# Kodi Window properties survive separate addon-script invocations.  Keep the
# completed result there so reopening TinyPPI during the same playback does not
# run hdrprobe again.
_CACHE_SESSION_PROPERTY = "TinyPPI.DVInfo.Session"
_CACHE_RESULT_SESSION_PROPERTY = "TinyPPI.DVInfo.ResultSession"
_CACHE_PATH_PROPERTY = "TinyPPI.DVInfo.Path"
_CACHE_READY_PROPERTY = "TinyPPI.DVInfo.Ready"
_CACHE_FIELD_PROPERTIES = {
    "cm_version": "TinyPPI.DVInfo.CmVersion",
    "l5_offsets": "TinyPPI.DVInfo.L5Offsets",
    "l6_mdl": "TinyPPI.DVInfo.L6Mdl",
    "l6_max_cll_fall": "TinyPPI.DVInfo.L6MaxCllFall",
    "bit_depth": "TinyPPI.DVInfo.BitDepth",
}

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

_inflight:  set[str]       = set()  # paths currently being processed
_lock                      = threading.Lock()

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


def _cache_window() -> xbmcgui.Window:
    """Return Kodi's global home window used for cross-invocation caching."""
    return xbmcgui.Window(10000)


def _session_token(window: xbmcgui.Window | None = None) -> str:
    """Return the current playback-session token."""
    window = window or _cache_window()
    return window.getProperty(_CACHE_SESSION_PROPERTY) or "0"


def _empty_info() -> dict[str, str]:
    """Return a complete empty DV metadata result."""
    return {key: "" for key in _CACHE_FIELD_PROPERTIES}


def _read_cached_info(path: str, session_token: str) -> dict[str, str] | None:
    """Return the completed playback cache for ``path``, if available."""
    window = _cache_window()
    if window.getProperty(_CACHE_READY_PROPERTY) != "true":
        return None
    if window.getProperty(_CACHE_RESULT_SESSION_PROPERTY) != session_token:
        return None
    if window.getProperty(_CACHE_PATH_PROPERTY) != path:
        return None

    return {
        key: window.getProperty(property_name)
        for key, property_name in _CACHE_FIELD_PROPERTIES.items()
    }


def _write_cached_info(
    path: str,
    info: dict[str, str],
    session_token: str,
) -> bool:
    """Publish a completed result if playback is still in the same session."""
    window = _cache_window()
    if _session_token(window) != session_token:
        return False

    try:
        if xbmc.Player().getPlayingFile() != path:
            return False
    except RuntimeError:
        return False

    # Ready is written last so readers never observe a partially updated
    # result.  Empty fields are intentional and cache a completed N/A result.
    window.clearProperty(_CACHE_READY_PROPERTY)
    window.setProperty(_CACHE_RESULT_SESSION_PROPERTY, session_token)
    window.setProperty(_CACHE_PATH_PROPERTY, path)
    for key, property_name in _CACHE_FIELD_PROPERTIES.items():
        window.setProperty(property_name, info.get(key, ""))
    window.setProperty(_CACHE_READY_PROPERTY, "true")
    return True


def reset_playback_cache() -> None:
    """Clear cached DV metadata and begin a new playback-cache session."""
    window = _cache_window()
    window.clearProperty(_CACHE_READY_PROPERTY)
    window.clearProperty(_CACHE_RESULT_SESSION_PROPERTY)
    window.clearProperty(_CACHE_PATH_PROPERTY)
    for property_name in _CACHE_FIELD_PROPERTIES.values():
        window.clearProperty(property_name)
    window.setProperty(_CACHE_SESSION_PROPERTY, uuid.uuid4().hex)

    with _lock:
        _inflight.clear()


def _ensure_executable(path: str) -> None:
    """Restore the exec bit on a bundled binary if it was lost.

    The executable bit is frequently lost when an addon is packaged as a zip
    and unpacked on install; restore it defensively so the binary can be
    spawned instead of failing with PermissionError ([Errno 13])."""
    if os.path.exists(path) and not os.access(path, os.X_OK):
        try:
            os.chmod(path, 0o755)
        except OSError:
            pass


def _hdrprobe() -> str:
    """Return the hdrprobe path from the tools.tinyppi addon, restoring the
    exec bit if needed."""
    try:
        base = xbmcaddon.Addon("tools.tinyppi").getAddonInfo("path")
    except Exception:
        return ""
    path = os.path.join(base, "tools", "hdrprobe", "hdrprobe")
    _ensure_executable(path)
    return path


def _local_source(path: str) -> tuple[str, bool]:
    """
    Return ``(local_path, is_temp)``.

    VFS URLs are partially copied into special://temp/ via xbmcvfs; real
    filesystem paths are used directly (hdrprobe samples a spread of seek
    points rather than reading the whole file).
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


def _compact_cm_version(value: str) -> str:
    """Return a compact CM version label from an hdrprobe ``cm_version`` string.

    hdrprobe reports the content-mapping version as ``"CM v2.9"`` or
    ``"CM v4.0"``; this collapses it to the ``"CMv2.9"`` / ``"CMv4.0"`` form the
    overlay shows.  Returns ``''`` when the value carries neither.
    """
    lower = value.lower()
    has_29 = "2.9" in lower
    has_40 = "4.0" in lower

    if has_29 and has_40:
        return "CMv2.9/4.0"
    if has_40:
        return "CMv4.0"
    if has_29:
        return "CMv2.9"
    return ""


def _fmt_num(value) -> str:
    """Format a JSON number for display, dropping a redundant ``.0`` tail.

    ``1000.0`` becomes ``"1000"`` and ``0.0001`` stays ``"0.0001"``; integers
    pass through unchanged.  Non-numeric values yield ``''``.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _parse_probe(data: dict) -> dict[str, str]:
    """Turn an hdrprobe JSON report into the separate overlay fields.

    Dolby Vision reports fill every field from the RPU.  Non-DV reports still
    populate the bit depth, and HDR10 (and other static-HDR) reports also fill
    the mastering-display and content-light fields from the static ``hdr``
    block, since those carry the same values under the same field names.  SDR
    carries neither, so those fields stay empty (shown as N/A).
    """
    info = _empty_info()

    general = data.get("general") or {}
    dovi = data.get("dolby_vision") or {}
    hdr = data.get("hdr") or {}

    # Bit depth: FEL reconstructs a 12-bit signal from the 10-bit base layer, so
    # 12-bit is reported for it; otherwise the container bit depth is used, and
    # stays empty for formats hdrprobe leaves unlabelled (such as SDR).
    if dovi.get("el_type") == "FEL":
        info["bit_depth"] = "12"
    elif isinstance(general.get("bit_depth"), int):
        info["bit_depth"] = str(general["bit_depth"])

    if dovi:
        info["cm_version"] = _compact_cm_version(dovi.get("cm_version") or "")

        areas = dovi.get("l5_active_areas") or []
        if areas:
            area = areas[0]
            info["l5_offsets"] = " | ".join(
                _fmt_num(area.get(edge, 0)) or "0"
                for edge in ("left", "right", "top", "bottom")
            )

        # DV carries the mastering display and content light in its RPU; both
        # use the same field names as the static hdr block below.
        mdl = dovi.get("mastering_display") or {}
        content_light = dovi.get("l6") or {}
    else:
        # HDR10 and other static-HDR formats carry the equivalent values as
        # static metadata; SDR has neither, leaving these empty (N/A).
        mdl = hdr.get("mastering") or {}
        content_light = hdr.get("content_light") or {}

    mdl_max = _fmt_num(mdl.get("max_luminance"))
    mdl_min = _fmt_num(mdl.get("min_luminance"))
    if mdl_max and mdl_min:
        info["l6_mdl"] = f"{mdl_max} | {mdl_min}"

    max_cll = _fmt_num(content_light.get("max_cll"))
    max_fall = _fmt_num(content_light.get("max_fall"))
    if max_cll and max_fall:
        info["l6_max_cll_fall"] = f"{max_cll} | {max_fall}"

    return info


def _run_hdrprobe(probe: str, src: str) -> dict | None:
    """Run hdrprobe on ``src`` and return the parsed JSON report, or ``None``.

    A truncated VFS chunk can make hdrprobe log parse errors, so the exit code
    is ignored; only decodable JSON on stdout is required.
    """
    try:
        out = subprocess.run(
            [probe, "--json", src],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        ).stdout
    except OSError as exc:
        _log(f"DV: hdrprobe failed to start: {exc}", xbmc.LOGWARNING)
        return None

    # Decode from the first brace onwards so any stray leading log text is
    # tolerated; a single file yields one JSON object.
    start = out.find("{")
    if start == -1:
        return None
    try:
        data, _ = json.JSONDecoder().raw_decode(out[start:])
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _detect(path: str) -> dict[str, str]:
    """Return compact Dolby Vision metadata for the given playing path."""
    probe = _hdrprobe()
    if not probe or not os.path.exists(probe):
        _log(f"DV: hdrprobe binary missing ({probe})", xbmc.LOGWARNING)
        return {}

    src, is_temp = _local_source(path)
    try:
        data = _run_hdrprobe(probe, src)
        if data is None:
            return {}

        return _parse_probe(data)
    finally:
        if is_temp and os.path.exists(_CHUNK_PATH):
            try:
                os.remove(_CHUNK_PATH)
            except OSError:
                pass


def _worker(path: str, session_token: str) -> None:
    """Background detection job; caches one completed result per playback."""
    try:
        info = _detect(path)
    except Exception as exc:
        _log(f"DV CM detection failed: {exc}", xbmc.LOGWARNING)
        info = {}

    try:
        _write_cached_info(path, info or _empty_info(), session_token)
    finally:
        with _lock:
            _inflight.discard(path)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _get_info_status_value(key: str) -> tuple[str, str]:
    """
    Non-blocking.  Return one cached DV metadata field for the current file,
    kicking off detection in the background on first call.

    Returns ``(value, status)`` where status is ``''`` for non-DV/no-file,
    ``'fetching'`` while detection is running, ``'ready'`` once a field has
    been found, and ``'failed'`` once the field cannot be determined.  The
    completed result is shared between addon invocations until playback stops.
    """
    if key == "cm_version" and "dolby" not in _info("VideoPlayer.HdrType").lower():
        return "", ""

    try:
        path = xbmc.Player().getPlayingFile()
    except RuntimeError:
        return "", ""
    if not path:
        return "", ""

    session_token = _session_token()
    cached_info = _read_cached_info(path, session_token)
    if cached_info is not None:
        value = cached_info.get(key, "")
        return value, "ready" if value else "failed"

    with _lock:
        if path in _inflight:
            return "", "fetching"
        _inflight.add(path)

    threading.Thread(
        target=_worker,
        args=(path, session_token),
        daemon=True,
    ).start()
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


def get_bit_depth() -> str:
    """Return the source video bit depth as a bare number string (e.g. ``12``).

    FEL Dolby Vision streams reconstruct a 12-bit signal, so 12-bit is
    reported for them; every other format uses hdrprobe's container bit depth.
    """
    return _get_info_value("bit_depth")
