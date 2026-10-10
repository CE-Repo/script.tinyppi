# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""PNG scaling with an on-disk cache of display-sized textures.

Kodi does not let add-ons choose ControlImage's resampling filter, so a
texture much larger than its on-screen box is scaled here (box filter in
premultiplied alpha) and cached in the add-on's profile.  Source images are
never modified.  Used for the codec logos (ui/splash.py).

A cached texture is named after the logo's content and the target size, so
it survives Kodi restarts and add-on updates and is rebuilt only when either
changes.  ``prune_cache`` removes copies that can no longer be requested.
"""

import binascii
import contextlib
import hashlib
import math
import os
import re
import struct
import threading
import time
import zlib

import xbmc
import xbmcvfs
from core.constants import PROFILE_DIR
from core.files import atomic_write
from core.log import channel

# Display-sized textures, keyed by source name, size and content.
_CACHE_DIR = f"{PROFILE_DIR}/scaled_images"
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

# Part of every content key.  Raise it whenever the scaler's output changes,
# so older textures stop matching (and prune_cache removes them).
_SCALER_VERSION = b"2"

# ``<source name>_<width>x<height>_<content key>.png``; anything else in the
# cache was left by an older version or an interrupted build.
_CACHE_NAME = re.compile(
    r"^(?P<stem>.+)_(?P<w>\d+)x(?P<h>\d+)_(?P<key>[0-9a-f]{16})\.png$"
)

# Age after which prune_cache treats a temporary file as abandoned rather
# than still being written.
_STALE_TMP_SECONDS = 600.0

# Content keys per source path, with the (mtime, size) they were computed
# at: a source is hashed again only when it changed on disk, and an update
# that rewrites an unchanged logo costs one hash but no scaling.
_content_keys: dict[str, tuple[tuple[int, int], str]] = {}

# Scale one image at a time (the playback-start prewarm and an overlay poll
# can both reach display_texture); parallel CPU-bound builds only compete for
# the interpreter.
_build_gate = threading.Lock()

# Scaling is CPU-bound pure Python and would starve Kodi's UI and polling
# threads of the interpreter lock for seconds.  A short pause every few rows
# hands the lock over and keeps TinyPPI responsive.
_YIELD_ROWS    = 16
_YIELD_SECONDS = 0.002

# The same for the flat per-pixel passes: about one pause per 16 rows.
_YIELD_PIXELS = 16 * 1024


def _breathe(row: int) -> None:
    """Give other threads the interpreter lock every ``_YIELD_ROWS`` rows."""
    if row % _YIELD_ROWS == _YIELD_ROWS - 1:
        time.sleep(_YIELD_SECONDS)


def _translate_path(path: str) -> str:
    try:
        return xbmcvfs.translatePath(path)
    except AttributeError:
        return xbmc.translatePath(path)


_log = channel("images")


def _log_debug(message: str) -> None:
    with contextlib.suppress(Exception):
        _log(message)


def _png_dimensions(path: str) -> tuple[int, int]:
    try:
        with open(path, "rb") as handle:
            header = handle.read(24)
    except OSError:
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
    for y in range(height):
        _breathe(y)
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
                (payload[i], payload[i + 1], payload[i + 2])
                for i in range(0, len(payload) - 2, 3)
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
    for index, (r, g, b, a) in enumerate(pixels):
        if index % _YIELD_PIXELS == _YIELD_PIXELS - 1:
            time.sleep(_YIELD_SECONDS)
        factor = a / 255.0
        premultiplied.append((r * factor, g * factor, b * factor, float(a)))
    return premultiplied


def _box_taps(src_len: int, dst_len: int) -> list[tuple[int, list[float]]]:
    """Return one box-filter tap per output pixel.

    Each tap is ``(first source index, normalised weights)``; computed once
    per axis and reused for every row or column.
    """
    scale = src_len / float(dst_len)
    taps = []
    for i in range(dst_len):
        low = i * scale
        high = (i + 1) * scale
        start = int(math.floor(low))
        end = min(src_len, int(math.ceil(high)))
        weights = [
            min(high, src + 1.0) - max(low, float(src))
            for src in range(start, end)
        ]
        total = sum(weights) or 1.0
        taps.append((start, [w / total for w in weights]))
    return taps


def _resize_horizontal(
    pixels: list[tuple[float, float, float, float]],
    src_w: int, src_h: int, dst_w: int,
) -> list[tuple[float, float, float, float]]:
    taps = _box_taps(src_w, dst_w)
    resized: list[tuple[float, float, float, float]] = []
    append = resized.append
    for y in range(src_h):
        _breathe(y)
        row_start = y * src_w
        for start, weights in taps:
            r = g = b = a = 0.0
            base = row_start + start
            for offset, weight in enumerate(weights):
                pr, pg, pb, pa = pixels[base + offset]
                r += pr * weight
                g += pg * weight
                b += pb * weight
                a += pa * weight
            append((r, g, b, a))
    return resized


def _resize_vertical(
    pixels: list[tuple[float, float, float, float]],
    src_w: int, src_h: int, dst_h: int,
) -> list[tuple[float, float, float, float]]:
    resized: list[tuple[float, float, float, float]] = []
    append = resized.append
    for y, (start, weights) in enumerate(_box_taps(src_h, dst_h)):
        _breathe(y)
        rows = [(src_y * src_w, weights[offset]) for offset, src_y
                in enumerate(range(start, start + len(weights)))]
        for x in range(src_w):
            r = g = b = a = 0.0
            for row_start, weight in rows:
                pr, pg, pb, pa = pixels[row_start + x]
                r += pr * weight
                g += pg * weight
                b += pb * weight
                a += pa * weight
            append((r, g, b, a))
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
            # Divided by the exact coverage, not the rounded byte: a half
            # covered white edge would otherwise come out as 254.
            scale = 255.0 / a
            rgba.extend((
                _clamp_byte(r * scale),
                _clamp_byte(g * scale),
                _clamp_byte(b * scale),
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
    atomic_write(path, png)


def _scale_png_to_cache(src_path: str, dst_path: str, dst_w: int, dst_h: int) -> None:
    """Scale *src_path* into *dst_path*.

    The file is written atomically (see ``core.files``), so neither a
    concurrent builder nor a power cut can leave a half-written PNG.
    """
    _scale_png_for_display(src_path, dst_path, dst_w, dst_h)


def _scale_png_for_display(src_path: str, dst_path: str, dst_w: int, dst_h: int) -> None:
    src_w, src_h, pixels = _decode_png_rgba(src_path)
    premultiplied = _premultiply_rgba(pixels)
    resized = _resize_horizontal(premultiplied, src_w, src_h, dst_w)
    resized = _resize_vertical(resized, dst_w, src_h, dst_h)
    _write_png_rgba(dst_path, dst_w, dst_h, _unpremultiply_rgba(resized))


def _cache_target(path: str, box_w: int, box_h: int) -> tuple[str, int, int] | None:
    """Return ``(cache_path, dst_w, dst_h)`` for a texture worth scaling.

    None when the source can be used as is: not a PNG, unreadable, or already
    at or below display size (this never upscales).
    """
    if not path.lower().endswith(".png"):
        return None

    src_w, src_h = _png_dimensions(path)
    dst_w, dst_h = _fit_size(src_w, src_h, box_w, box_h)
    if not dst_w or (src_w <= dst_w and src_h <= dst_h):
        return None

    cache_dir = _translate_path(_CACHE_DIR)
    name = os.path.splitext(os.path.basename(path))[0]
    cache_name = f"{name}_{dst_w}x{dst_h}_{_content_key(path)}.png"
    return (os.path.join(cache_dir, cache_name), dst_w, dst_h)


def _content_key(path: str) -> str:
    """Return the key the cached copies of *path* are filed under.

    A content digest rather than the modification time: an add-on update
    rewrites every file, and a time-based key would rescale every logo after
    each update.
    """
    stat = os.stat(path)
    stamp = (stat.st_mtime_ns, stat.st_size)
    held = _content_keys.get(path)
    if held is not None and held[0] == stamp:
        return held[1]
    with open(path, "rb") as handle:
        key = hashlib.blake2b(
            _SCALER_VERSION + handle.read(), digest_size=8
        ).hexdigest()
    _content_keys[path] = (stamp, key)
    return key


def display_texture(path: str, box_w: int, box_h: int) -> str:
    """Return *path* scaled to fit *box_w* x *box_h*, building the cache entry
    if missing.

    Scaling is slow: call this off the UI thread.  Returns *path* unchanged
    when no scaling is needed or the cache cannot be built.
    """
    try:
        target = _cache_target(path, box_w, box_h)
        if target is None:
            return path
        cache_path, dst_w, dst_h = target
        if not os.path.exists(cache_path):
            # Re-check inside the gate: the previous holder may have built
            # this very file.
            with _build_gate:
                if not os.path.exists(cache_path):
                    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
                    _scale_png_to_cache(path, cache_path, dst_w, dst_h)
        return cache_path
    except Exception as exc:
        _log_debug(f"scaled texture failed for {os.path.basename(path)}: {exc}")
        return path


def prune_cache(media_root: str) -> int:
    """Delete cached textures that can no longer be requested; return the count.

    Copies of an unchanged logo are kept at every size, so moving a size
    slider back finds its copy.  Removed are copies of logos that changed or
    are no longer in *media_root*, files named by an older scheme, and
    abandoned temporary files.

    Holds the build gate, so it never races a build in this process; a
    temporary file counts as abandoned only after ``_STALE_TMP_SECONDS``,
    which covers builds in other processes.
    """
    cache_dir = _translate_path(_CACHE_DIR)
    try:
        entries = os.listdir(cache_dir)
    except OSError:
        return 0  # nothing cached yet

    sources: dict[str, list[str]] = {}
    for folder, _dirs, files in os.walk(media_root):
        for file_name in files:
            stem, extension = os.path.splitext(file_name)
            if extension.lower() == ".png":
                sources.setdefault(stem, []).append(os.path.join(folder, file_name))

    removed = 0
    now = time.time()
    with _build_gate:
        current: dict[str, set[str]] = {}
        for entry in entries:
            path = os.path.join(cache_dir, entry)
            try:
                if entry.endswith(".tmp"):
                    stale = now - os.stat(path).st_mtime > _STALE_TMP_SECONDS
                else:
                    match = _CACHE_NAME.match(entry)
                    stale = match is None or match["key"] not in _current_keys(
                        match["stem"], sources, current)
                if stale:
                    os.remove(path)
                    removed += 1
            except OSError as exc:
                _log_debug(f"could not prune {entry}: {exc}")
    return removed


def _current_keys(stem: str, sources: dict, current: dict) -> set[str]:
    """Return the content keys of the sources named *stem*, once per prune."""
    keys = current.get(stem)
    if keys is None:
        keys = set()
        for path in sources.get(stem, ()):
            with contextlib.suppress(OSError):
                keys.add(_content_key(path))
        current[stem] = keys
    return keys
