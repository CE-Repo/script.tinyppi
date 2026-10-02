# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Row model for the Dolby Vision metadata view.

Where ``dvinfo`` picks a few readings for the overlay, this module walks the
whole parse result of ``script.module.sidedata``: flags, structure, the
dvcC/dvvC record, every RPU block from the header to L255, the composer's
reshaping curves, the static MDCV / CLL SEIs and HDR10+.  It produces
``(kind, name, value)`` rows for ui.dvmetadata, without interpreting
anything.

The composer subtree is only parsed on request (see
``info.dvinfo.get_sidedata``), and its coefficients are the only derived
values: the RPU splits each into two halves (see ``_coefficient``).

Names, units and scalings follow the module's FIELDS.md.  Fields the stream
does not carry are dropped, and sections without fields with them.

Under DM metadata compression most frames omit blocks such as L2, L8 or the
source range, so the last received block is held until replaced (see
``_HeldBlocks``).  Given a parse result of its own, ``build_scene_rows`` holds
nothing and simply formats it.
"""

from functools import cache

import xbmc
import xbmcaddon

from info.dvinfo import get_sidedata

# Row kinds for ui.dvmetadata: a heading, a name / value pair, a full-width
# line, and an empty row.  Kodi lists scroll by a uniform item size, so the
# space above a heading is an empty row rather than a taller layout.
SECTION = "section"
ROW     = "row"
WIDE    = "wide"
SPACE   = "space"

# Table rows: column headings and readings, with cells as a list.  A
# proportional font cannot be padded into columns, so the skin draws each
# cell in a fixed slot.
HEADINGS = "headings"
COLUMNS  = "columns"

# Cells per table row: the 1195 px list holds a 235 px name column and six
# 160 px cells.  Wider levels (L8 has eight controls) continue in a second
# table below.
MAX_COLUMNS = 6

# Cells per row on the compact grid, used for nine-column tables such as the
# HDR10+ distribution.
MAX_COMPACT_COLUMNS = 9

# Internal marker for "no reading"; _section drops rows holding it.
EMPTY = "—"

# Origin of a section's block.  Only CACHED is shown, next to the heading of
# a section held from an earlier frame (see _HeldBlocks).
LIVE   = "Live"
CACHED = "Cached"

_SIDEDATA_ID = "script.module.sidedata"

# The playing item; held blocks belong to it (see _HeldBlocks).
_SOURCE_LABEL = "Player.FilenameAndPath"

# Separator in composite values ("2081 | 1000").
_JOIN = " | "

# HDR10+ maxRGB percentiles shown, in spec order.
_HDR10PLUS_PERCENTILES = (1, 5, 10, 25, 50, 75, 90, 95, 99)


# --- Value formatting ------------------------------------------------------

def _text(value) -> str:
    """Return *value* as a stripped string, or EMPTY."""
    if value is None:
        return EMPTY
    text = str(value).strip()
    return text or EMPTY


def _num(value) -> str:
    """Format a number without a redundant ``.0``, or EMPTY."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return EMPTY
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _lum(value) -> str:
    """Format a luminance in nits, like dvinfo (see ``dvinfo._fmt_lum``)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return EMPTY
    if value and abs(value) < 1.0:
        return f"{value:.4f}".rstrip("0").rstrip(".")
    return str(int(round(value)))


def _scaled(value) -> str:
    """Format a 0..1 or -1..1 value (UI trims, knee point), or EMPTY.

    EMPTY is also how a disabled trim control reads.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return EMPTY
    return f"{value:.4f}"


def _percent(value) -> str:
    """Format a percentage to one decimal, or EMPTY."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return EMPTY
    return f"{value:.1f} %"


def _flag(value) -> str:
    """Format a flag as Kodi's localized Yes / No, or EMPTY."""
    if value is None:
        return EMPTY
    return xbmc.getLocalizedString(107 if value else 106)


def _joined(*values: str) -> str:
    """Join the present parts of a composite value, or return EMPTY."""
    present = [value for value in values if value != EMPTY]
    return _JOIN.join(present) if present else EMPTY


def _coords(pair) -> str:
    """Format a CIE ``(x, y)`` pair of raw codes or floats."""
    if not isinstance(pair, (tuple, list)) or len(pair) != 2:
        return EMPTY
    x, y = pair
    if isinstance(x, float) or isinstance(y, float):
        return _joined(f"{x:.4f}", f"{y:.4f}")
    return _joined(_num(x), _num(y))


@cache
def _module_version() -> str:
    """Return the installed script.module.sidedata version, or EMPTY.

    Read once: the imported parser stays in use until the process ends.
    """
    try:
        version = xbmcaddon.Addon(_SIDEDATA_ID).getAddonInfo("version")
    except Exception:
        version = ""
    return version or EMPTY


# --- Sections --------------------------------------------------------------

def _section(rows: list, title: str, entries, state: str = "") -> None:
    """Append a heading and its entries to *rows*, skipping empty ones.

    An entry is a ``(name, value)`` pair or a full ``(kind, name, value)``
    triple.  Entries valued EMPTY are dropped, and the heading too when none
    remain.  Blank rows are kept only between readings.

    *state* (CACHED or '') becomes the heading row's value rather than part
    of the title, because the view remembers the viewer's position by title.
    """
    kept = [
        entry if len(entry) == 3 else (ROW, entry[0], entry[1])
        for entry in entries
    ]
    kept = [row for row in kept
            if row[0] == SPACE or (row[2] and row[2] != EMPTY)]
    while kept and kept[0][0] == SPACE:
        kept.pop(0)
    while kept and kept[-1][0] == SPACE:
        kept.pop()
    if not kept:
        return
    if rows:
        # Space before every heading but the first.
        rows.append((SPACE, f"space.{title}", ""))
    rows.append((SECTION, title, state))
    rows.extend(kept)


