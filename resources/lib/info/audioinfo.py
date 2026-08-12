"""Audio-bitstream metadata via audioprobe.

Kodi reports the audio format it is feeding the sink, not the one the file
carries: during passthrough ``audiobitspersample`` is always 8, and a DTS-HD
track reports its 48 kHz compatibility core rather than the 96/192 kHz
extension.  audioprobe (the aarch64 build in tools.tinyppi,
``tools/audioprobe/audioprobe``) reads the source bitstream itself, so the
overlay can show the true depth and rate of the track being played.

Kodi plays from VFS URLs (nfs://, smb://, http://) that audioprobe cannot open,
so the stream is piped into ``audioprobe --json -`` over stdin: blocks are read
through xbmcvfs and written to the probe until it has taken its head budget
(the write then fails with a broken pipe, the documented success signal) or the
stream ends.  Real filesystem paths are handed to audioprobe directly instead,
where it reads to EOF for the fullest analysis.  Detection runs once per file
in a background thread so the polling loop never blocks, and the completed
track list is cached on Kodi's Home window, which survives the separate script
invocations the addon is launched through.

Blu-ray discs are a special case: Kodi hands us the raw ``*.iso``, a
``bluray://`` title stream, or a ``.mpls`` playlist, and probing the ISO header
alone reads the wrong clip.  ``_resolve_disc_stream`` maps the reference to the
``.m2ts`` clip actually playing: a playlist is parsed to its clip, a bare image
falls back to the main feature, and an already-resolved title stream is read
as-is.
"""

import json
import os
import subprocess
import threading
import urllib.parse
import uuid

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs

# Read granularity for the VFS stream on the stdin path.  audioprobe reads a
# bounded head of its stdin and closes it (a broken pipe) once it has what it
# needs -- verified to take ~16 MiB of a UHD stream and mark the rest
# ``input_truncated`` -- so the read is bounded by the probe's own head budget.
# No fixed byte cap is imposed here (that would truncate the probe), and nothing
# larger than one block is ever held in memory.  Local files are read by the
# probe itself and never come through here.
_BLOCK_BYTES = 1024 * 1024

# Upper bound on how long to wait for audioprobe to finish.  Detection runs in a
# daemon background thread, so a probe that never exits (a broken build, a stuck
# signal) would otherwise hang that thread forever; on timeout the probe is
# killed and the track list stays empty, exactly like any other failed run.
_PROBE_TIMEOUT = 30

# Kodi Window properties survive separate script invocations, so the completed
# track list is kept there to avoid re-probing during the same playback.
_CACHE_SESSION_PROPERTY        = "TinyPPI.AudioInfo.Session"
_CACHE_RESULT_SESSION_PROPERTY = "TinyPPI.AudioInfo.ResultSession"
_CACHE_PATH_PROPERTY           = "TinyPPI.AudioInfo.Path"
_CACHE_READY_PROPERTY          = "TinyPPI.AudioInfo.Ready"
_CACHE_TRACKS_PROPERTY         = "TinyPPI.AudioInfo.Tracks"

_inflight: set[str] = set()  # paths currently being processed
_lock               = threading.Lock()


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

    None means "not probed yet"; ``''`` means the probe finished and found no
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


# --- Probe binary ----------------------------------------------------------

def _ensure_executable(path: str) -> None:
    """Restore the exec bit on the bundled binary, often lost when an addon is
    zipped and unpacked, so it can be spawned instead of raising PermissionError."""
    if os.path.exists(path) and not os.access(path, os.X_OK):
        try:
            os.chmod(path, 0o755)
        except OSError:
            pass


