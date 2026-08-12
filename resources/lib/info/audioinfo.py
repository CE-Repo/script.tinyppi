"""Audio-bitstream metadata via script.module.audiodata.

Kodi reports the audio format it is feeding the sink, not the one the file
carries: during passthrough ``audiobitspersample`` is always 8, and a DTS-HD
track reports its 48 kHz compatibility core rather than the 96/192 kHz the
extension substream stores.  The audiodata module reads those numbers out of
the source bitstream itself, so the overlay can show the true depth and rate of
the track being played.

The stream is read through Kodi's own VFS, so nfs:// / smb:// / bluray:// URLs
work exactly like a local path and nothing has to be copied to disk.  Reading
is sequential and budgeted: the module stops as soon as every track has
answered, and nothing larger than one chunk is ever held in memory.  Detection
runs once per file in a background thread so the polling loop never blocks, and
the completed track list is cached on Kodi's Home window, which survives the
separate script invocations the addon is launched through.

Blu-ray discs are a special case: Kodi hands us the raw ``*.iso``, a
``bluray://`` title stream, or a ``.mpls`` playlist, and reading the ISO header
alone finds the wrong clip.  ``_resolve_disc_stream`` maps the reference to the
``.m2ts`` clip actually playing: a playlist is parsed to its clip, a bare image
falls back to the main feature, and an already-resolved title stream is read
as-is.
"""

import json
import threading
import urllib.parse
import uuid

import xbmc
import xbmcgui
import xbmcvfs

try:
    import audiodata as _audiodata
    _AUDIODATA_IMPORT_ERROR = None
except Exception as exc:  # a missing/broken module must not take the addon down
    _audiodata = None
    _AUDIODATA_IMPORT_ERROR = exc

# Kodi Window properties survive separate script invocations, so the completed
# track list is kept there to avoid re-reading during the same playback.
_CACHE_SESSION_PROPERTY        = "TinyPPI.AudioInfo.Session"
_CACHE_RESULT_SESSION_PROPERTY = "TinyPPI.AudioInfo.ResultSession"
_CACHE_PATH_PROPERTY           = "TinyPPI.AudioInfo.Path"
_CACHE_READY_PROPERTY          = "TinyPPI.AudioInfo.Ready"
_CACHE_TRACKS_PROPERTY         = "TinyPPI.AudioInfo.Tracks"

_inflight: set[str] = set()  # paths currently being processed
_lock               = threading.Lock()

_logged_import_error = False


def _log(msg: str, level: int = xbmc.LOGINFO) -> None:
    xbmc.log(f"TinyPPI: {msg}", level)


# --- Playback cache --------------------------------------------------------

def _cache_window() -> xbmcgui.Window:
    """Return Kodi's global home window used for cross-invocation caching."""
    return xbmcgui.Window(10000)


def _session_token(window: xbmcgui.Window | None = None) -> str:
    """Return the current playback-session token."""
    window = window or _cache_window()
    return window.getProperty(_CACHE_SESSION_PROPERTY) or "0"


def _cache_is_current(window, path: str, session_token: str) -> bool:
    """Return whether the window cache holds a completed result for ``path``."""
    return (
        window.getProperty(_CACHE_READY_PROPERTY) == "true"
        and window.getProperty(_CACHE_RESULT_SESSION_PROPERTY) == session_token
        and window.getProperty(_CACHE_PATH_PROPERTY) == path
    )


def _read_cached_tracks(path: str, session_token: str) -> str | None:
    """Return the cached track list for ``path`` as its stored JSON string, or
    None when the cache holds no completed result for it.

    None means "not read yet"; ``''`` means the read finished and found no
    track, which is a different answer.
    """
    window = _cache_window()
    if not _cache_is_current(window, path, session_token):
        return None
    return window.getProperty(_CACHE_TRACKS_PROPERTY)


