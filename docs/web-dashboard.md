# Web Dashboard

TinyPPI can serve everything the overlay shows to a browser on your phone or
laptop, so the readings can be followed **while the picture stays untouched**.
The dashboard is off out of the box; switch it on under **Settings →
Dashboard**, then open the address it names on any device on the same network:

```
http://<box-ip>:8099/
```

**Settings → Dashboard → Show address and token** prints that address together
with the access token, which is what you need standing in front of the TV with
a phone in your hand.

## What it shows

The page is split into six tabs, switched from a floating bar of icons at the
foot of the screen — the five of the TinyPPI app, in the same order, and the
settings:

| Tab | What is on it |
|---|---|
| **Live** | What is playing, the transport row, the VS10 output and every reading of the overlay |
| **Metadata** | The Dolby Vision metadata: the active picture area, the luminance chart and the full list (see below) |
| **Films** | Continue watching (films), recently added films, the unwatched films and the whole film library |
| **Series** | Continue watching (episodes), recently updated series, the series with unwatched episodes and the whole series library |
| **History** | The metrics and the events of the title that is playing — or, for ten minutes after the credits, of the one that just ended |
| **Settings** | The theme, the access token and the two reports |

The address remembers the tab (`/#films`, `/#history`, …), so a bookmark or a
reload comes back to it, and each device reopens the tab it was left on. The
film and series tabs are only in the bar when the box offers those libraries,
and the metadata tab only while a Dolby Vision title is playing. Live,
metadata, history and settings stand centred between the two bars; the two
shelves start at the top.
The bar shows icons only; each key names its tab under a pointer and to a
screen reader. Like the app's, it steps away after three seconds with
nothing happening, handing its room at the foot of the page back to the last
card, and comes back with the next touch, scroll, key or pointer movement. The top bar carries just the name, the version and the
connection light.

- **Now playing** — the poster, title, year and genre, the file name (when
  *Show file name* is on), elapsed time and progress.
- **Format badges** — a row for the picture (resolution, HDR format with the
  Dolby Vision profile and layer, a conversion as `DV → HDR10`, IMAX) and a
  row for the sound (codec, Atmos or DTS:X, channel layout), the same badges
  the TinyPPI app draws under its title.
- **Metrics** — the player cache, current frame rate, warning count and how
  often the output or a playback track was switched.
- **A live luminance chart** — the Dolby Vision L1 peak and frame average on a
  logarithmic scale, over the last minute, the last ten, or the whole title:
  the add-on has been sampling since playback started, so a page opened halfway
  through a film gets the part it missed instead of starting from empty.
- **Events** — a list with timestamps of the things worth knowing about: an
  output switched to or from Dolby Vision, a display mode change, the box
  running hot or its processor at full load, or the selected audio/subtitle
  track changing. A long list scrolls
  inside its own card rather than stretching the page under it.
- **What the last title came to** — for ten minutes after the credits the page
  keeps the film that just ended: a card of its own with its switch and warning
  totals, and the events of that film still under it. Those figures are
  worth most once a film is over, which used to be exactly when they were
  thrown away. Both are on the history tab.
- **Continue watching** — the films and episodes the box was stopped in the
  middle of, the last one seen first: the films at the top of the films tab,
  the episodes at the top of the series tab. Each poster carries how far it
  got, and a tap resumes it where it was (see below).
- **Recently added** — the ten films, and the ten series, that arrived in the
  library last, newest first (see below).
- **The film library** — the films in Kodi's video database as a wall of
  posters, and a tap starts one on the box (see below). Its tab is there
  whether or not anything is playing.
- **The series library** — the same wall again for what Kodi knows as TV
  shows, with how many episodes are still unwatched on each poster. A tap opens
  the show and a tap on one of its episodes starts it (see below).
- **The active picture area** the RPU declares (L5), drawn to scale inside the
  coded frame — the letterbox as the stream describes it, changing with the
  scene on an IMAX Enhanced title. It sits on the metadata tab, with the
  blocks it is read from.
- **Every row of the overlay**, grouped as it is on screen: Video, Processing,
  Audio, HDR static metadata, Dolby Vision metadata and System. A reading that
  just moved is highlighted the same way the overlay highlights it.
