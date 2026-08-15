"""Row model for the Dolby Vision metadata view.

``dvinfo`` picks the handful of readings the overlay has room for and formats
each one for its row.  This module does the opposite: it walks the whole parse
result ``script.module.sidedata`` returns -- flags, structure, the dvcC/dvvC
configuration record, every RPU block from the header through L11, and the
static MDCV / CLL SEIs (plus the HDR10+ payload when the stream carries one) --
and lays it out as ``(kind, name, value)`` rows for ui.dvmetadata to put in a list.
Nothing is left out and nothing is interpreted: the metadata view is where you go
to see what the bitstream actually says.

Field names, units and value scalings follow the module's own FIELDS.md, so a
row here reads the same as the documented field it comes from.  Only readings
the bitstream actually carries make it into the list: a field the stream leaves
out is dropped rather than shown as a dash, and a section left with nothing to
say drops with it, so the view is what this stream has rather than a form with
most of its boxes blank.  Everything is read live: the per-frame blocks (L1,
L2, L5, L8) move with the picture, the title-level ones stand still.

Carries what a frame omits, though.  Under DM metadata compression an RPU
refers back to an earlier frame's metadata rather than repeating it, so a block
this stream plainly has -- L2, L8, the source range, the title-level levels --
is missing from most frames of it.  Read strictly frame by frame those sections
would come and go every second or two; instead the last block that arrived
stands until a new one replaces it (see _hold).

Formatting only, apart from the stream labels and the parser version the first
section names, and the held blocks the live path fills in: hand ``build_rows``
a parse result of your own and it yields the same rows anywhere, holding
nothing.
"""

import xbmc
import xbmcaddon

from info.dvinfo import get_sidedata

# Row kinds, which ui.dvmetadata turns into the fields of a list item: a heading,
# a name / value pair, one line of text across the full width -- for a value
# with no name worth giving it, which needs the name column's room too -- and
# an empty row.
#
# The empty row is what sets the headings apart.  A Kodi list scrolls by one
# uniform item size, so a heading cannot simply be given a taller layout than
# the rows under it; a blank row of the same height ahead of each one buys the
# same air without putting the container's scrolling out of step.
SECTION = "section"
ROW     = "row"
WIDE    = "wide"
SPACE   = "space"

# And two that make a table: a row of column headings and a row of readings
# under it, each carrying its cells as a list rather than as one string.  A
# trim pass is a set of readings that only mean anything read against each
# other, and a proportional font cannot be padded into columns -- so the cells
# go to the skin one at a time, and it draws each in a fixed slot of its own.
HEADINGS = "headings"
COLUMNS  = "columns"

# Cells such a row can hold.  The list is 1195 px wide and the grid divides it
# exactly: the name column takes 235, then six cells of 160 reach the right
# edge with nothing left over.  A level with more controls than that -- L8,
# with eight -- takes a second table underneath the first, headings and all,
# rather than a column running off the edge.
MAX_COLUMNS = 6

# What a formatter returns wherever the bitstream carries no reading: an absent
# block, a field the parser could not fill.  It never reaches the list -- see
# _section, which drops the rows that come back holding it -- so it is the
# internal "nothing here", not a label anyone reads.
EMPTY = "—"

# Where the block under a section heading came from.  Only CACHED is ever said
# out loud, on the heading of a section this frame did not carry and that is
# standing on the last frame that did (see _hold); LIVE is what the rest are,
# and a heading with nothing after it is the ordinary case worth no ink.
LIVE   = "Live"
CACHED = "Cached"

_SIDEDATA_ID = "script.module.sidedata"

# What is playing, which is what the held blocks are kept against: they
# describe this title's grade and nothing of the next one's (see _hold).
_SOURCE_LABEL = "Player.FilenameAndPath"

# Between the parts of a composite value ("2081 | 1000").
_JOIN = " | "

# Percentiles of the HDR10+ maxRGB distribution worth printing, in the order
# the spec lists them.
_HDR10PLUS_PERCENTILES = (1, 5, 10, 25, 50, 75, 90, 95, 99)