def _write_cached_tracks(path: str, tracks: str, session_token: str) -> bool:
    """Publish a completed result if playback is still in the same session."""
    window = _cache_window()
    if _session_token(window) != session_token:
        return False

    try:
        if xbmc.Player().getPlayingFile() != path:
            return False
    except RuntimeError:
        return False

    # Ready is written last so readers never see a partial result; an empty
    # track list intentionally caches a completed "nothing found" result.
    window.clearProperty(_CACHE_READY_PROPERTY)
    window.setProperty(_CACHE_RESULT_SESSION_PROPERTY, session_token)
    window.setProperty(_CACHE_PATH_PROPERTY, path)
    window.setProperty(_CACHE_TRACKS_PROPERTY, tracks)
    window.setProperty(_CACHE_READY_PROPERTY, "true")
    return True


def reset_playback_cache() -> None:
    """Clear the cached audio tracks and begin a new playback-cache session."""
    window = _cache_window()
    window.clearProperty(_CACHE_READY_PROPERTY)
    window.clearProperty(_CACHE_RESULT_SESSION_PROPERTY)
    window.clearProperty(_CACHE_PATH_PROPERTY)
    window.clearProperty(_CACHE_TRACKS_PROPERTY)
    window.setProperty(_CACHE_SESSION_PROPERTY, uuid.uuid4().hex)

    with _lock:
        _inflight.clear()


# --- Blu-ray stream resolution ---------------------------------------------

def _vfs_join(base: str, tail: str) -> str:
    """Join a VFS base directory and a relative tail with a single separator."""
    return f"{base.rstrip('/')}/{tail}"


def _mpls_clip_names(data: bytes) -> list[str]:
    """Return the ordered clip stems (e.g. ``['00801']``) a Blu-ray ``.mpls``
    playlist plays, or ``[]`` when unparseable.  Only the PlayList section is
    walked: each PlayItem's 5-char ``clip_information_file_name`` plus 4-char
    ``clip_codec_identifier`` (``M2TS``) is all that's needed to map a title
    back to its stream file(s)."""
    if len(data) < 12 or data[:4] != b"MPLS":
        return []

    playlist_start = int.from_bytes(data[8:12], "big")
    # PlayList section: length(4) reserved(2) number_of_PlayItems(2) …
    if playlist_start + 8 > len(data):
        return []
    count = int.from_bytes(data[playlist_start + 6:playlist_start + 8], "big")

    names: list[str] = []
    pos = playlist_start + 10  # skip length(4) reserved(2) n_items(2) n_subpaths(2)
    for _ in range(count):
        if pos + 2 > len(data):
            break
        length = int.from_bytes(data[pos:pos + 2], "big")
        item = data[pos + 2:pos + 2 + length]
        if len(item) >= 9 and item[5:9] == b"M2TS":
            name = item[:5].decode("ascii", "ignore")
            if name.isdigit():
                names.append(name)
        pos += 2 + length
    return names


def _clip_from_playlist(mpls_path: str) -> str:
    """Return the VFS path of the first ``.m2ts`` clip the given ``.mpls``
    playlist plays, so the title the viewer actually selected is read.
    Returns ``''`` when the playlist can't be read/parsed (e.g. the VFS handed
    back the already-assembled title stream), letting the caller fall back to
    the playing URL directly."""
    idx = mpls_path.lower().rfind("/playlist/")
    if idx == -1:
        return ""

    try:
        f = xbmcvfs.File(mpls_path)
        try:
            # The header plus every PlayItem sits well within the first chunk.
            data = f.readBytes(256 * 1024)
        finally:
            f.close()
    except Exception as exc:
        _log(f"Audio: cannot read playlist {mpls_path}: {exc}", xbmc.LOGWARNING)
        return ""

    clips = _mpls_clip_names(bytes(data))
    if not clips:
        return ""

    # …/PLAYLIST/<n>.mpls -> …/STREAM/<clip>.m2ts, in the same VFS namespace so
    # bluray:// / udf:// / plain paths all resolve without re-encoding.
    stream_dir = mpls_path[:idx] + "/STREAM/"
    return f"{stream_dir}{clips[0]}.m2ts"


