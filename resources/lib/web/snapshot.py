# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""Build the dashboard snapshot from the overlay's own readings.

``info.publish`` only calls ``setProperty`` on its window, so passing a
collector instead of an ``xbmcgui.Window`` yields exactly the overlay's
values (formatting, units, N/A labels) without duplicating the logic.

The row layout (web/rows.py) mirrors ``script-tinyppi-main.xml`` and reuses
its string ids, so translations and label changes apply to both.

The player's tracks and commands live in web/player.py, the VS10 modes in
web/vs10.py and the title's history in web/session.py.
"""

import time
import zlib

import xbmc
from core.utils import (
    PROP_EFFECTIVE_HDR_TYPE,
    PROP_HDR10PLUS_PRESENT,
    cond,
    home_window,
    info,
    localized,
    read_pass,
)
from info import dvmetadata
from info.dvinfo import (
    L1_EMPTY,
    L5_EMPTY,
    get_l1_nits,
    get_l5_offsets,
    na_label,
)
from info.properties import output_hdr_token
from info.publish import (
    publish_scene_properties,
    publish_static_properties,
)
from web.payloads import (
    Controls,
    FrameSize,
    Group,
    GroupRow,
    IdleSnapshot,
    MetadataRow,
    Metrics,
    PlayingSnapshot,
    Snapshot,
)
from web.player import broadcast_times, current_track_state, player_controls
from web.rows import GROUPS, finish_time, is_dv_source, overlay_rows, render
from web.session import SessionLog
from web.values import clean_value, numbers
from web.vs10 import vs10_state

# Home property with the source HDR type (from publish_hdr_type).
_PROP_HDR_TYPE = "TinyPPI.HdrType"


class PropertySink:
    """Stand-in for ``xbmcgui.Window`` that collects property values.

    Only the property methods ``info.publish`` uses are provided.
    """

    __slots__ = ("values",)

    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def setProperty(self, name: str, value: str) -> None:
        self.values[str(name)] = "" if value is None else str(value)

    def getProperty(self, name: str) -> str:
        return self.values.get(name, "")

    def clearProperty(self, name: str) -> None:
        self.values.pop(name, None)


# --- Readings --------------------------------------------------------------

# Readings taken directly from Kodi, under the keys the rows use.
_EXTRA_INFOLABELS = (
    ("PlayerTime",          "Player.Time"),
    ("PlayerDuration",      "Player.Duration"),
    # End time from Kodi's clock in the box's regional format; computing it
    # on the phone could disagree with the TV.
    ("PlayerFinishTime",    "Player.FinishTime"),
    ("PlayerProgress",      "Player.Progress"),
    ("PlayerCacheLevel",    "Player.CacheLevel"),
    ("VideoQueueLevel",     "Player.Process(VideoQueueLevel)"),
    ("VideoQueueDataLevel", "Player.Process(VideoQueueDataLevel)"),
    ("AudioQueueLevel",     "Player.Process(AudioQueueLevel)"),
    ("AudioQueueDataLevel", "Player.Process(AudioQueueDataLevel)"),
    ("AudioChannelsSink",   "Player.Process(audiochannelssink)"),
    ("CpuTemperature",      "System.CPUTemperature"),
    ("MemoryUsed",          "System.Memory(used.percent)"),
    ("Title",               "VideoPlayer.Title"),
    ("Filename",            "Player.Filename"),
    # Details for the now-playing card; empty for non-library files.
    ("Year",                "VideoPlayer.Year"),
    ("Genre",               "VideoPlayer.Genre"),
    ("Show",                "VideoPlayer.TVShowTitle"),
    ("Season",              "VideoPlayer.Season"),
    ("Episode",             "VideoPlayer.Episode"),
)

# Presence flags (true / false / '') as markers; the browser shows icons,
# copied reports use localized words.
_PRESENCE_GLYPH = {"true": "✔", "false": "✘"}
_PRESENCE_WORD = {
    xbmc.getLocalizedString(107): _PRESENCE_GLYPH["true"],
    xbmc.getLocalizedString(106): _PRESENCE_GLYPH["false"],
}

_PRESENCE_FLAGS = (
    ("DoviRpuPresentFlag", "DoviRpuPresentVar"),
    ("DoviBlPresentFlag",  "DoviBlPresentVar"),
    ("DoviElPresentFlag",  "DoviElPresentVar"),
)


def _first_number(value: str) -> float | None:
    found = numbers(value)
    return found[0] if found else None


def _nth(found: list[float], index: int) -> float | None:
    """Return *found*'s number at *index*, or None when it has fewer."""
    return found[index] if len(found) > index else None