# --- Value formatting ------------------------------------------------------

def _text(value) -> str:
    """Return a plain string value, or EMPTY when there is nothing to show."""
    if value is None:
        return EMPTY
    text = str(value).strip()
    return text or EMPTY


def _num(value) -> str:
    """Format a number, dropping a redundant ``.0`` tail (``1000.0`` ->
    ``1000``).  Anything that is not a number reads as EMPTY."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return EMPTY
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _lum(value) -> str:
    """Format a luminance in nits: whole numbers at or above 1 cd/m², four
    decimals below it, trailing zeros trimmed.  Mirrors dvinfo's formatting so
    a value reads the same here as it does on the overlay."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return EMPTY
    if value and abs(value) < 1.0:
        return f"{value:.4f}".rstrip("0").rstrip(".")
    return str(int(round(value)))


def _scaled(value) -> str:
    """Format a value that lives on a fixed 0..1 or -1..1 scale (the Dolby UI
    trims, the HDR10+ knee point), or EMPTY when the block leaves it out --
    which is how a disabled trim control reads."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return EMPTY
    return f"{value:.4f}"


def _percent(value) -> str:
    """Format a percentage to one decimal, or EMPTY."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return EMPTY
    return f"{value:.1f} %"


def _flag(value) -> str:
    """Format a presence flag as Kodi's own Yes / No, EMPTY when unknown."""
    if value is None:
        return EMPTY
    return xbmc.getLocalizedString(107 if value else 106)


def _joined(*values: str) -> str:
    """Join the parts of a composite value, leaving out the parts the stream
    does not carry.  EMPTY when none of them survive, which is what drops the
    row."""
    present = [value for value in values if value != EMPTY]
    return _JOIN.join(present) if present else EMPTY


def _coords(pair) -> str:
    """Format a CIE ``(x, y)`` coordinate pair, raw codes or floats alike."""
    if not isinstance(pair, (tuple, list)) or len(pair) != 2:
        return EMPTY
    x, y = pair
    if isinstance(x, float) or isinstance(y, float):
        return _joined(f"{x:.4f}", f"{y:.4f}")
    return _joined(_num(x), _num(y))


def _module_version() -> str:
    """Return the installed script.module.sidedata version, or EMPTY when the
    module is not there -- which is also why every parsed row would be empty."""
    try:
        return xbmcaddon.Addon(_SIDEDATA_ID).getAddonInfo("version") or EMPTY
    except Exception:
        return EMPTY


# --- Sections --------------------------------------------------------------

