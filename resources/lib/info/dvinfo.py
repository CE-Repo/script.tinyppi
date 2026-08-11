"""Dolby Vision / HDR metadata detection via hdrprobe.

Inspects the playing stream with hdrprobe and parses its JSON report into the
Dolby Vision, Level 5/6 and bit-depth properties consumed by properties.py.

Kodi plays from VFS URLs (nfs://, smb://, http://) that standalone hdrprobe
cannot open, so the stream is piped into ``hdrprobe --json -`` over stdin:
blocks are read through xbmcvfs and written to the probe until it has taken
its head budget (the write then fails with a broken pipe, the documented
success signal) or the stream ends.  Real filesystem paths are handed to
hdrprobe directly instead, where it reads to EOF for the fullest analysis.
Detection runs once per file in a cached background thread so the polling loop
never blocks.  CoreELEC only; the hdrprobe binary is the aarch64 build in
tools.tinyppi (tools/hdrprobe/hdrprobe).

Blu-ray discs are a special case: Kodi hands us the raw ``*.iso``, a
``bluray://`` title stream, or a ``.mpls`` playlist, and probing the ISO
header alone reports the wrong output mode.  ``_resolve_disc_stream`` maps the
reference to the ``.m2ts`` clip actually playing: a playlist is parsed to its
clip, a bare image falls back to the main feature, and an already-resolved
title stream is read as-is.
"""

import json
import os
import subprocess
import threading
import urllib.parse
import uuid

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs

_ADDON      = xbmcaddon.Addon()

# Read granularity for the VFS stream on the stdin path.  Both hdrprobe and
# audioprobe read a bounded head of their stdin and close it (a broken pipe)
# once they have what they need — audioprobe verified to take ~16 MiB of a UHD
# stream and mark the rest ``input_truncated`` — so the read is bounded by the
# probes' own head budgets, exactly like hdrprobe alone.  No fixed byte cap is
# imposed here (that would truncate whichever probe needs the most), and nothing
# larger than one block is ever held in memory.  Local files are read by each
# probe itself and never come through here.
_BLOCK_BYTES = 1024 * 1024

# Upper bound on how long to wait for hdrprobe to finish.  Detection runs in a
# daemon background thread, so a probe that never exits (a broken build, a stuck
# signal) would otherwise hang that thread forever and leave the overlay on
# "Fetching...".  hdrprobe 0.6.0 keeps a sub-2s guarantee without --full, so
# this only ever trips on a genuine hang; on timeout the probe is killed and the
# result falls back to N/A, exactly like any other failed detection.
_PROBE_TIMEOUT = 30

_LABEL_FETCH = 32096
_LABEL_NA    = 32033

# Shown for L5 when the RPU has nothing to report.
L5_EMPTY = "0 | 0 | 0 | 0"

# Kodi Window properties survive separate script invocations, so the completed
# result is kept there to avoid re-running hdrprobe during the same playback.
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
    "hdr10_mdl": "TinyPPI.DVInfo.Hdr10Mdl",
    "hdr10_max_cll_fall": "TinyPPI.DVInfo.Hdr10MaxCllFall",
    "dv_version": "TinyPPI.DVInfo.DvVersion",
    "dv_profile": "TinyPPI.DVInfo.DvProfile",
    "dv_rpu_present": "TinyPPI.DVInfo.DvRpuPresent",
    "dv_bl_present": "TinyPPI.DVInfo.DvBlPresent",
    "dv_el_present": "TinyPPI.DVInfo.DvElPresent",
    "dv_el_type": "TinyPPI.DVInfo.DvElType",
    "bit_depth": "TinyPPI.DVInfo.BitDepth",
    "audio_tracks": "TinyPPI.DVInfo.AudioTracks",
}

_inflight:  set[str]       = set()  # paths currently being processed
_lock                      = threading.Lock()


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


def is_fetch_label(value: str) -> bool:
    """Return True when a value is the localized ``Fetching...`` status label."""
    return value == _fetch_label()


def _cache_window() -> xbmcgui.Window:
    """Return Kodi's global home window used for cross-invocation caching."""
    return xbmcgui.Window(10000)


def _session_token(window: xbmcgui.Window | None = None) -> str:
    """Return the current playback-session token."""
    window = window or _cache_window()
    return window.getProperty(_CACHE_SESSION_PROPERTY) or "0"


def _empty_info() -> dict[str, str]:
    """Return a complete empty DV metadata result."""
    return dict.fromkeys(_CACHE_FIELD_PROPERTIES, "")


def _cache_is_current(window, path: str, session_token: str) -> bool:
    """Return whether the window cache holds a completed result for ``path``."""
    return (
        window.getProperty(_CACHE_READY_PROPERTY) == "true"
        and window.getProperty(_CACHE_RESULT_SESSION_PROPERTY) == session_token
        and window.getProperty(_CACHE_PATH_PROPERTY) == path
    )


def _read_cached_field(path: str, session_token: str, key: str) -> str | None:
    """Return one cached field for ``path``, or None when the cache is not current.

    None means "no completed result to read"; ``''`` means the result is there
    and this field is empty, which is a different answer and drives a different
    label.

    Reading the one field rather than the whole result matters because callers
    ask for a single one at a time: rebuilding the seventeen-field dict on each
    of them turned a poll of the overlay into several hundred window-property
    reads, and the L5 row alone is refreshed several times a second.
    """
    window = _cache_window()
    if not _cache_is_current(window, path, session_token):
        return None

    return window.getProperty(_CACHE_FIELD_PROPERTIES[key])


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

    # Ready is written last so readers never see a partial result; empty fields
    # intentionally cache a completed N/A result.
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
    """Restore the exec bit on the bundled binary, often lost when an addon is
    zipped and unpacked, so it can be spawned instead of raising PermissionError."""
    if os.path.exists(path) and not os.access(path, os.X_OK):
        try:
            os.chmod(path, 0o755)
        except OSError:
            pass


