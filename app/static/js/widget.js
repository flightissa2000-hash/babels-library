/* Babel's Library desktop widget: recently read + quick search. Double-click opens the full app. */
const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const hash = (s) => { let h = 2166136261; for (const c of String(s)) { h ^= c.charCodeAt(0); h = Math.imul(h, 16777619); } return h >>> 0; };
let items = [], q = "", sel = null, pinned = false, tab = "recent", openAlbum = null;
try { tab = localStorage.getItem("inkwell-widget-tab") || "recent"; } catch (e) {}

const theme = () => THEMES[document.documentElement.dataset.theme] || THEMES.wordtown;
const colorFor = (it) => { const p = theme().spines; return p[hash(it.id + (it.title || "")) % p.length]; };
const author = (it) => { const a = it.authors || []; return !a.length ? (it.kind === "graphic" ? it.publisher || "Creators not listed" : ["music"].includes(it.kind) ? "Unknown artist" : ["tv", "movie"].includes(it.kind) ? it.series || "" : "Unknown author") : a.length > 2 ? a[0] + " et al." : a.join(" & "); };
function ago(t) {
  if (!t) return "";
  const s = Date.now() / 1000 - t;
  if (s < 90) return "just now";
  if (s < 3600) return Math.round(s / 60) + " min ago";
  if (s < 86400) return Math.round(s / 3600) + " h ago";
  if (s < 86400 * 14) return Math.round(s / 86400) + " d ago";
  return new Date(t * 1000).toLocaleDateString();
}
const cover = (it) => it.has_cover
  ? `<div class="cover" style="--c:${colorFor(it)}"><img alt="" src="/api/items/${it.id}/cover?v=${it.cover_v || 0}"></div>`
  : `<div class="cover" style="--c:${colorFor(it)}"><div class="gen-cover"><div class="t">${esc(it.title)}</div></div></div>`;

function row(it) {
  const pct = Math.round((it.progress || 0) * 100);
  const meta = it.opened_at ? `${ago(it.opened_at)}${it.has_file ? " · " + pct + "%" : ""}` : author(it);
  const verb = ["tv", "movie"].includes(it.kind) ? "Watch" : it.kind === "music" ? "Play" : "Read";
  return `<li class="w-item ${it.id === sel ? "sel" : ""}" data-id="${it.id}" title="Double-click to open">
    ${cover(it)}<div class="w-body">${it.has_file ? `<button class="w-read" data-read-id="${it.id}" title="${verb} now">${verb}</button>` : ""}${it.audio_status === "ready" ? `<button class="w-read w-listen" data-listen-id="${it.id}" title="Listen to the audiobook">🎧 Listen</button>` : ""}<div class="wt">${esc(it.title || "Untitled")}</div>
    <div class="wa">${esc(it.opened_at ? author(it) : (it.kind === "article" ? it.topic : it.genre) || "")}</div>
    <div class="wa">${esc(meta)}</div>
    ${it.has_file && it.opened_at ? `<div class="bar"><i style="width:${pct}%"></i></div>` : ""}</div></li>`;
}

