"""Dolby Vision / HDR metadata read straight out of Kodi's player.

CoreELEC's Kodi publishes what its own decoder already parsed out of the playing
stream as ``Player.Process(...)`` InfoLabels (xbmc PR #67, *Playerprocessinfo:
add live Dolby Vision and HDR metadata infolabels*): the Dolby Vision
configuration record, the RPU's level 1 / 5 / 6 metadata, the HDR10 static
metadata (MDCV / CLL) and the stream's bit depth.

Nearly everything TinyPPI used to run hdrprobe for is in there, and it is
strictly better than a probe: it costs nothing (the decoder parsed it anyway),
it is there the instant playback starts instead of after a scan, it describes
the stream Kodi is actually decoding rather than a re-read of the file, and the
per-frame values (level 5 active area, level 1 luminance) follow the picture
instead of standing on whatever frame the probe happened to see.

So dvinfo prefers this module and only falls back to hdrprobe when the labels
are missing -- an older Kodi, or a build without the patch -- which keeps every
row filled exactly as before on those boxes.  ``available()`` is what tells the
two apart: an unknown ``Player.Process`` parameter resolves to nothing, so a
label that must always carry a number ("0" at the very least) reading empty
means this build does not have them.

Two details of the old hdrprobe line are not in the labels and are therefore
lost on a build that has them: the HDR10+ profile letter (``HDR10+ Profile A``
now reads ``HDR10+``) and the SL-HDR / HDR Vivid names, which Kodi does not
detect at all -- such a stream reads as the HDR10 or HLG base it rides on.

Field names and value shapes match dvinfo's cache exactly, so the two sources
are interchangeable to every caller.  Audio is not covered here at all: the
source bit depth and sample rate still come from audioprobe.
"""

import xbmc
from core.utils import clean, info

# A label that always answers on a build that has the patch: the raw HDR type is
# a plain number (0 for SDR), so an empty answer can only mean the parameter was
# not understood.  Support cannot appear or disappear while Kodi runs, so a
# positive answer is remembered; a negative one is not, because it is also what
# an unpatched build says and re-asking costs a single label read.
_SUPPORT_LABEL = "video.hdr.type.raw"

_supported = False

# Fields that are not final until the stream's Dolby Vision metadata has been
# parsed: Kodi fills the stream and frame level values only once it has seen an
# rpu (``video.dovi.has.header``) and reads its defaults until then, which would
# briefly show a profile 7 title as an 8.1 with no enhancement layer.  While
# ``pending()`` holds they answer with nothing, so the overlay shows the same
# "Fetching..." it shows for a probe that has not finished.
#
# The HDR type is deliberately not in here: it comes from the container rather
# than the rpu, and it is what the overlay picks its whole layout from.
PENDING_FIELDS = frozenset({
    "output_mode",
    "cm_version",
    "structure",
    "l5_offsets",
    "l6_mdl",
    "l6_max_cll_fall",
    "l1_nits",
    "l1_pq",
    "hdr10_mdl",
    "hdr10_max_cll_fall",
    "dv_version",
    "dv_profile",
    "dv_rpu_present",
    "dv_bl_present",
    "dv_el_present",
    "dv_el_type",
    "bit_depth",
})

# Base-layer signal compatibility ids that make up the second half of a Dolby
# Vision profile string: 1 = HDR10 (8.1), 2 = SDR (8.2), 4 = HLG (8.4).  Ids the
# table does not name (0 = none, 6 = the profile 7 convention) carry no suffix.
_COMPATIBILITY_SUFFIX = {1: ".1", 2: ".2", 4: ".4"}

# Profiles whose display string is fixed by convention rather than by the
# compatibility id, matching what hdrprobe reported for them.
_FIXED_PROFILE_LABELS = {5: "5.0", 7: "7.6"}


def _label(name: str) -> str:
    """Return one ``Player.Process`` InfoLabel, stripped."""
    return info(f"Player.Process({name})").strip()