def _hdrprobe() -> str:
    """Return the hdrprobe path from tools.tinyppi, restoring the exec bit."""
    try:
        base = xbmcaddon.Addon("tools.tinyppi").getAddonInfo("path")
    except Exception:
        return ""
    path = os.path.join(base, "tools", "hdrprobe", "hdrprobe")
    _ensure_executable(path)
    return path


def _audioprobe() -> str:
    """Return the audioprobe path from tools.tinyppi, restoring the exec bit."""
    try:
        base = xbmcaddon.Addon("tools.tinyppi").getAddonInfo("path")
    except Exception:
        return ""
    path = os.path.join(base, "tools", "audioprobe", "audioprobe")
    _ensure_executable(path)
    return path


def _vfs_join(base: str, tail: str) -> str:
    """Join a VFS base directory and a relative tail with a single separator."""
    return f"{base.rstrip('/')}/{tail}"


def _mpls_clip_names(data: bytes) -> list[str]:
    """Return the ordered clip stems (e.g. ``['00801']``) a Blu-ray ``.mpls``
    playlist plays, or ``[]`` when unparseable.  Only the PlayList section is
    walked: each PlayItem's 5-char ``clip_information_file_name`` plus 4-char
    ``clip_codec_identifier`` (``M2TS``) is all that's needed to map a title
    back to its stream file(s)."""
    if len(data) < 12 or data[:4] != b"MPLS":
        return []

    playlist_start = int.from_bytes(data[8:12], "big")
    # PlayList section: length(4) reserved(2) number_of_PlayItems(2) …
    if playlist_start + 8 > len(data):
        return []
    count = int.from_bytes(data[playlist_start + 6:playlist_start + 8], "big")

    names: list[str] = []
    pos = playlist_start + 10  # skip length(4) reserved(2) n_items(2) n_subpaths(2)
    for _ in range(count):
        if pos + 2 > len(data):
            break
        length = int.from_bytes(data[pos:pos + 2], "big")
        item = data[pos + 2:pos + 2 + length]
        if len(item) >= 9 and item[5:9] == b"M2TS":
            name = item[:5].decode("ascii", "ignore")
            if name.isdigit():
                names.append(name)
        pos += 2 + length
    return names


def _clip_from_playlist(mpls_path: str) -> str:
    """Return the VFS path of the first ``.m2ts`` clip the given ``.mpls``
    playlist plays, so the title the viewer actually selected is probed.
    Returns ``''`` when the playlist can't be read/parsed (e.g. the VFS handed
    back the already-assembled title stream), letting the caller fall back to
    the playing URL directly."""
    idx = mpls_path.lower().rfind("/playlist/")
    if idx == -1:
        return ""

    try:
        f = xbmcvfs.File(mpls_path)
        try:
            # The header plus every PlayItem sits well within the first chunk.
            data = f.readBytes(256 * 1024)
        finally:
            f.close()
    except Exception as exc:
        _log(f"DV: cannot read playlist {mpls_path}: {exc}", xbmc.LOGWARNING)
        return ""

    clips = _mpls_clip_names(data)
    if not clips:
        return ""

    # …/PLAYLIST/<n>.mpls -> …/STREAM/<clip>.m2ts, in the same VFS namespace so
    # bluray:// / udf:// / plain paths all resolve without re-encoding.
    stream_dir = mpls_path[:idx] + "/STREAM/"
    return f"{stream_dir}{clips[0]}.m2ts"


def _disc_image_stream_dir(path: str) -> str:
    """Return the ``BDMV/STREAM/`` VFS directory URL for a raw Blu-ray image or
    extracted disc folder, or ``''`` otherwise.  Only used for a bare image
    with no title information; a ``bluray://``/``.mpls``/``.m2ts`` path already
    identifies the playing stream and isn't routed here."""
    low = path.lower()

    # A raw disc image: wrap it in Kodi's UDF VFS so its files can be listed.
    if low.endswith(".iso"):
        return f"udf://{urllib.parse.quote(path, safe='')}/BDMV/STREAM/"

    # An already-extracted Blu-ray folder (the …/BDMV directory itself).
    trimmed = path.rstrip("/")
    if trimmed.lower().endswith("/bdmv"):
        return _vfs_join(trimmed, "STREAM/")

    return ""


def _largest_stream_file(stream_dir: str) -> str:
    """Return the VFS path of the largest ``.m2ts`` in a ``BDMV/STREAM``
    directory, or ``''`` when it can't be listed or holds no stream files.  Used
    only as the last-resort fallback for a bare disc image ("play main movie"
    mode), where the largest clip is the main feature."""
    try:
        _dirs, files = xbmcvfs.listdir(stream_dir)
    except Exception as exc:
        _log(f"DV: cannot list {stream_dir}: {exc}", xbmc.LOGWARNING)
        return ""

    best_path, best_size = "", -1
    for name in files:
        if not name.lower().endswith(".m2ts"):
            continue
        candidate = stream_dir + name
        try:
            size = xbmcvfs.Stat(candidate).st_size()
        except Exception:
            continue
        if size > best_size:
            best_path, best_size = candidate, size
    return best_path