/* ---------- music tab: browse albums, play or queue ---------- */
const akey = (x) => `${(x.album_artist || (x.authors || [])[0] || "Unknown artist").toLowerCase()}|${(x.album || "Singles").toLowerCase()}`;
function albums() {
  const m = new Map();
  for (const it of items.filter((i) => i.kind === "music")) {
    const k = akey(it);
    if (!m.has(k)) m.set(k, { key: k, title: it.album || "Singles", artist: it.album_artist || (it.authors || [])[0] || "Unknown artist", tracks: [], year: it.year });
    const a = m.get(k);
    a.tracks.push(it);
    if (it.has_cover && !a.cover) a.cover = it;
  }
  const out = [...m.values()];
  for (const a of out) a.tracks.sort((x, y) => (x.disc || 1) - (y.disc || 1) || (x.track || 999) - (y.track || 999) || x.title.localeCompare(y.title));
  return out.sort((a, b) => a.artist.localeCompare(b.artist) || a.title.localeCompare(b.title));
}
const albumArt = (a) => a.cover ? `<img alt="" loading="lazy" src="/api/items/${a.cover.id}/cover?v=${a.cover.cover_v || 0}">` : `<span style="--c:${colorFor(a.tracks[0])}">${esc(a.title.slice(0, 2))}</span>`;
function renderMusic(list) {
  const al = albums();
  if (!al.length) { list.innerHTML = `<li class="w-empty">No music yet. Add some in the full Babel's Library window.</li>`; return; }
  if (openAlbum) {
    const a = al.find((x) => x.key === openAlbum);
    if (a) {
      $("#wTitle").textContent = a.title;
      list.innerHTML = `<li class="wm-head"><button class="wm-back" data-m="back" title="All albums">‹ Albums</button>
          <div class="wm-hero"><div class="wm-art">${albumArt(a)}</div><div><b>${esc(a.title)}</b><span>${esc(a.artist)}${a.year ? " · " + esc(a.year) : ""}</span><span>${a.tracks.length} tracks</span></div></div>
          <div class="wm-acts"><button class="w-read" data-m="play">▶ Play</button><button class="w-ghost" data-m="shuffle">⤨ Shuffle</button><button class="w-ghost" data-m="next">Play next</button><button class="w-ghost" data-m="queue">＋ Queue</button></div></li>` +
        a.tracks.map((t, i) => `<li class="wm-trk" data-i="${i}"><button class="wm-play" data-m="from" data-i="${i}"><span class="n">${t.track || i + 1}</span><span class="t">${esc(t.title)}</span></button>
          <button class="w-ico" data-m="tnext" data-i="${i}" title="Play next">⤵</button><button class="w-ico" data-m="tqueue" data-i="${i}" title="Add to queue">＋</button></li>`).join("");
      return;
    }
    openAlbum = null;
  }
  $("#wTitle").textContent = "Music";
  let shown = al;
  if (q.trim()) {
    const words = q.toLowerCase().split(/\s+/).filter(Boolean);
    shown = al.filter((a) => { const hay = [a.title, a.artist, ...a.tracks.map((t) => t.title)].join(" ").toLowerCase(); return words.every((w) => hay.includes(w)); });
  }
  list.innerHTML = `<li class="wm-top"><button class="w-read" data-m="all">⤨ Shuffle all music</button></li>` +
    (shown.length ? `<li class="wm-grid">${shown.map((a) => `<button class="wm-alb" data-album="${esc(a.key)}" title="${esc(a.title)} — ${esc(a.artist)}"><div class="wm-art">${albumArt(a)}<span class="wm-qp" data-m="qplay" data-album="${esc(a.key)}" title="Play">▶</span></div><b>${esc(a.title)}</b><span>${esc(a.artist)}</span></button>`).join("")}</li>`
      : `<li class="w-empty">No albums match “${esc(q)}”.</li>`);
}
function musicClick(e) {
  const m = e.target.closest("[data-m]"), alb = e.target.closest(".wm-alb");
  const al = albums();
  if (m) {
    e.stopPropagation();
    const act = m.dataset.m;
    const a = al.find((x) => x.key === (m.dataset.album || openAlbum));
    const i = Number(m.dataset.i);
    if (act === "back") { openAlbum = null; render(); }
    else if (act === "all") { const t = al.flatMap((x) => x.tracks); if (t.length) Player.playList(t, 0, { shuffle: true }); }
    else if (!a) return;
    else if (act === "play" || act === "qplay") Player.playList(a.tracks, 0, { shuffle: false });
    else if (act === "shuffle") Player.playList(a.tracks, 0, { shuffle: true });
    else if (act === "next") { Player.playNext(a.tracks); flash(m, "Up next"); }
    else if (act === "queue") { Player.addToQueue(a.tracks); flash(m, "Queued"); }
    else if (act === "from") Player.playList(a.tracks, i, { shuffle: false });
    else if (act === "tnext") { Player.playNext([a.tracks[i]]); flash(m, "✓"); }
    else if (act === "tqueue") { Player.addToQueue([a.tracks[i]]); flash(m, "✓"); }
    return true;
  }
  if (alb) { openAlbum = alb.dataset.album; render(); $("#wList").scrollTop = 0; return true; }
  return false;
}
function flash(btn, txt) { const o = btn.textContent; btn.textContent = txt; setTimeout(() => { btn.textContent = o; }, 1100); }
function setTab(t) {
  tab = t;
  try { localStorage.setItem("inkwell-widget-tab", t); } catch (e) {}
  document.querySelectorAll("#wTabs button").forEach((b) => b.classList.toggle("on", b.dataset.tab === t));
  $("#wSearch").placeholder = t === "music" ? "Search albums and songs…" : t === "video" ? "Search shows and films…" : "Search your library…";
  render();
}

