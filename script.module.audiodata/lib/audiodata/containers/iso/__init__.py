"""ISO disc-image probing: locate the main feature and read its audio.

Blu-ray (BDMV): walk the UDF filesystem to ``BDMV/PLAYLIST``, rank the
playlists by deduped duration, pick the winner's largest clip and read that
``BDMV/STREAM/*.m2ts`` as a transport stream.  DVD-Video: walk the ISO9660
bridge to ``VIDEO_TS``, pick the title set with the most VOB bytes and read its
first ``VTS_tt_1.VOB`` as a program stream.

Both run against the image by absolute byte range, reusing the TS and PS
backends on the located clip.
"""

from .. import mpegps, mpegts
from .image import Image
from . import iso9660, mpls, udf

__all__ = ["looks_like_iso", "probe", "Image"]

# Playlists are KiB-scale; cap the read so a corrupt file entry cannot gather
# megabytes per playlist.
_MPLS_READ_CAP = 4 << 20
# Two playlists within this many seconds are a duration tie, broken by bytes.
_DURATION_TIE_SECS = 1.0


def looks_like_iso(image) -> bool:
    """Whether an image is any ISO we can read (UDF or ISO9660)."""
    return udf.is_udf_iso(image) or iso9660.looks_like_iso9660(image)


def probe(source, file_len: int, scan_limit: int, deep: bool = True):
    """Read a disc image and return the Report of its main feature."""
    image = source if isinstance(source, Image) else Image(source, file_len)

    # Blu-ray first: a UDF volume with a BDMV directory.  DVDs are UDF too but
    # without BDMV, so a missing-BDMV UDF volume falls through to the DVD path.
    if udf.is_udf_iso(image):
        try:
            volume = udf.UdfVolume.open(image)
            entries = volume.read_dir(volume.root())
            has_bdmv = any(e.is_dir and e.name.upper() == "BDMV" for e in entries)
        except udf.UdfError:
            volume, entries, has_bdmv = None, None, False
        if has_bdmv:
            return _probe_bluray(image, volume, entries, scan_limit)

    if iso9660.looks_like_iso9660(image):
        return _probe_dvd(image, scan_limit)

    raise ValueError("ISO image is neither a Blu-ray (BDMV) nor a "
                     "DVD-Video (VIDEO_TS) volume")


# --- Blu-ray (BDMV over UDF) -----------------------------------------------

def _find(entries, name: str):
    for entry in entries:
        if entry.name.upper() == name.upper():
            return entry
    return None


def _probe_bluray(image, volume, entries, scan_limit: int):
    has_aacs = _find(entries, "AACS") is not None
    bdmv = _find(entries, "BDMV")
    if bdmv is None or not bdmv.is_dir:
        raise ValueError("no BDMV directory")
    bdmv_entries = volume.read_dir(bdmv)

    playlist_dir = _find(bdmv_entries, "PLAYLIST")
    stream_dir = _find(bdmv_entries, "STREAM")
    if playlist_dir is None or not playlist_dir.is_dir:
        raise ValueError("no BDMV/PLAYLIST directory")
    if stream_dir is None or not stream_dir.is_dir:
        raise ValueError("no BDMV/STREAM directory")

    # Clip id ("00055") -> (entry, size) from BDMV/STREAM.
    clips = {}
    for entry in volume.read_dir(stream_dir):
        if entry.is_dir:
            continue
        clip_id = _clip_id_of(entry.name)
        if clip_id is None:
            continue
        try:
            clips[clip_id] = (entry, volume.info_len(entry))
        except udf.UdfError:
            continue
    clip_sizes = {clip_id: size for clip_id, (_entry, size) in clips.items()}

    # Parse every playlist; they are tiny, and malformed ones are skipped.
    candidates = []
    playlists = sorted((e for e in volume.read_dir(playlist_dir)
                        if not e.is_dir and _has_ext(e.name, ".mpls")),
                       key=lambda e: e.name)
    for entry in playlists:
        try:
            playlist = mpls.parse(volume.read_small(entry, _MPLS_READ_CAP))
        except (udf.UdfError, mpls.MplsError):
            continue
        if playlist.items:
            candidates.append((entry.name, playlist))

    name, clip_id = _select_main(candidates, clip_sizes)
    clip_entry = clips[clip_id][0]
    extents = volume.extents(clip_entry)
    span = _coalesce(extents)
    if span is None:
        raise ValueError("main-feature m2ts is fragmented inside the ISO; "
                         "not supported")
    clip_start, clip_len = span
    if image.size and clip_start + clip_len > image.size:
        raise ValueError("main-feature m2ts extends past the end of the image "
                         "(truncated ISO?)")

    try:
        report = mpegts.probe(image.range_reader(clip_start, clip_len), scan_limit)
    except ValueError as exc:
        if has_aacs:
            raise ValueError(
                f"clip {clip_entry.name} is not readable ({exc}); "
                "AACS-encrypted? probe a decrypted backup") from None
        raise ValueError(f"main-feature clip {clip_entry.name}: {exc}") from None
    report.container = f"Blu-ray ISO (BDMV, {clip_entry.name} via {name})"
    return report