def _disc_image_stream_dir(path: str) -> str:
    """Return the ``BDMV/STREAM/`` VFS directory URL for a raw Blu-ray image or
    extracted disc folder, or ``''`` otherwise.  Only used for a bare image
    with no title information; a ``bluray://``/``.mpls``/``.m2ts`` path already
    identifies the playing stream and isn't routed here."""
    low = path.lower()

    # A raw disc image: wrap it in Kodi's UDF VFS so its files can be listed.
    if low.endswith(".iso"):
        return f"udf://{urllib.parse.quote(path, safe='')}/BDMV/STREAM/"

    # An already-extracted Blu-ray folder (the …/BDMV directory itself).
    trimmed = path.rstrip("/")
    if trimmed.lower().endswith("/bdmv"):
        return _vfs_join(trimmed, "STREAM/")

    return ""


def _largest_stream_file(stream_dir: str) -> str:
    """Return the VFS path of the largest ``.m2ts`` in a ``BDMV/STREAM``
    directory, or ``''`` when it can't be listed or holds no stream files.  Used
    only as the last-resort fallback for a bare disc image ("play main movie"
    mode), where the largest clip is the main feature."""
    try:
        _dirs, files = xbmcvfs.listdir(stream_dir)
    except Exception as exc:
        _log(f"Audio: cannot list {stream_dir}: {exc}", xbmc.LOGWARNING)
        return ""

    best_path, best_size = "", -1
    for name in files:
        if not name.lower().endswith(".m2ts"):
            continue
        candidate = stream_dir + name
        try:
            size = xbmcvfs.Stat(candidate).st_size()
        except Exception:
            continue
        if size > best_size:
            best_path, best_size = candidate, size
    return best_path


def _resolve_disc_stream(path: str) -> str:
    """Resolve a Blu-ray reference to the ``.m2ts`` clip actually playing, so
    the read covers the selected title rather than the disc-image filesystem
    header.  A ``.mpls`` playlist is parsed to its first clip; a bare ``.iso``/
    extracted ``BDMV`` folder carries no title info, so the largest clip is
    used; everything else already refers to the playing stream and is
    returned unchanged.
    """
    low = path.lower()

    if low.endswith(".mpls"):
        clip = _clip_from_playlist(path)
        if clip:
            _log(f"Audio: reading playlist clip {clip}")
            return clip
        _log(f"Audio: playlist {path} unresolved; reading it directly",
             xbmc.LOGWARNING)
        return path

    if low.endswith(".iso") or low.rstrip("/").endswith("/bdmv"):
        stream_dir = _disc_image_stream_dir(path)
        main = _largest_stream_file(stream_dir) if stream_dir else ""
        if main:
            _log(f"Audio: reading disc main feature {main}")
            return main
        _log(f"Audio: no clip resolved for {path}; reading it directly",
             xbmc.LOGWARNING)

    return path


# --- Detection -------------------------------------------------------------

def _detect(path: str) -> list[dict]:
    """Return the source audio-track list for the given playing path.

    The stream is opened through Kodi's VFS, so a local file and an nfs:// URL
    take the same path, and handed to audiodata as a sequential reader.  The
    full track list is returned so the active track can be selected -- and
    re-selected on a track change -- at read time.
    """
    global _logged_import_error

    if _audiodata is None:
        if not _logged_import_error:
            _logged_import_error = True
            _log(
                "Audio: script.module.audiodata unavailable "
                f"({_AUDIODATA_IMPORT_ERROR}); source audio metadata is not "
                "available",
                xbmc.LOGWARNING,
            )
        return []

    source = _resolve_disc_stream(path)
    try:
        handle = xbmcvfs.File(source)
    except Exception as exc:
        _log(f"Audio: cannot open {source}: {exc}", xbmc.LOGWARNING)
        return []

    try:
        report = _audiodata.probe(_VfsSource(handle),
                                  extension=_extension_of(source))
    finally:
        try:
            handle.close()
        except Exception:
            pass

    if report.error:
        _log(f"Audio: {source}: {report.error}", xbmc.LOGWARNING)
    elif report.container:
        _log(f"Audio: {source} read as {report.container}, "
             f"{len(report.tracks)} audio track(s)")
    return [track.as_dict() for track in report.tracks]