/* ---------- TV & Movies tab: pick a show or film; it plays right here in a widget-sized player ---------- */
const skey = (s) => (s || "").toLowerCase().replace(/\((?:19|20)\d\d\)|\b(?:19|20)\d\d\b/g, " ").replace(/[^a-z0-9]+/g, "");
const fmtT = (s) => { s = Math.max(0, Math.floor(s || 0)); const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), x = String(s % 60).padStart(2, "0"); return h ? `${h}:${String(m).padStart(2, "0")}:${x}` : `${m}:${x}`; };
const epCode = (e) => `S${e.season || 1} · E${e.episode ?? "?"}`;
const episodesOf = (it) => it.kind === "tv"
  ? items.filter((x) => x.kind === "tv" && x.has_file && skey(x.series) === skey(it.series)).sort((a, b) => (a.season || 1) - (b.season || 1) || (a.episode || 0) - (b.episode || 0))
  : it.series ? items.filter((x) => x.kind === "movie" && x.has_file && skey(x.series) === skey(it.series)).sort((a, b) => (a.series_index || 0) - (b.series_index || 0) || (parseInt(a.year) || 0) - (parseInt(b.year) || 0)) : [it];
function nextEp(eps) {
  const half = eps.filter((e) => !e.watched && (e.progress || 0) > 0.02).sort((a, b) => (b.opened_at || 0) - (a.opened_at || 0))[0];
  if (half) return half;
  let last = -1; eps.forEach((e, i) => { if (e.watched) last = i; });
  return eps.slice(last + 1).find((e) => !e.watched) || eps[0];
}
function renderVideo(list) {
  $("#wTitle").textContent = "TV & Movies";
  const words = q.toLowerCase().split(/\s+/).filter(Boolean);
  const hit = (s) => words.every((w) => s.toLowerCase().includes(w));
  const shows = new Map();
  for (const e of items.filter((x) => x.kind === "tv" && x.has_file)) { const k = skey(e.series); if (!shows.has(k)) shows.set(k, []); shows.get(k).push(e); }
  const showRows = [...shows.values()].map((eps) => {
    eps.sort((a, b) => (a.season || 1) - (b.season || 1) || (a.episode || 0) - (b.episode || 0));
    return { it: nextEp(eps), title: eps[0].series || "Unknown series", eps, last: Math.max(...eps.map((e) => e.opened_at || 0)), cov: eps.find((e) => e.has_cover) || eps[0] };
  }).filter((r) => hit(r.title));
  const films = items.filter((x) => x.kind === "movie" && x.has_file && hit([x.title, x.series].join(" ")));
  const watching = [...showRows.filter((r) => r.last), ...films.filter((m) => m.opened_at && !m.watched && (m.progress || 0) < 0.92).map((m) => ({ it: m, title: m.title, eps: [m], last: m.opened_at, cov: m }))]
    .sort((a, b) => b.last - a.last).slice(0, 4);
  const vrow = (r) => {
    const it = r.it, pct = Math.round(Math.min(1, it.watched ? 1 : it.progress || 0) * 100), done = r.eps.filter((e) => e.watched).length;
    const sub = it.kind === "tv" ? `${it === r.eps.find((e) => !e.watched && (e.progress || 0) > 0.02) ? "Resume" : "Next"}: ${epCode(it)}${it.title && !/^Episode \d+$/.test(it.title) ? " · " + it.title : ""}` : [it.year, it.duration ? fmtT(it.duration) : ""].filter(Boolean).join(" · ");
    return `<li class="w-item wv-item" data-vid="${it.id}">${cover(r.cov)}<div class="w-body"><button class="w-read" data-vid="${it.id}">${pct > 1 && pct < 100 ? "Resume" : "Watch"}</button>
      <div class="wt">${esc(r.title)}</div><div class="wa">${esc(sub)}</div>
      ${it.kind === "tv" ? `<div class="wa">${done} of ${r.eps.length} watched</div><div class="bar"><i style="width:${Math.round(100 * done / r.eps.length)}%"></i></div>` : pct > 1 ? `<div class="bar"><i style="width:${pct}%"></i></div>` : ""}</div></li>`;
  };
  let html = "";
  if (watching.length && !words.length) html += `<li class="w-sec">Keep watching</li>` + watching.map(vrow).join("");
  if (showRows.length) html += `<li class="w-sec">TV</li>` + showRows.sort((a, b) => a.title.localeCompare(b.title)).map(vrow).join("");
  if (films.length) html += `<li class="w-sec">Movies</li>` + films.sort((a, b) => (a.series || a.title).localeCompare(b.series || b.title) || (a.series_index || 0) - (b.series_index || 0)).map((m) => vrow({ it: m, title: m.title, eps: [m], cov: m })).join("");
  list.innerHTML = html || `<li class="w-empty">${words.length ? `Nothing matches “${esc(q)}”.` : "No TV or movies yet. Add some in the full Babel's Library window."}</li>`;
}