def _int(name: str) -> int | None:
    """Return a label as an int, or None when it is empty / not a number."""
    raw = clean(_label(name))
    if not raw:
        return None
    try:
        return int(float(raw))
    except ValueError:
        return None


def _num(name: str) -> str:
    """Return a numeric label as a display string, or ``''`` when it is empty or
    not a number.

    Kodi's own formatting is kept: whole numbers print bare and luminance prints
    to four decimals, so a minimum that rounds to nothing still reads ``0.0000``
    -- measured and almost zero -- rather than an unqualified ``0``.
    """
    raw = clean(_label(name))
    if not raw:
        return ""
    try:
        float(raw)
    except ValueError:
        return ""
    return raw


def _flag(name: str) -> bool:
    """Return True for a ``1`` / ``true`` flag label."""
    return _label(name).lower() in ("1", "true")


def _pair(first: str, second: str) -> str:
    """Return ``"<a> | <b>"`` for two numeric labels, or '' if either is empty."""
    a = _num(first)
    b = _num(second)
    return f"{a} | {b}" if a and b else ""


def _triple(first: str, second: str, third: str) -> str:
    """Return ``"<a> | <b> | <c>"``, or '' when any of the three is empty."""
    values = [_num(name) for name in (first, second, third)]
    return " | ".join(values) if all(values) else ""


def _hdr_token(name: str) -> str:
    """Collapse an HDR type label to TinyPPI's own token.

    Kodi spells the types ``hdr10`` / ``hdr10plus`` / ``hlg`` / ``dolbyvision``
    and leaves SDR empty; spelled-out variants (``Dolby Vision``, ``SDR``) are
    read too, so a build whose labels are worded differently still resolves.
    """
    raw = _label(name).lower().replace(" ", "").replace("-", "").replace("_", "")
    if not raw or raw in ("none", "sdr", "unknown"):
        return ""
    if "dolbyvision" in raw or raw.startswith("dovi"):
        return "dolbyvision"
    if "hdr10plus" in raw or "hdr10+" in raw:
        return "hdr10+"
    if "hdr10" in raw:
        return "hdr10"
    if "hlg" in raw:
        return "hlg"
    return ""


def available() -> bool:
    """Return whether this Kodi publishes the live metadata labels."""
    global _supported

    if _supported:
        return True
    _supported = bool(_label(_SUPPORT_LABEL))
    return _supported


def pending() -> bool:
    """Return whether the stream announced Dolby Vision but no RPU has been
    parsed yet, so the RPU-fed fields are still on their defaults."""
    return _flag("video.dovi.has.config") and not _flag("video.dovi.has.header")


def _is_dovi() -> bool:
    """Return whether the playing stream carries Dolby Vision."""
    return (
        _flag("video.dovi.has.config")
        or _flag("video.dovi.has.header")
        or _hdr_token("video.source.hdr.type") == "dolbyvision"
    )


def _el_type() -> str:
    """Return the enhancement-layer type as ``FEL`` / ``MEL``, or ``''``.

    The source label is read first: it is the only place the original type
    survives a profile 7 to profile 8 conversion, which is what the player hands
    the decoder.  Both the short (``FEL``) and spelled-out (``full enhancement
    layer``) wordings are recognised.
    """
    for name in ("video.source.dovi.el.type", "video.dovi.el.type"):
        raw = _label(name).lower()
        if "fel" in raw or "full" in raw:
            return "FEL"
        if "mel" in raw or "minimum" in raw:
            return "MEL"
    return ""


def _profile_and_compatibility() -> tuple[int | None, int | None]:
    """Return the Dolby Vision ``(profile, compatibility id)`` of the source.

    The source pair describes the stream as it was authored; the decoder pair
    (which reads profile 8 for a converted profile 7 stream) stands in when the
    container signalled nothing, e.g. an RPU found only in the bitstream.
    """
    profile = _int("video.source.dovi.profile")
    if profile:
        return profile, _int("video.source.dovi.bl.signal.compatibility")

    profile = _int("video.dovi.profile")
    if profile:
        return profile, _int("video.dovi.bl.signal.compatibility")

    return None, None


