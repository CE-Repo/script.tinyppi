"""Client for the borderprobe helper binary.

borderprobe measures the black bars in the picture by decoding the frame at a
given playback position, which replaces the ``/dev/amvideocap0`` capture this
module's caller used to depend on: that node exists on Amlogic and nowhere
else, so the measurement could not be developed, tested or reproduced anywhere
but on the box itself.

The process is held open for as long as a file is playing.  Opening a container
and probing its streams costs far more than decoding one frame does -- on a
file across the network it is nearly all of the time -- so a process launched
per poll would pay it sixty times a minute.  Held open, a poll is a seek, a
decode and a line of text.  See ``docs/PROTOCOL.md`` in the borderprobe repo.

## Serving Kodi's own filesystem

Kodi plays from ``nfs://``, ``smb://``, ``bluray://`` and friends, which a
standalone binary cannot open -- the same problem dvinfo.py solves for hdrprobe
by piping the file in on stdin.  That trick does not transfer here, because
borderprobe seeks to an arbitrary position on every poll and a pipe only goes
forwards.

So the flow is inverted: borderprobe asks, and this module answers out of an
``xbmcvfs.File`` handle, which speaks every protocol Kodi does with Kodi's own
credentials and mounts.  Each request names its own absolute offset, so there
is no shared cursor to keep in step and a seek on the far side costs no round
trip at all.

The consequence for this code is that a command's answer is not the next thing
to arrive on the pipe: a ``READ`` can come first, and more than one.  Every
exchange therefore runs through :meth:`_Probe._exchange`, which serves requests
until a real reply shows up.  Answering out of order, or reading the pipe
anywhere else, deadlocks both sides.
"""

import os
import queue
import subprocess
import threading

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


def _log(msg: str, level: int = xbmc.LOGDEBUG) -> None:
    xbmc.log(f"TinyPPI: {msg}", level)


class BorderProbeError(Exception):
    """The helper could not be started, or stopped answering."""


def binary_path() -> str:
    """Return the borderprobe path from tools.tinyppi, restoring the exec bit.

    Mirrors dvinfo.py's ``_hdrprobe``: the binaries live in the companion addon
    so a TinyPPI update does not have to carry them, and an addon install can
    drop the executable bit.

    The binary is called ``borderprobe`` on every platform, Windows included:
    it is spawned from a full path rather than typed at a prompt, and Windows
    runs a PE from a full path whatever it is called.  One name means there is
    no platform branch here to get wrong -- an earlier version looked for
    ``borderprobe.exe`` beside a file called ``borderprobe`` and reported the
    binary as missing, which reads as a packaging fault rather than a naming
    one.
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

    ``translatePath`` resolves Kodi's own ``special://`` scheme and leaves
    everything else alone, so the existence check is what actually decides:
    a path the OS can open goes straight to libavformat, and anything else --
    every network protocol, every Blu-ray structure -- goes over the bridge.
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
        self._lines: queue.Queue = queue.Queue()
        # Why the last NONE was returned ("too-dark", say).  Kept so the caller
        # can say what the helper is doing, rather than only that it is quiet.
        self.last_none_reason = ""

        flags = 0
        if os.name == "nt":  # keep a console window from flashing up on dev boxes
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        try:
            self._proc = subprocess.Popen(
                [binary, "--server"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                bufsize=0,
                creationflags=flags,
            )
        except OSError as exc:
            raise BorderProbeError(f"cannot start borderprobe: {exc}") from exc

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
        """Size of the open VFS handle, or -1 when it cannot be determined.

        -1 is honest rather than fatal: libavformat copes with an unknown size
        on a seekable stream, it just probes more conservatively.
        """
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

    def _write(self, data: bytes) -> None:
        try:
            self._proc.stdin.write(data)
            self._proc.stdin.flush()
        except (OSError, ValueError) as exc:
            raise BorderProbeError(f"borderprobe stdin closed: {exc}") from exc

    def _pump(self) -> None:
        """Feed stdout lines to _readline until the helper closes it."""
        try:
            for raw in iter(self._proc.stdout.readline, b""):
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
        if self._vfs is not None:
            try:
                self._vfs.seek(offset, 0)
                data = bytes(self._vfs.readBytes(length))
            except Exception as exc:
                # A short read is end of file; a failed one is not, but both
                # leave us with nothing to send.  Zero bytes is the protocol's
                # end-of-file answer and stops the helper cleanly either way.
                _log(f"borderprobe: read at {offset} failed: {exc}")
                data = b""

        self._write(b"DATA %d\n" % len(data) + data)

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
            for stream in (self._proc.stdin, self._proc.stdout):
                try:
                    stream.close()
                except Exception:
                    pass
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
