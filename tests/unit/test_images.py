# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""PNG decoding, scaling and the texture cache (core/images.py)."""

import os
import struct
import types
import zlib

import pytest

import xbmc
import xbmcvfs
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



# --- Edge cases of the decoder ----------------------------------------------

def _raw_png(path, header, scanlines, chunks_after=(), end=True):
    """Write a PNG from an IHDR payload and already filtered scanline bytes."""
    data = images._PNG_SIGNATURE + _chunk(b"IHDR", header)
    data += _chunk(b"IDAT", zlib.compress(scanlines))
    for kind, payload in chunks_after:
        data += _chunk(kind, payload)
    if end:
        data += _chunk(b"IEND", b"")
    path.write_bytes(data)
    return str(path)


@pytest.mark.parametrize(("a", "b", "c", "expected"), [
    (10, 20, 10, 20),      # p == b
    (20, 10, 10, 20),      # p == a
    (10, 0, 5, 5),         # p == c: the upper-left neighbour is closest
    (0, 0, 0, 0),
])
def test_paeth_picks_the_closest_neighbour(a, b, c, expected):
    assert images._paeth(a, b, c) == expected == _paeth(a, b, c)


def test_a_paeth_row_that_predicts_from_the_upper_left(tmp_path):
    # Row 2 pixel 2 has left 10, up 0 and upper-left 5: the predictor is c.
    rows = [bytes((5, 0)), bytes((10, 7))]
    path = write_png(tmp_path / "g.png", 2, 2, rows, color_type=0, bpp=1, filters=(4,))
    assert images._decode_png_rgba(path)[2] == [
        (5, 5, 5, 255), (0, 0, 0, 255), (10, 10, 10, 255), (7, 7, 7, 255)]


def test_an_unknown_filter_type_is_refused(tmp_path):
    header = struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)
    path = _raw_png(tmp_path / "f.png", header, b"\x05" + bytes(4))
    with pytest.raises(ValueError, match="unsupported PNG filter"):
        images._decode_png_rgba(path)


@pytest.mark.parametrize("fields", [(1, 0, 0), (0, 1, 0), (0, 0, 1)])
def test_compression_filter_method_and_interlacing_must_be_standard(tmp_path, fields):
    header = struct.pack(">IIBBBBB", 1, 1, 8, 6, *fields)
    path = _raw_png(tmp_path / "i.png", header, bytes(5))
    with pytest.raises(ValueError, match="unsupported PNG format"):
        images._decode_png_rgba(path)


def test_unknown_chunks_and_a_missing_end_are_tolerated(tmp_path):
    header = struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)
    path = _raw_png(tmp_path / "t.png", header, bytes((0, 1, 2, 3, 4)),
                    chunks_after=[(b"tEXt", b"Software\x00test")], end=False)
    assert images._decode_png_rgba(path) == (1, 1, [(1, 2, 3, 4)])


def test_rgb_and_grey_without_transparency_are_opaque(tmp_path):
    rgb = write_png(tmp_path / "rgb.png", 2, 1, [bytes((1, 2, 3, 0, 0, 0))], color_type=2, bpp=3)
    assert images._decode_png_rgba(rgb)[2] == [(1, 2, 3, 255), (0, 0, 0, 255)]
    grey = write_png(tmp_path / "grey.png", 2, 1, [bytes((7, 0))], color_type=0, bpp=1)
    assert images._decode_png_rgba(grey)[2] == [(7, 7, 7, 255), (0, 0, 0, 255)]


def test_a_header_that_does_not_start_with_ihdr_has_no_size(tmp_path):
    path = tmp_path / "x.png"
    path.write_bytes(images._PNG_SIGNATURE + _chunk(b"gAMA", bytes(12)))
    assert images._png_dimensions(str(path)) == (0, 0)


def test_a_short_indexed_row_yields_the_indices_it_holds():
    assert images._palette_indices(bytes((0b10110100,)), 5, 4) == [0b1011, 0b0100]
    assert images._palette_indices(bytes((0b11100100,)), 3, 2) == [3, 2, 1]


# --- Sharing the interpreter --------------------------------------------------

@pytest.fixture
def pauses(monkeypatch):
    seen = []
    monkeypatch.setattr(images, "time", types.SimpleNamespace(sleep=seen.append))
    return seen


def test_the_scaler_pauses_every_sixteen_rows(pauses):
    for row in range(48):
        images._breathe(row)
    assert len(pauses) == 3


def test_decoding_a_tall_image_pauses_between_rows(tmp_path, pauses):
    path = rgba_png(tmp_path / "tall.png", [(1, 2, 3, 255)] * 32, 1, 32)
    assert images._decode_png_rgba(path)[2] == [(1, 2, 3, 255)] * 32
    assert len(pauses) == 2


def test_premultiplying_pauses_every_block_of_pixels(pauses, monkeypatch):
    monkeypatch.setattr(images, "_YIELD_PIXELS", 4)
    out = images._premultiply_rgba([(255, 255, 255, 51)] * 8)
    assert out == [(51.0, 51.0, 51.0, 51.0)] * 8
    assert len(pauses) == 2


# --- Paths and the cache ------------------------------------------------------

def test_special_paths_are_translated():
    assert images._translate_path("special://profile/x") == xbmcvfs.translatePath(
        "special://profile/x")


def test_an_old_kodi_without_xbmcvfs_paths_uses_xbmc(monkeypatch):
    monkeypatch.delattr(xbmcvfs, "translatePath")
    monkeypatch.setattr(xbmc, "translatePath", lambda path: f"/legacy/{path}")
    assert images._translate_path("special://profile/x") == "/legacy/special://profile/x"


def test_a_copy_built_while_waiting_for_the_gate_is_not_built_again(tmp_path, cache, monkeypatch):
    logo = rgba_png(tmp_path / "dolby.png", [(9, 9, 9, 255)] * 100, 10, 10)
    cache_path = images._cache_target(logo, 5, 5)[0]
    cache.mkdir()

    class BuiltMeanwhile:
        """The gate's previous holder built this very copy."""

        def __enter__(self):
            with open(cache_path, "wb") as handle:
                handle.write(b"built by the other thread")

        def __exit__(self, *_exc):
            return False

    builds = []
    monkeypatch.setattr(images, "_build_gate", BuiltMeanwhile())
    monkeypatch.setattr(images, "_scale_png_to_cache", lambda *args: builds.append(args))
    assert images.display_texture(logo, 5, 5) == cache_path
    assert builds == []


def test_prune_ignores_other_media_and_logs_what_it_cannot_remove(tmp_path, cache):
    media = tmp_path / "media"
    media.mkdir()
    (media / "dts.jpg").write_bytes(b"")
    cache.mkdir()
    (cache / f"dts_5x5_{'0' * 16}.png").write_bytes(b"")     # its logo is not a PNG
    stuck = cache / "old.tmp"
    stuck.mkdir()                                              # cannot be removed as a file
    os.utime(stuck, (0, 0))
    assert images.prune_cache(str(media)) == 1
    assert os.listdir(cache) == ["old.tmp"]
    assert any(line.startswith("TinyPPI [images]: could not prune old.tmp: ")
               for _level, line in xbmc.LOG)


def test_a_log_failure_never_breaks_a_build(monkeypatch):
    def broken(_message):
        raise RuntimeError("log closed")
    monkeypatch.setattr(images, "_log", broken)
    images._log_debug("anything")
    written = []
    monkeypatch.setattr(images, "_log", written.append)
    images._log_debug("scaled")
    assert written == ["scaled"]
