"""Container backends and the top-level dispatch."""

import io
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "lib"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import audiodata                                        # noqa: E402
import builders as b                                    # noqa: E402
from audiodata import containers                        # noqa: E402
from audiodata.containers import matroska, mp4, mpegps, mpegts  # noqa: E402


def source(data: bytes):
    return io.BytesIO(data)


DTS_HD_FRAME = b.dts_core() + b.dts_exss() + b.DTS_XLL_SYNC


class TestMatroska(unittest.TestCase):

    def _file(self):
        entries = [
            b.track_entry(1, "A_DTS", "eng", channels=8, name="Main"),
            b.track_entry(2, "A_AC3", "ger", channels=6),
            b.track_entry(3, "A_TRUEHD", "jpn", channels=8, default=False),
        ]
        blocks = [b.simple_block(1, DTS_HD_FRAME),
                  b.simple_block(2, b.ac3()),
                  b.simple_block(3, b.truehd())]
        return b.matroska(entries, blocks)

    def test_tracks_in_declaration_order_with_metadata(self):
        report = matroska.probe(source(self._file()), 1 << 20)
        self.assertEqual(report.container, "Matroska")
        self.assertEqual([t.codec for t in report.tracks],
                         ["DTS-HD MA", "AC-3", "TrueHD"])
        self.assertEqual([t.language for t in report.tracks],
                         ["eng", "ger", "jpn"])
        self.assertEqual([t.default for t in report.tracks], [True, True, False])
        self.assertEqual(report.tracks[0].title, "Main")

    def test_bitstream_overrides_the_container_rate(self):
        report = matroska.probe(source(self._file()), 1 << 20)
        # The container says 48 kHz; the extension substream says 96 kHz.
        self.assertEqual(report.tracks[0].sample_rate, 96000)
        self.assertEqual(report.tracks[0].bit_depth, 24)
        self.assertEqual(report.tracks[2].sample_rate, 192000)
        self.assertEqual(report.tracks[2].bit_depth, 24)

    def test_container_rate_for_the_lossy_track(self):
        report = matroska.probe(source(self._file()), 1 << 20)
        self.assertEqual(report.tracks[1].sample_rate, 48000)
        self.assertIsNone(report.tracks[1].bit_depth)

    def test_shallow_mode_keeps_only_container_metadata(self):
        report = matroska.probe(source(self._file()), 1 << 20, deep=False)
        self.assertEqual(report.tracks[0].sample_rate, 48000)
        self.assertEqual(report.tracks[0].note, "container metadata only")

    def test_webm_doctype(self):
        entries = [b.track_entry(1, "A_OPUS", private=b.opus_head())]
        report = matroska.probe(source(b.matroska(entries, doctype="webm")), 1 << 20)
        self.assertEqual(report.container, "WebM")
        self.assertEqual(report.tracks[0].codec, "Opus")
        self.assertEqual(report.tracks[0].sample_rate, 48000)

    def test_codec_private_formats(self):
        cases = (
            ("A_FLAC", b.flac_streaminfo(), "FLAC", 96000, 24),
            ("A_ALAC", b.alac_config(), "ALAC", 96000, 24),
            ("A_MS/ACM", b.waveformatex(), "PCM", 48000, 24),
            ("A_VORBIS", b.vorbis_id(), "Vorbis", 44100, None),
            ("A_AAC", b.asc(), "AAC-LC", 48000, None),
        )
        for codec_id, private, name, rate, depth in cases:
            entries = [b.track_entry(1, codec_id, private=private)]
            report = matroska.probe(source(b.matroska(entries)), 1 << 20)
            track = report.tracks[0]
            self.assertEqual((track.codec, track.sample_rate, track.bit_depth),
                             (name, rate, depth), codec_id)

    def test_pcm_float_defaults_to_32_bit(self):
        entries = [b.track_entry(1, "A_PCM/FLOAT/IEEE")]
        report = matroska.probe(source(b.matroska(entries)), 1 << 20)
        self.assertEqual(report.tracks[0].bit_depth, 32)

    def test_old_style_sbr_doubles_the_rate(self):
        entries = [b.track_entry(1, "A_AAC/MPEG4/LC/SBR", rate=24000.0)]
        report = matroska.probe(source(b.matroska(entries)), 1 << 20)
        self.assertEqual(report.tracks[0].sample_rate, 48000)

    def test_video_tracks_are_ignored(self):
        entries = [b.track_entry(1, "V_MPEGH/ISO/HEVC", track_type=1),
                   b.track_entry(2, "A_AC3")]
        report = matroska.probe(source(b.matroska(entries)), 1 << 20)
        self.assertEqual([t.codec for t in report.tracks], ["AC-3"])

    def test_lacing_headers_are_skipped(self):
        for lacing in (1, 2, 3):
            frame = b"\x00" + b"\x05" * 4 + DTS_HD_FRAME
            entries = [b.track_entry(1, "A_DTS")]
            blocks = [b.simple_block(1, frame, lacing=lacing)]
            report = matroska.probe(source(b.matroska(entries, blocks)), 1 << 20)
            self.assertEqual(report.tracks[0].sample_rate, 96000, f"lacing {lacing}")

    def test_not_matroska_raises(self):
        with self.assertRaises(ValueError):
            matroska.probe(source(b"\x00" * 4096), 1 << 20)


