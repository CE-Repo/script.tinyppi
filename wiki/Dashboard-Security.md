# Dashboard Security

While the [web dashboard](Web-Dashboard) is on, it can be reached by anything
on the same network. This page explains how it is protected and how to set it
up for your network.

---

## Recommendations at a glance

| Your network | Recommended settings |
|---|---|
| **Home network, only your own devices** | Defaults are fine: token for control, open reading. |
| **Shared network** (flat share, dorm, office, guest Wi-Fi) | Turn on **Require the token for reading too**. |
| **Read-only use** (no remote, no switching) | Turn off **Allow VS10 switching from the dashboard**. |
| **Not used** | Leave **Enable web dashboard** off (the default). |

And always:

- **Never forward the dashboard's port to the internet.** If you need remote
  access, use a VPN into your home network.
- Leave port 8080 to Kodi's own web server; the dashboard uses 8099 by default.

---

## The access token

- The token is an **8-character code** from an alphabet without look-alike
  characters (`ABCDEFGHJKLMNPQRSTUVWXYZ23456789` — no `0/O`, `1/I/L`), so it can
  be read off the TV and typed on a phone.
- It is generated automatically the first time it is needed, and can be shown
  with **Settings → Dashboard → Show address and token**. You can also type
  your own into **Access token**.
- The browser keeps it per device after you enter it once (on the page's
  **Settings** tab, which shows it with all but the last two characters hidden).
- **Generate a new token** replaces it immediately. Every browser holding the
  old token is asked for the new one.
- **The token never appears in an address**, where it would end up in browser
  histories and logs. The page sends it in the `X-TinyPPI-Token` request
  header. For the live stream and the pictures, which a browser cannot send
  a header with, the page trades the token for a **read session cookie**
  (`POST /api/session`): `HttpOnly`, so no script can read it, and
  `SameSite=Strict`, so no other site's page can use it. It is valid for
  reading only, ends with the browser session, and ends for everyone when the
  dashboard's server restarts — a new token included.

### What needs the token

| Action | Token needed |
|---|---|
| Switching a VS10 mode | **always** |
| Remote (play/pause, seek, volume, tracks, chapters, stop) | **always** |
| Starting a film or episode, marking watched/unwatched, clearing a resume point | **always** |
| Reading the readings, history, library and artwork | only when **Require the token for reading too** is on, the device is **not on the home network**, **or** the page was opened under an untrusted host name (see below) |
| Start-up information (version, feature flags, UI strings) | never — it contains no player state |

All write actions additionally require **Allow VS10 switching from the
dashboard**; with it off the server answers them with *403 control disabled*.

---

## Reading without the token: home network only

The dashboard listens on **IPv6 and IPv4** (where IPv6 is unavailable, on
IPv4 only). Over IPv6 a box can have addresses the internet can reach, so
reading without the token is limited to clients on the **home network**:

- loopback, private (`192.168.x.x`, `10.x.x.x`, `172.16–31.x.x`, IPv6 ULA
  `fd00::/8`) and link-local addresses,
- IPv6 addresses in one of the **box's own IPv6 networks** — home devices
  often reach the box over global addresses from the same prefix. The box
  re-reads its networks once a minute, since a router may hand out a new
  prefix at any time.

Any other client — over a global IPv6 address the router lets through, or a
forwarded port — is asked for the token first, whatever **Require the token
for reading too** says.

---

## Guessing lockout

An address that presents **ten different wrong tokens within ten minutes**
is turned away for **ten minutes** — the right token included. It gets
*429 Too Many Requests* with a `Retry-After` header, and the log records:

```
TinyPPI [web]: 192.168.1.57 presented 10 wrong tokens; turning it away for 10 minutes
```

- Only **different** wrong tokens count. A page still holding a token that has
  since been replaced keeps sending that same old token; it is simply asked
  for the new one and is never locked out for it.
- An empty token is not counted as a guess.
- Only a short hash of each wrong token is kept in memory — never the guess
  itself — and nothing is written to disk.
- **At home every address counts on its own**, so one device locking itself
  out does not lock out the house.