def _payload_summary(parsed: dict) -> str:
    """Name the sections the payload carried, e.g. ``config, rpu``, or EMPTY."""
    present = [
        key for key in ("config", "rpu", "hdr10plus", "mdcv", "cll")
        if parsed.get(key)
    ]
    return ", ".join(present) if present else EMPTY


def _stream_pairs(parsed: dict, carried: str) -> list:
    """Return Kodi's view of the stream and what the raw label delivered.

    *carried* names the sections in this frame's own payload, which may
    differ from the sections shown (some may be held, see _HeldBlocks).
    """
    flags = parsed.get("flags") or []
    return [
        ("HDR type (Kodi)", _text(xbmc.getInfoLabel("VideoPlayer.HdrType"))),
        ("HDR detail (Kodi)", _text(xbmc.getInfoLabel("VideoPlayer.HdrDetail"))),
        ("Side data", carried),
        ("Flags", ", ".join(flags) if flags else EMPTY),
        ("Structure", _text(parsed.get("structure"))),
        ("Parser module", _module_version()),
    ]


def _config_pairs(config: dict | None) -> list:
    """Return the dvcC / dvvC record rows (source profile even after 4/7 -> 8)."""
    config = config or {}
    major = _num(config.get("version_major"))
    minor = _num(config.get("version_minor"))
    version = EMPTY if EMPTY in (major, minor) else f"{major}.{minor}"
    return [
        ("Record version", version),
        ("Profile", _num(config.get("profile"))),
        ("Compatibility ID", _num(config.get("compat_id"))),
        ("Level", _num(config.get("level"))),
        ("RPU present", _flag(config.get("rpu_present"))),
        ("BL present", _flag(config.get("bl_present"))),
        ("EL present", _flag(config.get("el_present"))),
        ("MD compression", _num(config.get("md_compression"))),
    ]


def _rpu_pairs(rpu: dict | None) -> list:
    """Return the RPU header rows plus the guessed profile and compression.

    Compressed DM data is why the source range is often missing.
    """
    rpu = rpu or {}
    header = rpu.get("header") or {}
    return [
        ("Guessed profile", _num(rpu.get("profile"))),
        ("CM version", _text(rpu.get("cm_version"))),
        ("DM compression", _flag(rpu.get("compressed"))),
        # The DM metadata ids and scene refresh flag: how a compressed frame
        # refers back to earlier metadata, and where a scene starts.
        ("Affected DM metadata ID", _num(rpu.get("affected_dm_metadata_id"))),
        ("Current DM metadata ID", _num(rpu.get("current_dm_metadata_id"))),
        ("Scene refresh", _num(rpu.get("scene_refresh_flag"))),
        # Extension blocks declared across the CM v2.9 and v4.0 groups.
        ("Extension blocks", _num(rpu.get("num_ext_blocks"))),
        ("RPU type", _num(header.get("rpu_type"))),
        ("RPU format", _num(header.get("rpu_format"))),
        ("VDR RPU profile", _num(header.get("vdr_rpu_profile"))),
        ("VDR RPU level", _num(header.get("vdr_rpu_level"))),
        ("VDR RPU normalized IDC", _num(header.get("vdr_rpu_normalized_idc"))),
        # Presence flags for the sequence info (source of the bit depths) and
        # the DM metadata (source of the levels and the source range).
        ("VDR sequence info", _flag(header.get("vdr_seq_info_present_flag"))),
        ("VDR DM metadata", _flag(header.get("vdr_dm_metadata_present_flag"))),
        ("BL bit depth", _num(header.get("bl_bit_depth"))),
        ("EL bit depth", _num(header.get("el_bit_depth"))),
        ("VDR bit depth", _num(header.get("vdr_bit_depth"))),
        ("BL full range", _flag(header.get("bl_video_full_range_flag"))),
        ("EL type", _text(header.get("el_type"))),
        (
            "EL spatial resampling",
            _flag(header.get("el_spatial_resampling_filter_flag")),
        ),
        (
            "Spatial resampling",
            _flag(header.get("spatial_resampling_filter_flag")),
        ),
        (
            "Chroma resampling filter",
            _flag(header.get("chroma_resampling_explicit_filter_flag")),
        ),
        ("Residual disabled", _flag(header.get("disable_residual_flag"))),
        ("Coefficient data type", _num(header.get("coefficient_data_type"))),
        ("Coefficient log2 denom", _num(header.get("coefficient_log2_denom"))),
        ("Reuses previous VDR RPU", _flag(header.get("use_prev_vdr_rpu_flag"))),
        ("Previous VDR RPU ID", _num(header.get("prev_vdr_rpu_id"))),
        # Fields without meaning of their own (deprecated NAL prefix, reserved
        # bits), shown because the RPU carries them.
        ("RPU NAL prefix", _num(header.get("rpu_nal_prefix"))),
        ("Reserved (3 bits)", _num(header.get("reserved_zero_3bits"))),
    ]


def _l1_pairs(rpu: dict | None) -> list:
    """Return L1 frame luminance rows as PQ code and nits (per frame)."""
    l1 = (rpu or {}).get("l1") or {}
    return [
        (name, _joined(_num(l1.get(pq)), _lum(l1.get(nits))))
        for name, pq, nits in (
            ("Min (PQ | nits)", "min_pq", "min_nits"),
            ("Max (PQ | nits)", "max_pq", "max_nits"),
            ("Average (PQ | nits)", "avg_pq", "avg_nits"),
        )
    ]


