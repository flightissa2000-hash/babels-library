/* CDs, TV & Movies: album shelves, series/seasons, posters, and a little player. */
window.Media = (() => {
  const fmtTime = (s) => { s = Math.max(0, Math.round(s || 0)); const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), x = s % 60; return (h ? h + ":" + String(m).padStart(2, "0") : m) + ":" + String(x).padStart(2, "0"); };
  const albumKey = (it) => `${(it.album_artist || (it.authors || [])[0] || "Unknown artist").toLowerCase()}|${(it.album || "Singles").toLowerCase()}`;

  function albums(items) {
    const map = new Map();
    for (const it of items.filter((i) => i.kind === "music")) {
      const k = albumKey(it);
      if (!map.has(k)) map.set(k, { key: k, title: it.album || "Singles", artist: it.album_artist || (it.authors || [])[0] || "Unknown artist", tracks: [], year: it.year, genre: it.genre });
      const a = map.get(k);
      a.tracks.push(it);
      a.year = a.year || it.year;
      a.genre = a.genre || it.genre;
      if (it.has_cover && !a.cover) a.cover = it;
      a.added = Math.max(a.added || 0, it.added_at || 0);
      a.opened = Math.max(a.opened || 0, it.opened_at || 0);
    }
    for (const a of map.values()) a.tracks.sort((x, y) => (x.disc || 1) - (y.disc || 1) || (x.track || 999) - (y.track || 999) || x.title.localeCompare(y.title));
    return [...map.values()];
  }

  function seriesList(items) {
    const map = new Map();
    for (const it of items.filter((i) => i.kind === "tv")) {
      const k = (it.series || "Unknown series").toLowerCase().replace(/\((?:19|20)\d\d\)|\b(?:19|20)\d\d\b/g, " ").replace(/[^a-z0-9]+/g, "") || "unknown";
      if (!map.has(k)) map.set(k, { key: k, title: it.series || "Unknown series", eps: [], genre: it.genre });
      const s = map.get(k);
      s.eps.push(it);
      if (it.has_cover && !s.cover) s.cover = it;
      s.genre = s.genre || it.genre;
      s.added = Math.max(s.added || 0, it.added_at || 0);
    }
    for (const s of map.values()) s.eps.sort((a, b) => (a.season || 0) - (b.season || 0) || (a.episode || 0) - (b.episode || 0));
    return [...map.values()];
  }

  const isDone = (e) => !!e.watched;
  const inProg = (e) => !e.watched && (e.progress || 0) > 0.02;
  const posterHTML = (it, title) => it && it.has_cover
    ? `<div class="cover poster-c"><img loading="lazy" alt="" src="/api/items/${it.id}/cover?v=${it.cover_v || it._cv || 0}"></div>`
    : `<div class="cover poster-c" style="--c:${colorFor(it || { id: title, title })}"><div class="gen-cover"><div class="t">${esc(title)}</div></div></div>`;
  const epCode = (e) => `S${e.season || 1} · E${e.episode ?? "?"}`;

  /* Shows and films you're partway through: resume a half-watched episode, or the next one after the last you finished. */
  function watchingList(items) {
    const out = [];
    for (const s of seriesList(items)) {
      const eps = s.eps;
      const half = eps.filter(inProg).sort((a, b) => (b.opened_at || 0) - (a.opened_at || 0))[0];
      let lastDone = -1;
      eps.forEach((e, i) => { if (isDone(e)) lastDone = i; });
      const next = half || (lastDone >= 0 ? eps.slice(lastDone + 1).find((e) => !isDone(e)) : null);
      if (!next) continue;
      const when = Math.max(...eps.map((e) => Math.max(e.opened_at || 0, e.watched_at || 0)));
      out.push({ type: "tv", s, ep: next, resume: next === half, when, done: eps.filter(isDone).length, total: eps.length });
    }
    for (const m of items.filter((i) => i.kind === "movie" && inProg(i))) out.push({ type: "movie", m, when: m.opened_at || 0 });
    return out.sort((a, b) => b.when - a.when);
  }
  function watchingSection(items) {
    const list = watchingList(items);
    if (!list.length) return "";
    return `<section class="group watching"><div class="group-head"><h2>${ransom("Currently watching")}</h2><span class="count">${list.length}</span></div>
      <div class="watch-row">${list.map((w) => {
        if (w.type === "movie") {
          const pct = Math.round((w.m.progress || 0) * 100);
          return `<div class="wcard"><button class="wc-art" data-read="${w.m.id}" title="Resume">${posterHTML(w.m, w.m.title)}<span class="wc-play">▶</span></button>
            <div class="wc-body"><b>${esc(w.m.title)}</b><span>${pct}% · ${fmtTime((w.m.duration || 0) * (1 - (w.m.progress || 0)))} left</span>
            <span class="wc-bar"><i style="width:${pct}%"></i></span><button class="btn sm primary" data-read="${w.m.id}">Resume</button></div></div>`;
        }
        const e = w.ep, pct = Math.round((e.progress || 0) * 100);
        return `<div class="wcard"><button class="wc-art" data-read="${e.id}" title="${w.resume ? "Resume" : "Play next episode"}">${posterHTML(w.s.cover, w.s.title)}<span class="wc-play">▶</span></button>
          <div class="wc-body"><b>${esc(w.s.title)}</b><span>${epCode(e)}${e.title && !/^Episode \d+$/.test(e.title) ? " · " + esc(e.title) : ""}</span>
          <span class="wc-bar" title="${w.done} of ${w.total} watched"><i style="width:${Math.round(100 * w.done / w.total)}%"></i></span>
          <span class="wc-sub">${w.done} of ${w.total} episodes watched</span>
          <span class="row"><button class="btn sm primary" data-read="${e.id}">${w.resume ? `Resume (${pct}%)` : "Next episode"}</button><button class="btn sm" data-series="${esc(w.s.key)}">Episodes</button></span></div></div>`;
      }).join("")}</div></section>`;
  }

  const disc = (cover, title) => `<div class="cd"><div class="cd-disc"></div><div class="cd-case">${cover ? `<img loading="lazy" alt="" src="/api/items/${cover.id}/cover?v=${cover.cover_v || cover._cv || 0}">` : `<div class="cd-blank"><span>${esc(title)}</span></div>`}</div></div>`;

  function groupBy(list, keyFn, order) {
    const m = new Map();
    for (const x of list) for (const k of [].concat(keyFn(x))) { if (!m.has(k)) m.set(k, []); m.get(k).push(x); }
    const g = [...m.entries()];
    g.sort(order || ((a, b) => a[0].localeCompare(b[0])));
    return g;
  }

  function render(items, gb) {
    const out = [];
    const kinds = new Set(items.map((i) => i.kind));
    if (kinds.has("music")) {
      // a jukebox: the window shows what's playing (with the controls), the albums are its selection strips
      let al = albums(items);
      al.sort((a, b) => a.artist.localeCompare(b.artist) || (parseInt(a.year) || 0) - (parseInt(b.year) || 0));
      const key = gb === "genre" ? (a) => a.genre || "Unknown genre" : gb === "year" ? (a) => a.year || "Undated" : gb === "author" ? (a) => a.artist : () => "Albums";
      const rows = groupBy(al, key, gb === "year" ? (a, b) => (parseInt(b[0]) || 0) - (parseInt(a[0]) || 0) : null).map(([name, list], gi) => {
        const L = String.fromCharCode(65 + (gi % 26));
        return `<div class="jx-row"><div class="jx-rowname"><b>${L}</b>${esc(name === "Albums" ? "Every record" : name)}<span>${list.length} ${list.length === 1 ? "album" : "albums"}</span></div><div class="jx-strips">
          ${list.map((a, i) => `<div class="jx-strip" data-album="${esc(a.key)}" title="${esc(a.title)} — ${esc(a.artist)}"><span class="jx-code">${L}${i + 1}</span>
            <span class="jx-art">${a.cover ? `<img loading="lazy" alt="" src="/api/items/${a.cover.id}/cover?v=${a.cover.cover_v || a.cover._cv || 0}">` : `<i class="jx-vinyl"></i>`}</span>
            <span class="jx-t"><b>${esc(a.title)}</b><small>${esc(a.artist)}${a.year ? " · " + esc(a.year) : ""}</small><small>${a.tracks.length} ${a.tracks.length === 1 ? "song" : "songs"}</small></span>
            <span class="jx-acts"><button class="jx-go" data-play-album="${esc(a.key)}" title="Play">▶</button><button class="jx-go alt" data-queue-album="${esc(a.key)}" data-how="end" title="Add to the queue">＋</button></span></div>`).join("")}</div></div>`;
      }).join("");
      out.push(`<section class="jukebox"><div class="jx-arch"><span class="jx-neon"></span><b>BABEL</b><small>SELECT-A-SONG</small></div>
        <div class="jx-window" id="jxWindow">${jxWindow()}</div>
        <div class="jx-dial"><button class="btn" data-shuffle-all="1">⤨ Shuffle everything</button><button class="btn" data-jx-queue>☰ The queue</button></div>
        <div class="jx-cards">${rows}</div><div class="jx-grille"></div></section>`);
    }
    if (kinds.has("tv") || kinds.has("movie")) out.push(watchingSection(items));
    if (kinds.has("tv")) {
      const sl = seriesList(items);
      out.push(`<section class="group"><div class="group-head"><h2>${ransom("TV")}</h2><span class="count">${sl.length} ${sl.length === 1 ? "series" : "series"}</span></div>
        <div class="cards">${sl.map((s) => {
          const seasons = new Set(s.eps.map((e) => e.season || 1));
          const done = s.eps.filter(isDone).length;
          return `<button class="card poster" data-series="${esc(s.key)}">${posterHTML(s.cover, s.title)}${done === s.eps.length ? `<span class="w-badge">✓ Watched</span>` : ""}
            ${done && done < s.eps.length ? `<span class="cprog"><i style="width:${Math.round(100 * done / s.eps.length)}%"></i></span>` : ""}
            <span class="ct">${esc(s.title)}</span><span class="ca">${seasons.size} ${seasons.size === 1 ? "season" : "seasons"} · ${s.eps.length} episode${s.eps.length === 1 ? "" : "s"}${done ? ` · ${done} watched` : ""}</span></button>`;
        }).join("")}</div></section>`);
    }
    if (kinds.has("movie")) {
      const mv = items.filter((i) => i.kind === "movie");
      const key = gb === "series" ? (m) => m.series || "Standalone films" : gb === "year" ? (m) => m.year || "Undated" : gb === "none" ? () => "Movies" : (m) => m.genre || "Unknown genre";
      for (const [name, list] of groupBy(mv, key, gb === "year" ? (a, b) => (parseInt(b[0]) || 0) - (parseInt(a[0]) || 0) : (a, b) => (a[0] === "Standalone films") - (b[0] === "Standalone films") || a[0].localeCompare(b[0]))) {
        list.sort((a, b) => (a.series_index || 0) - (b.series_index || 0) || (parseInt(a.year) || 0) - (parseInt(b.year) || 0));
        out.push(`<section class="group"><div class="group-head"><h2>${ransom(name)}</h2><span class="count">${list.length} ${list.length === 1 ? "film" : "films"}</span></div>
          <div class="cards">${list.map((m) => `<button class="card poster" data-open="${m.id}">${posterHTML(m, m.title)}${m.watched ? `<span class="w-badge">✓ Watched</span>` : ""}${inProg(m) ? `<span class="cprog"><i style="width:${Math.round(m.progress * 100)}%"></i></span>` : ""}
            <span class="ct">${esc(m.title)}</span><span class="ca">${esc(m.year || "")}${m.duration ? " · " + fmtTime(m.duration) : ""}</span></button>`).join("")}</div></section>`);
      }
    }
    if (!out.length) return `<div class="empty"><h2>No music, TV or movies yet</h2><p>Add audio or video files with Add to library, scan a folder, or save them into your inbox folder. Music is filed by artist and album; TV by series and season.</p><button class="btn primary" data-action="add">Add media</button></div>`;
    return out.join("");
  }

  /* ---------- TV & Movies: two wheels (shows, films) on the left, the chosen one big on the right, and the
     TV ⇄ Movies switch in the bottom-right corner. Mouse wheel, arrow keys or a click turn the wheel. ---------- */
  const W = { mode: "tv", sel: { tv: null, movie: null } };
  try { const m = localStorage.getItem("inkwell-wheel"); W.mode = ["movie", "anim"].includes(m) ? m : "tv"; } catch (e) {}
  // animation: anime and cartoons, shows and films together (told apart by their genre, tags or description)
  const normT = (s) => String(s || "").toLowerCase().replace(/[^a-z0-9]+/g, "");
  const isAnim = (i) => W.animated.has(normT(i.kind === "tv" ? i.series : i.title)) || /\banim(e|at)|cartoon|stop-motion/i.test([i.genre, i.subject, (i.tags || []).join(" "), i.summary].join(" "));
  W.sel.anim = null;
  W.animated = new Set();
  // which shows and films are animated: the app looks each one up once (AniList, Wikipedia) and remembers
  async function loadAnimated(n = 0) {
    try {
      const r = await fetch("/api/media/animated").then((x) => x.json());
      const before = W.animated.size;
      W.animated = new Set(r.titles.map(normT));
      if (W.animated.size !== before && S.area === "video" && !S.home) window.render();
      if (r.pending && n < 40) setTimeout(() => loadAnimated(n + 1), 4000);
    } catch (e) {}
  }
  loadAnimated();
  function wheelItems(items) {
    if (W.mode === "anim") {
      const shows = seriesList(items).filter((s) => s.eps.some(isAnim)).map((s) => ({ key: "s:" + s.key, s, title: s.title, cover: s.cover, last: Math.max(...s.eps.map((e) => Math.max(e.opened_at || 0, e.watched_at || 0))) }));
      const films = items.filter((i) => i.kind === "movie" && isAnim(i)).map((m) => ({ key: "m:" + m.id, m, title: m.title, cover: m, last: m.opened_at || 0 }));
      return [...shows, ...films].sort((a, b) => a.title.localeCompare(b.title));
    }
    if (W.mode === "tv") {
      return seriesList(items).map((s) => ({ key: "s:" + s.key, s, title: s.title, cover: s.cover,
        last: Math.max(...s.eps.map((e) => Math.max(e.opened_at || 0, e.watched_at || 0))) }))
        .sort((a, b) => a.title.localeCompare(b.title));
    }
    return items.filter((i) => i.kind === "movie").map((m) => ({ key: "m:" + m.id, m, title: m.title, cover: m, last: m.opened_at || 0 }))
      .sort((a, b) => (a.m.series || a.title).localeCompare(b.m.series || b.title) || (a.m.series_index || 0) - (b.m.series_index || 0) || (parseInt(a.m.year) || 0) - (parseInt(b.m.year) || 0));
  }
  function wheel(items) {
    const tvN = seriesList(items).length, mvN = items.filter((i) => i.kind === "movie").length;
    const anN = seriesList(items).filter((s) => s.eps.some(isAnim)).length + items.filter((i) => i.kind === "movie" && isAnim(i)).length;
    if (W.mode === "anim" && !anN) W.mode = "tv";
    if (!tvN && !mvN) return `<div class="empty"><h2>No TV or movies yet</h2><p>Add video files with Add to library or scan a folder. TV is filed by series and season.</p><button class="btn primary" data-action="add">Add video</button></div>`;
    if (W.mode === "tv" && !tvN) W.mode = "movie";
    if (W.mode === "movie" && !mvN) W.mode = "tv";
    const list = wheelItems(items);
    let sel = list.findIndex((x) => x.key === W.sel[W.mode]);
    if (sel < 0) { const recent = [...list].sort((a, b) => b.last - a.last)[0]; sel = Math.max(0, list.indexOf(recent)); W.sel[W.mode] = list[sel]?.key; }
    W.list = list; W.i = sel;
    return `<div class="vw" data-mode="${W.mode}">
      <div class="vw-wheel" id="vwWheel" tabindex="0" aria-label="${W.mode === "tv" ? "Shows" : "Films"}">${list.map((x, i) => {
        const e = x.s ? x.s.eps : [x.m], done = e.filter(isDone).length, pct = x.s ? Math.round(100 * done / e.length) : Math.round(Math.min(1, x.m.watched ? 1 : x.m.progress || 0) * 100);
        const sub = x.s ? `${new Set(x.s.eps.map((q) => q.season || 1)).size} season${new Set(x.s.eps.map((q) => q.season || 1)).size === 1 ? "" : "s"} · ${x.s.eps.length} ep.` : [x.m.year, x.m.duration ? fmtTime(x.m.duration) : ""].filter(Boolean).join(" · ");
        return `<button class="vw-card ${i === sel ? "sel" : ""} ${pct >= 100 ? "done" : ""}" data-vw="${i}">
          <span class="vw-thumb">${x.cover && x.cover.has_cover ? `<img loading="lazy" alt="" src="/api/items/${x.cover.id}/cover?v=${x.cover.cover_v || x.cover._cv || 0}">` : `<i style="--c:${colorFor(x.cover || { id: x.title, title: x.title })}">${esc((x.title || "?")[0])}</i>`}</span>
          <span class="vw-txt"><b>${esc(x.title)}</b><small>${esc(sub)}${x.m && x.m.series ? ` · ${esc(x.m.series)}${x.m.series_index ? " #" + +x.m.series_index : ""}` : ""}</small></span>
          ${pct > 1 ? `<span class="vw-prog"><i style="width:${pct}%"></i></span>` : ""}${pct >= 100 ? `<span class="vw-done">✓</span>` : ""}</button>`;
      }).join("")}</div>
      <div class="vw-right"><div class="vw-stage" id="vwStage"></div>
        <div class="vw-swap" role="group" aria-label="Show TV or movies">
          <button class="vw-sw ${W.mode === "tv" ? "on" : ""}" data-vw-mode="tv"><b>TV</b><small>${tvN} ${tvN === 1 ? "series" : "series"}</small></button>
          <button class="vw-sw ${W.mode === "movie" ? "on" : ""}" data-vw-mode="movie"><b>Movies</b><small>${mvN} ${mvN === 1 ? "film" : "films"}</small></button>
          <button class="vw-sw ${W.mode === "anim" ? "on" : ""}" data-vw-mode="anim"><b>Animation</b><small>${anN ? `${anN} anime & cartoons` : "none yet"}</small></button>
        </div></div></div>`;
  }
  function placeWheel(animate = true) {
    const box = $("#vwWheel");
    if (!box) return;
    const cards = [...box.children], h = box.clientHeight, ch = 92;
    cards.forEach((c, i) => {
      const d = i - W.i, ad = Math.abs(d);
      c.style.transition = animate ? "" : "none";
      // fanned out on a curve: the chosen card sits in the middle and sticks out; the rest lean back the further away they are
      c.style.transform = `translate(${-Math.min(ad, 5) * 11 + (d === 0 ? 30 : 0)}px, ${h / 2 - ch / 2 + d * (ch + 6)}px)`;
      c.style.opacity = ad > 7 ? 0 : 1 - Math.max(0, ad - 4) * 0.22;
      c.style.zIndex = 50 - ad;
      c.classList.toggle("sel", d === 0);
      c.tabIndex = d === 0 ? 0 : -1;
    });
    paintStage();
  }
  function paintStage() {
    const el = $("#vwStage"), x = W.list?.[W.i];
    if (!el || !x) return;
    W.sel[W.mode] = x.key;
    const coverUrl = (c) => (c && c.has_cover ? `/api/items/${c.id}/cover?v=${c.cover_v || c._cv || 0}` : "");
    const backdrop = (c) => { const u = coverUrl(c); return u ? `<div class="vw-backdrop" style="background-image:url('${u}')"></div>` : ""; };
    if (x.m) {
      const m = x.m, pct = Math.round(Math.min(1, m.watched ? 1 : m.progress || 0) * 100);
      // the rest of its series (or, for a standalone film, others in its genre) as a strip of posters along the bottom
      const kin = W.list.map((y, i) => ({ y, i })).filter(({ y }) => y.m && y.m.id !== m.id && (m.series ? y.m.series === m.series : m.genre && y.m.genre === m.genre)).slice(0, 12);
      const ticket = [["Year", m.year], ["Runtime", m.duration ? fmtTime(m.duration) : ""], ["Genre", m.genre], ["Directed by", (m.authors || []).join(", ")]].filter(([, v]) => v);
      el.innerHTML = `${backdrop(m)}<div class="vw-in vw-film" key="${x.key}"><div class="vw-poster">${posterHTML(m, m.title)}${m.watched ? `<span class="vw-stamp">Seen it!</span>` : pct > 1 ? `<span class="vw-stamp now">Now showing</span>` : ""}</div><div class="vw-info">
        <span class="vw-kind">${m.series ? `${esc(m.series)}${m.series_index ? " · No. " + +m.series_index : ""}` : "Feature film"}</span>
        <h2>${esc(m.title)}</h2>
        <div class="vw-ticket">${ticket.map(([k, v]) => `<span><small>${k}</small><b>${esc(v)}</b></span>`).join("")}</div>
        <div class="vw-reel"><div class="vw-bar"><i style="width:${pct}%"></i></div><small>${m.watched ? "✓ Watched" : pct > 1 ? `${pct}% watched · ${fmtTime((m.duration || 0) * (1 - (m.progress || 0)))} left` : "Not started"}</small></div>
        <p class="vw-syn">${esc(m.summary || "No synopsis yet. Use Details → Fill in from Wikipedia.")}</p>
        <div class="d-actions">${m.has_file ? `<button class="btn primary" data-read="${m.id}">${pct > 1 && !m.watched ? "▶ Resume" : "▶ Watch"}</button>` : ""}<button class="btn" data-detail="${m.id}">Details</button></div></div></div>
        ${kin.length ? `<div class="vw-kin"><h3>${m.series ? `More from the ${esc(m.series)} series` : `More ${esc(m.genre)}`}</h3><div class="vw-strip">${kin.map(({ y, i }) => `<button class="vw-mini ${y.m.watched ? "seen" : ""}" data-vw-go="${i}" title="${esc(y.m.title)}">${posterHTML(y.m, y.m.title)}<b>${esc(y.m.title)}</b><small>${esc(y.m.year || "")}${y.m.watched ? " · ✓" : ""}</small></button>`).join("")}</div></div>` : ""}`;
      // a long synopsis shows its first lines (the series strip stays in view) and opens up on a click
      const syn = el.querySelector(".vw-syn");
      if (syn && syn.scrollHeight > syn.clientHeight + 4) {
        syn.insertAdjacentHTML("afterend", `<button class="vw-synmore">Read more ▾</button>`);
        syn.nextElementSibling.onclick = (e) => { e.stopPropagation(); syn.classList.add("full"); e.currentTarget.remove(); };
      }
      return;
    }
    const s = x.s, eps = s.eps, done = eps.filter(isDone).length;
    const half = eps.filter(inProg).sort((a, b) => (b.opened_at || 0) - (a.opened_at || 0))[0];
    let last = -1; eps.forEach((e, i) => { if (isDone(e)) last = i; });
    const next = half || eps.slice(last + 1).find((e) => !isDone(e)) || eps[0];
    const syn = eps.find((e) => e.summary)?.summary || "";
    el.innerHTML = `${backdrop(s.cover)}<div class="vw-in" key="${x.key}">${posterHTML(s.cover, s.title)}<div class="vw-info">
      <span class="vw-kind">TV series</span><h2>${esc(s.title)}</h2>
      <p class="vw-meta">${esc([s.genre, `${new Set(eps.map((e) => e.season || 1)).size} season(s)`, `${eps.length} episodes`].filter(Boolean).join(" · "))}</p>
      <div class="vw-bar"><i style="width:${Math.round(100 * done / eps.length)}%"></i></div><small>${done} of ${eps.length} watched</small>
      ${syn ? `<p class="vw-syn">${esc(syn)}</p>` : ""}
      <div class="d-actions"><button class="btn primary" data-read="${next.id}">▶ ${next === half ? `Resume ${epCode(next)}` : done ? `Next: ${epCode(next)}` : `Play ${epCode(next)}`}</button><button class="btn" data-series="${esc(s.key)}">All episodes</button></div>
      <ol class="vw-eps">${eps.map((e) => `<li class="${isDone(e) ? "done" : ""} ${e === next ? "next" : ""}"><button data-read="${e.id}"><span>${epCode(e)}</span><b>${esc(e.title)}</b><em>${isDone(e) ? "✓" : inProg(e) ? Math.round(e.progress * 100) + "%" : e.duration ? fmtTime(e.duration) : ""}</em></button></li>`).join("")}</ol>
    </div></div>`;
    // other shows in the same genre, as a strip of posters (a show is its own series: its episodes are listed above)
    const kin = W.list.map((y, i) => ({ y, i })).filter(({ y }) => y.s && y.s.key !== s.key && s.genre && y.s.genre === s.genre).slice(0, 12);
    if (kin.length) el.insertAdjacentHTML("beforeend", `<div class="vw-kin"><h3>More ${esc(s.genre)}</h3><div class="vw-strip">${kin.map(({ y, i }) => `<button class="vw-mini" data-vw-go="${i}" title="${esc(y.s.title)}">${posterHTML(y.s.cover, y.s.title)}<b>${esc(y.s.title)}</b><small>${y.s.eps.length} ep.</small></button>`).join("")}</div></div>`);
  }
  function turnWheel(to) {
    if (!W.list?.length) return;
    W.i = Math.max(0, Math.min(W.list.length - 1, to));
    placeWheel();
  }
  function bindWheel() {
    const box = $("#vwWheel");
    if (!box) return;
    requestAnimationFrame(() => placeWheel(false));
    let acc = 0;
    box.onwheel = (e) => { e.preventDefault(); acc += e.deltaY; if (Math.abs(acc) >= 60) { turnWheel(W.i + Math.sign(acc)); acc = 0; } };
    box.onclick = (e) => { const c = e.target.closest("[data-vw]"); if (!c) return; const i = Number(c.dataset.vw); if (i === W.i) { const b = $("#vwStage [data-read]"); b && b.click(); } else turnWheel(i); };
    const stage = $("#vwStage");
    if (stage) stage.onclick = (e) => { const g = e.target.closest("[data-vw-go]"); if (g) { e.stopPropagation(); turnWheel(Number(g.dataset.vwGo)); } };
    box.onkeydown = (e) => {
      if (e.key === "ArrowDown") { e.preventDefault(); turnWheel(W.i + 1); }
      else if (e.key === "ArrowUp") { e.preventDefault(); turnWheel(W.i - 1); }
      else if (e.key === "Enter") { const b = $("#vwStage [data-read]"); b && b.click(); }
    };
    $$(".vw [data-vw-mode]").forEach((b) => b.onclick = () => {
      if (b.dataset.vwMode === W.mode) return;
      W.mode = b.dataset.vwMode;
      try { localStorage.setItem("inkwell-wheel", W.mode); } catch (e) {}
      const vw = $(".vw"); vw?.classList.add("swapping");
      setTimeout(() => window.render(), 160);   // the app's render (this file's own render draws music shelves)
    });
    if (!W._resize) { W._resize = true; window.addEventListener("resize", () => placeWheel(false)); }
  }

  /* the jukebox's window: the record on the turntable, what's playing, and the player's buttons */
  function jxWindow() {
    const t = Player.current();
    if (!t) return `<div class="jx-idle">Pick a record below, or ⤨ shuffle everything</div>`;
    const on = Player.playing, rep = Player.repeat;
    return `<span class="jx-rec ${on ? "spin" : ""}">${t.has_cover ? `<img alt="" src="/api/items/${t.id}/cover?v=${t.cover_v || 0}">` : ""}</span>
      <span class="jx-np"><small>NOW PLAYING</small><b>${esc(t.title)}</b><small>${esc([(t.authors || [])[0], t.album].filter(Boolean).join(" · "))}</small></span>
      <span class="jx-ctl"><button class="jx-b ${Player.shuffle ? "on" : ""}" data-jx="shuffle" title="Shuffle">⤨</button><button class="jx-b" data-jx="prev" title="Previous">⏮</button>
        <button class="jx-b jx-play" data-jx="toggle" title="Play or pause">${on ? "❚❚" : "▶"}</button><button class="jx-b" data-jx="next" title="Next">⏭</button>
        <button class="jx-b ${rep !== "off" ? "on" : ""}" data-jx="repeat" title="Repeat">${rep === "one" ? "🔂" : "🔁"}</button></span>`;
  }
  addEventListener("player-changed", () => { const w = document.getElementById("jxWindow"); if (w) w.innerHTML = jxWindow(); });
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-jx]");
    if (b) { e.stopPropagation(); ({ shuffle: () => Player.toggleShuffle(), prev: Player.prev, toggle: Player.toggle, next: () => Player.next(), repeat: Player.cycleRepeat })[b.dataset.jx](); return; }
    if (e.target.closest("[data-jx-queue]")) Player.openQueue();
  });

  /* ---------- album / series panels (in the drawer) ---------- */
  function openAlbum(key) {
    const a = albums(S.items).find((x) => x.key === key);
    if (!a) return;
    const total = a.tracks.reduce((s, t) => s + (t.duration || 0), 0);
    $("#drawerBody").innerHTML = `<div class="album-head">${disc(a.cover, a.title)}<div>
        <h2>${esc(a.title)}</h2><div class="by">${esc(a.artist)}${a.year ? ", " + esc(a.year) : ""}</div>
        <div class="by">${esc(a.genre || "")}${a.genre ? " · " : ""}${a.tracks.length} tracks${total ? " · " + fmtTime(total) : ""}</div>
        <div class="d-actions"><button class="btn primary" data-play-album="${esc(key)}">Play album</button><button class="btn" data-play-album="${esc(key)}" data-shuffle="1">⤨ Shuffle</button>
          <button class="btn" data-queue-album="${esc(key)}" data-how="next">Play next</button><button class="btn" data-queue-album="${esc(key)}" data-how="end">Add to queue</button></div></div></div>
      <ol class="tracklist">${a.tracks.map((t, i) => `<li><button class="trk" data-play-album="${esc(key)}" data-start="${i}"><span class="tn">${t.track || i + 1}</span><span class="tt">${esc(t.title)}</span><span class="td">${t.duration ? fmtTime(t.duration) : ""}</span></button><span class="trk-q"><button class="icon-btn sm" data-queue-track="${t.id}" data-how="next" title="Play next">⤵</button><button class="icon-btn sm" data-queue-track="${t.id}" data-how="end" title="Add to queue">＋</button></span><button class="icon-btn sm" data-detail="${t.id}" title="Details">⋯</button></li>`).join("")}</ol>${Coll.albumSection(key)}`;
    showDrawer();
  }

  function openSeries(key) {
    const s = seriesList(S.items).find((x) => x.key === key);
    if (!s) return;
    const bySeason = new Map();
    for (const e of s.eps) { const n = e.season || 1; if (!bySeason.has(n)) bySeason.set(n, []); bySeason.get(n).push(e); }
    const syn = s.eps.find((e) => e.summary)?.summary || "";
    const done = s.eps.filter(isDone).length;
    $("#drawerBody").innerHTML = `<div class="series-head">${posterHTML(s.cover, s.title)}<div><h2 class="series-title">${esc(s.title)}</h2>
      <div class="by">${done} of ${s.eps.length} episodes watched</div>
      <div class="d-actions"><button class="btn sm" data-watch-all="${esc(s.key)}" data-val="${done === s.eps.length ? 0 : 1}">${done === s.eps.length ? "Mark all unwatched" : "Mark all watched"}</button>
      <button class="btn sm" data-poster-for="${s.eps[0].id}">Find poster</button></div></div></div>${syn ? `<p class="summary">${esc(syn)}</p>` : ""}
      ${[...bySeason.entries()].sort((a, b) => a[0] - b[0]).map(([n, eps]) => `<div class="d-sec"><h4>Season ${n}</h4><ol class="tracklist">
        ${eps.map((e) => `<li class="${e.watched ? "ep-done" : ""}"><label class="ep-w" title="Watched"><input type="checkbox" data-watch-ep="${e.id}" ${e.watched ? "checked" : ""}></label><button class="trk" data-read="${e.id}"><span class="tn">${e.episode ?? ""}</span><span class="tt">${esc(e.title)}</span><span class="td">${e.watched ? "✓" : inProg(e) ? Math.round(e.progress * 100) + "%" : (e.duration ? fmtTime(e.duration) : "")}</span></button><button class="icon-btn sm" data-detail="${e.id}" title="Details">⋯</button></li>`).join("")}
      </ol></div>`).join("")}`;
    showDrawer();
  }

  function showDrawer() {
    const dr = $("#drawer");
    dr.classList.add("open");
    dr.setAttribute("aria-hidden", "false");
    dr.scrollTop = 0;
    S.openId = null;
  }

  /* ---------- music: hand tracks to the shared player (js/player.js) ---------- */
  const allTracks = () => albums(S.items).flatMap((a) => a.tracks);
  function play(queue, i = 0) { Player.playList(queue, i); }
  function bindPlayer() {
    Player.bind({ remote: typeof MINI !== "undefined" && MINI });  // the mini reader window remote-controls the main player
    document.addEventListener("change", async (e) => {
      const cb = e.target.closest("[data-watch-ep]");
      if (!cb) return;
      await api.send("PATCH", `/api/items/${cb.dataset.watchEp}`, { watched: cb.checked });
      const key = S.items.find((x) => x.id === Number(cb.dataset.watchEp));
      await loadItems();
      if (key) openSeries(seriesList(S.items).find((s) => s.eps.some((x) => x.id === key.id))?.key);
    });
    document.addEventListener("click", async (e) => {
      const wa = e.target.closest("[data-watch-all]"), pf = e.target.closest("[data-poster-for]");
      if (wa) {
        const s = seriesList(S.items).find((x) => x.key === wa.dataset.watchAll);
        if (!s) return;
        await Promise.all(s.eps.map((x) => api.send("PATCH", `/api/items/${x.id}`, { watched: wa.dataset.val === "1" })));
        await loadItems(); openSeries(s.key);
      } else if (pf) {
        pf.disabled = true; pf.textContent = "Looking…";
        try { await api.send("POST", `/api/items/${pf.dataset.posterFor}/poster`, {}); toast("Poster added"); await loadItems(); const it = S.items.find((x) => x.id === Number(pf.dataset.posterFor)); if (it) openSeries(seriesList(S.items).find((s) => s.eps.includes(it))?.key); }
        catch (err) { toast(err.message, "error"); pf.disabled = false; pf.textContent = "Find poster"; }
      }
    });
    document.addEventListener("click", (e) => {
      const b = e.target.closest("[data-play-album]");
      const qa = e.target.closest("[data-queue-album]");
      const qt = e.target.closest("[data-queue-track]");
      const all = e.target.closest("[data-shuffle-all]");
      const al = !b && !qa && e.target.closest("[data-album]");
      const se = e.target.closest("[data-series]");
      if (all) {
        const t = allTracks();
        if (t.length) { Player.playList(t, 0, { shuffle: true }); toast(`Shuffling ${t.length} songs`); }
      } else if (qt) {
        const t = S.items.find((x) => x.id === Number(qt.dataset.queueTrack));
        if (!t) return;
        qt.dataset.how === "next" ? Player.playNext([t]) : Player.addToQueue([t]);
        toast(qt.dataset.how === "next" ? `“${t.title}” plays next` : `Added “${t.title}” to the queue`);
      } else if (qa) {
        const a2 = albums(S.items).find((x) => x.key === qa.dataset.queueAlbum);
        if (!a2) return;
        qa.dataset.how === "next" ? Player.playNext(a2.tracks) : Player.addToQueue(a2.tracks);
        toast(qa.dataset.how === "next" ? `${a2.title} plays next` : `Added ${a2.title} to the queue`);
      } else if (b) {
        const a2 = albums(S.items).find((x) => x.key === b.dataset.playAlbum);
        if (!a2) return;
        if (b.dataset.shuffle) Player.playList(a2.tracks, 0, { shuffle: true });
        else Player.playList(a2.tracks, Number(b.dataset.start || 0));
      } else if (al) openAlbum(al.dataset.album);
      else if (se) openSeries(se.dataset.series);
    });
  }

  /* ---------- poster frames for videos (offline, in the app) ---------- */
  async function videoCover(it) {
    return new Promise((resolve) => {
      const v = document.createElement("video");
      v.muted = true; v.preload = "metadata"; v.crossOrigin = "anonymous";
      v.src = `/api/items/${it.id}/file`;
      const fail = () => { v.removeAttribute("src"); v.load(); resolve(false); };
      const t = setTimeout(fail, 20000);
      v.addEventListener("error", () => { clearTimeout(t); fail(); });
      v.addEventListener("loadedmetadata", () => { v.currentTime = Math.min(120, (v.duration || 60) * 0.12); });
      v.addEventListener("seeked", async () => {
        clearTimeout(t);
        try {
          const w = 480, h = Math.round((v.videoHeight / v.videoWidth) * w) || 270;
          const c = document.createElement("canvas");
          c.width = w; c.height = h;
          c.getContext("2d").drawImage(v, 0, 0, w, h);
          const blob = await new Promise((r) => c.toBlob(r, "image/jpeg", 0.85));
          await fetch(`/api/items/${it.id}/cover`, { method: "POST", body: blob });
          resolve(true);
        } catch (e) { resolve(false); }
        v.removeAttribute("src"); v.load();
      }, { once: true });
    });
  }

  return { render, wheel, bindWheel, openAlbum, openSeries, bindPlayer, videoCover, albums, fmtTime, play, seriesList };
})();