- **Beyond the home network an IPv6 client counts per /64** — the block one
  device can draw new addresses from (privacy extensions) — so it cannot
  dodge the lockout by switching addresses.
- Both tables (open guess windows and lockouts) hold at most 256 addresses
  each, so many senders cannot fill the box's memory.

With 32 symbols and 8 positions there are about 10¹² tokens; at ten guesses per
ten minutes, guessing is hopeless.

---

## Trusted host names (DNS rebinding protection)

With **Require the token for reading too** off, a malicious web page could, in
theory, point a host name of its own at your box's IP address and read the
dashboard through the browser of somebody at home (a *DNS rebinding* attack).
The browser would still send the attacker's domain in the `Host` header, so
the dashboard checks it.

Reading **without** a token is only allowed when the page was opened as:

- an **IP address** (`http://192.168.1.20:8099/`, IPv6 included),
- a **single-label name** (`http://coreelec:8099/`),
- the **box's own host name**,
- a name ending in a **home-network suffix**: `.local`, `.localhost`,
  `.localdomain`, `.lan`, `.home`, `.home.arpa`, `.internal`, `.intranet`,
  `.corp`, `.private`, `.fritz.box`, `.speedport.ip`.

Under any other name — a dynamic-DNS name, for example — the page asks for the
token before it shows anything.

---

## Headers and content policy

Every response carries:

| Header | Purpose |
|---|---|
| `X-Content-Type-Options: nosniff` | No content-type guessing. |
| `X-Frame-Options: DENY` | The page may not be shown inside another site's frame (clickjacking). |
| `Referrer-Policy: no-referrer` | No address of the dashboard ever leaves the page in a referrer. |
| `Cache-Control: no-store` | Live player state is never cached (static files and artwork set their own policy). |

The page itself is served with a strict **Content Security Policy**: it loads
and runs nothing but its own files and API — no inline scripts or styles, no
other origin, no plugins, no framing. An injected script (for example in a
film title) has nowhere to run.

---

## Other safeguards

- **Fixed routes.** Only a fixed table of paths is served; no request path is
  ever resolved against the filesystem.
- **The MDBList API key stays on the box.** It goes to mdblist.com only,
  with the id of the film being asked for, and never to a page; leave it
  empty and nothing is sent with it (see
  [Ratings from MDBList](Web-Dashboard#ratings-from-mdblist)).
- **WhatsOn gets a film's id only.** The playing film's IMDb or TMDb id goes
  to whatson-api.onrender.com, once per film, without a key and nothing else;
  turn it off under **Rotten Tomatoes from WhatsOn** (see
  [Rotten Tomatoes from WhatsOn](Web-Dashboard#rotten-tomatoes-from-whatson)).
- **File names stay private.** The file path obeys the overlay's **Show file
  name** setting: with it off, the path is not sent to the browser either.
- **Bounded connections.** One address may hold at most **16** connections
  (beyond the home network one IPv6 /64) and all of them together **48**; at
  most **6** live streams run at once. A browser opens six connections per
  host at most, so the caps only ever turn away something that is not a
  browser.
- **Checked artwork tags.** The `v` tag of an artwork URL goes into the
  `ETag` header only if it is a plain hex tag, so no crafted value can add
  headers to the answer.
- **Small requests only.** Request bodies are limited to 4 KB of JSON.
- **Bounded timeouts.** Idle connections are closed after 15 s, and a stream
  that stops reading is dropped after 4 s, so nothing can hold the server or
  Kodi's shutdown.
- **Masked logs.** Debug logs get posted to forums, so nothing secret is
  logged: a token in a request line (from an older page or a hand-typed
  address — the server no longer reads it from there) is masked as
  `token=***`, and share credentials in paths (`smb://user:password@nas/…`)
  are written as `smb://***@nas/…`.
- **Off by default.** The server only runs while **Enable web dashboard** is
  on, and stops cleanly when Kodi shuts down.

---

## License note

TinyPPI is licensed under the AGPL. If you modify TinyPPI and let other people
reach your modified dashboard over a network, section 13 of the AGPL requires
you to offer them the source of your modified version. See
[License and Credits](License-and-Credits).
