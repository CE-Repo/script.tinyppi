"""Client for the borderprobe helper binary.

borderprobe measures the black bars in the picture by decoding the frame at a
given playback position, replacing the ``/dev/amvideocap0`` capture this
module's caller used to depend on -- a node that exists only on Amlogic, so
that measurement could never be developed or tested off the box.

The process is held open for as long as a file is playing, since opening a
container and probing its streams costs far more than decoding one frame (on
a networked file, nearly all of it); a held-open process turns a poll into a
seek, a decode and a line of text.  See ``docs/PROTOCOL.md`` in the
borderprobe repo.

Kodi plays from ``nfs://``, ``smb://``, ``bluray://`` and friends, which a
standalone binary cannot open -- and unlike dvinfo.py's stdin trick for
hdrprobe, piping doesn't work here because borderprobe seeks to an arbitrary
position on every poll.  So the flow is inverted: borderprobe asks, and this
module answers out of an ``xbmcvfs.File`` handle that speaks every protocol
Kodi does. Each request names its own absolute offset, so there's no shared
cursor and a far-side seek costs no round trip.

The consequence is that a command's answer isn't necessarily the next thing on
the pipe -- a ``READ`` (or several) can come first.  Every exchange therefore
runs through :meth:`_Probe._exchange`, which serves requests until a real
reply shows up; answering out of order, or reading the pipe anywhere else,
deadlocks both sides.
"""

import io
import os
import queue
import subprocess
import threading
import time

import xbmc
import xbmcaddon
import xbmcvfs

# Read requests are not bounded to borderprobe's typical buffer size: probing a
# file that is not fast-start (the moov atom sits at the end, not the front)
# can legitimately ask for a multi-megabyte chunk to pull the whole index in
# one go, and that is seen in practice well north of 1 MiB.  The cap exists
# only to stop a corrupted length field from being used to size an allocation,
# so it is set far above any real request rather than at a guessed buffer size.
_MAX_READ = 32 << 20

# A command must not block the sampler thread forever if the helper wedges.
# Generous, because the first OPEN on a cold remote file genuinely can take a
# second or two while libavformat pulls the index.
_TIMEOUT_SECONDS = 20.0

# Options the server is started with.
#
# --threads 1 is what makes the load measurable, which is what makes it
# controllable.  FFmpeg's default is a decoder thread per core, so a query
# briefly took the whole box and its wall time said nothing about what it had
# cost.  On one thread the wall time of a query is very nearly its CPU time, and
# cropdetect times every query and paces itself by the result (see _MAX_DUTY
# there) -- so the helper is held to a known share of one core instead of an
# assumed share of an unknown number of them.  Nothing waits on a query, so the
# longer each one now takes costs nobody anything.
#
# --frames 2 rather than the helper's default of three, for the same reason it
# was chosen before: it keeps a frame-level cross-check against a single odd
# decode while measurably cutting what a query costs -- and under a duty cycle a
# cheaper query is not just cheaper, it is one the sampler can afford to make
# more often.
#
# --accurate is deliberately not used.  It would drop the keyframe lag by
# decoding forward to the exact position, but it costs about three times a
# plain query, which buys less than it spends on the Amlogic boxes this runs on.
#
# --recycle-decoder is deliberately not used either.  It would cut the helper
# from roughly 190 MB resident to 12 MB on 4K HEVC, but at about twice the CPU
# per query, which is the one thing this configuration is trying not to spend.
# cropdetect bounds the memory by closing the helper once nothing has read a
# value for a while instead -- see _KEEPALIVE_TIMEOUT there.
_PROBE_OPTIONS = ("--threads", "1", "--frames", "2")


def _log(msg: str, level: int = xbmc.LOGDEBUG) -> None:
    xbmc.log(f"TinyPPI: {msg}", level)


class BorderProbeError(Exception):
    """The helper could not be started, or stopped answering."""


