# Web Dashboard

TinyPPI can serve everything the overlay shows to a **browser on your phone,
tablet or laptop**, so the readings can be followed while the picture on the
TV stays untouched. On top of the readings the dashboard has a live luminance
chart, an event history, a remote, VS10 switching, and the film and series
library with continue watching.

The page is served entirely by the add-on: nothing is loaded from the
internet, and it works on a box without any outside connection. Only the
overview's ratings reach out, from the box rather than the browser: the IMDb
Top 250 place, and — when you give it a key — the ratings MDBList gathers (see
[The IMDb Top 250](#the-imdb-top-250) and
[Ratings from MDBList](#ratings-from-mdblist)).

---

## Contents

- [Switching it on](#switching-it-on)
- [The tabs](#the-tabs)
- [Live](#live)
- [Overview](#overview)
- [The IMDb Top 250](#the-imdb-top-250)
- [Ratings from MDBList](#ratings-from-mdblist)
- [Rotten Tomatoes from WhatsOn](#rotten-tomatoes-from-whatson)
- [Metadata](#metadata)
- [History](#history)
- [Films](#films)
- [Series](#series)
- [Continue watching and recently added](#continue-watching-and-recently-added)
- [Play, resume and watched marks](#play-resume-and-watched-marks)
- [The remote](#the-remote)
- [Chapters on the progress bar](#chapters-on-the-progress-bar)
- [Switching VS10 from the browser](#switching-vs10-from-the-browser)
- [Settings tab](#settings-tab)
- [Themes](#themes)
- [Layout on phones and desktops](#layout-on-phones-and-desktops)
- [What it costs the box](#what-it-costs-the-box)
- [Dashboard settings](#dashboard-settings)

---

## Switching it on

1. **Settings → Dashboard → Enable web dashboard** (off by default).
2. **Settings → Dashboard → Show address and token** shows the address to open
   and the access token — handy when you are standing in front of the TV with
   the phone in your hand.
3. Open the address on any device on the **same network**:

   ```
   http://<box-ip>:8099/
   ```

The port is set under **Settings → Dashboard → Port** (1024–65535, default
**8099**). Leave 8080 alone; Kodi's own web server usually has it.

> **Do not forward the dashboard's port to the internet.** It is meant for a
> home network. See [Dashboard Security](Dashboard-Security).

The server listens on **IPv4 and IPv6**. Reading without the token works for
devices on the home network only; anything else is asked for the token.

On a phone the page can be **added to the home screen**; it then opens like an
app, with the status bar in the theme's color.

The row labels come from Kodi's own string table, so the dashboard speaks the
same language as the overlay.

---

## The tabs

The page has six tabs, switched from a floating bar of icons at the foot of
the screen:

| Tab | Address | What is on it | Shown |
|---|---|---|---|
| **Live** | `/#live` | Now playing, the overview (slogan, plot, director, cast, ratings), transport controls, VS10 output and every reading of the overlay | always |
| **Metadata** | `/#metadata` | Active picture area, L1 luminance chart, the full Dolby Vision metadata list | only while a Dolby Vision title plays (and **Show the Dolby Vision metadata view** is on) |
| **Films** | `/#films` | Continue watching (films), recently added, unwatched films, the whole film library | when the film library is offered |
| **Series** | `/#series` | Continue watching (episodes), recently updated series, series with unwatched episodes, the whole series library | when the series library is offered |
| **History** | `/#history` | Metrics, chart and events of the playing title — or, for ten minutes after the credits, of the one that just ended | always |
| **Settings** | `/#settings` | Theme, access token, the progress bar's chapter dots, copy report | always |

- The address remembers the tab, so a bookmark or a reload comes back to it,
  and each device reopens the tab it was left on.
- A page that is on the Metadata tab when the Dolby Vision title ends goes back
  to Live.
- The tab bar shows icons only; each key names its tab on hover and to screen
  readers. Like the TinyPPI app's bar, it steps out of the way after three
  seconds without interaction and returns with the next touch, scroll, key or
  pointer movement.
- The top bar carries the name, the version and the **connection light**
  (*Connected*, *Connecting…*, *Disconnected*).
- `http://<box-ip>:8099/metadata` — the address of the old stand-alone
  metadata page — still works and lands on the Metadata tab.

---

## Live

**Now playing** — the poster, title, year and genre (its first two), the
studio (only the first), the file name (only when the overlay's **Show file
name** is on), elapsed time, progress and the time the title **ends at**.

**Overview** — what the title is about, who made it and how it is rated (see
[below](#overview)).

**Format badges** — the same badges the TinyPPI app draws under the title:

- a picture row: resolution, HDR format with the Dolby Vision profile and
  layer, a conversion such as `DV → HDR10`, IMAX;
- a sound row: codec, Atmos or DTS:X, channel layout.

**VS10 output** — the current output and the modes that can be switched to
(see [below](#switching-vs10-from-the-browser)).

**Every row of the overlay**, grouped as on screen: Video, Processing, Audio,
HDR static metadata, Dolby Vision, Metadata and System. A reading that just
moved is highlighted the same way the overlay highlights it.

**The remote** sits on this tab too (see [below](#the-remote)).

With nothing playing the tab says *"Nothing is playing — Start a video on the
box and everything it carries appears here."*

What a source cannot carry is left out rather than shown empty: the peak and
average tiles, the luminance chart, the active-area box and both metadata
sections come from the Dolby Vision RPU and appear only for Dolby Vision; the
HDR static metadata group is left out for SDR. That is the same rule the
overlay follows.

---

## Overview

A card under *Now playing*, everything in it centred:

- **Slogan and plot** — the slogan (where the library has one; most episodes
  have none) right over the plot, so the two read as one text, the slogan set
  upright and bold like a heading.
- **Director** and **Cast** — each a bold heading over the names: every
  director, and the cast's first **20** in billing order, ending in "…" where
  there are more. An episode's cast is its own guests and then the show's.
- **Ratings** — under a heading of their own, a row of small shields: first
  the age rating (FSK, MPA, TV Parental Guidelines, BBFC as a mark on the
  level's colour; any other written out), then a score for each source — IMDb,
  TMDB, Trakt, TheTVDB, Letterboxd, Metacritic and its users, Rotten Tomatoes
  and its Popcornmeter, Roger Ebert (*RE*), MyAnimeList, or the first letter of
  any other — then your own rating behind a heart and the place in the IMDb
  Top 250 (*250* | *#17*). How many voted is not shown.

**Folded from the start.** The card opens folded: the plot cut to **five
lines**, the director, the cast and the ratings hidden under it. A click or
tap on the text (or Enter / Space once it has the focus) lets all of it out,
and another folds it again. Only a plot that fits its five lines with nothing
under it has nothing to fold. Every new title starts folded again.

**Which board is an age rating?** An episode carries its show's age rating.
One that names neither its country nor its board ("Rated 12", which the TMDb
scraper writes with its default prefix) is read as the one board that gives
that level — "PG-13" is American, "15" British — and where more than one does
("12", "18", "PG") as the board of the country Kodi's language points to:
German, British English or American English. The credits and the ratings are
what Kodi knows of whatever plays, so an add-on's stream that names them has
them too.

**Which service is a mark?** A tap or click on a shield shows its name over it
for two seconds (*IMDb*, *Trakt*, *FSK*, *IMDb Top 250* …); a mouse pointer
shows the same as a tooltip. A tap on a shield does not fold the card. A
screen reader hears each shield in full (*"IMDb 8.5"*).

The services' marks are their own logos, the age ratings, Metacritic's users,
Roger Ebert and the Top 250 simplified marks drawn for TinyPPI (see
[License and Credits](License-and-Credits)). The ratings are read from the
library once per title, and only while a page is open. Without a plot, the
card shows the credits and the ratings alone; with none of them it is left
out, as it is for a file that is not in the library. The card folds away from
its heading like the others and remembers it.

---

## The IMDb Top 250

Scrapers seldom write a film's place in the IMDb Top 250 any more, and one
they did write is stale the day after. So the box reads the place from a
public MDBList list that follows IMDb's chart — **no key needed**. It is
fetched when a film first plays with a page open, then at most twice a day
(ten minutes later when it could not be had). The list is the same 250 films
for everyone, so fetching it tells nothing of what you watch. A film is looked
up by the IMDb id the library holds; one in the chart shows its place, one that
is not shows none. Until the list is in, and for a film without an IMDb id,
the library's own place stands. Episodes have none.

---

## Ratings from MDBList

Kodi's library holds only the ratings its scraper wrote — with the TMDb
scraper often TMDb's alone. [MDBList](https://mdblist.com) gathers what a film
was given by IMDb, TMDb, Trakt, Letterboxd, Rotten Tomatoes (critics and
Popcornmeter), Metacritic (critics and users), Roger Ebert and MyAnimeList.

1. Sign in at mdblist.com and take the free API key under **Preferences → API**.
2. Enter it under **Settings → Dashboard → Ratings → MDBList API key**.

From then on — the film already playing included — the box asks MDBList once per film — by the IMDb id the
library holds, else the TMDb one — and the card shows the library's ratings
until the answer is in. Where both have a rating from one source, MDBList's is
shown; any other the library holds stands beside them. Every rating is out of
ten: a score out of 100 a tenth of it, Roger Ebert's four stars ten. An answer
is kept for half a day.

The library's ratings are shown alone without a key, for a film MDBList does
not know or cannot be reached for (asked again ten minutes later), when
MDBList refuses the key (Kodi's log says so, and the key is not sent again
until it is changed) or while the day's limit is spent. Episodes always show
the library's: MDBList rates shows, not episodes.

**A rating missing?** Kodi's log has a line for every film MDBList is asked
for — `TinyPPI [web]: MDBList rated imdb tt0816692: imdb, tmdb, tomatoes, …` —
naming the houses it rated the film by and, after *no rating from*, those it
listed without one. A film MDBList could not be asked for, or answered with an
error, is logged as a warning.

---

## Rotten Tomatoes from WhatsOn

Rotten Tomatoes certifies some films: **Certified Fresh** for its critics'
Tomatometer, **Verified Hot** for its audience's Popcornmeter. Neither the
library nor MDBList says so, but
[WhatsOn](https://github.com/pierrevano/whatson-api) — a free service for
non-commercial use — does, **no key needed**. A certified rating's shield
wears a small red seal with a tick on the corner of its mark, and its tooltip
and what a screen reader hears name the certificate ("Rotten Tomatoes ·
Certified Fresh 9.3").

WhatsOn also fills in what MDBList lacks: it has no Rotten Tomatoes rating
for some films that Rotten Tomatoes does rate (The Matrix and Interstellar
among them). Where neither MDBList nor the library has the Tomatometer or the
Popcornmeter for a film, WhatsOn's is shown; one they have stands.

It is on by default: **Settings → Dashboard → Ratings → Rotten Tomatoes from
WhatsOn**. The box asks WhatsOn for a film (episodes never) once MDBList has
answered or will not be asked, by the IMDb id the library holds, else the TMDb
one, and keeps the answer — a film WhatsOn does not know included — for half a
day. One question per film stays well inside what WhatsOn allows without a key
(40 an hour, 200 a day); should the limit be spent all the same, the box waits
as long as WhatsOn says. WhatsOn runs on a free host that sleeps when idle, so
its first answer can take up to a minute; the card shows the ratings it has
meanwhile.

Kodi's log has a line for every film WhatsOn is asked for —
`TinyPPI [web]: WhatsOn rated imdb tt0133093: tomatoes (certified), popcorn` —
or says it does not know the film, could not be reached or answered with an
error.

---

## Metadata

Only while a Dolby Vision title plays.

- **Active picture area** — the L5 active area the RPU declares, drawn to scale
  inside the coded frame: the letterbox as the stream describes it, changing
  with the scene on an IMAX Enhanced title.
- **Frame luminance (L1)** — the peak and frame average on a logarithmic scale,
  over the last **1 min**, the last **10 min** or the **whole title**. The
  add-on samples from the start of playback, so a page opened halfway through
  a film gets the part it missed instead of starting from empty.
- **The Dolby Vision metadata list** — the same list as the on-screen
  [metadata view](Dolby-Vision-Metadata-View): configuration record, the RPU
  from its header through L255, the composer's reshaping curves, the trim
  passes and the static SEIs. It stays live, highlights changed readings, and
  flows into two or three columns on a wide screen without breaking a section
  across columns.

The list is the largest thing the dashboard sends. It can be switched off
under **Settings → Dashboard → Show the Dolby Vision metadata view** — the
first thing to turn off on a slow network.

---

## History

The figures of the playing title:

- **Metrics** — player cache, current frame rate, warning count, and how often
  the output or a playback track was switched.
- **Luminance chart** (Dolby Vision) — as on the Metadata tab.
- **Events** — a timestamped list of what is worth knowing about. A long list
  scrolls inside its card.

| Event | Recorded when |
|---|---|
| VS10 output | the output is switched to or from Dolby Vision (counts as a *switch*) |
| Display mode | the HDMI display mode changes (*switch*) |
| Audio track | the selected audio track changes (*switch*) |
| Subtitle | the selected subtitle changes (*switch*) |
| Frame rate | the input frame rate changes |
| Temperature | the CPU reaches 75 °C (*warning*) |
| Processor | the CPU reaches full load (*warning*) |

The history keeps one sample per second for the chart (up to the last hour)
and the last 60 events. Track changes are recorded only once they have been
stable for 1.5 s, dated from the moment they started.

**What the last title came to** — for **ten minutes after playback ends** the
page keeps the film that just finished: a card with its switch and warning
totals, and its events under it. Those figures matter most once a film is
over, which is exactly when they used to be thrown away.

---

## Films

The **film library**: every film in Kodi's video database as a wall of posters,
in the order Kodi files them. A tap opens the [title dialog](#play-resume-and-watched-marks).

- A film left **half-watched** carries a progress bar along the bottom of its
  poster and is **resumed** where it was.
- A film already **seen** wears a tick in the corner.
- The **IMDb rating** — or **TMDb** where IMDb has none — sits in the opposite
  corner; neither, no badge.
- Under the title: the **year** and the **running time**.
- A **search box** narrows the wall as you type; the cross in it clears it.

The tab is there **whether or not anything is playing** — lining up what comes
next from the phone halfway through a film is a fair thing to want. A search
still being typed, or a show open on the Series tab, survives a film starting
underneath.

**Posters are fetched small.** A tile on a phone is about 120 px wide, while
the scraped poster is often 2000 px. Kodi already keeps a smaller copy of
everything it has drawn, so walls are served from Kodi's **texture cache**
(falling back to the original only when the cache has just been cleared).
They are served at the size Kodi already holds rather than a smaller one
still: the cache is keyed by the whole address, so a size nobody asked for
before is an entry the box has to build — for scraped artwork a fresh
download of the original — which would make the wall slower, not faster.
Posters are fetched as they scroll into view, and each crosses the network
once: its address carries the picture's own tag, so the browser keeps it.

**It keeps itself up to date.** Every snapshot carries the library's version,
which moves whenever what the shelves would show moves — a film watched to the
end, one stopped in the middle, a scan that added something. A page left open
all evening re-reads the list the moment it goes out of date. A re-read that
finds nothing new costs one validator request and leaves the wall, the search
box and the open show exactly as they were. A change made in Kodi's own windows
reaches the page about two seconds later.

The cards **arrive open** and fold away under their headings (with the number
of titles beside them); each device remembers how they were left.

---

## Series

The same wall for what Kodi knows as **TV shows**, with one level more:

- Each poster shows how many **episodes are still unwatched**, in the corner a
  watched film wears its tick; a show seen right through wears the tick.
  Ratings as on the film wall.
- A tap on a series opens the [title dialog](#play-resume-and-watched-marks);
  **Open** shows its episodes **in the order they were made**, each **season
  folded** under its own heading (season number, episode count and total
  running time). *Specials* have their own heading.
- A tap opens a season; a tap on an episode opens its dialog.
- The way back to the wall is at the top of the card, one tap away however far
  down you scrolled.
- A half-watched episode carries the same progress bar, and each row shows the
  episode's running time.

The seasons arrive folded because a show that ran nine years is several
hundred rows; folded, it is a dozen lines, and a still inside a folded season
is never fetched. A show's episodes are only read when the show is opened —
a house with ninety series would otherwise send every episode of all of them
to draw ninety posters.

---

## Continue watching and recently added

At the top of the **Films** and **Series** tabs:

| Row | Contents |
|---|---|
| **Continue watching** | Films (respectively episodes) stopped part-way, the last one seen first, up to 30. Read with Kodi's own *in progress* filter. An episode shows its show's poster with the episode under the name. |
| **Recently added** | The 10 films that arrived last, and the 10 series that gained an episode last (Kodi dates a series by its newest episode), newest first. |
| **Unwatched films** / **Unwatched series** | Only what is still unwatched: films without a tick, series with an episode waiting. |

Each is a row that scrolls sideways. A row with nothing in it is not shown. The
full walls (**Films**, **All series**) follow underneath.

---

## Play, resume and watched marks

A tap on a film, series or episode — on a wall or in a row — opens a dialog:

| Option | Shown for | Effect |
|---|---|---|
| **Play** / **Resume** | films, episodes | Starts it on the box; *Resume* where Kodi has a resume point. |
| **Open** | series | Shows its episodes (a series itself cannot be played). |
| **Play from the beginning** | stopped part-way | Starts from the top, without the resume question on the TV. |
| **Clear resume point** | stopped part-way | Forgets where it got to (taking it off *Continue watching*), leaving watched/unwatched as it was. |
| **Mark as watched** | all | Writes a play count and removes the resume point — as Kodi's context menu does. A series marks every episode. |
| **Mark as unwatched** | all | Removes the play count. A series marks every episode. |

All of these need the **access token** and **Allow VS10 switching from the
dashboard**.

Kodi writes where a title got to slightly *after* it reports that playback
stopped (and announces nothing when it only wrote a resume point), so the
lists are refreshed a moment after a stop rather than at the stop itself.

---

## The remote

On the Live tab, under the progress bar, in two rows:

| Row | Buttons |
|---|---|
| First | Back and forward by 10 s, 1 min and 10 min |
| Second | Previous chapter · Play / Pause · Volume down · Mute · Volume up · Stop · Next chapter |

Under them: a picker for the **audio track** and one for the **subtitles**
(including *Off*). The **progress bar** is dragged — with a finger, or a
mouse held down — and the box seeks to where it was let go; a tap is the
shortest such drag. While it is held, the fill, the clock under it and the
chapter over it follow the finger rather than the player. With the bar
focused, the arrow keys nudge it 10 s.

- Every button goes through Kodi's JSON-RPC into the running player, and the
  page only offers what the player reports: a file with one audio track has no
  audio picker; without chapters the chapter keys are dimmed rather than
  seeking a big step instead.
- On live TV the progress bar is the **broadcast** (EPG event), and seeking is
  done relative to it.
- **Volume steps rather than slides** — it is sent as the same *volume up /
  down / mute* actions a remote sends. A box whose CEC adapter forwards volume
  passes them to the amplifier or soundbar; otherwise Kodi's own mixer reacts.
  CEC has no "set to 40" command, and Kodi's own volume number stands still
  while the amplifier changes, so no level is displayed.

The remote needs the token, and it is not drawn at all with **Allow VS10
switching from the dashboard** off.

---

## Chapters on the progress bar

A file with two chapters or more gets a dot on the progress bar where each
chapter **ahead of the position** starts; a dot goes as the bar passes it, so
the part already seen stays clear. The first chapter of nearly every film
starts at the very beginning, where there is no boundary to mark, so it never
gets one. Two dots closer than six pixels are drawn as one.

Over the bar stands which chapter is playing, of how many, and its name when
the file names it (*Chapter 3 of 12 · Arrival*). A name a ripper or muxer made
up — "Chapter 06", "Kapitel 6", a bare "06", the time it starts — is left out,
since it says nothing the number does not; a real name behind such a number
("Chapter 6: The Hunt") keeps only the name.

- **Pointing and dragging.** While a mouse is over the bar, or a finger drags
  it, every chapter is marked, those already seen too (in a light tone of the
  accent). A drag that comes close to a dot snaps onto it, and the label names
  the chapter under the finger. Pointing at a dot, or tapping it, names its
  chapter and when it starts.
- **Jumping.** With the remote allowed, a drag let go on a dot, or a tap on
  one, jumps to the start of that chapter rather than to the spot, and
  Page Up / Page Down go a chapter back and on while the bar has the focus.
  The jump is asked for by the chapter's number, so it lands where the
  chapter starts and not a few seconds either side of it.
- **Always there.** The dots are a reading, not a control, so they are shown
  with the remote switched off too. They come from Kodi's own
  `Player.GetChapters` — the chapters Kodi's own seek bar marks — read once
  per title. **Show chapter markers** on the Settings tab takes the dots and
  the label off the bar, for that device only.

---

## Switching VS10 from the browser

With **Allow VS10 switching from the dashboard** on (the default), the Live tab
shows the output modes that apply to the playing source — the same set as the
on-screen [VS10 dialog](VS10-Output-Modes), SDR sources included — and a tap
applies one. The switch takes exactly the path a `run_mode` keymap takes,
native VS10 actions included.

- A switch takes a few seconds. Taps arriving meanwhile are not queued: the
  last one replaces any still waiting.
- **HDR10+** and **HLG** sources, and **Dolby Vision titles carrying HDR10+**,
  have no VS10 modes; the whole VS10 card, output line included, is hidden for
  them. A stream whose HDR10+ Kodi has stripped for a display that cannot show
  it keeps its modes: what was removed is no longer in what the decoder is fed.
- Switching **always** requires the access token, whatever the reading setting
  says.

---

## Settings tab

- **Theme** — Dark, Dark (adaptive) or Midnight, and the adaptive intensity
  (see [Themes](#themes)).
- **Access token** — the token this device holds, all but its last two
  characters hidden, and a key to enter a new one.
- **Progress bar** — whether the progress bar shows a dot where each chapter
  starts; this device's own choice.
- **Copy report** — copies everything as plain text, ready to paste into a
  forum post: the rows, what the title added up to, and the events. With
  nothing playing it copies the report of the title that just finished.
- A second key beside it copies the **Dolby Vision metadata list**.

A key with nothing to copy is dimmed.

---

## Themes

Three themes, all dark — this is watched in the room the projector is in:

| Theme | Look |
|---|---|
| **Dark** | The plain theme. |
| **Dark (adaptive)** | What a first visit gets: the same page, with the **now-playing card** taking its color from the poster. The artwork is read region by region, and the one color that stands for it best is drawn across the card as a broad glow — strongest beside the poster, gone well before the card's foot. How much color survives is worked out per film against the contrast the text needs: a dark poster keeps nearly all of it, a bright one is held back. Other cards keep their plain surfaces but take the film's **accent** for headings, badges, buttons and the chart's traces. Intensity: **Subtle**, **Standard** or **Strong**. A title without a poster looks like plain Dark. |
| **Midnight** | Deeper and bluer, for a room with nothing else lit. |

The choice is stored **in the browser, per device**, applied before the first
paint (no flash of the wrong theme) and never sent to the box.

---

## Layout on phones and desktops

- **Phone:** one column, read top to bottom — what is playing, every reading,
  then figures, charts and events.
- **Laptop / tablet held sideways:** two columns — what is playing down the
  left, what it has come to down the right — with the readings full width
  beneath, as many cards per row as fit.

It is the same page folded differently: nothing is hidden by the wide layout or
added by the narrow one. Every panel below the film **folds away**, and each
device remembers which were open — a second screen on a shelf can be trimmed to
the two or three readings you watch for.

---

## What it costs the box

A second screen often stays open for a whole film, so the dashboard is built
not to be felt:

| Design | Effect |
|---|---|
| **Connects as it loads** | The live stream opens together with the page, not after the translations. |
| **Only what moved is sent** | A browser gets one full snapshot on connect, then — five times a second — only the readings that changed: a few dozen bytes on a still scene, instead of tens of kilobytes. |
| **Hidden pages disconnect** | Lock the phone or switch browser tabs and the stream is dropped; come back and it reconnects at once. Saves the phone's battery and one of the six stream slots. |
| **Nothing is built for nobody** | With no page connected the box builds no snapshot at all; once a second it only records what the history needs (chart sample, events). |
| **One builder for all pages** | Five open tabs cost the same as one. |
| **Static files are cached** | Page files are sent compressed with a validator; a second visit fetches almost nothing. The poster is fetched once per film, from Kodi's texture cache. |
| **Library scans are coalesced** | Kodi announces every item a scan adds. The box waits until the scan pauses for 2 s (or 10 s have passed on a long one) and drops its lists once. Two pages asking for the same list at once share one database read. |
| **A full server says so** | A seventh device sees *"Too many connections"* instead of a silent *Disconnected*, and takes the first slot that frees. |

---

## Dashboard settings

All under **Settings → Dashboard**:

| Setting | Default | Effect |
|---|---|---|
| **Enable web dashboard** | Off | Starts or stops the server. Applied immediately — no restart needed. |
| **Port** | 8099 | Listening port (1024–65535). Out-of-range values fall back to 8099. |
| **Show address and token** | — | Shows the address and the current token. |
| **Access token** | *generated* | The key the page asks for. Created automatically (8 characters) the first time it is needed; can also be typed in. |
| **Generate a new token** | — | Replaces the token; every browser with the old one has to enter the new one. |
| **Show the Dolby Vision metadata view** | On | Adds the Metadata tab's full list. |
| **Show the film library** | On | Offers the Films tab and film rows. Needs **Allow VS10 switching** too. |
| **Show the series library** | On | Offers the Series tab and episode rows. Needs **Allow VS10 switching** too. |
| **Require the token for reading too** | Off | Asks for the token before showing anything at all. |
| **Allow VS10 switching from the dashboard** | On | Enables VS10 switching, the remote, playback and watched marks from the browser. Off makes the dashboard read-only. |
| **Ratings → MDBList API key** | empty | A free key from mdblist.com; the overview then shows the ratings MDBList gathers for a film (see [Ratings from MDBList](#ratings-from-mdblist)). Empty, it shows the library's. |

Security details — the token, the lockout, trusted host names and the headers —
are on [Dashboard Security](Dashboard-Security). The endpoints are documented on
[Dashboard HTTP API](Dashboard-HTTP-API).