- **The Dolby Vision metadata view**, on a tab of its own (see below).
- **Copy report**, on the settings tab, hands the whole set over as plain
  text, ready to paste into a forum post — the rows, what the title added up
  to, and the events along the way. It works with nothing playing too, where it
  writes the report of the title that just finished. The second key beside it
  copies the metadata list. A key with nothing to copy is dimmed.
- **The access token** this device holds, all but its last two characters
  hidden, and a key to enter a new one — also on the settings tab.

What a source cannot carry is left out rather than shown empty: the peak and
average tiles, the luminance chart, the active-area box and both metadata
sections come from the Dolby Vision RPU, so they appear for a Dolby Vision
title and not for any other, and the HDR static-metadata group is left out on
an SDR one. That is the same rule the overlay follows when it decides which
panels to draw.

The row labels come from Kodi's own string table, so the dashboard is in the
same language the overlay is. Nothing is loaded from the internet: the page is
served entirely by the add-on and works on a box with no outside connection.
On a phone it can be added to the home screen.

## How it is laid out

The page takes the width it is given. On a phone it is one column, read top to
bottom: what is playing, every reading under it, then the figures, the charts
and the events. On a laptop or a tablet held sideways it becomes two — what is
playing down the left, what the playing of it has come to down the right — with
the readings running the full width beneath both, as many cards to a row as
fit. Nothing is hidden by the wider layout and nothing is added by the narrow
one; it is the same page, folded differently, so a phone and a desktop looking
at the same film show the same things in the same order.

Every panel below the film folds away, and each one remembers whether it was
open on that device — so a second screen left on a shelf can be trimmed to the
two or three readings that are being watched for.

## What it costs to leave open

A second screen is left running for the length of a film, so the page is built
not to be felt while it is:

- **It connects as it loads.** The stream is opened in the same breath as the
  page rather than after the translations have been fetched, so the dashboard
  is live about as fast as it can draw.
- **Only what moved is sent.** A browser is given one whole snapshot when it
  connects and, five times a second after that, only the readings that actually
  changed — which on a title standing still is a few dozen bytes where the
  snapshot it replaces is tens of kilobytes.
- **A page nobody is looking at is not connected.** Lock the phone or switch
  tabs and the stream is dropped; come back and it is up again immediately.
  That is the battery on the phone and one of the add-on's six stream slots,
  neither spent on a page in a pocket.
- **Nothing is built for nobody.** With no page connected the box builds no
  snapshot at all: once a second it only notes what the history needs — the
  luminance sample and the events — so a dashboard that is switched on but not
  open costs the box next to nothing.
- **The page itself is cached.** Its files are sent with a validator and
  compressed, so opening the dashboard a second time fetches almost nothing,
  and the poster is fetched once per film however often the page is reopened —
  out of Kodi's texture cache, like the posters on the shelves (see below), so
  it is small and needs no internet.
- **A library scan is not felt either.** Kodi announces every item a scan
  adds on its own, and the shelves are not read again for each: the box waits
  until the scan has paused for two seconds — or, on a long one, ten seconds
  have passed — and drops its lists once. Two pages asking for the same list at
  the same moment share one read of the video database.
- **A full server says so.** Open the dashboard on a seventh device and it
  reports that rather than sitting on "Disconnected"; it takes the first slot
  that frees.

## Themes

The settings tab switches the page between three themes, and every one of
them is dark — this is watched in the room the projector is in, so there is
nothing here for a lit one:

- **Dark** — the plain one, and what a first visit gets.
- **Dark (adaptive)** — the same page, with the **now-playing card** taking
  its colour from the poster of whatever is on screen. The artwork is read
  region by region and the one colour that stands for it best is drawn across
  the card as a broad glow — strongest beside the poster, spent well before the
  foot, so the bottom of the card is the same plain panel every other one is
  whether the controls are folded out or away.
  How much of the colour survives is worked out per film against the contrast
  the card's text needs: a dark poster keeps nearly all of it, a bright one is
  held down as far as it has to be, and both end up equally readable. No other
  card is painted: the surfaces around the film stay exactly what they are on
  the plain dark theme, so the page has one coloured thing on it and everything
  else is the page.
  What the other cards do take is the film's accent, for the things read past
  rather than read — the card headings, a badge, a button, the luminance
  chart's own traces — while the readings themselves keep the plain text
  colour. A title with no poster looks exactly as it does on the plain dark
  theme; there was nothing to take a colour from. While this theme is on, the
  settings tab also offers how strongly it tints: **subtle**, **standard** or
  **strong**.
