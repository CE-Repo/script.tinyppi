# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""The playing video over JSON-RPC: tracks, volume, chapters (the count for
the keys, the list for the dots on the bar), the audio and subtitle
offsets, live-TV times and the transport commands the dashboard may send."""

import json
import math
import re
from collections.abc import Callable, Mapping
from threading import Lock

import xbmc
from core.log import channel
from core.utils import cond, info
from web.payloads import Chapter, Controls, Track
from web.values import Json, Unchecked, clean_value, numbers

_log = channel("web")


# --- State -----------------------------------------------------------------

def rpc(method: str, params: Mapping[str, object] | None = None) -> Json:
    """Call Kodi's JSON-RPC and return the answer as a dict ({} on failure)."""
    request: dict[str, object] = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params:
        request["params"] = params
    try:
        answer = json.loads(xbmc.executeJSONRPC(json.dumps(request)))
    except (RuntimeError, ValueError) as exc:  # Kodi shutting down, or an answer that is no JSON
        _log(f"JSON-RPC {method} failed: {exc}")
        return {}
    return answer if isinstance(answer, dict) else {}


def video_player_id() -> int | None:
    """Return the video player id, or None when nothing plays."""
    result = rpc("Player.GetActivePlayers").get("result") or []
    for player in result:
        if isinstance(player, dict) and player.get("type") == "video":
            return player.get("playerid")
    return None


def chapter_count() -> int:
    """Return the chapter count (only available as an InfoLabel)."""
    try:
        return int(info("Player.ChapterCount") or 0)
    except ValueError:
        return 0


# --- Chapters --------------------------------------------------------------

# More than any disc carries.  A file claiming more is cut off rather than
# drawn as a bar of dots.
_CHAPTER_LIMIT = 200

# A name is a label beside the bar, not a paragraph.
_CHAPTER_NAME_LIMIT = 80

# The names a ripper or a muxer gives the chapters of a disc that names none
# (MakeMKV, mkvmerge and the like): a word for "chapter" and a number, in the
# languages such names turn up in, a bare number, or the time the chapter
# starts.  They say nothing "Chapter 6 of 13" does not already say.
_CHAPTER_WORD = (
    r"(?:chapters?|chap|ch|kapitel|kap|chapitre|cap[ií]tulo|capitolo|cap[ií]tol"
    r"|hoofdstuk|rozdzia[lł]|kapitola|kapittel|kappale|luku|глава|κεφάλαιο"
    r"|ch[uư]ơng|章节|章節|الفصل|פרק)"
    # A Roman numeral only apart from the word, or "Chill" would be one.
    r"(?:\.?\s*#?\s*\d+|(?:\.\s*|\s+)[ivxlc]+)"
)
# Hungarian and Turkish put the number first, Chinese and Japanese round it.
_CHAPTER_NUMBER_FIRST = r"\d+\.?\s*(?:fejezet|b[oö]l[uü]m)|第\s*\d+\s*[章节節話话回]"
_MADE_UP_NAME = re.compile(
    rf"{_CHAPTER_WORD}|{_CHAPTER_NUMBER_FIRST}|#?\d{{1,3}}"
    r"|\d{1,2}:\d{2}(?::\d{2})?(?:[.,]\d+)?",
    re.IGNORECASE)
# A real name behind such a number ("Chapter 6: The Hunt", "06. The Hunt"),
# which keeps only the name.  A bare number counts only with a mark after
# it, so "3 Days Later" keeps its 3, and only up to three digits, so a year
# does too.
_NUMBERED_NAME = re.compile(
    rf"(?:(?:{_CHAPTER_WORD}|{_CHAPTER_NUMBER_FIRST})(?:\s*[:.\-–—|·：]\s*|\s+)"
    r"|#?\d{1,3}\s*[:.\-–—|·：]\s*)(?P<rest>.+)",
    re.IGNORECASE)


def _whole(value: object) -> int | None:
    """Return *value* if JSON gave it as a whole number (not a boolean)."""
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _clock_like(total: int, duration: str) -> str:
    """Return *total* seconds written the way *duration* is.

    Kodi writes ``hh:mm:ss`` for a title of an hour or more and ``mm:ss``
    below, and a chapter's start reads as part of the same row.
    """
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if duration.count(":") >= 2:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{hours * 60 + minutes:02d}:{secs:02d}"