def _resolve_disc_stream(path: str) -> str:
    """Resolve a Blu-ray reference to the ``.m2ts`` clip actually playing, so
    the probe reads the selected title rather than the disc-image filesystem
    header.  A ``.mpls`` playlist is parsed to its first clip; a bare ``.iso``/
    extracted ``BDMV`` folder carries no title info, so the largest clip is
    used; everything else already refers to the playing stream and is
    returned unchanged.
    """
    low = path.lower()

    if low.endswith(".mpls"):
        clip = _clip_from_playlist(path)
        if clip:
            _log(f"DV: probing playlist clip {clip}")
            return clip
        _log(f"DV: playlist {path} unresolved; probing it directly",
             xbmc.LOGWARNING)
        return path

    if low.endswith(".iso") or low.rstrip("/").endswith("/bdmv"):
        stream_dir = _disc_image_stream_dir(path)
        main = _largest_stream_file(stream_dir) if stream_dir else ""
        if main:
            _log(f"DV: probing disc main feature {main}")
            return main
        _log(f"DV: no clip resolved for {path}; probing it directly",
             xbmc.LOGWARNING)

    return path


def _decode_audio_tracks(out: str) -> list[dict]:
    """Parse audioprobe's JSON report from ``out`` and return the audio-track
    list of the first (only) file, trimmed to the fields the overlay needs.
    Decoding starts at the first brace so stray leading log text is tolerated
    (mirrors ``_decode_report``).  Returns ``[]`` when there's no decodable
    report, the file couldn't be read, or it carries no audio track.
    """
    start = out.find("{")
    if start == -1:
        return []
    try:
        data, _ = json.JSONDecoder().raw_decode(out[start:])
    except ValueError:
        return []
    if not isinstance(data, dict):
        return []

    files = data.get("files")
    if not isinstance(files, list) or not files or not isinstance(files[0], dict):
        return []

    raw_tracks = files[0].get("audio_tracks")
    if not isinstance(raw_tracks, list):
        return []

    # Keep only what track selection and the depth / rate getters read; codec,
    # channels and language are retained to match the track against Kodi's
    # active audio stream (see ``_active_audio_track``).
    tracks: list[dict] = []
    for track in raw_tracks:
        if isinstance(track, dict):
            tracks.append({
                "codec": track.get("codec"),
                "sample_rate": track.get("sample_rate"),
                "bit_depth": track.get("bit_depth"),
                "channels": track.get("channels"),
                "language": track.get("language"),
            })
    return tracks


def _run_audioprobe(probe: str, src: str) -> list[dict]:
    """Run audioprobe on a real filesystem ``src`` and return its audio-track
    list, or ``[]``.  Local paths only; Kodi VFS URLs are streamed over stdin
    instead (see ``_probe_stream_stdin``)."""
    try:
        out = subprocess.run(
            [probe, "--json", src],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            # Decode as UTF-8 (not the C/POSIX process locale): audioprobe echoes
            # the source path back, so an accented filename would otherwise raise
            # UnicodeDecodeError; errors="replace" tolerates stray bytes too.
            encoding="utf-8",
            errors="replace",
            timeout=_PROBE_TIMEOUT,
        ).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        _log(f"Audio: audioprobe did not complete: {exc}", xbmc.LOGWARNING)
        return []
    return _decode_audio_tracks(out)


def _compact_cm_version(value: str) -> str:
    """Collapse hdrprobe's ``"CM v2.9"`` / ``"CM v4.0"`` into ``"CMv2.9"`` /
    ``"CMv4.0"`` (or both), or ``''`` when it carries neither."""
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


def _present_flag(value) -> str:
    """Return ``true`` / ``false`` for a presence flag (rendered as an icon via
    ``String.IsEqual``), or ``''`` when ``None`` so neither icon shows."""
    if value is None:
        return ""
    return "true" if value else "false"


def _fmt_pair(source: dict, key_a: str, key_b: str) -> str:
    """Return ``"<a> | <b>"`` for two numeric fields, or '' if either is missing
    (the luminance getters then render the ``0 | 0`` placeholder)."""
    a = _fmt_num(source.get(key_a))
    b = _fmt_num(source.get(key_b))
    return f"{a} | {b}" if a and b else ""


def _report_format(data: dict, general: dict, hdr: dict) -> str:
    """Return hdrprobe's ``format`` string, looked up across the report root and
    the ``general`` / ``hdr`` blocks so its exact location does not matter."""
    for block in (data, general, hdr):
        fmt = block.get("format")
        if isinstance(fmt, str) and fmt.strip():
            return fmt
    return ""


def _hdr_type_token(fmt: str) -> str:
    """Collapse a ``format`` string to a VideoPlayer.HdrType-style token: ``''``
    (SDR), ``'hdr10'`` / ``'hdr10+'``, ``'hlg'`` or ``'dolbyvision'``."""
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
    """Return the Dolby Vision ``<profile>.<compatibility>`` string as hdrprobe
    reports it (e.g. ``'7.6'``, ``'8.1'``), deriving the common cases from the
    layer structure and base-layer compatibility id when the field is missing."""
    profile = dovi.get("profile")
    if profile is None:
        profile = dovi.get("dv_profile")

    if isinstance(profile, str) and profile.strip():
        return profile.strip()
    if isinstance(profile, (int, float)) and not isinstance(profile, bool):
        return f"{float(profile):.1f}"

    # No explicit profile field — derive the common single-/dual-layer cases.
    structure = dovi.get("structure") or {}
    if dovi.get("el_type") or dovi.get("el_present") or structure.get("el_present"):
        return "7.6"
    compat = dovi.get("bl_compatibility_id")
    if compat == 0:
        return "5.0"
    return {1: "8.1", 2: "8.2", 4: "8.4"}.get(compat, "8.1")


def _dv_level_label(dovi: dict) -> str:
    """Return the Dolby Vision ``level`` as a bare display string.

    A ``.m2ts`` signals Dolby Vision through the playlist, not the PMT, so it
    carries no container DV level; hdrprobe 0.6.0 derives one from the coded
    resolution and frame rate against the Dolby level table.  Derived and
    container-read levels alike print as the plain number.
    """
    return _fmt_num(dovi.get("level"))


