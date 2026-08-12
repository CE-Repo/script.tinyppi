"""Tests for audiodata: bitstream parsers, Matroska enumeration, dispatch.

Run with:  python3 -m unittest discover tests
"""

import io
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "lib"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import audiodata                                        # noqa: E402
import builders as b                                    # noqa: E402
from audiodata import codecs, matroska                  # noqa: E402
from audiodata.bitreader import BitReader               # noqa: E402


def reader_for(data: bytes):
    """Return a sequential ``read(n)`` over a bytes buffer."""
    return io.BytesIO(data).read


class TestBitReader(unittest.TestCase):

    def test_reads_across_byte_boundaries(self):
        r = BitReader(bytes([0b10110010, 0b01011100]))
        self.assertEqual(r.read(3), 0b101)
        self.assertEqual(r.read(7), 0b1001001)
        self.assertEqual(r.read(6), 0b011100)

    def test_wide_read(self):
        self.assertEqual(BitReader(b"\x64\x58\x20\x25").read(32), 0x64582025)

    def test_past_the_end_raises(self):
        with self.assertRaises(EOFError):
            BitReader(b"\x00").read(9)

    def test_skip_tracks_position(self):
        r = BitReader(b"\xff\x0f")
        r.skip(12)
        self.assertEqual(r.pos, 12)
        self.assertEqual(r.read(4), 0xF)


class TestDts(unittest.TestCase):

    def test_extension_substream_round_trip(self):
        parsed = codecs.parse_dts_exss(b.dts_exss())
        self.assertEqual(parsed, {"sample_rate": 96000, "bit_depth": 24,
                                  "channels": 8})

    def test_every_extension_rate_index(self):
        expected = (8000, 16000, 32000, 64000, 128000, 22050, 44100, 88200,
                    176400, 352800, 12000, 24000, 48000, 96000, 192000, 384000)
        for index, rate in enumerate(expected):
            parsed = codecs.parse_dts_exss(b.dts_exss(sample_rate_index=index))
            self.assertEqual(parsed["sample_rate"], rate, f"index {index}")

    def test_optional_descriptor_fields_are_skipped(self):
        # The rate and depth sit behind three optional fields; each must shift
        # the read position by exactly its own width.
        for kwargs in ({"asset_type": True},
                       {"language": True},
                       {"text": 12},
                       {"asset_type": True, "language": True, "text": 5}):
            parsed = codecs.parse_dts_exss(b.dts_exss(**kwargs))
            self.assertEqual(parsed["sample_rate"], 96000, kwargs)
            self.assertEqual(parsed["bit_depth"], 24, kwargs)

    def test_long_header_flavour_is_not_misread(self):
        # header_size_type 1 widens two fields; the short-header builder must
        # not accidentally parse as one.
        parsed = codecs.parse_dts_exss(b.dts_exss(bit_depth=16))
        self.assertEqual(parsed["bit_depth"], 16)

    def test_implausible_bit_depth_is_rejected(self):
        self.assertIsNone(codecs.parse_dts_exss(b.dts_exss(bit_depth=7)))

    def test_core_round_trip(self):
        self.assertEqual(codecs.parse_dts_core(b.dts_core()),
                         {"sample_rate": 48000})
        self.assertEqual(codecs.parse_dts_core(b.dts_core(sfreq_index=8)),
                         {"sample_rate": 44100})

    def test_core_reserved_rate_rejected(self):
        self.assertIsNone(codecs.parse_dts_core(b.dts_core(sfreq_index=4)))

    def test_core_short_frame_rejected(self):
        self.assertIsNone(codecs.parse_dts_core(b.dts_core(fsize=10)))

    def test_extension_wins_over_core(self):
        # A DTS-HD frame is the core followed by its extension; the extension
        # is what states the real rate, so it must be the one reported.
        frame = b.dts_core() + b.dts_exss()
        self.assertEqual(codecs.parse_dts(frame)["sample_rate"], 96000)

    def test_core_only_stream_falls_back(self):
        self.assertEqual(codecs.parse_dts(b.dts_core())["sample_rate"], 48000)

    def test_no_sync_word(self):
        self.assertIsNone(codecs.parse_dts(b"\x00" * 512))