class TestMpegTs(unittest.TestCase):

    def _bluray(self, bdav=True):
        streams = [(0x86, 0x1100, bytes([0x0A, 0x04]) + b"eng\x00"),   # DTS-HD MA
                   (0x83, 0x1101, bytes([0x0A, 0x04]) + b"ger\x00"),   # TrueHD
                   (0x80, 0x1102, b"")]                                # HDMV LPCM
        frames = {0x1100: DTS_HD_FRAME, 0x1101: b.truehd(),
                  0x1102: b.hdmv_lpcm()}
        return b.transport_stream(streams, frames, bdav=bdav, hdmv=True)

    def test_bdav_packet_size_is_detected(self):
        report = mpegts.probe(source(self._bluray()).read, 1 << 20)
        self.assertEqual(report.container, "M2TS (BDAV)")

    def test_plain_ts_packet_size_is_detected(self):
        report = mpegts.probe(source(self._bluray(bdav=False)).read, 1 << 20)
        self.assertEqual(report.container, "MPEG-TS")

    def test_streams_language_and_parameters(self):
        report = mpegts.probe(source(self._bluray()).read, 1 << 20)
        by_codec = {t.codec: t for t in report.tracks}
        self.assertIn("DTS-HD MA", by_codec)
        self.assertEqual(by_codec["DTS-HD MA"].sample_rate, 96000)
        self.assertEqual(by_codec["DTS-HD MA"].bit_depth, 24)
        self.assertEqual(by_codec["DTS-HD MA"].language, "eng")
        self.assertEqual(by_codec["TrueHD"].sample_rate, 192000)
        self.assertEqual(by_codec["TrueHD"].language, "ger")

    def test_hdmv_lpcm_is_read_from_its_pes_header(self):
        report = mpegts.probe(source(self._bluray()).read, 1 << 20)
        lpcm = next(t for t in report.tracks if "LPCM" in t.codec)
        self.assertEqual((lpcm.sample_rate, lpcm.bit_depth, lpcm.channels),
                         (96000, 24, 6))

    def test_stream_type_0x80_is_ac3_without_the_hdmv_registration(self):
        streams = [(0x80, 0x1100, b"")]
        data = b.transport_stream(streams, {0x1100: b.ac3()}, hdmv=False)
        report = mpegts.probe(source(data).read, 1 << 20)
        self.assertEqual(report.tracks[0].codec, "AC-3")

    def test_dvb_descriptors_classify_private_data(self):
        for tag, codec in ((0x6A, "AC-3"), (0x7A, "E-AC-3"), (0x7B, "DTS")):
            streams = [(0x06, 0x1100, bytes([tag, 0x00]))]
            frame = {0x6A: b.ac3(), 0x7A: b.eac3(), 0x7B: b.dts_core()}[tag]
            data = b.transport_stream(streams, {0x1100: frame})
            report = mpegts.probe(source(data).read, 1 << 20)
            self.assertEqual(report.tracks[0].codec, codec, hex(tag))

    def test_truehd_falls_back_to_the_embedded_ac3_core(self):
        streams = [(0x83, 0x1100, b"")]
        data = b.transport_stream(streams, {0x1100: b.ac3()})
        report = mpegts.probe(source(data).read, 1 << 20)
        track = report.tracks[0]
        self.assertEqual(track.codec, "TrueHD")
        self.assertEqual(track.sample_rate, 48000)
        self.assertIsNone(track.bit_depth)
        self.assertIn("AC-3 core", track.note)

    def test_pmt_flavour_name_survives_a_plain_dts_reading(self):
        # The PMT says DTS-HD MA; a window without the XLL sync must not
        # downgrade the name to "DTS".
        streams = [(0x86, 0x1100, b"")]
        data = b.transport_stream(streams, {0x1100: b.dts_core()})
        report = mpegts.probe(source(data).read, 1 << 20)
        self.assertEqual(report.tracks[0].codec, "DTS-HD MA")

    def test_no_pat_raises(self):
        with self.assertRaises(ValueError):
            mpegts.probe(source(b"\x47" + b"\x00" * 100000).read, 1 << 20)