def _clean_format_name(raw_format: str) -> str:
    """Return just the primary format name from a ``format`` string, dropping a
    fallback qualifier (``"HDR10+ / HDR10"`` / ``"HDR10 (fallback)"`` -> leading name)."""
    return raw_format.split("(")[0].split("/")[0].strip()


def _hdr10plus_profile_label(hdr10plus: dict) -> str:
    """Return the HDR10+ profile, e.g. ``'Profile A'``, or ``''`` when absent."""
    profile = str(hdr10plus.get("profile") or "").strip()
    if not profile:
        return ""
    if profile.lower().startswith("profile"):
        return profile
    return f"Profile {profile.upper()}"


def _sl_hdr_label(sl_hdr: dict) -> str:
    """Return the SL-HDR variant name (``SL-HDR1`` / ``SL-HDR2`` / ``SL-HDR3``),
    from the block's ``mode`` (1 = SDR-, 2 = PQ-, 3 = HLG-graded base spec), or
    ``''`` when the block carries no valid mode.

    SL-HDR (ETSI TS 103 433) is dynamic reconstruction metadata riding on an
    HDR10 / HLG base; the digit matches the reported ``mode`` (hdrprobe's
    ``format`` label uses the same, e.g. ``"SL-HDR2 / HDR10"``)."""
    mode = sl_hdr.get("mode")
    if isinstance(mode, int) and not isinstance(mode, bool) and 1 <= mode <= 3:
        return f"SL-HDR{mode}"
    return ""


def _static_mastering(hdr: dict) -> dict:
    """Return the base layer's mastering-display block from the ``hdr`` block.

    Schema 3.0 renamed ``hdr.mastering`` to ``hdr.mastering_display`` (one name
    for the shape shared with the Dolby Vision and SL-HDR blocks).  Both names
    are read, newest first, so a report from either schema resolves — the
    bundled on-device hdrprobe may still be a 2.x build.
    """
    mastering = hdr.get("mastering_display") or hdr.get("mastering")
    return mastering if isinstance(mastering, dict) else {}


def _static_hdr_token(
    general: dict, hdr: dict, hdr10plus: dict, raw_format: str
) -> str:
    """Classify a non-Dolby-Vision stream into an HDR token.

    The ``format`` label is unreliable for HDR10 (its SEI isn't in every
    chunk), so the transfer characteristic and mastering-display block are
    checked first, with the format label only as a last resort.  Schema 2.x
    nests the transfer characteristic under ``color.transfer``; 1.x kept it on
    the track/``hdr`` block -- all three spots are consulted here.
    """
    if hdr10plus:
        return "hdr10+"

    color = general.get("color") or {}
    transfer = (
        hdr.get("transfer")
        or color.get("transfer")
        or general.get("transfer")
        or ""
    ).lower()
    if "hlg" in transfer or "b67" in transfer:
        return "hlg"
    if "pq" in transfer or "2084" in transfer or _static_mastering(hdr):
        return "hdr10"

    return _hdr_type_token(raw_format)


# Enhancement-layer tags whose colour is user-themeable (FEL forest, MEL
# tangerine by default).  The ARGB hex is published by theme.apply_theme; the
# tag is coloured only when read (see _colourise_el_tag) so a colour change
# takes effect live without re-running detection.
_EL_COLOURS = ("FEL", "MEL")
_EL_COLOUR_PROPERTIES = {
    "FEL": "TinyPPI.FelColor",
    "MEL": "TinyPPI.MelColor",
}
_EL_COLOUR_DEFAULTS = {
    "FEL": "FF81C784",  # palette Forest
    "MEL": "FFFFB74D",  # palette Tangerine
}


def _format_el_tag(profile: str, el_type: str) -> str:
    """Return the profile string with a single (uncoloured) FEL/MEL tag appended.

    The tag is pulled out of the profile string (``"7.6 (FEL)"``), or supplied
    by ``el_type`` when absent; ``_colourise_el_tag`` colours it at read time.
    """
    tag = ""
    base = []
    for token in profile.split():
        stripped = token.strip("()[]").upper()
        if not tag and stripped in _EL_COLOURS:
            tag = stripped
        else:
            base.append(token)

    if not tag and el_type in _EL_COLOURS:
        tag = el_type

    base_str = " ".join(base)
    return f"{base_str} {tag}".strip() if tag else base_str


def _colourise_el_tag(text: str) -> str:
    """Wrap a trailing FEL/MEL tag in its themed colour (falling back to the
    palette default); any other value is returned unchanged."""
    for tag in _EL_COLOURS:
        if text == tag or text.endswith(" " + tag):
            colour = xbmcgui.Window(10000).getProperty(
                _EL_COLOUR_PROPERTIES[tag]
            ).strip() or _EL_COLOUR_DEFAULTS[tag]
            head = text[: len(text) - len(tag)]
            return f"{head}[COLOR {colour}]{tag}[/COLOR]"
    return text


def _structure_abbr(dovi: dict) -> str:
    """Return the layer structure as a compact ``(<track>-<layer>)`` tag, e.g.
    ``(ST-DL)`` / ``(DT-DL)`` / ``(ST-SL)`` (Single/Dual Track, Single/Dual
    Layer).  Single-layer profiles carry no ``structure`` field; ``''`` for non-DV."""
    if not dovi:
        return ""

    structure = dovi.get("structure")
    if isinstance(structure, str) and structure.strip():
        low = structure.lower()
        track = "DT" if "dual track" in low else "ST"
        layer = "DL" if "dual layer" in low else "SL"
    else:
        # Single-layer profiles (5 / 8) report no structure line.
        track = "ST"
        layer = "DL" if dovi.get("el_present") else "SL"

    return f"({track}-{layer})"


