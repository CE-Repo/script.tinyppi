# IMAX Detection

TinyPPI marks films whose home release carries **IMAX** material at an
expanded aspect ratio. The mark appears as:

- the detail `(IMAX)` or `(IMAX Enhanced)` on the overlay's **Aspect ratio** row,
- the combined **IMAX logo** in place of the plain HDR10 / HDR10+ / Dolby Vision
  logo in the [codec logos](Codec-Logos),
- an IMAX badge on the [web dashboard](Web-Dashboard).

The mark describes the **film**, not the current frame, so it stays for the
whole runtime.

---

## Why by name and not by picture

IMAX is not an aspect ratio. 1.78:1 is IMAX framing in *The Dark Knight* but
ordinary framing in a TV production, and no single frame can tell them apart.
TinyPPI therefore identifies the **film**, by one of:

1. **A release name containing `IMAX`.** A file or folder called
   `Dune.Part.Two.2024.IMAX.2160p…` is recognised without being listed.
   A name containing **IMAX Enhanced** is recognised as IMAX Enhanced.
2. **An entry in the title list** shipped with the add-on
   (`resources/data/imax_titles.txt`) or in **your own list** (see below).

A film that cannot be identified is never marked — guessing from the picture
would mark every 1.78:1 film.

---

## Where names are looked for

- the playing file's name,
- its folder (rip tags are sometimes only on the folder),
- for a disc image, the image itself or the folder holding it (what plays is a
  stream inside the mounted disc),
- Kodi's **title**, **original title** and **year** for the item — so a film
  streamed through an add-on, whose URL says nothing, is found through its
  library entry.

---

## How matching works

Each name is normalised before matching:

- case, punctuation and accents are ignored,
- `&` reads as `and`,
- roman numerals and number words read as figures, so *The Wandering Earth II*
  matches `The.Wandering.Earth.2`,
- German umlauts count as spelled out, so *Drachenzähmen* matches
  `Drachenzaehmen`.

The name is then **cut where it stops naming the film** and starts describing
the file — at the first year, resolution or release tag (`2160p`, `UHD`,
`BluRay`, `x265`, `German`, `Remux`, `DV`, `Atmos` …).

A listed title has to match **the end of what remains**:

- `The Dark Knight` matches `The.Dark.Knight.2008.2160p.UHD.BluRay`.
- `Aquaman` does **not** match `Aquaman.and.the.Lost.Kingdom.2023…` — the
  sequel needs (and has) its own entry.

A **year** written on an entry has to match the item's year too, which keeps
remakes apart: `Ghostbusters 2016` never marks the 1984 film.

---

## Adding your own titles

Do not edit the bundled list — it is replaced by every update. Create your own
file instead; it is read **in addition** to the bundled one and survives
updates:

```
/storage/.kodi/userdata/addon_data/script.tinyppi/imax_titles.txt
```

Format — one title per line, anything after `#` is a comment:

```text
# My additions
Oppenheimer                            # Expanded IMAX sequences
Top Gun Maverick
Eternals @enhanced                     # Disney+ IMAX Enhanced only
Ghostbusters 2016                      # year separates the remake
```

- Keep entries as **short as they can be while staying unambiguous**.
- Add a **year** only to separate a remake from its original — once written,
  it must match the item's year.
- Write **`@enhanced`** after the title (before any comment) for a release
  with the **IMAX Enhanced** certification; the badge then reads
  *IMAX Enhanced* instead of *IMAX*.

Changes are picked up the next time a title starts.

---

## The bundled list

The bundled list is a starting point, not a complete catalogue. Whether a given
disc actually switches aspect ratio varies between releases and territories,
so entries are verified before they are added — a wrong entry makes the badge
appear on a film that never opens up. Entries carry comments such as
*"US Blu-ray; UHD and some regional BDs are fixed"* where it depends on the
edition.

Missing a title you have verified? Open an issue or a pull request against
`resources/data/imax_titles.txt` with the release it applies to.
