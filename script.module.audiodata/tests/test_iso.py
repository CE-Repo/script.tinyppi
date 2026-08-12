"""Disc-image walks: ISO9660/DVD end to end, MPLS parsing, and the
main-feature selection heuristics."""

import io
import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "lib"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import audiodata                                        # noqa: E402
import builders as b                                    # noqa: E402
from audiodata.containers import iso                    # noqa: E402
from audiodata.containers.iso import iso9660, mpls, udf  # noqa: E402
from audiodata.containers.iso.image import Image        # noqa: E402

SECTOR = 2048


def both_endian32(value: int) -> bytes:
    return struct.pack("<I", value) + struct.pack(">I", value)


def dir_record(name: bytes, lba: int, size: int, is_dir: bool) -> bytes:
    body = bytearray(33 + len(name))
    body[1] = 0                                   # extended attribute length
    body[2:10] = both_endian32(lba)
    body[10:18] = both_endian32(size)
    body[25] = 0x02 if is_dir else 0x00
    body[32] = len(name)
    body[33:33 + len(name)] = name
    if len(body) % 2:
        body.append(0)
    body[0] = len(body)
    return bytes(body)


def build_dvd_iso(vob_payload: bytes) -> bytes:
    """A minimal DVD-Video ISO9660 image: root -> VIDEO_TS -> VTS_01_1.VOB."""
    root_lba, video_ts_lba, vob_lba = 20, 21, 22
    vob_size = len(vob_payload)

    root_dir = (dir_record(b"\x00", root_lba, SECTOR, True)
                + dir_record(b"\x01", root_lba, SECTOR, True)
                + dir_record(b"VIDEO_TS", video_ts_lba, SECTOR, True))
    video_ts = (dir_record(b"\x00", video_ts_lba, SECTOR, True)
                + dir_record(b"\x01", root_lba, SECTOR, True)
                + dir_record(b"VIDEO_TS.VOB;1", vob_lba, 16, False)
                + dir_record(b"VTS_01_1.VOB;1", vob_lba, vob_size, False))

    pvd = bytearray(SECTOR)
    pvd[0] = 1
    pvd[1:6] = b"CD001"
    pvd[6] = 1
    struct.pack_into("<H", pvd, 128, SECTOR)
    pvd[156:156 + 34] = dir_record(b"\x00", root_lba, SECTOR, True)[:34]

    image = bytearray(SECTOR * 40)
    image[16 * SECTOR:17 * SECTOR] = pvd
    image[root_lba * SECTOR:root_lba * SECTOR + len(root_dir)] = root_dir
    image[video_ts_lba * SECTOR:video_ts_lba * SECTOR + len(video_ts)] = video_ts
    image[vob_lba * SECTOR:vob_lba * SECTOR + vob_size] = vob_payload
    return bytes(image)


class TestIso9660(unittest.TestCase):

    def _image(self):
        vob = b.program_stream([(0xBD, bytes([0xA0]) + b.dvd_lpcm()),
                                (0xC0, b.mpeg_audio())])
        return build_dvd_iso(vob)

    def test_detected_as_an_iso(self):
        image = Image(io.BytesIO(self._image()), len(self._image()))
        self.assertTrue(iso9660.looks_like_iso9660(image))
        self.assertTrue(iso.looks_like_iso(image))

    def test_directory_walk(self):
        data = self._image()
        volume = iso9660.Iso9660.open(Image(io.BytesIO(data), len(data)))
        names = [e.name for e in volume.read_dir(volume.root())]
        self.assertEqual(names, ["VIDEO_TS"])
        video_ts = volume.read_dir(volume.root())[0]
        files = sorted(e.name for e in volume.read_dir(video_ts))
        self.assertEqual(files, ["VIDEO_TS.VOB", "VTS_01_1.VOB"])

    def test_dvd_probe_end_to_end(self):
        report = audiodata.probe(self._image())
        self.assertIn("DVD-Video ISO", report.container)
        self.assertIn("VTS_01_1.VOB", report.container)
        by_codec = {t.codec: t for t in report.tracks}
        self.assertEqual(by_codec["LPCM (DVD)"].sample_rate, 96000)
        self.assertEqual(by_codec["LPCM (DVD)"].bit_depth, 24)
        self.assertEqual(by_codec["MP3"].sample_rate, 44100)


