# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Entries of the Dolby Vision metadata view's per-block sections.

One builder per block of the parse result: the RPU levels L1 to L255 with
the L2 / L8 trim tables, the source master and colorimetry, the static
MDCV / CLL SEIs and HDR10+.  Each returns ``(name, value)`` pairs or full
``(kind, name, value)`` rows; ``info.dvmetadata`` arranges them into
sections.  Names, units and scalings follow the parser module's FIELDS.md.
"""

from collections.abc import Callable, Sequence
from functools import partial

from info import dvformat as fmt
from info.dvformat import (
    COLUMNS,
    EMPTY,
    HEADINGS,
    MAX_COLUMNS,
    MAX_COMPACT_COLUMNS,
    SPACE,
    Block,
    Entry,
    Pair,
)

# HDR10+ maxRGB percentiles shown, in spec order.
_HDR10PLUS_PERCENTILES = (1, 5, 10, 25, 50, 75, 90, 95, 99)


def l1_pairs(rpu: Block | None) -> list[Pair]:
    """Return L1 frame luminance rows as PQ code and nits (per frame)."""
    l1 = (rpu or {}).get("l1") or {}
    return [
        (name, fmt.joined(fmt.num(l1.get(pq)), fmt.lum(l1.get(nits))))
        for name, pq, nits in (
            ("Min (PQ | nits)", "min_pq", "min_nits"),
            ("Max (PQ | nits)", "max_pq", "max_nits"),
            ("Average (PQ | nits)", "avg_pq", "avg_nits"),
        )
    ]


def source_pairs(rpu: Block | None) -> list[Pair]:
    """Return the source master rows: PQ range and display size.

    Only frames with uncompressed DM data carry them.
    """
    source = (rpu or {}).get("source") or {}
    return [
        ("Min (PQ | nits)", fmt.joined(fmt.num(source.get("min_pq")),
                                    fmt.lum(source.get("min_nits")))),
        ("Max (PQ | nits)", fmt.joined(fmt.num(source.get("max_pq")),
                                    fmt.lum(source.get("max_nits")))),
        ("Display diagonal (in)", fmt.num(source.get("diagonal"))),
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


def _unset(cells: list[str]) -> bool:
    """Return whether every cell of a table row is unset."""
    return all(cell == EMPTY for cell in cells)


def _blanked(cells: list[str]) -> list[str]:
    """Return a table row with unset cells blank, as tables show them."""
    return ["" if cell == EMPTY else cell for cell in cells]


def colorimetry_entries(rpu: Block | None) -> list[Entry]:
    """Return the VDR DM signal description and colour matrices as raw codes.

    Only frames with uncompressed DM data carry them.
    """
    block = (rpu or {}).get("colorimetry") or {}
    return _matrix_entries(block) + _signal_pairs(block)


def _matrix_entries(block: Block) -> list[Entry]:
    """Return the colour matrices as a compact table, or [] without any."""
    matrices = [
        (name, [fmt.num(value) for value in block.get(key) or []])
        for key, name in _COLORIMETRY_MATRICES
    ]
    matrices = [(name, cells) for name, cells in matrices
                if len(cells) == MAX_COMPACT_COLUMNS and not _unset(cells)]
    if not matrices:
        return []
    entries: list[Entry] = [(HEADINGS, _MATRIX_LEGEND, list(_MATRIX_COLUMNS))]
    entries.extend((COLUMNS, name, _blanked(cells)) for name, cells in matrices)
    # Space between the matrices and the signal description.
    entries.append((SPACE, "space.colorimetry", ""))
    return entries


def _signal_pairs(block: Block) -> list[Pair]:
    """Return the signal description rows."""
    offsets = block.get("ycc_to_rgb_offset") or []
    return [
        ("YCC to RGB offset",
         fmt.joined(*(fmt.num(value) for value in offsets)) if offsets else EMPTY),
        ("Signal EOTF", fmt.num(block.get("signal_eotf"))),
        ("EOTF parameters",
         fmt.joined(*(fmt.num(block.get(f"signal_eotf_param{index}"))
                   for index in range(3)))),
        ("Signal bit depth", fmt.num(block.get("signal_bit_depth"))),
        ("Colour space", fmt.num(block.get("signal_color_space"))),
        ("Chroma format", fmt.num(block.get("signal_chroma_format"))),
        ("Full range", fmt.num(block.get("signal_full_range_flag"))),
    ]


def l3_pairs(rpu: Block | None) -> list[Pair]:
    """Return the L3 PQ offset rows."""
    l3 = (rpu or {}).get("l3") or {}
    return [
        ("Min PQ offset", fmt.num(l3.get("min_pq_offset"))),
        ("Max PQ offset", fmt.num(l3.get("max_pq_offset"))),
        ("Average PQ offset", fmt.num(l3.get("avg_pq_offset"))),
    ]


def l4_pairs(rpu: Block | None) -> list[Pair]:
    """Return the L4 temporal stability anchors as raw codes."""
    l4 = (rpu or {}).get("l4") or {}
    return [
        ("Anchor PQ", fmt.num(l4.get("anchor_pq"))),
        ("Anchor power", fmt.num(l4.get("anchor_power"))),
    ]


def l5_pairs(rpu: Block | None) -> list[Pair]:
    """Return the L5 active-area offsets of this frame."""
    l5 = (rpu or {}).get("l5") or {}
    return [
        (f"{edge.capitalize()} offset", fmt.num(l5.get(edge)))
        for edge in ("left", "right", "top", "bottom")
    ]


def l6_pairs(rpu: Block | None) -> list[Pair]:
    """Return the L6 rows (the RPU's own declaration, not the static SEIs)."""
    l6 = (rpu or {}).get("l6") or {}
    return [
        ("MaxCLL", fmt.num(l6.get("max_cll"))),
        ("MaxFALL", fmt.num(l6.get("max_fall"))),
        ("Max luminance", fmt.lum(l6.get("max_lum_nits"))),
        ("Min luminance", fmt.lum(l6.get("min_lum_nits"))),
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
_VECTOR_FIELDS = tuple((str(index), f"Field {index + 1}") for index in range(6))

# One trim table: legend, controls, the block of a pass, the formatter.
_TrimTable = tuple[str, Sequence[tuple[str, str]], Callable[[Block], Block],
                   Callable[[object], str]]

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


def _target_nits(trim: Block) -> int | None:
    """Return the target display brightness of *trim* in whole nits, or None."""
    value = trim.get("nits")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(round(value))


def _target(trim: Block) -> str:
    """Name a pass by its target display brightness.

    The L10 index and raw target PQ code repeat the same information and are
    left out to keep the width for the cells.
    """
    return f"{fmt.num(trim.get('nits'))} nits"


def _vector_block(trim: Block, key: str) -> Block:
    """Return an L8 vector of *trim* keyed by position, for ``_table``.

    Empty when the pass has none (older parser or short block).
    """
    vector = trim.get(key)
    if not isinstance(vector, (list, tuple)):
        return {}
    return {str(index): value for index, value in enumerate(vector)}


def _table(legend: str, controls: Sequence[tuple[str, str]], trims: list[Block],
           block_of: Callable[[Block], Block], formatter: Callable[[object], str]) -> list[Entry]:
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

    entries: list[Entry] = []
    for start in range(0, len(used), MAX_COLUMNS):
        chunk = used[start:start + MAX_COLUMNS]
        if entries:
            entries.append((SPACE, f"space.{legend}.{start}", ""))
        entries.append((HEADINGS, legend, [heading for _key, heading in chunk]))
        entries.extend(_pass_rows(trims, [key for key, _heading in chunk],
                                  block_of, formatter))
    return entries


def _pass_rows(trims: list[Block], keys: list[str], block_of: Callable[[Block], Block],
               formatter: Callable[[object], str]) -> list[Entry]:
    """Return one table row per pass that sets any of *keys*."""
    rows: list[Entry] = []
    for trim in trims:
        cells = [formatter(block_of(trim).get(key)) for key in keys]
        if not _unset(cells):
            rows.append((COLUMNS, _target(trim), _blanked(cells)))
    return rows


def _trim_tables(level: str) -> list[_TrimTable]:
    """Return *level*'s tables as (legend, controls, block of a pass, formatter)."""
    if level != "l8":
        return [
            (_LEGEND_RAW, _TRIM_RAW, lambda trim: trim, fmt.num),
            (_LEGEND_UI, _TRIM_UI, lambda trim: trim.get("ui") or {}, fmt.scaled),
        ]
    tables: list[_TrimTable] = [
        (_LEGEND_RAW, _TRIM_RAW_L8, lambda trim: trim, fmt.num),
        (_LEGEND_UI, _TRIM_UI, lambda trim: trim.get("ui") or {}, fmt.scaled),
    ]
    tables.extend(
        (legend, _VECTOR_FIELDS, partial(_vector_block, key=key), fmt.num)
        for key, legend in _TRIM_VECTORS
    )
    tables.append((_LEGEND_BLOCK, _TRIM_BLOCK, lambda trim: trim, fmt.num))
    return tables


def trim_entries(level: str, trims: list[Block] | None) -> list[Entry]:
    """Return the trim passes of *level* (l2 / l8) as tables.

    Controls across, one row per target display.  Raw codes and the UI's
    -1..1 scale are separate tables; L8 adds one table per secondary vector
    and one for the block length.  Only passes for ``_TRIM_TARGETS`` are
    shown; nothing left means no section.
    """
    trims = [trim for trim in (trims or [])
             if _target_nits(trim) in _TRIM_TARGETS]
    entries: list[Entry] = []
    for legend, controls, block_of, formatter in _trim_tables(level):
        table = _table(legend, controls, trims, block_of, formatter)
        if table and entries:
            # Space between the tables.
            entries.append((SPACE, f"space.{level}.{legend}", ""))
        entries.extend(table)
    return entries


def l9_pairs(rpu: Block | None) -> list[Pair]:
    """Return the L9 source primaries, with coordinates when present."""
    block = (rpu or {}).get("l9") or {}
    pairs: list[Pair] = [
        ("Index", fmt.num(block.get("index"))),
        ("Primaries", fmt.text(block.get("name"))),
    ]
    coords = block.get("coords") or {}
    if coords:
        pairs.extend(
            (f"{key.capitalize()} (x | y)", fmt.coords(coords.get(key)))
            for key in ("red", "green", "blue", "white")
        )
    # The length decides whether coordinates are present at all.
    pairs.append(("Block length", fmt.num(block.get("length"))))
    return pairs


def l10_pairs(targets: list[Block] | None) -> list[Pair]:
    """Return one row per L10 target display with its primaries and PQ range."""
    pairs: list[Pair] = []
    for target in targets or []:
        name = f"{fmt.num(target.get('nits'))} nits"
        index = target.get("target_display_index")
        if index is not None:
            name += f" (#{fmt.num(index)})"
        readings = []
        primary = fmt.text(target.get("primary_name"))
        if primary != EMPTY:
            readings.append(primary)
        for label, key in (("max PQ", "target_max_pq"),
                           ("min PQ", "target_min_pq"),
                           ("length", "length")):
            reading = fmt.num(target.get(key))
            if reading != EMPTY:
                readings.append(f"{label} {reading}")
        if readings:
            pairs.append((name, "  ".join(readings)))
    return pairs


def l11_pairs(rpu: Block | None) -> list[Pair]:
    """Return the L11 content type and whitepoint rows."""
    l11 = (rpu or {}).get("l11") or {}
    return [
        ("Content type", fmt.text(l11.get("content_type_name"))),
        ("Whitepoint", fmt.text(l11.get("whitepoint_name"))),
        ("Reference mode", fmt.flag(l11.get("reference_mode"))),
        ("Reserved bytes", fmt.joined(fmt.num(l11.get("reserved_byte2")),
                                   fmt.num(l11.get("reserved_byte3")))),
    ]


def l254_pairs(rpu: Block | None) -> list[Pair]:
    """Return the L254 (CM v4.0 marker) raw codes."""
    l254 = (rpu or {}).get("l254") or {}
    return [
        ("DM mode", fmt.num(l254.get("dm_mode"))),
        ("DM version index", fmt.num(l254.get("dm_version_index"))),
    ]


def l255_pairs(rpu: Block | None) -> list[Pair]:
    """Return the L255 debug run mode rows (rare in encoded content)."""
    l255 = (rpu or {}).get("l255") or {}
    return [
        ("Run mode", fmt.num(l255.get("dm_run_mode"))),
        ("Run version", fmt.num(l255.get("dm_run_version"))),
        ("Debug", fmt.joined(*(fmt.num(l255.get(f"dm_debug{index}"))
                            for index in range(4)))),
    ]


def static_pairs(mdcv: Block | None, cll: Block | None) -> list[Pair]:
    """Return the static MDCV / CLL rows, kept apart from L6 (they can differ)."""
    mdcv = mdcv or {}
    cll  = cll or {}
    primaries = mdcv.get("primaries") or {}
    pairs: list[Pair] = [
        ("Max luminance", fmt.lum(mdcv.get("max_luminance"))),
        ("Min luminance", fmt.lum(mdcv.get("min_luminance"))),
        ("Primaries", fmt.text(primaries.get("name"))),
    ]
    if primaries:
        pairs.extend(
            (f"{key.capitalize()} (x | y)", fmt.coords(primaries.get(key)))
            for key in ("red", "green", "blue")
        )
    pairs.extend((
        ("White point (x | y)", fmt.coords(mdcv.get("white_point"))),
        ("MaxCLL", fmt.num(cll.get("max_cll"))),
        ("MaxFALL", fmt.num(cll.get("max_fall"))),
    ))
    return pairs


def hdr10plus_pairs(hdr10plus: Block) -> list[Entry]:
    """Return the HDR10+ (ST 2094-40) rows."""
    maxscl = hdr10plus.get("maxscl") or []
    pairs: list[Entry] = [
        ("Profile", fmt.text(hdr10plus.get("profile"))),
        ("Application version", fmt.num(hdr10plus.get("application_version"))),
        ("Windows", fmt.num(hdr10plus.get("num_windows"))),
        (
            "Target display (nits)",
            fmt.lum(hdr10plus.get("targeted_system_display_maximum_luminance")),
        ),
        (
            "MaxSCL (R | G | B)",
            fmt.joined(*(fmt.lum(value) for value in maxscl)) if maxscl else EMPTY,
        ),
        ("Average maxRGB", fmt.lum(hdr10plus.get("average_maxrgb"))),
        ("Bright pixels", fmt.percent(hdr10plus.get("fraction_bright_pixels"))),
    ]
    if hdr10plus.get("profile") == "B":
        pairs.extend(_tone_curve_pairs(hdr10plus))
    return pairs + _distribution_rows(hdr10plus)


def _tone_curve_pairs(hdr10plus: Block) -> list[Pair]:
    """Return the profile B tone curve: knee point and Bézier anchors."""
    anchors = hdr10plus.get("bezier_anchors") or []
    return [
        ("Knee point (x | y)",
         fmt.joined(fmt.scaled(hdr10plus.get("knee_point_x")),
                    fmt.scaled(hdr10plus.get("knee_point_y")))),
        ("Bézier anchors", " ".join(fmt.num(value) for value in anchors) or EMPTY),
    ]


def _distribution_rows(hdr10plus: Block) -> list[Entry]:
    """Return the nine maxRGB percentiles as one compact table, or [].

    ui.dvmetadata picks the compact grid from the cell count.
    """
    distribution = {
        entry.get("percentage"): entry.get("nits")
        for entry in hdr10plus.get("distribution") or []
    }
    values = _blanked([fmt.lum(distribution.get(percent))
                       for percent in _HDR10PLUS_PERCENTILES])
    if not any(values):
        return []
    return [
        (HEADINGS, "Distribution", [f"{percent}%" for percent in _HDR10PLUS_PERCENTILES]),
        (COLUMNS, "maxRGB (nits)", values),
    ]