def _build_output_mode(
    dovi: dict,
    token: str,
    hdr10plus: dict,
    raw_format: str,
    sl_hdr: dict | None = None,
    hdr_vivid: dict | None = None,
) -> str:
    """Build the overlay's output-mode string from hdrprobe's report.

    Dolby Vision reads as ``Dolby Vision Profile <p>``; HDR Vivid (CUVA) and
    SL-HDR (dynamic-metadata formats riding on an HDR10/HLG base) read as their
    own name; HDR10+ appends ``Profile A``/``B``; other streams show the
    classified format name.  A stream signalling Dolby Vision alongside an
    SL-HDR fallback still reads as DV, which is authoritative.
    """
    if dovi:
        profile = _dv_profile_label(dovi) or "8.1"
        el_type = (dovi.get("el_type") or "").upper()
        return f"Dolby Vision Profile {_format_el_tag(profile, el_type)}"

    if hdr_vivid:
        return "HDR Vivid"

    sl_label = _sl_hdr_label(sl_hdr or {})
    if sl_label:
        return sl_label

    if token == "hdr10+":
        return f"HDR10+ {_hdr10plus_profile_label(hdr10plus)}".strip()
    if token == "hdr10":
        return "HDR10"
    if token == "hlg":
        return "HLG"
    return _clean_format_name(raw_format)


