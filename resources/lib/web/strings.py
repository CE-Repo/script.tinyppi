# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""The dashboard's own chrome, in whatever language Kodi is set to."""

import xbmc

from core import settings

# The page's own chrome, keyed the way its script names them.  Sent with
# /api/hello so the dashboard speaks whatever language Kodi is set to, the
# same as the row labels that travel with each snapshot.  Four of them are
# the overlay's own strings rather than new ones, so the two always agree on
# what a reading is called.
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
    # The VS10 output the picture leaves on, not the audio row's sink,
    # which keeps #32055: one string cannot be translated for both.
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
    # The summary figures, history chart and transport row.
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
    # What a reading with no value shows, as the overlay's own rows do.
    "na":            32033,
    "warnings":        32514,
    "temperature":     32018,
    "processor":       32014,
    # The theme button and the menu behind a long press on it.
    "theme_dark":      32496,
    "theme_adaptive":  32497,
    "theme_midnight":  32498,
    "theme_menu":      32500,
    "tint_label":      32501,
    "tint_subtle":     32502,
    "tint_standard":   32503,
    "tint_strong":     32504,
    # The playback chart, the title that has just ended, and the one thing a
    # stream can be refused for that is worth naming.
    "last_played":     32507,
    "summary":         32508,
    "busy":            32509,
    # The tab bar.  The two shelves are named by "films" and "series".
    "tab_live":        32582,
    "tab_metadata":    32583,
    "tab_history":     32584,
    # The settings tab: the theme, the token and the reports that used to sit
    # behind the key in the top bar.
    "tab_settings":    32585,
    "token_enter":     32586,
    "report_live":     32587,
    # The two keys either side of play, on a file that has chapters.
    "chapter_previous": 32515,
    "chapter_next":     32516,
    # The volume, which steps rather than slides so that a box passing volume
    # over CEC can send the steps on to an amplifier.
    "volume_down":      32517,
    "volume_up":        32518,
    # The wall clock under the middle of the progress bar, between how far the
    # title has got and how long it runs for.
    "ends_at":          32531,
    # The film library the idle page offers instead of an empty screen.
    "films":            32532,
    "films_empty":      32533,
    "films_search":     32534,
    "films_starting":   32535,
    "films_failed":     32536,
    "films_resume":     32537,
    "films_watched":    32540,
    # The row of films and episodes left half-watched, above both shelves.
    "continue":         32572,
    # The row of what arrived in the library last, under it.
    "recent":           32588,
    # The walls of what is still unwatched, under the walls of everything, and
    # the question a press on a title asks.
    "films_unseen":     32573,
    "series_unseen_shows": 32574,
    "mark_watched":     32575,
    "mark_unwatched":   32576,
    "mark_failed":      32577,
    "films_play":       32578,
    "series_open":      32579,
    "play_from_start":  32580,
    "resume_clear":     32581,
    # And the series library beside it: the same shelf with one floor more,
    # so the same strings again plus the few an episode list needs.
    "series":           32541,
    "series_empty":     32542,
    "series_search":    32543,
    "series_back":      32544,
    "series_unseen":    32545,
    "series_season":    32546,
    "series_specials":  32547,
    "series_failed":    32548,
    # The cross inside either search box.
    "search_clear":     32551,
    # How long something runs: the two halves of it, and the minutes alone for
    # anything short of an hour.
    "runtime_hm":       32552,
    "runtime_m":        32553,
    "runtime_h":        32554,
}


def ui_strings(addon=None) -> dict[str, str]:
    """The page's chrome, localized through Kodi's own string table."""
    addon = addon or settings.addon()
    strings = {key: addon.getLocalizedString(string_id)
               for key, string_id in _UI_STRINGS.items()}
    # Yes and No are Kodi core strings, not entries in this add-on's table.
    # Asking Addon.getLocalizedString for 106/107 returns an empty string and
    # would erase the report values when the hello response reaches the page.
    strings["yes"] = xbmc.getLocalizedString(107) or "Yes"
    strings["no"] = xbmc.getLocalizedString(106) or "No"
    strings["cancel"] = xbmc.getLocalizedString(222) or "Cancel"
    return strings
