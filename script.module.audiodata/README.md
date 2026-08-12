# script.module.audiodata

Reads what an audio track really is, out of its own bitstream.

A player reports the audio format it is feeding its sink, not the one the file
carries. During passthrough Kodi reports no PCM bit depth at all, and a DTS-HD
track reports the 48 kHz core every decoder can fall back to rather than the
96 or 192 kHz its extension substream actually stores. This module reads those
numbers from the stream itself.

Stdlib only. No binaries, no native libraries, no player API — every parser is
testable off the device.

## Installation

Declare it in your addon's `addon.xml`:

```xml
<import addon="script.module.audiodata" version="1.0.0"/>
```

## Usage

```python
import audiodata

with open("movie.mkv", "rb") as f:
    tracks = audiodata.probe(f.read)

for track in tracks:
    print(track["codec"], track["sample_rate"], track["bit_depth"])
```

`probe(read, budget=...)` takes any callable returning up to `n` bytes and
`b""` at the end of the stream. It is only ever called forwards, so a Kodi VFS
handle works directly:

```python
handle = xbmcvfs.File(url)
tracks = audiodata.probe(lambda n: bytes(handle.readBytes(n) or b""))
```

## Result

One entry per audio track:

| Key | Content |
|---|---|
| `codec` | plain codec name (`dts`, `truehd`, `mlp`, `ac3`, `eac3`, `flac`, `pcm`, `aac`, …) |
| `sample_rate` | sample rate in Hz, or `None` |
| `bit_depth` | PCM bit depth, or `None` when the format codes none |
| `channels` | channel count, or `None` |
| `language` | ISO language tag, `"und"` when unknown |

`probe` never raises. A stream it cannot read yields `[]`, which callers should
read as "no reading", not as "no audio".

## How a stream is read

Two paths, picked from what the stream turns out to be:

- **Matroska** is parsed properly. Its Tracks element gives every audio track
  in declaration order, which is what lets a caller match the track a player
  reports as active against the one read here. Clusters are only walked for the
  formats whose container header can be wrong (DTS, TrueHD, MLP); a PCM or FLAC
  track is fully described where it sits.
- **Everything else** (MPEG-TS/M2TS, MP4, a raw elementary stream) is scanned
  for the codecs' own sync words, yielding one entry per codec family rather
  than per track. A caller matching on codec family still resolves it; one that
  needs track order does not.

Reading is sequential and budgeted (16 MiB by default) so a stream whose frames
never parse still terminates, and nothing larger than one chunk is held.

## Formats

| Format | Sample rate | Bit depth |
|---|---|---|
| DTS extension substream | asset descriptor `nuMaxSampleRate` | `nuBitResolution` |
| DTS core | `SFREQ` | — (lossy) |
| TrueHD | major sync rate code | 24, the value FFmpeg also hardcodes; the bitstream carries none |
| MLP | major sync rate code | major sync quantization code |
| FLAC | STREAMINFO | STREAMINFO |
| AC-3 / E-AC-3 | `fscod` / `fscod2` | — (lossy) |
| PCM, others | container | container |

Field layouts follow FFmpeg's own parsers (`dca_exss.c`, `dca_parser.c`,
`mlp_parser.c`, `ac3_parser.c`) so the numbers line up with what other tools
report for the same stream.

## Known limitations

- **AC-3 is not scanned for.** Its sync word is 16 bits, which turns up roughly
  every 64 KiB of arbitrary data, and range-checking the rest of the header does
  not make that reliable without a track boundary to anchor it to. It is parsed
  where Matroska names the track. Nothing is lost: AC-3 and E-AC-3 are lossy, so
  they code no PCM bit depth, and their sample rate is whatever the container
  already says.
- **MP4 and MPEG-TS are scanned, not demuxed.** Their results carry no track
  order and no language, and a file with two tracks of the same codec family at
  different rates reports whichever header comes first.
- **TrueHD carries no bit depth.** 24 is reported because that is what the
  format is in practice and what FFmpeg assumes; it is not read from the stream.
- **Only the first DTS asset is read.** Multi-asset extension substreams are
  not enumerated.

## Testing

```
python3 -m unittest discover tests
```

The tests build synthetic bitstreams whose field values are known and assert
they survive the round trip. That proves the parsers agree with the layouts
documented in `codecs.py`; it does not prove those layouts match a real
encoder's output, which only a real stream can show.

## License

MIT.
