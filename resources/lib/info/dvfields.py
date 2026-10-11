# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Dolby Vision and HDR fields derived from parsed side data.

``build_info`` turns one frame's parsed side data and Kodi's HDR labels into
the string fields ``info.dvinfo`` serves; everything here is a pure
function of its arguments.
"""

import re

from info.dvformat import Block

# All fields; info.dvinfo's getters expose them one by one.
FIELDS = (
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

# Enhancement-layer types that get a tag (coloured by info.dvinfo).
EL_TAGS = ("FEL", "MEL")


def empty_info() -> dict[str, str]:
    """Return a complete empty field dict."""
    return dict.fromkeys(FIELDS, "")


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


def _format_el_tag(profile: str, el_type: str) -> str:
    """Return *profile* with an uncoloured FEL/MEL tag appended."""
    if el_type in EL_TAGS:
        return f"{profile} {el_type}".strip()
    return profile


# --- Field derivation ------------------------------------------------------

# A bare DV profile as reported by VideoPlayer.HdrDetail, e.g. ``8.1``.
_PROFILE_RE = re.compile(r"^\d{1,2}(?:\.\d{1,2})?$")

# Kodi's label words for each HDR token, checked in this order.
_LABEL_TOKENS = (
    ("dolbyvision", ("dolby", "dovi")),
    ("hdr10+",      ("hdr10plus", "hdr10+")),
    ("hlg",         ("hlg",)),
    ("hdr10",       ("hdr", "pq")),
)


def _hdr_token(label: str, parsed: Block) -> str:
    """Return the source HDR token: '', hdr10, hdr10+, hlg or dolbyvision.

    Kodi's label (from the container) is the only source for HLG.  The side
    data (from the bitstream) catches what the container does not signal,
    e.g. DV announced only in a Blu-ray playlist, or unflagged HDR10+.
    """
    low = (label or "").strip().lower()
    token = next((token for token, words in _LABEL_TOKENS
                  if any(word in low for word in words)), "")
    return token if token == "dolbyvision" else _side_data_token(token, parsed)


def _side_data_token(token: str, parsed: Block) -> str:
    """Return *token* (from Kodi's label) as the side data refines it."""
    if parsed.get("rpu") or parsed.get("config"):
        return "dolbyvision"
    if parsed.get("hdr10plus"):
        return "hdr10+"
    if not token and (parsed.get("mdcv") or parsed.get("cll")):
        return "hdr10"
    return token


def _dv_profile(hdr_detail: str, config: Block | None, rpu: Block | None) -> str:
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


def _hdr10plus_profile_label(hdr10plus: Block | None) -> str:
    """Return the HDR10+ profile, e.g. ``Profile B``, or ''."""
    profile = str((hdr10plus or {}).get("profile") or "").strip()
    return f"Profile {profile.upper()}" if profile else ""


def _output_mode(
    token: str, profile: str, el_type: str, hdr10plus: Block | None
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


def _cm_version(rpu: Block | None) -> str:
    """Return the CM version (``CMv4.0`` / ``CMv2.9``), or '' without DM data."""
    version = (rpu or {}).get("cm_version")
    return f"CMv{version}" if version else ""


def _structure_abbr(structure: object, config: Block | None, el_type: str) -> str:
    """Return the layer structure: ``ST-DL``, ``DT-DL`` or ``ST-SL``.

    Single/dual track, single/dual layer.  The side data names a structure
    only for dual-layer streams; profiles 5 and 8 fall back to ``ST-SL``.
    """
    if isinstance(structure, str) and structure.strip():
        track = "DT" if structure.strip().lower().startswith("dt") else "ST"
        return f"{track}-DL"
    dual = bool((config or {}).get("el_present")) or el_type in EL_TAGS
    return "ST-DL" if dual else "ST-SL"


def _dv_record_version(config: Block | None) -> str:
    """Return the dvcC/dvvC record version, e.g. ``1.0``, or ''.

    The record's own version, not the DV level (``config['level']``).
    """
    major = _fmt_num((config or {}).get("version_major"))
    minor = _fmt_num((config or {}).get("version_minor"))
    return f"{major}.{minor}" if major and minor else ""


def _presence(
    config: Block | None, rpu: Block | None, el_type: str
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
        return "true", "true", _present_flag(el_type in EL_TAGS)
    return "", "", ""


def _bit_depth(el_type: str) -> str:
    """Return ``12`` for a full enhancement layer, else ''.

    Other depths follow from the HDR type (see
    ``properties.get_VideoBitDepthVar``).
    """
    return "12" if el_type == "FEL" else ""


def build_info(parsed: Block, hdr_label: str, hdr_detail: str) -> dict[str, str]:
    """Turn one parse result into the overlay fields.

    Dolby Vision fills the RPU rows (L1, L5, L6, CM version, layers).  The
    static MDCV / CLL SEIs fill the HDR10 rows for any format, Dolby Vision
    included (its HDR10 fallback, shown apart from L6).  Missing blocks
    leave their rows empty (N/A).
    """
    info = empty_info()

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
        _dolby_vision_fields(info, parsed, profile, el_type)
    _rpu_fields(info, rpu or {})
    _static_fields(info, mdcv, cll)
    return info


def _dolby_vision_fields(info: dict[str, str], parsed: Block, profile: str,
                         el_type: str) -> None:
    """Fill the Dolby Vision rows: CM version, structure, profile, layers."""
    config = parsed.get("config")
    rpu    = parsed.get("rpu")
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


def _rpu_fields(info: dict[str, str], rpu: Block) -> None:
    """Fill the rows of the per-frame RPU blocks (L5, L1, L6, source)."""
    # L5 active area, L1 luminance in nits and PQ.
    l5 = rpu.get("l5")
    if l5:
        info["l5_offsets"] = _joined([
            _fmt_num(l5.get(edge)) for edge in ("left", "right", "top", "bottom")
        ])

    l1 = rpu.get("l1")
    if l1:
        info["l1_nits"] = _joined([
            _fmt_lum(l1.get(key)) for key in ("min_nits", "max_nits", "avg_nits")
        ])
        info["l1_pq"] = _joined([
            _fmt_num(l1.get(key)) for key in ("min_pq", "max_pq", "avg_pq")
        ])

    # L6: mastering display and content light declared in the RPU.
    l6 = rpu.get("l6")
    if l6:
        info["l6_mdl"] = _joined([
            _fmt_lum(l6.get("max_lum_nits")), _fmt_lum(l6.get("min_lum_nits")),
        ])
        info["l6_max_cll_fall"] = _joined([
            _fmt_num(l6.get("max_cll")), _fmt_num(l6.get("max_fall")),
        ])

    # The source master's PQ range as luminance; the MDL row prefers it over
    # L6.  Only in frames with uncompressed DM data (see _STATIC_FIELDS).
    source = rpu.get("source")
    if source:
        info["source_mdl"] = _joined([
            _fmt_lum(source.get("max_nits")), _fmt_lum(source.get("min_nits")),
        ])


def _static_fields(info: dict[str, str], mdcv: Block | None, cll: Block | None) -> None:
    """Fill the HDR10 rows from the static MDCV and CLL SEIs."""
    if mdcv:
        info["hdr10_mdl"] = _joined([
            _fmt_lum(mdcv.get("max_luminance")), _fmt_lum(mdcv.get("min_luminance")),
        ])
    if cll:
        info["hdr10_max_cll_fall"] = _joined([
            _fmt_num(cll.get("max_cll")), _fmt_num(cll.get("max_fall")),
        ])
