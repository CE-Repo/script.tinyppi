"""Dolby Vision / HDR metadata from CoreELEC's raw side-data infolabel.

``Player.Process(video.sidedata)`` is the CoreELEC 22 label through which the
Amlogic video codec publishes the raw payloads of the stream it is decoding --
the Dolby Vision RPU, the dvcC/dvvC configuration record, the HDR10+ ST 2094-40
T.35 message and the static MDCV / CLL SEIs -- base64-encoded in a JSON object.
Kodi itself parses none of it; script.module.sidedata does (libdovi and
libavutil through ctypes), and this module maps its result onto the compact
fields properties.py publishes.

Everything here is live.  The label is re-published per presentation timestamp,
so the per-frame blocks -- L1 (frame luminance, the FLL / PQ rows) and L5 (the
active area the aspect-ratio row is computed from) -- follow the picture rather
than describing a single probed moment of the file.  There is no detection
step, no background worker and nothing to cache across a playback: a parse
happens only when the raw payload actually changes, and the field dict it
yields is held for a fraction of a second so one polling pass over the ~20
getters costs a single parse.

What the side data describes is the source, not the picture after the player
has had its way with it: CoreELEC latches the payloads from the demuxer's own
hints and from the packets before its bitstream conversion runs, and records
what it then did in the ``flags`` key (``converted`` for a profile 4/7 -> 8
rewrite, ``rpu-removed`` / ``hdr10plus-removed`` for metadata stripped for a
display that cannot take it).  So the Dolby Vision profile, its enhancement
layer and the layer structure all still read as the file carries them.

Kodi's own ``VideoPlayer.HdrType`` / ``VideoPlayer.HdrDetail`` are read
alongside: the type classifies HLG, which carries no side-data payload of its
own, and the detail stands in for a Dolby Vision profile that arrives without a
configuration record.

CoreELEC 22 on Amlogic only; on anything else the label stays empty and every
field degrades to its N/A label, exactly as an absent metadata block does.
"""

import re
import threading
import time

import xbmc
import xbmcaddon
import xbmcgui

try:
    from sidedata import parse_sidedata as _parse_sidedata
    _SIDEDATA_IMPORT_ERROR = None
except Exception as exc:  # a missing/broken module must not take the addon down
    _parse_sidedata = None
    _SIDEDATA_IMPORT_ERROR = exc

_ADDON = xbmcaddon.Addon()

_LABEL_NA = 32033

# Shown for L5 / L1 when the RPU has nothing to report.
L5_EMPTY = "0 | 0 | 0 | 0"
L1_EMPTY = "0 | 0 | 0"

_SIDEDATA_LABEL   = "Player.Process(video.sidedata)"
_HDR_TYPE_LABEL   = "VideoPlayer.HdrType"
_HDR_DETAIL_LABEL = "VideoPlayer.HdrDetail"

# How long a derived field dict stays valid.  Short enough that every polling
# pass sees the current frame's metadata, long enough that the getters of one
# pass share a single infolabel read and a single parse.
_SNAPSHOT_TTL = 0.1

# Every field a caller can ask for; the getters below name them one at a time.
_FIELDS = (
    "hdr_format",
    "output_mode",
    "cm_version",
    "structure",
    "l5_offsets",
    "l1_nits",
    "l1_pq",
    "l6_mdl",
    "l6_max_cll_fall",
    "hdr10_mdl",
    "hdr10_max_cll_fall",
    "dv_version",
    "dv_profile",
    "dv_rpu_present",
    "dv_bl_present",
    "dv_el_present",
    "dv_el_type",
    "bit_depth",
)

_lock              = threading.Lock()
_snapshot_key      = None
_snapshot_info: dict[str, str] = dict.fromkeys(_FIELDS, "")
_snapshot_playing  = False
_snapshot_until    = 0.0

_logged_import_error = False
_logged_derive_error = False


def _log(msg: str, level: int = xbmc.LOGINFO) -> None:
    xbmc.log(f"TinyPPI: {msg}", level)