def _chapter_name(raw: object) -> str:
    """Return the name a chapter was given, or "" for one a tool made up.

    A real name behind a made-up number loses the number: the label beside
    the bar already says which chapter it is.
    """
    name = clean_value(str(raw or ""))
    # Asked of the whole name first: "6. fejezet" is made up as it stands,
    # not a "6." with a name behind it.
    numbered = None if _MADE_UP_NAME.fullmatch(name) else _NUMBERED_NAME.fullmatch(name)
    if numbered:
        name = numbered.group("rest").strip()
    return "" if _MADE_UP_NAME.fullmatch(name) else name[:_CHAPTER_NAME_LIMIT]


def _chapter_entry(entry: object, length: int, duration: str) -> Chapter | None:
    """Return one of Kodi's chapters placed on *length*, or None if malformed."""
    if not isinstance(entry, dict):
        return None
    index, start = _whole(entry.get("index")), _whole(entry.get("time"))
    if index is None or start is None or not 0 <= start <= length:
        return None
    return {
        "index": index,
        "start": start,
        "at":    round(start * 100 / length, 3),
        "time":  _clock_like(start, duration),
        "name":  _chapter_name(entry.get("name")),
    }


def _fetch_chapters(player_id: int, duration: str) -> list[Chapter]:
    """Return the chapters of *player_id*'s file, placed on *duration*."""
    length = seconds(duration)
    if not length:
        return []
    result = rpc("Player.GetChapters", {"playerid": player_id}).get("result")
    found = result.get("chapters") if isinstance(result, dict) else None
    if not isinstance(found, list):
        return []
    chapters = [chapter for entry in found[:_CHAPTER_LIMIT]
                if (chapter := _chapter_entry(entry, length, duration))]
    # One chapter is the whole file under another name: nothing to mark.
    return chapters if len(chapters) >= 2 else []


def chapter_list(duration: str) -> list[Chapter]:
    """Return the playing file's chapters, for the dots on the progress bar.

    Player.GetChapters (Kodi 22) names each chapter and says where it
    starts, in whole seconds.  The count is an InfoLabel and costs nothing,
    so JSON-RPC is only asked for a file that has chapters to give.
    """
    if chapter_count() < 2:
        return []
    player_id = video_player_id()
    if player_id is None:
        return []
    return _fetch_chapters(player_id, duration)


def current_chapter(chapters: list[Chapter], position: str) -> int:
    """Return the index of the chapter *position* is in; 0 for none.

    Worked out from the list rather than read from Player.Chapter, so the
    highlighted dot always agrees with where the dots are drawn: a jump
    lands on the whole second a chapter is listed at, which can be just
    short of where Kodi itself counts the chapter as begun.
    """
    now = seconds(position)
    if now is None:
        return 0
    current = 0
    for chapter in chapters:
        if chapter["start"] > now:
            break
        current = chapter["index"]
    return current


def _stream_label(stream: Json, fallback: str) -> str:
    """Return a track label prefixed with its upper-cased language code.

    Only a separate leading token counts as an existing prefix (``eng`` vs.
    the start of ``English``).
    """
    name = (stream.get("name") or "").strip()
    language = (stream.get("language") or "").strip()
    tag = language.upper() if re.fullmatch(r"[A-Za-z]{2,3}", language) else language
    if name and tag:
        leading_tag = re.compile(
            rf"^{re.escape(language)}(?=$|[\s·|:/-])", re.IGNORECASE
        )
        if leading_tag.search(name):
            return leading_tag.sub(tag, name, count=1)
        return f"{tag} · {name}"
    return name or tag or fallback


def _track_list(streams: list[Json] | None) -> list[Track]:
    """Return a picker's tracks as ``{index, label}``, numbered if unnamed."""
    return [{"index": stream.get("index", index),
             "label": clean_value(_stream_label(stream, f"#{index + 1}"))}
            for index, stream in enumerate(streams or [])]


def _current_index(stream: object) -> object:
    """Return the index of the current track, or -1 for none."""
    return stream.get("index", -1) if isinstance(stream, dict) else -1