class TestMpegPs(unittest.TestCase):

    def test_dvd_lpcm_and_ac3_substreams(self):
        packets = [
            (0xBD, bytes([0xA0]) + b.dvd_lpcm()),
            (0xBD, bytes([0x80, 0, 0, 0]) + b.ac3()),
            (0xC0, b.mpeg_audio()),
        ]
        report = mpegps.probe(source(b.program_stream(packets)).read, 1 << 20)
        by_codec = {t.codec: t for t in report.tracks}
        self.assertEqual(report.container, "MPEG-PS")
        self.assertEqual(by_codec["LPCM (DVD)"].sample_rate, 96000)
        self.assertEqual(by_codec["LPCM (DVD)"].bit_depth, 24)
        self.assertEqual(by_codec["AC-3"].sample_rate, 48000)
        self.assertEqual(by_codec["MP3"].sample_rate, 44100)

    def test_dts_substream(self):
        packets = [(0xBD, bytes([0x88, 0, 0, 0]) + DTS_HD_FRAME)]
        report = mpegps.probe(source(b.program_stream(packets)).read, 1 << 20)
        self.assertEqual(report.tracks[0].sample_rate, 96000)

    def test_not_a_program_stream_raises(self):
        with self.assertRaises(ValueError):
            mpegps.probe(source(b"\x00" * 4096).read, 1 << 20)


class TestMp4(unittest.TestCase):

    def test_ddts_configuration(self):
        import struct
        ddts = b.box(b"ddts", struct.pack(">I", 96000) + bytes(8) + bytes([24]))
        data = b.mp4_file(b"dtsl", children=ddts)
        report = mp4.probe(source(data), len(data))
        track = report.tracks[0]
        self.assertEqual((track.codec, track.sample_rate, track.bit_depth),
                         ("DTS-HD MA", 96000, 24))
        self.assertEqual(track.language, "eng")

    def test_esds_carries_the_audio_specific_config(self):
        asc = b.asc()
        dsi = bytes([0x05, len(asc)]) + asc
        dcd = bytes([0x04, 13 + len(dsi), 0x40]) + bytes(12) + dsi
        es = bytes([0x03, 3 + len(dcd), 0, 1, 0]) + dcd
        data = b.mp4_file(b"mp4a", children=b.box(b"esds", bytes(4) + es))
        report = mp4.probe(source(data), len(data))
        self.assertEqual(report.tracks[0].codec, "AAC-LC")
        self.assertEqual(report.tracks[0].sample_rate, 48000)

    def test_alac_and_flac_boxes(self):
        data = b.mp4_file(b"alac", children=b.box(b"alac", bytes(4) + b.alac_config()))
        report = mp4.probe(source(data), len(data))
        self.assertEqual((report.tracks[0].codec, report.tracks[0].bit_depth),
                         ("ALAC", 24))

        data = b.mp4_file(b"fLaC",
                          children=b.box(b"dfLa", bytes(4) + b.flac_streaminfo(magic=False)))
        report = mp4.probe(source(data), len(data))
        self.assertEqual((report.tracks[0].codec, report.tracks[0].sample_rate),
                         ("FLAC", 96000))

    def test_pcm_sample_size_is_the_bit_depth(self):
        data = b.mp4_file(b"in24", sample_size=24)
        report = mp4.probe(source(data), len(data))
        self.assertEqual((report.tracks[0].codec, report.tracks[0].bit_depth),
                         ("PCM 24-bit", 24))

    def test_no_moov_raises(self):
        data = b.box(b"ftyp", b"isom" + bytes(8))
        with self.assertRaises(ValueError):
            mp4.probe(source(data), len(data))