def _profile_label() -> str:
    """Return the Dolby Vision profile string (``7.6``, ``8.1``, ...), or ''."""
    profile, compatibility = _profile_and_compatibility()
    if not profile:
        return ""

    fixed = _FIXED_PROFILE_LABELS.get(profile)
    if fixed:
        return fixed
    return f"{profile}{_COMPATIBILITY_SUFFIX.get(compatibility, '')}"


def _hdr_format() -> str:
    """Return the HDR type token of the source stream.

    Read from the *source* side deliberately: the plain type follows the Dolby
    Vision VS10 engine, which reads dolbyvision for whatever it tone maps, and
    the overlay is describing the file rather than the output.
    """
    token = _hdr_token("video.source.hdr.type")
    if token in ("hdr10", "hlg") and (
        _hdr_token("video.source.additional.hdr.type") == "hdr10+"
    ):
        # HDR10+ carried alongside an HDR10 base; the base is what the container
        # signalled, the dynamic metadata is what the stream actually is.
        return "hdr10+"
    return token


def _output_mode() -> str:
    """Return the overlay's output-mode line for the playing stream."""
    if _is_dovi():
        profile = _profile_label() or "8.1"
        # The FEL / MEL tag is coloured by dvinfo when the value is read, so it
        # is appended plain here -- same shape hdrprobe's line had.
        return f"Dolby Vision Profile {profile} {_el_type()}".strip()

    token = _hdr_format()
    if token == "hdr10+":
        # No profile letter: Kodi reports that the metadata is there, not which
        # HDR10+ profile carries it.
        return "HDR10+"
    if token == "hdr10":
        return "HDR10"
    if token == "hlg":
        return "HLG"
    return "SDR" if _label("video.hdr.type.raw") else ""


def _cm_version() -> str:
    """Return the Dolby Vision content-mapping version (``CMv2.9`` / ``CMv4.0``).

    Kodi reports the RPU's version, sometimes with the extension block revision
    behind it (``CMv4.0 1-0``); only the version itself is shown.
    """
    raw = _label("video.dovi.meta.version")
    if not raw:
        return ""
    token = raw.split()[0]
    return token if token.upper().startswith("CM") else ""


def _structure() -> str:
    """Return the layer structure tag (``(ST-SL)`` / ``(ST-DL)`` / ``(DT-DL)``).

    Kodi names the packaging only while the enhancement layer is still there, so
    a profile 7 stream the player converted reports none; the source enhancement
    layer says there was one, and a converted stream carried it inside the base
    track (single track, dual layer).
    """
    if not _is_dovi():
        return ""

    packaging = _label("video.dovi.dual.track").upper()
    if packaging:
        return f"({packaging})"
    return "(ST-DL)" if _el_type() else "(ST-SL)"


def _l5_offsets() -> str:
    """Return the RPU's level 5 active-area offsets for the frame on screen.

    Empty when the frame carries no level 5 metadata, which is dvinfo's cue to
    fall back to the ``0 | 0 | 0 | 0`` placeholder.
    """
    if not (_flag("video.dovi.has.l5") or _label("video.dovi.l5.detected")):
        return ""

    offsets = []
    for edge in ("left", "right", "top", "bottom"):
        value = _int(f"video.dovi.l5.{edge}.offset")
        if value is None:
            return ""
        offsets.append(str(value))
    return " | ".join(offsets)


def _l1_frame_luminance(unit: str) -> str:
    """Return the level 1 min / max / average luminance of the frame on screen.

    Level 1 is the one metadata level every RPU carries, so it needs no presence
    flag of its own: it is there for as long as an rpu has been parsed, and it
    describes the frame being shown rather than the title as a whole.  ``unit``
    picks the two ways Kodi reports it -- ``nits`` for the frame light level,
    ``pq`` for the raw 12-bit PQ codes it is derived from.

    Empty for a stream with no rpu, which is the overlay's cue to leave the row
    out entirely: nothing but Dolby Vision has these numbers.
    """
    if not _flag("video.dovi.has.header"):
        return ""
    return _triple(
        f"video.dovi.l1.min.{unit}",
        f"video.dovi.l1.max.{unit}",
        f"video.dovi.l1.avg.{unit}",
    )