def player_controls() -> Controls:
    """Return the controllable player state: tracks, volume, mute, chapters.

    Via JSON-RPC, since pickers need full lists with indices.  Only used
    when control is enabled.
    """
    state: Controls = {"audio": [], "subtitle": [], "audio_current": -1,
                   "subtitle_current": -1, "subtitle_on": False,
                   "volume": None, "muted": False, "chapters": 0,
                   "audio_delay": None, "subtitle_delay": None}

    app = rpc("Application.GetProperties",
               {"properties": ["volume", "muted"]}).get("result") or {}
    if isinstance(app, dict):
        state["volume"] = app.get("volume")
        state["muted"] = bool(app.get("muted"))

    player_id = video_player_id()
    if player_id is None:
        return state

    # Tells the page whether to show the chapter keys.
    state["chapters"] = chapter_count()
    # InfoLabels, so the fine adjustments cost no JSON-RPC.
    state["audio_delay"] = offset(info("Player.AudioDelay"))
    state["subtitle_delay"] = offset(info("Player.SubtitleDelay"))

    properties = rpc("Player.GetProperties", {
        "playerid": player_id,
        "properties": ["audiostreams", "currentaudiostream",
                       "subtitles", "currentsubtitle", "subtitleenabled"],
    }).get("result") or {}
    if not isinstance(properties, dict):
        return state

    state["audio"] = _track_list(properties.get("audiostreams"))
    state["subtitle"] = _track_list(properties.get("subtitles"))
    state["audio_current"] = _current_index(properties.get("currentaudiostream"))
    state["subtitle_current"] = _current_index(properties.get("currentsubtitle"))
    state["subtitle_on"] = bool(properties.get("subtitleenabled"))
    return state


def current_track_state() -> dict[str, str]:
    """Return identifying tokens for the active audio and subtitle streams.

    Includes the index (via JSON-RPC), since tracks may share language and
    name.
    """
    player_id = video_player_id()
    if player_id is None:
        return {"audio": "", "audio_id": "", "subtitle": ""}
    result = rpc("Player.GetProperties", {
        "playerid": player_id,
        "properties": ["currentaudiostream", "currentsubtitle",
                       "subtitleenabled"],
    }).get("result") or {}
    if not isinstance(result, dict):
        return {"audio": "", "audio_id": "", "subtitle": ""}

    def token(stream: Json) -> str:
        if not isinstance(stream, dict) or stream.get("index") is None:
            return ""
        index = int(stream.get("index", -1))
        label = clean_value(_stream_label(stream, f"#{index + 1}"))
        return f"#{index + 1} · {label}" if label != f"#{index + 1}" else label

    audio_stream = result.get("currentaudiostream") or {}
    audio = token(audio_stream)
    audio_id = (f"#{int(audio_stream.get('index', -1)) + 1}"
                if isinstance(audio_stream, dict)
                and audio_stream.get("index") is not None else "")
    subtitle = (token(result.get("currentsubtitle") or {})
                if result.get("subtitleenabled") else "__off__")
    return {"audio": audio, "audio_id": audio_id, "subtitle": subtitle}


# --- Fine adjustments ------------------------------------------------------

# Kodi moves the audio offset in steps of 25 ms within ten seconds either
# way (Player.SetAudioDelay), the subtitle offset in steps of 100 ms within
# a minute either way.  The subtitle offset has no JSON-RPC method: it is
# moved by input actions, a step each, which show Kodi's own slider on the
# TV for a moment.
_AUDIO_DELAY_STEP     = 0.025
_AUDIO_DELAY_LIMIT    = 10.0
_SUBTITLE_DELAY_STEP  = 0.1
_SUBTITLE_DELAY_LIMIT = 60.0
# The most steps one subtitle request moves: a minute's worth, from either
# end of the range back to none.  A move from one end to the other (1200
# keys, each showing Kodi's slider) stops half-way; the next tap goes on.
_SUBTITLE_DELAY_MAX_STEPS = 600
# One subtitle move at a time: each works out its steps from the offset in
# force, and two taps read at once would both step from the same offset.
_SUBTITLE_DELAY_LOCK = Lock()

# An offset as the InfoLabels write it: "-0.125 s".
_OFFSET = re.compile(r"\s*([-+]?\d+(?:\.\d+)?)\s*s?\s*")


def offset(label: str) -> float | None:
    """Return an offset InfoLabel ("-0.125 s") in seconds, or None."""
    found = _OFFSET.fullmatch(label)
    return round(float(found.group(1)), 3) if found else None


# --- Live TV ---------------------------------------------------------------

def is_live_tv() -> bool:
    """Return whether a live PVR channel (TV or radio) is playing."""
    return cond("PVR.IsPlayingTV") or cond("PVR.IsPlayingRadio")