def _fmt_num(value) -> str:
    """Format a JSON number, dropping a redundant ``.0`` tail (``1000.0`` ->
    ``"1000"``).  Non-numeric values yield ``''``."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _select_report_blocks(
    data: dict,
) -> tuple[dict, dict, dict, dict, dict, dict]:
    """Return the ``(general, hdr, dolby_vision, hdr10plus, sl_hdr, hdr_vivid)``
    blocks of a report.  Schema 2.0 nests everything under ``video_tracks[0]``
    (standing in for ``general``); 1.x keeps all blocks at the root.  Both
    layouts are resolved here so the rest of the parser stays schema-agnostic.
    """
    tracks = data.get("video_tracks")
    if isinstance(tracks, list) and tracks and isinstance(tracks[0], dict):
        track = tracks[0]
        return (
            track,
            track.get("hdr") or {},
            track.get("dolby_vision") or {},
            track.get("hdr10plus") or {},
            track.get("sl_hdr") or {},
            track.get("hdr_vivid") or {},
        )

    return (
        data.get("general") or {},
        data.get("hdr") or {},
        data.get("dolby_vision") or {},
        data.get("hdr10plus") or {},
        data.get("sl_hdr") or {},
        data.get("hdr_vivid") or {},
    )


def _parse_probe(data: dict) -> dict[str, str]:
    """Turn an hdrprobe JSON report into the separate overlay fields.  Dolby
    Vision fills every field from the RPU; HDR10 and other static-HDR formats
    fill the mastering-display/content-light fields from the ``hdr`` block;
    SDR carries neither, so those fields stay empty (shown as N/A).
    """
    info = _empty_info()

    general, hdr, dovi, hdr10plus, sl_hdr, hdr_vivid = _select_report_blocks(data)

    # HDR type / output-mode line.  A DV RPU block is authoritative; otherwise
    # the type is classified from the transfer characteristic and mastering
    # block rather than the fallback-prone format label.
    raw_format = _report_format(data, general, hdr)
    if dovi:
        hdr_format = "dolbyvision"
    else:
        hdr_format = _static_hdr_token(general, hdr, hdr10plus, raw_format)
        # SL-HDR / HDR Vivid ride on an HDR10 / HLG base (SL-HDR1 is graded from
        # SDR); when the base classified as SDR yet dynamic-HDR metadata is
        # present, treat the stream as HDR10 so the overlay draws an HDR panel
        # rather than the SDR one.  The base token drives the skin's HdrType
        # branch; the format name itself is set on output_mode below.
        if not hdr_format and (sl_hdr or hdr_vivid):
            hdr_format = "hdr10"
    info["hdr_format"] = hdr_format
    info["output_mode"] = _build_output_mode(
        dovi, hdr_format, hdr10plus, raw_format, sl_hdr, hdr_vivid
    )

    # Bit depth: FEL uses hdrprobe's reconstructed_bit_depth (12-bit fallback);
    # otherwise the container bit depth, left empty for unlabelled formats (SDR).
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

        # DV carries the mastering display and content light in its RPU.
        mdl = dovi.get("mastering_display") or {}
        content_light = dovi.get("l6") or {}
    else:
        # HDR10 and other static-HDR formats carry them as static metadata.
        mdl = _static_mastering(hdr)
        content_light = hdr.get("content_light") or {}

    # The ``l6_*`` rows come from the source selected above; the ``hdr10_*``
    # rows always come from the static ``hdr`` block, so a DV stream shows its
    # HDR10 fallback layer distinctly from the RPU (L6) values.  Missing values
    # are left blank (rendered as ``0 | 0`` by the luminance getters).
    static_mdl = _static_mastering(hdr)
    static_light = hdr.get("content_light") or {}
    for key, source, key_a, key_b in (
        ("l6_mdl", mdl, "max_luminance", "min_luminance"),
        ("l6_max_cll_fall", content_light, "max_cll", "max_fall"),
        ("hdr10_mdl", static_mdl, "max_luminance", "min_luminance"),
        ("hdr10_max_cll_fall", static_light, "max_cll", "max_fall"),
    ):
        pair = _fmt_pair(source, key_a, key_b)
        if pair:
            info[key] = pair

    # Dolby Vision layer descriptors, straight from the RPU report.
    if dovi:
        info["dv_version"] = _dv_level_label(dovi)
        info["dv_profile"] = (_dv_profile_label(dovi).split() or [""])[0]
        info["dv_rpu_present"] = _present_flag(dovi.get("rpu_present"))
        info["dv_bl_present"] = _present_flag(dovi.get("bl_present"))
        info["dv_el_present"] = _present_flag(dovi.get("el_present"))
        # FEL/MEL type; profiles without an EL (e.g. 8.1) fall back to the
        # profile number.  Stored uncoloured, themed at read time.
        el_type = (dovi.get("el_type") or "").upper()
        info["dv_el_type"] = el_type or info["dv_profile"]

    return info


def _decode_report(out: str) -> dict | None:
    """Parse hdrprobe's JSON report from ``out``, or ``None`` when it holds no
    decodable report object.  Decoding starts at the first brace so stray
    leading log text (and hdrprobe's stdin parse warnings) are tolerated."""
    start = out.find("{")
    if start == -1:
        return None
    try:
        data, _ = json.JSONDecoder().raw_decode(out[start:])
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _run_hdrprobe(probe: str, src: str) -> dict | None:
    """Run hdrprobe on a real filesystem ``src`` and return the parsed report,
    or ``None``.  Used only for genuine local paths, where hdrprobe opens the
    file itself and reads to EOF for the fullest analysis; VFS URLs are streamed
    in over stdin instead (see ``_probe_stream_stdin``)."""
    try:
        out = subprocess.run(
            [probe, "--json", src],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            # Decode as UTF-8, not the C/POSIX process locale: hdrprobe echoes
            # the source path back, so an accented filename would otherwise raise
            # UnicodeDecodeError.  errors="replace" tolerates stray bytes too.
            encoding="utf-8",
            errors="replace",
            # Guard the background thread against a probe that never exits;
            # subprocess.run kills it on timeout (raises TimeoutExpired).
            timeout=_PROBE_TIMEOUT,
        ).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        _log(f"DV: hdrprobe did not complete: {exc}", xbmc.LOGWARNING)
        return None

    return _decode_report(out)


def _spawn_stdin_probe(probe: str) -> "subprocess.Popen | None":
    """Spawn ``<probe> --json -`` with a stdin pipe, or ``None`` when it cannot
    start."""
    try:
        return subprocess.Popen(
            [probe, "--json", "-"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
    except OSError as exc:
        _log(f"DV: probe failed to start ({probe}): {exc}", xbmc.LOGWARNING)
        return None


def _collect_probe_output(proc: "subprocess.Popen") -> str:
    """Close ``proc``'s stdin, drain its stdout and return it as text.

    ``communicate()`` closes stdin (signalling EOF for short streams) and reads
    the small JSON report the probe writes only after it stops reading, so there
    is no deadlock; the timeout guards the background thread against a probe that
    never exits (it is then killed and reaped)."""
    try:
        out, _ = proc.communicate(timeout=_PROBE_TIMEOUT)
    except Exception as exc:
        _log(f"DV: probe did not complete: {exc}", xbmc.LOGWARNING)
        proc.kill()
        proc.communicate()
        return ""
    return out.decode("utf-8", "replace") if out else ""


def _probe_stream_stdin(
    hdr_probe: str, audio_probe: str, vfs_url: str
) -> tuple[dict | None, list[dict]]:
    """Probe a Kodi VFS stream without copying it to disk.

    Neither hdrprobe nor audioprobe can open nfs:///smb:///bluray:///https://
    URLs itself, so the stream is read once through xbmcvfs and each block is
    written to whichever probes are available over their ``--json -`` stdin.
    Feeding a probe stops once its stdin write fails with a broken pipe (it has
    taken its head budget); the read as a whole stops once every probe has done
    so or the stream ends.  No fixed byte cap is imposed, since each probe
    self-bounds its own stdin head and a cap would truncate whichever probe
    needs the most data; nothing larger than a single block is ever held in
    memory.

    ``hdr_probe``/``audio_probe`` may be ``''`` when that binary is missing.
    Returns ``(report, audio_tracks)``, ``None``/``[]`` respectively when
    hdrprobe is absent or emitted no decodable JSON.
    """
    hdr = _spawn_stdin_probe(hdr_probe) if hdr_probe else None
    audio = _spawn_stdin_probe(audio_probe) if audio_probe else None

    open_pipes = {
        name: proc
        for name, proc in (("hdr", hdr), ("audio", audio))
        if proc is not None
    }
    if not open_pipes:
        return None, []

    try:
        f = xbmcvfs.File(vfs_url)
        try:
            while open_pipes:
                block = f.readBytes(_BLOCK_BYTES)
                if not block:
                    break  # stream ended within the probes' budgets
                for name, proc in list(open_pipes.items()):
                    try:
                        proc.stdin.write(block)
                    except (BrokenPipeError, OSError):
                        del open_pipes[name]  # this probe took what it needs
        finally:
            f.close()
    except Exception as exc:
        _log(f"DV: VFS read failed for {vfs_url}: {exc}", xbmc.LOGWARNING)

    report = _decode_report(_collect_probe_output(hdr)) if hdr is not None else None
    tracks = (
        _decode_audio_tracks(_collect_probe_output(audio))
        if audio is not None else []
    )
    return report, tracks


def _detect(path: str) -> dict[str, str]:
    """Return compact Dolby Vision + audio metadata for the given playing path.

    Real filesystem paths are probed by hdrprobe/audioprobe directly (fullest
    analysis); Kodi VFS URLs, which neither binary can open, are streamed into
    both over stdin in a single read.  The full audio-track list is cached so
    the active track can be selected -- and re-selected on a track change -- at
    read time.
    """
    source = _resolve_disc_stream(path)
    is_local = source.startswith("/")

    probe = _hdrprobe()
    have_probe = bool(probe) and os.path.exists(probe)
    if not have_probe:
        _log(f"DV: hdrprobe binary missing ({probe})", xbmc.LOGWARNING)

    audio_probe = _audioprobe()
    have_audio = bool(audio_probe) and os.path.exists(audio_probe)
    if not have_audio:
        _log(f"Audio: audioprobe binary missing ({audio_probe})", xbmc.LOGWARNING)

    if is_local:
        data = _run_hdrprobe(probe, source) if have_probe else None
        tracks = _run_audioprobe(audio_probe, source) if have_audio else []
    else:
        data, tracks = _probe_stream_stdin(
            probe if have_probe else "",
            audio_probe if have_audio else "",
            source,
        )

    info = _parse_probe(data) if data is not None else {}

    if tracks:
        if not info:
            info = _empty_info()
        info["audio_tracks"] = json.dumps(tracks, separators=(",", ":"))
    return info


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


def _start_worker(path: str, session_token: str) -> bool:
    """Spawn the background detection worker for ``path`` unless one is already
    in flight for it.  Returns True when a new worker was started."""
    with _lock:
        if path in _inflight:
            return False
        _inflight.add(path)

    threading.Thread(
        target=_worker,
        args=(path, session_token),
        daemon=True,
    ).start()
    return True


def prime_playback_detection() -> bool:
    """Kick off DV/audio detection for the currently playing file ahead of time.

    Called from the background service at playback start so hdrprobe and the
    audio-bitstream scan finish while the video plays, leaving the result
    cached before the overlay is ever opened.  Non-blocking; a no-op when
    nothing is playing or a result is already cached/in flight.  Returns True
    when a new detection worker was started.
    """
    try:
        path = xbmc.Player().getPlayingFile()
    except RuntimeError:
        return False
    if not path:
        return False

    session_token = _session_token()
    if _cache_is_current(_cache_window(), path, session_token):
        return False

    return _start_worker(path, session_token)


def _get_info_status_value(key: str) -> tuple[str, str]:
    """Non-blocking.  Return one cached DV metadata field for the current file,
    starting background detection on first call.

    Returns ``(value, status)`` where status is ``''`` (non-DV/no-file),
    ``'fetching'``, ``'ready'`` or ``'failed'``.
    """
    try:
        path = xbmc.Player().getPlayingFile()
    except RuntimeError:
        return "", ""
    if not path:
        return "", ""

    session_token = _session_token()
    value = _read_cached_field(path, session_token, key)
    if value is not None:
        return value, "ready" if value else "failed"

    _start_worker(path, session_token)
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


def _get_info_value_or(key: str, fallback: str) -> str:
    """Return a metadata field, showing ``fallback`` (e.g. ``0 | 0``) instead of
    N/A when absent; the ``Fetching...`` label is kept while detection runs."""
    value, status = _get_info_status_value(key)
    if value:
        return value
    if status == "fetching":
        return _fetch_label()
    return fallback


def get_hdr_format() -> str:
    """Return the detected HDR type token (``''`` / ``'hdr10'`` / ``'hdr10+'`` /
    ``'hlg'`` / ``'dolbyvision'``), empty until detection completes.  No status label."""
    value, _status = _get_info_status_value("hdr_format")
    return value


def get_output_mode() -> str:
    """Return the output-mode line (format + DV profile), with ``Fetching...`` /
    ``N/A`` labels and the FEL/MEL tag coloured at read time."""
    return _colourise_el_tag(_get_info_value("output_mode"))


def get_cm_version() -> str:
    """Return the DV Content-Mapping version, or '' when unknown.  No status label."""
    value, _status = _get_info_status_value("cm_version")
    return value


def get_structure() -> str:
    """Return the layer-structure tag (``(ST-DL)`` / ``(DT-DL)`` / ``(ST-SL)``),
    or '' when unknown.  No status label."""
    value, _status = _get_info_status_value("structure")
    return value


def get_l5_offsets() -> str:
    """Return Dolby Vision Level 5 active-area offsets, falling back to
    ``0 | 0 | 0 | 0`` (left | right | top | bottom) rather than N/A."""
    return _get_info_value_or("l5_offsets", L5_EMPTY)


def get_l6_rpu_mdl() -> str:
    """Return Dolby Vision Level 6 RPU mastering-display luminance."""
    return _get_info_value_or("l6_mdl", "0 | 0")


def get_l6_rpu_max_cll_fall() -> str:
    """Return Dolby Vision Level 6 RPU MaxCLL/MaxFALL."""
    return _get_info_value_or("l6_max_cll_fall", "0 | 0")


def get_hdr10_mdl() -> str:
    """Return the HDR10 static mastering-display luminance (``max | min``)."""
    return _get_info_value_or("hdr10_mdl", "0 | 0")


def get_hdr10_max_cll_fall() -> str:
    """Return the HDR10 static MaxCLL/MaxFALL (``cll | fall``)."""
    return _get_info_value_or("hdr10_max_cll_fall", "0 | 0")


def get_dv_version() -> str:
    """Return the Dolby Vision ``level`` (e.g. ``6``), or '' when unknown.  No
    status label."""
    value, _status = _get_info_status_value("dv_version")
    return value


def get_dv_profile() -> str:
    """Return the bare Dolby Vision profile number (e.g. ``7.6``), or '' when
    not (yet) known.  Surfaces no status label."""
    value, _status = _get_info_status_value("dv_profile")
    return value


def get_dv_rpu_present() -> str:
    """Return ``true`` / ``false`` for RPU presence, or '' when unknown."""
    value, _status = _get_info_status_value("dv_rpu_present")
    return value


def get_dv_bl_present() -> str:
    """Return ``true`` / ``false`` for base-layer presence, or '' when unknown."""
    value, _status = _get_info_status_value("dv_bl_present")
    return value


def get_dv_el_present() -> str:
    """Return ``true`` / ``false`` for enhancement-layer presence, or '' when
    unknown."""
    value, _status = _get_info_status_value("dv_el_present")
    return value


def get_dv_el_type() -> str:
    """Return the enhancement-layer type (``FEL`` / ``MEL``, themed), or the
    plain profile number when there is no EL, or '' when unknown."""
    return _colourise_el_tag(get_dv_el_type_raw())


def get_dv_el_type_raw() -> str:
    """Return the enhancement-layer type (``FEL`` / ``MEL``), or the plain
    profile number when there is no EL, uncoloured; '' when unknown.

    Unlike ``get_dv_el_type``, this carries no ``[COLOR]`` wrapper, for callers
    that theme it themselves (e.g. the splash's Dolby Vision layer-indicator
    pill, one colour per FEL / MEL / other-profile bucket)."""
    value, _status = _get_info_status_value("dv_el_type")
    return value


def get_bit_depth() -> str:
    """Return the source bit depth as a bare number string (e.g. ``12``);
    FEL uses the reconstructed depth, others the container depth."""
    return _get_info_value("bit_depth")


def _cached_audio_tracks() -> list[dict]:
    """Return the cached audio-track list for the current file (starting
    background detection on first access), or ``[]`` while it runs / when none
    were found."""
    value, _status = _get_info_status_value("audio_tracks")
    if not value:
        return []
    try:
        tracks = json.loads(value)
    except ValueError:
        return []
    return tracks if isinstance(tracks, list) else []


def _norm_audio_family(name) -> str:
    """Collapse a codec name — audioprobe's (``"DTS-HD MA"``) or Kodi's
    (``"dtshd_ma"`` / ``"dca"``) — to a comparable family token, so the active
    Kodi stream can be matched against a probed track regardless of naming."""
    token = "".join(ch for ch in str(name or "").lower() if ch.isalnum())
    if not token:
        return ""
    if "truehd" in token:
        return "truehd"
    if "mlp" in token:
        return "mlp"
    if "dts" in token or token.startswith("dca"):
        return "dts"
    if "eac3" in token or "ddp" in token:
        return "eac3"
    if "ac3" in token:
        return "ac3"
    if "flac" in token:
        return "flac"
    return token


def _current_audio_stream() -> dict:
    """Return Kodi's currently active audio stream (``index`` / ``codec`` / …)
    via JSON-RPC, or ``{}`` when nothing is playing or the query fails.  Read
    live so a track change is reflected without re-probing the file."""
    try:
        active = json.loads(xbmc.executeJSONRPC(json.dumps({
            "jsonrpc": "2.0", "id": 1, "method": "Player.GetActivePlayers",
        })))
        players = active.get("result") or []
        playerid = next(
            (p.get("playerid") for p in players if p.get("type") == "video"),
            None,
        )
        if playerid is None:
            return {}
        props = json.loads(xbmc.executeJSONRPC(json.dumps({
            "jsonrpc": "2.0", "id": 1, "method": "Player.GetProperties",
            "params": {
                "playerid": playerid,
                "properties": ["currentaudiostream"],
            },
        })))
        stream = (props.get("result") or {}).get("currentaudiostream") or {}
        return stream if isinstance(stream, dict) else {}
    except (ValueError, KeyError, TypeError):
        return {}


def _active_audio_track() -> dict | None:
    """Select the probed track for the audio stream Kodi is currently playing.

    Both Kodi and audioprobe enumerate the container's audio tracks in order,
    so the active stream ``index`` maps straight into the probed list; the
    codec family is cross-checked to guard against the two orderings diverging,
    falling back to a unique family match when they do.  Re-evaluated on every
    read, so switching audio track updates the values without re-probing.
    """
    tracks = _cached_audio_tracks()
    if not tracks:
        return None
    if len(tracks) == 1:
        return tracks[0]

    stream = _current_audio_stream()
    idx = stream.get("index")
    family = _norm_audio_family(stream.get("codec"))

    candidate = None
    if isinstance(idx, int) and 0 <= idx < len(tracks):
        candidate = tracks[idx]
        if not family or _norm_audio_family(candidate.get("codec")) == family:
            return candidate

    if family:
        matches = [
            track for track in tracks
            if _norm_audio_family(track.get("codec")) == family
        ]
        if len(matches) == 1:
            return matches[0]

    return candidate


def get_active_audio_bit_depth() -> str:
    """Return the bit depth of the active audio track as read from the source
    bitstream by audioprobe (e.g. ``"24"``), or '' while detection runs, when no
    depth is coded (lossy codecs report none) or when no track could be
    selected.  No status label."""
    track = _active_audio_track()
    if not track:
        return ""
    depth = track.get("bit_depth")
    return str(depth) if isinstance(depth, int) and not isinstance(depth, bool) else ""


def get_active_audio_sample_rate() -> str:
    """Return the sample rate in Hz of the active audio track as read from the
    source bitstream by audioprobe (e.g. ``"96000"``), or '' while detection
    runs or no track could be selected.  Unlike Kodi's own value this is the
    true source rate, so DTS 96/24 and high-rate DTS-HD read correctly instead
    of as their 48 kHz compatibility core.  No status label."""
    track = _active_audio_track()
    if not track:
        return ""
    rate = track.get("sample_rate")
    return str(rate) if isinstance(rate, int) and not isinstance(rate, bool) else ""