def _localized(label_id: int, fallback: str) -> str:
    """Return an addon-localized label, falling back when Kodi has no string."""
    text = _ADDON.getLocalizedString(label_id)
    return text or fallback


def _na_label() -> str:
    """Return the localized label shown when DV metadata is not available."""
    return _localized(_LABEL_NA, "N/A")


def is_status_label(value: str) -> bool:
    """Return True when a value is the localized N/A status label rather than a
    reading, so callers can substitute their own fallback for it."""
    return value == _na_label()


# --- Side-data access ------------------------------------------------------

def _empty_sidedata() -> dict:
    """Return a parse result shaped like script.module.sidedata's, all empty."""
    return {
        "flags": [],
        "structure": None,
        "config": None,
        "rpu": None,
        "hdr10plus": None,
        "mdcv": None,
        "cll": None,
    }


def _empty_info() -> dict[str, str]:
    """Return a complete empty field dict."""
    return dict.fromkeys(_FIELDS, "")


def _parse(raw: str) -> dict:
    """Parse the raw side-data JSON, or return an empty result.

    ``parse_sidedata`` degrades each section to None rather than raising, so the
    guard here only covers the module being absent and the one failure it
    documents as out of its hands (a libdovi panic on malformed RPU bytes).
    """
    global _logged_import_error

    if _parse_sidedata is None:
        if not _logged_import_error:
            _logged_import_error = True
            _log(
                "DV: script.module.sidedata unavailable "
                f"({_SIDEDATA_IMPORT_ERROR}); DV/HDR metadata is not available",
                xbmc.LOGWARNING,
            )
        return _empty_sidedata()

    if not raw:
        return _empty_sidedata()

    try:
        parsed = _parse_sidedata(raw)
    except Exception as exc:
        _log(f"DV: side data could not be parsed: {exc}", xbmc.LOGWARNING)
        return _empty_sidedata()

    return parsed if isinstance(parsed, dict) else _empty_sidedata()


def _derive(key: tuple[str, str, str]) -> dict[str, str]:
    """Parse one raw payload and derive the fields, never raising.

    ``parse_sidedata`` degrades rather than raising and ``_build_info`` only
    reads with ``.get``, so nothing here is expected to throw -- but the whole
    chain now runs inside polling loops that would lose their thread if it did,
    and it crosses into a third-party module and a native library on the way.
    So the derivation is contained here: an unexpected failure costs the frame's
    metadata, logged once, and nothing else.
    """
    global _logged_derive_error

    try:
        return _build_info(_parse(key[0]), key[1], key[2])
    except Exception as exc:
        if not _logged_derive_error:
            _logged_derive_error = True
            _log(
                f"DV: side data could not be interpreted ({exc}); "
                "DV/HDR fields stay empty for now",
                xbmc.LOGWARNING,
            )
        return _empty_info()


def _snapshot() -> tuple[dict[str, str], bool]:
    """Return ``(fields, playing)`` for the frame on screen.

    ``playing`` separates "nothing to say" from "nothing there": with no video
    every field reads empty, while a playing stream that simply carries no such
    metadata block reads as N/A or as the row's own placeholder.

    The raw payload is re-parsed only when it changes, and the derived dict is
    held for ``_SNAPSHOT_TTL``, so a polling pass costs one parse no matter how
    many fields it asks for.
    """
    global _snapshot_key, _snapshot_info, _snapshot_playing, _snapshot_until

    now = time.monotonic()
    with _lock:
        if now < _snapshot_until:
            return _snapshot_info, _snapshot_playing

    if not xbmc.getCondVisibility("Player.HasVideo"):
        empty = _empty_info()
        with _lock:
            _snapshot_key     = None
            _snapshot_info    = empty
            _snapshot_playing = False
            _snapshot_until   = now + _SNAPSHOT_TTL
        return empty, False

    key = (
        xbmc.getInfoLabel(_SIDEDATA_LABEL),
        xbmc.getInfoLabel(_HDR_TYPE_LABEL),
        xbmc.getInfoLabel(_HDR_DETAIL_LABEL),
    )

    with _lock:
        if key == _snapshot_key:
            _snapshot_playing = True
            _snapshot_until   = now + _SNAPSHOT_TTL
            return _snapshot_info, True

    fields = _derive(key)

    with _lock:
        _snapshot_key     = key
        _snapshot_info    = fields
        _snapshot_playing = True
        _snapshot_until   = time.monotonic() + _SNAPSHOT_TTL
    return fields, True


