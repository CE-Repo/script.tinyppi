# Dashboard HTTP API

The [web dashboard](Web-Dashboard) is a static page talking to a small JSON API
on the same port. The API can also be used directly — from a script, a
home-automation system or `curl` — for example to read the current HDR format
or to switch VS10 modes.

> The API is an internal interface of the dashboard. It is stable in practice
> but not versioned; check this page after updates.

Base URL: `http://<box-ip>:<port>` (port **8099** by default). The server
listens on IPv6 and IPv4, e.g. `http://[fd00::20]:8099`.

---

## Authentication

Send the access token in the **`X-TinyPPI-Token`** header. Only the header
counts: a `token` query parameter is **ignored** since 2.15.1, because an
address ends up in histories and logs.

```bash
curl -H 'X-TinyPPI-Token: ABCD2345' http://192.168.1.20:8099/api/state
```

A browser cannot send a header with an `EventSource` or an `<img>`, so the
page trades the token for a **read session cookie** first (see
[`POST /api/session`](#post-apisession--read-session)). The cookie counts as
the token for the read routes only. Scripts simply send the header on every
request.

| Route type | Token required |
|---|---|
| `GET /api/hello` | never |
| Other `GET` routes ("readers") | only with **Require the token for reading too** on, from a client beyond the home network (see [Dashboard Security](Dashboard-Security#reading-without-the-token-home-network-only)), or under an untrusted `Host` name (see [Dashboard Security](Dashboard-Security#trusted-host-names-dns-rebinding-protection)); the read session cookie counts as the token |
| `POST /api/session` | **always** (the header), but not **Allow VS10 switching** |
| All other `POST` routes ("writers") | **always** (the header — the cookie does not count), and **Allow VS10 switching from the dashboard** must be on |

Errors are JSON: `{"error": "<message>"}`.

| Status | Body | Meaning |
|---|---|---|
| 400 | `bad body length`, `bad JSON`, `unknown mode`, `command failed`, `playback failed`, `update failed`, `watched required`, `no title named` | The request was not understood or the action failed. |
| 401 | `token required` | Missing or wrong token (in the header). |
| 403 | `control disabled` | A write with **Allow VS10 switching** off. |
| 403 | `library disabled` | The film/series library is switched off (or control is off). |
| 404 | `no such route`, `no such artwork`, `no artwork`, `no such series`, `no such title` | Unknown path, or nothing to return. |
| 429 | `too many wrong tokens` (+ `retry_ms`, `Retry-After`) | The address (beyond the home network: its IPv6 /64) is locked out for guessing. |
| 503 | `too many streams` / `shutting down` (+ `retry_ms`) | All six stream slots are taken, or Kodi is shutting down. |
| 503 | `library unavailable` | The video database could not be read. |

---

## Read routes (`GET`)

### `GET /api/hello`

Start-up information for the page. No token, no player state.

```json
{
  "name": "TinyPPI",
  "version": "2.15.1",
  "auth_read": false,
  "control": true,
  "library": true,
  "series": true,
  "interval_ms": 200,
  "strings": { "...": "localized UI strings" }
}
```

| Field | Meaning |
|---|---|
| `auth_read` | Whether *this request* would need the token to read (setting, client beyond the home network, or untrusted host). |
| `control` | **Allow VS10 switching from the dashboard**. |
| `library` / `series` | Whether the film / series shelves are offered (each needs its setting **and** `control`), and with them a film's / an episode's or show's details (`/api/details`). The dashboard and the TinyPPI app hide a shelf that is off, and the overview's key to the details of a title on it. |
| `interval_ms` | How often a watched snapshot is rebuilt (200 ms). |

### `GET /api/state`

The current snapshot, once. Use it for polling when you don't want a stream.

While something plays the snapshot contains, among others:

| Key | Content |
|---|---|
| `seq` | Snapshot sequence number. |
| `playing`, `paused` | Player state. |
| `title`, `filename` | Title; the file name only when **Show file name** is on. |
| `hdr_type` | Source format: `""` (SDR), `hdr10`, `hdr10plus`, `hlg`, `dolbyvision`. |
| `effective` | The type the overlay layout follows (differs during VS10 conversion). |
| `output_type` | The format actually being output. |
| `time`, `duration`, `finish` | Position, duration, and the clock time it ends at (box's regional format). |
| `metrics` | Cache, frame rate and other figures for the metric tiles. |
| `groups` | The overlay's rows as cards: `[{id, title, rows: [{id, label, value, detail}]}]`. Card ids: `video`, `processing`, `audio`, `system`, `hdr`, `dv`, `metadata`. |
| `metadata` | The Dolby Vision metadata list (only for Dolby Vision, with **Show the Dolby Vision metadata view** on). |
| `vs10` | `{"options": [{"mode", "label"}], "output": "…"}` — the switchable modes for this source and the current output. |
| `art` | Tags of the playing title's artwork (used in `/api/art` URLs). |
| `media` | `year`, `genre` (its first two), `show`, `season`, `episode`; and for the overview: `tagline`, `plot` (markup stripped, line breaks kept), `ratings` (`[{source, rating, votes}]`, each out of ten, the known sources first), `mpaa` (the age rating as written), `age` and `age_level` (its mark, e.g. `fsk12`, and level, e.g. `12`; empty where it has no mark), `userrating` (1–10, 0 for none), `top250` (0 for none), `genres` (every one), `directors` (every one), `writers` (every one), `cast` (its first 20) with `cast_more` and `roles` (who each played, `""` where the library names nobody; read off `VideoPlayer.CastAndRole` in Kodi's language), `studios` (the first), and `item` — which library title it is, `{"kind": "movie"|"episode", "id"}`, for its details to be opened by (`/api/details`); `{}` for a file the library does not know. |
| `controls` | What the remote can offer: audio tracks, subtitles, chapters, the audio and subtitle offsets (`audio_delay`, `subtitle_delay`, seconds; `null` where Kodi reports none) … |
| `session` | `{seq, switches, warnings}` — when `seq` changes, re-read `/api/history`. |
| `library` | The library version; when it changes, re-read the shelves. |
| `control` | Same as in `/api/hello`. |
| `streams_full` | Whether a stream request would currently be refused. |

With nothing playing: `playing: false`, empty `groups`/`metadata`, plus `last`
— the summary of the title that ended within the last ten minutes
(`title`, `position`, `ago`, `switches`, `warnings`, `peak`, `events`).

Example — read the source format with `jq`:

```bash
curl -s http://192.168.1.20:8099/api/state | jq -r '.hdr_type, .output_type'
```

### `GET /api/stream`

A **Server-Sent Events** stream of snapshots. One stream slot of six is held
while connected.

| Event | Data |
|---|---|
| `state` | The first frame: a complete snapshot (as `/api/state`). |
| `delta` | Every following frame: only what changed (see below). |
| `bye` | `{"retry_ms": 20000}` — the server is stopping; wait before reconnecting. |
| `: ping` *(comment)* | Heartbeat every 15 s on an idle stream. |

A **delta frame** has the shape:

```json
{
  "seq": 1234,
  "set": { "time": "01:12:45", "metrics": { "...": "..." } },
  "del": ["some_key"],
  "groups":   { "rows": [["<row id>", "<value>", "<detail>"]] },
  "metadata": { "rows": [[17, "<value or cells>"]] }
}
```

- `set` — top-level keys whose value changed, sent whole.
- `del` — top-level keys that disappeared.
- `groups` / `metadata` — either `{"rows": [...]}` with only the changed rows
  (while the card/row layout is unchanged), or the complete new list when the
  layout changed.

Frames come at most five times a second, and only when something moved.

```bash
curl -N -H 'X-TinyPPI-Token: ABCD2345' http://192.168.1.20:8099/api/stream
```

### `GET /api/history`

The chart and event history of the current (or just finished) title:

```json
{
  "now": 4380.2, "step": 1.0,
  "t": [0.0, 1.0, "..."], "max": [812.3, "..."], "avg": [96.1, "..."],
  "events": [{"t": 1203.4, "pos": "00:20:03", "kind": "audio", "...": "..."}],
  "seq": 7, "switches": 3
}
```

`t` is seconds since playback started; `max` / `avg` are L1 peak and average in
nits (null outside Dolby Vision). Event `kind`s: `vs10`, `mode`, `audio`,
`subtitle`, `fps`, `temperature`, `cpu`.

### `GET /api/library`

The film library: `{"movies": [...], "count": N, "tag": "…"}`. Each film:
`id`, `title`, `poster` (tag), and when known `year`, `duration` (seconds),
`watched`, `resume`, `rating`, `added`, `genres` (up to four), and — once
Kodi has read the file — `video` (`dv`, `hdr10plus`, `hdr10`, `hlg`, `sdr`),
for Dolby Vision its `dv_profile` as Kodi's scan found it (`5`, `7 FEL`,
`7 MEL`, `8.1`, `8.4`, …),
`resolution` (`2160p`, `1080p`, `720p`, `sd`) and `audio`, the first audio
track's codec family (`truehd`, `eac3`, `ac3`, `dtshd_ma`, `dtshd_hra`, `dts`,
`flac`, `pcm`, `aac`, `opus`, `mp3`, `vorbis`). Kodi's stream details carry no
Atmos or DTS:X flag, so the family is all a filter can go by. The response has
an `ETag`; send it back as `If-None-Match` to get a cheap `304 Not Modified`.

### `GET /api/series`

The series library: `{"shows": [...], "count": N, "tag": "…"}`. Each show
carries its `genres` as a film does.

### `GET /api/episodes?tvshowid=<id>`

The episodes of one series: `{"tvshowid", "title", "episodes": [...], "count", "tag"}`.
`404 no such series` means the library changed; reload `/api/series`.

### `GET /api/continue`

Films and episodes stopped part-way, newest first (up to 30), and with the
series shelf on, the **next up** row: the next unwatched episode (specials
left out) of up to 15 shows being watched, the show watched last first —
An episode in `items` carries its show's `tvshowid`, which is how the page
offers the way to that show —
`{"items": [{"kind": "movie" | "episode", ...}], "next": [{"kind": "episode",
"id", "title", "tvshowid", "show", "poster", "thumb", "season", "episode",
"duration", "rating"}], "count", "tag"}`. An episode already in `items` is not
repeated in `next`.

### `GET /api/details?movieid=|tvshowid=|episodeid=<id>`

One title's details, read when it is opened: `kind`, `id`, `title`, the
`ratings` the snapshot's overview would show for the same title — the
library's, MDBList's over them and WhatsOn's Rotten Tomatoes ratings and
certificates (a film's answer is waited on for up to four seconds; one that
takes longer is there on the next read) — and where there are any `mpaa` with
its `age` mark and `age_level` (an episode's are its show's), `userrating`,
`top250` and `awards`; and where the library has them `plot`, `tagline`,
`premiered`, `year`, `duration`, `genres`, `directors`, `writers`, `studios`,
`countries`, the `cast` (each entry has `name`, `role` and an optional
`thumbnail`; the whole cast in billing order, `cast_more` always `false`) and the file's `video`,
`dv_profile`, `resolution` and `audio`, and the tags of its pictures for
`/api/art` — `poster` and `fanart` for a film or a series, `thumb` for an
episode. Every title has `watched` (a series once every episode is) and
`resume` (seconds, 0 for none), which the page's keys are drawn from. An
episode adds `show`, `tvshowid`, `season` and `episode`; a series its number
of `season`s. Each kind needs its shelf's setting and **Allow VS10 switching
from the dashboard** (`403 library disabled`); an unknown title is
`404 no such title`.

A cast member's optional `thumbnail` is an opaque portrait tag (16 hex
digits), not a source URL. It is present only when Kodi supplies a non-empty thumbnail path.
Request `/api/art?kind=thumb&portrait=<thumbnail>&v=<thumbnail>` to load it.
Clients should keep an initial or another placeholder if the field is absent
or the image request fails; older servers omit the field.

### `GET /api/art?kind=<kind>[&movieid=|&tvshowid=|&episodeid=<id>][&portrait=<tag>][&v=<tag>]`

Artwork: `kind` is `poster`, `fanart` or `thumb`. Without an id or `portrait`,
the playing title's artwork. With a `v` tag the answer is cacheable for a week
(`immutable`); the tag must be plain hex (as the snapshot and the lists give
it), anything else is ignored and the answer is not cached. Images are served
from Kodi's texture cache where possible.

For a cast portrait, use `kind=thumb&portrait=<tag>` with the optional `v` tag
set to the same value. The portrait tag comes from `/api/details`. The server
resolves only paths Kodi supplied while details were read; callers cannot
provide a file path or source URL. At most 4096 portrait paths are retained in
memory. An unknown or evicted tag, or an unreadable image, returns 404; reopen
the details to register its portraits again. Portraits use the same read
authorization and cache policy as other artwork.

---

## `POST /api/session` — read session

Trades the token for the read session cookie the page's stream and pictures
use. Needs the token in the header and a JSON body (`{}`); works with
**Allow VS10 switching** off.

```bash
curl -i -X POST -H 'X-TinyPPI-Token: ABCD2345' -H 'Content-Type: application/json' \
     -d '{}' http://192.168.1.20:8099/api/session
```

The answer is `{"ok": true}` with
`Set-Cookie: tinyppi_session=…; Path=/api/; HttpOnly; SameSite=Strict`. The
cookie is valid for the read routes only, ends with the browser session, and
ends for everyone when the dashboard's server restarts (a new token
included).

---

## Write routes (`POST`)

All take a JSON body (max 4 KB), need the token in the header and **Allow
VS10 switching**.

### `POST /api/mode` — switch VS10

```bash
curl -X POST -H 'X-TinyPPI-Token: ABCD2345' -H 'Content-Type: application/json' \
     -d '{"mode": "hdr10"}' http://192.168.1.20:8099/api/mode
```

Accepted modes are exactly the dashboard's buttons: `original_sdr`, `hdr10`,
`dv`, `original_hdr`, `sdr8`, `original_dv`. The call returns at once
(`{"ok": true, "mode": "hdr10"}`); the switch runs in the background, and a
newer request replaces one still waiting. For `sdr10` and `original_hlg` use
`RunScript(script.tinyppi,run_mode,…)` (see
[Launching and Keymaps](Launching-and-Keymaps)).

### `POST /api/command` — remote

Body: `{"action": "<action>", "value": <value>}`.

| Action | Value | Effect |
|---|---|---|
| `playpause` | — | Toggle pause. |
| `stop` | — | Stop playback. |
| `seek` | seconds, −3600 … 3600 | Relative seek. |
| `seek_percent` | 0 … 100 | Absolute seek (relative to the EPG event on live TV). |
| `volume_up` / `volume_down` / `mute` | — | Sent as remote actions (CEC-friendly). |
| `volume` | 0 … 100 | Absolute Kodi volume (kept for older clients). |
| `chapter_previous` / `chapter_next` | — | Chapter skip; fails without at least two chapters. |
| `audio` | stream index 0 … 64 | Select an audio track. |
| `subtitle` | index 0 … 64, or −1 | Select and enable a subtitle; −1 turns subtitles off. |
| `subtitles` | `true` / `false` | Show or hide the selected subtitle. |
| `audio_delay` | seconds, −10 … 10 | Set the audio offset (rounded to Kodi's 25 ms steps). |
| `subtitle_delay` | seconds, −60 … 60 | Set the subtitle offset, in Kodi's 100 ms steps; each step shows Kodi's own slider on the TV for a moment (there is no JSON-RPC method for it). One request moves at most 60 s; requests run one after another. |

```bash
curl -X POST -H 'X-TinyPPI-Token: ABCD2345' -H 'Content-Type: application/json' \
     -d '{"action": "seek", "value": 30}' http://192.168.1.20:8099/api/command
```

### `POST /api/play` — start a title

`{"movieid": 123}` or `{"episodeid": 456}`; add `"resume": false` to start from
the beginning (anything else resumes).

### `POST /api/watched` — mark watched / unwatched

`{"movieid": 123, "watched": true}` — or `tvshowid` (every episode) or
`episodeid`. `watched` must be a boolean.

### `POST /api/resume` — clear a resume point

`{"movieid": 123}` or `{"episodeid": 456}`.

---

## Static files

`/`, `/index.html`, `/metadata`, `/metadata.html`, `/manifest.webmanifest`,
`/icon.png`, `/fanart.png`, and the page's own `css/`, `js/`, `icons/` and
`ratings/` (the rating marks) files. They are served gzip-compressed (when the browser accepts it) with an
`ETag`, so a revisit is answered with `304`.
