"""Live Dolby Vision / HDR metadata from CoreELEC's player.

CoreELEC/xbmc PR #68 exposes the metadata already parsed by the Amlogic video
decoder as ``Player.Process(...)`` InfoLabels.  The L1 and L5 values follow the
presented frame; the remaining values are stream metadata.  TinyPPI reads only
the fields that PR #68 actually publishes here.  In particular, this module
does not build the overlay's Output mode -- that line deliberately remains on
the existing hdrprobe path in :mod:`info.dvinfo`.

An absent metadata level resolves to an empty string.  The API-version label is
the feature probe: it always returns a value on a build containing PR #68,
including while no Dolby Vision video is playing.
"""

import xbmc

from core.utils import clean, info


_API_LABEL = "video.dovi.apiversion"
_supported = False


def _label(name: str) -> str:
    """Return one ``Player.Process`` InfoLabel, stripped."""
    return clean(info(f"Player.Process({name})")).strip()


def _num(name: str) -> str:
    """Return a numeric label unchanged, or ``''`` when it is unavailable."""
    value = _label(name)
    if not value:
        return ""
    try:
        float(value)
    except ValueError:
        return ""
    return value


def _pair(first: str, second: str) -> str:
    """Return ``"<a> | <b>"`` when both numeric labels are available."""
    values = (_num(first), _num(second))
    return " | ".join(values) if all(values) else ""


def _triple(first: str, second: str, third: str) -> str:
    """Return ``"<a> | <b> | <c>"`` when all labels are available."""
    values = (_num(first), _num(second), _num(third))
    return " | ".join(values) if all(values) else ""


def available() -> bool:
    """Return whether this Kodi build contains the PR #68 label interface."""
    global _supported

    if _supported:
        return True
    _supported = bool(_label(_API_LABEL))
    return _supported


def _profile() -> str:
    """Return the source Dolby Vision profile, including compatibility id."""
    return _label("video.dovi.profile")


def _el_type() -> str:
    """Return ``FEL`` / ``MEL`` for a profile 7 enhancement layer."""
    value = _label("video.dovi.el.type").upper()
    return value if value in ("FEL", "MEL") else ""


def _display_el_type() -> str:
    """Match TinyPPI's old field shape: EL type, otherwise DV profile."""
    return _el_type() or _profile()


def _cm_version() -> str:
    """Return the creative metadata version in TinyPPI's ``CMvX.Y`` form."""
    value = _label("video.dovi.meta.version")
    if value in ("2.9", "4.0"):
        return f"CMv{value}"
    return value if value.lower().startswith("cmv") else ""


def _source_mdl() -> str:
    """Return the RPU source mastering bounds as ``min | max`` nits."""
    return _pair(
        "video.dovi.source.min.nits",
        "video.dovi.source.max.nits",
    )


def _l1_frame_luminance(unit: str) -> str:
    """Return the current frame's L1 ``min | max | average`` values."""
    return _triple(
        f"video.dovi.l1.min.{unit}",
        f"video.dovi.l1.max.{unit}",
        f"video.dovi.l1.avg.{unit}",
    )


def _l5_offsets() -> str:
    """Return the current frame's L5 offsets as ``left | right | top | bottom``."""
    values = tuple(
        _num(f"video.dovi.l5.{edge}.offset")
        for edge in ("left", "right", "top", "bottom")
    )
    return " | ".join(values) if all(values) else ""


_FIELDS = {
    # These values previously came from hdrprobe.  They now come exclusively
    # from PR #68 when its API is available.  Output mode is intentionally not
    # present: it must continue to use hdrprobe unchanged.
    "cm_version": _cm_version,
    "l5_offsets": _l5_offsets,
    "l6_mdl": _source_mdl,
    "l6_max_cll_fall": lambda: _pair(
        "video.dovi.l6.max.cll",
        "video.dovi.l6.max.fall",
    ),
    "hdr10_mdl": lambda: _pair(
        "video.hdr.min.lum",
        "video.hdr.max.lum",
    ),
    "hdr10_max_cll_fall": lambda: _pair(
        "video.hdr.max.cll",
        "video.hdr.max.fall",
    ),
    "l1_nits": lambda: _l1_frame_luminance("nits"),
    "l1_pq": lambda: _l1_frame_luminance("pq"),
    "dv_profile": _profile,
    "dv_el_type": _display_el_type,
}

FIELDS = frozenset(_FIELDS)


def field(key: str) -> str:
    """Return one live metadata field, or ``''`` when it is absent."""
    reader = _FIELDS.get(key)
    if reader is None:
        return ""
    try:
        return reader()
    except Exception as exc:  # pragma: no cover - Kodi label reads must not fail
        xbmc.log(
            f"TinyPPI: live metadata field {key} failed: {exc}",
            xbmc.LOGWARNING,
        )
        return ""


def get_hdr_type() -> str:
    """Expose stock ``VideoPlayer.HdrType`` without using it in TinyPPI."""
    return clean(info("VideoPlayer.HdrType")).strip()


def get_hdr_detail() -> str:
    """Expose stock ``VideoPlayer.HdrDetail`` without using it in TinyPPI."""
    return clean(info("VideoPlayer.HdrDetail")).strip()