def seconds(clock: str) -> int | None:
    """Return ``hh:mm:ss`` or ``mm:ss`` as seconds, or None."""
    try:
        parts = [int(part) for part in clock.strip().split(":")]
    except ValueError:
        return None
    if not 2 <= len(parts) <= 3:
        return None
    total = 0
    for part in parts:
        total = total * 60 + part
    return total


def broadcast_times() -> dict[str, str]:
    """Return position, length and progress of a live broadcast from the EPG.

    On live TV the player only knows the timeshift buffer.  Without EPG data
    the player's readings stay.
    """
    if not is_live_tv():
        return {}
    duration = info("PVR.EpgEventDuration(hh:mm:ss)")
    if not any(numbers(duration)):
        return {}
    elapsed = info("PVR.EpgEventElapsedTime(hh:mm:ss)")
    # Computed: PVR.EpgEventProgress is empty as a label.
    length, position = seconds(duration), seconds(elapsed)
    progress = (f"{min(100.0, max(0.0, position * 100 / length)):.1f}"
                if length and position is not None else "")
    return {
        "PlayerTime":       elapsed,
        "PlayerDuration":   duration,
        "PlayerProgress":   progress,
        "PlayerFinishTime": info("VideoPlayer.EndTime"),
        "BroadcastTimes":   "1",
    }


# --- Player commands -------------------------------------------------------

# Maximum relative seek in seconds.
_SEEK_LIMIT = 3600

# A command on the playing video: (player id, value) -> success.
_PlayerCommand = Callable[[int, Unchecked], bool]


def _number(value: Unchecked, low: float, high: float) -> float | None:
    """Return *value* as a number within [*low*, *high*], or None."""
    if isinstance(value, bool):  # JSON true/false would pass as 1/0
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or not low <= number <= high:
        return None
    return number


def _input_action(name: str) -> bool:
    """Send *name* as an input action, like a remote, and return success."""
    return rpc("Input.ExecuteAction", {"action": name}).get("result") == "OK"


def _set_volume(value: Unchecked) -> bool:
    level = _number(value, 0, 100)
    if level is None:
        return False
    return "result" in rpc("Application.SetVolume", {"volume": int(level)})


def _play_pause(player_id: int, value: Unchecked) -> bool:
    return "result" in rpc("Player.PlayPause", {"playerid": player_id})


def _stop(player_id: int, value: Unchecked) -> bool:
    return "result" in rpc("Player.Stop", {"playerid": player_id})


def _seek(player_id: int, value: Unchecked) -> bool:
    step = _number(value, -_SEEK_LIMIT, _SEEK_LIMIT)
    if step is None:
        return False
    return "result" in rpc("Player.Seek", {
        "playerid": player_id, "value": {"seconds": int(step)}})


def _seek_percent(player_id: int, value: Unchecked) -> bool:
    where = _number(value, 0, 100)
    if where is None:
        return False
    # Live TV: the bar is the broadcast (see broadcast_times) but Kodi's
    # percentage is the timeshift buffer's, so seek relatively.
    broadcast = broadcast_times()
    if broadcast:
        length = seconds(broadcast["PlayerDuration"])
        now = seconds(broadcast["PlayerTime"])
        if length is None or now is None:
            return False
        return "result" in rpc("Player.Seek", {
            "playerid": player_id,
            "value": {"seconds": int(round(length * where / 100 - now))}})
    return "result" in rpc("Player.Seek", {
        "playerid": player_id, "value": {"percentage": where}})


def _chapter(name: str) -> _PlayerCommand:
    """Return the command stepping one chapter with input action *name*."""
    def step(player_id: int, value: Unchecked) -> bool:
        # No JSON-RPC method for chapters; the input action falls back to a
        # big step without chapters, so the count is checked first.
        return chapter_count() >= 2 and _input_action(name)
    return step


def _chapter_goto(player_id: int, value: Unchecked) -> bool:
    """Jump to the start of the chapter numbered *value* (a dot on the bar).

    The number is looked up in the box's own list rather than a time taken
    from the page, and seeked to as a time rather than a percentage: a
    percentage of a two-hour film rounds to seconds either side.
    """
    number = _number(value, 1, _CHAPTER_LIMIT)
    if number is None or not number.is_integer():
        return False
    for chapter in _fetch_chapters(player_id, info("Player.Duration")):
        if chapter["index"] == int(number):
            hours, rest = divmod(chapter["start"], 3600)
            minutes, secs = divmod(rest, 60)
            return "result" in rpc("Player.Seek", {
                "playerid": player_id,
                "value": {"time": {"hours": hours, "minutes": minutes,
                                   "seconds": secs, "milliseconds": 0}}})
    return False