- **Midnight** — deeper and bluer, for a room with nothing else lit in it.

The choice is remembered in the browser, per device, and is applied before the
page is first drawn, so reopening the dashboard never flashes the wrong theme.
The phone's own status bar follows it. Nothing is
sent to the add-on: the theme is the browser's business, not the box's.

## The Dolby Vision metadata tab

The **Metadata** tab — also reachable as `http://<box-ip>:8099/metadata`, the
address the view had when it was a window of its own, so an old bookmark still
lands on it — lists every block the stream's side data carries: the configuration record, the RPU from its header through L255, the
composer's reshaping curves, the trim passes and the static SEIs. It is the
same list the on-screen view shows,
built from the same rows, and it stays live: the per-frame blocks move with the
picture and a reading that just changed is highlighted, exactly as in the
overlay. On a wide screen it flows into two or three columns, never breaking a
section across them, and the metadata key under **Copy report** on the
settings tab hands the whole list over as plain text.

On any other source, and with nothing playing, the tab is not in the bar at
all; a page that is on it when the title ends goes back to the live tab.

It can be turned off entirely under **Settings → Dashboard** — it is the
largest thing the add-on sends, so on a slow network it is the first thing to
switch off.

## Starting a film from the browser

The **Films** tab is the **film library**: every film in Kodi's video
database, as posters, in the order Kodi files them. A tap starts one on the
television.

The tab is there whether or not anything is playing — lining up what comes
next is a fair thing to want from the phone halfway through a film — and a
search still being typed, or a show still open on the series tab, survives a
film starting under it.

It keeps itself up to date without being asked. Every snapshot carries the
version the box's library is on, and that number moves whenever what the
shelves would say moves — a film watched to the end, one switched off in the
middle, a scan that added a series — so a page left open on a shelf all evening
reads it again at the moment it goes out of date rather than showing this
afternoon's answer until somebody reloads it. A read that finds nothing has
actually changed costs a validator and leaves the wall, the search box and the
open show exactly as they were. A change made in Kodi's own windows reaches the
page about two seconds later: that is how long the box waits for the next one,
since a scan sends them by the hundred.

A film the box left half-watched carries a bar along the bottom of its poster
and is **resumed** where it was, the same as pressing it in Kodi's own window;
one already seen wears a tick in the corner of the picture. What **IMDb** made of it — or TMDb where IMDb has nothing to say — sits in the opposite corner of the poster, and is left off entirely where neither house has an opinion. Under the
title are the year and how long the film runs. The card carries a
search box, which narrows the wall as it is typed in; the cross inside it empties
it again and puts the whole shelf back.

The cards **arrive open** — the tab is there for the films — and each folds
away under its own heading with the number of titles beside it. How it was
left is remembered on each device.

The list is read from the video database once and held until Kodi says it
changed, so a film added mid-evening appears without anything being restarted,
and a phone that opens the page twice is answered the second time with a
validator rather than the whole library. A title ending is a moment or two
behind that: Kodi writes where it got to after it has said that playback
stopped — and says nothing at all when what it wrote was only a resume point —
so the held lists are dropped once the box has had its moment to write rather
than at the stop itself. The posters are fetched as they are
scrolled to, and each one crosses the network once: its address carries the
picture's own tag, so the browser keeps it.

They are also fetched small. A tile on a phone is a hundred and twenty pixels
wide and the poster behind it is what the scraper fetched — often two
thousand — which a browser has to carry over the network and then decode in
full before it can draw any of it. Kodi already keeps a smaller copy of
everything it has ever drawn, so a wall is served out of its texture cache
rather than out of the original, and falls back to the original only on a box
whose cache has just been cleared.

Out of the cache as Kodi already holds it, note, rather than asking it for a
smaller size still: the cache is keyed by the whole address, so a size nobody
has asked for before is an entry the box has to build — and for scraped
artwork, building one means fetching the original off the internet again. That
is a download per tile, which makes for a slower wall rather than a faster one.