const V = { it: null, eps: [], saveAt: 0 };
const vid = () => $("#wVid");
function saveVideo(force) {
  const v = vid();
  if (!V.it || !v.duration) return;
  if (!force && Math.abs(v.currentTime - V.saveAt) < 10) return;
  V.saveAt = v.currentTime;
  post0(`/api/items/${V.it.id}`, { last_location: v.currentTime.toFixed(0), progress: v.currentTime / v.duration });
}
const post0 = (u, b) => fetch(u, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(b) }).catch(() => {});
function playVideo(id) {
  const it = items.find((x) => x.id === id);
  if (!it) return;
  saveVideo(true);
  V.it = it; V.eps = episodesOf(it); V.saveAt = 0;
  Player.pause();                                   // music stops while a video plays
  const v = vid();
  $("#wVideo").hidden = false;
  document.body.classList.add("w-watching");
  $("#wvTitle").textContent = it.kind === "tv" ? `${it.series || ""} · ${epCode(it)}` : it.title;
  const start = parseFloat(it.last_location) || 0;
  v.src = `/api/items/${it.id}/file`;
  v.onloadedmetadata = () => { if (start > 5 && start < v.duration - 10) v.currentTime = start; };
  v.play().catch(() => {});
  const i = V.eps.findIndex((x) => x.id === it.id);
  $("#wvPrev").disabled = i <= 0; $("#wvNext").disabled = i < 0 || i >= V.eps.length - 1;
  $("#wvQueue").hidden = V.eps.length < 2;
  paintVQueue();
  post0(`/api/items/${it.id}`, { opened: true });
}
function stepVideo(d) { const i = V.eps.findIndex((x) => x.id === V.it?.id); const n = V.eps[i + d]; if (n) playVideo(n.id); }
function closeVideo() {
  saveVideo(true);
  const v = vid(); v.pause(); v.removeAttribute("src"); v.load();
  V.it = null;
  $("#wVideo").hidden = true; $("#wvQueuePanel").hidden = true;
  document.body.classList.remove("w-watching");
  refresh().then(render);
}
function paintVQueue() {
  $("#wvQTitle").textContent = V.it?.kind === "tv" ? V.it.series || "Episodes" : V.it?.series || "Films";
  $("#wvQList").innerHTML = V.eps.map((e) => `<li class="${e.id === V.it?.id ? "q-now" : ""} ${e.watched ? "done" : ""}"><button class="q-go" data-vq="${e.id}"><b>${esc(e.kind === "tv" ? epCode(e) : e.title)}</b><span>${esc(e.kind === "tv" ? e.title : e.year || "")}${e.watched ? " · ✓" : (e.progress || 0) > 0.02 ? ` · ${Math.round(e.progress * 100)}%` : ""}</span></button></li>`).join("");
}
(() => {
  const v = vid();
  v.addEventListener("play", () => { $("#wvPlay").textContent = "❚❚"; $("#wVideo").classList.add("playing"); });
  v.addEventListener("pause", () => { $("#wvPlay").textContent = "▶"; $("#wVideo").classList.remove("playing"); saveVideo(true); });
  v.addEventListener("timeupdate", () => {
    $("#wvTime").textContent = `${fmtT(v.currentTime)} / ${fmtT(v.duration)}`;
    $("#wvFill").style.width = (v.duration ? (v.currentTime / v.duration) * 100 : 0) + "%";
    saveVideo(false);
  });
  v.addEventListener("ended", () => { if (V.it) post0(`/api/items/${V.it.id}`, { last_location: v.duration.toFixed(0), progress: 1 }); stepVideo(1); });
  v.addEventListener("click", () => (v.paused ? v.play() : v.pause()));
  $("#wvPlay").onclick = () => (v.paused ? v.play() : v.pause());
  $("#wvPrev").onclick = () => stepVideo(-1);
  $("#wvNext").onclick = () => stepVideo(1);
  $("#wvBack").onclick = closeVideo;
  $("#wvBig").onclick = () => { const id = V.it?.id; closeVideo(); if (id) openMain(id); };
  $("#wvSeek").onclick = (e) => { const r = e.currentTarget.getBoundingClientRect(); if (v.duration) v.currentTime = Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)) * v.duration; };
  $("#wvVol").oninput = (e) => { const p = Number(e.target.value); v.volume = p <= 0.004 ? 0 : Math.pow(10, (-36 * (1 - p)) / 20); try { localStorage.setItem("inkwell-wvol", p); } catch (er) {} };
  try { const p = parseFloat(localStorage.getItem("inkwell-wvol")); if (p >= 0 && p <= 1) { $("#wvVol").value = p; v.volume = p <= 0.004 ? 0 : Math.pow(10, (-36 * (1 - p)) / 20); } } catch (er) {}
  $("#wvQueue").onclick = () => { $("#wvQueuePanel").hidden = !$("#wvQueuePanel").hidden; paintVQueue(); };
  $("#wvQClose").onclick = () => { $("#wvQueuePanel").hidden = true; };
  $("#wvQList").onclick = (e) => { const b = e.target.closest("[data-vq]"); if (b) { $("#wvQueuePanel").hidden = true; playVideo(Number(b.dataset.vq)); } };
  document.addEventListener("keydown", (e) => {
    if ($("#wVideo").hidden || e.target.matches("input")) return;
    if (e.key === " ") { e.preventDefault(); v.paused ? v.play() : v.pause(); }
    else if (e.key === "ArrowRight") v.currentTime += 10;
    else if (e.key === "ArrowLeft") v.currentTime -= 10;
    else if (e.key === "Escape") closeVideo();
  });
  window.addEventListener("beforeunload", () => saveVideo(true));
})();