class TestTrueHd(unittest.TestCase):

    def test_rate_codes(self):
        for code, rate in ((0, 48000), (1, 96000), (2, 192000),
                           (8, 44100), (9, 88200), (10, 176400)):
            parsed = codecs.parse_truehd(b.truehd(rate_code=code))
            self.assertEqual(parsed["sample_rate"], rate, f"code {code}")

    def test_bit_depth_is_the_documented_constant(self):
        self.assertEqual(codecs.parse_truehd(b.truehd())["bit_depth"], 24)

    def test_reserved_rate_rejected(self):
        self.assertIsNone(codecs.parse_truehd(b.truehd(rate_code=0xF)))

    def test_mlp_carries_its_own_depth(self):
        parsed = codecs.parse_truehd(b.mlp(quant_code=0, rate_code=1))
        self.assertEqual(parsed, {"sample_rate": 96000, "bit_depth": 16})

    def test_mlp_reserved_quantization_rejected(self):
        self.assertIsNone(codecs.parse_truehd(b.mlp(quant_code=5)))


class TestFlac(unittest.TestCase):

    def test_round_trip_with_and_without_magic(self):
        for magic in (True, False):
            parsed = codecs.parse_flac_streaminfo(
                b.flac_streaminfo(magic=magic))
            self.assertEqual(parsed, {"sample_rate": 96000, "bit_depth": 24,
                                      "channels": 2}, f"magic={magic}")

    def test_zero_rate_rejected(self):
        self.assertIsNone(codecs.parse_flac_streaminfo(
            b.flac_streaminfo(sample_rate=0)))

    def test_truncated_rejected(self):
        self.assertIsNone(codecs.parse_flac_streaminfo(b"fLaC\x00\x00"))


class TestAc3(unittest.TestCase):

    def test_ac3_rates(self):
        for fscod, rate in ((0, 48000), (1, 44100), (2, 32000)):
            parsed = codecs.parse_ac3(b.ac3(fscod=fscod))
            self.assertEqual(parsed["sample_rate"], rate, f"fscod {fscod}")

    def test_ac3_reserved_rate_rejected(self):
        self.assertIsNone(codecs.parse_ac3(b.ac3(fscod=3)))

    def test_eac3_half_rates(self):
        for fscod2, rate in ((0, 24000), (1, 22050), (2, 16000)):
            parsed = codecs.parse_ac3(b.eac3(fscod=3, fscod2=fscod2))
            self.assertEqual(parsed["sample_rate"], rate, f"fscod2 {fscod2}")

    def test_lossy_codes_no_bit_depth(self):
        self.assertNotIn("bit_depth", codecs.parse_ac3(b.ac3()))


class TestScan(unittest.TestCase):

    def test_finds_each_family_once(self):
        blob = b"\x00" * 64 + b.dts_exss() + b"\x11" * 32 + b.truehd()
        found = codecs.scan_families(blob)
        self.assertEqual(found["dts"]["sample_rate"], 96000)
        self.assertEqual(found["truehd"]["sample_rate"], 192000)

    def test_random_data_yields_nothing(self):
        import random
        random.seed(20260812)
        blob = bytes(random.randrange(256) for _ in range(200000))
        self.assertEqual(codecs.scan_families(blob), {})


