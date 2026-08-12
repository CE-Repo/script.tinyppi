# script.module.audiodata

Reads what an audio track really is, out of its own bitstream.

A player reports the audio format it is feeding its sink, not the one the file
carries. During passthrough Kodi reports no PCM bit depth at all, and a DTS-HD
track reports the 48 kHz core every decoder can fall back to rather than the
96 or 192 kHz its extension substream actually stores. This module reads those
numbers from the stream itself.

A pure-Python port of [audioprobe](https://github.com/CE-Repo/audioprobe),
covering the same containers and codecs. Stdlib only — no binaries, no native
libraries, no subprocesses.

## Installation

Declare it in your addon's `addon.xml`:

```xml
<import addon="script.module.audiodata" version="1.0.0"/>
```

## Usage

```python
import audiodata

report = audiodata.probe("movie.mkv")
print(report.container)                       # "Matroska"
for track in report.tracks:
    print(track.codec, track.sample_rate, track.bit_depth, track.layout())
```

`probe(source, ...)` accepts a filesystem path, a `bytes` buffer, or any
seekable file-like object with `read` and `seek` — so a Kodi VFS handle works
through a thin adapter:

```python
class VfsSource:
    def __init__(self, handle): self._h = handle
    def read(self, n):          return bytes(self._h.readBytes(n) or b"")
    def seek(self, off, wh=0):  return self._h.seek(off, wh)
    def size(self):             return self._h.size()

report = audiodata.probe(VfsSource(xbmcvfs.File(url)))
```

`probe_tracks(source, ...)` returns the same tracks as plain dicts, for callers
crossing a JSON edge.

### Options

| Argument | Meaning |
|---|---|
| `scan_limit` | how far into a transport or program stream the audio PES is followed (default 64 MiB) |
| `deep` | sample frames out of the container for codecs the container describes incompletely (default on) |
| `extension` | orders the candidates for a raw elementary stream, which carries no magic to sniff |

## Result

`probe` returns a `Report` with `container`, `tracks`, `error` and `truncated`.
Each `Track`:

| Field | Content |
|---|---|
| `id` | container-specific identifier (Matroska track number, TS PID, MP4 track id) |
| `codec` | display name (`DTS-HD MA`, `TrueHD`, `LPCM (Blu-ray)`, `AAC-LC`, …) |
| `sample_rate` | sample rate in Hz, or `None` |
| `bit_depth` | PCM bit depth, or `None` where the format codes none |
| `channels`, `lfe` | channel count and whether an LFE channel is present |
| `layout()` | `5.1`-style layout derived from those two |
| `language`, `title`, `default` | as the container declares them |
| `note` | how a reading was qualified, e.g. `parameters from embedded AC-3 core` |

`probe` never raises. A source it cannot read yields a `Report` whose `error`
carries the reason and whose `tracks` are empty — read that as "no reading",
not as "no audio".

## Supported inputs

| Containers | Matroska/WebM, MPEG-TS, BDAV M2TS (192-byte packets), MP4/MOV/M4A, AVI, MPEG program streams (`.mpg .vob`), FLAC, WAV, Ogg |
|---|---|
| **Disc images** | Blu-ray ISO (BDMV over UDF, including UDF 2.50 metadata partitions) and DVD-Video ISO (VIDEO_TS over ISO9660) |
| **Codecs** | AC-3, E-AC-3, DTS, DTS-ES, DTS 96/24, DTS-HD MA/HRA, DTS Express, TrueHD, MLP, AAC (ADTS, LATM/LOAS, ASC), HE-AAC, MP1/MP2/MP3, FLAC, PCM/LPCM (Blu-ray + DVD), ALAC, Opus, Vorbis, WAVEFORMATEX |
| **Elementary streams** | `.ac3 .eac3 .dts .dtshd .thd .mlp .aac .mp3` … |

Bit depth is reported where the format defines one (PCM, FLAC, ALAC, DTS,
TrueHD, Blu-ray and DVD LPCM). Perceptual codecs like AC-3, AAC or Opus have no
meaningful bit depth and report `None`.

### Where each reading comes from

| Format | Sample rate | Bit depth |
|---|---|---|
| DTS extension substream | asset descriptor `nuMaxSampleRate` | `nuBitResolution` |
| DTS core | `SFREQ` | `PCMR` |
| TrueHD | major sync rate code | 24, the value FFmpeg also assumes; the bitstream carries none |
| MLP | major sync rate code | major sync quantization code |
| Blu-ray / DVD LPCM | PES audio data header | same header |
| FLAC / ALAC | STREAMINFO / ALACSpecificConfig | same |
| AAC | ASC, ADTS or LATM (SBR extension rate wins) | — |
| AC-3 / E-AC-3 | `fscod` / `fscod2` | — |
| PCM, others | container | container |

Field layouts follow FFmpeg's own parsers (`dca_exss.c`, `dca_parser.c`,
`mlp_parser.c`, `ac3_parser.c`) and audioprobe, so the numbers line up with
what other tools report for the same stream.

## How a disc image is read

Blu-ray: walk the UDF filesystem to `BDMV/PLAYLIST`, rank the playlists by
deduped duration, pick the winner's largest clip and read that
`BDMV/STREAM/*.m2ts` as a transport stream. Deduping by `(clip, in, out)`
collapses an obfuscation decoy's looped segment to a single contribution, so a
decoy cannot out-rank the real feature; playlists naming clips absent from
`STREAM` are dropped, and identical PlayItem sequences collapse to the
lowest-numbered playlist.

DVD-Video: walk the ISO9660 bridge to `VIDEO_TS`, pick the title set with the
most VOB bytes across its parts and read its first `VTS_tt_1.VOB` as a program
stream.

Both address the image by absolute byte range rather than mapping it, so a
40 GB image costs only the ranges actually read.

## Differences from audioprobe

- **No NAS prefetcher.** audioprobe memory-maps a file and pre-streams the
  regions it is about to parse. A Kodi VFS handle cannot be mapped, so reads go
  straight through the VFS. Local files lose the mmap fast path.
- **No CLI, no directory walking, no output rendering.** This is the parsing
  half; presentation belongs to the caller.
- An AACS-encrypted Blu-ray is reported as such, but not decrypted — same as
  audioprobe.

## Known limitations

- **Only the first DTS asset is read.** Multi-asset extension substreams are
  not enumerated.
- **TrueHD carries no bit depth.** 24 is reported because that is what the
  format is in practice and what FFmpeg assumes; it is not read from the
  stream.
- **Fragmented clips inside an ISO are not read.** UDF caps a single extent
  near 1 GiB, so a feature-length clip is many exactly-adjacent extents; a
  genuinely scattered file is refused rather than read wrongly.
- **DVB Opus in a transport stream** carries no in-band OpusHead, so it is
  named but not measured.

## Testing

```
python3 -m unittest discover tests
```

The tests build synthetic bitstreams, containers and disc images whose field
values are known, and assert they survive the round trip. That proves the
parsers agree with the layouts documented in the source; it does not prove
those layouts match a real encoder's output, which only a real stream can show.

## License

MIT.