def _source_pairs(rpu: dict | None) -> list:
    """Return the source master rows: PQ range and display size.

    Only frames with uncompressed DM data carry them.
    """
    source = (rpu or {}).get("source") or {}
    return [
        ("Min (PQ | nits)", _joined(_num(source.get("min_pq")),
                                    _lum(source.get("min_nits")))),
        ("Max (PQ | nits)", _joined(_num(source.get("max_pq")),
                                    _lum(source.get("max_nits")))),
        ("Display diagonal (in)", _num(source.get("diagonal"))),
    ]


# The colorimetry block's two 9-coefficient matrices as (field, row name);
# they share one table with the coefficient index as heading.
_COLORIMETRY_MATRICES = (
    ("ycc_to_rgb_coef", "YCC to RGB"),
    ("rgb_to_lms_coef", "RGB to LMS"),
)
# Name-column legend and headings for that table (compact grid).
_MATRIX_LEGEND  = "Matrix (raw)"
_MATRIX_COLUMNS = [str(index + 1) for index in range(MAX_COMPACT_COLUMNS)]


def _colorimetry_entries(rpu: dict | None) -> list:
    """Return the VDR DM signal description and colour matrices as raw codes.

    Only frames with uncompressed DM data carry them.
    """
    block = (rpu or {}).get("colorimetry") or {}
    entries: list = []

    matrices = [
        (name, [_num(value) for value in block.get(key) or []])
        for key, name in _COLORIMETRY_MATRICES
    ]
    matrices = [(name, cells) for name, cells in matrices
                if len(cells) == MAX_COMPACT_COLUMNS
                and not all(cell == EMPTY for cell in cells)]
    if matrices:
        entries.append((HEADINGS, _MATRIX_LEGEND, list(_MATRIX_COLUMNS)))
        entries.extend(
            (COLUMNS, name, ["" if cell == EMPTY else cell for cell in cells])
            for name, cells in matrices
        )
        # Space between the matrices and the signal description.
        entries.append((SPACE, "space.colorimetry", ""))

    offsets = block.get("ycc_to_rgb_offset") or []
    entries.extend([
        ("YCC to RGB offset",
         _joined(*(_num(value) for value in offsets)) if offsets else EMPTY),
        ("Signal EOTF", _num(block.get("signal_eotf"))),
        ("EOTF parameters",
         _joined(*(_num(block.get(f"signal_eotf_param{index}"))
                   for index in range(3)))),
        ("Signal bit depth", _num(block.get("signal_bit_depth"))),
        ("Colour space", _num(block.get("signal_color_space"))),
        ("Chroma format", _num(block.get("signal_chroma_format"))),
        ("Full range", _num(block.get("signal_full_range_flag"))),
    ])
    return entries


def _l3_pairs(rpu: dict | None) -> list:
    """Return the L3 PQ offset rows."""
    l3 = (rpu or {}).get("l3") or {}
    return [
        ("Min PQ offset", _num(l3.get("min_pq_offset"))),
        ("Max PQ offset", _num(l3.get("max_pq_offset"))),
        ("Average PQ offset", _num(l3.get("avg_pq_offset"))),
    ]


def _l4_pairs(rpu: dict | None) -> list:
    """Return the L4 temporal stability anchors as raw codes."""
    l4 = (rpu or {}).get("l4") or {}
    return [
        ("Anchor PQ", _num(l4.get("anchor_pq"))),
        ("Anchor power", _num(l4.get("anchor_power"))),
    ]


def _l5_pairs(rpu: dict | None) -> list:
    """Return the L5 active-area offsets of this frame."""
    l5 = (rpu or {}).get("l5") or {}
    return [
        (f"{edge.capitalize()} offset", _num(l5.get(edge)))
        for edge in ("left", "right", "top", "bottom")
    ]


def _l6_pairs(rpu: dict | None) -> list:
    """Return the L6 rows (the RPU's own declaration, not the static SEIs)."""
    l6 = (rpu or {}).get("l6") or {}
    return [
        ("MaxCLL", _num(l6.get("max_cll"))),
        ("MaxFALL", _num(l6.get("max_fall"))),
        ("Max luminance", _lum(l6.get("max_lum_nits"))),
        ("Min luminance", _lum(l6.get("min_lum_nits"))),
    ]


# Raw trim controls (12 bit, 2048 neutral) in Dolby's order, as (field,
# heading).  Each pass is one table row.
_TRIM_RAW = (
    ("slope",        "Slope"),
    ("offset",       "Offset"),
    ("power",        "Power"),
    ("chromaweight", "Chroma"),
    ("saturation",   "Saturation"),
    ("tonedetail",   "Detail"),
)
# L8 adds two controls, which takes it past MAX_COLUMNS.
_TRIM_RAW_L8 = _TRIM_RAW + (
    ("mid_contrast", "Mid contrast"),
    ("clip_trim",    "Clip trim"),
)
# The same pass on the Dolby UI's -1..1 scale; gain, lift and gamma derive
# from slope, offset and power.
_TRIM_UI = (
    ("gain",         "Gain"),
    ("lift",         "Lift"),
    ("gamma",        "Gamma"),
    ("chromaweight", "Chroma"),
    ("saturation",   "Saturation"),
    ("tonedetail",   "Detail"),
)

# L8's secondary trims, six readings each (``saturation_vector`` /
# ``hue_vector``), present only in L8 blocks of length 19 / 25.
_TRIM_VECTORS = (
    ("saturation_vector", "Legend (sat)"),
    ("hue_vector",        "Legend (hue)"),
)
# One column per vector field, named by position: the module documents them
# only as raw codes in bitstream order.
_VECTOR_FIELDS = tuple((index, f"Field {index + 1}") for index in range(6))

