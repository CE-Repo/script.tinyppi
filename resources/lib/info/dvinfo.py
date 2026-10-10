# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Dolby Vision / HDR metadata from CoreELEC's raw side-data InfoLabel.

``Player.Process(video.sidedata)`` (CoreELEC 22) publishes the raw payloads
of the stream being decoded as base64 in JSON: the Dolby Vision RPU, the
dvcC/dvvC configuration record, the HDR10+ ST 2094-40 message and the static
MDCV / CLL SEIs.  script.module.sidedata parses them (libdovi and libavutil
via ctypes); this module maps the result onto the fields properties.py
publishes.

The label updates per frame, so L1 (frame luminance) and L5 (active area)
follow the picture.  A payload is parsed only when it changes, and the field
dict is held for a fraction of a second, so one polling pass over the ~20
getters costs one parse.  The RPU's composer data (reshaping curves, NLQ) is
large and only built on request (``get_sidedata(mapping=True)``, asked by
the metadata view on each tick).

The side data describes the source: CoreELEC captures it before its own
bitstream conversion and records what it did in ``flags`` (``converted`` for
profile 4/7 -> 8, ``rpu-removed`` / ``hdr10plus-removed``).  So profile,
enhancement layer and structure read as the file carries them.

``VideoPlayer.HdrType`` identifies HLG (which has no payload), and
``VideoPlayer.HdrDetail`` supplies the DV profile when there is no
configuration record.