def _section(rows: list, title: str, entries, state: str = "") -> None:
    """Append a heading and its entries to *rows*, skipping what is not there.

    An entry is either a ``(name, value)`` pair for a two-column row, or an
    already complete ``(kind, name, value)`` triple for one that is not.  An
    entry whose value came back EMPTY is left out, and a heading whose entries
    all went that way is left out with them: an absent block should take no
    room at all rather than a screenful of dashes.

    A blank row is the one entry that carries no value and is meant to: it is
    kept, but only between readings.  One that ends up at either end of a
    section is dropped, so a section can never open or close on a gap it does
    not need -- the row before the next heading is already there.

    *state* is CACHED for a section standing on a block held from an earlier
    frame, and empty for one the frame itself carried.  The heading row takes
    it as its value, beside the title rather than in it: the title is what a
    section is known by -- it is what the view remembers the viewer's place
    with -- and a word that came and went with the frame would take their place
    with it.  ui.dvmetadata is what puts the two together for the eye.
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
        # Air ahead of the heading -- not before the first one, which needs no
        # separating from what is above it.
        rows.append((SPACE, f"space.{title}", ""))
    rows.append((SECTION, title, state))
    rows.extend(kept)


def _payload_summary(parsed: dict) -> str:
    """Name the sections the payload actually carried, e.g. ``config, rpu,
    mdcv``.  EMPTY when none of them arrived at all."""
    present = [
        key for key in ("config", "rpu", "hdr10plus", "mdcv", "cll")
        if parsed.get(key)
    ]
    return ", ".join(present) if present else EMPTY


def _stream_pairs(parsed: dict, carried: str) -> list:
    """Kodi's own view of the stream, plus what the raw label delivered.

    *carried* names the sections this frame's own payload brought, which is not
    the same as the sections below it: those may be held from an earlier frame
    (see _hold), and this row is where a reader can tell.
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
    """The dvcC / dvvC configuration record: container-level truth, so it still
    names the source profile after a 4/7 -> 8 conversion."""
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
    """The RPU header and the two facts that sit beside it: the profile libdovi
    guesses from the RPU shape, and whether this frame's DM data is compressed
    (which is what empties the source range below)."""
    rpu = rpu or {}
    header = rpu.get("header") or {}
    return [
        ("Guessed profile", _num(rpu.get("profile"))),
        ("CM version", _text(rpu.get("cm_version"))),
        ("DM compression", _flag(rpu.get("compressed"))),
        ("RPU type", _num(header.get("rpu_type"))),
        ("RPU format", _num(header.get("rpu_format"))),
        ("VDR RPU profile", _num(header.get("vdr_rpu_profile"))),
        ("VDR RPU level", _num(header.get("vdr_rpu_level"))),
        ("BL bit depth", _num(header.get("bl_bit_depth"))),
        ("EL bit depth", _num(header.get("el_bit_depth"))),
        ("VDR bit depth", _num(header.get("vdr_bit_depth"))),
        ("EL type", _text(header.get("el_type"))),
        (
            "EL spatial resampling",
            _flag(header.get("el_spatial_resampling_filter_flag")),
        ),
        ("Residual disabled", _flag(header.get("disable_residual_flag"))),
    ]


def _l1_pairs(rpu: dict | None) -> list:
    """L1 frame luminance, each reading as its raw PQ code and the nits it
    decodes to.  Per frame: these move with the picture."""
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
    """The PQ range of the master the grade was made from.  Only frames whose
    DM data is uncompressed carry it, so it reads EMPTY on the rest."""
    source = (rpu or {}).get("source") or {}
    return [
        ("Min (PQ | nits)", _joined(_num(source.get("min_pq")),
                                    _lum(source.get("min_nits")))),
        ("Max (PQ | nits)", _joined(_num(source.get("max_pq")),
                                    _lum(source.get("max_nits")))),
    ]


def _l3_pairs(rpu: dict | None) -> list:
    """L3 PQ offsets."""
    l3 = (rpu or {}).get("l3") or {}
    return [
        ("Min PQ offset", _num(l3.get("min_pq_offset"))),
        ("Max PQ offset", _num(l3.get("max_pq_offset"))),
        ("Average PQ offset", _num(l3.get("avg_pq_offset"))),
    ]


def _l5_pairs(rpu: dict | None) -> list:
    """L5 active area: the black bars the RPU declares for this frame."""
    l5 = (rpu or {}).get("l5") or {}
    return [
        (f"{edge.capitalize()} offset", _num(l5.get(edge)))
        for edge in ("left", "right", "top", "bottom")
    ]


def _l6_pairs(rpu: dict | None) -> list:
    """L6: the mastering display and content light the RPU itself declares,
    which is not the same thing as the static SEIs further down."""
    l6 = (rpu or {}).get("l6") or {}
    return [
        ("MaxCLL", _num(l6.get("max_cll"))),
        ("MaxFALL", _num(l6.get("max_fall"))),
        ("Max luminance", _lum(l6.get("max_lum_nits"))),
        ("Min luminance", _lum(l6.get("min_lum_nits"))),
    ]