def _audio(player_id: int, value: Unchecked) -> bool:
    index = _number(value, 0, 64)
    if index is None:
        return False
    return "result" in rpc("Player.SetAudioStream", {
        "playerid": player_id, "stream": int(index)})


def _subtitle(player_id: int, value: Unchecked) -> bool:
    """-1 turns subtitles off, any other index selects and enables."""
    index = _number(value, -1, 64)
    if index is None:
        return False
    if index < 0:
        return "result" in rpc("Player.SetSubtitle", {
            "playerid": player_id, "subtitle": "off"})
    return "result" in rpc("Player.SetSubtitle", {
        "playerid": player_id, "subtitle": int(index), "enable": True})


def _audio_delay(player_id: int, value: Unchecked) -> bool:
    """Set the audio offset to *value* seconds (rounded to Kodi's steps)."""
    wanted = _number(value, -_AUDIO_DELAY_LIMIT, _AUDIO_DELAY_LIMIT)
    if wanted is None:
        return False
    steps = round(wanted / _AUDIO_DELAY_STEP)
    return "result" in rpc("Player.SetAudioDelay", {
        "playerid": player_id, "offset": round(steps * _AUDIO_DELAY_STEP, 3)})


def _subtitle_delay(player_id: int, value: Unchecked) -> bool:
    """Move the subtitle offset to *value* seconds, a step at a time.

    Worked out from the offset in force, which only the InfoLabel tells.
    """
    target = _number(value, -_SUBTITLE_DELAY_LIMIT, _SUBTITLE_DELAY_LIMIT)
    if target is None:
        return False
    with _SUBTITLE_DELAY_LOCK:
        current = offset(info("Player.SubtitleDelay"))
        if current is None:
            return False
        steps = round((target - current) / _SUBTITLE_DELAY_STEP)
        steps = max(-_SUBTITLE_DELAY_MAX_STEPS, min(_SUBTITLE_DELAY_MAX_STEPS, steps))
        action = "subtitledelayplus" if steps > 0 else "subtitledelayminus"
        return all(_input_action(action) for _ in range(abs(steps)))


def _subtitles(player_id: int, value: Unchecked) -> bool:
    """Show (true) or hide (false) the selected subtitle."""
    if not isinstance(value, bool):
        return False
    return "result" in rpc("Player.SetSubtitle", {
        "playerid": player_id, "subtitle": "on" if value else "off"})


# Commands that need no playing video.  Volume and mute are sent as input
# actions, like a remote, not via Application.SetVolume/SetMute (Kodi's
# software mixer).  Only the input path lets a CEC adapter forward them to
# an amplifier; without CEC they change Kodi's volume.  CEC has no absolute
# level, hence the steps, and the volume Kodi reports may then not match the
# amplifier's.  "volume" (absolute) is no longer used by the page but kept
# for older clients.
_APP_COMMANDS: dict[str, Callable[[Unchecked], bool]] = {
    "volume":      _set_volume,
    "volume_up":   lambda value: _input_action("volumeup"),
    "volume_down": lambda value: _input_action("volumedown"),
    "mute":        lambda value: _input_action("mute"),
}

# Commands on the playing video, given its player id.
_PLAYER_COMMANDS: dict[str, _PlayerCommand] = {
    "playpause":        _play_pause,
    "stop":             _stop,
    "seek":             _seek,
    "seek_percent":     _seek_percent,
    "chapter_previous": _chapter("chapterorbigstepback"),
    "chapter_next":     _chapter("chapterorbigstepforward"),
    "chapter_goto":     _chapter_goto,
    "audio":            _audio,
    "subtitle":         _subtitle,
    "subtitles":        _subtitles,
    "audio_delay":      _audio_delay,
    "subtitle_delay":   _subtitle_delay,
}


def apply_command(action: str, value: Unchecked = None) -> bool:
    """Run a transport command and return whether it succeeded.

    Requests name an action from the tables above, never a JSON-RPC method.
    JSON-RPC (not builtins) so success can be reported; False without a
    playing video.
    """
    app_command = _APP_COMMANDS.get(action)
    if app_command is not None:
        return app_command(value)
    player_command = _PLAYER_COMMANDS.get(action)
    if player_command is None:
        return False
    player_id = video_player_id()
    if player_id is None:
        return False
    return player_command(player_id, value)