class TestMpls(unittest.TestCase):

    @staticmethod
    def playlist(items):
        """items: list of (clip id, in, out)."""
        body = bytearray()
        for clip_id, in_45k, out_45k in items:
            item = (clip_id.encode() + b"M2TS" + bytes(3)
                    + struct.pack(">II", in_45k, out_45k) + bytes(8))
            body += struct.pack(">H", len(item)) + item
        header = b"MPLS0200" + struct.pack(">I", 40) + bytes(28)
        playlist = (struct.pack(">I", len(body) + 6) + bytes(2)
                    + struct.pack(">HH", len(items), 0) + body)
        return header + playlist

    def test_parses_items_and_duration(self):
        data = self.playlist([("00801", 0, 45000 * 60), ("00802", 0, 45000 * 30)])
        parsed = mpls.parse(data)
        self.assertEqual([i.clip_id for i in parsed.items], ["00801", "00802"])
        self.assertAlmostEqual(parsed.duration_secs_deduped(), 90.0)

    def test_looped_segments_are_deduped(self):
        data = self.playlist([("00801", 0, 45000 * 60)] * 20)
        self.assertAlmostEqual(mpls.parse(data).duration_secs_deduped(), 60.0)
        self.assertEqual(mpls.parse(data).distinct_clips(), ["00801"])

    def test_rejects_a_foreign_or_unsupported_file(self):
        with self.assertRaises(mpls.MplsError):
            mpls.parse(b"\x00" * 64)
        with self.assertRaises(mpls.MplsError):
            mpls.parse(b"MPLS9999" + bytes(64))