# --- Value formatting ------------------------------------------------------

def _fmt_num(value) -> str:
    """Format a plain number, dropping a redundant ``.0`` tail (``1000.0`` ->
    ``"1000"``).  Non-numeric values yield ``''``."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _fmt_lum(value) -> str:
    """Format a luminance in nits.

    Whole numbers at or above 1 cd/m², four decimals below it (a mastering
    display's minimum is of the order of 0.0001), with the trailing-zero tail
    trimmed so ``0.0050`` reads as ``0.005``.  Mirrors the reference
    diagnostic's number formatting.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return ""
    if value and abs(value) < 1.0:
        return f"{value:.4f}".rstrip("0").rstrip(".")
    return str(int(round(value)))


def _joined(values: list[str]) -> str:
    """Join the parts of a multi-value row, or ``''`` when one is missing."""
    return " | ".join(values) if all(values) else ""


def _present_flag(value) -> str:
    """Return ``true`` / ``false`` for a presence flag (rendered as an icon via
    ``String.IsEqual``), or ``''`` when unknown so neither icon shows."""
    if value is None:
        return ""
    return "true" if value else "false"


# Enhancement-layer tags whose colour is user-themeable (FEL forest, MEL
# tangerine by default).  The ARGB hex is published by theme.apply_theme; the
# tag is coloured only when read (see _colourise_el_tag) so a colour change
# takes effect live.
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
    """Return the profile string with a single (uncoloured) FEL/MEL tag
    appended; ``_colourise_el_tag`` colours it at read time."""
    if el_type in _EL_COLOURS:
        return f"{profile} {el_type}".strip()
    return profile


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


# --- Field derivation ------------------------------------------------------

# A bare Dolby Vision profile as VideoPlayer.HdrDetail reports it, e.g. ``8.1``.
_PROFILE_RE = re.compile(r"^\d{1,2}(?:\.\d{1,2})?$")


def _hdr_token(label: str, parsed: dict) -> str:
    """Classify the source into a ``VideoPlayer.HdrType``-style token: ``''``
    (SDR), ``'hdr10'`` / ``'hdr10+'``, ``'hlg'`` or ``'dolbyvision'``.

    Kodi's label reads the container and is the only source for HLG, which
    carries no payload of its own.  The side data is the bitstream itself, so
    it settles what the container does not signal -- Dolby Vision announced
    through a Blu-ray playlist rather than the PMT, or HDR10+ the demuxer did
    not flag.  Both describe the source, so a stream the player converts or
    strips downstream still reads as the format it actually is.
    """
    low = (label or "").strip().lower()
    if "dolby" in low or "dovi" in low:
        token = "dolbyvision"
    elif "hdr10plus" in low or "hdr10+" in low:
        token = "hdr10+"
    elif "hlg" in low:
        token = "hlg"
    elif "hdr" in low or "pq" in low:
        token = "hdr10"
    else:
        token = ""

    if token == "dolbyvision":
        return token
    if parsed.get("rpu") or parsed.get("config"):
        return "dolbyvision"
    if parsed.get("hdr10plus"):
        return "hdr10+"
    if not token and (parsed.get("mdcv") or parsed.get("cll")):
        return "hdr10"
    return token


def _dv_profile(hdr_detail: str, config: dict | None, rpu: dict | None) -> str:
    """Return the Dolby Vision ``<profile>.<compatibility>`` string.

    The dvcC/dvvC configuration record is container-level truth and the same
    thing the old probe read, so it answers first.  CoreELEC latches it from the
    demuxer's own hints rather than the rewritten ones, so it still names the
    source profile after the profile 4/7 -> 8 conversion the player applies
    before the decoder (which the side data notes with a ``converted`` flag).

    Without a configuration record, ``VideoPlayer.HdrDetail`` is asked next --
    only when it holds a bare profile number, so an unrelated value cannot leak
    into the line -- and the RPU's own guess is the last resort.  That guess
    carries no compatibility digit: a profile 10 stream has a profile 8-shaped
    RPU, so it is reported plain rather than invented.
    """
    profile = (config or {}).get("profile")
    compat  = (config or {}).get("compat_id")
    if profile is not None and compat is not None:
        return f"{profile}.{compat}"

    detail = (hdr_detail or "").strip()
    if _PROFILE_RE.match(detail):
        return detail

    guess = (rpu or {}).get("profile")
    return str(guess) if guess is not None else ""


def _hdr10plus_profile_label(hdr10plus: dict | None) -> str:
    """Return the HDR10+ profile, e.g. ``'Profile B'``, or ``''`` when absent."""
    profile = str((hdr10plus or {}).get("profile") or "").strip()
    return f"Profile {profile.upper()}" if profile else ""


def _output_mode(
    token: str, profile: str, el_type: str, hdr10plus: dict | None
) -> str:
    """Build the overlay's output-mode string.

    Dolby Vision reads as ``Dolby Vision Profile <p>`` plus its FEL/MEL tag,
    HDR10+ appends ``Profile A``/``B``; SDR yields ``''`` so the caller can
    fall back to a plain label from Kodi's own HDR type.

    A Dolby Vision stream whose profile is not known at all -- Kodi says so but
    no side data reached us, e.g. on a build without the label -- reads as the
    bare format name.  Naming a profile there would be a guess, and this line
    is the one the overlay is read for.
    """
    if token == "dolbyvision":
        if not profile:
            return "Dolby Vision"
        return f"Dolby Vision Profile {_format_el_tag(profile, el_type)}"
    if token == "hdr10+":
        return f"HDR10+ {_hdr10plus_profile_label(hdr10plus)}".strip()
    if token == "hdr10":
        return "HDR10"
    if token == "hlg":
        return "HLG"
    return ""


def _cm_version(rpu: dict | None) -> str:
    """Return the DV Content-Mapping version as ``CMv4.0`` / ``CMv2.9``, or
    ``''`` when the RPU carries no display-management block."""
    version = (rpu or {}).get("cm_version")
    return f"CMv{version}" if version else ""


def _structure_abbr(structure, config: dict | None, el_type: str) -> str:
    """Return the layer structure as a compact ``(<track>-<layer>)`` tag:
    ``(ST-DL)`` / ``(DT-DL)`` / ``(ST-SL)`` (Single/Dual Track, Single/Dual
    Layer).  The side data names a structure only for dual-layer streams, so a
    single-layer profile (5 / 8) falls through to ``(ST-SL)``."""
    if isinstance(structure, str) and structure.strip():
        track = "DT" if structure.strip().lower().startswith("dt") else "ST"
        return f"({track}-DL)"
    dual = bool((config or {}).get("el_present")) or el_type in _EL_COLOURS
    return "(ST-DL)" if dual else "(ST-SL)"


def _dv_level(config: dict | None) -> str:
    """Return the Dolby Vision level from the configuration record (e.g. ``6``),
    or ``''`` when it is absent or unset."""
    level = (config or {}).get("level")
    return str(level) if isinstance(level, int) and level > 0 else ""


def _presence(
    config: dict | None, rpu: dict | None, el_type: str
) -> tuple[str, str, str]:
    """Return the ``(rpu, base layer, enhancement layer)`` presence flags.

    The configuration record states all three.  Without one, an RPU that parsed
    proves itself and its base layer, and its header's FEL/MEL type stands in
    for the enhancement layer.
    """
    if config:
        return (
            _present_flag(config.get("rpu_present")),
            _present_flag(config.get("bl_present")),
            _present_flag(config.get("el_present")),
        )
    if rpu:
        return "true", "true", _present_flag(el_type in _EL_COLOURS)
    return "", "", ""


def _bit_depth(el_type: str) -> str:
    """Return the source bit depth, which only a full enhancement layer can
    raise: base layer plus FEL reconstruct to 12-bit.

    Everything else -- MEL, single-layer Dolby Vision, HDR10, HDR10+, HLG -- is
    a 10-bit stream, and SDR an 8-bit one, so ``''`` is returned there and the
    caller derives the depth from the HDR type (see
    properties.get_VideoBitDepthVar).
    """
    return "12" if el_type == "FEL" else ""


def _build_info(parsed: dict, hdr_label: str, hdr_detail: str) -> dict[str, str]:
    """Turn one parsed side-data result into the separate overlay fields.

    Dolby Vision fills the RPU-backed rows (L1, L5, L6, CM version, layer
    descriptors); the static MDCV / CLL SEIs fill the HDR10 rows for every
    format that carries them, Dolby Vision included -- there they are its HDR10
    fallback layer, shown distinctly from the RPU's own L6 values.  A format
    that carries neither leaves those rows empty (shown as N/A).
    """
    info = _empty_info()

    config    = parsed.get("config")
    rpu       = parsed.get("rpu")
    hdr10plus = parsed.get("hdr10plus")
    mdcv      = parsed.get("mdcv")
    cll       = parsed.get("cll")
    header    = (rpu or {}).get("header") or {}

    token   = _hdr_token(hdr_label, parsed)
    el_type = (header.get("el_type") or "").upper()
    profile = _dv_profile(hdr_detail, config, rpu) if token == "dolbyvision" else ""

    info["hdr_format"]  = token
    info["output_mode"] = _output_mode(token, profile, el_type, hdr10plus)

    if token == "dolbyvision":
        info["cm_version"]     = _cm_version(rpu)
        info["structure"]      = _structure_abbr(parsed.get("structure"), config, el_type)
        info["dv_version"]     = _dv_level(config)
        info["dv_profile"]     = profile
        # FEL/MEL type; profiles without an EL (e.g. 8.1) fall back to the
        # profile number.  Stored uncoloured, themed at read time.
        info["dv_el_type"]     = el_type or profile
        info["bit_depth"]      = _bit_depth(el_type)
        (
            info["dv_rpu_present"],
            info["dv_bl_present"],
            info["dv_el_present"],
        ) = _presence(config, rpu, el_type)

    # Per-frame RPU blocks: the active area the aspect-ratio row is computed
    # from, and the frame's luminance in nits (FLL) and raw PQ codes.
    l5 = (rpu or {}).get("l5")
    if l5:
        info["l5_offsets"] = _joined([
            _fmt_num(l5.get(edge)) for edge in ("left", "right", "top", "bottom")
        ])

    l1 = (rpu or {}).get("l1")
    if l1:
        info["l1_nits"] = _joined([
            _fmt_lum(l1.get(key)) for key in ("min_nits", "max_nits", "avg_nits")
        ])
        info["l1_pq"] = _joined([
            _fmt_num(l1.get(key)) for key in ("min_pq", "max_pq", "avg_pq")
        ])

    # L6 carries the mastering display and content light the RPU itself
    # declares; the static SEIs carry the stream's own.
    l6 = (rpu or {}).get("l6")
    if l6:
        info["l6_mdl"] = _joined([
            _fmt_lum(l6.get("max_lum_nits")), _fmt_lum(l6.get("min_lum_nits")),
        ])
        info["l6_max_cll_fall"] = _joined([
            _fmt_num(l6.get("max_cll")), _fmt_num(l6.get("max_fall")),
        ])

    if mdcv:
        info["hdr10_mdl"] = _joined([
            _fmt_lum(mdcv.get("max_luminance")), _fmt_lum(mdcv.get("min_luminance")),
        ])

    if cll:
        info["hdr10_max_cll_fall"] = _joined([
            _fmt_num(cll.get("max_cll")), _fmt_num(cll.get("max_fall")),
        ])

    return info


# --- Field getters ---------------------------------------------------------

def _raw(key: str) -> str:
    """Return one field verbatim, ``''`` when it has no value.  No status label,
    for the fields whose absence the skin itself branches on."""
    fields, _playing = _snapshot()
    return fields.get(key, "")


def _value(key: str) -> str:
    """Return one field, or the localized N/A label while a video is playing."""
    fields, playing = _snapshot()
    value = fields.get(key, "")
    if value:
        return value
    return _na_label() if playing else ""


def _value_or(key: str, fallback: str) -> str:
    """Return one field, showing ``fallback`` (e.g. ``0 | 0``) instead of the
    N/A label when it is absent."""
    return _raw(key) or fallback


def get_hdr_format() -> str:
    """Return the detected HDR type token (``''`` / ``'hdr10'`` / ``'hdr10+'`` /
    ``'hlg'`` / ``'dolbyvision'``).  No status label."""
    return _raw("hdr_format")


def get_output_mode() -> str:
    """Return the output-mode line (format + DV profile), with the ``N/A`` label
    and the FEL/MEL tag coloured at read time."""
    return _colourise_el_tag(_value("output_mode"))


def get_cm_version() -> str:
    """Return the DV Content-Mapping version, or '' when unknown.  No status label."""
    return _raw("cm_version")


def get_structure() -> str:
    """Return the layer-structure tag (``(ST-DL)`` / ``(DT-DL)`` / ``(ST-SL)``),
    or '' when unknown.  No status label."""
    return _raw("structure")


def get_l5_offsets() -> str:
    """Return the Dolby Vision Level 5 active-area offsets of the current frame,
    falling back to ``0 | 0 | 0 | 0`` (left | right | top | bottom)."""
    return _value_or("l5_offsets", L5_EMPTY)


def get_l1_nits() -> str:
    """Return the Level 1 frame luminance in nits (``min | max | avg``) for the
    current frame, falling back to ``0 | 0 | 0``."""
    return _value_or("l1_nits", L1_EMPTY)


def get_l1_pq() -> str:
    """Return the Level 1 frame luminance as raw PQ codes (``min | max | avg``,
    0-4095) for the current frame, falling back to ``0 | 0 | 0``."""
    return _value_or("l1_pq", L1_EMPTY)


def get_l6_rpu_mdl() -> str:
    """Return Dolby Vision Level 6 RPU mastering-display luminance."""
    return _value_or("l6_mdl", "0 | 0")


def get_l6_rpu_max_cll_fall() -> str:
    """Return Dolby Vision Level 6 RPU MaxCLL/MaxFALL."""
    return _value_or("l6_max_cll_fall", "0 | 0")


def get_hdr10_mdl() -> str:
    """Return the HDR10 static mastering-display luminance (``max | min``)."""
    return _value_or("hdr10_mdl", "0 | 0")


def get_hdr10_max_cll_fall() -> str:
    """Return the HDR10 static MaxCLL/MaxFALL (``cll | fall``)."""
    return _value_or("hdr10_max_cll_fall", "0 | 0")


def get_dv_version() -> str:
    """Return the Dolby Vision ``level`` (e.g. ``6``), or '' when unknown.  No
    status label."""
    return _raw("dv_version")


def get_dv_profile() -> str:
    """Return the bare Dolby Vision profile number (e.g. ``7.6``), or '' when
    not known.  Surfaces no status label."""
    return _raw("dv_profile")


def get_dv_rpu_present() -> str:
    """Return ``true`` / ``false`` for RPU presence, or '' when unknown."""
    return _raw("dv_rpu_present")


def get_dv_bl_present() -> str:
    """Return ``true`` / ``false`` for base-layer presence, or '' when unknown."""
    return _raw("dv_bl_present")


def get_dv_el_present() -> str:
    """Return ``true`` / ``false`` for enhancement-layer presence, or '' when
    unknown."""
    return _raw("dv_el_present")


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
    return _raw("dv_el_type")


def get_bit_depth() -> str:
    """Return the source bit depth as a bare number string (e.g. ``12``); a full
    enhancement layer reports the reconstructed VDR depth, every other stream
    its base-layer depth."""
    return _value("bit_depth")