def _web_presence_value(value: object) -> str:
    """Replace standalone Yes/No parts with icon markers."""
    parts = clean_value(str(value)).split(" | ")
    return " | ".join(_PRESENCE_WORD.get(part, part) for part in parts)


def _metadata_row(kind: str, name: str, value: object) -> MetadataRow:
    """Convert an ``info.dvmetadata`` row for the page (cells stay a list)."""
    if isinstance(value, (list, tuple)):
        return {"kind": kind, "name": clean_value(name),
                "cells": [_web_presence_value(cell) for cell in value]}
    return {"kind": kind, "name": clean_value(name),
            "value": _web_presence_value(value)}


# --- Output ----------------------------------------------------------------


def _output_hdr_type(mode: str, source: str) -> str:
    """Return the output as a source-style token, to detect conversions.

    Unlike ``TinyPPI.EffectiveHdrType`` (a layout choice) this is the real
    output.  An unreadable mode returns *source*, so passthrough is never
    reported as a conversion.
    """
    if not (mode or "").strip():
        return source
    token = output_hdr_token(mode)
    # The source side spells it hdr10plus (see publish_hdr_type).
    return "hdr10plus" if token == "hdr10+" else token


# --- Artwork ---------------------------------------------------------------

# InfoLabels per artwork kind, best first (episode -> show art, file ->
# Kodi's thumbnail).
_ART_LABELS = {
    "poster": ("Player.Art(poster)", "Player.Art(tvshow.poster)",
               "Player.Art(thumb)", "VideoPlayer.Cover"),
    "fanart": ("Player.Art(fanart)", "Player.Art(tvshow.fanart)",
               "VideoPlayer.Fanart"),
}


def _is_skin_texture(path: str) -> bool:
    """Return whether *path* is a skin texture name rather than artwork.

    Kodi answers ``VideoPlayer.Cover`` with ``DefaultVideoCover.png`` for
    files without art; real artwork is always a path or URL.
    """
    return "/" not in path and "\\" not in path


def art_path(kind: str) -> str:
    """Return the raw path of the playing title's artwork *kind*, or ''."""
    for label in _ART_LABELS.get(kind, ()):
        path = info(label).strip()
        if path and not _is_skin_texture(path):
            return path
    return ""


def _art_tags() -> dict[str, str]:
    """Return a short tag per artwork kind that changes with the picture.

    Used in the image URL, so a poster is fetched once per film.
    """
    tags = {}
    for kind in _ART_LABELS:
        path = art_path(kind)
        tags[kind] = f"{zlib.crc32(path.encode('utf-8', 'replace')):08x}" if path else ""
    return tags


def audio_event_label(values: dict[str, str]) -> str:
    """Return the active audio label, as in the audio card."""
    language = clean_value(values.get("AudioNameShortVar", "")).strip()
    format_parts = (
        clean_value(values.get(key, "")).strip()
        for key in ("AudioCodecVar", "AudioChannelsVar",
                    "AudioCodecSpatialVar")
    )
    audio_format = " ".join(part for part in format_parts if part)
    return " | ".join(part for part in (language, audio_format) if part)


def subtitle_event_label(values: dict[str, str]) -> str:
    """Return the active subtitle label as the card prints it.

    E.g. "DEU | Deutsch (PGS)"; Kodi's stream names are often just "FORCED".
    """
    language = clean_value(values.get("SubtitleNameShortVar", "")).strip()
    name     = clean_value(values.get("SubtitleNameVar", "")).strip()
    codec    = clean_value(values.get("SubtitleCodecVar", "")).strip()
    label = " | ".join(part for part in (language, name) if part)
    return f"{label} ({codec})".strip() if codec else label


# --- Snapshot --------------------------------------------------------------