class TestAviWavOgg(unittest.TestCase):

    def test_avi_waveformatex(self):
        data = b.avi_file(b.waveformatex(), name="Commentary")
        report = audiodata.probe(data)
        self.assertEqual(report.container, "AVI")
        track = report.tracks[0]
        self.assertEqual((track.codec, track.sample_rate, track.bit_depth), ("PCM", 48000, 24))
        self.assertEqual(track.title, "Commentary")

    def test_wav(self):
        report = audiodata.probe(b.wav_file(b.waveformatex()))
        self.assertEqual(report.container, "WAV")
        self.assertEqual(report.tracks[0].bit_depth, 24)

    def test_wav_extensible(self):
        report = audiodata.probe(
            b.wav_file(b.waveformatex(tag=0xFFFE, extensible_sub=1)))
        self.assertEqual(report.container, "WAV (extensible)")

    def test_ogg_opus_and_vorbis(self):
        report = audiodata.probe(b.ogg_file(b.opus_head()))
        self.assertEqual((report.container, report.tracks[0].codec), ("Ogg", "Opus"))
        report = audiodata.probe(b.ogg_file(b.vorbis_id()))
        self.assertEqual(report.tracks[0].codec, "Vorbis")

    def test_native_flac(self):
        report = audiodata.probe(b.flac_streaminfo())
        self.assertEqual((report.container, report.tracks[0].sample_rate),
                         ("FLAC", 96000))


class TestDispatch(unittest.TestCase):

    def test_sniffing_picks_each_backend(self):
        cases = (
            (b.matroska([b.track_entry(1, "A_AC3")]), "Matroska"),
            (b.mp4_file(b"mp4a"), "MP4"),
            (b.wav_file(b.waveformatex()), "WAV"),
            (b.avi_file(b.waveformatex()), "AVI"),
            (b.ogg_file(b.opus_head()), "Ogg"),
            (b.flac_streaminfo(), "FLAC"),
            (b.program_stream([(0xC0, b.mpeg_audio())]), "MPEG-PS"),
        )
        for data, container in cases:
            self.assertEqual(audiodata.probe(data).container, container, container)

    def test_elementary_stream_by_extension(self):
        report = audiodata.probe(DTS_HD_FRAME, extension="dts")
        self.assertEqual(report.tracks[0].codec, "DTS-HD MA")
        report = audiodata.probe(b.truehd(), extension=".thd")
        self.assertEqual(report.tracks[0].codec, "TrueHD")

    def test_sniffs_as_ts_agrees_with_the_dispatcher(self):
        ts = b.transport_stream([(0x81, 0x1100, b"")], {0x1100: b.ac3()})
        self.assertTrue(containers.sniffs_as_ts(ts[:4096]))
        self.assertFalse(containers.sniffs_as_ts(b.mp4_file(b"mp4a")[:4096]))

    def test_probe_tracks_returns_plain_dicts(self):
        tracks = audiodata.probe_tracks(b.matroska([b.track_entry(1, "A_AC3")]))
        self.assertEqual(tracks[0]["codec"], "AC-3")
        self.assertEqual(tracks[0]["language"], "und")
        self.assertIn("layout", tracks[0])

    def test_layout_naming(self):
        streams = [(0x86, 0x1100, b"")]
        data = b.transport_stream(streams, {0x1100: DTS_HD_FRAME})
        track = audiodata.probe(data).tracks[0]
        self.assertEqual(track.channels, 8)
        self.assertEqual(track.layout(), "7.1")

    def test_failures_never_raise(self):
        self.assertEqual(audiodata.probe(b"").tracks, [])
        self.assertTrue(audiodata.probe(b"\xa5" * 100000).error)
        self.assertEqual(audiodata.probe_tracks(b"\x00" * 1000), [])

    def test_a_failing_reader_is_reported_not_raised(self):
        class Broken:
            def read(self, _n):
                raise OSError("the share went away")

            def seek(self, *_a):
                return 0

        self.assertEqual(audiodata.probe(Broken()).tracks, [])

    def test_bytes_path_and_filelike_agree(self):
        data = b.matroska([b.track_entry(1, "A_AC3")])
        self.assertEqual(audiodata.probe(data).tracks[0].codec,
                         audiodata.probe(source(data)).tracks[0].codec)


if __name__ == "__main__":
    unittest.main()
