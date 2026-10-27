# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 U3knOwn

"""The dashboard's UI strings in Kodi's current language."""

import xbmc
import xbmcaddon
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
    # Chapter dots on the progress bar, and the switch for them.
    "chapter":          32366,
    "chapter_of":       32367,
    "progress_bar":     32368,
    "chapter_marks":    32369,
    # What a screen reader calls the overview card's row of ratings.
    "ratings":          32383,
    # The overview card under what is playing: its title, and what its
    # rating marks say to a screen reader.
    "plot":             32370,
    "plot_episode":     32434,
    "my_rating":        32372,
    "top250":           32373,
    # What an award's shield says it won or was nominated for, in figures.
    "award_won":        32389,
    "award_nominated":  32390,
    # And what its credits are called.
    "director":         32386,
    "cast":             32378,
    # The remote's fine adjustments.
    "audio_offset":     32391,
    "subtitle_offset":  32392,
    "offset_reset":     32394,
    # Sorting and filtering the shelves.
    "sort":             32395,
    "sort_title":       32396,
    "sort_year":        32397,
    "sort_rating":      32398,
    "sort_added":       32399,
    "sort_runtime":     32400,
    "sort_ascending":   32413,
    "sort_descending":  32414,
    "filter_genre":     32401,
    "filter_video":     32402,
    "filter_resolution": 32403,
    "filter_audio":     32404,
    "filter_empty":     32412,
    # The next-up row and a title's details.
    "next_up":          32405,
    "details":          32406,
    "writer":           32407,
    "studio":           32408,
    "details_failed":   32409,
    "genre":            32410,
    "close":            32411,
    # Arranging the cards on a tab, and the tabs on the bar.
    "cards_edit":       32415,
    "cards_edit_hint":  32416,
    "cards_done":       32417,
    "cards_reset":      32418,
    "cards_move_up":    32419,
    "cards_move_down":  32420,
    "cards_hide":       32421,
    "cards_show":       32422,
    "cards_hidden":     32423,
    "cards_all_hidden": 32424,
    "settings_tabs":    32425,
    "settings_tabs_desc": 32426,
    "settings_cards":   32427,
    "settings_cards_desc": 32428,
    "settings_cards_reset": 32429,
    "settings_cards_reset_desc": 32430,
    # The way from an episode to its show, and the remote's card.
    "go_to_show":       32431,
    "player":           32432,
    # How many episodes the open show has, under its name.
    "series_episodes":  32433,
}


def ui_strings(addon: xbmcaddon.Addon | None = None) -> dict[str, str]:
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