Starting a film needs the access token and the same **Allow VS10 switching from
the dashboard** setting the rest of the controls need. The card itself can be
turned off under **Settings → Dashboard → Show the film library**, which stops
the list being read and served at all.

## Continue watching

At the top of the films tab and of the series tab is a row of the films —
respectively the episodes — left half-watched, the last one seen first: the
quickest way back into whatever was on. It scrolls sideways; an episode stands
on it as its show's poster, with which episode it is under the name. Every poster carries the same resume bar
the walls do and the same rating badge — a film its own, an episode its show's
— and a tap resumes it where it was.

It is read with Kodi's own "in progress" filter, holds the thirty most recent
titles, and is dropped and read again on the same occasions the shelves are, so
a film switched off in the middle is at the front of the row as soon as the box
has written where it got to. A row with nothing on it is no card at all. Films
are on it only where the film library is offered and episodes only where the
series library is.

## Recently added

Under **Continue watching** is a second row of the same kind: the ten films
that arrived in the library last, and on the series tab the ten series that
gained an episode last, newest first. Kodi dates a series by its newest
episode, so a show that got a new episode last night is at the front. The
tiles are the ones on the walls — a tap on a film asks what to do with it, a
tap on a series opens it in the series card further down — and the row is
built from the lists the walls are, so it moves with them.

## Watched and unwatched

A tap on a film, a series or an episode opens a dialog with three options:
**Play** (or **Resume**, where the box has a point to resume from),
**Mark as watched** and **Mark as unwatched**. For a series the first option is
**Open**, since a series cannot be played; its episodes can. Marking is written
into Kodi's own library, the way its context menu does it: a title marked
watched gets a play count and loses its resume point, one marked unwatched
loses its play count. A series marked either way is every episode of it.
Continue-watching tiles open the same dialog.

A film or an episode that was stopped part-way through gets two more options:
**Play from the beginning**, which starts it from the top without the resume
question on the television, and **Clear resume point**, which forgets where it
got to — taking it off the continue-watching row — while leaving it watched or
unwatched as it was.

Under **Continue watching** and **Recently added** are two cards holding only what is still
**unwatched**: the films without a tick, and the series with an episode still
waiting, each on a row that scrolls sideways like the two above them; the walls
of all films and all series follow them. The tiles ask the
same question as on the full walls, and opening an unwatched series opens it
in the series card further down. A card with nothing on it is not shown.

## Starting an episode from the browser

The **Series** tab is the same shelf again for the **series library**, with
one floor more. A series is not something that can be put on — an episode is — so a
tap on a poster does not start anything: the wall gives way to that show's
episodes, in the order they were made and each season folded away under its own
heading. A tap opens a season, a tap on one of its episodes starts it. The way
back out sits at the top of the card, where it is one tap away however far down
a show you have scrolled.

The seasons arrive folded, all of them: a series that has run for nine years is
several hundred rows, and a list that opened on all of them would open in the
middle of season one. Folded, a whole show is a dozen lines — which season, how
many episodes are in it and how long they run altogether — and it costs
nothing to draw, because a still inside a folded season is never fetched.

Each poster carries the number of episodes still unwatched in the corner a
watched film wears its tick in — the one number a shelf of series is scanned
for — and a show seen right through wears the tick instead. What **IMDb** made of it — or TMDb where IMDb has nothing to say — sits in the opposite corner of the poster, and is left off entirely where neither house has an opinion.

An episode half-watched carries the same bar along the bottom of its still and
is resumed where it was, and each row says how long that episode runs beside
the number it is.

The episodes of a show are read when that show is opened and not before: a
house with ninety series in it would otherwise be sent every episode of all of
them to draw a wall of ninety posters. What is read is then held beside the
shelf and dropped by the same notification, so a freshly scanned episode
appears without anything being restarted.

The series card arrives folded for the same reason the film card does, and
remembers per device how it was left. It has a setting of its own —
**Settings → Dashboard → Show the series library** — so a box can offer the
films and not the series, or the other way round.

## Switching VS10 from the browser

With **Allow VS10 switching from the dashboard** on (the default), the page
shows the output modes that apply to the playing source — the same set the
on-screen VS10 dialog offers, SDR sources included — and a tap applies one.
The switch is handed to the add-on's own `run_mode` entry point, so it takes
exactly the path a keymap shortcut takes, native VS10 actions included.