# Name-column legends of the heading rows.
_LEGEND_RAW   = "Legend (raw)"
_LEGEND_UI    = "Legend (UI)"
_LEGEND_BLOCK = "Legend (block)"

# The L8 block length, which decides which fields exist (mid contrast above
# 10, clip trim above 12, vectors above 18 / 24).  A separate table, since it
# describes the block rather than the grade.
_TRIM_BLOCK = (("length", "Length"),)

# Target displays whose trim passes are shown.  A full L8 has a dozen
# near-identical passes; these four reference points keep the table to one
# screen.
_TRIM_TARGETS = (100, 600, 1000, 2000)


def _target_nits(trim: dict) -> int | None:
    """Return the target display brightness of *trim* in whole nits, or None."""
    value = trim.get("nits")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(round(value))


def _target(trim: dict) -> str:
    """Name a pass by its target display brightness.

    The L10 index and raw target PQ code repeat the same information and are
    left out to keep the width for the cells.
    """
    return f"{_num(trim.get('nits'))} nits"


def _vector_block(trim: dict, key: str) -> dict:
    """Return an L8 vector of *trim* keyed by position, for ``_table``.

    Empty when the pass has none (older parser or short block).
    """
    vector = trim.get(key)
    if not isinstance(vector, (list, tuple)):
        return {}
    return dict(enumerate(vector))


def _table(legend: str, controls, trims: list, block_of, formatter) -> list:
    """Build one trim table: a heading row, then one row per pass.

    Only controls set by some pass get a column; unset cells are blank (a
    disabled trim), and passes setting nothing get no row.  More controls
    than ``MAX_COLUMNS`` continue in a second table.
    """
    used = [
        (key, heading) for key, heading in controls
        if any(formatter(block_of(trim).get(key)) != EMPTY for trim in trims)
    ]
    if not used:
        return []

    entries: list = []
    for start in range(0, len(used), MAX_COLUMNS):
        chunk = used[start:start + MAX_COLUMNS]
        if entries:
            entries.append((SPACE, f"space.{legend}.{start}", ""))
        entries.append((HEADINGS, legend, [heading for _key, heading in chunk]))
        for trim in trims:
            cells = [formatter(block_of(trim).get(key)) for key, _h in chunk]
            if all(cell == EMPTY for cell in cells):
                continue
            entries.append((COLUMNS, _target(trim),
                            ["" if cell == EMPTY else cell for cell in cells]))
    return entries


def _trim_entries(level: str, trims: list | None) -> list:
    """Return the trim passes of *level* (l2 / l8) as tables.

    Controls across, one row per target display.  Raw codes and the UI's
    -1..1 scale are separate tables; L8 adds one table per secondary vector
    and one for the block length.  Only passes for ``_TRIM_TARGETS`` are
    shown; nothing left means no section.
    """
    raw_controls = _TRIM_RAW_L8 if level == "l8" else _TRIM_RAW
    trims = [trim for trim in (trims or [])
             if _target_nits(trim) in _TRIM_TARGETS]
    entries: list = []

    tables = [
        (_LEGEND_RAW, raw_controls, lambda trim: trim, _num),
        (_LEGEND_UI, _TRIM_UI, lambda trim: trim.get("ui") or {}, _scaled),
    ]
    tables.extend(
        (legend, _VECTOR_FIELDS,
         lambda trim, key=key: _vector_block(trim, key), _num)
        for key, legend in (_TRIM_VECTORS if level == "l8" else ())
    )
    if level == "l8":
        tables.append((_LEGEND_BLOCK, _TRIM_BLOCK, lambda trim: trim, _num))

    for legend, controls, block_of, formatter in tables:
        table = _table(legend, controls, trims, block_of, formatter)
        if not table:
            continue
        if entries:
            # Space between the tables.
            entries.append((SPACE, f"space.{level}.{legend}", ""))
        entries.extend(table)
    return entries


def _l9_pairs(rpu: dict | None) -> list:
    """Return the L9 source primaries, with coordinates when present."""
    block = (rpu or {}).get("l9") or {}
    pairs = [
        ("Index", _num(block.get("index"))),
        ("Primaries", _text(block.get("name"))),
    ]
    coords = block.get("coords") or {}
    if coords:
        pairs.extend(
            (f"{key.capitalize()} (x | y)", _coords(coords.get(key)))
            for key in ("red", "green", "blue", "white")
        )
    # The length decides whether coordinates are present at all.
    pairs.append(("Block length", _num(block.get("length"))))
    return pairs


def _l10_pairs(targets: list | None) -> list:
    """Return one row per L10 target display with its primaries and PQ range."""
    pairs = []
    for target in targets or []:
        name = f"{_num(target.get('nits'))} nits"
        index = target.get("target_display_index")
        if index is not None:
            name += f" (#{_num(index)})"
        readings = []
        primary = _text(target.get("primary_name"))
        if primary != EMPTY:
            readings.append(primary)
        for label, key in (("max PQ", "target_max_pq"),
                           ("min PQ", "target_min_pq"),
                           ("length", "length")):
            reading = _num(target.get(key))
            if reading != EMPTY:
                readings.append(f"{label} {reading}")
        if readings:
            pairs.append((name, "  ".join(readings)))
    return pairs


def _l11_pairs(rpu: dict | None) -> list:
    """Return the L11 content type and whitepoint rows."""
    l11 = (rpu or {}).get("l11") or {}
    return [
        ("Content type", _text(l11.get("content_type_name"))),
        ("Whitepoint", _text(l11.get("whitepoint_name"))),
        ("Reference mode", _flag(l11.get("reference_mode"))),
        ("Reserved bytes", _joined(_num(l11.get("reserved_byte2")),
                                   _num(l11.get("reserved_byte3")))),
    ]


