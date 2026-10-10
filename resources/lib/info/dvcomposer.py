# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""The composer's rows for the Dolby Vision metadata view (RPU data mapping).

The reshaping curves and the NLQ table that rebuild the picture from the
base layer.  Their coefficients are the only derived values in the view:
the RPU splits each into two halves (see ``_coefficient``).
"""

from collections.abc import Sequence

from info import dvformat as fmt
from info.dvformat import COLUMNS, EMPTY, HEADINGS, MAX_COLUMNS, SPACE

# The three reshaping curves in module order, named by component; also the
# NLQ table's columns.
CURVE_COMPONENTS = ("Y", "Cb", "Cr")

# Curve shapes by ``mapping_idc``; unknown codes are shown as is.
_MAPPING_IDC_NAMES: dict[int | None, str] = {0: "Polynomial", 1: "MMR"}

# Composer table legends and leading columns: polynomial segments start
# with order and interpolation, MMR segments with order and constant.
_LEGEND_SEGMENT   = "Segment"
_LEGEND_TERM      = "Term"
_LEGEND_COMPONENT = "Component"
_POLY_HEADINGS    = ("Order", "Linear interp")
_MMR_HEADINGS     = ("Order", "Constant")


def _coefficient(int_part: object, frac_part: object, denom: object) -> str:
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


def _grid(legend: str, headings: Sequence[str],
          rows: Sequence[tuple[str, Sequence[str]]]) -> list:
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


def _denominator(rpu: dict | None) -> object:
    """Return the header's ``coefficient_log2_denom``."""
    return ((rpu or {}).get("header") or {}).get("coefficient_log2_denom")


def composer_pairs(rpu: dict | None) -> list:
    """Return the composer scalars: RPU id, colour space, partitions, NLQ."""
    mapping = _mapping(rpu)
    pivots  = mapping.get("nlq_pred_pivot_value") or []
    return [
        ("VDR RPU ID", fmt.num(mapping.get("vdr_rpu_id"))),
        ("Mapping colour space", fmt.num(mapping.get("mapping_color_space"))),
        ("Mapping chroma format",
         fmt.num(mapping.get("mapping_chroma_format_idc"))),
        ("Partitions (x | y)", fmt.joined(fmt.num(mapping.get("num_x_partitions")),
                                       fmt.num(mapping.get("num_y_partitions")))),
        ("NLQ method", fmt.num(mapping.get("nlq_method_idc"))),
        ("NLQ pivots", fmt.num(mapping.get("nlq_num_pivots"))),
        ("NLQ pivot values", fmt.joined(*(fmt.num(value) for value in pivots))),
    ]


def _polynomial_entries(polynomial: dict | None, denom: object) -> list:
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
            fmt.num(orders[segment]) if segment < len(orders) else EMPTY,
            fmt.flag(interp[segment]) if segment < len(interp) else EMPTY,
        ]
        cells.extend(
            _coefficient(value, fracs[term] if term < len(fracs) else 0, denom)
            for term, value in enumerate(ints)
        )
        rows.append((f"Segment {segment + 1}", cells))
    return _grid(_LEGEND_SEGMENT, headings, rows)


def _mmr_entries(mmr: dict | None, denom: object) -> list:

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
            fmt.num(orders[segment]) if segment < len(orders) else EMPTY,
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


def curve_entries(rpu: dict | None, index: int) -> list:
    """Return one component's curve: shape, pivots and coefficients."""
    curves = _mapping(rpu).get("curves") or []
    curve  = (curves[index] if index < len(curves) else None) or {}
    if not curve:
        return []

    idc     = curve.get("mapping_idc")
    pivots  = curve.get("pivots") or []
    entries: list = [
        ("Shape", fmt.text(_MAPPING_IDC_NAMES.get(idc, fmt.num(idc)))),
        ("Pivots", fmt.num(curve.get("num_pivots"))),
        ("Pivot codewords", fmt.joined(*(fmt.num(value) for value in pivots))),
    ]

    denom = _denominator(rpu)
    table = (_polynomial_entries(curve.get("polynomial"), denom) +
             _mmr_entries(curve.get("mmr"), denom))
    if table:
        entries.append((SPACE, f"space.curve.{index}", ""))
        entries.extend(table)
    return entries


def nlq_entries(rpu: dict | None) -> list:
    """Return the NLQ dequantization data, one column per component.

    Dual-layer profiles (4 and 7) only.
    """
    nlq = _mapping(rpu).get("nlq") or {}
    if not nlq:
        return []

    denom = _denominator(rpu)
    rows  = [("Offset", [fmt.num(value) for value in nlq.get("nlq_offset") or []])]
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
    return _grid(_LEGEND_COMPONENT, list(CURVE_COMPONENTS), rows)