A switch takes a few seconds, and the buttons are not queued up behind it: a
tap that arrives while one is running replaces any tap still waiting, so three
quick taps end in the mode tapped last rather than in three switches in a row.

**HDR10+** and **HLG** are the two sources with no modes: neither is a VS10
input, so the driver has no group for either and the on-screen dialog draws
none — both are left with the player-process button alone. The dashboard
follows, and hides the whole VS10 card — output line included — for the length
of an HDR10+ or HLG stream. HDR10 keeps its three.

A **Dolby Vision title with an HDR10+ track** is the third: it reads as Dolby
Vision, because the RPU is what it is, but the driver does not take the Dolby
Vision group's modes while the ST 2094-40 payload rides along with it. Both the
dialog and the dashboard leave that hybrid grade with no modes rather than
offer a switch that does nothing. A stream whose HDR10+ Kodi has stripped for a
display that cannot show it keeps its modes: what was removed is no longer in
what the decoder is fed.

Switching **always** requires the access token, whatever reading is set to.

## The remote

The same setting turns on the transport row under the progress bar, in two
rows of its own: ten seconds, a minute and ten minutes either way on the first,
and on the second a chapter back, play and pause, quieter, mute, louder, stop
and a chapter on. Under them sits a picker each for the audio track and the
subtitles. Tapping the progress bar itself seeks there, and the arrow keys
nudge it ten seconds when it has the focus.

The volume steps rather than slides, and that is what lets it reach an
amplifier. Kodi's own volume is a number inside the Kodi process, and a box
whose CEC adapter is set to pass volume on leaves that number alone and sends
the amplifier a CEC command instead — from the input path, which an action
reaches and an absolute level never does. So the two steps go in as the actions
a remote sends: a soundbar answers them wherever the remote's own volume keys
reach it, and Kodi's own mixer answers them everywhere else, with nothing to
configure here either way.

What that costs is the level itself. CEC carries "up", "down" and "mute" and
has no command for "set it to forty" — and the level Kodi does report is its
own mixer's, which on such a box sits still while the room gets louder. So no
figure is shown at all, and the three keys say what they do rather than where
they have got to.

Every one of them goes through Kodi's own JSON-RPC into the running player, and
the page only offers what the player actually reports — a file with one audio
track shows no audio picker, and on one with no chapters the two chapter keys
are dimmed rather than left to seek a minute instead. Like the VS10 buttons,
they need the access token, and with **Allow VS10 switching from the
dashboard** off the row is not drawn at all.

The remote sits on the live tab, one press away from every other tab in the
bar.

## Security

The dashboard is reachable by anything on the same network while it is on, so:

- It is **off by default** and has to be switched on deliberately.
- **Do not forward its port to the internet.** It is meant for a home network.
- The **access token** is required for every VS10 switch. Turn on **Require the
  token for reading too** if the network the box is on is shared — the page
  then asks for the token before it shows anything at all.
- **Generate a new token** replaces it and logs out every browser still holding
  the old one.
- A device that presents **ten different wrong tokens** within ten minutes is
  turned away for ten minutes, the right token included. A page still holding
  a token that has since been replaced does not count against it: that is the
  same wrong token again, and the page simply asks for the new one.
- Opened under the box's address or a name of the home network (`coreelec`,
  `coreelec.local`, `coreelec.fritz.box`, `….lan`, `….home` and the like), the
  readings need no token unless the setting above asks for one. Opened under
  any other name — a dynamic DNS name, say — the page asks for the token before
  it shows anything. That is also what stops a web page elsewhere from reading
  the dashboard through the browser of somebody at home (DNS rebinding).
- The page may not be shown inside another site's frame, and it loads and runs
  nothing but its own files (Content Security Policy).
- The file name obeys the overlay's own *Show file name* setting: with it off,
  the path is not sent to the browser either.
- Only a fixed set of routes is served — no path is ever resolved against the
  filesystem.
- One device can hold at most sixteen connections to the dashboard, and all
  of them together forty-eight; a browser opens six at most, so this only ever
  turns away something that is not one.

Leave port 8080 alone; Kodi's own web server usually has it. 8099 is the
default here.