function render() {
  const list = $("#wList");
  if (tab === "music") return renderMusic(list);
  if (tab === "video") return renderVideo(list);
  if (q.trim()) {
    const words = q.toLowerCase().split(/\s+/).filter(Boolean);
    const hits = items.filter((it) => {
      const hay = [it.title, (it.authors || []).join(" "), (it.tags || []).join(" "), it.topic, it.genre, it.year].join(" ").toLowerCase();
      return words.every((w) => hay.includes(w));
    });
    $("#wTitle").textContent = "Search";
    list.innerHTML = hits.length ? hits.slice(0, 40).map(row).join("") : `<li class="w-empty">Nothing in your library matches “${esc(q)}”.</li>`;
    return;
  }
  $("#wTitle").textContent = "Recently read";
  const reading = items.filter((i) => ["book", "article", "graphic"].includes(i.kind));  // music, TV and films live in their own places
  const read = reading.filter((i) => i.opened_at).sort((a, b) => b.opened_at - a.opened_at).slice(0, 12);
  const fresh = reading.filter((i) => !i.opened_at).sort((a, b) => b.added_at - a.added_at).slice(0, Math.max(3, 8 - read.length));
  let html = read.map(row).join("");
  if (!read.length) html = `<li class="w-empty">Books and articles you open will show up here.</li>`;
  if (fresh.length) html += `<li class="w-sec">New in your library</li>` + fresh.map(row).join("");
  list.innerHTML = html;
}