CoreELEC 22 on Amlogic only; elsewhere the label is empty and every field
falls back to N/A.
"""

import re
import threading
import time

import xbmc
from core.log import channel
from core.utils import home_window, localized

try:
    from sidedata import parse_sidedata as _parse_sidedata
    _SIDEDATA_IMPORT_ERROR = None
except Exception as exc:  # a broken module must not break the add-on
    _parse_sidedata = None
    _SIDEDATA_IMPORT_ERROR = exc

# ``include_mapping`` arrived in script.module.sidedata 1.6.0 (required by
# addon.xml).  Detected rather than assumed, so an older module still serves
# every other field; the composer section is then simply empty.
_MAPPING_KWARG = "include_mapping" in getattr(
    getattr(_parse_sidedata, "__code__", None), "co_varnames", ())

_LABEL_NA = 32230

# Shown for L5 / L1 when the RPU has nothing to report.
L5_EMPTY = "0 | 0 | 0 | 0"
L1_EMPTY = "0 | 0 | 0"

_SIDEDATA_LABEL   = "Player.Process(video.sidedata)"
_HDR_TYPE_LABEL   = "VideoPlayer.HdrType"
_HDR_DETAIL_LABEL = "VideoPlayer.HdrDetail"

# The playing item; latched fields belong to it (see _hold_static), as do
# dvmetadata's held blocks.  Only compared, never published.
_SOURCE_LABEL     = "Player.FilenameAndPath"

# Lifetime of a derived field dict: short enough for every pass to see the
# current frame, long enough for one pass to share one read and parse.
_SNAPSHOT_TTL = 0.1

# How long a request for the RPU's composer data lasts.  The mapping can be
# thousands of coefficients and only the metadata view shows it, so the view
# asks on each tick (see ``get_sidedata``) and the request lapses on close.
_MAPPING_TTL = 1.0

# All fields; the getters below expose them one by one.
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
    "source_mdl",
    "hdr10_mdl",
    "hdr10_max_cll_fall",
    "dv_version",
    "dv_profile",
    "dv_rpu_present",
    "dv_bl_present",
    "dv_el_present",
    "dv_el_type",
    "bit_depth",
    "hdr10plus_present",
)

# Fields not present in every frame (see _hold_static).  The source mastering
# display is only in frames with uncompressed DM data; without the latch the
# MDL row would flip to L6 every other frame.  HDR10+ presence is a property
# of the title (hybrid grade or not), so it is latched too.
_STATIC_FIELDS = ("source_mdl", "hdr10plus_present")

# Problems already logged ("import", "derive"): each is logged once.
_warned: set[str] = set()


_log = channel("dv", xbmc.LOGINFO)


def _localized(label_id: int, fallback: str) -> str:
    """Return a localized label, or *fallback* when Kodi has none."""
    return localized(label_id) or fallback


def _na_label() -> str:
    """Return the localized N/A label."""
    return _localized(_LABEL_NA, "N/A")


def na_label() -> str:
    """Return the localized N/A label for other modules."""
    return _na_label()


def is_status_label(value: str) -> bool:
    """Return whether *value* is the N/A label rather than a reading."""
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


def _parse(raw: str, mapping: bool = False) -> dict:
    """Parse the raw side-data JSON, or return an empty result.

    ``parse_sidedata`` returns None per section instead of raising; the guard
    covers a missing module and libdovi panics on malformed RPU bytes.
    *mapping* also builds the RPU's composer data, which the overlay never
    needs.
    """
    if _parse_sidedata is None:
        if "import" not in _warned:
            _warned.add("import")
            _log(
                "DV: script.module.sidedata unavailable "
                f"({_SIDEDATA_IMPORT_ERROR}); DV/HDR metadata is not available",
                xbmc.LOGWARNING,
            )
        return _empty_sidedata()

    if not raw:
        return _empty_sidedata()

    try:
        if _MAPPING_KWARG:
            parsed = _parse_sidedata(raw, include_mapping=mapping)
        else:
            parsed = _parse_sidedata(raw)
    except Exception as exc:
        _log(f"DV: side data could not be parsed: {exc}", xbmc.LOGWARNING)
        return _empty_sidedata()

    return parsed if isinstance(parsed, dict) else _empty_sidedata()


def _derive(key: tuple[str, str, str, bool]) -> tuple[dict | None, dict[str, str]]:
    """Parse a raw payload and derive the fields; never raises.

    Returns ``(parsed, fields)``, so the metadata view can reuse the parse.
    Nothing here should throw, but it runs in polling threads and crosses
    into a native library, so a failure only costs the frame's metadata and
    is logged once.
    """
    parsed = None
    try:
        parsed = _parse(key[0], key[3])
        return parsed, _build_info(parsed, key[1], key[2])
    except Exception as exc:
        if "derive" not in _warned:
            _warned.add("derive")
            _log(
                f"DV: side data could not be interpreted ({exc}); "
                "DV/HDR fields stay empty for now",
                xbmc.LOGWARNING,
            )
        return parsed, _empty_info()


class _Snapshots:
    """The current frame's fields, held for ``_SNAPSHOT_TTL``.

    Shared by everything that polls the metadata (overlay, splash,
    dashboard); the payload is re-parsed only when it changes.  Also holds
    the latch of title-level fields (see ``_hold_static``) and the pending
    composer-data request (see ``get_sidedata``).
    """

    def __init__(self) -> None:
        self._lock    = threading.Lock()
        self._key: tuple | None = None
        self._info    = _empty_info()
        self._parsed: dict | None = None
        self._playing = False
        self._until   = 0.0
        self._mapping_until  = 0.0
        self._latched: dict[str, str] = {}
        self._latched_source = ""

    def want_mapping(self) -> None:
        """Ask for the RPU's composer data for the next ``_MAPPING_TTL``."""
        with self._lock:
            self._mapping_until = time.monotonic() + _MAPPING_TTL

    @property
    def parsed(self) -> dict | None:
        """The full parse result behind the current fields."""
        with self._lock:
            return self._parsed

    def _hold_static(self, fields: dict[str, str], source: str) -> None:
        """Carry title-level fields across frames that omit them.

        With DM metadata compression most frames refer back to earlier
        metadata, so these fields are usually absent and their rows would
        blink N/A.  The last reading therefore stands until replaced, within
        the same title: a change of *source* clears the latch.

        Keyed to the title, not to the end of playback, which this module
        may never see (the dashboard producer stops asking when playback
        ends, see ``Snapshots.build`` in web/snapshot.py).  Otherwise a plain
        DV title after a DV + HDR10+ hybrid read as hybrid and got no VS10
        modes (issue #71).

        Call with the lock held, with *source* read outside it.
        """
        if source != self._latched_source:
            self._latched.clear()
            self._latched_source = source

        for name in _STATIC_FIELDS:
            value = fields.get(name, "")
            if value:
                self._latched[name] = value
            elif self._latched.get(name):
                fields[name] = self._latched[name]

    def current(self) -> tuple[dict[str, str], bool]:
        """Return ``(fields, playing)`` for the current frame.

        *playing* tells "no video" (all fields empty) from "no such
        metadata" (N/A or the row's placeholder).

        A pending composer-data request is part of the key, so the snapshot
        is re-parsed when the mapping is first wanted and again after the
        request lapses.
        """
        now = time.monotonic()
        with self._lock:
            if now < self._until:
                return self._info, self._playing
            mapping = now < self._mapping_until

        if not xbmc.getCondVisibility("Player.HasVideo"):
            empty = _empty_info()
            with self._lock:
                self._key     = None
                self._info    = empty
                self._parsed  = None
                self._playing = False
                self._until   = now + _SNAPSHOT_TTL
                self._latched.clear()
                self._latched_source = ""
            return empty, False

        key = (
            xbmc.getInfoLabel(_SIDEDATA_LABEL),
            xbmc.getInfoLabel(_HDR_TYPE_LABEL),
            xbmc.getInfoLabel(_HDR_DETAIL_LABEL),
            mapping,
        )

        with self._lock:
            if key == self._key:
                self._playing = True
                self._until   = now + _SNAPSHOT_TTL
                return self._info, True

        parsed, fields = _derive(key)
        # Read outside the lock: only assignments happen under it.
        source = xbmc.getInfoLabel(_SOURCE_LABEL)

        with self._lock:
            self._hold_static(fields, source)
            self._key     = key
            self._info    = fields
            self._parsed  = parsed
            self._playing = True
            self._until   = time.monotonic() + _SNAPSHOT_TTL
        return fields, True


