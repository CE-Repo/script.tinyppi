# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""The dashboard's UI strings in Kodi's current language."""

import xbmc

from core import settings

# UI string ids keyed as the page's script names them, sent with /api/hello.
# Some reuse the overlay's strings, so both name readings the same.
_UI_STRINGS = {
    "connected":     32274,
    "connecting":    32275,
    "offline":       32276,
    "idle_title":    32277,
    "idle_text":     32278,
    "peak":          32279,
    "average":       32280,
    "fps":           32055,   # FPS
    "chart":         32281,
    "active_area":   32271,   # L5 Active Area
    "vs10":          32282,
    "metadata":      32080,   # Dolby Vision metadata view
    "metadata_section": 32264,  # Metadata
    "no_metadata":      32283,
    "no_metadata_text": 32284,
    # The picture's VS10 output, not the audio sink (#32241).
    "output":        32285,   # Output (picture)
    "copy":          32286,
    "copied":        32287,
    "token_title":   32288,
    "token_text":    32289,
    "save":          32290,
    "cancel":        32291,
    "token_bad":     32292,
    "switching":     32293,
    "switched":      32294,
    "switch_failed": 32295,
    # Summary figures, history chart and transport row.
    "switches":      32296,
    "events":        32297,
    "events_empty":  32298,
    "range_1m":      32299,
    "range_10m":     32300,
    "range_all":     32301,
    "audio_track":   32302,
    "subtitles":     32303,
    "off":           32304,
    "mute":          32305,
    "playpause":     32306,
    "stop":          32307,
    "ev_mode":       32308,
    "controls":      32309,
    "metrics":       32310,
    "player_cache":  32311,
    # Shown for readings without a value, as in the overlay.
    "na":            32230,
    "warnings":        32312,
    "temperature":     32250,
    "processor":       32249,
    # Theme button and its long-press menu.
    "theme_dark":      32313,
    "theme_adaptive":  32314,
    "theme_midnight":  32315,
    "theme_menu":      32316,
    "tint_label":      32317,
    "tint_subtle":     32318,
    "tint_standard":   32319,
    "tint_strong":     32320,
    # Playback chart, the last title, and the "too many streams" reason.
    "last_played":     32321,
    "summary":         32322,
    "busy":            32323,
    # Tab bar (the shelves use "films" and "series").
    "tab_live":        32324,
    "tab_metadata":    32325,
    "tab_history":     32326,
    # Settings tab: theme, token and reports.
    "tab_settings":    32327,
    "token_enter":     32328,
    "report_live":     32329,
    # Chapter keys next to play.
    "chapter_previous": 32330,
    "chapter_next":     32331,
    # Volume steps (not a slider, so CEC can pass them to an amplifier).
    "volume_down":      32332,
    "volume_up":        32333,
    # End time under the progress bar.
    "ends_at":          32334,
    # Film library shown when idle.
    "films":            32335,
    "films_empty":      32336,
    "films_search":     32337,
    "films_starting":   32338,
    "films_failed":     32339,
    "films_resume":     32340,
    "films_watched":    32341,
    # Row of partly watched films and episodes.
    "continue":         32342,
    # Row of recently added items.
    "recent":           32343,
    # Unwatched walls and the per-title actions.
    "films_unseen":     32344,
    "series_unseen_shows": 32345,
    "mark_watched":     32346,
    "mark_unwatched":   32347,
    "mark_failed":      32348,
    "films_play":       32349,
    "series_open":      32350,
    "play_from_start":  32351,
    "resume_clear":     32352,
    # Series library, plus the episode list strings.
    "series":           32353,
    "series_empty":     32354,
    "series_search":    32355,
    "series_back":      32356,
    "series_unseen":    32357,
    "series_season":    32358,
    "series_specials":  32359,
    "series_failed":    32360,
    # Clear button in the search boxes.
    "search_clear":     32361,
    # Runtime formats.
    "runtime_hm":       32362,
    "runtime_m":        32363,
    "runtime_h":        32364,
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