def binary_path() -> str:
    """Return the borderprobe path from tools.tinyppi, restoring the exec bit.

    Mirrors dvinfo.py's ``_hdrprobe``: the binaries live in the companion addon
    so a TinyPPI update needn't carry them, and an install can drop the exec
    bit.  Called ``borderprobe`` on every platform including Windows, since
    it's spawned from a full path -- one name means no platform branch to get
    wrong.
    """
    try:
        base = xbmcaddon.Addon("tools.tinyppi").getAddonInfo("path")
    except Exception:
        _log("borderprobe: tools.tinyppi is not installed", xbmc.LOGWARNING)
        return ""

    path = os.path.join(base, "tools", "borderprobe", "borderprobe")
    if not os.path.exists(path):
        # Name what was looked for, so the log says which file to put where
        # rather than only that one is absent.
        _log(f"borderprobe: no binary at {path}", xbmc.LOGWARNING)
        return ""

    if not os.access(path, os.X_OK):
        try:
            os.chmod(path, 0o755)
        except OSError:
            pass
    return path


def _local_path(source: str) -> str:
    """Return a real filesystem path for *source*, or '' when there is none.

    ``translatePath`` resolves Kodi's ``special://`` scheme and leaves
    everything else alone, so the existence check decides: a path the OS can
    open goes straight to libavformat, everything else goes over the bridge.
    """
    try:
        translated = xbmcvfs.translatePath(source)
    except Exception:
        translated = source
    try:
        return translated if translated and os.path.exists(translated) else ""
    except OSError:
        return ""


