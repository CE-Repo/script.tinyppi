// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 U3knOwn

"use strict";

/* ===========================================================================
   What a title's details page is drawn from: its facts and its cast, the
   titles it leads on to, and its ratings and awards as shields.

   Nothing here asks for a mount point, so it is there on every page.
   js/live-panels.js hands these out through TinyPPI.panels (facts, cast,
   related, shields, ratingGroups), and asks ratingBadges itself whether a
   snapshot says anything a details page could show; js/marking.js draws the
   page.  The styling is in live-panels.css.

   Loaded after core.js, whose strings (TinyPPI.T) the shields read, and
   before js/live-panels.js.
=========================================================================== */

window.TinyPPIDetails = (function () {

  /* How far, in pixels, a mouse may move on a row of cards and still click. */
  const DRAG_SLOP = 5;

  /* --- a title's facts and cast ----------------------------------------

     Drawn on a title's details page (see showDetails in js/marking.js), as
     the app draws them: each fact its
     name, quieter and small, over the names; and the cast under its
     heading as a row of cards -- a large square portrait or a figure on a colour of its own, the name on two
     lines and who they played on one, held open where they are not
     filled so every card stands the same height -- with an ellipsis where
     the library holds more. */

  /* A film's facts from TMDb (see _film_facts in web/library/details.py)
     follow the names: when it first ran in cinemas and where ("(DE)"), and
     what it cost and what it took on one line -- "Budget/Box office" over "$165M/$402M",
     or whichever of the two is known -- in the reader's own way of writing
     a day and a sum of dollars. */
  function factNodes(credits, T) {
    const money = [[T.budget, credits.budget], [T.revenue, credits.revenue]]
      .filter(([, amount]) => amount > 0);
    const made = credits.revenue - credits.budget;
    const rows = [
      [T.genre, credits.genres], [T.studio, credits.studios], [T.country, credits.countries],
      [T.cinema, credits.cinema && [cinemaDay(credits.cinema) +
        (credits.cinema_country ? " (" + credits.cinema_country + ")" : "")]],
      [money.map(([heading]) => heading).join("/"),
       [money.map(([, amount]) => dollars(amount)).join("/")].filter(Boolean)],
      /* What it took less what it cost, where both are known: its profit,
         or what it lost under that name. */
      [made < 0 ? T.loss : T.profit, money.length === 2 && made !== 0 && [dollars(Math.abs(made))]],
      ...showFacts(credits, T)
    ];
    const nodes = [];
    for (const [heading, names] of rows) {
      if (!names || !names.length) continue;
      const fact = document.createElement("div");
      fact.className = "fact";
      const term = document.createElement("dt");
      term.textContent = heading;
      const value = document.createElement("dd");
      value.textContent = names.join(", ");
      fact.append(term, value);
      nodes.push(fact);
    }
    return nodes;
  }

  /* A show's run on TMDb (see _show_state in web/library/details.py): its
     state, who airs it, how many seasons and episodes there are in all --
     "Seasons/Episodes" over "5/62", where TMDb knows both -- and the next
     episode to air and the last aired, "S03E01 · Its title · 16 Jan 2027". */
  function showFacts(credits, T) {
    const sized = credits.tmdb_seasons > 0 && credits.tmdb_episodes > 0;
    return [
      [T.status, credits.status && [T["status_" + credits.status] || credits.status]],
      [T.network, credits.networks],
      [T.seasons_episodes, sized && [credits.tmdb_seasons + "/" + credits.tmdb_episodes]],
      [T.next_episode, credits.next_episode && [airing(credits.next_episode)]],
      [T.last_episode, credits.last_episode && [airing(credits.last_episode)]]
    ];
  }

  function airing(episode) {
    const code = "S" + String(episode.season).padStart(2, "0") +
      "E" + String(episode.episode).padStart(2, "0");
    return [code, episode.title, episode.date && cinemaDay(episode.date)]
      .filter(Boolean).join(" \u00b7 ");
  }

  /* "2021-09-16" as the reader writes a day; the day itself where it is no
     day at all. */
  function cinemaDay(day) {
    const date = new Date(day + "T00:00:00");
    return isNaN(date) ? day : date.toLocaleDateString(undefined, { dateStyle: "medium" });
  }

  /* Whole US dollars, short: "165 Mio. $", "$165M". */
  function dollars(amount) {
    return new Intl.NumberFormat(undefined, {
      style: "currency", currency: "USD", notation: "compact", maximumSignificantDigits: 3
    }).format(amount);
  }

  /* The colours a person without a portrait stands on, two to a gradient,
     the app's own (see PLACEHOLDER_COLOURS in the app's DetailsDialog.kt). */
  const PLACEHOLDER_COLOURS = [
    ["#1D3557", "#E63946"], ["#0B3D2E", "#3CA87A"], ["#2B1055", "#D53369"],
    ["#3A1C08", "#F4A259"], ["#0F2027", "#2C7A99"], ["#42275A", "#B06AB3"],
    ["#141E30", "#4A7AB0"], ["#5C2A09", "#E0B050"], ["#1F1C2C", "#928DAB"],
    ["#093028", "#3CA87A"], ["#3E0E12", "#C0392B"], ["#16222A", "#4A8BA3"]
  ];

  /* Each person always on the same pair, picked by their name the way the
     app picks it (Java's String.hashCode), so the app and the page agree. */
  function placeholder(name) {
    let hash = 0;
    for (let i = 0; i < name.length; i += 1) hash = (Math.imul(31, hash) + name.charCodeAt(i)) | 0;
    const count = PLACEHOLDER_COLOURS.length;
    const [from, to] = PLACEHOLDER_COLOURS[((hash % count) + count) % count];
    return "linear-gradient(135deg, " + from + ", " + to + ")";
  }

  /* A head and shoulders in pale outline, the same shape at any size. */
  function personFigure() {
    const NS = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(NS, "svg");
    svg.setAttribute("class", "figure");
    svg.setAttribute("viewBox", "0 0 300 300");
    const head = document.createElementNS(NS, "circle");
    head.setAttribute("cx", "150");
    head.setAttribute("cy", "118");
    head.setAttribute("r", "58");
    const shoulders = document.createElementNS(NS, "ellipse");
    shoulders.setAttribute("cx", "150");
    shoulders.setAttribute("cy", "290");
    shoulders.setAttribute("rx", "105");
    shoulders.setAttribute("ry", "92");
    svg.append(head, shoulders);
    return svg;
  }

  /* A person's page on TMDb, with everything they have made: by their id
     where TMDb's credits of the title named them (see web/tmdb.py), and
     otherwise TMDb's search for their name. */
  function personPage(person) {
    return person.tmdb > 0
      ? "https://www.themoviedb.org/person/" + encodeURIComponent(person.tmdb)
      : "https://www.themoviedb.org/search/person?query=" + encodeURIComponent(person.name);
  }

  function castParts(credits, T) {
    /* Kodi's directors and writers by their codes, everyone else TMDb names
       under their jobs as the add-on words them (see _more_crew in
       web/library/details.py). */
    const codes = { director: T.director, writer: T.writer };
    const crew = credits.crew ? credits.crew.map((person) => ({
      ...person, role: codes[person.role] || person.role
    })) : [
      ...(credits.directors || []).map((name) => ({ name, role: T.director })),
      ...(credits.writers || []).map((name) => ({ name, role: T.writer }))
    ];
    return [
      ...castCards(credits, T.cast),
      ...castCards({ cast: crew }, T.crew)
    ];
  }

  function castCards(credits, title) {
    const cast = credits.cast || [];
    if (!cast.length) return [];
    /* How many there are, beside the heading: "Cast (24)", "(20+)" where
       the library holds more than the row shows. */
    const heading = document.createElement("h4");
    heading.className = "casthead";
    const count = document.createElement("span");
    count.className = "count";
    count.textContent = " (" + cast.length + (credits.cast_more ? "+" : "") + ")";
    heading.append(title, count);
    const row = document.createElement("ul");
    row.className = "castrow";
    for (const person of cast) {
      const item = document.createElement("li");
      const initial = document.createElement("span");
      initial.className = "initial";
      initial.setAttribute("aria-hidden", "true");
      /* Under the portrait, and in its place where there is none or it
         cannot be read: a figure on a colour of the person's own. */
      initial.style.background = placeholder(person.name);
      initial.append(personFigure());
      if (person.thumbnail) {
        const photo = document.createElement("img");
        photo.alt = "";
        photo.loading = "lazy";
        photo.src = "/api/art?kind=thumb&portrait=" + encodeURIComponent(person.thumbnail) +
          "&v=" + encodeURIComponent(person.thumbnail);
        photo.addEventListener("error", () => photo.remove(), { once: true });
        initial.append(photo);
      }
      const name = document.createElement("strong");
      name.textContent = person.name;
      const role = document.createElement("span");
      role.className = "role";
      role.textContent = person.role || "";
      const text = document.createElement("div");
      text.className = "casttext";
      text.append(name, role);
      /* The card is the way to the person's page on TMDb. */
      const link = document.createElement("a");
      link.className = "castlink";
      link.href = personPage(person);
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.draggable = false;
      link.append(initial, text);
      item.append(link);
      row.append(item);
    }
    if (credits.cast_more) {
      const more = document.createElement("li");
      more.className = "more";
      more.textContent = "\u2026";
      row.append(more);
    }
    mouseScroll(row);
    return [heading, row];
  }

  /* Where a title's page leads on to (see _collection and _recommended in
     web/library/details.py): the film series it is part of, under the
     series' name, and the titles of the library TMDb recommends after it --
     each a poster card with its name and year, as the cast's portraits are.
     A title the library holds opens its own page (*open*, see openRelated
     in js/marking.js); one it does not, its page on TMDb.  The title the
     page is about stands in its series, marked, and leads nowhere. */
  function relatedParts(found, T, open) {
    const collection = found.collection;
    return [
      ...relatedRow(collection ? collection.name : "", collection ? collection.parts : [], T, open),
      ...relatedRow(T.recommended, found.recommended || [], T, open)
    ];
  }

  function relatedRow(title, titles, T, open) {
    if (!titles.length) return [];
    const heading = document.createElement("h4");
    heading.className = "casthead";
    const count = document.createElement("span");
    count.className = "count";
    count.textContent = " (" + titles.length + ")";
    heading.append(title, count);
    const row = document.createElement("ul");
    row.className = "castrow posterrow";
    for (const item of titles) {
      const entry = document.createElement("li");
      entry.append(relatedCard(item, T, open));
      row.append(entry);
    }
    mouseScroll(row);
    return [heading, row];
  }

  function relatedCard(item, T, open) {
    const picture = document.createElement("span");
    picture.className = "initial";
    picture.setAttribute("aria-hidden", "true");
    picture.style.background = placeholder(item.title);
    const address = relatedPoster(item);
    if (address) {
      const poster = document.createElement("img");
      poster.alt = "";
      poster.loading = "lazy";
      poster.src = address;
      poster.addEventListener("error", () => poster.remove(), { once: true });
      picture.append(poster);
    }
    const mark = item.current ? T.this_film : item.id ? "" : "TMDb";
    if (mark) {
      const badge = document.createElement("span");
      badge.className = "posterbadge";
      badge.textContent = mark;
      picture.append(badge);
    }
    const name = document.createElement("strong");
    name.textContent = item.title;
    const year = document.createElement("span");
    year.className = "role";
    year.textContent = item.year ? String(item.year) : "";
    const text = document.createElement("div");
    text.className = "casttext";
    text.append(name, year);
    let card;
    if (item.current) {
      card = document.createElement("div");
      card.className = "castlink current";
      card.setAttribute("aria-current", "page");
    } else if (item.id) {
      card = document.createElement("button");
      card.type = "button";
      card.className = "castlink";
      card.addEventListener("click", (event) => {
        if (!event.defaultPrevented) open(item);
      });
    } else {
      card = document.createElement("a");
      card.className = "castlink";
      card.href = "https://www.themoviedb.org/" + (item.kind === "tvshow" ? "tv/" : "movie/") +
        encodeURIComponent(item.tmdb);
      card.target = "_blank";
      card.rel = "noopener noreferrer";
      card.title = T.on_tmdb;
      card.draggable = false;
    }
    card.append(picture, text);
    return card;
  }

  /* A related title's poster: the library's own through its id, else
     TMDb's through the add-on (see portrait_path in
     web/library/details.py); "" where there is neither. */
  function relatedPoster(item) {
    if (item.id && item.poster) {
      return "/api/art?kind=poster&" + (item.kind === "tvshow" ? "tvshowid=" : "movieid=") +
        encodeURIComponent(item.id) + "&v=" + encodeURIComponent(item.poster);
    }
    if (!item.id && item.portrait) {
      return "/api/art?kind=poster&portrait=" + encodeURIComponent(item.portrait) +
        "&v=" + encodeURIComponent(item.portrait);
    }
    return "";
  }

  /* With no scrollbar to take hold of, a mouse drags the row sideways the
     way a finger does.  The wheel is left to the page.  A drag that moved
     the row is no click on the card it ended on. */
  function mouseScroll(row) {
    let drag = null;
    let dragged = false;
    row.addEventListener("pointerdown", (event) => {
      dragged = false;
      if (event.pointerType !== "mouse" || event.button !== 0) return;
      drag = { x: event.clientX, left: row.scrollLeft };
      row.classList.add("dragging");
    });
    row.addEventListener("pointermove", (event) => {
      if (!drag) return;
      if (Math.abs(event.clientX - drag.x) > DRAG_SLOP) dragged = true;
      row.scrollLeft = drag.left - (event.clientX - drag.x);
    });
    row.addEventListener("click", (event) => {
      if (dragged) event.preventDefault();
    }, true);
    for (const type of ["pointerup", "pointerleave", "pointercancel"]) {
      row.addEventListener(type, () => {
        drag = null;
        row.classList.remove("dragging");
      });
    }
  }

  /* What a rating's mark is drawn from, and what a screen reader calls the
     house it is from: brand names, the same in every language.  The marks
     are the add-on's own drawings in each house's colours (see
     tools/gen_rating_marks.py); a source none of these names -- an NFO may
     carry any -- wears a plain circle with its first letter instead. */
  const RATING_SOURCES = {
    imdb: "IMDb", tmdb: "TMDb", trakt: "Trakt", tvdb: "TVDB", letterboxd: "Letterboxd",
    metacritic: "Metacritic", metacriticuser: "Metacritic User Score",
    rottentomatoes: "Rotten Tomatoes", popcorn: "Rotten Tomatoes Popcornmeter",
    rogerebert: "Roger Ebert", myanimelist: "MyAnimeList", mdblist: "MDBList"
  };
  /* What Rotten Tomatoes calls a rating it certified: its critics' and its
     audience's.  A certified one wears a seal on its mark's corner. */
  const CERTIFICATES = { rottentomatoes: "Certified Fresh", popcorn: "Verified Hot" };
  /* The big awards, as the add-on names them (see web/awards.py) and as
     they are called, untranslated. */
  const AWARDS = { oscar: "Oscar", globe: "Golden Globe", bafta: "BAFTA", emmy: "Emmy" };

  /* Every rating the library holds for the title (see web/ratings.py), in
     the order the badges stand: the age rating first -- who the film is for
     is asked before how good it is -- then a score for each source, the
     reader's own, the place in the IMDb Top 250 and the big awards.
     Each badge says in words what its mark shows, for a screen reader and
     under a pointer. */
  /* The board an age rating's mark is from, by its name ("fsk12" is the
     FSK's). */
  function boardOf(age) {
    if (age.startsWith("fsk")) return "FSK";
    if (age.startsWith("mpa_")) return "MPA";
    if (age.startsWith("tv_")) return "TV Parental Guidelines";
    return "BBFC";
  }

  function ratingBadges(media, T) {
    const badges = [];
    if (media.mpaa) {
      /* One the add-on could read for its board and level -- FSK, MPA, TV
         Parental Guidelines, BBFC -- is a shield like the others: the board
         on the level's colour, the level beside it ("FSK" | "12").  Any other
         is written as the scraper wrote it. */
      badges.push(media.age
        ? { kind: "age", mark: media.age, value: media.age_level || "", said: media.mpaa,
            named: boardOf(media.age) }
        : { kind: "age", value: media.mpaa, said: media.mpaa, named: media.mpaa });
    }
    for (const entry of media.ratings || []) {
      const source = entry.source || "";
      const name = RATING_SOURCES[source] ||
        source.charAt(0).toUpperCase() + source.slice(1);
      const value = entry.rating.toFixed(1);
      const certificate = (entry.certified && CERTIFICATES[source]) || "";
      const named = certificate ? name + " · " + certificate : name;
      badges.push({
        kind: "score",
        mark: RATING_SOURCES[source] ? source : "",
        letter: name.charAt(0),
        certified: Boolean(certificate),
        value, said: (named + " " + value).trim(), named
      });
    }
    if (media.userrating) {
      const value = String(media.userrating);
      badges.push({ kind: "mine", value, said: T.my_rating + " " + value, named: T.my_rating });
    }
    if (media.top250) {
      badges.push({ kind: "rank", mark: "top250", value: "#" + media.top250,
                    said: T.top250.replace("%s", media.top250), named: "IMDb Top 250" });
    }
    for (const award of media.awards || []) badges.push(awardBadge(award, T));
    return badges;
  }

  /* An award wears a drawing of what it hands out on its own ground, and
     beside it how many it won -- or, where it won none, how many it was
     nominated for, on a quieter shield (see .rating.nominee).  Under a
     pointer, what it won it for. */
  function awardBadge(award, T) {
    const name = AWARDS[award.award] || award.award;
    const won = award.won.length;
    const more = award.nominated ? T.award_nominated.replace("%s", award.nominated) : "";
    const value = String(won || award.nominated);
    const said = name + " " + (won ? T.award_won.replace("%s", won) : more);
    const named = won ? [name + ": " + award.won.join(", "), more].filter(Boolean).join(" · ")
      : name + " · " + more;
    return { kind: won ? "award" : "nominee", mark: "award_" + award.award, value, said, named };
  }

  /* The left of a shield: the drawing for its source on a ground of the
     house's own colour (see .rating .side in live-panels.css), the reader's
     heart on the accent, a letter for a source there is no drawing of -- or
     nothing, for an age rating that is no FSK one and is written out. */
  function ratingSide(badge) {
    const side = document.createElement("span");
    if (badge.mark) {
      /* An age rating's plate is the whole of the left, edge to edge. */
      side.className = "side " + badge.mark + (badge.kind === "age" ? " plate" : "");
      const image = document.createElement("img");
      /* As wide as it is drawn: the SVG says, and the CSS gives only the
         height (see .rating .mark). */
      image.className = "mark";
      image.src = "/ratings/" + badge.mark + ".svg";
      image.alt = "";
      side.append(image);
      if (badge.certified) {
        const seal = document.createElement("img");
        seal.className = "seal";
        seal.src = "/ratings/certified.svg";
        seal.alt = "";
        side.append(seal);
      }
      return side;
    }
    if (badge.kind === "age") return null;
    side.className = "side " + (badge.kind === "mine" ? "heart" : "letter");
    side.textContent = badge.letter || "";
    return side;
  }

  /* The shields of a library title's details (see showDetails in
     js/marking.js).  Each is a shield: the house on the left, what it gave
     on the right.  What a reader is told is the badge's sentence, kept off
     the screen; what is drawn is kept from the reader, who would otherwise
     hear "8.5 612,345" with nothing to say what either is. */
  let ratingTipId = 0;

  /* A popover stays visible above the dialog and its scrolling content.
     The native title still supplies the pointer's usual hover hint. */
  function ratingTip(node, text) {
    const tip = document.createElement("span");
    tip.className = "rating-tip";
    tip.id = "rating-tip-" + (++ratingTipId);
    tip.setAttribute("popover", "auto");
    tip.setAttribute("role", "tooltip");
    tip.textContent = text;
    node.tabIndex = 0;
    node.setAttribute("aria-describedby", tip.id);
    const show = () => {
      tip.showPopover();
      const badge = node.getBoundingClientRect();
      const box = tip.getBoundingClientRect();
      tip.style.left = Math.max(8, Math.min(badge.left, window.innerWidth - box.width - 8)) + "px";
      tip.style.top = Math.max(8, Math.min(badge.bottom + 8, window.innerHeight - box.height - 8)) + "px";
    };
    node.addEventListener("click", show);
    node.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" && event.key !== " ") return;
      event.preventDefault();
      show();
    });
    node.addEventListener("blur", () => tip.hidePopover());
    return tip;
  }

  function shieldNodes(badges) {
    const nodes = [];
    for (const badge of badges) {
      const node = document.createElement("span");
      node.className = "rating " + badge.kind;
      node.setAttribute("role", "listitem");
      /* Under a pointer, as after a tap, whose it is: what it gave stands
         on the shield already. */
      node.title = badge.named;
      const said = document.createElement("span");
      said.className = "said";
      said.textContent = badge.said;
      const look = document.createElement("span");
      look.className = "look";
      look.setAttribute("aria-hidden", "true");
      const side = ratingSide(badge);
      if (side) look.append(side);
      if (badge.value) {
        const figures = document.createElement("span");
        figures.className = "figures";
        const value = document.createElement("span");
        value.className = "value";
        value.textContent = badge.value;
        figures.append(value);
        look.append(figures);
      }
      node.append(said, look, ratingTip(node, badge.named));
      nodes.push(node);
    }
    return nodes;
  }

  /* A library title's ratings, as shields. */
  function shields(media) {
    return shieldNodes(ratingBadges(media, TinyPPI.T));
  }

  /* Each group owns its heading and accessible list. Empty groups disappear. */
  function ratingGroups(media) {
    const T = TinyPPI.T;
    const badges = ratingBadges(media, T);
    const awards = badges.filter((badge) => badge.kind === "award" || badge.kind === "nominee");
    const ratings = badges.filter((badge) => badge.kind !== "award" && badge.kind !== "nominee");
    const groups = [];
    for (const [title, entries] of [[T.ratings, ratings], [T.awards, awards]]) {
      if (!entries.length) continue;
      const group = document.createElement("section");
      group.className = "ratinggroup";
      const heading = document.createElement("h4");
      heading.textContent = title;
      const row = document.createElement("div");
      row.className = "ratings";
      row.setAttribute("role", "list");
      row.setAttribute("aria-label", title);
      row.append(...shieldNodes(entries));
      group.append(heading, row);
      if (entries.some((badge) => badge.kind === "nominee")) {
        const hint = document.createElement("p");
        hint.className = "ratingnote";
        hint.textContent = T.award_hint;
        group.append(hint);
      }
      groups.push(group);
    }
    return groups;
  }

  return { factNodes, castParts, relatedParts, ratingBadges, shields, ratingGroups };

})();