class TestMatroska(unittest.TestCase):

    def _two_track_file(self):
        entries = [
            b.track_entry(1, "A_DTS", "eng", channels=8),
            b.track_entry(2, "A_AC3", "ger", channels=6),
        ]
        blocks = [b.simple_block(1, b.dts_core() + b.dts_exss())]
        return b.matroska(entries, blocks)

    def test_tracks_in_declaration_order(self):
        tracks = matroska.parse(reader_for(self._two_track_file()), 1 << 20)
        self.assertEqual([t["codec"] for t in tracks], ["dts", "ac3"])
        self.assertEqual([t["language"] for t in tracks], ["eng", "ger"])
        self.assertEqual([t["channels"] for t in tracks], [8, 6])

    def test_bitstream_overrides_the_container_rate(self):
        # The container says 48 kHz; the extension substream says 96 kHz.
        tracks = matroska.parse(reader_for(self._two_track_file()), 1 << 20)
        self.assertEqual(tracks[0]["sample_rate"], 96000)
        self.assertEqual(tracks[0]["bit_depth"], 24)

    def test_container_rate_used_where_no_frame_is_read(self):
        tracks = matroska.parse(reader_for(self._two_track_file()), 1 << 20)
        self.assertEqual(tracks[1]["sample_rate"], 48000)

    def test_flac_private_data_is_read(self):
        entries = [b.track_entry(1, "A_FLAC", "eng", rate=44100.0,
                                 private=b.flac_streaminfo(magic=False))]
        tracks = matroska.parse(reader_for(b.matroska(entries)), 1 << 20)
        self.assertEqual(tracks[0]["sample_rate"], 96000)
        self.assertEqual(tracks[0]["bit_depth"], 24)

    def test_pcm_bit_depth_from_the_container(self):
        entries = [b.track_entry(1, "A_PCM/INT/LIT", rate=48000.0,
                                 bit_depth=24)]
        tracks = matroska.parse(reader_for(b.matroska(entries)), 1 << 20)
        self.assertEqual(tracks[0], {"codec": "pcm", "sample_rate": 48000,
                                     "bit_depth": 24, "channels": 6,
                                     "language": "und"})

    def test_video_tracks_are_ignored(self):
        video = b.element(0xAE, b.element(0xD7, b.uint(1))
                          + b.element(0x83, b.uint(1))
                          + b.element(0x86, b"V_MPEGH/ISO/HEVC"))
        entries = [video, b.track_entry(2, "A_AC3")]
        tracks = matroska.parse(reader_for(b.matroska(entries)), 1 << 20)
        self.assertEqual([t["codec"] for t in tracks], ["ac3"])

    def test_not_matroska_returns_none(self):
        self.assertIsNone(matroska.parse(reader_for(b"\x00" * 4096), 1 << 20))

    def test_truncated_stream_does_not_hang(self):
        data = self._two_track_file()[:40]
        self.assertIn(matroska.parse(reader_for(data), 1 << 20), (None, []))


class TestProbe(unittest.TestCase):

    def test_matroska_path(self):
        entries = [b.track_entry(1, "A_DTS", "eng", channels=8)]
        blocks = [b.simple_block(1, b.dts_exss())]
        tracks = audiodata.probe(reader_for(b.matroska(entries, blocks)))
        self.assertEqual(len(tracks), 1)
        self.assertEqual(tracks[0]["codec"], "dts")
        self.assertEqual(tracks[0]["sample_rate"], 96000)
        self.assertEqual(tracks[0]["bit_depth"], 24)

    def test_scan_path_for_a_foreign_container(self):
        # Anything that is not Matroska: a transport-stream-like blob with a
        # DTS frame somewhere inside it.
        blob = b"\x47" + b"\x00" * 500 + b.dts_exss() + b"\x00" * 500
        tracks = audiodata.probe(reader_for(blob))
        self.assertEqual([t["codec"] for t in tracks], ["dts"])
        self.assertEqual(tracks[0]["sample_rate"], 96000)

    def test_scan_finds_a_header_across_the_chunk_seam(self):
        frame = b.dts_exss()
        head = b"\x00" * (1024 * 1024 - 8)     # split the frame over two chunks
        tracks = audiodata.probe(reader_for(head + frame + b"\x00" * 4096))
        self.assertEqual([t["codec"] for t in tracks], ["dts"])

    def test_empty_stream(self):
        self.assertEqual(audiodata.probe(reader_for(b"")), [])

    def test_garbage_stream(self):
        self.assertEqual(audiodata.probe(reader_for(b"\xa5" * 100000)), [])

    def test_a_failing_reader_never_raises(self):
        def broken(_count):
            raise OSError("the share went away")
        self.assertEqual(audiodata.probe(broken), [])

    def test_budget_is_respected(self):
        pulled = []

        def counting(count):
            pulled.append(count)
            if sum(pulled) > 4 * 1024 * 1024:
                return b""
            return b"\x00" * count

        audiodata.probe(counting, budget=1024 * 1024)
        self.assertLessEqual(sum(pulled), 1024 * 1024 + 4096)


if __name__ == "__main__":
    unittest.main()