def _l254_pairs(rpu: dict | None) -> list:
    """Return the L254 (CM v4.0 marker) raw codes."""
    l254 = (rpu or {}).get("l254") or {}
    return [
        ("DM mode", _num(l254.get("dm_mode"))),
        ("DM version index", _num(l254.get("dm_version_index"))),
    ]


def _l255_pairs(rpu: dict | None) -> list:
    """Return the L255 debug run mode rows (rare in encoded content)."""
    l255 = (rpu or {}).get("l255") or {}
    return [
        ("Run mode", _num(l255.get("dm_run_mode"))),
        ("Run version", _num(l255.get("dm_run_version"))),
        ("Debug", _joined(*(_num(l255.get(f"dm_debug{index}"))
                            for index in range(4)))),
    ]


# --- Composer (RPU data mapping) -------------------------------------------

# The three reshaping curves in module order, named by component; also the
# NLQ table's columns.
_CURVE_COMPONENTS = ("Y", "Cb", "Cr")

# Curve shapes by ``mapping_idc``; unknown codes are shown as is.
_MAPPING_IDC_NAMES = {0: "Polynomial", 1: "MMR"}

# Composer table legends and leading columns: polynomial segments start
# with order and interpolation, MMR segments with order and constant.
_LEGEND_SEGMENT   = "Segment"
_LEGEND_TERM      = "Term"
_LEGEND_COMPONENT = "Component"
_POLY_HEADINGS    = ("Order", "Linear interp")
_MMR_HEADINGS     = ("Order", "Constant")


def _coefficient(int_part, frac_part, denom) -> str:
    """Combine a composer coefficient's halves as the decoder does.

    ``int_part + frac_part / 2 ** coefficient_log2_denom`` -- the RPU
    syntax's own arithmetic, the only derived value in the view.  EMPTY
    without the header's denominator.
    """
    if isinstance(denom, bool) or not isinstance(denom, int) or denom < 0:
        return EMPTY
    if isinstance(int_part, bool) or not isinstance(int_part, int):
        return EMPTY
    if isinstance(frac_part, bool) or not isinstance(frac_part, int):
        frac_part = 0
    return f"{int_part + frac_part / float(1 << denom):.6g}"


def _grid(legend: str, headings, rows) -> list:
    """Lay out *rows* (``(name, cells)``) as a table under *headings*.

    Empty rows are dropped; more headings than ``MAX_COLUMNS`` continue in a
    second table.  Short rows are padded to the heading width so
    ui.dvmetadata._paint can right-align narrow tables and keep each reading
    under its heading.
    """
    entries: list = []
    for start in range(0, len(headings), MAX_COLUMNS):
        stop  = start + MAX_COLUMNS
        chunk = list(headings[start:stop])
        body  = []
        for name, cells in rows:
            part = ["" if cell == EMPTY else cell for cell in cells[start:stop]]
            if any(part):
                body.append((COLUMNS, name, part + [""] * (len(chunk) - len(part))))
        if not body:
            continue
        if entries:
            entries.append((SPACE, f"space.{legend}.{start}", ""))
        entries.append((HEADINGS, legend, chunk))
        entries.extend(body)
    return entries


def _mapping(rpu: dict | None) -> dict:
    """Return the RPU's composer data, or {}.

    Only parsed while the metadata view asks for it (see
    ``info.dvinfo.get_sidedata``) and missing before sidedata 1.6.0; the
    composer sections then drop out.
    """
    return (rpu or {}).get("data_mapping") or {}


def _denominator(rpu: dict | None):
    """Return the header's ``coefficient_log2_denom``."""
    return ((rpu or {}).get("header") or {}).get("coefficient_log2_denom")


def _composer_pairs(rpu: dict | None) -> list:
    """Return the composer scalars: RPU id, colour space, partitions, NLQ."""
    mapping = _mapping(rpu)
    pivots  = mapping.get("nlq_pred_pivot_value") or []
    return [
        ("VDR RPU ID", _num(mapping.get("vdr_rpu_id"))),
        ("Mapping colour space", _num(mapping.get("mapping_color_space"))),
        ("Mapping chroma format",
         _num(mapping.get("mapping_chroma_format_idc"))),
        ("Partitions (x | y)", _joined(_num(mapping.get("num_x_partitions")),
                                       _num(mapping.get("num_y_partitions")))),
        ("NLQ method", _num(mapping.get("nlq_method_idc"))),
        ("NLQ pivots", _num(mapping.get("nlq_num_pivots"))),
        ("NLQ pivot values", _joined(*(_num(value) for value in pivots))),
    ]


def _polynomial_entries(polynomial: dict | None, denom) -> list:
    """Return a polynomial curve as a table, one segment per row.

    Order and linear-interpolation flag first, then the coefficients from
    the lowest order up.
    """
    polynomial = polynomial or {}
    orders     = polynomial.get("poly_order") or []
    interp     = polynomial.get("linear_interp_flag") or []
    coef_int   = polynomial.get("poly_coef_int") or []
    coef_frac  = polynomial.get("poly_coef") or []

    width    = max((len(terms) for terms in coef_int), default=0)
    headings = list(_POLY_HEADINGS) + [f"c{term}" for term in range(width)]
    rows     = []
    for segment in range(max(len(orders), len(coef_int))):
        ints  = coef_int[segment] if segment < len(coef_int) else []
        fracs = coef_frac[segment] if segment < len(coef_frac) else []
        cells = [
            _num(orders[segment]) if segment < len(orders) else EMPTY,
            _flag(interp[segment]) if segment < len(interp) else EMPTY,
        ]
        cells.extend(
            _coefficient(value, fracs[term] if term < len(fracs) else 0, denom)
            for term, value in enumerate(ints)
        )
        rows.append((f"Segment {segment + 1}", cells))
    return _grid(_LEGEND_SEGMENT, headings, rows)