def _audioprobe() -> str:
    """Return the audioprobe path from tools.tinyppi, restoring the exec bit."""
    try:
        base = xbmcaddon.Addon("tools.tinyppi").getAddonInfo("path")
    except Exception:
        return ""
    path = os.path.join(base, "tools", "audioprobe", "audioprobe")
    _ensure_executable(path)
    return path


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
    playlist plays, so the title the viewer actually selected is probed.
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

    clips = _mpls_clip_names(data)
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
    the probe reads the selected title rather than the disc-image filesystem
    header.  A ``.mpls`` playlist is parsed to its first clip; a bare ``.iso``/
    extracted ``BDMV`` folder carries no title info, so the largest clip is
    used; everything else already refers to the playing stream and is
    returned unchanged.
    """
    low = path.lower()

    if low.endswith(".mpls"):
        clip = _clip_from_playlist(path)
        if clip:
            _log(f"Audio: probing playlist clip {clip}")
            return clip
        _log(f"Audio: playlist {path} unresolved; probing it directly",
             xbmc.LOGWARNING)
        return path

    if low.endswith(".iso") or low.rstrip("/").endswith("/bdmv"):
        stream_dir = _disc_image_stream_dir(path)
        main = _largest_stream_file(stream_dir) if stream_dir else ""
        if main:
            _log(f"Audio: probing disc main feature {main}")
            return main
        _log(f"Audio: no clip resolved for {path}; probing it directly",
             xbmc.LOGWARNING)

    return path


# --- Probing ---------------------------------------------------------------

def _decode_audio_tracks(out: str) -> list[dict]:
    """Parse audioprobe's JSON report from ``out`` and return the audio-track
    list of the first (only) file, trimmed to the fields the overlay needs.
    Decoding starts at the first brace so stray leading log text (and the
    probe's stdin parse warnings) are tolerated.  Returns ``[]`` when there's no
    decodable report, the file couldn't be read, or it carries no audio track.
    """
    start = out.find("{")
    if start == -1:
        return []
    try:
        data, _ = json.JSONDecoder().raw_decode(out[start:])
    except ValueError:
        return []
    if not isinstance(data, dict):
        return []

    files = data.get("files")
    if not isinstance(files, list) or not files or not isinstance(files[0], dict):
        return []

    raw_tracks = files[0].get("audio_tracks")
    if not isinstance(raw_tracks, list):
        return []

    # Keep only what track selection and the depth / rate getters read; codec,
    # channels and language are retained to match the track against Kodi's
    # active audio stream (see ``_active_audio_track``).
    tracks: list[dict] = []
    for track in raw_tracks:
        if isinstance(track, dict):
            tracks.append({
                "codec": track.get("codec"),
                "sample_rate": track.get("sample_rate"),
                "bit_depth": track.get("bit_depth"),
                "channels": track.get("channels"),
                "language": track.get("language"),
            })
    return tracks


def _run_audioprobe(probe: str, src: str) -> list[dict]:
    """Run audioprobe on a real filesystem ``src`` and return its audio-track
    list, or ``[]``.  Local paths only; Kodi VFS URLs are streamed over stdin
    instead (see ``_probe_stream_stdin``)."""
    try:
        out = subprocess.run(
            [probe, "--json", src],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            # Decode as UTF-8 (not the C/POSIX process locale): audioprobe echoes
            # the source path back, so an accented filename would otherwise raise
            # UnicodeDecodeError; errors="replace" tolerates stray bytes too.
            encoding="utf-8",
            errors="replace",
            # Guard the background thread against a probe that never exits;
            # subprocess.run kills it on timeout (raises TimeoutExpired).
            timeout=_PROBE_TIMEOUT,
        ).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        _log(f"Audio: audioprobe did not complete: {exc}", xbmc.LOGWARNING)
        return []
    return _decode_audio_tracks(out)


def _spawn_stdin_probe(probe: str) -> "subprocess.Popen | None":
    """Spawn ``<probe> --json -`` with a stdin pipe, or ``None`` when it cannot
    start."""
    try:
        return subprocess.Popen(
            [probe, "--json", "-"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
    except OSError as exc:
        _log(f"Audio: probe failed to start ({probe}): {exc}", xbmc.LOGWARNING)
        return None


def _collect_probe_output(proc: "subprocess.Popen") -> str:
    """Close ``proc``'s stdin, drain its stdout and return it as text.

    ``communicate()`` closes stdin (signalling EOF for short streams) and reads
    the small JSON report the probe writes only after it stops reading, so there
    is no deadlock; the timeout guards the background thread against a probe that
    never exits (it is then killed and reaped)."""
    try:
        out, _ = proc.communicate(timeout=_PROBE_TIMEOUT)
    except Exception as exc:
        _log(f"Audio: probe did not complete: {exc}", xbmc.LOGWARNING)
        proc.kill()
        proc.communicate()
        return ""
    return out.decode("utf-8", "replace") if out else ""


def _probe_stream_stdin(probe: str, vfs_url: str) -> list[dict]:
    """Probe a Kodi VFS stream without copying it to disk.

    audioprobe cannot open nfs:///smb:///bluray:///https:// URLs itself, so the
    stream is read through xbmcvfs and each block is written to its ``--json -``
    stdin.  Feeding stops once a stdin write fails with a broken pipe (the probe
    has taken its head budget) or the stream ends.  No fixed byte cap is imposed,
    since the probe self-bounds its own stdin head and a cap would truncate it;
    nothing larger than a single block is ever held in memory.
    """
    proc = _spawn_stdin_probe(probe)
    if proc is None:
        return []

    try:
        f = xbmcvfs.File(vfs_url)
        try:
            while True:
                block = f.readBytes(_BLOCK_BYTES)
                if not block:
                    break  # stream ended within the probe's budget
                try:
                    proc.stdin.write(block)
                except (BrokenPipeError, OSError):
                    break  # the probe took what it needs
        finally:
            f.close()
    except Exception as exc:
        _log(f"Audio: VFS read failed for {vfs_url}: {exc}", xbmc.LOGWARNING)

    return _decode_audio_tracks(_collect_probe_output(proc))


def _detect(path: str) -> list[dict]:
    """Return the source audio-track list for the given playing path.

    A real filesystem path is probed directly (fullest analysis); a Kodi VFS
    URL, which audioprobe cannot open, is streamed into it over stdin.  The full
    track list is returned so the active track can be selected -- and
    re-selected on a track change -- at read time.
    """
    probe = _audioprobe()
    if not probe or not os.path.exists(probe):
        _log(f"Audio: audioprobe binary missing ({probe})", xbmc.LOGWARNING)
        return []

    source = _resolve_disc_stream(path)
    if source.startswith("/"):
        return _run_audioprobe(probe, source)
    return _probe_stream_stdin(probe, source)


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
    """Kick off the audio-bitstream scan for the currently playing file ahead of
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
    """Collapse a codec name — audioprobe's (``"DTS-HD MA"``) or Kodi's
    (``"dtshd_ma"`` / ``"dca"``) — to a comparable family token, so the active
    Kodi stream can be matched against a probed track regardless of naming."""
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
    return token


def _current_audio_stream() -> dict:
    """Return Kodi's currently active audio stream (``index`` / ``codec`` / …)
    via JSON-RPC, or ``{}`` when nothing is playing or the query fails.  Read
    live so a track change is reflected without re-probing the file."""
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
    """Select the probed track for the audio stream Kodi is currently playing.

    Both Kodi and audioprobe enumerate the container's audio tracks in order,
    so the active stream ``index`` maps straight into the probed list; the
    codec family is cross-checked to guard against the two orderings diverging,
    falling back to a unique family match when they do.  Re-evaluated on every
    read, so switching audio track updates the values without re-probing.
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
    bitstream by audioprobe (e.g. ``"24"``), or '' while detection runs, when no
    depth is coded (lossy codecs report none) or when no track could be
    selected.  No status label."""
    track = _active_audio_track()
    if not track:
        return ""
    depth = track.get("bit_depth")
    return str(depth) if isinstance(depth, int) and not isinstance(depth, bool) else ""


def get_active_audio_sample_rate() -> str:
    """Return the sample rate in Hz of the active audio track as read from the
    source bitstream by audioprobe (e.g. ``"96000"``), or '' while detection
    runs or no track could be selected.  Unlike Kodi's own value this is the
    true source rate, so DTS 96/24 and high-rate DTS-HD read correctly instead
    of as their 48 kHz compatibility core.  No status label."""
    track = _active_audio_track()
    if not track:
        return ""
    rate = track.get("sample_rate")
    return str(rate) if isinstance(rate, int) and not isinstance(rate, bool) else ""