_snapshots = _Snapshots()


def _snapshot() -> tuple[dict[str, str], bool]:
    """Return ``(fields, playing)`` for the current frame (see ``_Snapshots``)."""
    return _snapshots.current()


def get_sidedata(mapping: bool = False) -> dict | None:
    """Return the full parse result behind the current fields.

    For the metadata view, which prints every block; it shares the overlay's
    snapshot, so no extra parse.  *mapping* requests the RPU's composer data
    for ``_MAPPING_TTL``; the view asks on each tick, and the first call
    after a lapse is answered without it (the next tick has it).

    None while no video plays or when the payload did not parse.
    """
    if mapping:
        _snapshots.want_mapping()
    _snapshots.current()
    return _snapshots.parsed


# --- Value formatting ------------------------------------------------------

def _fmt_num(value: object) -> str:
    """Format a number without a redundant ``.0``; '' for non-numbers."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _fmt_lum(value: object) -> str:
    """Format a luminance in nits.

    Whole numbers from 1 cd/m² up, otherwise up to four decimals with
    trailing zeros trimmed (``0.005``), like the reference diagnostic.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return ""
    if value and abs(value) < 1.0:
        return f"{value:.4f}".rstrip("0").rstrip(".")
    return str(int(round(value)))


def _joined(values: list[str]) -> str:
    """Join the parts of a multi-value row, or '' when one is missing."""
    return " | ".join(values) if all(values) else ""


def _present_flag(value: object) -> str:
    """Return ``true``/``false`` for a presence flag, or '' when unknown.

    The skin shows an icon via ``String.IsEqual``; '' shows neither.
    """
    if value is None:
        return ""
    return "true" if value else "false"


# Enhancement-layer tags with themeable colours (FEL forest, MEL tangerine by
# default).  theme.apply_theme publishes the ARGB value; tags are coloured
# when read, so a colour change applies immediately.
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
    """Return *profile* with an uncoloured FEL/MEL tag appended."""
    if el_type in _EL_COLOURS:
        return f"{profile} {el_type}".strip()
    return profile


def _colourise_el_tag(text: str) -> str:
    """Colour a trailing FEL/MEL tag with its themed colour."""
    for tag in _EL_COLOURS:
        if text == tag or text.endswith(" " + tag):
            colour = home_window().getProperty(
                _EL_COLOUR_PROPERTIES[tag]
            ).strip() or _EL_COLOUR_DEFAULTS[tag]
            head = text[: len(text) - len(tag)]
            return f"{head}[COLOR {colour}]{tag}[/COLOR]"
    return text


# --- Field derivation ------------------------------------------------------

# A bare DV profile as reported by VideoPlayer.HdrDetail, e.g. ``8.1``.
_PROFILE_RE = re.compile(r"^\d{1,2}(?:\.\d{1,2})?$")


def _hdr_token(label: str, parsed: dict) -> str:
    """Return the source HDR token: '', hdr10, hdr10+, hlg or dolbyvision.

    Kodi's label (from the container) is the only source for HLG.  The side
    data (from the bitstream) catches what the container does not signal,
    e.g. DV announced only in a Blu-ray playlist, or unflagged HDR10+.
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

    The dvcC/dvvC record comes first; it names the source profile even after
    a 4/7 -> 8 conversion.  Next ``VideoPlayer.HdrDetail``, if it is a bare
    profile number, and last the RPU's own guess, without a compatibility
    digit (a profile 10 stream has a profile 8-shaped RPU).
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
    """Return the HDR10+ profile, e.g. ``Profile B``, or ''."""
    profile = str((hdr10plus or {}).get("profile") or "").strip()
    return f"Profile {profile.upper()}" if profile else ""


def _output_mode(
    token: str, profile: str, el_type: str, hdr10plus: dict | None
) -> str:
    """Build the overlay's output-mode string.

    ``Dolby Vision Profile <p>`` plus its FEL/MEL tag, or plain
    ``Dolby Vision`` when the profile is unknown; HDR10+ appends its
    profile.  SDR yields '' so the caller can fall back to Kodi's HDR type.
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
    """Return the CM version (``CMv4.0`` / ``CMv2.9``), or '' without DM data."""
    version = (rpu or {}).get("cm_version")
    return f"CMv{version}" if version else ""


