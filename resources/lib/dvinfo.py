"""
dvinfo.py – Dolby Vision Content-Mapping version detection for TinyPPI.

Determines whether the playing Dolby Vision stream carries CM v2.9 or
CM v4.0 metadata by inspecting it with hdrprobe and reading the
``dolby_vision`` block of its JSON report.  The same report supplies the
separate Level 6 and Level 5 metadata properties.

The video bit depth is reported too: FEL Dolby Vision streams reconstruct a
higher-bit-depth signal from a 10-bit base layer, so hdrprobe's
reconstructed_bit_depth is reported for them (falling back to 12-bit when
absent); every other format uses hdrprobe's container bit depth.

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
    "hdr_format": "TinyPPI.DVInfo.HdrFormat",
    "output_mode": "TinyPPI.DVInfo.OutputMode",
    "cm_version": "TinyPPI.DVInfo.CmVersion",
    "structure": "TinyPPI.DVInfo.Structure",
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


def _report_format(data: dict, general: dict, hdr: dict) -> str:
    """Return hdrprobe's HDR ``format`` string, wherever the report places it.

    hdrprobe labels the detected format ("Dolby Vision", "HDR10", "HDR10+",
    "HLG", "SDR", possibly with a " (fallback)" suffix).  The field is looked
    up across the report root and the ``general``/``hdr`` blocks so a schema
    tweak in where it lives does not break detection.
    """
    for block in (data, general, hdr):
        fmt = block.get("format")
        if isinstance(fmt, str) and fmt.strip():
            return fmt
    return ""


def _hdr_type_token(fmt: str) -> str:
    """Collapse an hdrprobe ``format`` string to a VideoPlayer.HdrType-style token.

    Mirrors Kodi's VideoPlayer.HdrType semantics the overlay branches on: ``''``
    for SDR, ``'hdr10'`` / ``'hdr10+'`` for HDR10, ``'hlg'`` for HLG and
    ``'dolbyvision'`` for Dolby Vision.
    """
    low = fmt.lower()
    if "dolby" in low:
        return "dolbyvision"
    if "hdr10+" in low:
        return "hdr10+"
    if "hdr10" in low:
        return "hdr10"
    if "hlg" in low:
        return "hlg"
    if "pq" in low:
        return "hdr10"
    return ""


def _dv_profile_label(dovi: dict) -> str:
    """Return the Dolby Vision profile as hdrprobe reports it.

    hdrprobe exposes the full ``<profile>.<compatibility>`` string directly —
    e.g. ``'4.2'``, ``'5.0'``, ``'7.6'``, ``'8.1'``, ``'8.4'``, ``'9.2'``,
    ``'10.0'``/``'10.1'``/``'10.4'``, ``'20.0'``/``'20.4'`` — so it is used
    verbatim.  Should that field be missing, the common cases are derived from
    the layer structure and the base-layer compatibility id as a fallback.
    """
    profile = dovi.get("profile")
    if profile is None:
        profile = dovi.get("dv_profile")

    if isinstance(profile, str) and profile.strip():
        return profile.strip()
    if isinstance(profile, (int, float)) and not isinstance(profile, bool):
        return f"{float(profile):.1f}"

    # Fallback: no explicit profile field — derive the common single-/dual-layer
    # cases with the same dotted notation.
    structure = dovi.get("structure") or {}
    if dovi.get("el_type") or dovi.get("el_present") or structure.get("el_present"):
        return "7.6"
    compat = dovi.get("bl_compatibility_id")
    if compat == 0:
        return "5.0"
    return {1: "8.1", 2: "8.2", 4: "8.4"}.get(compat, "8.1")


def _clean_format_name(raw_format: str) -> str:
    """Return just the primary format name from an hdrprobe ``format`` string.

    hdrprobe qualifies a format with its fallback base, e.g. ``"HDR10+ / HDR10"``
    or ``"HDR10 (fallback)"``; only the leading name (``"HDR10+"`` / ``"HDR10"``)
    is shown.
    """
    return raw_format.split("(")[0].split("/")[0].strip()


def _hdr10plus_profile_label(hdr10plus: dict) -> str:
    """Return the HDR10+ profile as shown, e.g. ``'Profile A'`` or ``'Profile B'``.

    Returns ``''`` when hdrprobe reports no HDR10+ profile.
    """
    profile = str(hdr10plus.get("profile") or "").strip()
    if not profile:
        return ""
    if profile.lower().startswith("profile"):
        return profile
    return f"Profile {profile.upper()}"


def _static_hdr_token(
    general: dict, hdr: dict, hdr10plus: dict, raw_format: str
) -> str:
    """Classify a non-Dolby-Vision stream into an HDR token.

    The ``format`` label is unreliable for HDR10: its static metadata rides in a
    periodic SEI that is not in every sampled chunk, so hdrprobe may fall back to
    ``PQ`` or even ``SDR``.  The transfer characteristic (PQ / HLG, carried in
    the always-present VUI) and the mastering-display block are authoritative, so
    they are checked first; the format label is only a last resort.
    """
    if hdr10plus:
        return "hdr10+"

    transfer = (hdr.get("transfer") or general.get("transfer") or "").lower()
    if "hlg" in transfer or "b67" in transfer:
        return "hlg"
    if "pq" in transfer or "2084" in transfer or hdr.get("mastering"):
        return "hdr10"

    return _hdr_type_token(raw_format)


def _colour_el_tag(profile: str, el_type: str) -> str:
    """Colour the FEL/MEL enhancement-layer tag — green FEL, orange MEL.

    hdrprobe carries the tag in the profile string, sometimes parenthesised
    (e.g. ``"7.6 (FEL)"``).  The tag is pulled out (parentheses dropped), shown
    once in colour and never duplicated; the profile number stays plain.  When
    the string carries no tag, ``el_type`` supplies it.
    """
    _COLOURS = {"FEL": "lightgreen", "MEL": "orange"}

    tag = ""
    base = []
    for token in profile.split():
        stripped = token.strip("()[]").upper()
        if not tag and stripped in _COLOURS:
            tag = stripped
        else:
            base.append(token)

    if not tag and el_type in _COLOURS:
        tag = el_type

    base_str = " ".join(base)
    if tag:
        return f"{base_str} [COLOR {_COLOURS[tag]}]{tag}[/COLOR]".strip()
    return base_str


def _structure_abbr(dovi: dict) -> str:
    """Return hdrprobe's layer structure as a compact ``(<track>-<layer>)`` tag.

    hdrprobe describes dual-layer streams as ``"Single track, dual layer"`` or
    ``"Dual track, dual layer"``; single-layer profiles (5 / 8) carry no
    ``structure`` field at all.  The two axes are abbreviated Single/Dual Track
    (``ST`` / ``DT``) and Single/Dual Layer (``SL`` / ``DL``) and joined as e.g.
    ``(ST-DL)``, ``(DT-DL)`` or ``(ST-SL)``.  Returns ``''`` for non-DV streams.
    """
    if not dovi:
        return ""

    structure = dovi.get("structure")
    if isinstance(structure, str) and structure.strip():
        low = structure.lower()
        track = "DT" if "dual track" in low else "ST"
        layer = "DL" if "dual layer" in low else "SL"
    else:
        # Single-layer profiles (5 / 8) report no structure line: they are
        # always a single track carrying a single layer.
        track = "ST"
        layer = "DL" if dovi.get("el_present") else "SL"

    return f"({track}-{layer})"


def _build_output_mode(
    dovi: dict, token: str, hdr10plus: dict, raw_format: str
) -> str:
    """Build the overlay's output-mode string from hdrprobe's report.

    Dolby Vision streams read as ``Dolby Vision Profile <p>``, with only the
    FEL/MEL enhancement-layer tag coloured (green / orange).  HDR10+ appends its
    ``Profile A`` / ``B``.  Every other stream shows the classified format name
    (``HDR10``, ``HLG``), falling back to hdrprobe's plain label with any
    fallback qualifier dropped.
    """
    if dovi:
        profile = _dv_profile_label(dovi) or "8.1"
        el_type = (dovi.get("el_type") or "").upper()
        return f"Dolby Vision Profile {_colour_el_tag(profile, el_type)}"

    if token == "hdr10+":
        return f"HDR10+ {_hdr10plus_profile_label(hdr10plus)}".strip()
    if token == "hdr10":
        return "HDR10"
    if token == "hlg":
        return "HLG"
    return _clean_format_name(raw_format)


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
    hdr10plus = data.get("hdr10plus") or {}

    # HDR type and output-mode line, straight from hdrprobe's own detection.  A
    # Dolby Vision RPU block is authoritative; otherwise the type is classified
    # from the transfer characteristic and mastering block (see _static_hdr_token)
    # rather than the fallback-prone format label.
    raw_format = _report_format(data, general, hdr)
    if dovi:
        hdr_format = "dolbyvision"
    else:
        hdr_format = _static_hdr_token(general, hdr, hdr10plus, raw_format)
    info["hdr_format"] = hdr_format
    info["output_mode"] = _build_output_mode(dovi, hdr_format, hdr10plus, raw_format)

    # Bit depth: FEL reconstructs a higher-bit-depth signal from the 10-bit base
    # layer, so hdrprobe's reconstructed_bit_depth is reported for it (falling
    # back to 12-bit when absent); otherwise the container bit depth is used, and
    # stays empty for formats hdrprobe leaves unlabelled (such as SDR).
    if dovi.get("el_type") == "FEL":
        reconstructed = dovi.get("reconstructed_bit_depth")
        info["bit_depth"] = str(reconstructed) if isinstance(reconstructed, int) else "12"
    elif isinstance(general.get("bit_depth"), int):
        info["bit_depth"] = str(general["bit_depth"])

    if dovi:
        info["cm_version"] = _compact_cm_version(dovi.get("cm_version") or "")
        info["structure"] = _structure_abbr(dovi)

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

    # DV, HDR10+ and HDR10 always carry these fields conceptually, so a missing
    # value falls back to ``0 | 0`` rather than N/A; HLG and SDR stay empty.
    hdr_fallback = hdr_format in ("dolbyvision", "hdr10+", "hdr10")

    mdl_max = _fmt_num(mdl.get("max_luminance"))
    mdl_min = _fmt_num(mdl.get("min_luminance"))
    if mdl_max and mdl_min:
        info["l6_mdl"] = f"{mdl_max} | {mdl_min}"
    elif hdr_fallback:
        info["l6_mdl"] = "0 | 0"

    max_cll = _fmt_num(content_light.get("max_cll"))
    max_fall = _fmt_num(content_light.get("max_fall"))
    if max_cll and max_fall:
        info["l6_max_cll_fall"] = f"{max_cll} | {max_fall}"
    elif hdr_fallback:
        info["l6_max_cll_fall"] = "0 | 0"

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


def get_hdr_format() -> str:
    """Return the hdrprobe-detected HDR type token, or '' when not (yet) known.

    Values mirror Kodi's VideoPlayer.HdrType: ``''`` for SDR, ``'hdr10'`` /
    ``'hdr10+'``, ``'hlg'`` and ``'dolbyvision'``.  Like the CM version this
    surfaces no status label; the token is empty until detection completes.
    """
    value, _status = _get_info_status_value("hdr_format")
    return value


def get_output_mode() -> str:
    """Return the hdrprobe output-mode line (format + Dolby Vision profile).

    Shows a localized ``Fetching...`` label while detection runs and ``N/A`` if
    it cannot be determined, matching the other hdrprobe-backed rows.  The FEL
    (green) / MEL (orange) enhancement-layer colour markup is embedded in the
    value for Dolby Vision streams.
    """
    return _get_info_value("output_mode")


def get_cm_version() -> str:
    """Return the source Dolby Vision Content-Mapping version, or '' when it is
    not (yet) known.

    Unlike the other fields, this never surfaces the "Fetching..." or "N/A"
    status labels: the value is shown only once detected, and stays empty
    otherwise.
    """
    value, _status = _get_info_status_value("cm_version")
    return value


def get_structure() -> str:
    """Return the compact Dolby Vision layer-structure tag, or '' when unknown.

    One of ``(ST-DL)`` / ``(DT-DL)`` / ``(ST-SL)`` (Single/Dual Track,
    Single/Dual Layer).  Like the CM version this surfaces no "Fetching..." /
    "N/A" status label: it is shown only once detected and stays empty otherwise.
    """
    value, _status = _get_info_status_value("structure")
    return value


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

    FEL Dolby Vision streams reconstruct a higher-bit-depth signal, so
    hdrprobe's reconstructed_bit_depth is reported for them (falling back to
    12-bit when absent); every other format uses hdrprobe's container bit depth.
    """
    return _get_info_value("bit_depth")