# Raw trim controls, 12 bit with 2048 neutral, in the order Dolby lists them,
# as (field, column heading).  A pass fills one row of the table, a control per
# cell, under a heading row naming them.
_TRIM_RAW = (
    ("slope",        "Slope"),
    ("offset",       "Offset"),
    ("power",        "Power"),
    ("chromaweight", "Chroma"),
    ("saturation",   "Saturation"),
    ("tonedetail",   "Detail"),
)
# L8 carries two controls L2 does not, which is what takes it past MAX_COLUMNS.
_TRIM_RAW_L8 = _TRIM_RAW + (
    ("mid_contrast", "Mid contrast"),
    ("clip_trim",    "Clip trim"),
)
# The same pass on the -1..1 scale the Dolby UI shows.  Gain, lift and gamma
# are derived from the slope / offset / power controls above, the rest are
# those rescaled.
_TRIM_UI = (
    ("gain",         "Gain"),
    ("lift",         "Lift"),
    ("gamma",        "Gamma"),
    ("chromaweight", "Chroma"),
    ("saturation",   "Saturation"),
    ("tonedetail",   "Detail"),
)

# What the name column says on each heading row.
_LEGEND_RAW = "Legend (raw)"
_LEGEND_UI  = "Legend (UI)"


def _target(trim: dict) -> str:
    """Name a pass by the display it was graded for."""
    target = f"{_num(trim.get('nits'))} nits"
    index  = trim.get("target_display_index")
    if index is not None:
        target += f" (#{_num(index)})"
    return target


