"""Codec bitstream header parsers: synthetic frames in, known values out."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "lib"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import builders as b                                    # noqa: E402
from audiodata import codecs                            # noqa: E402
from audiodata.bitreader import BitReader               # noqa: E402


class TestBitReader(unittest.TestCase):

    def test_reads_msb_first_across_byte_boundaries(self):
        r = BitReader(bytes([0b1010_1100, 0b0101_0011]))
        self.assertEqual(r.read(3), 0b101)
        self.assertEqual(r.read(5), 0b01100)
        self.assertEqual(r.read(8), 0b0101_0011)

    def test_wide_read(self):
        self.assertEqual(BitReader(b"\x64\x58\x20\x25").read(32), 0x64582025)

    def test_past_the_end_raises(self):
        with self.assertRaises(EOFError):
            BitReader(b"\x00").read(9)


class TestDts(unittest.TestCase):

    def test_core_states_its_own_rate_depth_and_layout(self):
        info = codecs.dts.parse(b.dts_core())
        self.assertEqual(info.sample_rate, 48000)
        self.assertEqual(info.bit_depth, 24)       # PCMR index 5
        self.assertEqual(info.channels, 6)         # AMODE 9 (5ch) + LFE
        self.assertTrue(info.lfe)
        self.assertEqual(info.name, "DTS")

    def test_core_pcmr_table(self):
        for pcmr, depth in ((0, 16), (1, 16), (2, 20), (3, 20), (5, 24), (6, 24)):
            info = codecs.dts.parse(b.dts_core(pcmr=pcmr))
            self.assertEqual(info.bit_depth, depth, f"pcmr {pcmr}")
        for pcmr in (4, 7):
            self.assertIsNone(codecs.dts.parse(b.dts_core(pcmr=pcmr)).bit_depth)

    def test_core_with_crc_shifts_the_later_fields(self):
        # CPF inserts a 16-bit HCRC ahead of PCMR; reading it wrong would move
        # the bit depth.
        self.assertEqual(codecs.dts.parse(b.dts_core(cpf=1)).bit_depth, 24)

    def test_core_reserved_rate_rejected(self):
        self.assertIsNone(codecs.dts.parse(b.dts_core(sfreq=4)))

    def test_core_short_frame_rejected(self):
        self.assertIsNone(codecs.dts.parse(b.dts_core(fsize=10)))

    def test_extension_round_trip(self):
        info = codecs.dts.parse(b.dts_exss())
        self.assertEqual(info.sample_rate, 96000)
        self.assertEqual(info.bit_depth, 24)
        self.assertEqual(info.channels, 8)

    def test_every_extension_rate_index(self):
        expected = (8000, 16000, 32000, 64000, 128000, 22050, 44100, 88200,
                    176400, 352800, 12000, 24000, 48000, 96000, 192000, 384000)
        for index, rate in enumerate(expected):
            info = codecs.dts.parse(b.dts_exss(rate_index=index))
            self.assertEqual(info.sample_rate, rate, f"index {index}")

    def test_optional_descriptor_fields_are_skipped(self):
        for kwargs in ({"asset_type": True}, {"language": True}, {"text": 12},
                       {"asset_type": True, "language": True, "text": 5}):
            info = codecs.dts.parse(b.dts_exss(**kwargs))
            self.assertEqual((info.sample_rate, info.bit_depth), (96000, 24), kwargs)

    def test_long_header_flavour(self):
        # header_size_type 1 widens the header, frame and per-asset size
        # fields; reading any of them at the short width shifts everything
        # after it.
        info = codecs.dts.parse(b.dts_exss(long_header=True))
        self.assertEqual((info.sample_rate, info.bit_depth, info.channels),
                         (96000, 24, 8))

    def test_long_header_with_optional_descriptor_fields(self):
        info = codecs.dts.parse(b.dts_exss(long_header=True, asset_type=True,
                                           language=True, text=7))
        self.assertEqual((info.sample_rate, info.bit_depth), (96000, 24))

    def test_extension_without_static_fields_yields_nothing(self):
        info = codecs.dts.parse(b.dts_exss(static_fields=False))
        self.assertEqual(info.name, "DTS-HD")       # named, but no parameters
        self.assertIsNone(info.sample_rate)

    def test_extension_wins_over_core(self):
        info = codecs.dts.parse(b.dts_core() + b.dts_exss())
        self.assertEqual(info.sample_rate, 96000)

    def test_flavour_naming(self):
        core, exss = b.dts_core(), b.dts_exss()
        self.assertEqual(codecs.dts.parse(core + exss + b.DTS_XLL_SYNC).name,
                         "DTS-HD MA")
        self.assertEqual(codecs.dts.parse(core + exss + b.DTS_XBR_SYNC).name,
                         "DTS-HD HRA")
        self.assertEqual(codecs.dts.parse(exss + b.DTS_LBR_SYNC).name,
                         "DTS Express")
        self.assertEqual(codecs.dts.parse(core + exss).name, "DTS-HD")

    def test_core_extension_naming(self):
        self.assertEqual(
            codecs.dts.parse(b.dts_core(ext_audio=1, ext_audio_id=0)).name, "DTS-ES")
        self.assertEqual(
            codecs.dts.parse(b.dts_core(ext_audio=1, ext_audio_id=2)).name, "DTS 96/24")
        self.assertEqual(
            codecs.dts.parse(b.dts_core(ext_audio=0, ext_audio_id=2)).name, "DTS")

    def test_no_sync_word(self):
        self.assertIsNone(codecs.dts.parse(b"\x00" * 512))


class TestTrueHd(unittest.TestCase):

    def test_rate_codes(self):
        for code, rate in ((0, 48000), (1, 96000), (2, 192000),
                           (8, 44100), (9, 88200), (10, 176400)):
            info = codecs.truehd.parse(b.truehd(rate_code=code))
            self.assertEqual(info.sample_rate, rate, f"code {code}")

    def test_rates_above_192k_rejected(self):
        self.assertIsNone(codecs.truehd.parse(b.truehd(rate_code=3)))

    def test_reserved_rate_rejected(self):
        self.assertIsNone(codecs.truehd.parse(b.truehd(rate_code=0xF)))

    def test_channel_assignment_and_lfe(self):
        # 8ch field bits 0..4 set: 2+1+1+2+2 = 8 channels, LFE on bit 2.
        info = codecs.truehd.parse(b.truehd(ch8=0x1F))
        self.assertEqual(info.channels, 8)
        self.assertTrue(info.lfe)
        self.assertEqual(info.bit_depth, 24)

    def test_falls_back_to_the_6ch_field(self):
        info = codecs.truehd.parse(b.truehd(ch8=0, ch6=0x0F))
        self.assertEqual(info.channels, 6)         # 2+1+1+2

    def test_major_sync_signature_is_required(self):
        # The same bytes without the 0xB752 signature must not be trusted.
        frame = bytearray(b.truehd())
        frame[8:10] = b"\x00\x00"
        self.assertIsNone(codecs.truehd.parse(bytes(frame)))

    def test_mlp_carries_its_own_depth_and_layout(self):
        info = codecs.truehd.parse(b.mlp(quant_code=0, rate_code=1, assignment=6))
        self.assertEqual((info.name, info.sample_rate, info.bit_depth), ("MLP", 96000, 16))
        self.assertEqual(info.channels, 5)


class TestAc3(unittest.TestCase):

    def test_ac3_rates_and_layout(self):
        for fscod, rate in ((0, 48000), (1, 44100), (2, 32000)):
            info = codecs.ac3.parse(b.ac3(fscod=fscod))
            self.assertEqual(info.sample_rate, rate, f"fscod {fscod}")
            self.assertEqual(info.channels, 6)     # acmod 7 (3/2) + LFE
            self.assertTrue(info.lfe)
            self.assertIsNone(info.bit_depth)

    def test_ac3_reserved_rate_rejected(self):
        self.assertIsNone(codecs.ac3.parse(b.ac3(fscod=3)))

    def test_ac3_invalid_frame_size_code_rejected(self):
        self.assertIsNone(codecs.ac3.parse(b.ac3(frmsizecod=38)))

    def test_eac3_half_rates(self):
        for fscod2, rate in ((0, 24000), (1, 22050), (2, 16000)):
            info = codecs.ac3.parse(b.eac3(fscod=3, fscod2=fscod2))
            self.assertEqual(info.sample_rate, rate, f"fscod2 {fscod2}")
            self.assertEqual(info.name, "E-AC-3")

    def test_eac3_dependent_substream_rejected(self):
        self.assertIsNone(codecs.ac3.parse(b.eac3(strmtyp=3)))


class TestAac(unittest.TestCase):

    def test_adts(self):
        info = codecs.aac.parse_adts(b.adts())
        self.assertEqual((info.name, info.sample_rate, info.channels),
                         ("AAC-LC", 48000, 6))
        self.assertIsNone(info.bit_depth)

    def test_asc(self):
        info = codecs.aac.parse_asc(b.asc())
        self.assertEqual((info.name, info.sample_rate, info.channels),
                         ("AAC-LC", 48000, 6))

    def test_sbr_extension_rate_wins(self):
        info = codecs.aac.parse_asc(b.asc(aot=5, sfi=6, ext_sfi=3))
        self.assertEqual((info.name, info.sample_rate), ("HE-AAC", 48000))

    def test_channel_configurations(self):
        self.assertEqual(codecs.aac.parse_asc(b.asc(chan_cfg=7)).channels, 8)
        self.assertEqual(codecs.aac.parse_asc(b.asc(chan_cfg=2)).channels, 2)
        self.assertIsNone(codecs.aac.parse_asc(b.asc(chan_cfg=0)).channels)


class TestMpegAudio(unittest.TestCase):

    def test_layers_and_versions(self):
        self.assertEqual(codecs.mpeg_audio.parse(b.mpeg_audio(layer=1)).name, "MP3")
        self.assertEqual(codecs.mpeg_audio.parse(b.mpeg_audio(layer=2)).name, "MP2")
        self.assertEqual(codecs.mpeg_audio.parse(b.mpeg_audio(layer=3)).name, "MP1")
        self.assertEqual(codecs.mpeg_audio.parse(b.mpeg_audio()).sample_rate, 44100)
        self.assertEqual(codecs.mpeg_audio.parse(b.mpeg_audio(version=2)).sample_rate,
                         22050)
        self.assertEqual(codecs.mpeg_audio.parse(b.mpeg_audio(version=0)).sample_rate,
                         11025)

    def test_reserved_fields_rejected(self):
        self.assertIsNone(codecs.mpeg_audio.parse(b.mpeg_audio(version=1)))
        self.assertIsNone(codecs.mpeg_audio.parse(b.mpeg_audio(layer=0)))
        self.assertIsNone(codecs.mpeg_audio.parse(b.mpeg_audio(sr_idx=3)))
        self.assertIsNone(codecs.mpeg_audio.parse(b.mpeg_audio(bitrate_idx=0xF)))

    def test_mono_mode(self):
        self.assertEqual(codecs.mpeg_audio.parse(b.mpeg_audio(mode=3)).channels, 1)


class TestFlac(unittest.TestCase):

    def test_round_trip_with_and_without_magic(self):
        for magic in (True, False):
            info = codecs.flac.parse(b.flac_streaminfo(magic=magic))
            self.assertEqual((info.sample_rate, info.bit_depth, info.channels),
                             (96000, 24, 2), f"magic={magic}")

    def test_zero_rate_rejected(self):
        self.assertIsNone(codecs.flac.parse(b.flac_streaminfo(sample_rate=0)))


class TestPcm(unittest.TestCase):

    def test_hdmv_lpcm(self):
        info = codecs.pcm.parse_hdmv_lpcm(b.hdmv_lpcm())
        self.assertEqual((info.name, info.sample_rate, info.bit_depth, info.channels),
                         ("LPCM (Blu-ray)", 96000, 24, 6))
        self.assertTrue(info.lfe)

    def test_hdmv_lpcm_tables(self):
        for fs, rate in ((1, 48000), (4, 96000), (5, 192000)):
            self.assertEqual(
                codecs.pcm.parse_hdmv_lpcm(b.hdmv_lpcm(sampling_frequency=fs)).sample_rate,
                rate)
        for bits, depth in ((1, 16), (2, 20), (3, 24)):
            self.assertEqual(
                codecs.pcm.parse_hdmv_lpcm(b.hdmv_lpcm(bits=bits)).bit_depth, depth)
        self.assertIsNone(codecs.pcm.parse_hdmv_lpcm(b.hdmv_lpcm(sampling_frequency=2)))
        self.assertIsNone(codecs.pcm.parse_hdmv_lpcm(b.hdmv_lpcm(bits=0)))

    def test_dvd_lpcm(self):
        info = codecs.pcm.parse_dvd_lpcm(b.dvd_lpcm())
        self.assertEqual((info.name, info.sample_rate, info.bit_depth, info.channels),
                         ("LPCM (DVD)", 96000, 24, 6))
        self.assertIsNone(codecs.pcm.parse_dvd_lpcm(b.dvd_lpcm(fs=2)))
        self.assertIsNone(codecs.pcm.parse_dvd_lpcm(b.dvd_lpcm(quant=3)))

    def test_waveformatex(self):
        info = codecs.pcm.parse_waveformatex(b.waveformatex())
        self.assertEqual((info.name, info.sample_rate, info.bit_depth, info.channels),
                         ("PCM", 48000, 24, 2))

    def test_waveformatex_lossy_tag_reports_no_depth(self):
        info = codecs.pcm.parse_waveformatex(b.waveformatex(tag=0x2000))
        self.assertEqual(info.name, "AC-3")
        self.assertIsNone(info.bit_depth)

    def test_waveformat_extensible_uses_the_subformat(self):
        info = codecs.pcm.parse_waveformatex(
            b.waveformatex(tag=0xFFFE, extensible_sub=1))
        self.assertEqual((info.name, info.bit_depth), ("PCM", 24))

    def test_alac_config(self):
        info = codecs.pcm.parse_alac_config(b.alac_config())
        self.assertEqual((info.name, info.sample_rate, info.bit_depth), ("ALAC", 96000, 24))
        self.assertIsNone(codecs.pcm.parse_alac_config(b.alac_config(depth=7)))


class TestXiph(unittest.TestCase):

    def test_opus_head(self):
        info = codecs.xiph.parse_opus_head(b.opus_head())
        self.assertEqual((info.name, info.sample_rate, info.channels),
                         ("Opus", 48000, 6))
        self.assertIsNone(info.note)

    def test_opus_notes_a_non_48k_input_rate(self):
        info = codecs.xiph.parse_opus_head(b.opus_head(input_rate=44100))
        self.assertEqual(info.sample_rate, 48000)
        self.assertIn("44100", info.note)

    def test_vorbis(self):
        info = codecs.xiph.parse_vorbis(b.vorbis_id())
        self.assertEqual((info.name, info.sample_rate, info.channels),
                         ("Vorbis", 44100, 2))


if __name__ == "__main__":
    unittest.main()