class _Probe:
    """One helper process bound to one file."""

    def __init__(self, binary: str, source: str):
        self._vfs = None
        self._proc = None
        self._stdout = None
        self._lines: queue.Queue = queue.Queue()
        # Why the last NONE was returned ("too-dark", say).  Kept so the caller
        # can say what the helper is doing, rather than only that it is quiet.
        self.last_none_reason = ""

        # Running totals, for the caller to difference across one query.  What
        # they are for: a query's wall time says the feature is expensive, but
        # not where the expense is.  These separate the two candidates -- bytes
        # hauled out of Kodi's VFS on our thread, against everything the helper
        # does on its own -- which on a file over a share are not remotely the
        # same size, and are not fixed by the same thing.
        self.reads_served = 0
        self.bytes_served = 0
        self.vfs_seconds = 0.0

        flags = 0
        if os.name == "nt":  # keep a console window from flashing up on dev boxes
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        try:
            self._proc = subprocess.Popen(
                [binary, "--server", *_PROBE_OPTIONS],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                bufsize=0,
                creationflags=flags,
            )
        except OSError as exc:
            raise BorderProbeError(f"cannot start borderprobe: {exc}") from exc

        # bufsize=0 above is for stdin, where a buffer would sit between us and
        # a helper waiting on a reply.  stdout must not inherit it: a raw stream
        # has no readline of its own, so the generic one falls back to reading a
        # single byte per syscall, and every "READ <offset> <length>" the helper
        # sends -- hundreds of them for one query on a network file -- was being
        # picked up a character at a time.  A buffer in front of it makes that
        # one read.
        self._stdout = io.BufferedReader(self._proc.stdout)

        # stdout carries nothing but text lines -- the binary payload travels
        # the other way, on stdin -- so it can safely be pumped into a queue.
        # That is what puts a clock on _readline: a blocking readline() cannot
        # be interrupted, so a wedged helper would otherwise hang the sampler
        # thread for the rest of playback with nothing said in the log.
        threading.Thread(target=self._pump, daemon=True).start()

        local = _local_path(source)
        if local:
            reply = self._exchange(f"OPEN {local}")
        else:
            self._vfs = xbmcvfs.File(source)
            size = self._file_size()
            reply = self._exchange(f"OPENIO {size} {source}")

        if reply != "OK":
            self.close()
            raise BorderProbeError(reply or "borderprobe did not answer OPEN")

    # -- wire ------------------------------------------------------------- #

    def _file_size(self) -> int:
        """Size of the open VFS handle, or -1 when unknown (libavformat copes
        with an unknown size on a seekable stream; it just probes more
        conservatively)."""
        try:
            return int(self._vfs.size())
        except Exception:
            pass
        try:
            self._vfs.seek(0, 2)
            size = int(self._vfs.seek(0, 1))
            self._vfs.seek(0, 0)
            return size
        except Exception:
            return -1

    def _write(self, data) -> None:
        """Write one buffer to the helper's stdin.  Takes any bytes-like object
        so a VFS read can go out unconverted; the pipe is blocking, so a write
        transfers in full."""
        try:
            self._proc.stdin.write(data)
            self._proc.stdin.flush()
        except (OSError, ValueError) as exc:
            raise BorderProbeError(f"borderprobe stdin closed: {exc}") from exc

    def _pump(self) -> None:
        """Feed stdout lines to _readline until the helper closes it."""
        try:
            for raw in iter(self._stdout.readline, b""):
                self._lines.put(raw)
        except (OSError, ValueError):
            pass  # the pipe went away; the None below says so
        finally:
            self._lines.put(None)

    def _readline(self) -> str:
        try:
            raw = self._lines.get(timeout=_TIMEOUT_SECONDS)
        except queue.Empty:
            raise BorderProbeError(
                f"no reply within {_TIMEOUT_SECONDS:.0f}s"
            ) from None
        if raw is None:
            raise BorderProbeError("borderprobe exited")
        return raw.decode("utf-8", "replace").strip()

    def _serve_read(self, request: str) -> None:
        """Answer a ``READ <offset> <length>`` out of the VFS handle."""
        try:
            _, offset, length = request.split()
            offset, length = int(offset), int(length)
        except ValueError:
            raise BorderProbeError(f"malformed request: {request}")

        if length < 0 or length > _MAX_READ:
            raise BorderProbeError(f"refusing a {length}-byte read")

        data = b""
        started = time.monotonic()
        if self._vfs is not None:
            try:
                self._vfs.seek(offset, 0)
                # Left as whatever readBytes hands back (a bytearray) and
                # written straight out.  A query pulls a couple of megabytes
                # through here several times a minute, and every conversion on
                # the way is a full copy of that made under the GIL, in the same
                # interpreter the overlay's own polling loop runs in.
                data = self._vfs.readBytes(length)
            except Exception as exc:
                # A short read is end of file; a failed one is not, but both
                # leave us with nothing to send.  Zero bytes is the protocol's
                # end-of-file answer and stops the helper cleanly either way.
                _log(f"borderprobe: read at {offset} failed: {exc}")
                data = b""

        self.vfs_seconds += time.monotonic() - started
        self.reads_served += 1
        self.bytes_served += len(data)

        # Header and payload go out as two writes rather than one concatenated
        # buffer, for the same reason: joining them would copy the payload
        # again.  The pipe is blocking, so each write transfers in full.
        self._write(b"DATA %d\n" % len(data))
        if data:
            self._write(data)

    def _exchange(self, command: str) -> str:
        """Send a command and return its reply, serving reads along the way."""
        self._write(command.encode("utf-8") + b"\n")
        while True:
            line = self._readline()
            if line.startswith("READ "):
                self._serve_read(line)
                continue
            return line

    # -- api -------------------------------------------------------------- #

    def measure(self, seconds: float):
        """Return ``(left, right, top, bottom)`` in coded pixels, or None.

        None means the helper had nothing to report for this position -- a fade
        to black, a shot too dark to judge -- which is a reason to keep the
        previous value, not to withdraw it.
        """
        reply = self._exchange(f"AT {seconds:.3f}")

        if reply.startswith("BARS "):
            try:
                return tuple(int(part) for part in reply.split()[1:5])
            except ValueError:
                raise BorderProbeError(f"malformed reply: {reply}")

        if reply.startswith("NONE"):
            self.last_none_reason = reply[4:].strip() or "no reason given"
            return None

        raise BorderProbeError(reply or "borderprobe stopped answering")

    def close(self) -> None:
        if self._proc is not None:
            try:
                self._proc.stdin.write(b"QUIT\n")
                self._proc.stdin.flush()
                self._proc.wait(timeout=2)
            except Exception:
                try:
                    self._proc.kill()
                    self._proc.wait(timeout=2)
                except Exception:
                    pass
            for stream in (self._proc.stdin, self._stdout, self._proc.stdout):
                if stream is None:
                    continue
                try:
                    stream.close()
                except Exception:
                    pass
            self._stdout = None
            self._proc = None

        if self._vfs is not None:
            try:
                self._vfs.close()
            except Exception:
                pass
            self._vfs = None


def open_probe(source: str):
    """Start a helper for *source*, or return None when one cannot be had."""
    binary = binary_path()
    if not binary:
        return None   # binary_path has already said what it looked for

    try:
        return _Probe(binary, source)
    except BorderProbeError as exc:
        _log(f"borderprobe: {exc} (binary: {binary})", xbmc.LOGWARNING)
        return None
