# License and Credits

---

## Licensing at a glance

| Part | License | File |
|---|---|---|
| **Source code** | GNU Affero General Public License v3.0 or later | [`LICENSE`](https://github.com/CE-Repo/script.tinyppi/blob/main/LICENSE) |
| **Name, logo, artwork** | All rights reserved; limited redistribution license for unmodified releases | [`LICENSE-ASSETS`](https://github.com/CE-Repo/script.tinyppi/blob/main/LICENSE-ASSETS) |
| **Third-party attributions** | — | [`NOTICE`](https://github.com/CE-Repo/script.tinyppi/blob/main/NOTICE) |

Every source file carries an `SPDX-License-Identifier: AGPL-3.0-or-later`
header.

Versions up to and including **2.7.6** were released under the **MIT license**
and remain available under it. From 2.7.7 on, the code is AGPL.

---

## Why the AGPL

TinyPPI serves a [web dashboard](Web-Dashboard) over the network. Under the
plain GPL, someone could run a modified TinyPPI as a network service without
ever publishing their changes. Section 13 of the AGPL closes that gap: anyone
who modifies TinyPPI and lets others interact with it over a network must offer
those users the source of the modified version — the same obligation a modified
copy handed out as a file already carries.

---

## Forking

Forking the code is expressly welcome. The conditions that come with it:

1. Keep the copyright notices and the SPDX headers in the files you keep.
2. Publish the complete source of your modified version under the AGPL —
   including to anyone who reaches its web dashboard over a network.
3. State prominently that you changed the files, and when.
4. Give your fork **its own name and its own artwork** (see below).
5. Keep the `NOTICE` file with the third-party attributions.

---

## Name, logo and artwork

The AGPL covers the *code*, not the branding. The name **TinyPPI**, `icon.png`,
`fanart.png`, and the original artwork under `resources/skins/Default/media/`
(background gradients, speaker-layout graphics, splash corners, interface
elements) and `resources/web/icons/` are:

> Copyright © 2026 U3knOwn. All rights reserved.

You **may** copy, host and redistribute them as part of an **unmodified**
release of TinyPPI — for example when mirroring the add-on in a Kodi
repository.

You **may not**, without written permission, use the name TinyPPI (or a
confusingly similar one) for a modified version, fork, repository or
distribution; use the logo or artwork in a modified version; or suggest that
the copyright holder endorses your version. This is the same arrangement
Mozilla applies to Firefox: a rebuild needs its own name.

For permission beyond that, open an issue on the repository.

---

## Trademarks

The format logos under `resources/skins/Default/media/codecs/` and the Dolby
Vision marks are **not** TinyPPI's property and are not licensed by it:

- *Dolby*, *Dolby Vision*, *Dolby Digital*, *Dolby Atmos* and *TrueHD* are
  trademarks of Dolby Laboratories, Inc.
- *DTS*, *DTS-HD* and *DTS:X* are trademarks of DTS, Inc. / Xperi.
- *IMAX* and *IMAX Enhanced* are trademarks of IMAX Corporation.

They are used only to identify the audio and video format a stream carries
(nominative use). No affiliation with or endorsement by their owners is claimed.

The **rating marks** under `resources/web/ratings/` (and the same marks in the
TinyPPI app) are not TinyPPI's either:

- IMDb, TMDB, Trakt, TheTVDB, Letterboxd, Metacritic, Rotten Tomatoes (and its
  Popcornmeter) and MyAnimeList wear **those services' own logos**. No licence
  to them is held or granted; their copyright and trademarks stay with their
  owners.
- The age ratings (FSK, MPA, TV Parental Guidelines, BBFC), Metacritic's users,
  Roger Ebert, the IMDb Top 250 and the awards (Academy Awards, Golden Globes,
  BAFTAs, Primetime Emmys) are simplified marks drawn for TinyPPI; their
  lettering is Inter (SIL Open Font License 1.1) turned into outlines.

The **awards list** (`resources/data/awards.json`) is from
[TheTVDB](https://thetvdb.com), read from its API by `tools/gen_awards.py` —
or, without a key, from the awards list of TheMovieDb Helper
(plugin.video.themoviedb.helper by jurialmunkey, GPL-3.0-or-later), which is
built from TheTVDB's — and cut to the four awards shown.

All of them are used only to name the source of a rating or an age rating
(nominative use); no affiliation with or endorsement by their owners is
claimed. The full list of trademark holders is in `LICENSE-ASSETS`.

---

## Credits

TinyPPI builds on the work of these projects — many thanks to their authors
and contributors.

### script.module.sidedata

[**script.module.sidedata**](https://github.com/matthane/script.module.sidedata)
by [matthane](https://github.com/matthane) — GPL-2.0-or-later.

Parsers for the raw Dolby Vision and HDR payloads CoreELEC 22 publishes through
`Player.Process(video.sidedata)`: the Dolby Vision RPU and dvcC/dvvC
configuration record, the HDR10+ ST 2094-40 metadata and the static MDCV / CLL
SEIs. TinyPPI reads every Dolby Vision / HDR value it shows through this module,
so the overlay follows the stream frame by frame instead of probing the file.
It is a separate add-on, declared as a dependency, not bundled.

### dovi_tool / libdovi

[**dovi_tool**](https://github.com/quietvoid/dovi_tool) by quietvoid performs
the RPU parsing used by script.module.sidedata.

### FFmpeg

**libavutil** performs the HDR10+ parsing used by script.module.sidedata.

### Kodi and CoreELEC

TinyPPI is an add-on for **Kodi** (GPL-2.0-or-later) and uses its Python API
and JSON-RPC interface. It is built for **CoreELEC**, whose Amlogic integration
and side-data InfoLabel make the readings possible. The native `vs10.*` actions
TinyPPI prefers come from SamuriHL's CoreELEC Kodi work.
