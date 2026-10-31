# Web Dashboard

TinyPPI can serve everything the overlay shows to a **browser on your phone,
tablet or laptop**, so the readings can be followed while the picture on the
TV stays untouched. On top of the readings the dashboard has a live luminance
chart, an event history, a remote, VS10 switching, and the film and series
library with continue watching.

The page and its images are served entirely by the add-on, so the browser
needs no connection to an outside image service. Kodi's cached artwork works
offline; an uncached original may need a connection from the box. A missing
cast portrait falls back to the person's initial. The overview's ratings
also reach out from the box rather than the browser: the IMDb
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
- [Awards](#awards)
- [Metadata](#metadata)
- [History](#history)
- [Films](#films)
- [Series](#series)
- [Continue watching and recently added](#continue-watching-and-recently-added)
- [Play, resume and watched marks](#play-resume-and-watched-marks)
- [The details page](#the-details-page)
- [Arranging the cards and the tabs](#arranging-the-cards-and-the-tabs)
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
| **Live** | `/#live` | Now playing, the overview (a key to the playing title's details), the player card (the remote), VS10 output and every reading of the overlay | always |
| **Metadata** | `/#metadata` | Active picture area, L1 luminance chart, the full Dolby Vision metadata list | only while a Dolby Vision title plays (and **Show the Dolby Vision metadata view** is on) |
| **Films** | `/#films` | The search and the filters, continue watching (films), recently added, unwatched films, the whole film library | when the film library is offered |
| **Series** | `/#series` | The search and the filters, continue watching (episodes), next up, recently updated series, series with unwatched episodes, the whole series library | when the series library is offered |
| **History** | `/#history` | Metrics, chart and events of the playing title — or, for ten minutes after the credits, of the one that just ended | always |
| **Settings** | `/#settings` | Theme, access token, the progress bar's chapter dots, copy report, which tabs the bar shows, putting the cards back | always |

Every tab but Live and Settings can be switched off on the Settings tab (see
[Arranging the cards and the tabs](#arranging-the-cards-and-the-tabs)); a tab
switched off is not on the bar even when it has something to show.

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

**Player** — the remote, on a card of its own under the overview as in the
TinyPPI app (see [below](#the-remote)).

With nothing playing the tab says *"Nothing is playing — Start a video on the
box and everything it carries appears here."*

What a source cannot carry is left out rather than shown empty: the peak and
average tiles, the luminance chart, the active-area box and both metadata
sections come from the Dolby Vision RPU and appear only for Dolby Vision; the
HDR static metadata group is left out for SDR. That is the same rule the
overlay follows.

---

## Overview

A card under *Now playing* that is nothing but its heading and an arrow — a
key. A click or tap on it opens the playing title's
[details page](#play-resume-and-watched-marks): its ratings as shields, the
slogan and the plot, genre, director, writer and studio, and the cast as a row
of cards. The page has no play keys there — the title is already playing.

For a film or an episode the library holds, on a box that takes orders
(**Allow VS10 switching from the dashboard**) and whose shelf for the title is
on — the film shelf for a film, the series shelf for an episode, as
`/api/hello` says — the page is the library's (`/api/details`). For anything
else — a **live TV** broadcast, a file the library does not know, or a box that
hands out no details — it shows what the snapshot says of what is playing: the
plot from the EPG or the file's tags, the ratings, and who made it and is in it,
each of the cast with who they played. Where the snapshot says nothing of it
either, there is no card. The TinyPPI app follows the same rule. The card is
named for what plays: *About the film*, *About the episode*, or for a live
channel *About the programme*.

The shields on the details page:

- **Ratings** — a centred row of small shields, each washed in its service's
  colour: first the age rating (FSK, MPA, TV Parental Guidelines, BBFC as a
  mark on the level's colour; any other written out), then a score for each
  source — IMDb, TMDB, Trakt, TheTVDB, Letterboxd, Metacritic and its users,
  Rotten Tomatoes and its Popcornmeter, Roger Ebert (*RE*), MyAnimeList,
  MDBList, or the first letter of any other — then your own rating behind a
  heart, the place in the IMDb Top 250 (*250* | *#17*) and the big awards (see
  [Awards](#awards)). How many voted is not shown. Every score is out of ten,
  whatever scale its service uses: Roger Ebert's 3.5 of 4 stars show as 8.8,
  Letterboxd's 4.5 of 5 as 9.0.

**Which board is an age rating?** An episode carries its show's age rating.
One that names neither its country nor its board ("Rated 12", which the TMDb
scraper writes with its default prefix) is read as the one board that gives
that level — "PG-13" is American, "15" British — and where more than one does
("12", "18", "PG") as the board of the country Kodi's language points to:
German, British English or American English. The credits and the ratings are
what Kodi knows of whatever plays, so an add-on's stream that names them has
them too.

**Which service is a mark?** A mouse pointer over a shield shows its name as a
tooltip (*IMDb*, *Trakt*, *FSK*, *IMDb Top 250* …). A screen reader hears each
shield in full (*"IMDb 8.5"*).

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

## Awards

The Academy Awards, the Golden Globes, the BAFTAs and the Primetime Emmys
stand last among the ratings, each as a drawing of what it hands out (a
statuette, a ringed globe, a theatre mask, a winged figure holding an atom)
with a figure beside it: how many it **won**, on a gold shield — or, where it won none, how
many it was **nominated** for, on a quieter grey one. A tap shows what it won
it for (*Oscar: Visual Effects (2015) · 4 nominated*).

They come with the add-on, from **[TheTVDB](https://thetvdb.com)**
(`resources/data/awards.json`, written by `tools/gen_awards.py`): **no key, no
request** on the box. A film is looked up by the TheTVDB, IMDb or TMDb id the
library holds, an episode by its show's. The list holds what was nominated
for one of these four, up to the season it was last written for; a title it
does not hold shows none.

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
ten: a score out of 100 a tenth of it, Roger Ebert's four stars ten. MDBList's
own score — made of all the others, the figure its page shows in the coloured
circle (`score_average`) — stands last of them, with MDBList's mark. An answer
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
non-commercial use — does, **no key needed**; it is always asked. A certified rating's shield
wears a small red seal with a tick on the corner of its mark, and its tooltip
and what a screen reader hears name the certificate ("Rotten Tomatoes ·
Certified Fresh 9.3").

WhatsOn also fills in what MDBList lacks: it has no Rotten Tomatoes rating
for some films that Rotten Tomatoes does rate (The Matrix and Interstellar
among them). Where neither MDBList nor the library has the Tomatometer or the
Popcornmeter for a film, WhatsOn's is shown; one they have stands.

The box asks WhatsOn for a film (episodes never) once MDBList has answered or
will not be asked, by the IMDb id the library holds, else the TMDb one, and
keeps the answer — a film WhatsOn does not know included — for half a day.
Without a key WhatsOn answers 40 times an hour and 200 times a day, which one
question per film stays well inside. A free key from its author
([pierrevano.github.io](https://pierrevano.github.io)) raises that to 200 an
hour and 1,000 a day: enter it under **Settings → Dashboard → Ratings →
WhatsOn API key (optional)**. A key WhatsOn does not know is answered as no
key at all. Should the limit be spent all the same, the box waits as long as
WhatsOn says; a key given meanwhile is asked with at once. WhatsOn runs on a free host that sleeps when idle, so
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
in the order Kodi files them. A tap opens its [details page](#the-details-page).

- A film left **half-watched** carries a progress bar along the bottom of its
  poster and is **resumed** where it was.
- A film already **seen** wears a tick in the corner.
- The **IMDb rating** — or **TMDb** where IMDb has none — sits in the opposite
  corner; neither, no badge.
- Under the title: the **year** and the **running time**.
- At the **top of the tab**, as in the app, a **search box** narrows the wall
  as you type; the cross in it clears it. Typing into it unfolds the wall if it
  was folded.
- Under it, on a card of its own, the wall can be **sorted** — by title (Kodi's own order), year,
  rating, date added or running time, each **ascending or descending** (the
  arrow key beside the order turns it round; a new order starts the way it
  reads best — newest, best and latest added first). The order and its way
  round are kept in the browser for the next visit; a film without the value
  goes last either way —
  and **filtered** by genre, picture format (Dolby Vision, HDR10+, HDR10,
  HLG, SDR — and under Dolby Vision each profile the library holds, such as
  P5, P7 FEL, P7 MEL or P8.1, where it holds more than one), resolution (4K, 1080p, 720p, SD) and audio format (the first
  audio track's codec: Dolby TrueHD, DTS-HD MA, Dolby Digital Plus, …). A
  filter offers only what the library holds and is left out where there is
  nothing to choose between; the formats come from what Kodi read off the
  files, so a film it has not scanned yet is under none of them. Kodi does
  not record Atmos or DTS:X in its library, so the sound is filtered by the
  codec it rides on. The filters and the search narrow the wall together. On
  a phone the order and the filters are one row that slides sideways, as the
  app's do.
- On a phone the wall stands **three posters to a row**.

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
- A tap on a series opens its [details page](#the-details-page); **Open**
  slides its **seasons** in over it, on a page drawn the way the details are —
  the show's backdrop, poster and name, its year and how many episodes it has —
  with its episodes **in the order they were made**, each **season folded**
  under its own heading (season number, episode count and total running time).
  *Specials* have their own heading.
- A tap opens a season; a tap on an episode opens its details page in front
  of the seasons.
- Leaving the seasons — the close key, Escape, the phone's back gesture, a
  pull down from the top or a click beside the page — slides them back out to
  the show's details page they were opened over, exactly as it was. The wall
  stays as it was underneath, the search included.
- A half-watched episode carries the same progress bar, and each row shows the
  episode's running time.
- The wall sorts as the film wall does (without the running time) and filters
  by genre.

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
| **Next up** (Series) | The next unwatched episode of each show being watched — its first unseen one in episode order, specials left out — the show watched last first, up to 15. An episode already on *Continue watching* is not repeated. |
| **Recently added** | The 10 films that arrived last, and the 10 series that gained an episode last (Kodi dates a series by its newest episode), newest first. |
| **Unwatched films** / **Unwatched series** | Only what is still unwatched: films without a tick, series with an episode waiting. |

Each is a row that scrolls sideways. A row with nothing in it is not shown. The
full walls (**Films**, **All series**) follow underneath.

---

## Play, resume and watched marks

A tap on a film, series or episode — on a wall or in a row — opens its
[details page](#the-details-page), with these keys under its heading:

| Option | Shown for | Effect |
|---|---|---|
| **Details** | all | The title's details from the library, under its backdrop (a film's or a series' fanart, an episode's still) with its poster: year and running time, the file's formats, every rating the overview card would show for the title, as its shields (age rating, the library's, MDBList's and Rotten Tomatoes' scores with their certificates, your own, the Top 250 place, the awards), tagline and plot, genres, director, writers, studio, and the cast as a row of cards of one height with who they played — the same layout as the overview card. On a phone it is a page of its own, the whole screen. On the **Dark (adaptive)** theme it wears the accent of the title's own poster rather than of what is playing. Under the heading the question's first answers as keys: **Play** or **Resume**, **Play from the beginning** where there is a point to resume from, **Open** for a series. |
| **Play** / **Resume** | films, episodes | Starts it on the box; *Resume* where Kodi has a resume point. |
| **Open** | series | Slides its seasons in over the page (a series itself cannot be played). |
| **Go to series** | episodes on *Continue watching* and *Next up* | Puts the episode's show's details page in its place, on the Series tab. |
| **Play from the beginning** | stopped part-way | Starts from the top, without the resume question on the TV. |
| **Clear resume point** | stopped part-way | Forgets where it got to (taking it off *Continue watching*), leaving watched/unwatched as it was. |
| **Mark as watched** | all | Writes a play count and removes the resume point — as Kodi's context menu does. A series marks every episode. |
| **Mark as unwatched** | all | Removes the play count. A series marks every episode. |

All of these need the **access token** and **Allow VS10 switching from the
dashboard**. Starting a title — **Play**, **Resume** or **Play from the
beginning** — takes the page to the **Live** tab, where what was just started
is shown.

Kodi writes where a title got to slightly *after* it reports that playback
stopped (and announces nothing when it only wrote a resume point), so the
lists are refreshed a moment after a stop rather than at the stop itself.

---

## The details page

What the library holds about one title, as a page of its own — on a phone the
whole screen, on a desktop a page up to 780 px wide in the middle of it. It
**slides in** from the side as it opens and **back out** as it is left, the
way one page of the app gives way to the next; a show's seasons slide in over
its details the same way.

- **Leaving it:** on a desktop the close key on the picture, Escape, or a
  click beside the page; on a phone — where it has no close key, as in the
  app — the back gesture or a pull down from its top.
- **Under the heading:** the keys of the table above — the first answer filling
  the row, the others as round icons beside it, on a phone too.
- **Who made it and who is in it** stand as rows of cards that scroll
  sideways and run out to the edge of the screen. A row fades out at the side
  it goes on past, so the card there runs out softly rather than being cut
  off; with a mouse it is dragged. The page shows no scrollbars.
- **Cast cards:** the actors come first under the localized cast heading
  (*Darsteller* in German). Directors and writers follow in a separate row
  headed *Cast*, with their functions under their names. A portrait supplied
  by Kodi appears at the top as a large rectangle with slightly rounded
  corners. Where Kodi has none, an optional **TMDb API key** (see
  [Settings Reference](Settings-Reference)) fills it from the title's own
  credits on TMDb; without the key nothing is asked. Without a picture,
  or if it cannot be loaded, the initial stands
  in its place. Names and roles are centred together between the picture's
  lower edge and the card's bottom. Cards stretch to the same height within
  a row; their height follows the text rather than a fixed pixel value.
  Names and roles can wrap. The TinyPPI app uses the same arrangement.
- **Where it leads on to** (with the **TMDb API key**): a film's **series**,
  under the series' name, as a row of posters in release order — the film
  itself marked, each film the library holds as the library has it, and the
  others, marked *TMDb*, with TMDb's poster and name. And under *More like
  this in your library*, the films (or series) of the library TMDb
  recommends after this one. A tap on a title the library holds opens **its
  own details page** in place of this one, with its keys — a series' on the
  Series tab; a title the library does not hold opens **its page on TMDb**.
  **Back**, Escape or the close key on a page opened this way go back to the
  page it was opened from, as it was; only on the first page do they close
  the details.
- **A series' state** (with the key) stands among its facts: whether it
  goes on, ended or was cancelled, who airs it, how many seasons and episodes
  there are in all, and the next episode to air and the last aired, with
  their days.
- **While it is read** a thin bar runs along the top of the window (and the
  pointer shows it is busy): the box may wait a few seconds on MDBList,
  WhatsOn and TMDb before it answers.
- A page gone back to within a minute is drawn at once from what was read,
  rather than after the box answers again.

---

## Arranging the cards and the tabs

As in the TinyPPI app, the cards on the Live, Metadata, Films, Series and
History tabs can be **moved and taken off**:

- **Long-press** a card's heading — or **right-click** it — and the tab turns
  into a list of its cards, each with arrows to move it and an eye to take it
  off the tab or put it back. **Reset** puts the tab back as it was, **Done**
  returns to it.
- What is playing stays at the top of the Live tab. On the Live tab the cards
  under it and the readings move among themselves, each in its own part of
  the page.
- A tab with every card taken off says so, with a key back to the list.
- **Settings → Tabs** switches the Metadata, Films, Series and History tabs
  on and off the bar. **Settings → Cards → Reset all cards** puts every card
  back on every tab.

Like the theme, all of this is kept **in the browser, per device**, and never
sent to the box.

---

## The remote

On the Live tab, in the **Player** card under the overview (it arrives
folded; its heading unfolds it), in two rows:

| Row | Buttons |
|---|---|
| First | Back and forward by 10 s, 1 min and 10 min |
| Second | Previous chapter · Play / Pause · Volume down · Mute · Volume up · Stop · Next chapter |

Under them, the **fine adjustments**: the **audio offset** (lip sync, in steps
of 50 ms within ±10 s) and the **subtitle offset** (in Kodi's 100 ms steps,
shown while subtitles are on). The two adjustments stand side by side when
there is room and stack on a narrow card. The TinyPPI app follows the same
rule, allowing more room when the device's text size is enlarged.
A tap on an offset's value puts it back to 0. Kodi has no JSON-RPC method for
the subtitle offset, so it is moved with the same key presses a remote sends,
and Kodi shows its own slider on the TV for a moment while it moves. Then a
picker for the **audio track** and one for the **subtitles** (including *Off*). The **progress bar** is dragged — with a finger, or a
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
- **Tabs** — which tabs the bar shows (see
  [Arranging the cards and the tabs](#arranging-the-cards-and-the-tabs)).
- **Cards** — how to move the cards, and a key that puts every card back on
  every tab.

A key with nothing to copy is dimmed.

---

## Themes

Three themes, all dark — this is watched in the room the projector is in.
The page is drawn in the **TinyPPI app's** design: its dark palette, cards one
step up from the page with a hairline round them and 20 px corners, pill-shaped
chips and buttons, tool keys with 12 px corners on the card's raised ground,
headings with the accent tick, small centred captions over the keys, Material
dialogs and the floating tab bar with the open tab as a filled pill. A phone and
a browser opened on the same box read as one thing.

| Theme | Look |
|---|---|
| **Dark** | The plain theme. |
| **Dark (adaptive)** | What a first visit gets: the same page, with the **now-playing card** taking its color from the poster. The artwork is read region by region, and the one color that stands for it best is drawn across the card as a broad glow — strongest beside the poster, gone well before the card's foot. How much color survives is worked out per film against the contrast the text needs: a dark poster keeps nearly all of it, a bright one is held back. Other cards keep their plain surfaces but take the film's **accent** for headings, badges, buttons and the chart's traces — and every colour drawn from it with it, as the app does: what is written on the accent, the tonal ground of a badge, a chosen chip or a cast card's initial, and what is written on that. A title's details page takes the accent of that title's own poster. Intensity: **Subtle**, **Standard** or **Strong**. A title without a poster looks like plain Dark. |
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