def _bit_depth() -> str:
    """Return the source bit depth.

    A full enhancement layer reconstructs to 12-bit, which is what the overlay
    has always shown for one; Kodi reports the base layer it hands the decoder.
    """
    if _el_type() == "FEL":
        return "12"

    depth = _int("video.bit.depth")
    return str(depth) if depth else ""


def _dovi_flag(name: str) -> str:
    """Return ``true`` / ``false`` for a Dolby Vision presence flag, or ``''``
    for a stream that carries no Dolby Vision at all."""
    if not _is_dovi():
        return ""
    return "true" if _flag(name) else "false"


def _el_present() -> str:
    """Return enhancement-layer presence, from the source side so it survives a
    profile 7 to profile 8 conversion."""
    if not _is_dovi():
        return ""
    if _int("video.source.dovi.profile"):
        return "true" if _flag("video.source.dovi.el.present") else "false"
    return "true" if _flag("video.dovi.el.present") else "false"


def _dv_level() -> str:
    """Return the Dolby Vision level, or '' when the stream declares none."""
    level = _int("video.dovi.level")
    return str(level) if level else ""


def _dv_profile_number() -> str:
    """Return the bare Dolby Vision profile string (``7.6`` / ``8.1``)."""
    return _profile_label()


def _dv_el_type() -> str:
    """Return the enhancement-layer type, falling back to the profile number for
    a Dolby Vision stream without one (what the overlay shows in that slot)."""
    if not _is_dovi():
        return ""
    return _el_type() or _profile_label()


_FIELDS = {
    "hdr_format": _hdr_format,
    "output_mode": _output_mode,
    "cm_version": _cm_version,
    "structure": _structure,
    "l5_offsets": _l5_offsets,
    "l6_mdl": lambda: (
        _pair("video.dovi.l6.max.lum", "video.dovi.l6.min.lum")
        if _flag("video.dovi.has.l6") else ""
    ),
    "l6_max_cll_fall": lambda: (
        _pair("video.dovi.l6.max.cll", "video.dovi.l6.max.fall")
        if _flag("video.dovi.has.l6") else ""
    ),
    "hdr10_mdl": lambda: (
        _pair("video.hdr.max.lum", "video.hdr.min.lum")
        if _flag("video.hdr.has.mdcv") else ""
    ),
    "hdr10_max_cll_fall": lambda: (
        _pair("video.hdr.max.cll", "video.hdr.max.fall")
        if _flag("video.hdr.has.cll") else ""
    ),
    "l1_nits": lambda: _l1_frame_luminance("nits"),
    "l1_pq": lambda: _l1_frame_luminance("pq"),
    "dv_version": _dv_level,
    "dv_profile": _dv_profile_number,
    "dv_rpu_present": lambda: _dovi_flag("video.dovi.rpu.present"),
    "dv_bl_present": lambda: _dovi_flag("video.dovi.bl.present"),
    "dv_el_present": _el_present,
    "dv_el_type": _dv_el_type,
    "bit_depth": _bit_depth,
}

# The fields this module can answer at all; anything else (the audio track list)
# stays with the probes.
FIELDS = frozenset(_FIELDS)


def field(key: str) -> str:
    """Return one metadata field for the playing stream, or ``''``.

    Never blocks and never caches: every value is a live label read, so a stream
    whose metadata changes mid-playback -- an RPU arriving, a level 5 active
    area opening up -- is followed rather than frozen at the first reading.
    """
    reader = _FIELDS.get(key)
    if reader is None:
        return ""
    if key in PENDING_FIELDS and pending():
        return ""
    try:
        return reader()
    except Exception as exc:  # pragma: no cover - a label read must never throw
        xbmc.log(f"TinyPPI: live metadata field {key} failed: {exc}",
                 xbmc.LOGWARNING)
        return ""
