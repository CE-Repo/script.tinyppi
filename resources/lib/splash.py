"""Start-up / OSD format-logo overlay.

On ``Player.OnAVStart`` the service (monitor.py) launches this via
``RunScript(script.tinyppi,splash)``.  It stacks two logos in a corner – the
HDR/video format on top, the audio format below.  Three settings triggers decide
when they show: ``splash_enabled`` (first ``splash_duration`` seconds),
``splash_show_on_osd`` (while the video OSD is open) and ``splash_show_on_tinyppi``
(while the TinyPPI overlay is open).

Logos are added as ``ControlImage`` controls directly onto the fullscreen video
window (12005) and toggled via a visibility condition (see ``_fade_in`` /
``_fade_out``); drawing straight onto the video window keeps playback controls
usable, unlike a modeless dialog.  Logos are re-resolved every poll, so an
audio-track change follows live.
"""

import binascii
import math
import os
import struct
import time
import zlib

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs

from maps import AUDIO_LOGO_MAP, HDR_LOGO_MAP
from theme import apply_theme
from utils import PROP_ACTIVE, PROP_DIALOG_MODE, PROP_RUNNING, info

_ADDON      = xbmcaddon.Addon()
_MEDIA_PATH = os.path.join(
    _ADDON.getAddonInfo("path"), "resources", "skins", "Default", "media"
)

# Kodi window ids / Home-window guard property.
WINDOW_FULLSCREEN_VIDEO = 12005
_HOME_WINDOW_ID         = 10000

# Re-entry guard so overlapping playback starts cannot stack two controllers;
# on the Home window because each RunScript call is a separate process.
PROP_SPLASH_ACTIVE = "TinyPPI.SplashActive"

# ControlImage aspect-ratio modes: keep for the logos, stretch for the panel.
_ASPECT_KEEP    = 2
_ASPECT_STRETCH = 0

# Background panel: a rounded rectangle assembled 9-slice from a 1x1 fill and
# four rounded-corner masks, all tinted the same ARGB colour.
_BG_TEXTURE     = os.path.join("common", "dot-1x1.png")
_DIVIDER_COLOR  = "59FFFFFF"
_CORNER_TEXTURES = {
    "tl": os.path.join("splash", "corner-tl.png"),
    "tr": os.path.join("splash", "corner-tr.png"),
    "bl": os.path.join("splash", "corner-bl.png"),
    "br": os.path.join("splash", "corner-br.png"),
}

# Fallback ARGB colours used only before theme.apply_theme has published the
# themed Home-window properties.
_BG_COLOR   = "FA15181A"  # Charcoal panel (matches the overlay background)
_LOGO_COLOR = "FFEDEDED"  # near-white (leaves white logos unchanged)

# Home-window properties published by theme.apply_theme for the splash colours.
_PROP_BG_COLOR      = "TinyPPI.SplashBackgroundColor"
_PROP_VIDEO_COLOR   = "TinyPPI.SplashVideoColor"
_PROP_AUDIO_COLOR   = "TinyPPI.SplashAudioColor"
_PROP_DIVIDER_COLOR = "TinyPPI.SplashDividerColor"

# Controller poll interval (seconds).
_POLL_INTERVAL = 0.25

# Fade in/out.  Kodi only plays "Visible"/"Hidden" animations on runtime-added
# controls when a *visibility condition* changes value (setVisible() alone does
# not), so the controls watch a global guard plus a per-mode Home-window
# property.  External conditions (VideoOSD / TinyPPI state) can then start the
# fades immediately once the controls have been preloaded.
PROP_SPLASH_VISIBLE = "TinyPPI.SplashVisible"
_VISIBLE_CONDITION  = (
    f"String.IsEqual(Window({_HOME_WINDOW_ID}).Property({PROP_SPLASH_VISIBLE}),true)"
)
_MODE_VISIBLE_PROPS = {
    "start":   "TinyPPI.SplashStartVisible",
    "osd":     "TinyPPI.SplashOsdVisible",
    "tinyppi": "TinyPPI.SplashTinyPPIVisible",
}
_FADE_IN_MS       = 350
_FADE_OUT_MS      = 150
_FADE_OUT_SECONDS = (_FADE_OUT_MS + 60) / 1000.0  # wait a touch past the fade
_RENDER_TICK      = 0.05  # one render frame, so Kodi settles a state change
_ANIM_IN  = ("Visible",
             f"effect=fade start=0 end=100 time={_FADE_IN_MS} tween=cubic easing=inout")
