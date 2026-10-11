# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""The splash's panel: logos stacked on a rounded, tinted background.

Builds the ``ControlImage`` controls ``ui.splash`` adds to the fullscreen
video window; sizes are fractions of the window's coordinate space
(``window_dims``).
"""

import os

import xbmcgui
from core import settings
from core.images import display_texture

_MEDIA_PATH = os.path.join(
    settings.addon().getAddonInfo("path"), "resources", "skins", "Default", "media"
)

# ControlImage aspect-ratio modes: keep for the logos, stretch for the panel.
_ASPECT_KEEP    = 2
_ASPECT_STRETCH = 0

# Background panel: 9-slice rounded rectangle from a 1x1 fill and four corner
# masks, tinted with one ARGB colour.
_BG_TEXTURE = os.path.join("common", "dot-1x1.png")
_CORNER_TEXTURES = {
    "tl": os.path.join("splash", "corner-tl.png"),
    "tr": os.path.join("splash", "corner-tr.png"),
    "bl": os.path.join("splash", "corner-bl.png"),
    "br": os.path.join("splash", "corner-br.png"),
}
# Conversion badge in the panel's top-right corner (see is_converting).
_DOT_TEXTURE = os.path.join("common", "dot-circle.png")
# DV layer pill on the panel's bottom (or top) edge (see dv_layer_token).
_PILL_TEXTURE = os.path.join("common", "pill.png")

# Base scale of the logo block (at a user scale of 100 %).
_BASE_SCALE = 0.95


def _make_image(rel_path: str, x: int, y: int, w: int, h: int, color: str) -> xbmcgui.ControlImage:
    """Build a tinted, aspect-keeping image from a media-relative path."""
    full_path = os.path.join(_MEDIA_PATH, rel_path.replace("/", os.sep))
    texture = display_texture(full_path, w, h)
    return xbmcgui.ControlImage(
        x, y, w, h, texture, aspectRatio=_ASPECT_KEEP, colorDiffuse=color,
    )


def _make_dot(cx: int, cy: int, diameter: int, color: str) -> xbmcgui.ControlImage:
    """Build a filled circle centred on (*cx*, *cy*)."""
    return _make_image(
        _DOT_TEXTURE,
        cx - diameter // 2, cy - diameter // 2, diameter, diameter, color,
    )


def _solid(x: int, y: int, w: int, h: int, color: str) -> xbmcgui.ControlImage:
    """Return a solid-colour rectangle from the 1x1 texture."""
    texture = os.path.join(_MEDIA_PATH, _BG_TEXTURE)
    return xbmcgui.ControlImage(
        x, y, max(1, w), max(1, h), texture,
        aspectRatio=_ASPECT_STRETCH, colorDiffuse=color,
    )


def _panel_controls(
    x: int, y: int, w: int, h: int, radius: int, color: str
) -> list[xbmcgui.ControlImage]:
    """Build a rounded rectangle from a centre, four edges and four corners."""
    c = max(1, min(radius, w // 2, h // 2))
    corner = lambda key, cx, cy: xbmcgui.ControlImage(  # noqa: E731
        cx, cy, c, c, os.path.join(_MEDIA_PATH, _CORNER_TEXTURES[key]),
        aspectRatio=_ASPECT_STRETCH, colorDiffuse=color,
    )
    return [
        _solid(x + c, y + c, w - 2 * c, h - 2 * c, color),  # centre
        _solid(x + c, y, w - 2 * c, c, color),              # top edge
        _solid(x + c, y + h - c, w - 2 * c, c, color),      # bottom edge
        _solid(x, y + c, c, h - 2 * c, color),              # left edge
        _solid(x + w - c, y + c, c, h - 2 * c, color),      # right edge
        corner("tl", x, y),
        corner("tr", x + w - c, y),
        corner("bl", x, y + h - c),
        corner("br", x + w - c, y + h - c),
    ]


def build_controls(
    logos: list[tuple[str, str]], colors: dict[str, str],
    offset_x: int, offset_y: int, screen_w: int, screen_h: int,
    user_scale: float = 1.0, layer_token: str = "", pill_at_top: bool = False,
) -> tuple[list[xbmcgui.ControlImage], xbmcgui.ControlImage | None]:
    """Lay out the logos as a vertical stack on a rounded panel.

    *logos* are ``(logo, colour key)`` pairs, top first; a single logo has
    no divider.  Sizes are fractions of the window's coordinate space.
    *offset_x* / *offset_y* (0-100 %) move the panel from the top-left inset
    to the bottom-right; *user_scale* resizes it.  *colors* holds the tints
    by key; *layer_token* picks the DV pill colour ('' for no pill), and
    *pill_at_top* moves the pill to the top edge.

    Returns ``(controls, dot)``; *dot* is the conversion badge (also in
    *controls*) for its own condition, None when there are no logos.
    """
    if not logos:
        return [], None

    # Base scale times the mode's own scale.
    scale = _BASE_SCALE * user_scale

    box_w    = int(screen_w * 0.09 * scale)
    box_h    = int(screen_h * 0.055 * scale)
    v_gap    = int(screen_h * 0.02 * scale)
    pad_x    = int(screen_w * 0.012 * scale)
    pad_y    = int(screen_h * 0.02 * scale)
    radius   = int(screen_h * 0.02 * scale)

    count   = len(logos)
    stack_h = count * box_h + (count - 1) * v_gap
    panel_w = box_w + 2 * pad_x
    panel_h = stack_h + 2 * pad_y

    # Position: an inset at 0 %, a smaller gap at 100 %, never flush.
    inset = int(screen_h * 0.0325)
    edge  = 35
    offset_x = min(100, max(0, offset_x))
    offset_y = min(100, max(0, offset_y))
    panel_x = inset + max(0, screen_w - panel_w - inset - edge) * offset_x // 100
    panel_y = inset + max(0, screen_h - panel_h - inset - edge) * offset_y // 100
    block_x = panel_x + pad_x
    top     = panel_y + pad_y

    controls: list[xbmcgui.ControlImage] = []

    # Panel and divider; always present, hidden by their themed opacity.
    controls.extend(_panel_controls(
        block_x - pad_x, top - pad_y,
        box_w + 2 * pad_x, panel_h,
        radius, colors["bg"],
    ))
    if count == 2:
        div_h = max(1, int(screen_h * 0.0025 * scale))
        div_y = top + box_h + v_gap // 2 - div_h // 2
        controls.append(_solid(block_x, div_y, box_w, div_h, colors["divider"]))

    # Logos top to bottom, each tinted by its kind (follows the order).
    for index, (logo, kind) in enumerate(logos):
        y = top + index * (box_h + v_gap)
        controls.append(_make_image(logo, block_x, y, box_w, box_h, colors[kind]))

    # Conversion badge in the top-right corner (condition set by the caller).
    dot_d   = max(1, int(box_h * 0.20))
    dot_pad = max(1, int(box_h * 0.20))
    dot_cx  = panel_x + panel_w - dot_pad - dot_d // 2
    dot_cy  = panel_y + dot_pad + dot_d // 2
    dot = _make_dot(dot_cx, dot_cy, dot_d, colors["convert_dot"])
    controls.append(dot)

    # DV layer pill, centred on the bottom or top edge; none for non-DV.
    if layer_token in ("fel", "mel", "other"):
        pill_w      = max(1, int(box_w * 0.30))
        pill_h      = max(1, int(box_h * 0.15))
        pill_margin = max(1, int(box_h * 0.10))
        pill_x = panel_x + (panel_w - pill_w) // 2
        pill_y = (
            panel_y + pill_margin if pill_at_top
            else panel_y + panel_h - pill_margin - pill_h
        )
        controls.append(
            _make_image(_PILL_TEXTURE, pill_x, pill_y, pill_w, pill_h, colors[layer_token])
        )

    return controls, dot


def window_dims(window: xbmcgui.Window) -> tuple[int, int]:
    """Return the coordinate space ``addControl`` uses on *window*.

    The window's own size, which may differ from the screen size; falls
    back to the screen size when the window reports none.
    """
    try:
        width, height = window.getWidth(), window.getHeight()
    except RuntimeError:  # window not created yet
        width = height = 0
    if width >= 640 and height >= 480:
        return width, height
    return xbmcgui.getScreenWidth(), xbmcgui.getScreenHeight()
