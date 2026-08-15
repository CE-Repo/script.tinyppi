"""Row model for the Dolby Vision debug view.

``dvinfo`` picks the handful of readings the overlay has room for and formats
each one for its row.  This module does the opposite: it walks the whole parse
result ``script.module.sidedata`` returns -- flags, structure, the dvcC/dvvC
configuration record, every RPU block from the header through L11, and the
static MDCV / CLL SEIs (plus the HDR10+ payload when the stream carries one) --
and lays it out as ``(kind, name, value)`` rows for ui.dvdebug to put in a list.
Nothing is left out and nothing is interpreted: the debug view is where you go
to see what the bitstream actually says.

Field names, units and value scalings follow the module's own FIELDS.md, so a
row here reads the same as the documented field it comes from.  Only readings
the bitstream actually carries make it into the list: a field the stream leaves
out is dropped rather than shown as a dash, and a section left with nothing to
say drops with it, so the view is what this stream has rather than a form with
most of its boxes blank.  Everything is read live: the per-frame blocks (L1,
L2, L5, L8) move with the picture, the title-level ones stand still.

Formatting only, apart from the stream labels and the parser version the first
section names: hand ``build_rows`` a parse result and it yields the same rows
anywhere.
"""

import xbmc
import xbmcaddon

from info.dvinfo import get_sidedata

# Row kinds, which ui.dvdebug turns into list layouts: a heading, a name /
# value pair, one line of text across the full width -- for the values that are
# a whole set of readings at once (a trim pass, a luminance distribution) and
# would not fit the value column -- and an empty row.
#
# The empty row is what sets the headings apart.  A Kodi list scrolls by one
# uniform item size, so a heading cannot simply be given a taller layout than
# the rows under it; a blank row of the same height ahead of each one buys the
# same air without putting the container's scrolling out of step.
SECTION = "section"
ROW     = "row"
WIDE    = "wide"
SPACE   = "space"

# What a formatter returns wherever the bitstream carries no reading: an absent
# block, a field the parser could not fill.  It never reaches the list -- see
# _section, which drops the rows that come back holding it -- so it is the
# internal "nothing here", not a label anyone reads.
EMPTY = "—"

_SIDEDATA_ID = "script.module.sidedata"

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

def _section(rows: list, title: str, entries) -> None:
    """Append a heading and its entries to *rows*, skipping what is not there.

    An entry is either a ``(name, value)`` pair for a two-column row, or an
    already complete ``(kind, name, value)`` triple for one that is not.  An
    entry whose value came back EMPTY is left out, and a heading whose entries
    all went that way is left out with them: an absent block should take no
    room at all rather than a screenful of dashes.
    """
    kept = [
        entry if len(entry) == 3 else (ROW, entry[0], entry[1])
        for entry in entries
    ]
    kept = [row for row in kept if row[2] and row[2] != EMPTY]
    if not kept:
        return
    if rows:
        # Air ahead of the heading -- not before the first one, which needs no
        # separating from what is above it.
        rows.append((SPACE, f"space.{title}", ""))
    rows.append((SECTION, title, ""))
    rows.extend(kept)


def _payload_summary(parsed: dict) -> str:
    """Name the sections the payload actually carried, e.g. ``config, rpu,
    mdcv``.  EMPTY when none of them arrived at all."""
    present = [
        key for key in ("config", "rpu", "hdr10plus", "mdcv", "cll")
        if parsed.get(key)
    ]
    return ", ".join(present) if present else EMPTY