def _mmr_entries(mmr: dict | None, denom) -> list:
    """Return an MMR curve as two tables.

    First one row per segment (order, constant), then one row per order
    level of coefficients, since higher orders add product terms.  Terms are
    named by position only, as the module documents them.
    """
    mmr        = mmr or {}
    orders     = mmr.get("mmr_order") or []
    const_int  = mmr.get("mmr_constant_int") or []
    const_frac = mmr.get("mmr_constant") or []
    coef_int   = mmr.get("mmr_coef_int") or []
    coef_frac  = mmr.get("mmr_coef") or []

    segments  = max(len(orders), len(const_int), len(coef_int))
    head_rows = []
    coef_rows = []
    width     = 0
    for segment in range(segments):
        head_rows.append((f"Segment {segment + 1}", [
            _num(orders[segment]) if segment < len(orders) else EMPTY,
            _coefficient(
                const_int[segment] if segment < len(const_int) else None,
                const_frac[segment] if segment < len(const_frac) else 0,
                denom,
            ),
        ]))
        levels = coef_int[segment] if segment < len(coef_int) else []
        fracs  = coef_frac[segment] if segment < len(coef_frac) else []
        for level, ints in enumerate(levels):
            row   = fracs[level] if level < len(fracs) else []
            width = max(width, len(ints))
            # With one segment (the usual case) the segment is not named.
            name  = (f"Order {level + 1}" if segments == 1 else
                     f"Segment {segment + 1} · order {level + 1}")
            coef_rows.append((name, [
                _coefficient(value, row[term] if term < len(row) else 0, denom)
                for term, value in enumerate(ints)
            ]))

    entries = _grid(_LEGEND_SEGMENT, list(_MMR_HEADINGS), head_rows)
    terms   = _grid(_LEGEND_TERM,
                    [str(term + 1) for term in range(width)], coef_rows)
    if entries and terms:
        # Space between the two tables.
        entries.append((SPACE, "space.mmr", ""))
    entries.extend(terms)
    return entries


def _curve_entries(rpu: dict | None, index: int) -> list:
    """Return one component's curve: shape, pivots and coefficients."""
    curves = _mapping(rpu).get("curves") or []
    curve  = (curves[index] if index < len(curves) else None) or {}
    if not curve:
        return []

    idc     = curve.get("mapping_idc")
    pivots  = curve.get("pivots") or []
    entries: list = [
        ("Shape", _text(_MAPPING_IDC_NAMES.get(idc, _num(idc)))),
        ("Pivots", _num(curve.get("num_pivots"))),
        ("Pivot codewords", _joined(*(_num(value) for value in pivots))),
    ]

    denom = _denominator(rpu)
    table = (_polynomial_entries(curve.get("polynomial"), denom) +
             _mmr_entries(curve.get("mmr"), denom))
    if table:
        entries.append((SPACE, f"space.curve.{index}", ""))
        entries.extend(table)
    return entries


def _nlq_entries(rpu: dict | None) -> list:
    """Return the NLQ dequantization data, one column per component.

    Dual-layer profiles (4 and 7) only.
    """
    nlq = _mapping(rpu).get("nlq") or {}
    if not nlq:
        return []

    denom = _denominator(rpu)
    rows  = [("Offset", [_num(value) for value in nlq.get("nlq_offset") or []])]
    for name, int_key, frac_key in (
        ("VDR in max", "vdr_in_max_int", "vdr_in_max"),
        ("Deadzone slope",
         "linear_deadzone_slope_int", "linear_deadzone_slope"),
        ("Deadzone threshold",
         "linear_deadzone_threshold_int", "linear_deadzone_threshold"),
    ):
        ints  = nlq.get(int_key) or []
        fracs = nlq.get(frac_key) or []
        rows.append((name, [
            _coefficient(value, fracs[at] if at < len(fracs) else 0, denom)
            for at, value in enumerate(ints)
        ]))
    return _grid(_LEGEND_COMPONENT, list(_CURVE_COMPONENTS), rows)


def _static_pairs(mdcv: dict | None, cll: dict | None) -> list:
    """Return the static MDCV / CLL rows, kept apart from L6 (they can differ)."""
    mdcv = mdcv or {}
    cll  = cll or {}
    primaries = mdcv.get("primaries") or {}
    pairs = [
        ("Max luminance", _lum(mdcv.get("max_luminance"))),
        ("Min luminance", _lum(mdcv.get("min_luminance"))),
        ("Primaries", _text(primaries.get("name"))),
    ]
    if primaries:
        pairs.extend(
            (f"{key.capitalize()} (x | y)", _coords(primaries.get(key)))
            for key in ("red", "green", "blue")
        )
    pairs.extend((
        ("White point (x | y)", _coords(mdcv.get("white_point"))),
        ("MaxCLL", _num(cll.get("max_cll"))),
        ("MaxFALL", _num(cll.get("max_fall"))),
    ))
    return pairs