// show the hidden title bar for a moment (when the widget appears), so it's clear where it went
function peekHead() {
  const h = $(".w-head");
  h.classList.add("peek");
  clearTimeout(peekHead.t);
  peekHead.t = setTimeout(() => h.classList.remove("peek"), 1800);
}

async function refresh() {
  try {
    const text = await (await fetch("/api/items")).text();
    const changed = text !== window._lastItems;
    window._lastItems = text;
    items = JSON.parse(text);
    const s = await (await fetch("/api/settings")).json();
    pinned = !!s.widget_locked;
    applyPin();
    const hide = s.widget_autohide !== false;          // title bar tucked away (Settings → Desktop widget)
    if (document.body.classList.contains("w-autohide") !== hide) {
      document.body.classList.toggle("w-autohide", hide);
      if (hide) peekHead();
    }
    const th = themeKey(s.theme);                     // follows the theme picked in Settings
    if (document.documentElement.dataset.theme !== th) {
      document.documentElement.dataset.theme = th;
      try { localStorage.setItem("inkwell-theme", th); } catch (e) {}
      render();
    }
    if (changed) render();
  } catch (e) { $("#wList").innerHTML = `<li class="w-empty">Babel's Library isn't running. Start it from the Babel's Library shortcut.</li>`; }
}

const post = (u, b) => fetch(u, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(b || {}) }).then((r) => r.json()).catch(() => ({}));

/* Read / Watch from the widget opens a separate reader window (the widget stays where it is). */
async function openReader(id) {
  const r = await post("/api/desktop/reader", { action: "open", id });
  if (!r.ok) window.open(`/?read=${id}&mini=1`, "inkwell-reader", "width=980,height=760");
}
async function openMain(readId) {
  const r = await post("/api/desktop/open-main", { read: readId || null, fullscreen: true });
  if (!r.ok) window.open("/" + (readId ? "?read=" + readId : ""), "_blank"); // running in a normal browser
}

