# Translations

TinyPPI's settings, overlay labels, notifications and the web dashboard are
translated through Kodi's standard `strings.po` files.

---

## Available languages

| Language | Folder |
|---|---|
| English (source) | `resources/language/resource.language.en_gb/` |
| German | `resources/language/resource.language.de_de/` |
| Arabic | `resources/language/resource.language.ar_sa/` |
| Hungarian | `resources/language/resource.language.hu_hu/` |
| Simplified Chinese | `resources/language/resource.language.zh_cn/` |

Kodi picks the file matching **Settings → Interface → Regional → Language**,
falling back to English for anything missing. The dashboard receives its UI
strings from the box in the same language (via `/api/hello`), so a phone always
shows the language Kodi is set to, not the phone's own.

The add-on's summary and description in `addon.xml` are translated separately,
with one `<summary lang="…">` and `<description lang="…">` per language.

---

## The string files

Each file holds **366 strings**:

```po
msgctxt "#32000"
msgid "General"
msgstr "Allgemein"
```

- `msgid` is the English source text — identical in every file.
- `msgstr` is the translation; empty in `en_gb`.
- The files are maintained with POEditor (`X-Generator: POEditor.com`).

Some strings are not translated on purpose:

- format names in the VS10 dialog (*SDR → HDR10*, *Dolby Vision (Original)*),
- technical values (`HDR10`, `DV`, `CMv4.0`, codec names),
- Kodi's own strings, which TinyPPI reuses where they exist — for example
  *Player process info* (`$LOCALIZE[10116]`) and Yes/No.

Placeholders such as `%s` (in *Season %s* or *%s h %s min*) must stay in the
translation.

The color names in the color picker are not in the string files either. They
are numbered English names (*Red*, *Red 1*, *Soft red* …); only the seven
colors the settings start out on — *White*, *Light blue*, *Charcoal*,
*Black*, *Crimson*, *Tangerine* and *Forest* — are translated (see
[Colors and Themes](Colors-and-Themes#color-names)).

---

## How the IDs are arranged

The IDs are grouped by where a string is used. Every area has a block of its
own, and each block starts on a multiple of ten with **at least 50 free IDs**
in front of the next one, so a new string can join its area without the other
strings being renumbered. Every category of the settings dialog counts as an
area of its own.

| Block | Area | In use | Free |
|---|---|---|---|
| 32000 – 32089 | Settings: **General** | 32000 – 32030 (31) | 59 |
| 32090 – 32189 | Settings: **TinyPPI overlay** | 32090 – 32135 (46) | 54 |
| 32190 – 32269 | Settings: **DV metadata** | 32190 – 32210 (21) | 59 |
| 32270 – 32369 | Settings: **Codec logos** | 32270 – 32315 (46) | 54 |
| 32370 – 32439 | Settings: **VS10 dialog** | 32370 – 32389 (20) | 50 |
| 32440 – 32509 | Settings: **Channels** | 32440 – 32454 (15) | 55 |
| 32510 – 32589 | Settings: **Dashboard**, with the *Show address and token* dialog | 32510 – 32533 (24) | 56 |
| 32590 – 32659 | **Color picker**: *(Default)*, the HEX tile and its messages, the translated color names | 32590 – 32601 (12) | 58 |
| 32660 – 32769 | **TinyPPI overlay**: start-up messages and every label of the overlay | 32660 – 32716 (57) | 53 |
| 32770 – 32829 | **Dolby Vision metadata view** | 32770 – 32771 (2) | 58 |
| 32830 – 32999 | **Web dashboard** | 32830 – 32921 (92) | 78 |

Within a block the strings follow the order in which they are used: the
settings as the settings dialog lists them, the overlay labels from top to
bottom, the dashboard's in the order of its string table. A string used in several places sits in the block where it appears
first — the dashboard, for example, reuses the overlay's labels for its
readings. Everything stays within **32000 – 32999**, the range Kodi reserves
for scripts.

---

## Improving a translation

1. Open the file of your language and find the string by its English `msgid`.
2. Change its `msgstr`.
3. Test it: copy the file into
   `/storage/.kodi/addons/script.tinyppi/resources/language/…/strings.po` on
   your box and restart Kodi. Use the file of the TinyPPI version installed on
   the box — a file from another version may number its strings differently
   (see [How the IDs are arranged](#how-the-ids-are-arranged)).
4. Open a pull request (or an issue with the corrected lines).

Keep translations short: the overlay's labels sit in a fixed-width column, and
the settings' help texts are shown in a small box.

---

## Adding a new language

1. Copy `resource.language.en_gb/strings.po` to a new folder named after Kodi's
   language code, e.g. `resource.language.fr_fr/strings.po`.
2. Set `"Language: fr\n"` in the header.
3. Fill in every `msgstr`.
4. Add `<summary lang="fr">` and `<description lang="fr">` to `addon.xml`.
5. Add the language to `LANGUAGES` in `tests/unit/test_settings_definition.py`.
   The test then checks that every setting label and help text exists and is
   translated in the new file.
6. Run `python3 -m pytest tests` and open a pull request.

---

## Adding a string (developers)

New user-visible text gets the **next free ID in the block of its area** (see
[How the IDs are arranged](#how-the-ids-are-arranged)) and goes into
**all five** files at once, sorted by ID — the English text as `msgid`
everywhere, translations as far as possible. Never squeeze a string into
another area's block: if a block runs full, or a new settings category needs
a block of its own, the blocks behind it are moved in one go, as in the
regrouping after 2.14.2. Settings strings without a translation fail
`test_settings_definition.py`. In Python, read strings with the add-on's
`localized(<id>)` helper; in skin files use `$ADDON[script.tinyppi <id>]`;
for the dashboard, add the ID to `_UI_STRINGS` in
`resources/lib/web/strings.py`.