def _select_main(candidates, clip_sizes):
    """The main-title heuristic.

    Longest deduped duration wins; ties within ``_DURATION_TIE_SECS`` are
    broken by total referenced clip bytes, then by the lowest playlist name.
    Playlists referencing clips absent from STREAM are dropped (robustness and
    decoy filtering), and identical PlayItem sequences collapse to the
    lowest-numbered playlist.  The probe clip is the winner's largest
    referenced clip.
    """
    kept = []
    seen_sequences = []
    for name, playlist in sorted(candidates, key=lambda c: c[0]):
        if any(item.clip_id not in clip_sizes for item in playlist.items):
            continue
        sequence = playlist.item_keys()
        if sequence in seen_sequences:
            continue
        seen_sequences.append(sequence)
        kept.append((name, playlist))

    best = None
    for name, playlist in kept:
        duration = playlist.duration_secs_deduped()
        total_bytes = sum(clip_sizes[c] for c in playlist.distinct_clips())
        if best is None:
            wins = True
        else:
            _bn, _bp, best_duration, best_bytes = best
            if abs(duration - best_duration) > _DURATION_TIE_SECS:
                wins = duration > best_duration
            else:
                # Equal falls through: kept is name-sorted, so the first wins.
                wins = total_bytes > best_bytes
        if wins:
            best = (name, playlist, duration, total_bytes)

    if best is None:
        raise ValueError("no usable playlist in BDMV/PLAYLIST")

    name, playlist = best[0], best[1]
    distinct = playlist.distinct_clips()
    pick = max(distinct, key=lambda clip_id: clip_sizes[clip_id])
    return name, pick


def _coalesce(extents):
    """One contiguous ``(start, len)`` from file-ordered extents, or None.

    UDF caps a single extent near 1 GiB, so a feature-length clip is many
    exactly-adjacent extents; a genuinely scattered file stays None.
    """
    if not extents:
        return None
    start, first_len = extents[0]
    end = start + first_len
    for offset, length in extents[1:]:
        if offset != end:
            return None
        end += length
    return (start, end - start) if end > start else None


def _clip_id_of(name: str):
    """``"00055.m2ts"`` -> ``"00055"``; None for non-m2ts names."""
    return name[:-5].upper() if _has_ext(name, ".m2ts") else None


def _has_ext(name: str, ext: str) -> bool:
    return len(name) > len(ext) and name[-len(ext):].lower() == ext.lower()


# --- DVD-Video (VIDEO_TS over ISO9660) --------------------------------------

def _probe_dvd(image, scan_limit: int):
    volume = iso9660.Iso9660.open(image)
    entries = volume.read_dir(volume.root())
    video_ts = next((e for e in entries
                     if e.is_dir and e.name.upper() == "VIDEO_TS"), None)
    if video_ts is None:
        raise ValueError("no VIDEO_TS directory (not a DVD-Video ISO)")

    selected = _select_dvd_vob(volume.read_dir(video_ts))
    if selected is None:
        raise ValueError("no VOB files in VIDEO_TS")
    vob, title = selected

    if image.size and vob.offset + vob.size > image.size:
        raise ValueError("main-feature VOB extends past the end of the image "
                         "(truncated ISO?)")
    try:
        report = mpegps.probe(image.range_reader(vob.offset, vob.size), scan_limit)
    except ValueError as exc:
        raise ValueError(f"main-feature VOB {vob.name}: {exc}") from None
    report.container = f"DVD-Video ISO ({title}, {vob.name})"
    return report


def _select_dvd_vob(files):
    """The DVD main title set: the ``VTS_tt`` group with the most VOB bytes
    across its parts 1..9 (menu part 0 and VIDEO_TS.VOB excluded), returning
    its first part ``VTS_tt_1.VOB``.  Falls back to the single largest VOB if
    no title set has a part 1."""
    totals = {}
    part1 = {}
    for f in files:
        if f.is_dir:
            continue
        parsed = _parse_vts(f.name)
        if parsed is None:
            continue
        title_set, part = parsed
        if 1 <= part <= 9:
            totals[title_set] = totals.get(title_set, 0) + f.size
            if part == 1:
                part1[title_set] = f

    usable = [(t, b) for t, b in totals.items() if t in part1]
    if usable:
        # Most bytes, ties broken by the lowest set number.
        best = max(usable, key=lambda item: (item[1], [-ord(c) for c in item[0]]))
        return part1[best[0]], f"VTS_{best[0]}"

    vobs = [f for f in files if not f.is_dir and _has_ext(f.name, ".vob")]
    if not vobs:
        return None
    return max(vobs, key=lambda f: f.size), "title"


def _parse_vts(name: str):
    """``"VTS_01_1.VOB"`` -> ``("01", 1)``; None for the menu or a non-VTS name."""
    upper = name.upper()
    if not upper.endswith(".VOB"):
        return None
    parts = upper[:-4].split("_")
    if len(parts) < 3 or parts[0] != "VTS":
        return None
    try:
        return parts[1], int(parts[2])
    except ValueError:
        return None