def _hdr10plus_pairs(hdr10plus: dict) -> list:
    """Return the HDR10+ (ST 2094-40) rows."""
    maxscl = hdr10plus.get("maxscl") or []
    profile_b = hdr10plus.get("profile") == "B"
    anchors = hdr10plus.get("bezier_anchors") or []
    distribution = {
        entry.get("percentage"): entry.get("nits")
        for entry in hdr10plus.get("distribution") or []
    }
    pairs = [
        ("Profile", _text(hdr10plus.get("profile"))),
        ("Application version", _num(hdr10plus.get("application_version"))),
        ("Windows", _num(hdr10plus.get("num_windows"))),
        (
            "Target display (nits)",
            _lum(hdr10plus.get("targeted_system_display_maximum_luminance")),
        ),
        (
            "MaxSCL (R | G | B)",
            _joined(*(_lum(value) for value in maxscl)) if maxscl else EMPTY,
        ),
        ("Average maxRGB", _lum(hdr10plus.get("average_maxrgb"))),
        ("Bright pixels", _percent(hdr10plus.get("fraction_bright_pixels"))),
    ]
    if profile_b:
        pairs.extend((
            ("Knee point (x | y)",
             _joined(_scaled(hdr10plus.get("knee_point_x")),
                     _scaled(hdr10plus.get("knee_point_y")))),
            ("Bézier anchors", " ".join(_num(value) for value in anchors)
                               or EMPTY),
        ))
    # The nine maxRGB percentiles as one compact table; ui.dvmetadata picks
    # the compact grid from the cell count.
    percentile_values = []
    for percent in _HDR10PLUS_PERCENTILES:
        value = _lum(distribution.get(percent))
        percentile_values.append("" if value == EMPTY else value)
    if any(percentile_values):
        pairs.extend((
            (HEADINGS, "Distribution",
             [f"{percent}%" for percent in _HDR10PLUS_PERCENTILES]),
            (COLUMNS, "maxRGB (nits)", percentile_values),
        ))
    return pairs


# --- Held blocks -----------------------------------------------------------

# Blocks that may be held from earlier frames, top-level and inside the RPU.
# With DM compression they arrive once and stay valid until replaced.  Held
# per block, never per field: a missing control in a present block is a
# disabled one.
_HELD_TOP = ("config", "rpu", "mdcv", "cll", "hdr10plus")
_HELD_RPU = ("header", "data_mapping", "source", "colorimetry", "l1", "l2",
             "l3", "l4", "l5", "l6", "l8", "l9", "l10", "l11", "l254", "l255")

class _HeldBlocks:
    """The last blocks seen, and the item they belong to.

    A new item clears them.  Only the metadata view's refresh uses these.
    """

    def __init__(self) -> None:
        self._blocks: dict = {}
        self._source: str | None = None

    def _fill_in(self, current: dict, names: tuple,
                 prefix: str) -> tuple[dict, dict]:
        """Fill omitted blocks of *current* and remember present ones.

        Also returns each block's origin: LIVE, CACHED, or no entry when
        neither has it.
        """
        held = self._blocks
        filled: dict = dict(current)
        origin: dict = {}
        for name in names:
            block = current.get(name)
            key   = prefix + name
            if block:
                held[key]    = block
                origin[key]  = LIVE
            elif held.get(key) is not None:
                filled[name] = held[key]
                origin[key]  = CACHED
        return filled, origin

    def hold(self, parsed: dict) -> tuple[dict, dict]:
        """Fill *parsed* with the blocks this frame does not repeat.

        Keeps sections such as the L2 / L8 trims from blinking out between
        frames; a new block still replaces the held one.  Also returns the
        origin map, so headings can mark held sections as Cached.  A change
        of item (or the end of playback) clears the held blocks.
        """
        source = xbmc.getInfoLabel(_SOURCE_LABEL)
        if source != self._source:
            self._blocks.clear()
            self._source = source

        parsed, origin = self._fill_in(parsed, _HELD_TOP, "")
        rpu = parsed.get("rpu")
        if isinstance(rpu, dict):
            filled, inside = self._fill_in(rpu, _HELD_RPU, "rpu.")
            # Hold the filled RPU, so a frame without any RPU still gets
            # every block.
            parsed["rpu"] = self._blocks["rpu"] = filled
            if origin.get("rpu") == CACHED:
                # No RPU in this frame: every block in it is held.
                inside = dict.fromkeys(inside, CACHED)
            origin.update(inside)
        return parsed, origin


_held = _HeldBlocks()


def _state(origin: dict, *keys: str) -> str:
    """Return CACHED when every block of a section was held, else ''."""
    seen = [origin[key] for key in keys if key in origin]
    return CACHED if seen and all(state == CACHED for state in seen) else ""


# --- Row model -------------------------------------------------------------

def build_scene_rows(
    parsed: dict | None = None,
) -> tuple[list[tuple[str, str, str]], dict, dict, str]:
    """Return the per-scene rows plus what ``build_static_rows`` needs.

    Returns ``(rows, parsed, origin, carried)``.  The scene rows (L1, L2,
    L8, L5, L3, L4, HDR10+) change during playback and are rebuilt on every
    poll.  Reads the live side data, holding omitted blocks (see _HeldBlocks),
    unless *parsed* is given, which is used as is.
    """
    live   = parsed is None
    # Request the composer data too (see info.dvinfo).
    parsed = get_sidedata(mapping=True) if live else parsed
    parsed = parsed if isinstance(parsed, dict) else {}

    # Summarise this frame's own payload before held blocks are added.
    carried = _payload_summary(parsed)
    origin: dict = {}
    if live:
        parsed, origin = _held.hold(parsed)

    rpu = parsed.get("rpu")
    rows: list[tuple[str, str, str]] = []

    # Per-frame blocks first, the most watched (L1, L2, L8) on top.
    _section(rows, "L1 — Frame luminance", _l1_pairs(rpu),
             _state(origin, "rpu.l1"))
    _section(rows, "L2 — Trims", _trim_entries("l2", (rpu or {}).get("l2")),
             _state(origin, "rpu.l2"))
    _section(rows, "L8 — Trims", _trim_entries("l8", (rpu or {}).get("l8")),
             _state(origin, "rpu.l8"))
    _section(rows, "L5 — Active area", _l5_pairs(rpu), _state(origin, "rpu.l5"))
    _section(rows, "L3 — PQ offsets", _l3_pairs(rpu), _state(origin, "rpu.l3"))
    _section(rows, "L4 — Temporal stability", _l4_pairs(rpu),
             _state(origin, "rpu.l4"))
    hdr10plus = parsed.get("hdr10plus")
    if hdr10plus:
        # Dynamic per scene, so it belongs with the scene rows.
        _section(rows, "HDR10+ (ST 2094-40)", _hdr10plus_pairs(hdr10plus),
                 _state(origin, "hdr10plus"))

    return rows, parsed, origin, carried


