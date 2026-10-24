# FAQ

### What does "PPI" stand for?

*Player Process Info* — Kodi's own name for its playback information overlay
(the `Player process info` entry of the video OSD). TinyPPI is a compact,
richer replacement for it.

### Does TinyPPI work on LibreELEC, Android, Windows or a PC?

No. It requires **CoreELEC 22 or later** on **Amlogic** hardware: the
readings come from the Amlogic driver and from the side-data InfoLabel only
CoreELEC 22 publishes. On anything else the add-on refuses to open its views.

### Does it work with CoreELEC 21 (Omega)?

No. CoreELEC 22 introduced `Player.Process(video.sidedata)`, which every
Dolby Vision and HDR reading depends on. Versions before 22 are rejected.

### Does TinyPPI slow down playback?

It is designed not to. The overlay reads each value once per 100 ms refresh and
only writes window properties that changed; side data is parsed only when it
changes; per-title facts are read once a second. The service starts its heavy
work five seconds after Kodi so it does not compete with start-up. The web
dashboard builds nothing while no page is connected.

### Why does my skin reload once after installing or switching skins?

TinyPPI registers two font sizes in the skin's `Font.xml` and asks Kodi to
reload the skin so they take effect. It happens once per skin (and again after
a skin update replaces `Font.xml`).

### Can I use it with a 720p skin?

No. The overlay is laid out for 1080i; skins with a `720p` folder are refused.

### Which key should I use?

Anything free during fullscreen playback. A color button on the remote is a
good choice. Use `NotifyAll(script.tinyppi,open_overlay)` for the fastest
response — see [Launching and Keymaps](Launching-and-Keymaps).

### Can I open the overlay and the VS10 dialog from different keys?

Yes. Map one key to `NotifyAll(script.tinyppi,open_overlay)` and another to
`NotifyAll(script.tinyppi,open_dialog)` (or `RunScript(script.tinyppi,dialog)`).
**Launch mode** only affects `RunAddon(script.tinyppi)`.

### Why does the aspect ratio differ from what Kodi shows?

Kodi reports the coded frame (a letterboxed 2.39:1 film in a 16:9 frame reads
1.78). For Dolby Vision, TinyPPI uses the RPU's L5 active area to compute the
ratio of the *visible* picture. Without L5 data it shows Kodi's value.

### Why does a profile 7 FEL disc show profile 7 although CoreELEC converts it?

The side data is captured before CoreELEC's own conversion, so TinyPPI shows
the stream as the file carries it. The `converted` flag in the metadata view's
**Stream** section tells you a conversion happened.

### Why is the "Bit depth" 12-bit for FEL?

A full enhancement layer reconstructs a 12-bit picture. MEL and single-layer
profiles are 10-bit, SDR 8-bit.

### What is the difference between FEL and MEL?

Both are Dolby Vision enhancement layers on profile 7 discs. A **FEL** (full
enhancement layer) carries real picture data that extends the base layer to 12
bit; a **MEL** (minimal enhancement layer) carries next to nothing. TinyPPI
colors the tag green (FEL) or orange (MEL) by default.

### Why are there no VS10 modes for HDR10+ or HLG?

The VS10 engine does not accept them as inputs; the driver has no mode group
for either. The same applies to Dolby Vision titles that also carry HDR10+
metadata. See [VS10 Output Modes](VS10-Output-Modes#which-modes-are-offered).

### Why does switching HDR10 → Dolby Vision briefly go to SDR?

The driver cannot switch directly between those outputs. TinyPPI performs two
complete switches through SDR, as you would by hand.

### Does the web dashboard need internet access?

No. Everything — the page, its icons and the posters — is served by the add-on from the
box. Posters come from Kodi's own texture cache. Only the overview's ratings
reach out, from the box: the IMDb Top 250 list (a public MDBList list, the
same for everyone), if you enter an MDBList API key, MDBList's ratings for
the playing film and WhatsOn's Rotten Tomatoes certificates, and its ratings
where they are missing (unless you turn that off). Without internet the card shows the library's ratings.

### Can I open the dashboard from outside my home?

Not directly, and you should not forward its port. Use a VPN into your home
network. Under a non-home host name the dashboard asks for the token even for
reading.

### Can several people use the dashboard at once?

Yes — up to six live pages. All of them are fed by one snapshot builder, so
five open tabs cost the box the same as one.

### Does the dashboard change anything on my TV picture?

Not by reading. Only the controls (VS10 switching, remote, playback, watched
marks) act on the box, and all of them need the token.

### Where can I report wrong IMAX entries or add titles?

Add your own to `addon_data/script.tinyppi/imax_titles.txt`; propose general
additions as an issue or pull request. See [IMAX Detection](IMAX-Detection).

### In which languages is TinyPPI available?

English, German, Arabic, Hungarian and Simplified Chinese. The dashboard uses
the same strings. Want to add one? See [Translations](Translations).

### Can I fork TinyPPI?

Yes — the code is AGPL-3.0-or-later. A fork needs its own name and artwork,
because the TinyPPI name, logo and artwork are not covered by the code license.
See [License and Credits](License-and-Credits).