def _structure_abbr(structure: object, config: dict | None, el_type: str) -> str:
    """Return the layer structure: ``ST-DL``, ``DT-DL`` or ``ST-SL``.

    Single/dual track, single/dual layer.  The side data names a structure
    only for dual-layer streams; profiles 5 and 8 fall back to ``ST-SL``.
    """
    if isinstance(structure, str) and structure.strip():
        track = "DT" if structure.strip().lower().startswith("dt") else "ST"
        return f"{track}-DL"
    dual = bool((config or {}).get("el_present")) or el_type in _EL_COLOURS
    return "ST-DL" if dual else "ST-SL"


def _dv_record_version(config: dict | None) -> str:
    """Return the dvcC/dvvC record version, e.g. ``1.0``, or ''.

    The record's own version, not the DV level (``config['level']``).
    """
    major = _fmt_num((config or {}).get("version_major"))
    minor = _fmt_num((config or {}).get("version_minor"))
    return f"{major}.{minor}" if major and minor else ""


def _presence(
    config: dict | None, rpu: dict | None, el_type: str
) -> tuple[str, str, str]:
    """Return the (RPU, base layer, enhancement layer) presence flags.

    Taken from the configuration record; without one, a parsed RPU implies
    RPU and base layer, and its FEL/MEL type implies the enhancement layer.
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
    """Return ``12`` for a full enhancement layer, else ''.

    Other depths follow from the HDR type (see
    ``properties.get_VideoBitDepthVar``).
    """
    return "12" if el_type == "FEL" else ""


def _build_info(parsed: dict, hdr_label: str, hdr_detail: str) -> dict[str, str]:
    """Turn one parse result into the overlay fields.

    Dolby Vision fills the RPU rows (L1, L5, L6, CM version, layers).  The
    static MDCV / CLL SEIs fill the HDR10 rows for any format, Dolby Vision
    included (its HDR10 fallback, shown apart from L6).  Missing blocks
    leave their rows empty (N/A).
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

    # HDR10+ still reaching the decoder.  On a DV source this is a hybrid
    # grade the driver cannot convert with VS10.  A payload Kodi stripped
    # (``hdr10plus-removed``) no longer counts.
    if hdr10plus and "hdr10plus-removed" not in (parsed.get("flags") or []):
        info["hdr10plus_present"] = "1"

    if token == "dolbyvision":
        info["cm_version"]     = _cm_version(rpu)
        info["structure"]      = _structure_abbr(parsed.get("structure"), config, el_type)
        info["dv_version"]     = _dv_record_version(config)
        info["dv_profile"]     = profile
        # FEL/MEL, or the profile number without an EL (e.g. 8.1).  Stored
        # uncoloured; themed when read.
        info["dv_el_type"]     = el_type or profile
        info["bit_depth"]      = _bit_depth(el_type)
        (
            info["dv_rpu_present"],
            info["dv_bl_present"],
            info["dv_el_present"],
        ) = _presence(config, rpu, el_type)

    # Per-frame RPU blocks: L5 active area, L1 luminance in nits and PQ.
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

    # L6: mastering display and content light declared in the RPU.
    l6 = (rpu or {}).get("l6")
    if l6:
        info["l6_mdl"] = _joined([
            _fmt_lum(l6.get("max_lum_nits")), _fmt_lum(l6.get("min_lum_nits")),
        ])
        info["l6_max_cll_fall"] = _joined([
            _fmt_num(l6.get("max_cll")), _fmt_num(l6.get("max_fall")),
        ])

    # The source master's PQ range as luminance; the MDL row prefers it over
    # L6.  Only in frames with uncompressed DM data (see _STATIC_FIELDS).
    source = (rpu or {}).get("source")
    if source:
        info["source_mdl"] = _joined([
            _fmt_lum(source.get("max_nits")), _fmt_lum(source.get("min_nits")),
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
    """Return field *key* verbatim, or '' (no N/A label)."""
    fields, _playing = _snapshot()
    return fields.get(key, "")


def _value(key: str) -> str:
    """Return field *key*, or N/A while a video plays."""
    fields, playing = _snapshot()
    value = fields.get(key, "")
    if value:
        return value
    return _na_label() if playing else ""


def _value_or(key: str, fallback: str) -> str:
    """Return field *key*, or *fallback* (e.g. ``0 | 0``) when absent."""
    return _raw(key) or fallback


def get_hdr_format() -> str:
    """Return the HDR token ('', hdr10, hdr10+, hlg, dolbyvision)."""
    return _raw("hdr_format")


def get_hdr10plus_present() -> str:
    """Return '1' when the stream carries HDR10+ metadata, else ''.

    Also set for a DV + HDR10+ hybrid, which VS10 cannot convert.  Latched
    per title (see ``_STATIC_FIELDS``).
    """
    return _raw("hdr10plus_present")


def get_output_mode() -> str:
    """Return the output-mode line (format and DV profile), or N/A."""
    return _colourise_el_tag(_value("output_mode"))


def get_cm_version() -> str:
    """Return the CM version, or ''."""
    return _raw("cm_version")


def get_structure() -> str:
    """Return the layer structure (``ST-DL`` / ``DT-DL`` / ``ST-SL``), or ''."""
    return _raw("structure")


def get_l5_offsets() -> str:
    """Return the L5 offsets (left | right | top | bottom), or zeros."""
    return _value_or("l5_offsets", L5_EMPTY)


def get_l1_nits() -> str:
    """Return the L1 luminance in nits (min | max | avg), or zeros."""
    return _value_or("l1_nits", L1_EMPTY)


def get_l1_pq() -> str:
    """Return the L1 luminance as PQ codes 0-4095 (min | max | avg), or zeros."""
    return _value_or("l1_pq", L1_EMPTY)


def get_rpu_mdl() -> str:
    """Return the RPU mastering-display luminance (max | min), or zeros.

    Prefers the source PQ range from the DM data; falls back to L6 (streams
    with fully compressed DM data never carry the source range).
    ``get_rpu_mdl_from_source`` tells which one was used.
    """
    return _raw("source_mdl") or _value_or("l6_mdl", "0 | 0")


def get_rpu_mdl_from_source() -> str:
    """Return ``true`` when ``get_rpu_mdl`` uses the source range, else ''."""
    return "true" if _raw("source_mdl") else ""


def get_l6_rpu_max_cll_fall() -> str:
    """Return the L6 MaxCLL / MaxFALL, or zeros."""
    return _value_or("l6_max_cll_fall", "0 | 0")


def get_hdr10_mdl(l6_fallback: bool = False) -> str:
    """Return the HDR10 static mastering-display luminance (max | min).

    *l6_fallback* uses L6 when there is no MDCV SEI (profile 5 has none).
    Off by default, because the DV panel shows L6 and the static SEIs as
    separate rows.
    """
    value = _raw("hdr10_mdl")
    if not value and l6_fallback:
        value = _raw("l6_mdl")
    return value or "0 | 0"


def get_hdr10_max_cll_fall(l6_fallback: bool = False) -> str:
    """Return the HDR10 static MaxCLL / MaxFALL (see ``get_hdr10_mdl``)."""
    value = _raw("hdr10_max_cll_fall")
    if not value and l6_fallback:
        value = _raw("l6_max_cll_fall")
    return value or "0 | 0"


def get_dv_version() -> str:
    """Return the dvcC/dvvC record version (e.g. ``1.0``), or ''."""
    return _raw("dv_version")


def get_dv_profile() -> str:
    """Return the DV profile (e.g. ``8.1``, or ``8`` without compatibility).

    '' when unknown; the skin branches on the empty value.
    """
    return _raw("dv_profile")


def get_dv_rpu_present() -> str:
    """Return RPU presence (``true``/``false``), or ''."""
    return _raw("dv_rpu_present")


def get_dv_bl_present() -> str:
    """Return base-layer presence (``true``/``false``), or ''."""
    return _raw("dv_bl_present")


def get_dv_el_present() -> str:
    """Return enhancement-layer presence (``true``/``false``), or ''."""
    return _raw("dv_el_present")


def get_dv_el_type() -> str:
    """Return the themed EL type (``FEL``/``MEL``) or profile number, or ''."""
    return _colourise_el_tag(get_dv_el_type_raw())


def get_dv_el_type_raw() -> str:
    """Return the EL type or profile number without colour markup, or ''.

    For callers that colour it themselves, such as the splash's layer pill.
    """
    return _raw("dv_el_type")


def get_bit_depth() -> str:
    """Return ``12`` for a full enhancement layer, else N/A while playing.

    The caller derives other depths from the HDR type.
    """
    return _value("bit_depth")