def _extension_of(source: str) -> str:
    """Return the source's file extension, for a raw elementary stream.

    Every container is sniffed from its own magic; only a bare ``.dts`` or
    ``.thd`` has none, and there the extension picks which parser to try first.
    """
    tail = source.rsplit("/", 1)[-1]
    return tail.rsplit(".", 1)[-1] if "." in tail else ""


class _VfsSource:
    """Adapts a Kodi VFS file handle to the seekable reader audiodata wants.

    ``readBytes`` hands back a bytearray, so it is normalised to bytes here and
    nothing downstream has to care which it got.
    """

    __slots__ = ("_handle",)

    def __init__(self, handle):
        self._handle = handle

    def read(self, count: int) -> bytes:
        return bytes(self._handle.readBytes(count) or b"")

    def seek(self, offset: int, whence: int = 0) -> int:
        return self._handle.seek(offset, whence)

    def size(self) -> int:
        try:
            return int(self._handle.size())
        except Exception:
            return 0


def _worker(path: str, session_token: str) -> None:
    """Background detection job; caches one completed result per playback."""
    try:
        tracks = _detect(path)
    except Exception as exc:
        _log(f"Audio detection failed: {exc}", xbmc.LOGWARNING)
        tracks = []

    try:
        _write_cached_tracks(
            path,
            json.dumps(tracks, separators=(",", ":")) if tracks else "",
            session_token,
        )
    finally:
        with _lock:
            _inflight.discard(path)


def _start_worker(path: str, session_token: str) -> bool:
    """Spawn the background detection worker for ``path`` unless one is already
    in flight for it.  Returns True when a new worker was started."""
    with _lock:
        if path in _inflight:
            return False
        _inflight.add(path)

    threading.Thread(
        target=_worker,
        args=(path, session_token),
        daemon=True,
    ).start()
    return True


def prime_playback_detection() -> bool:
    """Kick off the audio-bitstream read for the currently playing file ahead of
    time.

    Called from the background service at playback start so the result is
    already cached before the overlay is ever opened.  Non-blocking; a no-op
    when nothing is playing or a result is already cached/in flight.  Returns
    True when a new detection worker was started.
    """
    try:
        path = xbmc.Player().getPlayingFile()
    except RuntimeError:
        return False
    if not path:
        return False

    session_token = _session_token()
    if _cache_is_current(_cache_window(), path, session_token):
        return False

    return _start_worker(path, session_token)


# --- Track selection -------------------------------------------------------

def _cached_audio_tracks() -> list[dict]:
    """Return the cached audio-track list for the current file (starting
    background detection on first access), or ``[]`` while it runs / when none
    were found."""
    try:
        path = xbmc.Player().getPlayingFile()
    except RuntimeError:
        return []
    if not path:
        return []

    session_token = _session_token()
    value = _read_cached_tracks(path, session_token)
    if value is None:
        _start_worker(path, session_token)
        return []
    if not value:
        return []

    try:
        tracks = json.loads(value)
    except ValueError:
        return []
    return tracks if isinstance(tracks, list) else []