_ANIM_OUT = ("Hidden",
             f"effect=fade start=100 end=0 time={_FADE_OUT_MS}")

# Per-mode horizontal / vertical offset settings (priority when several are
# active: TinyPPI overlay > OSD > start-up window).
_OFFSET_SETTINGS = {
    "start":   ("splash_start_offset_x",   "splash_start_offset_y"),
    "osd":     ("splash_osd_offset_x",     "splash_osd_offset_y"),
    "tinyppi": ("splash_tinyppi_offset_x", "splash_tinyppi_offset_y"),
}

# Per-mode size multiplier (stored 80–130 %, default 100 %); multiplies the base
# layout scale below.
_SCALE_SETTINGS = {
    "start":   "splash_start_scale",
    "osd":     "splash_osd_scale",
    "tinyppi": "splash_tinyppi_scale",
}

# Base layout scale for the logo block; a user scale of 1.0 keeps the original size.
_BASE_SCALE = 0.95

# Kodi does not expose the image resampling filter used by ControlImage.  Keep
# source logos untouched and cache only the display-sized texture when a logo is
# larger than its fitted on-screen size.
_SCALED_LOGO_CACHE = "special://profile/addon_data/script.tinyppi/scaled_logos"
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _amlogic_hdr_token() -> str:
    """Classify the Amlogic output mode (``amlogic.eoft_gamut``) into an
    ``HDR_LOGO_MAP`` key (``''`` for SDR / unknown)."""
    parts = info("Player.Process(amlogic.eoft_gamut)").split()
    mode = parts[0].upper() if parts else ""
    if "DV" in mode or "DOLBY" in mode:
        return "dolbyvision"
    if "HDR10+" in mode or "HDR10PLUS" in mode or "PLUS" in mode:
        return "hdr10+"
    if "HLG" in mode:
        return "hlg"
    if "HDR" in mode:
        return "hdr10"
    return ""


def _current_logos() -> list[str]:
    """Return [video, audio] logos to stack, or [] unless both are available.
    The video logo falls back to SDR, so this effectively gates on the audio codec."""
    codec = info("VideoPlayer.AudioCodec").lower().strip()
    audio_logo = AUDIO_LOGO_MAP.get(codec, "")

    video_logo = HDR_LOGO_MAP.get(_amlogic_hdr_token(), HDR_LOGO_MAP[""])

    if not audio_logo or not video_logo:
        return []
    return [video_logo, audio_logo]


def _translate_path(path: str) -> str:
    try:
        return xbmcvfs.translatePath(path)
    except AttributeError:
        return xbmc.translatePath(path)


def _log_debug(message: str) -> None:
    try:
        xbmc.log(f"TinyPPI splash: {message}", xbmc.LOGDEBUG)
    except Exception:
        pass


def _png_dimensions(path: str) -> tuple[int, int]:
    try:
        with open(path, "rb") as handle:
            header = handle.read(24)
    except Exception:
        return (0, 0)
    if len(header) < 24 or not header.startswith(_PNG_SIGNATURE):
        return (0, 0)
    if header[12:16] != b"IHDR":
        return (0, 0)
    return struct.unpack(">II", header[16:24])


