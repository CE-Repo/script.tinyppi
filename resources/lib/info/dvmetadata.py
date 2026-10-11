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
does not carry are dropped, and sections without fields with them.  The
entries of the per-block sections (L1 to L255, trims, static SEIs, HDR10+)
come from ``info.dvlevels``; this module arranges them.

Under DM metadata compression most frames omit blocks such as L2, L8 or the
source range, so the last received block is held until replaced (see
``_HeldBlocks``).  Given a parse result of its own, ``build_scene_rows`` holds
nothing and simply formats it.
"""

from collections.abc import Iterable
from functools import cache

import xbmc
import xbmcaddon
from info import dvformat as fmt
from info import dvlevels as levels
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
    Block,
    Entry,
    Pair,
    Row,
    Value,
)
from info.dvinfo import get_sidedata

_SIDEDATA_ID = "script.module.sidedata"

# The playing item; held blocks belong to it (see _HeldBlocks).
_SOURCE_LABEL = "Player.FilenameAndPath"


@cache
def _module_version() -> str:
    """Return the installed script.module.sidedata version, or EMPTY.

    Read once: the imported parser stays in use until the process ends.
    """
    try:
        version = xbmcaddon.Addon(_SIDEDATA_ID).getAddonInfo("version")
    except RuntimeError:  # not installed: Kodi raises RuntimeError
        version = ""
    return version or EMPTY


# Where each block of a frame came from, by key (``rpu.l2``): LIVE or CACHED.
Origin = dict[str, str]


# --- Sections --------------------------------------------------------------

def _kept_rows(entries: Iterable[Entry]) -> list[Row]:
    """Return *entries* as rows, without EMPTY values and outer blank rows."""
    kept = [
        entry if len(entry) == 3 else (ROW, entry[0], entry[1])
        for entry in entries
    ]
    kept = [row for row in kept
            if row[0] == SPACE or (row[2] and row[2] != EMPTY)]
    return _without_outer_space(kept)


def _without_outer_space(rows: list[Row]) -> list[Row]:
    """Return *rows* without blank rows at either end."""
    start, stop = 0, len(rows)
    while start < stop and rows[start][0] == SPACE:
        start += 1
    while stop > start and rows[stop - 1][0] == SPACE:
        stop -= 1
    return rows[start:stop]


def _section(rows: list[Row], title: str, entries: Iterable[Entry], state: str = "") -> None:
    """Append a heading and its entries to *rows*, skipping empty ones.

    An entry is a ``(name, value)`` pair or a full ``(kind, name, value)``
    triple.  Entries valued EMPTY are dropped, and the heading too when none
    remain.  Blank rows are kept only between readings.

    *state* (CACHED or '') becomes the heading row's value rather than part
    of the title, because the view remembers the viewer's position by title.
    """
    kept = _kept_rows(entries)
    if not kept:
        return
    if rows:
        # Space before every heading but the first.
        rows.append((SPACE, f"space.{title}", ""))
    rows.append((SECTION, title, state))
    rows.extend(kept)


def _payload_summary(parsed: Block) -> str:
    """Name the sections the payload carried, e.g. ``config, rpu``, or EMPTY."""
    present = [
        key for key in ("config", "rpu", "hdr10plus", "mdcv", "cll")
        if parsed.get(key)
    ]
    return ", ".join(present) if present else EMPTY


def _stream_pairs(parsed: Block, carried: str) -> list[Pair]:
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


def _config_pairs(config: Block | None) -> list[Pair]:
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


def _rpu_pairs(rpu: Block | None) -> list[Pair]:
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
        self._blocks: dict[str, Block] = {}
        self._source: str | None = None

    def _fill_in(self, current: Block, names: tuple[str, ...],
                 prefix: str) -> tuple[Block, Origin]:
        """Fill omitted blocks of *current* and remember present ones.

        Also returns each block's origin: LIVE, CACHED, or no entry when
        neither has it.
        """
        held = self._blocks
        filled: Block = dict(current)
        origin: Origin = {}
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

    def hold(self, parsed: Block) -> tuple[Block, Origin]:
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


def _state(origin: Origin, *keys: str) -> str:
    """Return CACHED when every block of a section was held, else ''."""
    seen = [origin[key] for key in keys if key in origin]
    return CACHED if seen and all(state == CACHED for state in seen) else ""


# --- Row model -------------------------------------------------------------

def build_scene_rows(
    parsed: Block | None = None,
) -> tuple[list[Row], Block, Origin, str]:
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
    origin: Origin = {}
    if live:
        parsed, origin = _held.hold(parsed)

    rpu = parsed.get("rpu")
    rows: list[Row] = []

    # Per-frame blocks first, the most watched (L1, L2, L8) on top.
    _section(rows, "L1 — Frame luminance", levels.l1_pairs(rpu),
             _state(origin, "rpu.l1"))
    _section(rows, "L2 — Trims", levels.trim_entries("l2", (rpu or {}).get("l2")),
             _state(origin, "rpu.l2"))
    _section(rows, "L8 — Trims", levels.trim_entries("l8", (rpu or {}).get("l8")),
             _state(origin, "rpu.l8"))
    _section(rows, "L5 — Active area", levels.l5_pairs(rpu), _state(origin, "rpu.l5"))
    _section(rows, "L3 — PQ offsets", levels.l3_pairs(rpu), _state(origin, "rpu.l3"))
    _section(rows, "L4 — Temporal stability", levels.l4_pairs(rpu),
             _state(origin, "rpu.l4"))
    hdr10plus = parsed.get("hdr10plus")
    if hdr10plus:
        # Dynamic per scene, so it belongs with the scene rows.
        _section(rows, "HDR10+ (ST 2094-40)", levels.hdr10plus_pairs(hdr10plus),
                 _state(origin, "hdr10plus"))

    return rows, parsed, origin, carried


def build_static_rows(parsed: Block, origin: Origin, carried: str) -> list[Row]:
    """Return the per-title rows from ``build_scene_rows``'s results.

    Source master, colorimetry, L6, L9-L11, L254, L255, static SEIs, RPU
    header, composer and file-level blocks rarely change, so callers may
    rebuild them less often; their Cached badges then reflect the frame they
    were built from.

    No leading blank row: ``join_rows`` decides that against the current
    scene rows, which may differ from the ones current when this was built.
    """
    rpu = parsed.get("rpu")
    rows: list[Row] = []

    # The grade.  The source range belongs here: it describes the master.
    _section(rows, "Source master", levels.source_pairs(rpu),
             _state(origin, "rpu.source"))
    _section(rows, "Colorimetry (VDR DM)", levels.colorimetry_entries(rpu),
             _state(origin, "rpu.colorimetry"))
    _section(rows, "L6 — RPU mastering display", levels.l6_pairs(rpu),
             _state(origin, "rpu.l6"))
    _section(rows, "L9 — Source primaries", levels.l9_pairs(rpu),
             _state(origin, "rpu.l9"))
    _section(rows, "L10 — Target displays", levels.l10_pairs((rpu or {}).get("l10")),
             _state(origin, "rpu.l10"))
    _section(rows, "L11 — Content type", levels.l11_pairs(rpu),
             _state(origin, "rpu.l11"))
    _section(rows, "L254 — CM v4.0", levels.l254_pairs(rpu),
             _state(origin, "rpu.l254"))
    _section(rows, "L255 — Debug run mode", levels.l255_pairs(rpu),
             _state(origin, "rpu.l255"))
    _section(rows, "Static metadata (MDCV / CLL)",
             levels.static_pairs(parsed.get("mdcv"), parsed.get("cll")),
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


def static_signature(parsed: Block, origin: Origin, carried: str) -> tuple[object, ...]:
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
    scene_rows: list[Row], static_rows: list[Row],
) -> list[Row]:
    """Concatenate scene and static rows, with a blank row between them.

    Decided here against the current scene rows, since the two halves may
    be rebuilt at different times.
    """
    if scene_rows and static_rows:
        static_rows = [(SPACE, f"space.{static_rows[0][1]}", "")] + static_rows
    return scene_rows + static_rows