def _norm_audio_family(name) -> str:
    """Collapse a codec name — audiodata's (``"DTS-HD MA"``) or Kodi's
    (``"dtshd_ma"`` / ``"dca"``) — to a comparable family token, so the active
    Kodi stream can be matched against a read track regardless of naming."""
    token = "".join(ch for ch in str(name or "").lower() if ch.isalnum())
    if not token:
        return ""
    if "truehd" in token:
        return "truehd"
    if "mlp" in token:
        return "mlp"
    if "dts" in token or token.startswith("dca"):
        return "dts"
    if "eac3" in token or "ddp" in token:
        return "eac3"
    if "ac3" in token:
        return "ac3"
    if "flac" in token:
        return "flac"
    if "pcm" in token:
        # audiodata says "LPCM (Blu-ray)" / "PCM"; Kodi says "pcm_bluray".
        return "pcm"
    if "aac" in token:
        return "aac"
    return token


def _current_audio_stream() -> dict:
    """Return Kodi's currently active audio stream (``index`` / ``codec`` / …)
    via JSON-RPC, or ``{}`` when nothing is playing or the query fails.  Read
    live so a track change is reflected without re-reading the file."""
    try:
        active = json.loads(xbmc.executeJSONRPC(json.dumps({
            "jsonrpc": "2.0", "id": 1, "method": "Player.GetActivePlayers",
        })))
        players = active.get("result") or []
        playerid = next(
            (p.get("playerid") for p in players if p.get("type") == "video"),
            None,
        )
        if playerid is None:
            return {}
        props = json.loads(xbmc.executeJSONRPC(json.dumps({
            "jsonrpc": "2.0", "id": 1, "method": "Player.GetProperties",
            "params": {
                "playerid": playerid,
                "properties": ["currentaudiostream"],
            },
        })))
        stream = (props.get("result") or {}).get("currentaudiostream") or {}
        return stream if isinstance(stream, dict) else {}
    except (ValueError, KeyError, TypeError):
        return {}


def _active_audio_track() -> dict | None:
    """Select the read track for the audio stream Kodi is currently playing.

    For a Matroska file both Kodi and audiodata enumerate the container's audio
    tracks in order, so the active stream ``index`` maps straight into the
    list; the codec family is cross-checked to guard against the two orderings
    diverging.  Other containers are scanned rather than enumerated, so the
    list holds one entry per codec family and only the family match resolves
    it.  Re-evaluated on every read, so switching audio track updates the
    values without re-reading the file.
    """
    tracks = _cached_audio_tracks()
    if not tracks:
        return None
    if len(tracks) == 1:
        return tracks[0]

    stream = _current_audio_stream()
    idx = stream.get("index")
    family = _norm_audio_family(stream.get("codec"))

    candidate = None
    if isinstance(idx, int) and 0 <= idx < len(tracks):
        candidate = tracks[idx]
        if not family or _norm_audio_family(candidate.get("codec")) == family:
            return candidate

    if family:
        matches = [
            track for track in tracks
            if _norm_audio_family(track.get("codec")) == family
        ]
        if len(matches) == 1:
            return matches[0]

    return candidate


def get_active_audio_bit_depth() -> str:
    """Return the bit depth of the active audio track as read from the source
    bitstream (e.g. ``"24"``), or '' while detection runs, when no depth is
    coded (lossy codecs carry none) or when no track could be selected.  No
    status label."""
    track = _active_audio_track()
    if not track:
        return ""
    depth = track.get("bit_depth")
    return str(depth) if isinstance(depth, int) and not isinstance(depth, bool) else ""


def get_active_audio_sample_rate() -> str:
    """Return the sample rate in Hz of the active audio track as read from the
    source bitstream (e.g. ``"96000"``), or '' while detection runs or no track
    could be selected.  Unlike Kodi's own value this is the true source rate,
    so DTS 96/24 and high-rate DTS-HD read correctly instead of as their 48 kHz
    compatibility core.  No status label."""
    track = _active_audio_track()
    if not track:
        return ""
    rate = track.get("sample_rate")
    return str(rate) if isinstance(rate, int) and not isinstance(rate, bool) else ""