def _table(legend: str, controls, trims: list, block_of, formatter) -> list:
    """One trim table: a heading row, then a row of cells per pass.

    Only the controls some pass actually sets get a column -- a column of
    nothing but blanks is a column's width spent saying so.  A cell the pass
    itself leaves out comes out blank rather than as a dash, which is how a
    disabled trim reads, and a pass that sets nothing in this table gets no
    row at all.

    More controls than a row holds means a second table under the first,
    headings repeated, rather than columns running off the edge of the list.
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
    """The trim passes of *level* (l2 / l8) as two tables.

    A pass is a set of readings that only mean anything read against each
    other and against the other passes, so they are laid out as the table they
    are: the controls across the top, one row per pass, the target display it
    was graded for down the left.  The raw codes and the -1..1 scale a
    colourist would recognise are two tables rather than two interleaved rows,
    because the column a reading sits in is what says what it is, and a
    heading is worth repeating far less often than it is worth reading.

    A level whose passes set nothing returns nothing, which drops its section.
    """
    raw_controls = _TRIM_RAW_L8 if level == "l8" else _TRIM_RAW
    trims = list(trims or [])
    entries: list = []

    for legend, controls, block_of, formatter in (
        (_LEGEND_RAW, raw_controls, lambda trim: trim, _num),
        (_LEGEND_UI, _TRIM_UI, lambda trim: trim.get("ui") or {}, _scaled),
    ):
        table = _table(legend, controls, trims, block_of, formatter)
        if not table:
            continue
        if entries:
            # Air between the two tables, so each reads as one.
            entries.append((SPACE, f"space.{level}.ui", ""))
        entries.extend(table)
    return entries


def _l9_pairs(rpu: dict | None) -> list:
    """L9: the primaries the content was graded against, plus the CIE
    coordinates the block carries when it names no known index."""
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
    return pairs


def _l10_pairs(targets: list | None) -> list:
    """The target displays L8's trim passes are graded against, each as one row
    naming what the display is and the PQ range it covers."""
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
                           ("min PQ", "target_min_pq")):
            reading = _num(target.get(key))
            if reading != EMPTY:
                readings.append(f"{label} {reading}")
        if readings:
            pairs.append((name, "  ".join(readings)))
    return pairs


def _l11_pairs(rpu: dict | None) -> list:
    """L11: what the grade was made for, and under which whitepoint."""
    l11 = (rpu or {}).get("l11") or {}
    return [
        ("Content type", _text(l11.get("content_type_name"))),
        ("Whitepoint", _text(l11.get("whitepoint_name"))),
        ("Reference mode", _flag(l11.get("reference_mode"))),
    ]


def _static_pairs(mdcv: dict | None, cll: dict | None) -> list:
    """The static MDCV / CLL SEIs: the stream's own HDR10 layer, shown apart
    from the RPU's L6 because they are separate declarations that need not
    agree."""
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
    """The ST 2094-40 payload, for a stream that carries HDR10+ alongside its
    Dolby Vision metadata."""
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
    # The maxRGB percentiles run the full width: nine readings do not fit a
    # value column, and they only mean anything read against each other.
    percentiles = "  ".join(
        f"{percent}% {_lum(distribution[percent])}"
        for percent in _HDR10PLUS_PERCENTILES
        if percent in distribution and _lum(distribution[percent]) != EMPTY
    )
    if percentiles:
        pairs.append((WIDE, "hdr10plus.distribution",
                      f"Distribution   {percentiles}"))
    return pairs


# --- Held blocks -----------------------------------------------------------

# The blocks a frame may leave out and still be described by, at the top level
# and inside the RPU.  Under DM metadata compression a frame's RPU refers back
# to an earlier one's metadata instead of carrying its own, so these arrive
# once and then stay away for as long as the grade does not change -- the
# reading still holds for the frame on screen, it is simply not repeated in it.
#
# Per block and never per field.  A block that is here is this frame's own, so
# a control it leaves out is one this pass disables, not one to fill in from an
# older pass -- the whole point of the trim tables is what a pass sets.
_HELD_TOP = ("config", "rpu", "mdcv", "cll", "hdr10plus")
_HELD_RPU = ("header", "source", "l1", "l2", "l3", "l5", "l6", "l8", "l9",
             "l10", "l11")

# The blocks last seen, by name, and what was playing when they were: nothing
# is carried from one title into the next, and stopping playback empties the
# label, which empties this with it.  Only the metadata view's own refresh
# reaches these, one call at a time.
_held: dict = {}
_held_source: str | None = None


def _fill_in(current: dict, names: tuple, prefix: str) -> tuple[dict, dict]:
    """Return *current* with the blocks it omits filled in from _held, and the
    ones it carries remembered in their place.

    Alongside it, where each block came from: LIVE for one this frame brought,
    CACHED for one put back from an earlier frame, and no entry at all for one
    neither has -- there is nothing to say about a block the stream does not
    carry, and its section is not there to say it on.
    """
    filled: dict = dict(current)
    origin: dict = {}
    for name in names:
        block = current.get(name)
        key   = prefix + name
        if block:
            _held[key]   = block
            origin[key]  = LIVE
        elif _held.get(key) is not None:
            filled[name] = _held[key]
            origin[key]  = CACHED
    return filled, origin


def _hold(parsed: dict) -> tuple[dict, dict]:
    """Fill *parsed* out with the blocks the frame on screen does not repeat.

    What a compressed frame leaves out is not absent from the stream, only
    from this RPU, so the view keeps the last block of each kind and puts it
    back when the next frame comes without one.  Rows that would otherwise
    blink out every second or two -- L2 and L8 trims above all, whole sections
    of them -- then stand still, and a reading that really does change still
    replaces the held one on the frame that carries it.

    Returns the origin map with it, which is what the headings say Live or
    Cached from: holding readings quietly would make a still reading and a
    stale one look alike.

    Kept against what is playing: a title change clears them, and so does the
    end of playback, which is what empties the label they are kept against.
    """
    global _held_source

    source = xbmc.getInfoLabel(_SOURCE_LABEL)
    if source != _held_source:
        _held.clear()
        _held_source = source

    parsed, origin = _fill_in(parsed, _HELD_TOP, "")
    rpu = parsed.get("rpu")
    if isinstance(rpu, dict):
        filled, inside = _fill_in(rpu, _HELD_RPU, "rpu.")
        # Hold the filled-out RPU rather than the frame's own, so a frame that
        # carries no RPU at all still gets every block, not just the ones the
        # last frame to carry one happened to have.
        parsed["rpu"] = _held["rpu"] = filled
        if origin.get("rpu") == CACHED:
            # No RPU in this frame at all: every block in the one standing in
            # for it is held, however live it looked when it was put away.
            inside = dict.fromkeys(inside, CACHED)
        origin.update(inside)
    return parsed, origin


def _state(origin: dict, *keys: str) -> str:
    """CACHED when every block a section was built from was held, else "".

    Every one of them and not merely one: a section with a reading from this
    frame in it is a live section, whatever else it had to fall back on.  A
    block the stream carries nowhere leaves no entry to judge, and its section
    is not in the list to be judged.
    """
    seen = [origin[key] for key in keys if key in origin]
    return CACHED if seen and all(state == CACHED for state in seen) else ""


# --- Row model -------------------------------------------------------------

def build_rows(parsed: dict | None = None) -> list[tuple[str, str, str]]:
    """Return the metadata view's rows for the frame on screen.

    Reads the current side data unless a parse result is passed in.  Every
    section is laid out in the same order every time, but only the readings the
    stream carries survive it: a block this stream has no data for takes no
    room, so what is on screen is what the bitstream said and the sections that
    are there can be read without hunting between empty ones.

    Read live, the blocks a compressed frame omits are held from the last frame
    that carried them and their heading says so (see _hold).  A parse result
    passed in is taken as it comes and holds nothing, so a caller with its own
    data gets its own data, every section of it live.
    """
    live   = parsed is None
    parsed = get_sidedata() if live else parsed
    parsed = parsed if isinstance(parsed, dict) else {}

    # Which blocks this frame itself brought, named before the held ones are
    # put back: the Stream section reports the payload in hand, and a held
    # block is precisely one that is not in it.
    carried = _payload_summary(parsed)
    origin: dict = {}
    if live:
        parsed, origin = _hold(parsed)

    rpu = parsed.get("rpu")
    rows: list[tuple[str, str, str]] = []

    _section(rows, "Stream", _stream_pairs(parsed, carried))
    _section(rows, "Configuration record (dvcC / dvvC)",
             _config_pairs(parsed.get("config")), _state(origin, "config"))
    # The RPU section is the header block plus the three readings that sit
    # beside it, which are the frame's own whenever it has an RPU at all.
    _section(rows, "RPU", _rpu_pairs(rpu),
             _state(origin, "rpu", "rpu.header"))
    _section(rows, "L1 — Frame luminance", _l1_pairs(rpu),
             _state(origin, "rpu.l1"))
    _section(rows, "Source PQ range", _source_pairs(rpu),
             _state(origin, "rpu.source"))
    _section(rows, "L2 — Trims", _trim_entries("l2", (rpu or {}).get("l2")),
             _state(origin, "rpu.l2"))
    _section(rows, "L3 — PQ offsets", _l3_pairs(rpu), _state(origin, "rpu.l3"))
    _section(rows, "L5 — Active area", _l5_pairs(rpu), _state(origin, "rpu.l5"))
    _section(rows, "L6 — RPU mastering display", _l6_pairs(rpu),
             _state(origin, "rpu.l6"))
    _section(rows, "L8 — Trims", _trim_entries("l8", (rpu or {}).get("l8")),
             _state(origin, "rpu.l8"))
    _section(rows, "L9 — Source primaries", _l9_pairs(rpu),
             _state(origin, "rpu.l9"))
    _section(rows, "L10 — Target displays", _l10_pairs((rpu or {}).get("l10")),
             _state(origin, "rpu.l10"))
    _section(rows, "L11 — Content type", _l11_pairs(rpu),
             _state(origin, "rpu.l11"))
    _section(rows, "Static metadata (MDCV / CLL)",
             _static_pairs(parsed.get("mdcv"), parsed.get("cll")),
             _state(origin, "mdcv", "cll"))

    hdr10plus = parsed.get("hdr10plus")
    if hdr10plus:
        _section(rows, "HDR10+ (ST 2094-40)", _hdr10plus_pairs(hdr10plus),
                 _state(origin, "hdr10plus"))

    if not rows:
        # Nothing was parsed at all -- no module, no side data, a frame that
        # arrived empty.  An empty window would read as a broken view rather
        # than as an answer, so say which it is.
        rows.append((SECTION, "No metadata in this frame", ""))

    return rows
