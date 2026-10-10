# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""PNG decoding, scaling and the texture cache (core/images.py)."""

import os
import struct
import zlib

import pytest

from core import images


def _chunk(kind, payload):
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(
        ">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)


def _paeth(a, b, c):
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    return b if pb <= pc else c


def _filtered(rows, bpp, filters):
    """Encode the scanlines, each with its own filter type (cycled)."""
    out = bytearray()
    previous = bytes(len(rows[0]))
    for index, row in enumerate(rows):
        kind = filters[index % len(filters)]
        out.append(kind)
        for i, value in enumerate(row):
            left = row[i - bpp] if i >= bpp else 0
            up = previous[i]
            upper_left = previous[i - bpp] if i >= bpp else 0
            predictor = (0, left, up, (left + up) // 2, _paeth(left, up, upper_left))[kind]
            out.append((value - predictor) & 0xFF)
        previous = row
    return bytes(out)


def write_png(path, width, height, rows, color_type=6, bit_depth=8, bpp=4,
              filters=(0,), extra=()):
    """Write a PNG from raw scanlines; *extra* chunks go before IDAT."""
    header = struct.pack(">IIBBBBB", width, height, bit_depth, color_type, 0, 0, 0)
    data = images._PNG_SIGNATURE + _chunk(b"IHDR", header)
    for kind, payload in extra:
        data += _chunk(kind, payload)
    data += _chunk(b"IDAT", zlib.compress(_filtered(rows, bpp, filters)))
    data += _chunk(b"IEND", b"")
    with open(path, "wb") as handle:
        handle.write(data)
    return str(path)


def rgba_png(path, pixels, width, height, filters=(0,)):
    rows = [bytes(value for pixel in pixels[y * width:(y + 1) * width] for value in pixel)
            for y in range(height)]
    return write_png(path, width, height, rows, filters=filters)


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    monkeypatch.setattr(images, "_YIELD_SECONDS", 0)
    images._content_keys.clear()


@pytest.fixture
def cache(monkeypatch, tmp_path):
    folder = tmp_path / "cache"
    monkeypatch.setattr(images, "_translate_path", lambda _path: str(folder))
    return folder


# --- Decoding ---------------------------------------------------------------

@pytest.mark.parametrize("filters", [(0,), (1,), (2,), (3,), (4,), (0, 1, 2, 3, 4)])
def test_every_filter_type_decodes(tmp_path, filters):
    width, height = 5, 6
    pixels = [((x * 50) % 256, (y * 40) % 256, (x * y * 7) % 256, 255 - x * 10)
              for y in range(height) for x in range(width)]
    path = rgba_png(tmp_path / "a.png", pixels, width, height, filters)
    assert images._decode_png_rgba(path) == (width, height, pixels)
    assert images._png_dimensions(path) == (width, height)


def test_rgb_and_grey_with_a_transparent_colour(tmp_path):
    rgb = write_png(tmp_path / "rgb.png", 2, 1, [bytes((1, 2, 3, 9, 9, 9))], color_type=2,
                    bpp=3, extra=[(b"tRNS", struct.pack(">HHH", 9, 9, 9))])
    assert images._decode_png_rgba(rgb)[2] == [(1, 2, 3, 255), (9, 9, 9, 0)]
    grey = write_png(tmp_path / "grey.png", 2, 1, [bytes((7, 0))], color_type=0,
                     bpp=1, extra=[(b"tRNS", struct.pack(">H", 0))])
    assert images._decode_png_rgba(grey)[2] == [(7, 7, 7, 255), (0, 0, 0, 0)]
    grey_alpha = write_png(tmp_path / "ga.png", 1, 1, [bytes((80, 128))], color_type=4, bpp=2)
    assert images._decode_png_rgba(grey_alpha)[2] == [(80, 80, 80, 128)]


@pytest.mark.parametrize(("bit_depth", "row"), [
    (8, bytes((0, 1, 2))), (4, bytes((0x01, 0x20))), (2, bytes((0b00011000,))),
    (1, bytes((0b01000000,))),
])
def test_indexed_colour_at_every_bit_depth(tmp_path, bit_depth, row):
    palette = bytes((10, 20, 30, 40, 50, 60, 70, 80, 90))
    width = 3 if bit_depth > 1 else 2
    path = write_png(tmp_path / "p.png", width, 1, [row], color_type=3, bit_depth=bit_depth,
                     bpp=1, extra=[(b"PLTE", palette), (b"tRNS", bytes((0,)))])
    expected = [(10, 20, 30, 0), (40, 50, 60, 255), (70, 80, 90, 255)][:width]
    assert images._decode_png_rgba(path)[2] == expected


@pytest.mark.parametrize(("header", "message"), [
    ({"bit_depth": 16}, "bit depth"),
    ({"color_type": 3, "bit_depth": 3}, "indexed"),
    ({"color_type": 5}, "color type"),
])
def test_unsupported_pngs_are_refused(tmp_path, header, message):
    path = write_png(tmp_path / "x.png", 1, 1, [bytes(8)], **header)
    with pytest.raises(ValueError, match=message):
        images._decode_png_rgba(path)


def test_not_a_png(tmp_path):
    path = tmp_path / "x.png"
    path.write_bytes(b"GIF89a" + bytes(30))
    assert images._png_dimensions(str(path)) == (0, 0)
    assert images._png_dimensions(str(tmp_path / "missing.png")) == (0, 0)
    with pytest.raises(ValueError):
        images._decode_png_rgba(str(path))


# --- Scaling ----------------------------------------------------------------

@pytest.mark.parametrize(("source", "box", "expected"), [
    ((400, 200), (100, 100), (100, 50)), ((200, 400), (100, 100), (50, 100)),
    ((300, 100), (90, 60), (90, 30)), ((0, 10), (10, 10), (0, 0)),
    ((10, 10), (0, 10), (0, 0)), ((1000, 1), (10, 10), (10, 1)),
])
def test_fit_size_keeps_the_aspect_ratio(source, box, expected):
    assert images._fit_size(*source, *box) == expected


def test_scaling_keeps_a_flat_colour(tmp_path):
    source = rgba_png(tmp_path / "flat.png", [(200, 100, 50, 255)] * 64, 8, 8)
    target = str(tmp_path / "small.png")
    images._scale_png_for_display(source, target, 3, 3)
    assert images._decode_png_rgba(target) == (3, 3, [(200, 100, 50, 255)] * 9)


def test_transparent_pixels_do_not_bleed_their_colour(tmp_path):
    # Opaque white beside fully transparent black: in straight alpha the edge
    # would turn grey.  Premultiplied, it stays white and only fades.
    pixels = [(255, 255, 255, 255), (0, 0, 0, 0)] * 2
    source = rgba_png(tmp_path / "edge.png", pixels, 2, 2)
    target = str(tmp_path / "edge-small.png")
    images._scale_png_for_display(source, target, 1, 1)
    [(r, g, b, a)] = images._decode_png_rgba(target)[2]
    assert (r, g, b) == (255, 255, 255)     # straight alpha would give about 128
    assert a in (127, 128)


# --- The cache --------------------------------------------------------------

def test_small_or_foreign_images_are_used_as_they_are(tmp_path, cache):
    small = rgba_png(tmp_path / "small.png", [(0, 0, 0, 255)] * 4, 2, 2)
    assert images.display_texture(small, 10, 10) == small
    jpeg = str(tmp_path / "logo.jpg")
    assert images.display_texture(jpeg, 10, 10) == jpeg
    assert not cache.exists()


def test_a_large_logo_is_scaled_once(tmp_path, cache, monkeypatch):
    logo = rgba_png(tmp_path / "dolby.png", [(9, 9, 9, 255)] * 100, 10, 10)
    scaled = images.display_texture(logo, 5, 4)
    assert os.path.dirname(scaled) == str(cache)
    assert images._CACHE_NAME.match(os.path.basename(scaled))["stem"] == "dolby"
    assert images._png_dimensions(scaled) == (4, 4)
    monkeypatch.setattr(images, "_scale_png_to_cache", pytest.fail)
    assert images.display_texture(logo, 5, 4) == scaled


def test_a_failing_build_falls_back_to_the_source(tmp_path, cache, monkeypatch):
    logo = rgba_png(tmp_path / "hdr.png", [(9, 9, 9, 255)] * 100, 10, 10)

    def broken(*_args):
        raise MemoryError
    monkeypatch.setattr(images, "_scale_png_to_cache", broken)
    assert images.display_texture(logo, 5, 5) == logo


def test_prune_keeps_current_copies_only(tmp_path, cache):
    media = tmp_path / "media"
    media.mkdir()
    logo = rgba_png(media / "dts.png", [(1, 2, 3, 255)] * 100, 10, 10)
    kept = [images.display_texture(logo, 5, 5), images.display_texture(logo, 4, 4)]
    old_scheme = cache / "dts_5x5.png"
    gone_logo = cache / f"atmos_5x5_{'0' * 16}.png"
    stale_tmp = cache / "x.tmp"
    fresh_tmp = cache / "y.tmp"
    for path in (old_scheme, gone_logo, stale_tmp, fresh_tmp):
        path.write_bytes(b"")
    os.utime(stale_tmp, (0, 0))
    assert images.prune_cache(str(media)) == 3
    assert sorted(os.listdir(cache)) == sorted([os.path.basename(p) for p in kept] + ["y.tmp"])

    # A changed logo makes its copies stale.
    rgba_png(media / "dts.png", [(4, 5, 6, 255)] * 100, 10, 10)
    assert images.prune_cache(str(media)) == 2


def test_prune_without_a_cache(tmp_path, cache):
    assert images.prune_cache(str(tmp_path)) == 0


def test_unpremultiplying_is_exact():
    # Half and a quarter covered white, and nearly transparent red.
    out = images._unpremultiply_rgba([(127.5, 127.5, 127.5, 127.5), (63.75, 63.75, 63.75, 63.75),
                                      (0.6, 0.0, 0.0, 0.6), (0.1, 0.1, 0.1, 0.1)])
    assert list(out) == [255, 255, 255, 128, 255, 255, 255, 64, 255, 0, 0, 1, 0, 0, 0, 0]


def test_a_new_scaler_version_rebuilds_old_copies(tmp_path, cache, monkeypatch):
    media = tmp_path / "media"
    media.mkdir()
    logo = rgba_png(media / "dts.png", [(1, 2, 3, 255)] * 100, 10, 10)
    old = images.display_texture(logo, 5, 5)
    monkeypatch.setattr(images, "_SCALER_VERSION", b"next")
    images._content_keys.clear()
    new = images.display_texture(logo, 5, 5)
    assert new != old
    assert images.prune_cache(str(media)) == 1
    assert os.path.exists(new) and not os.path.exists(old)