$("#wSearch").addEventListener("input", (e) => { q = e.target.value; render(); });
$("#wSearch").addEventListener("keydown", (e) => {
  if (e.key === "Enter") { const first = $(".w-item"); if (first) { const it = items.find((x) => x.id === Number(first.dataset.id)); it && it.kind === "music" ? playHere(it.id) : openReader(it.id); } }
  if (e.key === "Escape") { e.target.value = q = ""; render(); }
});
/* music plays right here in the widget; books and video open the full app */
function albumOf(it) {
  const k = (x) => `${(x.album_artist || (x.authors || [])[0] || "").toLowerCase()}|${(x.album || "Singles").toLowerCase()}`;
  return items.filter((x) => x.kind === "music" && k(x) === k(it))
    .sort((a, b) => (a.disc || 1) - (b.disc || 1) || (a.track || 999) - (b.track || 999) || a.title.localeCompare(b.title));
}
function playHere(id) {
  const it = items.find((x) => x.id === id);
  if (!it) return;
  const al = albumOf(it);
  Player.playList(al.length ? al : [it], Math.max(0, al.findIndex((x) => x.id === id)));
}
$("#wTabs").addEventListener("click", (e) => { const b = e.target.closest("button[data-tab]"); if (b) setTab(b.dataset.tab); });
$("#wList").addEventListener("click", (e) => {
  if (tab === "music") { musicClick(e); return; }
  if (tab === "video") { const v = e.target.closest("[data-vid]"); if (v) { e.stopPropagation(); playVideo(Number(v.dataset.vid)); } return; }
  const lb = e.target.closest("[data-listen-id]");
  if (lb) { e.stopPropagation(); Player.playAudiobook(Number(lb.dataset.listenId)); return; }
  const rb = e.target.closest("[data-read-id]");
  if (rb) {
    e.stopPropagation();
    const it = items.find((x) => x.id === Number(rb.dataset.readId));
    if (it && it.kind === "music") playHere(it.id); else openReader(Number(rb.dataset.readId));
    return;
  }
  const li = e.target.closest(".w-item");
  if (!li) return;
  sel = Number(li.dataset.id);
  document.querySelectorAll(".w-item").forEach((x) => x.classList.toggle("sel", x === li));
});
document.addEventListener("dblclick", (e) => {
  if (e.target.closest("input,button,.w-corners,.w-read,.w-player,.w-tabs,.w-video") || tab === "music" || tab === "video") return;
  const li = e.target.closest(".w-item");
  const it = li && items.find((x) => x.id === Number(li.dataset.id));
  if (it && it.kind === "music") { playHere(it.id); return; }
  if (li && it && it.has_file) openReader(it.id); else openMain(null);
});
function applyPin() {
  $("#wPin").classList.toggle("on", pinned);
  $("#wPin").title = pinned ? "Pinned here. Click to unpin and move it again" : "Pin the widget here so it can't be moved";
  $(".w-head").classList.toggle("pywebview-drag-region", !pinned);
  $(".w-head").classList.toggle("locked", pinned);
  $("#wCorner").hidden = pinned;
  if (pinned) $("#wCorners").hidden = true;
}
$("#wPin").onclick = () => { pinned = !pinned; applyPin(); post("/api/desktop/widget", { action: "lock", value: pinned }); };
$("#wExpand").onclick = () => openMain(null);
window.inkwellRefresh = refresh;
$("#wCorner").onclick = () => { $("#wCorners").hidden = !$("#wCorners").hidden; };
$("#wCorners").onclick = (e) => { const b = e.target.closest("button"); if (!b) return; $("#wCorners").hidden = true; post("/api/desktop/widget", { action: "snap", value: b.dataset.corner }); };
$("#wClose").onclick = async () => { const r = await post("/api/desktop/widget", { action: "quit" }); if (!r.ok) window.close(); };

window.addEventListener("focus", refresh);
Player.bind({ remote: true, onChange: (st) => { $("#wFoot").hidden = !!(st.tracks && st.tracks.length); } });
$("#wSeek").addEventListener("click", (e) => {
  const r = e.currentTarget.getBoundingClientRect();
  Player.seek(Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)));
});
setTab(tab);
refresh();
setInterval(() => { if (!document.hidden) refresh(); }, 10000);
document.addEventListener("visibilitychange", () => {   // shown again: catch up at once (theme too)
  if (document.hidden) return;
  refresh();
  if (document.body.classList.contains("w-autohide")) peekHead();
});