def build_static_rows(parsed: dict, origin: dict, carried: str) -> list[tuple[str, str, str]]:
    """Return the per-title rows from ``build_scene_rows``'s results.

    Source master, colorimetry, L6, L9-L11, L254, L255, static SEIs, RPU
    header, composer and file-level blocks rarely change, so callers may
    rebuild them less often; their Cached badges then reflect the frame they
    were built from.

    No leading blank row: ``join_rows`` decides that against the current
    scene rows, which may differ from the ones current when this was built.
    """
    rpu = parsed.get("rpu")
    rows: list[tuple[str, str, str]] = []

    # The grade.  The source range belongs here: it describes the master.
    _section(rows, "Source master", _source_pairs(rpu),
             _state(origin, "rpu.source"))
    _section(rows, "Colorimetry (VDR DM)", _colorimetry_entries(rpu),
             _state(origin, "rpu.colorimetry"))
    _section(rows, "L6 — RPU mastering display", _l6_pairs(rpu),
             _state(origin, "rpu.l6"))
    _section(rows, "L9 — Source primaries", _l9_pairs(rpu),
             _state(origin, "rpu.l9"))
    _section(rows, "L10 — Target displays", _l10_pairs((rpu or {}).get("l10")),
             _state(origin, "rpu.l10"))
    _section(rows, "L11 — Content type", _l11_pairs(rpu),
             _state(origin, "rpu.l11"))
    _section(rows, "L254 — CM v4.0", _l254_pairs(rpu),
             _state(origin, "rpu.l254"))
    _section(rows, "L255 — Debug run mode", _l255_pairs(rpu),
             _state(origin, "rpu.l255"))
    _section(rows, "Static metadata (MDCV / CLL)",
             _static_pairs(parsed.get("mdcv"), parsed.get("cll")),
             _state(origin, "mdcv", "cll"))

    # File-level facts last, so the readings come first.  The RPU section is
    # the header plus the scalars next to it.
    _section(rows, "RPU", _rpu_pairs(rpu),
             _state(origin, "rpu", "rpu.header"))

    # The composer, which reconstructs the picture from the base layer (not
    # a level, so it follows the header).  Only present when requested (see
    # info.dvinfo.get_sidedata).
    _section(rows, "Composer — Data mapping", _composer_pairs(rpu),
             _state(origin, "rpu.data_mapping"))
    for index, component in enumerate(_CURVE_COMPONENTS):
        _section(rows, f"Composer — {component} curve",
                 _curve_entries(rpu, index),
                 _state(origin, "rpu.data_mapping"))
    _section(rows, "Composer — NLQ", _nlq_entries(rpu),
             _state(origin, "rpu.data_mapping"))

    _section(rows, "Configuration record (dvcC / dvvC)",
             _config_pairs(parsed.get("config")), _state(origin, "config"))
    _section(rows, "Stream", _stream_pairs(parsed, carried))

    return rows


# Origin keys behind build_static_rows's Cached badges.
_STATIC_STATE_KEYS = ("rpu.source", "rpu.colorimetry", "rpu.l6", "rpu.l9",
                      "rpu.l10", "rpu.l11", "rpu.l254", "rpu.l255", "mdcv",
                      "cll", "rpu", "rpu.header", "rpu.data_mapping", "config")


def static_signature(parsed: dict, origin: dict, carried: str) -> tuple:
    """Return a comparable value of what ``build_static_rows`` reads.

    Lets a caller (ui.dvmetadata's ``_merged_rows``) rebuild the static rows
    as soon as a block changes rather than on its slow interval; an
    unchanged tick costs one comparison.

    Includes the heading states and the composer data (which a stream may
    re-send per shot).  Deliberately excludes the Stream section's live
    reads and the per-frame RPU scalars (compression and scene refresh flip
    constantly); those rows update on the caller's slow interval.
    """
    rpu = parsed.get("rpu") or {}
    return (
        carried,
        parsed.get("flags"),
        parsed.get("structure"),
        parsed.get("config"),
        parsed.get("mdcv"),
        parsed.get("cll"),
        rpu.get("header"),
        rpu.get("data_mapping"),
        rpu.get("source"),
        rpu.get("colorimetry"),
        rpu.get("l6"),
        rpu.get("l9"),
        rpu.get("l10"),
        rpu.get("l11"),
        rpu.get("l254"),
        rpu.get("l255"),
        tuple(origin.get(key) for key in _STATIC_STATE_KEYS),
    )


def join_rows(
    scene_rows: list[tuple[str, str, str]], static_rows: list[tuple[str, str, str]],
) -> list[tuple[str, str, str]]:
    """Concatenate scene and static rows, with a blank row between them.

    Decided here against the current scene rows, since the two halves may
    be rebuilt at different times.
    """
    if scene_rows and static_rows:
        static_rows = [(SPACE, f"space.{static_rows[0][1]}", "")] + static_rows
    return scene_rows + static_rows
