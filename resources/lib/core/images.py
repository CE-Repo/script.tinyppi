"""PNG scaling with an on-disk cache of display-sized textures.

Kodi does not expose the image resampling filter used by ControlImage, so a
texture much larger than its on-screen box is rescaled here (box filter, in
premultiplied alpha) and the result cached under the add-on's profile
directory.  Source images are never modified.

Used for the codec logos (ui/splash.py) and the channel layout graphics
(info/properties.py).
"""

import binascii
import math
import os
import struct
import threading
import time
import zlib

import xbmc
import xbmcvfs

# Cache of display-sized textures, keyed by source name, size and mtime.
_CACHE_DIR = "special://profile/addon_data/script.tinyppi/scaled_images"
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

# Builds currently running via ensure_texture(), so a caller polling once a
# second does not start the same scale over and over.
_builds: set = set()
_builds_lock = threading.Lock()

# Only ever scale one image at a time (the playback-start prewarm and an overlay
# poll can both reach display_texture): several CPU-bound threads would fight
# each other and Kodi for the interpreter, for no gain.
_build_gate = threading.Lock()

# Scaling is pure Python and CPU-bound, and CPython hands the interpreter lock
# to such a thread again and again — a background build would leave Kodi's UI
# and polling threads waiting seconds for their turn.  Pausing briefly every few
# rows hands the lock over; it costs the build a little and keeps TinyPPI
# responsive while it runs.
_YIELD_ROWS    = 16
_YIELD_SECONDS = 0.002

# Same idea for the flat per-pixel passes: roughly one pause per 16 source rows.
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


def _log_debug(message: str) -> None:
    try:
        xbmc.log(f"TinyPPI images: {message}", xbmc.LOGDEBUG)
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
    for index, (r, g, b, a) in enumerate(pixels):
        if index % _YIELD_PIXELS == _YIELD_PIXELS - 1:
            time.sleep(_YIELD_SECONDS)
        factor = a / 255.0
        premultiplied.append((r * factor, g * factor, b * factor, float(a)))
    return premultiplied


def _box_taps(src_len: int, dst_len: int) -> list[tuple[int, list[float]]]:
    """Return one ``(first source index, normalised weights)`` box-filter tap per
    output pixel, computed once per axis and reused for every row/column."""
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
    resized = []
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
    resized = []
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


def _scale_png_to_cache(src_path: str, dst_path: str, dst_w: int, dst_h: int) -> None:
    """Scale ``src_path`` into ``dst_path`` via a temp file + rename, so a
    concurrent builder never observes a half-written PNG."""
    tmp_path = f"{dst_path}.{os.getpid()}-{threading.get_ident()}.tmp"
    _scale_png_for_display(src_path, tmp_path, dst_w, dst_h)
    try:
        os.replace(tmp_path, dst_path)
    except OSError:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise


def _scale_png_for_display(src_path: str, dst_path: str, dst_w: int, dst_h: int) -> None:
    src_w, src_h, pixels = _decode_png_rgba(src_path)
    premultiplied = _premultiply_rgba(pixels)
    resized = _resize_horizontal(premultiplied, src_w, src_h, dst_w)
    resized = _resize_vertical(resized, dst_w, src_h, dst_h)
    _write_png_rgba(dst_path, dst_w, dst_h, _unpremultiply_rgba(resized))


def _cache_target(path: str, box_w: int, box_h: int):
    """Return ``(cache_path, dst_w, dst_h)`` for a texture worth scaling, or
    ``None`` when the source can be used as-is (not a PNG, unreadable, or
    already at/below display size — this never upscales)."""
    if not path.lower().endswith(".png"):
        return None

    src_w, src_h = _png_dimensions(path)
    dst_w, dst_h = _fit_size(src_w, src_h, box_w, box_h)
    if not dst_w or (src_w <= dst_w and src_h <= dst_h):
        return None

    stat = os.stat(path)
    cache_dir = _translate_path(_CACHE_DIR)
    name = os.path.splitext(os.path.basename(path))[0]
    cache_name = (
        f"{name}_{src_w}x{src_h}_{dst_w}x{dst_h}_"
        f"{int(stat.st_mtime)}_{stat.st_size}.png"
    )
    return (os.path.join(cache_dir, cache_name), dst_w, dst_h)


def display_texture(path: str, box_w: int, box_h: int) -> str:
    """Return ``path`` scaled to fit ``box_w`` x ``box_h`` and cached, building
    the cache entry now if missing.

    Scaling is slow, so only call this off the UI thread (``ready_texture`` is
    the non-blocking counterpart).  Falls back to the source path unchanged if
    no scaling is needed or the cache can't be built.
    """
    try:
        target = _cache_target(path, box_w, box_h)
        if target is None:
            return path
        cache_path, dst_w, dst_h = target
        if not os.path.exists(cache_path):
            # One build at a time, and re-check inside the gate: whoever waited
            # here may have been waiting for this very file.
            with _build_gate:
                if not os.path.exists(cache_path):
                    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
                    _scale_png_to_cache(path, cache_path, dst_w, dst_h)
        return cache_path
    except Exception as exc:
        _log_debug(f"scaled texture failed for {os.path.basename(path)}: {exc}")
        return path


def ready_texture(path: str, box_w: int, box_h: int) -> str:
    """Return the scaled texture only if it is already cached, else ``""``.

    Never scales, so it is safe on the UI thread: callers show the unscaled
    source until a build (see ``ensure_texture``) has finished.
    """
    try:
        target = _cache_target(path, box_w, box_h)
        if target is None:
            return path
        cache_path = target[0]
        return cache_path if os.path.exists(cache_path) else ""
    except Exception as exc:
        _log_debug(f"cache lookup failed for {os.path.basename(path)}: {exc}")
        return path


def ensure_texture(path: str, box_w: int, box_h: int) -> None:
    """Build the scaled texture in the background unless it is cached or already
    being built.  Returns immediately."""
    try:
        target = _cache_target(path, box_w, box_h)
        if target is None or os.path.exists(target[0]):
            return
    except Exception:
        return

    key = (path, box_w, box_h)
    with _builds_lock:
        if key in _builds:
            return
        _builds.add(key)

    threading.Thread(
        target=_build_worker, args=(key,), name="TinyPPI-scale", daemon=True,
    ).start()


def _build_worker(key: tuple) -> None:
    try:
        display_texture(*key)
    finally:
        with _builds_lock:
            _builds.discard(key)
