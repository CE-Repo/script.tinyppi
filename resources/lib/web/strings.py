# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""The dashboard's UI strings in Kodi's current language."""

import xbmc

from core import settings

# UI string ids keyed as the page's script names them, sent with /api/hello.
# Some reuse the overlay's strings, so both name readings the same.
_UI_STRINGS = {
    "connected":     32448,
    "connecting":    32449,
    "offline":       32450,
    "idle_title":    32451,
    "idle_text":     32452,
    "peak":          32453,
    "average":       32454,
    "fps":           32140,   # FPS
    "chart":         32455,
    "active_area":   32030,   # L5 Active Area
    "vs10":          32467,
    "metadata":      32393,   # Dolby Vision metadata view
    "metadata_section": 32289,  # Metadata
    "no_metadata":      32470,
    "no_metadata_text": 32471,
    # The picture's VS10 output, not the audio sink (#32055).
    "output":        32057,   # Output (picture)
    "copy":          32456,
    "copied":        32457,
    "token_title":   32459,
    "token_text":    32460,
    "save":          32461,
    "cancel":        32462,
    "token_bad":     32463,
    "switching":     32464,
    "switched":      32465,
    "switch_failed": 32466,
    # Summary figures, history chart and transport row.
    "switches":      32478,
    "events":        32479,
    "events_empty":  32480,
    "range_1m":      32481,
    "range_10m":     32482,
    "range_all":     32483,
    "audio_track":   32484,
    "subtitles":     32485,
    "off":           32486,
    "mute":          32488,
    "playpause":     32489,
    "stop":          32490,
    "ev_mode":       32491,
    "controls":      32494,
    "metrics":       32495,
    "player_cache":  32511,
    # Shown for readings without a value, as in the overlay.
    "na":            32033,
    "warnings":        32514,
    "temperature":     32018,
    "processor":       32014,
    # Theme button and its long-press menu.
    "theme_dark":      32496,
    "theme_adaptive":  32497,
    "theme_midnight":  32498,
    "theme_menu":      32500,
    "tint_label":      32501,
    "tint_subtle":     32502,
    "tint_standard":   32503,
    "tint_strong":     32504,
    # Playback chart, the last title, and the "too many streams" reason.
    "last_played":     32507,
    "summary":         32508,
    "busy":            32509,
    # Tab bar (the shelves use "films" and "series").
    "tab_live":        32582,
    "tab_metadata":    32583,
    "tab_history":     32584,
    # Settings tab: theme, token and reports.
    "tab_settings":    32585,
    "token_enter":     32586,
    "report_live":     32587,
    # Chapter keys next to play.
    "chapter_previous": 32515,
    "chapter_next":     32516,
    # Volume steps (not a slider, so CEC can pass them to an amplifier).
    "volume_down":      32517,
    "volume_up":        32518,
    # End time under the progress bar.
    "ends_at":          32531,
    # Film library shown when idle.
    "films":            32532,
    "films_empty":      32533,
    "films_search":     32534,
    "films_starting":   32535,
    "films_failed":     32536,
    "films_resume":     32537,
    "films_watched":    32540,
    # Row of partly watched films and episodes.
    "continue":         32572,
    # Row of recently added items.
    "recent":           32588,
    # Unwatched walls and the per-title actions.
    "films_unseen":     32573,
    "series_unseen_shows": 32574,
    "mark_watched":     32575,
    "mark_unwatched":   32576,
    "mark_failed":      32577,
    "films_play":       32578,
    "series_open":      32579,
    "play_from_start":  32580,
    "resume_clear":     32581,
    # Series library, plus the episode list strings.
    "series":           32541,
    "series_empty":     32542,
    "series_search":    32543,
    "series_back":      32544,
    "series_unseen":    32545,
    "series_season":    32546,
    "series_specials":  32547,
    "series_failed":    32548,
    # Clear button in the search boxes.
    "search_clear":     32551,
    # Runtime formats.
    "runtime_hm":       32552,
    "runtime_m":        32553,
    "runtime_h":        32554,
}


def ui_strings(addon=None) -> dict[str, str]:
    """Return the UI strings localized through Kodi."""
    addon = addon or settings.addon()
    strings = {key: addon.getLocalizedString(string_id)
               for key, string_id in _UI_STRINGS.items()}
    # Yes, No and Cancel are Kodi core strings; the add-on's table would
    # return '' for them.
    strings["yes"] = xbmc.getLocalizedString(107) or "Yes"
    strings["no"] = xbmc.getLocalizedString(106) or "No"
    strings["cancel"] = xbmc.getLocalizedString(222) or "Cancel"
    return strings