class TestSelection(unittest.TestCase):

    @staticmethod
    def candidate(name, items):
        return name, mpls.Playlist([mpls.PlayItem(c, i, o) for c, i, o in items])

    def test_longest_deduped_duration_wins(self):
        sizes = {"00801": 30 << 30, "00802": 1 << 30}
        cands = [self.candidate("00000.mpls", [("00802", 0, 45000 * 600)]),
                 self.candidate("00001.mpls", [("00801", 0, 45000 * 7000)])]
        name, clip = iso._select_main(cands, sizes)
        self.assertEqual((name, clip), ("00001.mpls", "00801"))

    def test_a_decoy_looping_one_segment_cannot_win(self):
        sizes = {"00801": 30 << 30, "00900": 1 << 30}
        real = self.candidate("00001.mpls", [("00801", 0, 45000 * 7000)])
        decoy = self.candidate("00002.mpls", [("00900", 0, 45000 * 100)] * 200)
        name, _clip = iso._select_main([real, decoy], sizes)
        self.assertEqual(name, "00001.mpls")

    def test_playlists_naming_missing_clips_are_dropped(self):
        sizes = {"00801": 1 << 30}
        cands = [self.candidate("00000.mpls", [("09999", 0, 45000 * 9000)]),
                 self.candidate("00001.mpls", [("00801", 0, 45000 * 100)])]
        name, _clip = iso._select_main(cands, sizes)
        self.assertEqual(name, "00001.mpls")

    def test_identical_sequences_collapse_to_the_lowest_name(self):
        sizes = {"00801": 1 << 30}
        items = [("00801", 0, 45000 * 100)]
        cands = [self.candidate("00005.mpls", items),
                 self.candidate("00001.mpls", items)]
        name, _clip = iso._select_main(cands, sizes)
        self.assertEqual(name, "00001.mpls")

    def test_duration_tie_is_broken_by_bytes(self):
        sizes = {"00801": 1 << 30, "00802": 30 << 30}
        items_a = [("00801", 0, 45000 * 100)]
        items_b = [("00802", 0, 45000 * 100)]
        cands = [self.candidate("00001.mpls", items_a),
                 self.candidate("00002.mpls", items_b)]
        name, clip = iso._select_main(cands, sizes)
        self.assertEqual((name, clip), ("00002.mpls", "00802"))

    def test_the_largest_referenced_clip_is_probed(self):
        sizes = {"00801": 1 << 30, "00802": 30 << 30}
        cands = [self.candidate("00001.mpls",
                                [("00801", 0, 45000), ("00802", 0, 45000)])]
        _name, clip = iso._select_main(cands, sizes)
        self.assertEqual(clip, "00802")

    def test_no_usable_playlist(self):
        with self.assertRaises(ValueError):
            iso._select_main([], {})

    def test_adjacent_extents_coalesce(self):
        self.assertEqual(iso._coalesce([(100, 50), (150, 50)]), (100, 100))
        self.assertEqual(iso._coalesce([(100, 50)]), (100, 50))

    def test_a_gap_refuses_to_coalesce(self):
        self.assertIsNone(iso._coalesce([(100, 50), (200, 50)]))
        self.assertIsNone(iso._coalesce([]))

    def test_clip_id_of(self):
        self.assertEqual(iso._clip_id_of("00055.m2ts"), "00055")
        self.assertEqual(iso._clip_id_of("00055.M2TS"), "00055")
        self.assertIsNone(iso._clip_id_of("index.bdmv"))

    def test_parse_vts(self):
        self.assertEqual(iso._parse_vts("VTS_01_1.VOB"), ("01", 1))
        self.assertEqual(iso._parse_vts("vts_02_3.vob"), ("02", 3))
        self.assertIsNone(iso._parse_vts("VIDEO_TS.VOB"))
        self.assertIsNone(iso._parse_vts("VTS_01_0.IFO"))

    def test_dvd_title_set_with_the_most_bytes_wins(self):
        files = [iso9660.DirRec("VTS_01_1.VOB", False, 0, 1000),
                 iso9660.DirRec("VTS_02_1.VOB", False, 0, 5000),
                 iso9660.DirRec("VTS_02_2.VOB", False, 0, 5000),
                 iso9660.DirRec("VIDEO_TS.VOB", False, 0, 90000)]
        vob, title = iso._select_dvd_vob(files)
        self.assertEqual((vob.name, title), ("VTS_02_1.VOB", "VTS_02"))

    def test_dvd_falls_back_to_the_largest_vob(self):
        files = [iso9660.DirRec("ODD.VOB", False, 0, 4242)]
        vob, title = iso._select_dvd_vob(files)
        self.assertEqual((vob.name, title), ("ODD.VOB", "title"))


class TestUdfDetection(unittest.TestCase):

    def test_nsr_descriptor_marks_a_udf_volume(self):
        data = bytearray(SECTOR * 40)
        data[18 * SECTOR + 1:18 * SECTOR + 6] = b"NSR02"
        image = Image(io.BytesIO(bytes(data)), len(data))
        self.assertTrue(udf.is_udf_iso(image))
        self.assertTrue(iso.looks_like_iso(image))

    def test_a_plain_image_is_not_udf(self):
        data = bytes(SECTOR * 40)
        self.assertFalse(udf.is_udf_iso(Image(io.BytesIO(data), len(data))))

    def test_a_udf_volume_without_descriptors_fails_cleanly(self):
        data = bytearray(SECTOR * 40)
        data[18 * SECTOR + 1:18 * SECTOR + 6] = b"NSR02"
        report = audiodata.probe(bytes(data))
        self.assertTrue(report.error)
        self.assertEqual(report.tracks, [])


class TestImage(unittest.TestCase):

    def test_read_at_is_exact_or_empty(self):
        image = Image(io.BytesIO(b"0123456789"), 10)
        self.assertEqual(image.read_at(2, 4), b"2345")
        self.assertEqual(image.read_at(8, 4), b"")      # past the end
        self.assertEqual(image.read_at(-1, 4), b"")

    def test_range_reader_stops_at_the_range_end(self):
        image = Image(io.BytesIO(b"0123456789"), 10)
        read = image.range_reader(3, 4)
        self.assertEqual(read(2), b"34")
        self.assertEqual(read(10), b"56")
        self.assertEqual(read(10), b"")


if __name__ == "__main__":
    unittest.main()