def _stream_pairs(parsed: dict) -> list:
    """Kodi's own view of the stream, plus what the raw label delivered."""
    flags = parsed.get("flags") or []
    return [
        ("HDR type (Kodi)", _text(xbmc.getInfoLabel("VideoPlayer.HdrType"))),
        ("HDR detail (Kodi)", _text(xbmc.getInfoLabel("VideoPlayer.HdrDetail"))),
        ("Side data", _payload_summary(parsed)),
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


# Raw trim codes, 12 bit with 2048 neutral, in the order Dolby lists them, as
# (short code, field, name).  A whole pass goes on one line, so the codes are
# abbreviated and the legend row below spells them out once per section.
_TRIM_RAW = (
    ("S",  "slope",        "slope"),
    ("O",  "offset",       "offset"),
    ("P",  "power",        "power"),
    ("CW", "chromaweight", "chroma"),
    ("SG", "saturation",   "saturation"),
    ("TD", "tonedetail",   "detail"),
)
# L8 carries two codes L2 does not.
_TRIM_RAW_L8 = _TRIM_RAW + (
    ("MC", "mid_contrast", "mid contrast"),
    ("CT", "clip_trim",    "clip trim"),
)
# The same pass on the -1..1 scale the Dolby UI shows.  Gain, lift and gamma
# are derived from the slope / offset / power codes above, the rest are those
# codes rescaled.
_TRIM_UI = (
    ("G",  "gain",         "gain"),
    ("L",  "lift",         "lift"),
    ("Gm", "gamma",        "gamma"),
    ("CW", "chromaweight", "chroma"),
    ("SG", "saturation",   "saturation"),
    ("TD", "tonedetail",   "detail"),
)


def _legend(prefix: str, controls) -> str:
    """Spell out one line of trim codes."""
    parts = "  ".join(f"{code} {name}" for code, _key, name in controls)
    return f"{prefix}   {parts}"


def _line(readings) -> str:
    """Run a pass's readings across one line, ``code value`` each."""
    return "  ".join(f"{code} {text}" for code, text in readings)


def _controls(block: dict, controls, formatter) -> list:
    """The controls of one trim pass that carry a value, ``(code, text)`` each.

    A control the pass leaves out -- which is how a disabled trim reads -- does
    not come back, so the line built from this carries the controls that were
    actually set rather than a row of dashes between them.
    """
    readings = []
    for code, key, _name in controls:
        text = formatter(block.get(key))
        if text != EMPTY:
            readings.append((code, text))
    return readings


def _trim_entries(level: str, trims: list | None) -> list:
    """A legend, then a raw and a UI line per trim pass of *level* (l2 / l8).

    A pass is one trim, so it reads as one line rather than a dozen rows: the
    codes run across it, and the line below repeats the same pass on the scale
    a colourist would recognise.  Both run the full width -- see WIDE.

    Each line is identified by its position in the level rather than by its
    text, which changes with every frame: the identity is what tells a refresh
    that only the readings moved from one that changed the view itself.

    A legend only spells out the codes the lines below it actually use, and a
    level whose passes set nothing returns no lines at all, which drops its
    section with them.
    """
    raw_controls = _TRIM_RAW_L8 if level == "l8" else _TRIM_RAW
    lines: list = []
    used_raw: set = set()
    used_ui:  set = set()

    for position, trim in enumerate(trims or []):
        raw = _controls(trim, raw_controls, _num)
        ui  = _controls(trim.get("ui") or {}, _TRIM_UI, _scaled)
        if not raw and not ui:
            continue
        target = f"{_num(trim.get('nits'))} nits"
        index  = trim.get("target_display_index")
        if index is not None:
            target += f" (#{_num(index)})"
        if raw:
            used_raw.update(code for code, _text in raw)
            lines.append((WIDE, f"{level}.{position}.raw",
                          f"{target}   " + _line(raw)))
        if ui:
            used_ui.update(code for code, _text in ui)
            lines.append((WIDE, f"{level}.{position}.ui", "UI   " + _line(ui)))

    legends = []
    for prefix, controls, used, name in (
        ("Raw", raw_controls, used_raw, "raw"),
        ("UI ", _TRIM_UI,     used_ui,  "ui"),
    ):
        if used:
            legends.append((
                WIDE,
                f"{level}.legend.{name}",
                _legend(prefix, [entry for entry in controls
                                 if entry[0] in used]),
            ))
    return legends + lines


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


# --- Row model -------------------------------------------------------------

def build_rows(parsed: dict | None = None) -> list[tuple[str, str, str]]:
    """Return the debug view's rows for the frame on screen.

    Reads the current side data unless a parse result is passed in.  Every
    section is laid out in the same order every time, but only the readings the
    stream carries survive it: a block this stream has no data for takes no
    room, so what is on screen is what the bitstream said and the sections that
    are there can be read without hunting between empty ones.
    """
    if parsed is None:
        parsed = get_sidedata()
    parsed = parsed if isinstance(parsed, dict) else {}

    rpu = parsed.get("rpu")
    rows: list[tuple[str, str, str]] = []

    _section(rows, "Stream", _stream_pairs(parsed))
    _section(rows, "Configuration record (dvcC / dvvC)",
             _config_pairs(parsed.get("config")))
    _section(rows, "RPU", _rpu_pairs(rpu))
    _section(rows, "L1 — Frame luminance", _l1_pairs(rpu))
    _section(rows, "Source PQ range", _source_pairs(rpu))
    _section(rows, "L2 — Trims", _trim_entries("l2", (rpu or {}).get("l2")))
    _section(rows, "L3 — PQ offsets", _l3_pairs(rpu))
    _section(rows, "L5 — Active area", _l5_pairs(rpu))
    _section(rows, "L6 — RPU mastering display", _l6_pairs(rpu))
    _section(rows, "L8 — Trims", _trim_entries("l8", (rpu or {}).get("l8")))
    _section(rows, "L9 — Source primaries", _l9_pairs(rpu))
    _section(rows, "L10 — Target displays", _l10_pairs((rpu or {}).get("l10")))
    _section(rows, "L11 — Content type", _l11_pairs(rpu))
    _section(rows, "Static metadata (MDCV / CLL)",
             _static_pairs(parsed.get("mdcv"), parsed.get("cll")))

    hdr10plus = parsed.get("hdr10plus")
    if hdr10plus:
        _section(rows, "HDR10+ (ST 2094-40)", _hdr10plus_pairs(hdr10plus))

    if not rows:
        # Nothing was parsed at all -- no module, no side data, a frame that
        # arrived empty.  An empty window would read as a broken view rather
        # than as an answer, so say which it is.
        rows.append((SECTION, "No metadata in this frame", ""))

    return rows
