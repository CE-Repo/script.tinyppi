# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""The playing video over JSON-RPC: tracks, volume, chapters, live-TV times
and the transport commands the dashboard may send."""

import json
import math
import re
from collections.abc import Callable, Mapping

import xbmc
from core.log import channel
from core.utils import cond, info
from web.payloads import Controls, Track
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
                   "volume": None, "muted": False, "chapters": 0}

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
    "audio":            _audio,
    "subtitle":         _subtitle,
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