def _fit_size(src_w: int, src_h: int, box_w: int, box_h: int) -> tuple[int, int]:
    if src_w <= 0 or src_h <= 0 or box_w <= 0 or box_h <= 0:
        return (0, 0)
    if src_w * box_h > box_w * src_h:
        return (box_w, max(1, int(round(box_w * src_h / float(src_w)))))
    return (max(1, int(round(box_h * src_w / float(src_h)))), box_h)


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    checksum = binascii.crc32(kind + payload) & 0xFFFFFFFF
    return (
        struct.pack(">I", len(payload))
        + kind
        + payload
        + struct.pack(">I", checksum)
    )


def _paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa = abs(p - a)
    pb = abs(p - b)
    pc = abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def _unfilter_png_scanlines(
    raw: bytes, width: int, height: int, bit_depth: int, color_type: int
) -> list[bytes]:
    bits_per_pixel = {
        0: bit_depth,
        2: bit_depth * 3,
        3: bit_depth,
        4: bit_depth * 2,
        6: bit_depth * 4,
    }[color_type]
    row_len = (width * bits_per_pixel + 7) // 8
    bpp = max(1, (bits_per_pixel + 7) // 8)
    rows = []
    prev = bytearray(row_len)
    pos = 0
    for _ in range(height):
        filter_type = raw[pos]
        pos += 1
        row = bytearray(raw[pos:pos + row_len])
        pos += row_len
        for i, value in enumerate(row):
            left = row[i - bpp] if i >= bpp else 0
            up = prev[i]
            upper_left = prev[i - bpp] if i >= bpp else 0
            if filter_type == 1:
                row[i] = (value + left) & 0xFF
            elif filter_type == 2:
                row[i] = (value + up) & 0xFF
            elif filter_type == 3:
                row[i] = (value + ((left + up) // 2)) & 0xFF
            elif filter_type == 4:
                row[i] = (value + _paeth(left, up, upper_left)) & 0xFF
            elif filter_type != 0:
                raise ValueError("unsupported PNG filter")
        rows.append(bytes(row))
        prev = row
    return rows


def _palette_indices(row: bytes, width: int, bit_depth: int) -> list[int]:
    if bit_depth == 8:
        return list(row[:width])
    indices = []
    mask = (1 << bit_depth) - 1
    for byte in row:
        for shift in range(8 - bit_depth, -1, -bit_depth):
            indices.append((byte >> shift) & mask)
            if len(indices) == width:
                return indices
    return indices


def _decode_png_rgba(path: str) -> tuple[int, int, list[tuple[int, int, int, int]]]:
    with open(path, "rb") as handle:
        data = handle.read()
    if not data.startswith(_PNG_SIGNATURE):
        raise ValueError("not a PNG")

    pos = len(_PNG_SIGNATURE)
    width = height = bit_depth = color_type = interlace = 0
    palette: list[tuple[int, int, int]] = []
    transparency = b""
    idat = []

    while pos < len(data):
        length = struct.unpack(">I", data[pos:pos + 4])[0]
        kind = data[pos + 4:pos + 8]
        payload = data[pos + 8:pos + 8 + length]
        pos += 12 + length
        if kind == b"IHDR":
            (
                width, height, bit_depth, color_type,
                compression, filter_method, interlace,
            ) = struct.unpack(">IIBBBBB", payload)
            if compression != 0 or filter_method != 0 or interlace != 0:
                raise ValueError("unsupported PNG format")
        elif kind == b"PLTE":
            palette = [
                tuple(payload[i:i + 3])
                for i in range(0, len(payload), 3)
            ]
        elif kind == b"tRNS":
            transparency = payload
        elif kind == b"IDAT":
            idat.append(payload)
        elif kind == b"IEND":
            break

    if bit_depth != 8 and color_type != 3:
        raise ValueError("unsupported PNG bit depth")
    if color_type == 3 and bit_depth not in (1, 2, 4, 8):
        raise ValueError("unsupported indexed PNG bit depth")
    if color_type not in (0, 2, 3, 4, 6):
        raise ValueError("unsupported PNG color type")

    raw = zlib.decompress(b"".join(idat))
    rows = _unfilter_png_scanlines(raw, width, height, bit_depth, color_type)
    pixels: list[tuple[int, int, int, int]] = []

    if color_type == 6:
        for row in rows:
            pixels.extend(
                (row[i], row[i + 1], row[i + 2], row[i + 3])
                for i in range(0, len(row), 4)
            )
    elif color_type == 2:
        transparent = None
        if len(transparency) >= 6:
            transparent = struct.unpack(">HHH", transparency[:6])
        for row in rows:
            for i in range(0, len(row), 3):
                rgb = (row[i], row[i + 1], row[i + 2])
                alpha = 0 if transparent == rgb else 255
                pixels.append((rgb[0], rgb[1], rgb[2], alpha))
    elif color_type == 4:
        for row in rows:
            pixels.extend(
                (row[i], row[i], row[i], row[i + 1])
                for i in range(0, len(row), 2)
            )
    elif color_type == 0:
        transparent = None
        if len(transparency) >= 2:
            transparent = struct.unpack(">H", transparency[:2])[0]
        for row in rows:
            for gray in row:
                alpha = 0 if transparent == gray else 255
                pixels.append((gray, gray, gray, alpha))
    else:
        alphas = list(transparency)
        for row in rows:
            for index in _palette_indices(row, width, bit_depth):
                r, g, b = palette[index]
                alpha = alphas[index] if index < len(alphas) else 255
                pixels.append((r, g, b, alpha))

    return (width, height, pixels)


def _premultiply_rgba(
    pixels: list[tuple[int, int, int, int]]
) -> list[tuple[float, float, float, float]]:
    premultiplied = []
    for r, g, b, a in pixels:
        factor = a / 255.0
        premultiplied.append((r * factor, g * factor, b * factor, float(a)))
    return premultiplied


def _resize_horizontal(
    pixels: list[tuple[float, float, float, float]],
    src_w: int, src_h: int, dst_w: int,
) -> list[tuple[float, float, float, float]]:
    scale = src_w / float(dst_w)
    resized = []
    for y in range(src_h):
        row_start = y * src_w
        for x in range(dst_w):
            left = x * scale
            right = (x + 1) * scale
            start = int(math.floor(left))
            end = min(src_w, int(math.ceil(right)))
            total = 0.0
            r = g = b = a = 0.0
            for src_x in range(start, end):
                weight = min(right, src_x + 1.0) - max(left, float(src_x))
                if weight <= 0:
                    continue
                pr, pg, pb, pa = pixels[row_start + src_x]
                r += pr * weight
                g += pg * weight
                b += pb * weight
                a += pa * weight
                total += weight
            resized.append((r / total, g / total, b / total, a / total))
    return resized


def _resize_vertical(
    pixels: list[tuple[float, float, float, float]],
    src_w: int, src_h: int, dst_h: int,
) -> list[tuple[float, float, float, float]]:
    scale = src_h / float(dst_h)
    resized = []
    for y in range(dst_h):
        top = y * scale
        bottom = (y + 1) * scale
        start = int(math.floor(top))
        end = min(src_h, int(math.ceil(bottom)))
        for x in range(src_w):
            total = 0.0
            r = g = b = a = 0.0
            for src_y in range(start, end):
                weight = min(bottom, src_y + 1.0) - max(top, float(src_y))
                if weight <= 0:
                    continue
                pr, pg, pb, pa = pixels[src_y * src_w + x]
                r += pr * weight
                g += pg * weight
                b += pb * weight
                a += pa * weight
                total += weight
            resized.append((r / total, g / total, b / total, a / total))
    return resized


def _clamp_byte(value: float) -> int:
    return max(0, min(255, int(round(value))))


def _unpremultiply_rgba(
    pixels: list[tuple[float, float, float, float]]
) -> bytes:
    rgba = bytearray()
    for r, g, b, a in pixels:
        alpha = _clamp_byte(a)
        if alpha == 0:
            rgba.extend((0, 0, 0, 0))
        else:
            rgba.extend((
                _clamp_byte(r * 255.0 / alpha),
                _clamp_byte(g * 255.0 / alpha),
                _clamp_byte(b * 255.0 / alpha),
                alpha,
            ))
    return bytes(rgba)


def _write_png_rgba(path: str, width: int, height: int, rgba: bytes) -> None:
    rows = bytearray()
    stride = width * 4
    for y in range(height):
        rows.append(0)
        rows.extend(rgba[y * stride:(y + 1) * stride])
    payload = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    png = (
        _PNG_SIGNATURE
        + _png_chunk(b"IHDR", payload)
        + _png_chunk(b"IDAT", zlib.compress(bytes(rows), 9))
        + _png_chunk(b"IEND", b"")
    )
    with open(path, "wb") as handle:
        handle.write(png)


def _scale_png_for_display(src_path: str, dst_path: str, dst_w: int, dst_h: int) -> None:
    src_w, src_h, pixels = _decode_png_rgba(src_path)
    premultiplied = _premultiply_rgba(pixels)
    resized = _resize_horizontal(premultiplied, src_w, src_h, dst_w)
    resized = _resize_vertical(resized, dst_w, src_h, dst_h)
    _write_png_rgba(dst_path, dst_w, dst_h, _unpremultiply_rgba(resized))


def _display_texture(path: str, box_w: int, box_h: int) -> str:
    if not path.lower().endswith(".png"):
        return path

    src_w, src_h = _png_dimensions(path)
    dst_w, dst_h = _fit_size(src_w, src_h, box_w, box_h)
    if not dst_w or (src_w <= dst_w and src_h <= dst_h):
        return path

    try:
        stat = os.stat(path)
        cache_dir = _translate_path(_SCALED_LOGO_CACHE)
        os.makedirs(cache_dir, exist_ok=True)
        name = os.path.splitext(os.path.basename(path))[0]
        cache_name = (
            f"{name}_{src_w}x{src_h}_{dst_w}x{dst_h}_"
            f"{int(stat.st_mtime)}_{stat.st_size}.png"
        )
        cache_path = os.path.join(cache_dir, cache_name)
        if not os.path.exists(cache_path):
            _scale_png_for_display(path, cache_path, dst_w, dst_h)
        return cache_path
    except Exception as exc:
        _log_debug(f"scaled logo cache failed for {os.path.basename(path)}: {exc}")
        return path


def _make_image(rel_path: str, x: int, y: int, w: int, h: int, color: str) -> xbmcgui.ControlImage:
    """Build a keep-aspect, tinted ``ControlImage`` from a media-relative path."""
    full_path = os.path.join(_MEDIA_PATH, rel_path.replace("/", os.sep))
    texture = _display_texture(full_path, w, h)
    return xbmcgui.ControlImage(
        x, y, w, h, texture, aspectRatio=_ASPECT_KEEP, colorDiffuse=color,
    )


def _solid(x: int, y: int, w: int, h: int, color: str) -> xbmcgui.ControlImage:
    """Return a stretched, solid-colour fill built from the 1x1 texture."""
    texture = os.path.join(_MEDIA_PATH, _BG_TEXTURE)
    return xbmcgui.ControlImage(
        x, y, max(1, w), max(1, h), texture,
        aspectRatio=_ASPECT_STRETCH, colorDiffuse=color,
    )


def _panel_controls(
    x: int, y: int, w: int, h: int, radius: int, color: str
) -> list[xbmcgui.ControlImage]:
    """Assemble a rounded rectangle from a centre fill, four edges and corners."""
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


def _build_controls(
    logos: list[str], colors: dict[str, str],
    offset_x: int, offset_y: int, screen_w: int, screen_h: int,
    user_scale: float = 1.0,
) -> list[xbmcgui.ControlImage]:
    """Lay out the logos as a vertical stack, sized to the skin.

    Sizes are fractions of the window's coordinate space so placement holds up
    across 720p / 1080p skins.  ``offset_x`` / ``offset_y`` (0–100 %) slide the
    block from a top-left inset (0 %) to the bottom-right corner (100 %);
    ``user_scale`` resizes it.  A rounded panel is drawn first (behind the
    logos); it and the divider are shown/hidden purely by their themed opacity.
    ``colors`` supplies the ARGB tints keyed by ``bg`` / ``video`` / ``audio`` /
    ``divider``.
    """
    if not logos:
        return []

    # Overall size multiplier: base layout scale times the per-mode user scale.
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

    # Slide the panel across the screen, keeping a corner inset at 0 % and a
    # smaller gap at 100 % so it never sits perfectly flush.
    inset = int(screen_h * 0.0325)
    edge  = 35
    offset_x = min(100, max(0, offset_x))
    offset_y = min(100, max(0, offset_y))
    panel_x = inset + max(0, screen_w - panel_w - inset - edge) * offset_x // 100
    panel_y = inset + max(0, screen_h - panel_h - inset - edge) * offset_y // 100
    block_x = panel_x + pad_x
    top     = panel_y + pad_y

    controls: list[xbmcgui.ControlImage] = []

    # Rounded background panel (behind the logos) plus a divider between them;
    # both are always present and hidden via their themed opacity.
    controls.extend(_panel_controls(
        block_x - pad_x, top - pad_y,
        box_w + 2 * pad_x, panel_h,
        radius, colors["bg"],
    ))
    if count == 2:
        div_h = max(1, int(screen_h * 0.0025 * scale))
        div_y = top + box_h + v_gap // 2 - div_h // 2
        controls.append(_solid(block_x, div_y, box_w, div_h, colors["divider"]))

    # Logos, top to bottom: video (HDR) first, then audio.
    logo_colors = (colors["video"], colors["audio"])
    for index, logo in enumerate(logos):
        y = top + index * (box_h + v_gap)
        controls.append(_make_image(logo, block_x, y, box_w, box_h, logo_colors[index]))
    return controls


def _window_dims(window) -> tuple[int, int]:
    """Return the coordinate-space size ``addControl`` uses on *window*.

    Uses ``Window.getWidth()`` / ``getHeight()`` (the system added controls are
    positioned in), which can differ from the global screen size; falls back to
    the screen size when the window reports no usable values.
    """
    try:
        width, height = window.getWidth(), window.getHeight()
    except Exception:
        width = height = 0
    if width >= 640 and height >= 480:
        return width, height
    return xbmcgui.getScreenWidth(), xbmcgui.getScreenHeight()


def _read_triggers(addon) -> tuple[bool, bool, bool]:
    """Return the ``(start, osd, tinyppi)`` trigger toggles from the settings."""
    return (
        addon.getSettingBool("splash_enabled"),
        addon.getSettingBool("splash_show_on_osd"),
        addon.getSettingBool("splash_show_on_tinyppi"),
    )


def _read_colors(home, addon) -> dict[str, str]:
    """Publish the themed colours and read the splash tints back off *home*."""
    apply_theme(home, addon)
    return {
        "bg":      home.getProperty(_PROP_BG_COLOR) or _BG_COLOR,
        "video":   home.getProperty(_PROP_VIDEO_COLOR) or _LOGO_COLOR,
        "audio":   home.getProperty(_PROP_AUDIO_COLOR) or _LOGO_COLOR,
        "divider": home.getProperty(_PROP_DIVIDER_COLOR) or _DIVIDER_COLOR,
    }


def _mode_scale(addon, mode: str) -> float:
    """Return the size multiplier for *mode* (setting stored as 80–130 %),
    clamped to 0.8–1.3."""
    try:
        percent = addon.getSettingInt(_SCALE_SETTINGS[mode])
    except Exception:
        return 1.0
    return min(1.3, max(0.8, percent / 100.0))


def _home_prop_condition(prop: str, expected: bool = True) -> str:
    """Return a Kodi visibility fragment for a true/false Home property."""
    condition = f"String.IsEqual(Window({_HOME_WINDOW_ID}).Property({prop}),true)"
    return condition if expected else f"!{condition}"


def _visible_condition(mode: str, suppress_start_for_osd: bool = False) -> str:
    """Return the Kodi visibility condition used by controls for *mode*."""
    parts = [
        _VISIBLE_CONDITION,
        _home_prop_condition(_MODE_VISIBLE_PROPS[mode]),
    ]
    if mode == "start":
        parts.extend((
            _home_prop_condition(PROP_RUNNING, False),
            _home_prop_condition(PROP_DIALOG_MODE, False),
        ))
        if suppress_start_for_osd:
            parts.append("!Window.IsVisible(videoosd)")
    elif mode == "osd":
        parts.extend((
            "Window.IsVisible(videoosd)",
            _home_prop_condition(PROP_RUNNING, False),
            _home_prop_condition(PROP_DIALOG_MODE, False),
        ))
    elif mode == "tinyppi":
        parts.extend((
            _home_prop_condition(PROP_ACTIVE),
            _home_prop_condition(PROP_DIALOG_MODE, False),
        ))
    return " + ".join(parts)


def _clear_mode_visibility(home, mode: str | None = None) -> None:
    """Clear one mode visibility property, or all mode properties."""
    props = (_MODE_VISIBLE_PROPS[mode],) if mode else _MODE_VISIBLE_PROPS.values()
    for prop in props:
        home.clearProperty(prop)


def _fade_in(video_window, home, monitor, mode: str, controls, condition: str) -> None:
    """Add *controls* to the video window and fade them in.

    The ordering is load-bearing (deviating makes the logos pop or flash):

    1. Force-hide every control *before* adding it, so freshly added controls
       don't flash at full opacity before their condition is first evaluated.
    2. Bind the visibility condition with the property cleared and before arming
       any animation, so the initial edge cannot play a "Hidden" fade.
    3. Wait one render tick to settle the hidden state.
    4. Arm the animations (only works once the controls belong to a window),
       then lift the force-hide — the condition is still false.
    5. Wait a tick, then flip the property false→true to play the "Visible" fade.
    """
    home.clearProperty(_MODE_VISIBLE_PROPS[mode])
    for control in controls:
        control.setVisible(False)
    video_window.addControls(controls)
    for control in controls:
        control.setVisibleCondition(condition, False)
    monitor.waitForAbort(_RENDER_TICK)
    for control in controls:
        control.setAnimations([_ANIM_IN, _ANIM_OUT])
    for control in controls:
        control.setVisible(True)
    monitor.waitForAbort(_RENDER_TICK)
    home.setProperty(PROP_SPLASH_VISIBLE, "true")
    home.setProperty(_MODE_VISIBLE_PROPS[mode], "true")


def _remove_controls(video_window, controls) -> None:
    """Remove controls from the video window, ignoring already-closed windows."""
    try:
        video_window.removeControls(controls)
    except Exception:
        # The video window may already be gone; a failed removal is harmless.
        pass


def _fade_out(video_window, home, monitor, mode: str, controls) -> None:
    """Fade *controls* out (condition true→false), await it, remove them."""
    home.clearProperty(_MODE_VISIBLE_PROPS[mode])
    monitor.waitForAbort(_FADE_OUT_SECONDS)
    try:
        video_window.removeControls(controls)
    except Exception:
        # The video window may already be gone; a failed removal is harmless.
        pass


def open_splash() -> None:
    """Run the logo overlay controller for the current video's lifetime.

    Each poll prepares the enabled modes (start-up, VideoOSD, TinyPPI overlay)
    and lets Kodi's visibility conditions start the actual fades immediately.
    Rebuilds still happen on offset / scale / colour / format changes.  Skips
    silently when all triggers are off, no video plays, or another controller is
    running.
    """
    show_on_start, show_on_osd, show_on_tinyppi = _read_triggers(xbmcaddon.Addon())
    if not show_on_start and not show_on_osd and not show_on_tinyppi:
        return

    player = xbmc.Player()
    if not player.isPlayingVideo():
        return

    home = xbmcgui.Window(_HOME_WINDOW_ID)
    if home.getProperty(PROP_SPLASH_ACTIVE) == "true":
        return

    if not _current_logos():
        return

    video_window = xbmcgui.Window(WINDOW_FULLSCREEN_VIDEO)
    screen_w, screen_h = _window_dims(video_window)
    monitor = xbmc.Monitor()

    home.setProperty(PROP_SPLASH_ACTIVE, "true")
    home.clearProperty(PROP_SPLASH_VISIBLE)
    _clear_mode_visibility(home)
    controls_by_mode: dict[str, list[xbmcgui.ControlImage]] = {}
    states: dict[str, tuple] = {}
    try:
        started = time.monotonic()
        while not monitor.abortRequested():
            if not player.isPlayingVideo():
                break

            # Read settings from a fresh Addon() each poll: an Addon caches its
            # settings at construction, so a new instance is needed to pick up
            # live edits without restarting playback.
            addon = xbmcaddon.Addon()
            show_on_start, show_on_osd, show_on_tinyppi = _read_triggers(addon)
            duration = addon.getSettingInt("splash_duration")

            now = time.monotonic()
            in_fullscreen = xbmc.getCondVisibility("Window.IsActive(fullscreenvideo)")
            in_start_window = show_on_start and (now - started < duration)

            desired_states: dict[str, tuple] = {}
            colors = None
            if in_fullscreen:
                logos = _current_logos()
                if logos:
                    modes = []
                    if show_on_start and in_start_window:
                        modes.append("start")
                    if show_on_osd:
                        modes.append("osd")
                    if show_on_tinyppi:
                        modes.append("tinyppi")

                    if modes:
                        colors = _read_colors(home, addon)
                        color_state = tuple(sorted(colors.items()))
                        for mode in modes:
                            setting_x, setting_y = _OFFSET_SETTINGS[mode]
                            desired_states[mode] = (
                                tuple(logos),
                                addon.getSettingInt(setting_x),
                                addon.getSettingInt(setting_y),
                                _mode_scale(addon, mode),
                                color_state,
                                _visible_condition(mode, show_on_osd),
                            )

            remove_modes = [
                mode for mode in tuple(controls_by_mode)
                if mode not in desired_states
            ]
            if remove_modes:
                for mode in remove_modes:
                    home.clearProperty(_MODE_VISIBLE_PROPS[mode])
                monitor.waitForAbort(_FADE_OUT_SECONDS)
                for mode in remove_modes:
                    _remove_controls(video_window, controls_by_mode[mode])
                    controls_by_mode.pop(mode, None)
                    states.pop(mode, None)

            for mode, desired in desired_states.items():
                if states.get(mode) == desired:
                    continue
                if mode in controls_by_mode:
                    _fade_out(video_window, home, monitor, mode, controls_by_mode[mode])
                controls = _build_controls(
                    list(desired[0]), colors, desired[1], desired[2],
                    screen_w, screen_h, desired[3],
                )
                controls_by_mode[mode] = controls
                states[mode] = desired
                _fade_in(video_window, home, monitor, mode, controls, desired[5])

            if not show_on_osd and not show_on_tinyppi and not in_start_window and not states:
                break

            wait_time = _POLL_INTERVAL
            if show_on_start and in_start_window:
                remaining = duration - (time.monotonic() - started)
                if remaining > 0:
                    wait_time = min(wait_time, remaining)

            if monitor.waitForAbort(wait_time):
                break
    finally:
        for controls in controls_by_mode.values():
            _remove_controls(video_window, controls)
        home.clearProperty(PROP_SPLASH_VISIBLE)
        _clear_mode_visibility(home)
        home.clearProperty(PROP_SPLASH_ACTIVE)
