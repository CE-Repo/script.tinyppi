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
values: the RPU splits each into two halves (see ``info.dvcomposer``).

Names, units and scalings follow the module's FIELDS.md.  Fields the stream
does not carry are dropped, and sections without fields with them.

Under DM metadata compression most frames omit blocks such as L2, L8 or the
source range, so the last received block is held until replaced (see
``_HeldBlocks``).  Given a parse result of its own, ``build_scene_rows`` holds
nothing and simply formats it.
"""

from collections.abc import Callable, Iterable, Sequence
from functools import cache

import xbmc
import xbmcaddon
from info import dvformat as fmt
from info.dvcomposer import CURVE_COMPONENTS, composer_pairs, curve_entries, nlq_entries

# The row kinds are part of this module's interface (ui.dvmetadata, the
# dashboard), so they are re-exported here.
from info.dvformat import (  # noqa: F401
    CACHED,
    COLUMNS,
    EMPTY,
    HEADINGS,
    LIVE,
    MAX_COLUMNS,
    MAX_COMPACT_COLUMNS,
    ROW,
    SECTION,
    SPACE,
    WIDE,
)
from info.dvinfo import get_sidedata

_SIDEDATA_ID = "script.module.sidedata"

# The playing item; held blocks belong to it (see _HeldBlocks).
_SOURCE_LABEL = "Player.FilenameAndPath"

# HDR10+ maxRGB percentiles shown, in spec order.
_HDR10PLUS_PERCENTILES = (1, 5, 10, 25, 50, 75, 90, 95, 99)


@cache
def _module_version() -> str:
    """Return the installed script.module.sidedata version, or EMPTY.

    Read once: the imported parser stays in use until the process ends.
    """
    try:
        version = xbmcaddon.Addon(_SIDEDATA_ID).getAddonInfo("version")
    except Exception:  # not installed: Kodi raises RuntimeError
        version = ""
    return version or EMPTY


# --- Sections --------------------------------------------------------------

def _section(rows: list, title: str, entries: Iterable[tuple], state: str = "") -> None:
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
        ("HDR type (Kodi)", fmt.text(xbmc.getInfoLabel("VideoPlayer.HdrType"))),
        ("HDR detail (Kodi)", fmt.text(xbmc.getInfoLabel("VideoPlayer.HdrDetail"))),
        ("Side data", carried),
        ("Flags", ", ".join(flags) if flags else EMPTY),
        ("Structure", fmt.text(parsed.get("structure"))),
        ("Parser module", _module_version()),
    ]


def _config_pairs(config: dict | None) -> list:
    """Return the dvcC / dvvC record rows (source profile even after 4/7 -> 8)."""
    config = config or {}
    major = fmt.num(config.get("version_major"))
    minor = fmt.num(config.get("version_minor"))
    version = EMPTY if EMPTY in (major, minor) else f"{major}.{minor}"
    return [
        ("Record version", version),
        ("Profile", fmt.num(config.get("profile"))),
        ("Compatibility ID", fmt.num(config.get("compat_id"))),
        ("Level", fmt.num(config.get("level"))),
        ("RPU present", fmt.flag(config.get("rpu_present"))),
        ("BL present", fmt.flag(config.get("bl_present"))),
        ("EL present", fmt.flag(config.get("el_present"))),
        ("MD compression", fmt.num(config.get("md_compression"))),
    ]


def _rpu_pairs(rpu: dict | None) -> list:
    """Return the RPU header rows plus the guessed profile and compression.

    Compressed DM data is why the source range is often missing.
    """
    rpu = rpu or {}
    header = rpu.get("header") or {}
    return [
        ("Guessed profile", fmt.num(rpu.get("profile"))),
        ("CM version", fmt.text(rpu.get("cm_version"))),
        ("DM compression", fmt.flag(rpu.get("compressed"))),
        # The DM metadata ids and scene refresh flag: how a compressed frame
        # refers back to earlier metadata, and where a scene starts.
        ("Affected DM metadata ID", fmt.num(rpu.get("affected_dm_metadata_id"))),
        ("Current DM metadata ID", fmt.num(rpu.get("current_dm_metadata_id"))),
        ("Scene refresh", fmt.num(rpu.get("scene_refresh_flag"))),
        # Extension blocks declared across the CM v2.9 and v4.0 groups.
        ("Extension blocks", fmt.num(rpu.get("num_ext_blocks"))),
        ("RPU type", fmt.num(header.get("rpu_type"))),
        ("RPU format", fmt.num(header.get("rpu_format"))),
        ("VDR RPU profile", fmt.num(header.get("vdr_rpu_profile"))),
        ("VDR RPU level", fmt.num(header.get("vdr_rpu_level"))),
        ("VDR RPU normalized IDC", fmt.num(header.get("vdr_rpu_normalized_idc"))),
        # Presence flags for the sequence info (source of the bit depths) and
        # the DM metadata (source of the levels and the source range).
        ("VDR sequence info", fmt.flag(header.get("vdr_seq_info_present_flag"))),
        ("VDR DM metadata", fmt.flag(header.get("vdr_dm_metadata_present_flag"))),
        ("BL bit depth", fmt.num(header.get("bl_bit_depth"))),
        ("EL bit depth", fmt.num(header.get("el_bit_depth"))),
        ("VDR bit depth", fmt.num(header.get("vdr_bit_depth"))),
        ("BL full range", fmt.flag(header.get("bl_video_full_range_flag"))),
        ("EL type", fmt.text(header.get("el_type"))),
        (
            "EL spatial resampling",
            fmt.flag(header.get("el_spatial_resampling_filter_flag")),
        ),
        (
            "Spatial resampling",
            fmt.flag(header.get("spatial_resampling_filter_flag")),
        ),
        (
            "Chroma resampling filter",
            fmt.flag(header.get("chroma_resampling_explicit_filter_flag")),
        ),
        ("Residual disabled", fmt.flag(header.get("disable_residual_flag"))),
        ("Coefficient data type", fmt.num(header.get("coefficient_data_type"))),
        ("Coefficient log2 denom", fmt.num(header.get("coefficient_log2_denom"))),
        ("Reuses previous VDR RPU", fmt.flag(header.get("use_prev_vdr_rpu_flag"))),
        ("Previous VDR RPU ID", fmt.num(header.get("prev_vdr_rpu_id"))),
        # Fields without meaning of their own (deprecated NAL prefix, reserved
        # bits), shown because the RPU carries them.
        ("RPU NAL prefix", fmt.num(header.get("rpu_nal_prefix"))),
        ("Reserved (3 bits)", fmt.num(header.get("reserved_zero_3bits"))),
    ]


def _l1_pairs(rpu: dict | None) -> list:
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


def _source_pairs(rpu: dict | None) -> list:
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


def _colorimetry_entries(rpu: dict | None) -> list:
    """Return the VDR DM signal description and colour matrices as raw codes.

    Only frames with uncompressed DM data carry them.
    """
    block = (rpu or {}).get("colorimetry") or {}
    entries: list = []

    matrices = [
        (name, [fmt.num(value) for value in block.get(key) or []])
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
         fmt.joined(*(fmt.num(value) for value in offsets)) if offsets else EMPTY),
        ("Signal EOTF", fmt.num(block.get("signal_eotf"))),
        ("EOTF parameters",
         fmt.joined(*(fmt.num(block.get(f"signal_eotf_param{index}"))
                   for index in range(3)))),
        ("Signal bit depth", fmt.num(block.get("signal_bit_depth"))),
        ("Colour space", fmt.num(block.get("signal_color_space"))),
        ("Chroma format", fmt.num(block.get("signal_chroma_format"))),
        ("Full range", fmt.num(block.get("signal_full_range_flag"))),
    ])
    return entries


def _l3_pairs(rpu: dict | None) -> list:
    """Return the L3 PQ offset rows."""
    l3 = (rpu or {}).get("l3") or {}
    return [
        ("Min PQ offset", fmt.num(l3.get("min_pq_offset"))),
        ("Max PQ offset", fmt.num(l3.get("max_pq_offset"))),
        ("Average PQ offset", fmt.num(l3.get("avg_pq_offset"))),
    ]


def _l4_pairs(rpu: dict | None) -> list:
    """Return the L4 temporal stability anchors as raw codes."""
    l4 = (rpu or {}).get("l4") or {}
    return [
        ("Anchor PQ", fmt.num(l4.get("anchor_pq"))),
        ("Anchor power", fmt.num(l4.get("anchor_power"))),
    ]


def _l5_pairs(rpu: dict | None) -> list:
    """Return the L5 active-area offsets of this frame."""
    l5 = (rpu or {}).get("l5") or {}
    return [
        (f"{edge.capitalize()} offset", fmt.num(l5.get(edge)))
        for edge in ("left", "right", "top", "bottom")
    ]


def _l6_pairs(rpu: dict | None) -> list:
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
    return f"{fmt.num(trim.get('nits'))} nits"


def _vector_block(trim: dict, key: str) -> dict:
    """Return an L8 vector of *trim* keyed by position, for ``_table``.

    Empty when the pass has none (older parser or short block).
    """
    vector = trim.get(key)
    if not isinstance(vector, (list, tuple)):
        return {}
    return dict(enumerate(vector))


def _table(legend: str, controls: Sequence[tuple[str, str]], trims: list,
           block_of: Callable[[dict], dict], formatter: Callable[[object], str]) -> list:

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

    tables: list[tuple] = [
        (_LEGEND_RAW, raw_controls, lambda trim: trim, fmt.num),
        (_LEGEND_UI, _TRIM_UI, lambda trim: trim.get("ui") or {}, fmt.scaled),
    ]
    tables.extend(
        (legend, _VECTOR_FIELDS,
         lambda trim, key=key: _vector_block(trim, key), fmt.num)
        for key, legend in (_TRIM_VECTORS if level == "l8" else ())
    )
    if level == "l8":
        tables.append((_LEGEND_BLOCK, _TRIM_BLOCK, lambda trim: trim, fmt.num))

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


def _l10_pairs(targets: list | None) -> list:
    """Return one row per L10 target display with its primaries and PQ range."""
    pairs = []
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


def _l11_pairs(rpu: dict | None) -> list:
    """Return the L11 content type and whitepoint rows."""
    l11 = (rpu or {}).get("l11") or {}
    return [
        ("Content type", fmt.text(l11.get("content_type_name"))),
        ("Whitepoint", fmt.text(l11.get("whitepoint_name"))),
        ("Reference mode", fmt.flag(l11.get("reference_mode"))),
        ("Reserved bytes", fmt.joined(fmt.num(l11.get("reserved_byte2")),
                                   fmt.num(l11.get("reserved_byte3")))),
    ]


def _l254_pairs(rpu: dict | None) -> list:
    """Return the L254 (CM v4.0 marker) raw codes."""
    l254 = (rpu or {}).get("l254") or {}
    return [
        ("DM mode", fmt.num(l254.get("dm_mode"))),
        ("DM version index", fmt.num(l254.get("dm_version_index"))),
    ]


def _l255_pairs(rpu: dict | None) -> list:
    """Return the L255 debug run mode rows (rare in encoded content)."""
    l255 = (rpu or {}).get("l255") or {}
    return [
        ("Run mode", fmt.num(l255.get("dm_run_mode"))),
        ("Run version", fmt.num(l255.get("dm_run_version"))),
        ("Debug", fmt.joined(*(fmt.num(l255.get(f"dm_debug{index}"))
                            for index in range(4)))),
    ]


def _static_pairs(mdcv: dict | None, cll: dict | None) -> list:
    """Return the static MDCV / CLL rows, kept apart from L6 (they can differ)."""
    mdcv = mdcv or {}
    cll  = cll or {}
    primaries = mdcv.get("primaries") or {}
    pairs = [
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


def _hdr10plus_pairs(hdr10plus: dict) -> list:
    """Return the HDR10+ (ST 2094-40) rows."""
    maxscl = hdr10plus.get("maxscl") or []
    profile_b = hdr10plus.get("profile") == "B"
    anchors = hdr10plus.get("bezier_anchors") or []
    distribution = {
        entry.get("percentage"): entry.get("nits")
        for entry in hdr10plus.get("distribution") or []
    }
    pairs: list[tuple] = [
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
    if profile_b:
        pairs.extend((
            ("Knee point (x | y)",
             fmt.joined(fmt.scaled(hdr10plus.get("knee_point_x")),
                     fmt.scaled(hdr10plus.get("knee_point_y")))),
            ("Bézier anchors", " ".join(fmt.num(value) for value in anchors)
                               or EMPTY),
        ))
    # The nine maxRGB percentiles as one compact table; ui.dvmetadata picks
    # the compact grid from the cell count.
    percentile_values = []
    for percent in _HDR10PLUS_PERCENTILES:
        value = fmt.lum(distribution.get(percent))
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
    _section(rows, "Composer — Data mapping", composer_pairs(rpu),
             _state(origin, "rpu.data_mapping"))
    for index, component in enumerate(CURVE_COMPONENTS):
        _section(rows, f"Composer — {component} curve",
                 curve_entries(rpu, index),
                 _state(origin, "rpu.data_mapping"))
    _section(rows, "Composer — NLQ", nlq_entries(rpu),
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