class SnapshotBuilder:
    """Build one dashboard snapshot per call with the overlay's publishers.

    Keeps a ``published`` dict like the overlay's loop, and refreshes the
    per-title readings on a slower interval.
    """

    #: Seconds between refreshes of the static (per-title) readings.
    STATIC_INTERVAL = 1.0

    def __init__(self) -> None:
        self._sink      = PropertySink()
        self._published: dict[str, str] = {}
        self._static_at = 0.0
        self._sequence  = 0
        self._meta_static: list[dvmetadata.Row] = []
        self._meta_static_at = 0.0
        #: The playing title's history; served by /api/history.
        self.session    = SessionLog()
        # Player controls, refreshed on the static interval (JSON-RPC).
        self._controls: Controls = {}
        self._controls_at = 0.0
        self._track_state: dict[str, str] = {
            "audio": "", "audio_id": "", "subtitle": "",
        }

    def _refresh(self) -> None:
        """Recompute the readings into the sink."""
        now = time.monotonic()
        if now - self._static_at >= self.STATIC_INTERVAL:
            self._static_at = now
            publish_static_properties(self._sink, self._published)
            # Read together with the static half, so track index and label
            # come from the same moment.
            self._track_state = current_track_state()
        publish_scene_properties(self._sink, self._published)

    def _values(self) -> dict[str, str]:
        """Return the sink's values plus the direct Kodi readings."""
        values = dict(self._sink.values)
        for key, label in _EXTRA_INFOLABELS:
            values[key] = info(label)
        values.update(broadcast_times())
        values.update(overlay_rows(values))
        for flag_key, source_key in _PRESENCE_FLAGS:
            values[flag_key] = _PRESENCE_GLYPH.get(values.get(source_key, ""), "")
        return values

    @staticmethod
    def _frame() -> FrameSize | None:
        """Return the coded frame size (the L5 offsets' reference)."""
        width  = _first_number(info("Player.Process(videowidth)").replace(",", ""))
        height = _first_number(info("Player.Process(videoheight)").replace(",", ""))
        if not width or not height:
            return None
        return {"w": int(width), "h": int(height)}

    def _metrics(self, values: dict[str, str], is_dv: bool) -> Metrics:
        """Return the numeric readings the page charts.

        From the raw getters, so no localized units need parsing.  L1 and L5
        exist only in DV and are padded with zeros otherwise (see
        ``_value_or``), so they are only passed for DV and when not padding.
        """
        raw_nits = get_l1_nits()
        raw_bars = get_l5_offsets()
        nits = numbers(raw_nits) if is_dv and raw_nits != L1_EMPTY else []
        bars = numbers(raw_bars) if is_dv and raw_bars != L5_EMPTY else []
        # FpsInfoVar is "input - drop" (see core.helpers.fps_display_texts).
        fps  = numbers(values.get("FpsInfoVar", ""))
        return {
            "l1": {"min": _nth(nits, 0), "max": _nth(nits, 1), "avg": _nth(nits, 2)},
            # L5 bars (left | right | top | bottom) and the coded frame, so
            # the page can draw the letterbox.
            "bars": bars if len(bars) == 4 else None,
            "frame": self._frame(),
            "aspect":   _first_number(values.get("AspectRatioVar", "")),
            "fps_in":   _nth(fps, 0),
            "fps_drop": _nth(fps, 1),
            "fps_out":  _first_number(values.get("FpsDropVar", "")),
            "progress": _first_number(values.get("PlayerProgress", "")),
            "cpu":      _first_number(values.get("CpuUsageVar", "")),
            "cpu_temp": _first_number(values.get("CpuTemperature", "")),
            "memory":   _first_number(values.get("MemoryUsed", "")),
            "cache":    _first_number(values.get("PlayerCacheLevel", "")),
        }

    def _metadata(self, is_dv: bool, enabled: bool) -> list[MetadataRow]:
        """Return the DV metadata rows, the same list as the on-screen view.

        Scene rows every tick, static rows on the slower interval, as in
        ``ui.dvmetadata``.  Empty for non-DV sources or when disabled.
        """
        if not (is_dv and enabled):
            self._meta_static = []
            self._meta_static_at = 0.0
            return []

        scene, parsed, origin, carried = dvmetadata.build_scene_rows()
        now = time.monotonic()
        if not self._meta_static or now - self._meta_static_at >= self.STATIC_INTERVAL:
            self._meta_static_at = now
            self._meta_static = dvmetadata.build_static_rows(parsed, origin, carried)

        rows = dvmetadata.join_rows(scene, self._meta_static)
        return [_metadata_row(kind, name, value) for kind, name, value in rows]

    def _groups(self, values: dict[str, str], source: str) -> list[Group]:
        """Return the cards with their rows, grouped like the overlay.

        Empty values read N/A.  Cards without any value, or not applying to
        the source (see ``GROUPS``), are left out.  Entries sharing an id
        are merged into one card in list order.
        """
        groups: list[Group] = []
        by_id: dict[str, Group] = {}
        for group_id, title_id, rows, applies in GROUPS:
            if not applies(source):
                continue
            rendered: list[GroupRow] = []
            for label_id, segments, detail in rows:
                value = render(segments, values)
                rendered.append({
                    "id":     f"{group_id}.{label_id}",
                    "label":  localized(label_id),
                    "value":  value,
                    "detail": render(detail, values) if value else "",
                })
            if not any(row["value"] for row in rendered):
                continue
            for row in rendered:
                if not row["value"]:
                    row["value"] = na_label()
            group = by_id.get(group_id)
            if group is None:
                group = {
                    "id":    group_id,
                    "title": localized(title_id),
                    "rows":  rendered,
                }
                by_id[group_id] = group
                groups.append(group)
            else:
                group["rows"].extend(rendered)
        return groups

    def _player_controls(self, control: bool) -> Controls:
        """Return tracks and volume on the static interval, if control is on."""
        if not control:
            self._controls = {}
            self._controls_at = 0.0
            return {}
        now = time.monotonic()
        if not self._controls or now - self._controls_at >= self.STATIC_INTERVAL:
            self._controls_at = now
            self._controls = player_controls()
        return self._controls

    def _active_tracks(self) -> dict[str, str]:
        """Return the active tracks from the last static refresh."""
        return self._track_state

    def build(self, allow_filename: bool = True, metadata: bool = True,
              control: bool = False, detail: bool = True) -> Snapshot | None:
        """Build one snapshot inside a single read pass.

        One side-data parse per pass (see ``info.dvinfo``).  Without *detail*
        only the session is updated and None is returned while playing (the
        producer's idle mode).
        """
        with read_pass():
            return self._build(allow_filename, metadata, control, detail)

    def _build(self, allow_filename: bool, metadata: bool, control: bool,
               detail: bool) -> Snapshot | None:
        """Build the snapshot inside ``build``'s read pass."""
        playing = cond("Player.HasVideo")
        self._sequence += 1

        if not playing:
            # Drop the last title's values.
            self._sink   = PropertySink()
            self._published = {}
            self._static_at = 0.0
            self._meta_static = []
            self._meta_static_at = 0.0
            self._controls = {}
            self._controls_at = 0.0
            self._track_state = {
                "audio": "", "audio_id": "", "subtitle": "",
            }
            # End the session but keep its figures for the idle page.
            self.session.end()
            idle: IdleSnapshot = {
                "seq":      self._sequence,
                "playing":  False,
                "groups":   [],
                "metrics":  {},
                "metadata": [],
                "vs10":     vs10_state("", playing=False),
                "session":  self.session.summary(),
                "last":     self.session.last(),
            }
            return idle

        self._refresh()
        values = self._values()
        home   = home_window()
        source = home.getProperty(_PROP_HDR_TYPE)
        # Lower-cased once for the checks below.
        source_key = source.strip().lower()
        is_dv      = is_dv_source(source_key)

        metrics  = self._metrics(values, is_dv)
        vs10     = vs10_state(
            source_key,
            hdr10plus=home.getProperty(PROP_HDR10PLUS_PRESENT) == "1",
        )
        title    = values.get("Title", "")
        position = values.get("PlayerTime", "")

        # Update the session first, so the totals include this pass.  The
        # file name identifies the session; it is only sent if allowed.
        tracks = self._active_tracks()
        audio_identity = tracks.get("audio_id", "") or tracks.get("audio", "")
        # When off, Kodi still reports the old language, so the card label
        # is only used while subtitles are on.
        subtitle = tracks.get("subtitle", "")
        subtitle_label = (subtitle if subtitle == "__off__"
                          else subtitle_event_label(values) or subtitle)
        self.session.observe(
            title,
            values.get("Filename", ""),
            metrics,
            {"vs10": vs10.get("output", ""),
             "mode": values.get("DisplayModeVar", ""),
             "audio": {"id": audio_identity,
                       "label": audio_event_label(values)
                                or tracks.get("audio", "")},
             "subtitle": {"id": subtitle, "label": subtitle_label}},
            position,
        )
        if not detail:
            return None

        snapshot: PlayingSnapshot = {
            "seq":       self._sequence,
            "playing":   True,
            "paused":    cond("Player.Paused"),
            "title":     title,
            # Respects the overlay's file-name setting.
            "filename":  values.get("Filename", "") if allow_filename else "",
            "hdr_type":  source,
            "effective": home.getProperty(PROP_EFFECTIVE_HDR_TYPE),
            # The real output, for the conversion badge (see
            # _output_hdr_type).
            "output_type": _output_hdr_type(vs10.get("output", ""), source),
            "time":      position,
            "duration":  values.get("PlayerDuration", ""),
            "finish":    finish_time(values),
            "metrics":   metrics,
            "groups":    self._groups(values, source_key),
            "metadata":  self._metadata(is_dv, metadata),
            "vs10":      vs10,
            "art":       _art_tags(),
            "media":     {
                "year":    values.get("Year", ""),
                "genre":   values.get("Genre", ""),
                "show":    values.get("Show", ""),
                "season":  values.get("Season", ""),
                "episode": values.get("Episode", ""),
            },
            "controls":  self._player_controls(control),
            "session":   self.session.summary(),
        }
        return snapshot


