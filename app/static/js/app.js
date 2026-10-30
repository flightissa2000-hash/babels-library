/* Babel's Library — library UI */
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const hash = (s) => { let h = 2166136261; for (const c of String(s)) { h ^= c.charCodeAt(0); h = Math.imul(h, 16777619); } return h >>> 0; };

const api = {
  async get(u) { const r = await fetch(u); if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || r.statusText); return r.json(); },
  async send(method, u, body) {
    const r = await fetch(u, { method, headers: { "Content-Type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body) });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.error || r.statusText);
    return j;
  },
};

const KIND_LABEL = { article: "Articles", book: "Books", graphic: "Graphic novels", music: "Music", tv: "TV", movie: "Movies" };
const COMIC_TYPES = ["cbz", "cbr", "cb7", "cbt"];
const READ_KINDS = ["article", "book", "graphic"], MEDIA_KINDS = ["music", "tv", "movie"];
const VIDEO_KINDS = ["tv", "movie"];
const AREA_KINDS = { books: ["book", "graphic"], articles: ["article"], music: ["music"], video: VIDEO_KINDS, journal: [] };
const READ_AREAS = ["books", "articles"];
const MINI = new URLSearchParams(location.search).has("mini");  // the separate reader window opened from the widget
if (MINI) document.documentElement.classList.add("mini");
const areaKinds = () => AREA_KINDS[S.area] || AREA_KINDS.books;
let TAX = { genres: {}, subjects: [], topics: [] };
const S = {
  items: [], settings: {}, kind: "all", q: "", tag: null, area: "books", home: true,      // (the app opens on the Bulletin)
  groupBy: "auto", sortBy: "added", view: "shelf", heistSel: null, openId: null,
};

function toast(msg, kind = "") {
  const t = document.createElement("div");
  t.className = "toast " + kind;
  t.textContent = msg;
  $("#toasts").append(t);
  setTimeout(() => t.remove(), kind === "error" ? 7000 : 4200);
}

/* a small question with a few answers; resolves to the chosen answer's value, or null if it's dismissed */
function askKeep(title, text, answers) {
  return new Promise((done) => {
    const w = document.createElement("div");
    w.className = "keep-ask";
    w.innerHTML = `<div class="ka-card" role="dialog"><h3>${esc(title)}</h3><p>${esc(text)}</p><div class="ka-row">${answers.map(([l, v, cls], i) => `<button class="btn ${cls || ""}" data-i="${i}">${esc(l)}</button>`).join("")}</div></div>`;
    const end = (v) => { w.remove(); removeEventListener("keydown", key, true); done(v); };
    const key = (e) => { if (e.key === "Escape") { e.stopPropagation(); end(null); } };
    w.onclick = (e) => { const b = e.target.closest("[data-i]"); if (b) end(answers[Number(b.dataset.i)][1]); else if (e.target === w) end(null); };
    addEventListener("keydown", key, true);
    document.body.append(w);
    w.querySelector("button")?.focus();
  });
}

/* sending one volume of a series (or episode of a show) to the phone: which of the others go too? Resolves to the
   items to send, or null if it's dismissed */
function pickSeries(it) {
  const k = it && inSeries(it) && seriesKey(it.series);
  const rest = !k ? [] : S.items.filter((x) => x.id !== it.id && x.has_file && inSeries(x) && seriesKey(x.series) === k);
  if (!rest.length) return Promise.resolve(it ? [it] : []);
  const all = [it, ...rest].sort(seriesOrder);
  const label = (x) => x.kind === "tv" && x.season != null ? `S${x.season}${x.episode != null ? " E" + x.episode : ""} · ${x.title}` : x.title;
  return new Promise((done) => {
    const w = document.createElement("div");
    w.className = "keep-ask";
    w.innerHTML = `<form class="ka-card sp-card" role="dialog"><h3>Send more of “${esc(it.series)}”?</h3>
      <p>Tick what your phone should fetch (tick a later one and everything in between comes too).</p>
      <div class="sp-quick"><button type="button" class="btn sm" data-sp="all">All</button><button type="button" class="btn sm" data-sp="none">Only this one</button></div>
      <div class="sp-list">${all.map((x) => `<label class="sp-row ${x.id === it.id ? "first" : ""}"><input type="checkbox" value="${x.id}" ${x.id === it.id ? "checked" : ""}><span>${esc(label(x))}</span></label>`).join("")}</div>
      <div class="ka-row"><button type="button" class="btn" data-x>Cancel</button><button class="btn primary" data-sp-go></button></div></form>`;
    const boxes = [...w.querySelectorAll(".sp-list input")];
    const picked = () => boxes.filter((b) => b.checked).map((b) => all.find((x) => x.id === Number(b.value)));
    const paint = () => { const n = picked().length, go = w.querySelector("[data-sp-go]"); go.disabled = !n; go.textContent = n ? `📱 Send ${n}` : "Tick something to send"; };
    const end = (v) => { w.remove(); removeEventListener("keydown", key, true); done(v); };
    const key = (e) => { if (e.key === "Escape") { e.stopPropagation(); end(null); } };
    let last = all.indexOf(it);           // (tick one, then another further down: everything between comes too)
    w.addEventListener("click", (e) => {
      const q = e.target.closest("[data-sp]");
      if (q) { boxes.forEach((b) => (b.checked = q.dataset.sp === "all" || Number(b.value) === it.id)); paint(); }
      if (e.target.closest("[data-x]") || e.target === w) end(null);
    });
    w.addEventListener("change", (e) => {
      const i = boxes.indexOf(e.target);
      if (i < 0) return;
      if (e.target.checked && last != null && last !== i && boxes[last].checked) {
        const [a, b] = last < i ? [last, i] : [i, last];
        for (let j = a; j <= b; j++) boxes[j].checked = true;
      }
      last = e.target.checked ? i : null;
      paint();
    });
    w.querySelector("form").onsubmit = (e) => { e.preventDefault(); const p = picked(); end(p.length ? p : null); };
    addEventListener("keydown", key, true);
    paint();
    document.body.append(w);
  });
}

/* articles kept for 30 days: a few days before one is due to go, ask whether to delete it or keep it longer */
const EXPIRY = { asking: false, later: {} };
async function checkExpiring() {
  if (EXPIRY.asking) return;
  // the browser's page is its own window on top of this one and would hide the question: ask once it's closed
  if (window.Browser && Browser.on) { clearTimeout(EXPIRY.wait); EXPIRY.wait = setTimeout(checkExpiring, 60000); return; }
  let l;
  try { l = (await api.get("/api/expiring")).items || []; } catch (e) { return; }
  EXPIRY.asking = true;
  try {
    for (const it of l) {
      if ((EXPIRY.later[it.id] || 0) > Date.now()) continue;
      const left = Math.max(0, Math.ceil((it.expires_at - Date.now() / 1000) / 86400));
      const a = await askKeep(`“${it.title || "An article"}” is due to be removed`,
        left ? `You kept it for 30 days; that's up in ${left} day${left > 1 ? "s" : ""}. Delete it then, or keep it longer?` : "You kept it for 30 days and the time's up. Delete it now, or keep it longer?",
        [["Keep 30 more days", "extend"], ["Keep for good", "keep"], [left ? "Delete it now" : "Delete it", "delete", "danger"], ["Ask me later", "later"]]);
      if (a == null || a === "later") { EXPIRY.later[it.id] = Date.now() + 6 * 3600e3; continue; }
      const r = await api.send("POST", `/api/items/${it.id}/expire`, { action: a });
      toast(a === "delete" ? `Removed${r.went ? ` (the file is in ${r.went})` : ""}` : a === "keep" ? "Kept for good" : "Kept for another 30 days");
      if (a === "delete") loadItems();
    }
  } finally { EXPIRY.asking = false; }
}

/* ---------------- helpers ---------------- */
const lastName = (n) => { n = (n || "").trim(); if (n.includes(",")) return n.split(",")[0].trim(); const p = n.split(/\s+/); return p[p.length - 1] || ""; };
const authorLine = (it) => { const a = it.authors || []; if (!a.length) return VIDEO_KINDS.includes(it.kind) ? (it.kind === "tv" ? it.series || "" : "") : it.kind === "music" ? "Unknown artist" : it.kind === "graphic" ? (it.publisher || "Creators not listed") : it.publisher && it.kind === "book" ? it.publisher : "Unknown author"; if (a.length === 1) return a[0]; if (a.length === 2) return a.join(" & "); return `${a[0]} et al.`; };
const theme = () => THEMES[document.documentElement.dataset.theme] || THEMES.wordtown;
const colorFor = (it) => { const p = theme().spines; return p[hash(it.id + (it.title || "")) % p.length]; };

function groupKeys(it) {
  switch (S.groupBy) {
    case "auto":
      if (it.fiction === 1 && it.kind !== "article") return [it.genre || "Fiction"];
      return [it.topic || "General Works"];
    case "topic": return [it.topic || "General Works"];
    case "journal": return [it.journal || "No journal listed"];
    case "genre": return it.kind === "article" ? [] : [it.genre || "Unknown genre"];
    case "subject": return [TAX.subjects.includes(it.subject) ? it.subject : "General Works"];
    case "series": return it.kind === "article" ? [] : [it.series || "Not in a series"];
    case "fiction": return [it.fiction === 1 ? "Fiction" : (it.fiction === 0 || it.kind === "article") ? "Non-fiction" : "Not yet known"];
    case "year": return [it.year || "Undated"];
    case "author": return [(it.authors || [])[0] ? lastName(it.authors[0]) + (it.authors[0].includes(",") ? "" : ", " + it.authors[0].split(/\s+/).slice(0, -1).join(" ")).replace(/, $/, "") : "Unknown author"];
    case "tag": return (it.tags && it.tags.length) ? it.tags : ["Untagged"];
    case "collection": return (it.collections || []).length ? it.collections.map((c) => Coll.nameOf(c) || "Collection") : ["Not in a collection"];
    case "kind": return [it.kind === "graphic" && it.format === "manga" ? "Graphic novels: Manga" : (KIND_LABEL[it.kind] || "Articles")];
    default: return ["Everything"];
  }
}

function sortItems(arr) {
  const by = {
    added: (a, b) => (b.added_at || 0) - (a.added_at || 0),
    opened: (a, b) => (b.opened_at || 0) - (a.opened_at || 0),
    title: (a, b) => (a.title || "").localeCompare(b.title || ""),
    author: (a, b) => lastName((a.authors || [""])[0]).localeCompare(lastName((b.authors || [""])[0])),
    "year-desc": (a, b) => (parseInt(b.year) || 0) - (parseInt(a.year) || 0),
    "year-asc": (a, b) => (parseInt(a.year) || 9999) - (parseInt(b.year) || 9999),
    notes: (a, b) => (b.ann_count || 0) - (a.ann_count || 0),
  }[S.sortBy];
  return arr.sort(by);
}

// the Books area splits graphic novels into manga and (western) comics
// an article saved from the web, or one from a news outlet (and no DOI), is a news story; the rest are papers
const isNewsStory = (it) => it.kind === "article" && (it.source === "web" || (it.source !== "paper" && !it.doi && /news|times|post|guardian|bbc|npr|reuters|apnews|propublica|tribune|herald|gazette|journal\.com|magazine|patch\.com|phys\.org|sciencedaily/i.test((it.url || "") + " " + (it.journal || ""))));
const kindMatches = (it, k) => k === "manga" ? it.kind === "graphic" && it.format === "manga"
  : k === "comic" ? it.kind === "graphic" && it.format !== "manga"
  : k === "paper" ? it.kind === "article" && !isNewsStory(it) : k === "news" ? isNewsStory(it) : it.kind === k;
const KIND_TABS = { books: [["book", "Books"], ["manga", "Manga"], ["comic", "Comics"]], articles: [["paper", "Scientific papers"], ["news", "News stories"]] };

function filtered() {
  const q = S.q.toLowerCase().trim();
  const kinds = areaKinds();
  return S.items.filter((it) => {
    if (!kinds.includes(it.kind)) return false;
    if (S.kind !== "all" && !kindMatches(it, S.kind)) return false;
    if (S.tag && !(it.tags || []).includes(S.tag)) return false;
    const wish = it.wanted && !it.has_file;          // (wanted, not owned: only in the Wishlist, never among what's here)
    if (S.coll === "wish") { if (!wish) return false; }
    else if (wish || (S.coll && !(it.collections || []).includes(S.coll))) return false;
    if (!q) return true;
    const hay = [it.title, (it.authors || []).join(" "), (it.tags || []).join(" "), it.topic, it.genre, it.subject, it.journal, it.year, it.publisher, it.series, it.album, it.album_artist].join(" ").toLowerCase();
    return q.split(/\s+/).every((w) => hay.includes(w));
  });
}

/* the Series field: a list of the series already in the library (only ones that still have something in them) */
function seriesSelect(it) {
  const group = it.kind === "tv" ? ["tv"] : it.kind === "movie" ? ["movie"] : ["book", "graphic"];
  const names = new Map();
  for (const x of S.items) {
    if (!x.series || !group.includes(x.kind) || !x.series.trim()) continue;
    const k = x.series.trim().toLowerCase();
    if (!names.has(k)) names.set(k, { name: x.series.trim(), n: 0 });
    names.get(k).n++;
  }
  const cur = (it.series || "").trim();
  const list = [...names.values()].sort((a, b) => a.name.localeCompare(b.name));
  return `<select name="series">
    <option value="" ${!cur ? "selected" : ""}>Not in a series</option>
    ${list.map((o) => `<option value="${esc(o.name)}" ${o.name.toLowerCase() === cur.toLowerCase() ? "selected" : ""}>${esc(o.name)} (${o.n})</option>`).join("")}
    <option value="__new">＋ New series…</option>
  </select>`;
}

/* ---------- series: always shown together, in order ---------- */
const seriesKey = (s) => (s || "").toLowerCase().replace(/^the\s+/, "")
  .replace(/\b(series|trilogy|chronicles?|saga|cycle|novels?|books|universe|sequence|quartet|quintet|duology)\b/g, " ").replace(/[^a-z0-9]+/g, "");
const inSeries = (it) => it.kind !== "article" && !!seriesKey(it.series);
const seriesOrder = (x, y) => (x.series_index ?? 999) - (y.series_index ?? 999) || (parseInt(x.year) || 9999) - (parseInt(y.year) || 9999) || (x.title || "").localeCompare(y.title || "");
const seriesHue = (s) => hash(seriesKey(s)) % 360;
function clusterSeries(items) {
  const out = [], seen = new Set();
  for (const it of items) {
    if (!inSeries(it)) { out.push(it); continue; }
    const k = seriesKey(it.series);
    if (seen.has(k)) continue;
    seen.add(k);
    out.push(...items.filter((x) => inSeries(x) && seriesKey(x.series) === k).sort(seriesOrder));
  }
  return out;
}

function grouped() {
  const map = new Map();
  const list = sortItems(filtered());
  // every book in a series goes in the same group as the series' first book, so the series stays together
  const lead = new Map();
  if (!["series", "tag", "collection"].includes(S.groupBy))
    for (const it of list) if (inSeries(it)) { const k = seriesKey(it.series), cur = lead.get(k); if (!cur || seriesOrder(it, cur) < 0) lead.set(k, it); }
  for (const it of list) {
    const keys = inSeries(it) && lead.has(seriesKey(it.series)) ? groupKeys(lead.get(seriesKey(it.series))) : groupKeys(it);
    for (const k of keys) { if (!map.has(k)) map.set(k, []); map.get(k).push(it); }
  }
  for (const [k, items] of map) map.set(k, clusterSeries(items));
  let groups = [...map.entries()];
  if (S.groupBy === "year") groups.sort((a, b) => (parseInt(b[0]) || 0) - (parseInt(a[0]) || 0));
  else if (S.groupBy === "author") groups.sort((a, b) => a[0].localeCompare(b[0]));
  else if (S.groupBy === "subject") groups.sort((a, b) => TAX.subjects.indexOf(a[0]) - TAX.subjects.indexOf(b[0]));
  else if (S.groupBy === "series") {
    groups.sort((a, b) => (a[0] === "Not in a series") - (b[0] === "Not in a series") || a[0].localeCompare(b[0]));
    for (const g of groups) g[1].sort((x, y) => (x.series_index || 999) - (y.series_index || 999) || (parseInt(x.year) || 0) - (parseInt(y.year) || 0));
  }
  else groups.sort((a, b) => b[1].length - a[1].length || a[0].localeCompare(b[0]));
  return groups;
}

/* a series is one stack in the library until you open it out; the ones opened out are remembered */
const openedSeries = () => { try { return JSON.parse(localStorage.getItem("inkwell-unfolded") || "[]"); } catch (e) { return []; } };
function seriesFolded(k) { return !openedSeries().includes(k); }
function toggleSeriesFold(k) {
  let f = openedSeries();
  f = f.includes(k) ? f.filter((x) => x !== k) : [...f, k];
  try { localStorage.setItem("inkwell-unfolded", JSON.stringify(f)); } catch (e) {}
  const el = document.querySelector(`.heist-series[data-series-key="${CSS.escape(k)}"]`);
  if (el) { el.classList.toggle("folded", !f.includes(k)); el.querySelector(".hs-head").setAttribute("aria-expanded", String(f.includes(k))); }
  else renderLib();
}
// the book a folded series shows on top of its stack: the next one to read
const seriesNext = (run) => run.find((x) => jstat(x) !== "finished" && !(x.progress > 0.97)) || run[0];
document.addEventListener("click", (e) => {
  const b = e.target.closest("[data-fold-series],[data-fold-open]");
  if (!b) return;
  e.stopPropagation();
  toggleSeriesFold(b.dataset.foldSeries || b.dataset.foldOpen);
}, true);

function seriesRuns(items) {
  const runs = [];
  for (const it of items) {
    const last = runs[runs.length - 1];
    if (last && inSeries(it) && inSeries(last[0]) && seriesKey(last[0].series) === seriesKey(it.series)) last.push(it);
    else runs.push([it]);
  }
  return runs;
}

const ransom = (s) => esc(s).split(/\s+/).map((w) => `<span class="rl">${w}</span>`).join(" ");

function coverHTML(it) {
  if (it.has_cover) return `<div class="cover" style="--c:${colorFor(it)}"><img loading="lazy" alt="" src="/api/items/${it.id}/cover?v=${it.cover_v || it._cv || 0}"></div>`;
  return `<div class="cover" style="--c:${colorFor(it)}"><div class="gen-cover"><div class="t">${esc(it.title || "Untitled")}</div><div class="a">${esc(authorLine(it))}</div><div class="k">${it.physical && !it.has_file ? "on your shelf" : it.kind}</div></div></div>`;
}

/* New arrivals come gift-wrapped (like the DS's presents): on the home page the whole info block of something new is
   a present until you unwrap it (click). Remembered on this computer. */
const UNWRAPPED = new Set((() => { try { return JSON.parse(localStorage.getItem("inkwell-unwrapped") || "[]"); } catch (e) { return []; } })());
// only things that arrive after wrapping began count (the library's own import dates can be refreshed by a rescan)
const GIFT_SINCE = (() => { let t = 0; try { t = +localStorage.getItem("inkwell-gift-since") || 0; if (!t) localStorage.setItem("inkwell-gift-since", t = Math.floor(Date.now() / 1000)); } catch (e) { t = Date.now() / 1000; } return t; })();
const isGift = (it) => !!it && it.has_file && it.kind !== "music" && !it.opened_at && !(it.progress > 0) && !it.watched
  && (it.added_at || 0) > Math.max(GIFT_SINCE, Date.now() / 1000 - 21 * 86400) && !UNWRAPPED.has(it.id);
const GIFT_WHAT = { book: "a book", graphic: "a comic", article: "an article", movie: "a film", tv: "a TV episode" };
/* the present itself: two halves of paper, a ribbon, a bow and a gift tag, laid over the info block */
function presentHTML(it) {
  if (!isGift(it)) return "";
  const what = it.kind === "graphic" && it.format === "manga" ? "a manga" : GIFT_WHAT[it.kind] || "something";
  return `<div class="present" data-gift="${it.id}" role="button" title="Something new: click to unwrap">
    <i class="p-half l"></i><i class="p-half r"></i><i class="p-rib-v"></i><i class="p-rib-h"></i>
    <span class="p-bow"><i class="lp l"></i><i class="lp r"></i><i class="tl l"></i><i class="tl r"></i><i class="knot"></i></span>
    <span class="p-tag"><i class="p-hole"></i><small>To: you</small><b>It's ${what}!</b><small>From: Babel's Library</small><em>click to unwrap</em></span>
    ${[[12, 16, 0], [82, 12, .7], [22, 72, 1.3], [88, 64, .4], [60, 86, 1.7], [40, 8, 1]].map(([x, y, d]) => `<i class="p-sp" style="left:${x}%;top:${y}%;animation-delay:${d}s"></i>`).join("")}
    <span class="p-fx"></span></div>`;
}
document.addEventListener("click", (e) => {
  const g = e.target.closest(".present");
  if (!g || g.classList.contains("open")) return;
  e.preventDefault(); e.stopPropagation();
  const id = Number(g.dataset.gift);
  UNWRAPPED.add(id);
  try { localStorage.setItem("inkwell-unwrapped", JSON.stringify([...UNWRAPPED].slice(-2000))); } catch (err) {}
  g.classList.add("open");
  Wheel.unwrapped.add(id);                  // it stays on "New additions" until you leave the tab
  setTimeout(() => { g.remove(); if (S.home && $("#hwWheel")) Wheel.render($("#library")); }, 1100);
}, true);

const tagChips = (it, n = 3) => (it.tags || []).slice(0, n).map((t) => `<span class="tagchip" data-tag="${esc(t)}">${esc(t)}</span>`).join("");

/* ---------------- views ---------------- */
const VIEWS = {
  /* Card catalogue: each group is a drawer of index cards; hover a card to pull it up. */
  catalog(groups) {
    const LCC = { "General Works": "A", "Philosophy, Psychology & Religion": "B", "History": "D", "Geography, Anthropology & Recreation": "G", "Social Sciences": "H", "Political Science": "J", "Law": "K", "Education": "L", "Music": "M", "Fine Arts": "N", "Language & Literature": "P", "Science": "Q", "Medicine": "R", "Agriculture": "S", "Technology & Engineering": "T", "Military & Naval Science": "U", "Bibliography & Library Science": "Z" };
    const call = (it) => {
      const cls = (LCC[it.subject] || "A") + (it.kind === "graphic" ? "N" : it.fiction === 1 ? "Z" : "") + (hash(it.topic || it.subject || "") % 900 + 10);
      const who = (lastName((it.authors || [""])[0]) || it.title || "X").replace(/[^A-Za-z]/g, "").toUpperCase();
      return `${cls} .${who[0] || "X"}${hash(it.id + "c") % 90 + 10}${it.year ? " " + esc(it.year) : ""}`;
    };
    return `<div class="catalog">` + groups.map(([name, items]) => `
      <section class="cdrawer ${items.length > 4 ? "wide" : ""}" style="--n:${Math.min(items.length, 12)}">
        <div class="cfront"><span class="clabel"><b>${esc(name)}</b><small>${items.length} card${items.length === 1 ? "" : "s"}</small></span><span class="cpull"></span></div>
        <div class="cstack">
          ${seriesRuns(items).flatMap((run) => {
            // a series is one card (the next to read) with the rest stacked behind it, until opened out
            if (run.length < 2) return run.map((it) => [it, null]);
            const k = seriesKey(run[0].series);
            return seriesFolded(k) ? [[seriesNext(run), { k, n: run.length, shut: true }]] : run.map((it, j) => [it, j === 0 ? { k, n: run.length, shut: false } : null]);
          }).map(([it, st], i) => `<button class="icard ${i === 0 ? "open" : ""} ${inSeries(it) ? "in-series" : ""} ${st && st.shut ? "stack" : ""}" data-open="${it.id}" style="--i:${i};--c:${colorFor(it)};--sh:${inSeries(it) ? seriesHue(it.series) : 0}">
            <span class="ic-head"><span class="ic-call">${call(it)}</span><span class="ic-title">${esc(it.title || "Untitled")}</span>${inSeries(it) ? `<span class="ic-series">${esc(it.series)}${it.series_index ? ` · ${+it.series_index}` : ""}</span>` : ""}${st ? `<span class="ic-stackn" data-fold-series="${esc(st.k)}" title="${st.shut ? "Show every book in this series" : "Stack this series back up"}">${st.shut ? `📚 ${st.n} in series ▸` : `▴ stack the ${st.n}`}</span>` : ""}${it.audio_status === "ready" ? `<span class="ic-ab" title="Audiobook available">🎧</span>` : ""}</span>
            <span class="ic-body">
              <span class="ic-thumb">${coverHTML(it)}</span>
              <span class="ic-text">
                <span class="ic-line"><b>${esc((it.authors || []).join("; ") || authorLine(it))}</b></span>
                <span class="ic-line">${esc([it.publisher || it.journal, it.year].filter(Boolean).join(", "))}${it.series ? ` · ${esc(it.series)}${it.series_index ? " " + +it.series_index : ""}` : ""}</span>
                <span class="ic-line ic-subj">${esc([it.subject, it.kind === "article" ? it.topic : it.genre].filter(Boolean).join(" — "))}</span>
                ${(it.tags || []).length ? `<span class="ic-line ic-tags">${(it.tags || []).slice(0, 4).map((t, k) => `${k + 1}. ${esc(t)}`).join("  ")}</span>` : ""}
                ${it.summary ? `<span class="ic-syn"><em>${it.kind === "article" ? "Abstract" : "Synopsis"}.</em> ${esc(it.summary.length > 700 ? it.summary.slice(0, 700).replace(/\s+\S*$/, "") + "…" : it.summary)}</span>` : `<span class="ic-syn none">No ${it.kind === "article" ? "abstract" : "synopsis"} yet.</span>`}
                ${(() => { const st = jstat(it); return st === "dropped" ? `<span class="ic-stamp dropped">DROPPED${it.progress > 0.02 ? " · " + Math.round(it.progress * 100) + "%" : ""}</span>`
                  : st === "finished" || it.progress > 0.97 ? `<span class="ic-stamp">READ</span>`
                  : st === "hold" ? `<span class="ic-stamp">ON HOLD</span>`
                  : st === "reading" ? `<span class="ic-stamp">ON LOAN${it.progress > 0.02 ? " · " + Math.round(it.progress * 100) + "%" : ""}</span>` : ""; })()}
              </span>
            </span>
            <span class="ic-hole"></span>
          </button>`).join("")}
        </div>
      </section>`).join("") + `</div>`;
  },
  heist(groups) {
    const all = groups.flatMap(([, items]) => items);
    S._hi = 0;
    if (!all.find((i) => i.id === S.heistSel)) S.heistSel = all[0]?.id;
    const KB = { article: "Article", book: "Book", graphic: "Comic" };
    const thumb = (it) => it.has_cover
      ? `<span class="hthumb" style="--c:${colorFor(it)}"><img loading="lazy" alt="" src="/api/items/${it.id}/cover?v=${it.cover_v || it._cv || 0}"></span>`
      : `<span class="hthumb gen" style="--c:${colorFor(it)}"><b>${esc((it.title || "?").trim()[0] || "?")}</b></span>`;
    return `<div class="heist"><div class="heist-list">${groups.map(([name, items], gi) => `
        <div class="heist-group" style="--gi:${gi % 6}"><span class="hg-name">${ransom(name)}</span><span class="hg-count">${items.length}</span><span class="hg-rule"></span></div>
        ${seriesRuns(items).map((run) => run.length > 1
          ? (() => {
              const k = seriesKey(run[0].series), shut = seriesFolded(k);
              const next = run.find((x) => jstat(x) !== "finished" && !(x.progress > 0.97)) || null;
              return `<div class="heist-series ${shut ? "folded" : ""}" data-series-key="${esc(k)}" style="--sh:${seriesHue(run[0].series)}">
                <button class="hs-head" data-fold-series="${esc(k)}" aria-expanded="${!shut}" title="${shut ? "Show" : "Hide"} the books in this series"><span class="hs-chev">▾</span><b>${esc(run[0].series)}</b><span class="hs-n">${run.length} books</span></button>
                <div class="hs-fold" data-fold-open="${esc(k)}">${run.slice(0, 8).map((x) => x.has_cover ? `<img alt="" loading="lazy" src="/api/items/${x.id}/cover?v=${x.cover_v || x._cv || 0}">` : `<i style="--c:${colorFor(x)}"></i>`).join("")}
                  <span>${next ? `Up next: <b>${next.series_index ? "#" + +next.series_index + " " : ""}${esc(next.title)}</b>` : "All read"}</span></div>
                <div class="hs-rows">${run.map(row).join("")}</div></div>`;
            })()
          : row(run[0])).join("")}`).join("")}
      </div><div class="heist-stage" id="heistStage"></div></div>`;
    function row(it) {
          const by = (it.authors || []).length ? authorLine(it) : (it.publisher || "");
          const pct = Math.round((it.progress || 0) * 100);
          const kind = it.kind === "graphic" && it.format === "manga" ? "Manga" : KB[it.kind] || "";
          return `<button class="heist-row ${it.id === S.heistSel ? "sel" : ""} ${inSeries(it) ? "in-series" : ""} ${jstat(it) === "dropped" ? "is-dropped" : ""} ${it.wanted && !it.has_file ? "is-wanted" : ""}" data-heist="${it.id}" data-open="${it.id}" style="--sh:${inSeries(it) ? seriesHue(it.series) : 0};--d:${Math.min(S._hi = (S._hi || 0) + 1, 30) * 28}ms;--c:${colorFor(it)}">
          ${inSeries(it) ? `<span class="hs-num" title="${esc(it.series)}${it.series_index ? " #" + +it.series_index : ""}">${it.series_index ? +it.series_index : "·"}</span>` : ""}${thumb(it)}
          <span class="hbody"><span class="ht">${esc(it.title || "Untitled")}${it.audio_status === "ready" ? " 🎧" : ""}</span>
            <span class="hsub">${by ? `<span>${esc(by)}</span>` : ""}${it.year ? `<span>${esc(it.year)}</span>` : ""}${inSeries(it) ? `<span class="hs-tag">${it.series_index ? `#${+it.series_index} in ` : ""}${esc(it.series)}</span>` : ""}</span></span>
          <span class="hside">${it.wanted && !it.has_file ? `<span class="hstat st-wanted" title="On your wishlist">Wanted</span>` : ""}${(() => { const st = jstat(it); return st === "reading" || st === "dropped" || st === "hold" ? `<span class="hstat st-${st}" title="${{ reading: "In progress", dropped: "Dropped", hold: "On hold" }[st]}">${{ reading: "Reading", dropped: "Dropped", hold: "On hold" }[st]}</span>` : ""; })()}${kind ? `<span class="hkind k-${it.kind}">${kind}</span>` : ""}${it.ann_count ? `<span class="hnotes" title="${it.ann_count} annotations">✎ ${it.ann_count}</span>` : ""}<span class="hmark">★</span></span>
          ${pct > 1 ? `<span class="hprog" title="${pct}% read"><i style="width:${pct}%"></i></span>` : ""}
        </button>`;
    }
  },
};

function renderStage() {
  const el = $("#heistStage");
  const it = S.items.find((i) => i.id === S.heistSel);
  if (!el || !it) return;
  el.innerHTML = `<div class="burst"></div><div class="halftone"></div><div class="card-tag">NEXT TARGET</div><div class="stage-in" key="${it.id}">${coverHTML(it)}<div>
    <h3>${ransom(it.title || "Untitled")}</h3>
    <div class="meta">${esc((it.authors || []).join(", ") || authorLine(it))}${it.year ? " · " + esc(it.year) : ""}<br>${esc(it.kind === "article" ? it.topic || "" : it.genre || "")}${inSeries(it) ? ` · ${it.series_index ? `Book ${+it.series_index} of ` : ""}${esc(it.series)}` : ""}</div>
    <p class="sum">${esc(it.summary || "")}</p>
    <div>${tagChips(it, 8)}</div>
    <div class="d-actions">${it.wanted && !it.has_file ? `<span class="wanted-stamp">WANTED</span><button class="btn primary" data-own="${it.id}" title="Put it on your shelf as a physical copy">I own it (physical copy)</button>${it.url ? `<button class="btn" data-dv-find="${esc(it.url)}">Find it online</button>` : ""}` : ""}${it.has_file ? `<button class="btn primary" data-read="${it.id}">Read</button>` : ""}${it.audio_status === "ready" ? `<button class="btn" data-listen="${it.id}">🎧 Listen</button>` : ""}<button class="btn" data-detail="${it.id}">Details & citations</button></div>
  </div></div><div class="stage-jr" id="stageJr" data-id="${it.id}"></div>`;
  Journal.paintStage(it);
}

function render() {
  renderLib();
  Coll.paintBar();
  Coll.paintSel();
}
/* ---------------- home: what you were last reading and watching ---------------- */
const byOpened = (a, b) => (b.opened_at || 0) - (a.opened_at || 0);
const pctOf = (it) => Math.round(Math.min(1, it.watched ? 1 : it.progress || 0) * 100);
function nextEpisode(ep) {
  // the episode to carry on with: this one if it isn't finished, else the next unwatched one in the show
  if (!(ep.watched || (ep.progress || 0) > 0.92)) return ep;
  const eps = S.items.filter((x) => x.kind === "tv" && seriesKey(x.series) === seriesKey(ep.series))
    .sort((a, b) => (a.season || 1) - (b.season || 1) || (a.episode || 0) - (b.episode || 0));
  const i = eps.findIndex((x) => x.id === ep.id);
  return eps.slice(i + 1).find((x) => !x.watched) || null;
}
function homeCard(it, kindLabel) {
  const pct = pctOf(it);
  const by = it.kind === "tv" ? `${it.series || ""}` : authorLine(it);
  const sub = it.kind === "tv" ? `S${it.season || 1} · E${it.episode ?? "?"}${it.title && !/^Episode \d+$/.test(it.title) ? " · " + it.title : ""}` : it.year || "";
  const verb = VIDEO_KINDS.includes(it.kind) ? (pct > 1 ? "Keep watching" : "Watch") : pct > 1 ? "Keep reading" : "Read";
  return `<article class="home-card k-${it.kind}">
    <button class="home-cov" data-detail="${it.id}" title="Details">${coverHTML(it)}</button>
    <div class="home-txt"><span class="home-kind">${esc(kindLabel)}</span><h3>${esc(it.kind === "tv" ? it.series || it.title : it.title || "Untitled")}</h3>
      <p>${esc([by, sub].filter(Boolean).join(" · "))}</p>
      <div class="home-prog" title="${pct}%"><i style="width:${pct}%"></i></div><small>${pct ? pct + "%" : "Not started"}${it.opened_at ? " · " + ago(it.opened_at) : ""}</small>
      ${it.has_file ? `<button class="btn sm primary" data-read="${it.id}">${verb}</button>` : ""}</div></article>`;
}
function ago(t) {
  const s = Date.now() / 1000 - t;
  return s < 3600 ? "just now" : s < 86400 ? Math.round(s / 3600) + " h ago" : s < 86400 * 14 ? Math.round(s / 86400) + " days ago" : new Date(t * 1000).toLocaleDateString();
}
function leaveHome() {
  S.home = false;
  $$("#areaSeg button").forEach((b) => b.classList.toggle("on", b.dataset.area === S.area));
}
function renderHome(lib) {
  Wheel.render(lib);
  queueCovers();
}

/* Home → The Bulletin: a weekly newsletter. This week's challenge (finish something you're partway through, or revisit
   something you finished long ago; it gets a stamp when you do), articles on your shelves you haven't opened, and a few
   things from the catalogue you don't have yet. Everything is picked once a week (the same all week). */
const Bulletin = (() => {
  const DAY = 86400;
  const weekStart = () => { const d = new Date(); d.setHours(0, 0, 0, 0); d.setDate(d.getDate() - ((d.getDay() + 6) % 7)); return d.getTime() / 1000; };
  const rng = (seed) => { let a = 0; for (const c of String(seed)) a = (a * 31 + c.charCodeAt(0)) >>> 0; return () => { a |= 0; a = (a + 0x6D2B79F5) | 0; let t = Math.imul(a ^ (a >>> 15), 1 | a); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; };
  const shuffle = (list, r) => { const a = [...list]; for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(r() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; } return a; };
  let srv;                     // this profile's challenge, as the computer keeps it (shared with its phones)
  const load = () => srv || null;
  const save = (c) => { srv = c; api.send("POST", "/api/bulletin", c).catch(() => {}); };
  let picks = null;            // the catalogue's suggestions, fetched once per visit

  function finishedAt(it) {
    const j = Journal.rowFor ? Journal.rowFor(it) : null;
    const f = j && j.finished ? Date.parse(j.finished) / 1000 : 0;
    return f || it.watched_at || (pctOf(it) >= 98 ? it.opened_at : 0) || 0;
  }
  /* this week's challenge: kept all week; "Pick another" draws again */
  /* a series is read in order: whatever volume turns up, the suggestion is the first one on your shelves that you
     haven't finished */
  const firstUnread = (it) => {
    if (!inSeries(it)) return it;
    const k = seriesKey(it.series);
    return S.items.filter((x) => x.has_file && x.kind === it.kind && inSeries(x) && seriesKey(x.series) === k).sort(seriesOrder)
      .find((x) => Wheel.status(x)[0] !== "done") || it;
  };
  // the challenge: a volume you've started is to be finished, one you haven't is to be started
  function inOrder(it, type, cur, reroll) {
    if (type === "revisit") return [it, type];
    const f = firstUnread(it);
    if (reroll && cur && f.id === cur.id) return [it, type];
    return [f, Wheel.status(f)[0] === "now" ? "finish" : "start"];
  }
  // Still in the Wrapper: the series' first unread volume, and none from a series you're partway through
  const wrapperPicks = (list) => {
    const seen = new Set();
    return list.map(firstUnread).filter((x) => !x.opened_at && Wheel.status(x)[0] === "new" && !seen.has(x.id) && seen.add(x.id));
  };
  function challenge(reroll = false) {
    const wk = weekStart(), cur = load();
    const ci = cur && S.items.find((i) => i.id === cur.id);
    if (cur && cur.week === wk && !reroll && ci && (cur.type === "revisit" || Wheel.status(ci)[0] === "done" || firstUnread(ci) === ci)) return cur;
    const r = rng(wk + ":" + ((cur && cur.week === wk ? cur.draw : 0) + (reroll ? 1 : 0)));
    const mine = S.items.filter((i) => i.has_file && ["book", "graphic", "tv", "movie", "article"].includes(i.kind) && !(cur && cur.id === i.id && reroll));
    const started = mine.filter((i) => { const s = Wheel.status(i)[0]; return s === "now"; });
    const long = mine.filter((i) => Wheel.status(i)[0] === "done" && finishedAt(i) && finishedAt(i) < Date.now() / 1000 - 180 * DAY);
    const fresh = mine.filter((i) => !i.opened_at && Wheel.status(i)[0] === "new");
    // finish what you're partway through; now and then revisit an old favourite or open something never started
    const pools = [["finish", started], ["revisit", long], ["start", fresh]].filter(([, p]) => p.length);
    if (!pools.length) { if (reroll) toast("Nothing else to pick right now: start something and it'll turn up here."); return reroll ? cur : null; }
    let [type, pool] = pools[0];
    if (pools.length > 1 && r() < (reroll ? 0.5 : 0.25)) [type, pool] = pools[1 + Math.floor(r() * (pools.length - 1))];
    const [it, kind] = inOrder(shuffle(pool, r)[0], type, cur, reroll);
    type = kind;
    const c = { week: wk, id: it.id, type, draw: (cur && cur.week === wk ? cur.draw || 0 : 0) + (reroll ? 1 : 0), since: it.opened_at || 0 };
    save(c);
    return c;
  }
  const done = (c, it) => c.type === "finish" ? Wheel.status(it)[0] === "done" : (it.opened_at || 0) > Math.max(c.week, c.since || 0);

  /* The Bulletin is a glossy weekly magazine: this week's challenge is the cover story; then the catalogue's hottest
     picks, the things on your shelves you haven't opened yet, and the papers waiting to be read */
  function render(lib, tabs) {
    if (srv === undefined) {
      return api.get("/api/bulletin").then((b) => {
        srv = b && b.week ? b : null;
        if (!srv && (typeof Profiles === "undefined" || Profiles.current() === 1)) {        // (from before profiles)
          try { srv = JSON.parse(localStorage.getItem("inkwell-challenge") || "null"); } catch (e) {}
        }
      }).catch(() => { srv = null; }).then(() => render(lib, tabs));
    }
    const wk = weekStart(), r = rng("shelf" + wk);
    const c = challenge(), it = c && S.items.find((i) => i.id === c.id);
    const wrapped = wrapperPicks(shuffle(S.items.filter((i) => ["book", "graphic", "movie", "tv"].includes(i.kind) && i.has_file && !i.opened_at), r)).filter((i) => !(it && i.id === it.id)).slice(0, 6);
    const when = new Date(wk * 1000).toLocaleDateString([], { month: "long", day: "numeric", year: "numeric" });
    const issue = Math.max(1, Math.round((wk - Date.UTC(2026, 0, 5) / 1000) / (7 * DAY)) + 1);
    const ch = it ? { it, c, ok: done(c, it), p: pctOf(it), finish: c.type === "finish", start: c.type === "start",
      ago: Math.round((Date.now() / 1000 - finishedAt(it)) / (30 * DAY)), by: [Wheel.kindName(it), authorLine(it), it.year].filter(Boolean).join(" · ") } : null;
    const act = (x) => x.ok ? "" : `<button class="btn primary" data-read="${x.it.id}">${VIDEO_KINDS.includes(x.it.kind) ? "▶ Watch it" : x.finish ? "Finish it" : x.start ? "Start it" : "Read it again"}</button>`;
    const hook = (x) => x.ok ? (x.finish ? "Done and dusted. Challenge complete." : "Revisited. Challenge complete.")
      : x.finish ? `${x.p}% read. One week to cross the finish line.` : x.start ? "Still in the wrapper. This is the week to open it." : `Last read ${x.ago} months ago. Time for a second look?`;
    const head = (x) => x.ok ? "MISSION ACCOMPLISHED" : x.finish ? "THE FINAL STRETCH" : x.start ? "FIRST PAGE" : "THE RETURN";
    lib.innerHTML = `<div class="vw hw bt-wrap"><div class="bt btx btx-mag">
      <section class="btm-cover ${ch && ch.ok ? "done" : ""}">${ch ? `<div class="btm-bg">${coverHTML(ch.it)}</div>` : ""}
        <div class="btm-sheen"></div>
        <div class="btm-title"><b>BABEL</b><span>Issue ${issue}<br>${esc(when)}</span></div>
        <div class="btm-ribbon">EXCLUSIVE</div>
        ${ch ? `<div class="btm-burst">${ch.ok ? "DONE!" : ch.finish ? `${ch.p}%<small>there</small>` : ch.start ? "NEW!" : "AGAIN?"}</div>
        <div class="btm-hero" data-detail="${ch.it.id}">${coverHTML(ch.it)}${ch.ok ? `<span class="bt-stamp">✓<b>Done!</b></span>` : ""}</div>
        <div class="btm-lines"><small>${ch.finish ? "THIS WEEK'S CHALLENGE" : ch.start ? "THE DEBUT ISSUE" : "THE REVISIT ISSUE"}</small><em>${head(ch)}</em><h2>${esc(Wheel.title(ch.it))}</h2>
          <p class="btm-by">${esc(ch.by)}</p><p class="btm-hook">${esc(hook(ch))}</p>
          ${ch.finish && !ch.ok ? `<div class="btm-meter"><i style="width:${ch.p}%"></i></div>` : ""}
          <div class="d-actions">${act(ch)}<button class="btn" data-bt-reroll>Pick another</button></div></div>`
        : `<div class="btm-lines"><em>COMING SOON</em><h2>Your next obsession</h2><p class="btm-hook">Start something and next week's challenge will be to finish it.</p></div>`}
        <figure class="btm-potd" id="btPotd" hidden></figure>
        <div class="btm-barcode"><i></i><span>0 ${String(issue).padStart(5, "0")} 42</span></div></section>
      <section class="btm-sec btm-hot"><header><small>FROM THE CATALOGUE</small><h3>Hot Off the Press</h3><p>This week's most talked-about finds you don't own yet</p></header>
        <div id="btNew" class="btm-ranks"><p class="hint">Stopping the presses…</p></div></section>
      <section class="btm-sec btm-tfa" id="btTfa" hidden></section>
      <section class="btm-sec btm-qotd" id="btQuote" hidden></section>
      <section class="btm-sec btm-wrap"><header><small>ON YOUR SHELVES</small><h3>Still in the Wrapper</h3><p>Books, comics and films you own but have never opened</p></header>
        ${wrapped.length ? `<div class="btm-velvet">${wrapped.map((x) => `<button class="btm-gem" data-detail="${x.id}">${coverHTML(x)}<span class="btm-seal">UNOPENED</span><b>${esc(Wheel.title(x))}</b><small>${esc([Wheel.kindName(x), authorLine(x)].filter(Boolean).join(" · "))}</small></button>`).join("")}</div>`
          : `<p class="hint">You've opened everything on your shelves. Impressive.</p>`}</section>
    </div>${tabs}</div>`;
    paintPicks(wk);
    paintPotd();
  }
  /* the dailies (only when the internet can be reached): Wikipedia's picture of the day, pinned in the cover's empty
     corner; its featured article; Wikiquote's quote of the day */
  const openWeb = (u) => u && (window.Browser && S.desktopMode === "native" ? Browser.open(u) : window.open(u));
  async function paintPotd() {
    let p = null;
    try { p = await api.get("/api/potd"); } catch (e) {}
    const a = p && p.article, tf = $("#btTfa");
    if (a && tf) {
      tf.innerHTML = `<header><small>FROM THE ENCYCLOPEDIA</small><h3>Today's Article</h3><p>Wikipedia's featured article of the day</p></header>
        <article class="btm-tfa-page">${a.img ? `<img src="${esc(a.img)}" alt="" onerror="this.remove()">` : ""}<h4>${esc(a.title)}</h4>${a.about ? `<em>${esc(a.about)}</em>` : ""}
          <p>${esc(a.text)}</p><button class="btn" data-bt-web="${esc(a.page)}">Read the whole article →</button></article>`;
      tf.hidden = false;
    }
    const q = p && p.quote, qb = $("#btQuote");
    if (q && qb) {
      qb.innerHTML = `<header><small>WORDS TO LIVE BY</small><h3>Quote of the Day</h3></header>
        <blockquote class="btm-q"><p>${esc(q.text)}</p><cite data-bt-web="${esc(q.page)}">— ${esc(q.by)}</cite></blockquote>`;
      qb.hidden = false;
    }
    for (const b of document.querySelectorAll("[data-bt-web]")) b.onclick = () => openWeb(b.dataset.btWeb);
    const box = $("#btPotd");
    if (!box || !p || !p.img) return;
    const img = new Image();
    img.onload = () => {
      box.innerHTML = `<span class="btm-potd-tag">PHOTO OF THE DAY</span><img src="${esc(p.img)}" alt="">
        <figcaption><b>${esc(p.desc || p.title)}</b><small>${esc([p.artist && "📷 " + p.artist, p.license].filter(Boolean).join(" · "))} · Wikimedia Commons</small></figcaption>`;
      box.title = "See it on Wikimedia Commons";
      box.onclick = () => p.page && (window.Browser && S.desktopMode === "native" ? Browser.open(p.page) : window.open(p.page));
      box.hidden = false;
    };
    img.src = p.img;            // (only shown once the picture itself has loaded: offline, nothing appears)
  }
  async function paintPicks(wk) {
    if (!picks) {
      const cats = ["book", "movie", "manga", "tv", "comic"];
      const got = await Promise.all(cats.map((cat) => api.get(`/api/discover/promos?cat=${cat}`).then((x) => (x.items || []).map((i) => ({ ...i, cat: i.cat || cat }))).catch(() => [])));
      const r = rng("new" + wk);
      picks = shuffle(got.flat().filter((x) => x.have !== "owned" && x.have !== "ignored" && x.title), r).slice(0, 6);
    }
    const box = $("#btNew"); if (!box) return;
    const src = (x) => `/api/discover/cover?` + new URLSearchParams({ u: /^https:\/\//.test(x.cover || "") ? x.cover : "", isbn: x.isbn || "", t: x.title || "", a: (x.authors || [])[0] || "" });
    const CAT = { book: "Book", movie: "Film", manga: "Manga", tv: "TV", comic: "Comic" };
    const want = (x, i) => x.have === "wanted" ? `<span class="bt-want got">✓ On your list</span>` : `<button class="bt-want" data-bt-want="${i}">＋ Want</button>`;
    const by = (x) => [CAT[x.cat] || "", (x.authors || [])[0], x.year].filter(Boolean).join(" · ");
    const img = (x) => `<div class="cover"><img loading="lazy" alt="" src="${esc(src(x))}" onerror="this.remove()"></div>`;
    // ranked like a chart: a giant outlined number behind each poster
    const card = (x, i) => `<div class="btm-rank" data-bt-find="${i}" title="Open it in the catalogue"><span class="btm-num">${i + 1}</span>${img(x)}<div class="btm-rinfo"><small>${esc((CAT[x.cat] || "").toUpperCase())}</small><b>${esc(x.title)}</b><span>${esc([(x.authors || [])[0], x.year].filter(Boolean).join(" · "))}</span>${want(x, i)}</div></div>`;
    box.innerHTML = picks.length ? picks.map(card).join("") : `<p class="hint">The catalogue couldn't be reached right now.</p>`;
  }
  document.addEventListener("click", async (e) => {
    if (e.target.closest("[data-bt-reroll]")) { challenge(true); return Wheel.render($("#library")); }
    const w = e.target.closest("[data-bt-want]");
    const fd = !w && e.target.closest("[data-bt-find]");         // a Hot Off the Press poster: its page in the catalogue
    if (fd && picks && picks[Number(fd.dataset.btFind)]) return Discover.showFind(picks[Number(fd.dataset.btFind)]);
    if (w) {
      const x = picks[Number(w.dataset.btWant)];
      try { await api.send("POST", "/api/wishlist", x); x.have = "wanted"; w.outerHTML = `<span class="bt-want got">✓ On your list</span>`; toast("Added to your shopping list"); loadItems(); }
      catch (err) { toast(err.message, "error"); }
    }
  });
  return { render };
})();

/* Home: the TV & Movies wheel for everything you're in the middle of. Cards fan out down the left (mouse wheel, arrow
   keys or a click turn it), the chosen one is shown big on the right; clicking the chosen card again (or Enter) opens it. */
const Wheel = {
  i: 0, list: [], tab: "bulletin", authors: new Map(), unwrapped: new Set(),
  tabs: { recent: "Recently opened", bulletin: "The Bulletin", new: "New additions" },
  items() {
    const ok = S.items.filter((i) => i.has_file && ["book", "graphic", "article", "tv", "movie"].includes(i.kind));
    if (this.tab === "new") return ok.filter((i) => isGift(i) || this.unwrapped.has(i.id)).sort((a, b) => (b.added_at || 0) - (a.added_at || 0)).slice(0, 80);
    const seen = new Set();             // one card per show: the episode to carry on with
    let out = ok.filter((i) => i.opened_at).sort(byOpened)
      .filter((i) => { if (i.kind !== "tv") return true; const k = seriesKey(i.series); if (seen.has(k)) return false; seen.add(k); return true; })
      .map((i) => (i.kind === "tv" ? nextEpisode(i) || i : i));
   return out.slice(0, 80);
  },
  kindName: (it) => (it.kind === "graphic" ? (it.format === "manga" ? "Manga" : "Comic") : { book: "Book", article: "Article", tv: "TV series", movie: "Film" }[it.kind] || it.kind),
  /* where you are with it, in words that suit the kind of thing it is */
  status(it) {
    const j = Journal.statusOf ? Journal.statusOf(it) : "", p = pctOf(it);
    if (j === "hold") return ["hold", "On hold"];
    if (j === "dropped") return ["dropped", "Dropped"];
    if (VIDEO_KINDS.includes(it.kind)) return it.watched || p >= 98 ? ["done", "Watched"] : p > 0 ? ["now", "Now showing"] : ["new", "Not started"];
    if (j === "finished" || p >= 98) return ["done", "Finished"];
    if (j === "reading" || p > 0) return ["now", "Reading"];
    return ["new", it.kind === "article" ? "Unread" : "Not started"];
  },
  title: (it) => (it.kind === "tv" ? it.series || it.title : it.title) || "Untitled",
  render(lib) {
    const gifts = S.items.filter((i) => isGift(i) || (this.tab === "new" && this.unwrapped.has(i.id))).length;      // "New additions" is there only while something is still wrapped
    if (this.tab === "new" && !gifts) this.tab = "recent";
    if (this.tab === "bulletin") return Bulletin.render(lib, this.tabsHtml(gifts));
    this.list = this.items();
    this.i = Math.min(this.i, Math.max(0, this.list.length - 1));
    if (!this._journal) { this._journal = true; Journal.load().then(() => S.home && this.render($("#library"))).catch(() => {}); }
    const thumb = (it) => it.has_cover ? `<img loading="lazy" alt="" src="/api/items/${it.id}/cover?v=${it.cover_v || it._cv || 0}">` : `<i style="--c:${colorFor(it)}">${esc(this.title(it)[0])}</i>`;
    lib.innerHTML = `<div class="vw hw">
      <div class="vw-wheel" id="hwWheel" tabindex="0" aria-label="Your books and films">${this.list.map((it, i) => {
        const [st, label] = this.status(it), p = pctOf(it);
        const sub = it.kind === "tv" ? `S${it.season || 1} · E${it.episode ?? "?"}` : [authorLine(it), it.year].filter(Boolean).join(" · ");
        if (isGift(it)) {       // still wrapped: no peeking at the title on the wheel either
          const what = it.kind === "graphic" && it.format === "manga" ? "a manga" : GIFT_WHAT[it.kind] || "something";
          return `<button class="vw-card hw-card wrapped" data-hw="${i}" data-gift-card="${it.id}"><span class="vw-thumb hw-giftthumb">🎁</span>
            <span class="vw-txt"><b>A present for you!</b><small>It's ${what} · unwrap it to see</small></span></button>`;
        }
        return `<button class="vw-card hw-card" data-hw="${i}" data-gift-card="${it.id}"><span class="vw-thumb">${thumb(it)}</span>
          <span class="vw-txt"><b>${esc(this.title(it))}</b><small>${esc(sub)}</small><em class="hw-st st-${st}">${label}</em></span>
          ${p > 1 && p < 100 ? `<span class="vw-prog"><i style="width:${p}%"></i></span>` : ""}</button>`;
      }).join("")}${this.list.length ? "" : `<p class="hw-empty">Books and films you open show up here.</p>`}</div>
      <div class="vw-right"><div class="vw-stage" id="hwStage"></div>${this.tabsHtml(gifts)}</div></div>`;
    requestAnimationFrame(() => this.place(false));
  },
  /* one swap button, in the same corner on every home screen: it says where it goes next (Recently opened ⇄ The
     Bulletin, and New additions too while presents are waiting, with their count) */
  tabsHtml(gifts) {
    const order = ["recent", "bulletin", ...(gifts ? ["new"] : [])];
    const next = order[(order.indexOf(this.tab) + 1) % order.length];
    return `<button class="hw-swap" data-hw-tab="${next}" title="Switch to ${esc(this.tabs[next])}">
        <span class="hw-swap-disc"><i>⇄</i></span><span class="hw-swap-lbl"><small>Switch to</small><b>${esc(this.tabs[next])}</b></span>
        ${gifts ? `<span class="hw-swap-gift" title="${gifts} new">🎁 ${gifts}</span>` : ""}</button>`;
  },
  place(animate = true) {
    const box = $("#hwWheel");
    if (!box) return;
    const h = box.clientHeight, ch = 92;
    [...box.querySelectorAll(".vw-card")].forEach((c, i) => {
      const d = i - this.i, ad = Math.abs(d);
      c.style.transition = animate ? "" : "none";
      c.style.transform = `translate(${-Math.min(ad, 5) * 11 + (d === 0 ? 30 : 0)}px, ${h / 2 - ch / 2 + d * (ch + 6)}px)`;
      c.style.opacity = ad > 7 ? 0 : 1 - Math.max(0, ad - 4) * 0.22;
      c.style.zIndex = 50 - ad;
      c.classList.toggle("sel", d === 0);
    });
    this.stage();
  },
  stage() {
    const el = $("#hwStage"), it = this.list[this.i];
    if (!el) return;
    if (!it) { el.innerHTML = `<div class="hw-none"><h2>Nothing here yet</h2><p>Open a book, comic or film and it shows up on this wheel.</p></div>`; return; }
    const [st, label] = this.status(it), p = pctOf(it), video = VIDEO_KINDS.includes(it.kind);
    const cover = it.has_cover ? `<div class="vw-backdrop hw-backdrop" style="background-image:url('/api/items/${it.id}/cover?v=${it.cover_v || it._cv || 0}')"></div>` : "";
    const who = it.kind === "tv" ? "" : (it.authors || [])[0] || "";
    const cat = it.kind === "graphic" ? (it.format === "manga" ? "manga" : "comic") : it.kind === "book" ? "book" : "";
    const ticket = [["Year", it.year], [video ? "Runtime" : "Pages", video ? (it.duration ? Media.fmtTime(it.duration) : "") : it.pages],
      ["Series", it.series && it.kind !== "tv" ? it.series + (it.series_index ? " #" + +it.series_index : "") : ""], ["Genre", it.genre], [it.kind === "article" ? "Journal" : "Publisher", it.journal || it.publisher]].filter(([, v]) => v);
    const verb = video ? (st === "now" ? "▶ Resume" : "▶ Watch") : st === "now" ? "Continue reading" : "Read";
    el.innerHTML = `${cover}${presentHTML(it)}<div class="vw-in hw-in" key="${it.id}"><div class="vw-poster">${coverHTML(it)}<span class="vw-stamp hw-stamp st-${st}">${label}</span></div><div class="vw-info">
      <span class="vw-kind">${esc(this.kindName(it))}${it.kind === "tv" ? ` · S${it.season || 1} E${it.episode ?? "?"}` : ""}</span>
      <h2>${esc(this.title(it))}</h2>
      ${who ? `<div class="hw-by"><span>${video ? "Directed by" : "by"} <b>${esc(authorLine(it))}</b></span>${cat ? `<button class="btn sm" id="hwMore" data-hw-author="${esc(who)}" data-hw-cat="${cat}" hidden></button>` : ""}</div>` : ""}
      ${ticket.length ? `<div class="vw-ticket">${ticket.map(([k, v]) => `<span><small>${k}</small><b>${esc(v)}</b></span>`).join("")}</div>` : ""}
      <div class="vw-reel"><div class="vw-bar"><i style="width:${p}%"></i></div><small><b class="hw-st st-${st}">${label}</b>${p > 1 && p < 100 ? ` · ${p}% ${video ? "watched" : "read"}` : ""}${it.opened_at ? ` · opened ${ago(it.opened_at)}` : ""}</small></div>
      ${it.summary ? `<p class="vw-syn">${esc(it.summary)}</p>` : ""}
      <div class="d-actions"><button class="btn primary" data-read="${it.id}">${verb}</button><button class="btn" data-detail="${it.id}">Details</button>${it.kind === "tv" ? `<button class="btn" data-series="${esc(seriesKey(it.series))}">All episodes</button>` : ""}</div></div></div>`;
    el.insertAdjacentHTML("beforeend", this.kin(it));
    if (who && cat) this.checkAuthor(who, cat, it.id);
  },
  /* "More from": the rest of its series on your shelves first (a show's other episodes); otherwise more by the same
     author (or director), as a film strip like the TV & Movies tab's */
  kin(it) {
    const norm = (s) => String(s || "").toLowerCase().replace(/[^a-z0-9]/g, "");
    const lead = (x) => norm(((x.authors || [])[0] || "").replace(/^(.*),\s*(.*)$/, "$2 $1"));
    const mine = S.items.filter((x) => x.id !== it.id && x.has_file && x.kind !== "music");
    let list = [], head = "";
    if (it.series) {
      list = mine.filter((x) => seriesKey(x.series) === seriesKey(it.series) && (it.kind === "tv" ? x.kind === "tv" : x.kind !== "tv"))
        .sort((a, b) => (a.season || 0) - (b.season || 0) || (a.episode || 0) - (b.episode || 0) || (a.series_index || 0) - (b.series_index || 0) || String(a.title).localeCompare(String(b.title)));
      if (it.kind === "tv") { const at = list.findIndex((x) => (x.season || 1) > (it.season || 1) || ((x.season || 1) === (it.season || 1) && (x.episode || 0) > (it.episode || 0))); if (at > 0) list = [...list.slice(at), ...list.slice(0, at)]; }
      head = it.kind === "tv" ? `More of ${esc(it.series)}` : `More from the ${esc(it.series)} series`;
    }
    if (!list.length && lead(it)) {
      list = mine.filter((x) => lead(x) === lead(it) && x.kind !== "tv").sort((a, b) => (parseInt(a.year) || 0) - (parseInt(b.year) || 0));
      head = `More ${it.kind === "movie" ? "directed by" : "by"} ${esc(authorLine(it))}`;
    }
    if (!list.length) return "";
    const sub = (x) => x.kind === "tv" ? `S${x.season || 1} · E${x.episode ?? "?"}` : [x.series_index ? "#" + +x.series_index : "", x.year].filter(Boolean).join(" · ");
    return `<div class="vw-kin hw-kin"><h3>${head}</h3><div class="vw-strip">${list.slice(0, 16).map((x) => `<button class="vw-mini ${pctOf(x) >= 98 ? "seen" : ""}" data-hw-kin="${x.id}" title="${esc(x.title)}">${coverHTML(x)}<b>${esc(x.kind === "tv" ? x.title || sub(x) : x.title)}</b><small>${esc(sub(x))}${pctOf(x) >= 98 ? " · ✓" : ""}</small></button>`).join("")}</div></div>`;
  },
  /* does this author have more out there than you have? Asked once the wheel stops on them (answers are cached) */
  checkAuthor(name, cat, id) {
    clearTimeout(this._at);
    const key = cat + ":" + name.toLowerCase();
    const show = (n) => {
      const b = $("#hwMore");
      if (!b || this.list[this.i]?.id !== id) return;
      const manga = cat !== "book";
      if (!n && !manga) return;
      b.textContent = manga ? `More from this author${n ? ` (${n})` : ""}` : `View all releases (${n} more)`;
      b.hidden = false;
    };
    if (this.authors.has(key)) return show(this.authors.get(key));
    this._at = setTimeout(async () => {
      try {
        const r = await api.get(`/api/discover/byauthor?${new URLSearchParams({ name, cat })}`);
        const n = r.items.filter((x) => x.have !== "owned").length;
        if (!r.pending) this.authors.set(key, n);
        show(n);
      } catch (e) { if (cat !== "book") show(0); }
    }, 450);
  },
  move(n) { const to = Math.max(0, Math.min(this.list.length - 1, this.i + n)); if (to !== this.i) { this.i = to; this.place(); } },
  open() { $("#hwStage [data-read]")?.click(); },
  bind() {
    const lib = $("#library");
    let acc = 0;
    lib.addEventListener("wheel", (e) => {
      if (!S.home || !e.target.closest("#hwWheel")) return;
      e.preventDefault();
      acc += e.deltaY;
      if (Math.abs(acc) >= 60) { this.move(Math.sign(acc)); acc = 0; }
    }, { passive: false });
    lib.addEventListener("click", (e) => {
      const tb = e.target.closest("[data-hw-tab]");
      if (tb) { this.tab = tb.dataset.hwTab; this.i = 0; this.unwrapped.clear(); return this.render(lib); }
      const c = e.target.closest("[data-hw]");
      if (c) { const i = Number(c.dataset.hw); return i === this.i ? this.open() : (this.i = i, this.place()); }
      const a = e.target.closest("[data-hw-author]");
      if (a) return Discover.byAuthor(a.dataset.hwAuthor, a.dataset.hwCat);
      const k = e.target.closest("[data-hw-kin]");
      if (k) {     // on the wheel already: turn to it; otherwise its details
        const id = Number(k.dataset.hwKin), i = this.list.findIndex((x) => x.id === id);
        return i >= 0 ? (this.i = i, this.place()) : openDrawer(id);
      }
    });
    document.addEventListener("keydown", (e) => {
      if (!S.home || !$("#hwWheel") || !$("#reader").hidden || (window.Browser && Browser.on) || document.querySelector("dialog[open], .dv.open")
        || /INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)) return;
      if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); this.move(e.key === "ArrowDown" ? 1 : -1); }
      if (e.key === "Enter") { e.preventDefault(); this.open(); }
    });
    addEventListener("resize", () => S.home && this.place(false));
  },
};

function renderLib() {
  const lib = $("#library");
  document.body.classList.toggle("is-home", !!S.home);
  if (S.home) { document.body.classList.remove("area-media", "area-journal", "area-video"); $$("#areaSeg button").forEach((b) => b.classList.remove("on")); return renderHome(lib); }
  document.body.classList.toggle("area-journal", S.area === "journal");
  if (S.area === "journal") { document.body.classList.remove("area-media"); Journal.render(lib); return; }
  document.body.classList.toggle("area-media", !READ_AREAS.includes(S.area));
  document.body.classList.toggle("area-video", S.area === "video");
  if (S.area === "video") {
    lib.innerHTML = Media.wheel(sortItems(filtered()));
    Media.bindWheel();
    queueCovers();
    return;
  }
  if (!READ_AREAS.includes(S.area)) {
    lib.innerHTML = Media.render(sortItems(filtered()), S.groupBy);
    queueCovers();
    return;
  }
  if (!S.items.some((i) => areaKinds().includes(i.kind))) {
    lib.innerHTML = S.area === "articles"
      ? `<div class="empty"><h2>No articles yet</h2><p>Drop article PDFs here, paste a DOI, or import your Zotero library. Each one gets an abstract, tags and citations.</p><button class="btn primary" data-action="add">Add articles</button></div>`
      : `<div class="empty"><h2>No books yet</h2><p>Drop EPUBs, PDFs or comics (CBZ/CBR) anywhere on this page, paste an ISBN, or save files into your inbox folder.</p><button class="btn primary" data-action="add">Add books</button></div>`;
    return;
  }
  const groups = grouped();
  if (!groups.length) {
    lib.innerHTML = `<div class="empty"><h2>Nothing matches</h2><p>${S.tag ? `Filtering by the tag “${esc(S.tag)}”. ` : ""}Try a different search.</p><button class="btn" data-action="clear">Clear filters</button></div>`;
    return;
  }
  const filterNote = S.tag ? `<p class="hint">Showing items tagged “${esc(S.tag)}”. <button class="btn sm" data-action="clear">Show everything</button></p>` : "";
  lib.innerHTML = filterNote + VIEWS[S.view](groups);
  if (S.view === "heist") renderStage();
  queueCovers();
}

/* ---------------- PDF cover generation (offline, via pdf.js) ---------------- */
pdfjsLib.GlobalWorkerOptions.workerSrc = "vendor/pdf.worker.min.js";
const coverQueue = new Set();
let coverBusy = false;
function queueCovers() {
  // one frame grab per show is enough (episodes share the show's poster)
  const showDone = new Set(S.items.filter((i) => i.kind === "tv" && (i.has_cover || i._coverTried)).map((i) => (i.series || "").toLowerCase()));
  for (const it of S.items) {
    if (it.kind !== "tv" || it.has_cover || it._coverTried) continue;
    const k = (it.series || "").toLowerCase();
    if (showDone.has(k)) it._coverTried = true; else showDone.add(k);
  }
  for (const it of S.items) if ((it.file_type === "pdf" || COMIC_TYPES.includes(it.file_type) || VIDEO_KINDS.includes(it.kind)) && it.has_file && !it.has_cover && !it._coverTried && it.status !== "analyzing") { it._coverTried = true; coverQueue.add(it.id); }
  pumpCovers();
}
async function pumpCovers() {
  if (coverBusy || !coverQueue.size) return;
  coverBusy = true;
  const id = coverQueue.values().next().value;
  const item0 = S.items.find((i) => i.id === id);
  // films and episodes: wait until an import has finished (their posters are looked up online first), then grab
  // frames one at a time with a pause between, so the video decoder is never swamped
  if (item0 && VIDEO_KINDS.includes(item0.kind) && (S.jobRunning || Date.now() - (S._lastVideoGrab || 0) < 2500)) {
    coverBusy = false;
    setTimeout(pumpCovers, 2500);
    return;
  }
  coverQueue.delete(id);
  try {
    const item = S.items.find((i) => i.id === id);
    if (item && VIDEO_KINDS.includes(item.kind)) {
      S._lastVideoGrab = Date.now();
      if (await Media.videoCover(item)) { item.has_cover = true; item._cv = Date.now(); scheduleRender(); }
      throw "done";
    }
    if (item && COMIC_TYPES.includes(item.file_type)) {
      if (await Comic.makeCover(item)) { item.has_cover = true; item._cv = Date.now(); scheduleRender(); }
      throw "done";
    }
    const pdf = await pdfjsLib.getDocument({ url: `/api/items/${id}/file`, disableAutoFetch: true, disableStream: true }).promise;
    const page = await pdf.getPage(1);
    const vp0 = page.getViewport({ scale: 1 });
    const vp = page.getViewport({ scale: 420 / vp0.width });
    const c = document.createElement("canvas");
    c.width = vp.width; c.height = vp.height;
    await page.render({ canvasContext: c.getContext("2d"), viewport: vp }).promise;
    const blob = await new Promise((r) => c.toBlob(r, "image/jpeg", 0.85));
    await fetch(`/api/items/${id}/cover`, { method: "POST", body: blob });
    const it = S.items.find((i) => i.id === id);
    if (it) { it.has_cover = true; it._cv = Date.now(); }
    pdf.destroy();
    scheduleRender();
  } catch (e) { if (e !== "done") console.warn("cover failed", id, e); }
  coverBusy = false;
  pumpCovers();
}
let renderTimer;
const scheduleRender = () => { clearTimeout(renderTimer); renderTimer = setTimeout(render, 250); };

/* ---------------- data ---------------- */
const jstat = (it) => (typeof Journal !== "undefined" ? Journal.statusOf(it) : "");
async function loadItems() {
  const prev = new Map(S.items.map((i) => [i.id, i]));
  const r = await fetch("/api/items");
  const text = await r.text();
  if (text === S._itemsText && !S._forceRender) return;  // nothing changed: don't rebuild the page
  S._itemsText = text; S._forceRender = false;
  S.items = JSON.parse(text);
  for (const it of S.items) { const p = prev.get(it.id); if (p) { it._coverTried = p._coverTried; it._cv = p._cv; } }
  $(".brand-name").dataset.cycle = String(S.items.length).padStart(3, "0");
  render();
  if (!S._jrLoaded && typeof Journal !== "undefined") { S._jrLoaded = true; Journal.load().then(() => { if (S.area !== "journal") renderLib(); }).catch(() => {}); }
  if (S.openId) { const it = S.items.find((i) => i.id === S.openId); if (it && $("#drawer").classList.contains("open") && !$("#drawer").contains(document.activeElement)) openDrawer(it.id, true); }
}

/* ---------------- drawer ---------------- */
const F = (name, label, val, cls = "", type = "text") => `<label class="${cls}">${label}<input type="${type}" name="${name}" value="${esc(val ?? "")}"></label>`;

const opts = (list, cur, blank) => (blank !== undefined ? `<option value="">${esc(blank)}</option>` : "") +
  [...new Set([...(cur && !list.includes(cur) ? [cur] : []), ...list])].map((g) => `<option ${g === cur ? "selected" : ""}>${esc(g)}</option>`).join("");

async function openDrawer(id, quiet = false) {
  S.openId = id;
  const it = await api.get(`/api/items/${id}`);
  const anns = await api.get(`/api/items/${id}/annotations`);
  const isMedia = MEDIA_KINDS.includes(it.kind);
  const isVideo = VIDEO_KINDS.includes(it.kind);
  const genres = TAX.genres[it.kind] || [];
  const cites = Object.entries(it.citations).map(([label, c]) => `<div class="cite"><b>${esc(label)}</b>${c.html}<button class="btn sm copy" data-copy="${esc(c.text)}">Copy</button></div>`).join("");
  const sumLabel = it.kind === "article" ? "Abstract" : "Synopsis";
  const byline = it.kind === "music" ? [(it.authors || []).join(", "), it.album].filter(Boolean).join(" · ")
    : it.kind === "tv" ? `${it.series || ""}${it.season ? ` · Season ${it.season}` : ""}${it.episode ? `, episode ${it.episode}` : ""}`
    : [(it.authors || []).join(", ") || authorLine(it), it.year].filter(Boolean).join(", ");
  const actionLabel = isVideo ? "Watch" : it.kind === "music" ? "Play" : "Read";
  $("#drawerBody").innerHTML = `
    <div class="d-top ${isVideo ? "wide" : ""}">${coverHTML(it)}<div>
      <h2>${esc(it.title || "Untitled")}</h2>
      <div class="by">${esc(byline)}</div>
      ${it.series && !["tv"].includes(it.kind) ? `<div class="by">${esc(it.series)}${it.series_index ? ` #${+it.series_index}` : ""}</div>` : ""}
      ${it.status === "analyzing" ? '<div class="badge-analyzing">Sorting and tagging…</div>' : `<div class="hint">${esc([it.subject, it.topic !== it.subject ? it.topic : ""].filter(Boolean).join(" › "))}</div>`}
    </div></div>
    <div class="d-actions">
      ${it.has_file ? `<button class="btn primary" ${it.kind === "music" ? `data-play-one="${it.id}"` : `data-read="${it.id}"`}>${it.audio_status === "ready" ? "📖 " : ""}${actionLabel}${it.progress && it.kind !== "music" && it.progress < 0.97 && jstat(it) !== "finished" ? " (" + Math.round(it.progress * 100) + "%)" : ""}</button>` : (it.wanted ? `<button class="btn primary" data-own="${it.id}">I own it (physical copy)</button><span class="hint">On your wishlist.</span>` : `<span class="hint">${it.physical ? "Physical copy, no file attached." : "No file attached."}</span>`)}
      ${it.audio_status === "ready" ? `<button class="btn primary" data-listen="${it.id}">🎧 Listen${it.audio_pos && !it.audio_pos.done && (it.audio_pos.ch || it.audio_pos.t > 20) ? ` (chapter ${it.audio_pos.ch + 1})` : ""}</button>` : ""}
      ${!it.has_file && (it.doi || it.url) ? `<button class="btn" id="dDownload" title="Look for a free, legal copy (open access, arXiv)">Download free copy</button>` : ""}
      ${isVideo ? `<label class="watched-box ${it.watched ? "on" : ""}"><input type="checkbox" id="dWatched" ${it.watched ? "checked" : ""}><span>Watched</span></label>` : ""}
      ${isVideo ? `<button class="btn" id="dPoster" title="Look up the official poster online">Find poster</button>` : ""}
      ${it.kind === "movie" ? `<button class="btn" id="dFilmFind" title="Find this film on Wikipedia and fill in its title, year, director, genre, synopsis and poster">Fill in from Wikipedia</button>` : ""}
      ${["book", "graphic"].includes(it.kind) && !it.has_cover ? `<button class="btn" id="dPullCover" title="Find this book's cover online (Hardcover, then Wikipedia and other catalogues)">Pull cover</button>` : ""}
      ${["book", "graphic"].includes(it.kind) && (S.settings.hardcover_token || "").trim() ? `<button class="btn" id="dHardcover" title="Replace the synopsis, authors, genre, series and year with Hardcover's">Pull info from Hardcover</button>` : ""}
      ${it.has_file && it.kind !== "music" ? `<button class="btn" id="dToPhone" title="Your phone fetches this file the next time its Babel's Library app syncs">📱 Send to phone</button>` : ""}
      ${typeof Profiles !== "undefined" ? Profiles.drawerToggle(it) : ""}
      <button class="btn" id="dReanalyze">Re-sort and re-tag</button>
      <button class="btn danger" id="dDelete">Remove</button>
    </div>
    ${it.kind === "movie" ? `<div class="d-sec d-film" id="dFilm" hidden>
      <h4>Which film is this?</h4>
      <form class="row" id="dFilmForm"><input name="q" value="${esc([it.title, it.year].filter(Boolean).join(" "))}" placeholder="Film name (and year)" style="flex:1"><button class="btn sm primary">Search</button></form>
      <ul class="film-hits" id="dFilmHits"></ul></div>` : ""}
    ${["epub", "pdf"].includes(it.file_type) && it.has_file ? `<div class="d-sec d-audio" id="dAudio" data-id="${it.id}"></div>` : ""}
    ${["book", "graphic", "movie", "tv"].includes(it.kind) ? `<div class="d-sec d-journal" id="dJournal" data-id="${it.id}"></div>` : ""}
    <div class="d-confirm" id="dConfirm" hidden>
      <span>Remove “${esc(it.title || "Untitled")}” from Babel's Library?</span>
      <div class="row wrap"><button class="btn" id="dRmKeep">Remove, keep the file</button>${it.has_file ? `<button class="btn danger" id="dRmFile">Remove and delete the file</button>` : ""}<button class="btn" id="dRmCancel">Cancel</button></div>
    </div>
    <form class="form-grid d-cat" id="dCat">
      ${it.kind !== "article" ? `<label>Genre<input name="genre" value="${esc(it.genre || "")}" list="genreList" placeholder="Pick or type a genre"></label>` : ""}
      ${["book", "graphic", "movie"].includes(it.kind) ? `<label>Series${seriesSelect(it)}</label>
        <label>Number in series<input name="series_index" type="number" step="0.5" min="0" value="${it.series_index ?? ""}"></label>` : ""}
      ${it.kind === "tv" ? `<label>Series${seriesSelect(it)}</label><label>Season<input name="season" type="number" min="0" value="${it.season ?? ""}"></label><label>Episode<input name="episode" type="number" min="0" value="${it.episode ?? ""}"></label>` : ""}
      ${it.kind === "music" ? `<label>Album<input name="album" value="${esc(it.album || "")}"></label><label>Album artist<input name="album_artist" value="${esc(it.album_artist || "")}"></label><label>Track<input name="track" type="number" min="0" value="${it.track ?? ""}"></label>` : ""}
      ${!isMedia ? `<label>Subject<select name="subject">${opts(TAX.subjects, it.subject)}</select></label><label>Topic<select name="topic">${opts(TAX.topics, it.topic)}</select></label>` : ""}
    </form>
    ${it.kind !== "music" ? `<div class="d-sec"><h4>${sumLabel}</h4><textarea class="summary-edit" id="dSummary" rows="5" placeholder="${it.kind === "article" ? "No abstract found. Paste one here." : "No synopsis yet. Add one here, or connect to the internet and re-sort to fetch the publisher's."}">${esc(it.summary || "")}</textarea></div>` : ""}
    <div class="d-sec"><h4>Tags</h4><div class="tag-edit" id="dTags">${(it.tags || []).map((t) => `<span class="tagchip" data-tag="${esc(t)}">${esc(t)}<button data-rmtag="${esc(t)}" title="Remove tag">×</button></span>`).join("")}<input id="dTagIn" placeholder="Add a tag"></div></div>
    ${it.has_file ? `<div class="d-file"><span class="hint">Saved as</span> <code>${esc(it.file_location || "")}</code> <button class="btn sm" data-action="reveal-item" data-id="${it.id}">Show in folder</button><button class="btn sm" id="dRename">Rename file to match title</button></div>` : ""}
    ${!isMedia ? `<div class="d-sec"><h4>Citations</h4>${cites}</div>` : ""}
    ${anns.length ? `<div class="d-sec"><h4>Annotations (${anns.length})</h4><ul class="small-ann">${anns.slice(0, 6).map((a) => `<li style="border-color:var(--hl-${a.color})"><b>${esc(a.title || (a.locator?.type === "pin" ? "Pin" : "Highlight"))}</b>${esc((a.note || a.quote || "").slice(0, 160))}</li>`).join("")}</ul>
      <div class="row"><a class="btn sm" href="/api/export/annotations?format=md&items=${it.id}" download>Export .md</a><a class="btn sm" href="/api/export/annotations?format=json&items=${it.id}" download>.json</a></div></div>` : ""}
    ${Coll.drawerSection(it)}
    <div class="d-sec"><h4>Details</h4>
      <form class="form-grid" id="dForm">
        <label>Type<select name="kind">${(isMedia ? MEDIA_KINDS : READ_KINDS).map((k) => `<option value="${k}" ${it.kind === k ? "selected" : ""}>${KIND_LABEL[k].replace(/s$/, "").replace("Graphic novel", "Graphic novel")}</option>`).join("")}</select></label>
        ${it.kind === "graphic" ? `<label>Reading direction<select name="direction"><option value="ltr">Left to right</option><option value="rtl" ${it.direction === "rtl" ? "selected" : ""}>Right to left (manga)</option></select></label>
          <label>Format<select name="format"><option value="comic">Comic / graphic novel</option><option value="manga" ${it.format === "manga" ? "selected" : ""}>Manga</option></select></label>` : ""}
        ${!isMedia ? `<label>Fiction?<select name="fiction"><option value="">Unknown</option><option value="1" ${it.fiction === 1 ? "selected" : ""}>Fiction</option><option value="0" ${it.fiction === 0 ? "selected" : ""}>Non-fiction</option></select></label>` : ""}
        ${F("title", "Title", it.title, "full")}
        <label class="full">${it.kind === "music" ? "Artists" : isVideo ? "Directors / creators" : "Authors"} (one per line)<textarea name="authors" rows="2">${esc((it.authors || []).join("\n"))}</textarea></label>
        ${F("year", "Year", it.year)}
        ${it.kind === "article" ? F("journal", "Journal", it.journal, "full") + F("volume", "Volume", it.volume) + F("issue", "Issue", it.issue) + F("pages", "Pages", it.pages) : (!isMedia ? F("place", "Place published", it.place) : "")}
        ${!isMedia ? F("publisher", "Publisher", it.publisher) + F("doi", "DOI", it.doi) + F("isbn", "ISBN", it.isbn) : ""}${F("url", "URL", it.url, "full")}
        ${!isMedia ? `<label class="full"><span><input type="checkbox" name="physical" ${it.physical ? "checked" : ""}> I own a physical copy</span></label>` : ""}
      </form>
      ${!isMedia ? `<form class="row" id="dFill" style="margin-top:10px"><input name="q" placeholder="Fill details from a DOI, ISBN or link" style="flex:1"><button class="btn sm">Fill in</button></form>` : ""}
    </div>
    <datalist id="genreList">${genres.map((g) => `<option value="${esc(g)}">`).join("")}</datalist>`;
  const dr = $("#drawer");
  dr.classList.add("open");
  dr.setAttribute("aria-hidden", "false");
  if (!quiet) dr.scrollTop = 0;

  if ($("#dAudio")) paintAudioSection(it);
  if ($("#dJournal")) Journal.paintItemSection(it);
  if ($("#dWatched")) $("#dWatched").onchange = async (e) => {
    await api.send("PATCH", `/api/items/${id}`, { watched: e.target.checked });
    e.target.closest(".watched-box").classList.toggle("on", e.target.checked);
    toast(e.target.checked ? "Marked as watched" : "Marked as not watched");
    await loadItems();
  };
  if ($("#dPoster")) $("#dPoster").onclick = async (e) => {
    e.target.disabled = true; e.target.textContent = "Looking…";
    try { await api.send("POST", `/api/items/${id}/poster`, {}); toast("Poster added"); await loadItems(); openDrawer(id, true); }
    catch (err) { toast(err.message, "error"); e.target.disabled = false; e.target.textContent = "Find poster"; }
  };
  const saveField = async (name, value) => {
    await api.send("PATCH", `/api/items/${id}`, { [name]: value });
    toast("Saved");
    await loadItems();
  };
  const fieldValue = (el) => {
    if (el.name === "authors") return el.value.split(/\n|;/).map((x) => x.trim()).filter(Boolean);
    if (el.type === "checkbox") return el.checked;
    if (el.name === "fiction") return el.value === "" ? null : Number(el.value);
    if (el.type === "number") return el.value === "" ? null : Number(el.value);
    return el.value;
  };
  const onChange = async (e) => {
    const el = e.target;
    if (!el.name) return;
    if (el.name === "series" && el.value === "__new") {
      // swap the list for a box to type the new series' name
      const inp = document.createElement("input");
      inp.name = "series"; inp.placeholder = "Name of the new series"; inp.className = el.className;
      el.replaceWith(inp); inp.focus();
      return;
    }
    if (el.name === "series" && !el.value) await api.send("PATCH", `/api/items/${id}`, { series_index: null });
    await saveField(el.name === "physical" ? "physical" : el.name, fieldValue(el));
    if (["kind", "genre", "series", "format", "subject", "topic"].includes(el.name)) openDrawer(id, true);
    else refreshCites(id);
  };
  $("#dForm").addEventListener("change", onChange);
  $("#dCat").addEventListener("change", onChange);
  if ($("#dSummary")) $("#dSummary").addEventListener("change", (e) => saveField("summary", e.target.value.trim()));
  if ($("#dFill")) $("#dFill").addEventListener("submit", async (e) => {
    e.preventDefault();
    try { await api.send("POST", `/api/items/${id}/fill`, { query: e.target.q.value }); toast("Details filled in"); await loadItems(); openDrawer(id, true); }
    catch (err) { toast(err.message, "error"); }
  });
  if ($("#dFilmFind")) {
    const searchFilms = async () => {
      const box = $("#dFilmHits"), q = $("#dFilmForm").q.value.trim();
      if (!q) return;
      box.innerHTML = `<li class="hint">Searching Wikipedia…</li>`;
      try {
        const hits = await api.get(`/api/films/search?q=${encodeURIComponent(q)}`);
        box.innerHTML = hits.length ? hits.map((f) => `<li><button class="film-hit" data-wiki="${esc(f.wiki)}">${f.thumb ? `<img alt="" src="${esc(f.thumb)}">` : `<span class="film-noimg">🎬</span>`}
            <span><b>${esc(f.title)}</b>${f.year ? ` <small>(${esc(f.year)})</small>` : ""}<em>${esc(f.description)}</em></span></button></li>`).join("")
          : `<li class="hint">No films found. Try the original title, or add the year.</li>`;
      } catch (err) { box.innerHTML = `<li class="error-text">${esc(err.message)}</li>`; }
    };
    $("#dFilmFind").onclick = () => { const p = $("#dFilm"); p.hidden = !p.hidden; if (!p.hidden) { p.scrollIntoView({ block: "nearest" }); searchFilms(); } };
    $("#dFilmForm").onsubmit = (e) => { e.preventDefault(); searchFilms(); };
    $("#dFilmHits").onclick = async (e) => {
      const b = e.target.closest(".film-hit");
      if (!b) return;
      $$(".film-hit", $("#dFilmHits")).forEach((x) => { x.disabled = true; });
      b.classList.add("picked");
      const names = { title: "title", year: "year", authors: "director", genre: "genre", fiction: "fiction", summary: "synopsis", series: "series", tags: "tags", poster: "poster" };
      try {
        const r = await api.send("POST", `/api/items/${id}/film`, { wiki: b.dataset.wiki });
        toast((r.changed.length ? "Filled in: " + r.changed.map((k) => names[k] || k).join(", ") : "Already up to date")
          + (r.kept.length ? `. Kept your own ${r.kept.map((k) => names[k] || k).join(", ")}.` : ""));
        await loadItems(); openDrawer(id, true);
      } catch (err) { toast(err.message, "error"); $$(".film-hit", $("#dFilmHits")).forEach((x) => { x.disabled = false; }); b.classList.remove("picked"); }
    };
  }
  if ($("#dToPhone")) $("#dToPhone").onclick = async (e) => {
    const b = e.currentTarget;
    try {
      const list = await pickSeries(S.items.find((x) => x.id === id));
      if (!list) return;
      let r;
      for (const x of list) r = await api.send("POST", `/api/phone/send/${x.id}`, {});
      toast(`Queued${list.length > 1 ? ` ${list.length}` : ""}: your phone${r.phones > 1 ? "s" : ""} will fetch ${list.length > 1 ? "them" : "it"} on the next sync`); b.textContent = "📱 Queued for your phone"; b.disabled = true;
    } catch (err) { toast(err.message, "error"); }
  };
  if ($("#dPullCover")) $("#dPullCover").onclick = async (e) => {
    e.target.disabled = true; e.target.textContent = "Looking…";
    try { await api.send("POST", `/api/items/${id}/pullcover`, {}); toast("Cover added"); await loadItems(); openDrawer(id, true); }
    catch (err) { toast(err.message, "error"); e.target.disabled = false; e.target.textContent = "Pull cover"; }
  };
  if ($("#dHardcover")) $("#dHardcover").onclick = async (e) => {
    e.target.disabled = true; e.target.textContent = "Asking Hardcover…";
    const names = { title: "title", authors: "authors", year: "year", summary: "synopsis", genre: "genre", fiction: "fiction", series: "series",
      series_index: "number in series", isbn: "ISBN", tags: "tags", cover: "cover" };
    try {
      const r = await api.send("POST", `/api/items/${id}/hardcover`, {});
      toast((r.changed.length ? "From Hardcover: " + r.changed.map((k) => names[k] || k).join(", ") : "Already matches Hardcover")
        + (r.kept.length ? `. Kept your own ${r.kept.map((k) => names[k] || k).join(", ")}.` : ""));
      await loadItems(); openDrawer(id, true);
    } catch (err) { toast(err.message, "error"); e.target.disabled = false; e.target.textContent = "Pull info from Hardcover"; }
  };
  $("#dReanalyze").onclick = async () => { await api.send("POST", `/api/items/${id}/reanalyze`); toast("Re-sorting… (your own edits are kept)"); await loadItems(); openDrawer(id, true); };
  $("#dDelete").onclick = () => { $("#dConfirm").hidden = false; $("#dConfirm").scrollIntoView({ block: "nearest" }); };
  $("#dRmCancel").onclick = () => { $("#dConfirm").hidden = true; };
  const remove = async (delFile) => { await api.send("DELETE", `/api/items/${id}${delFile ? "?delete_file=1" : ""}`); closeDrawer(); toast(delFile ? "Removed and deleted the file" : "Removed from library (the file is still in your folder)"); loadItems(); };
  $("#dRmKeep").onclick = () => remove(false);
  if ($("#dRmFile")) $("#dRmFile").onclick = () => remove(true);
  if ($("#dDownload")) $("#dDownload").onclick = async () => { await api.send("POST", `/api/items/${id}/download`); toast("Looking for a free copy…"); };
  if ($("#dRename")) $("#dRename").onclick = async () => { try { const r = await api.send("POST", `/api/items/${id}/rename-file`); toast("Renamed to " + r.path.split(/[\\/]/).pop()); await loadItems(); openDrawer(id, true); } catch (err) { toast(err.message, "error"); } };
  $("#dTagIn").addEventListener("keydown", async (e) => {
    if (e.key !== "Enter" || !e.target.value.trim()) return;
    e.preventDefault();
    await saveTags(id, [...(it.tags || []), e.target.value.trim()]);
  });
  $$("[data-rmtag]", dr).forEach((b) => b.onclick = (e) => { e.stopPropagation(); saveTags(id, (it.tags || []).filter((t) => t !== b.dataset.rmtag)); });
}
async function saveTags(id, tags) { await api.send("PATCH", `/api/items/${id}`, { tags: [...new Set(tags)] }); await loadItems(); openDrawer(id, true); }
async function refreshCites(id) {
  const it = await api.get(`/api/items/${id}`);
  const box = $$(".d-sec", $("#drawer")).find((s) => s.querySelector("h4")?.textContent === "Citations");
  if (box) box.innerHTML = "<h4>Citations</h4>" + Object.entries(it.citations).map(([label, c]) => `<div class="cite"><b>${esc(label)}</b>${c.html}<button class="btn sm copy" data-copy="${esc(c.text)}">Copy</button></div>`).join("");
}
function closeDrawer() { $("#drawer").classList.remove("open"); $("#drawer").setAttribute("aria-hidden", "true"); S.openId = null; }

/* ---------------- add dialog ---------------- */
async function uploadFiles(files) {
  const list = $("#uploadList");
  for (const f of files) {
    if (!/\.(pdf|epub|cbz|cbr|cb7|cbt|mp3|flac|m4a|aac|ogg|oga|opus|wav|wma|aiff?|mp4|m4v|mkv|webm|avi|mov|wmv|mpe?g|ts)$/i.test(f.name)) { toast(`${f.name}: Babel's Library can't add this kind of file`, "error"); continue; }
    const li = document.createElement("li");
    li.textContent = `${f.name}: uploading…`;
    list.prepend(li);
    try {
      const r = await fetch("/api/upload", { method: "POST", headers: { "X-Filename": encodeURIComponent(f.name) }, body: f });
      const j = await r.json();
      if (!r.ok) throw new Error(j.error);
      li.textContent = j.new ? `${f.name}: added, sorting now` : `${f.name}: already in your library`;
    } catch (e) { li.textContent = `${f.name}: ${e.message}`; }
  }
  loadItems();
}

const MANUAL_FIELDS = `
  <label>Type<select name="kind"><option value="book">Book</option><option value="article">Article</option><option value="graphic">Graphic novel</option></select></label>
  <label>Fiction?<select name="fiction"><option value="">Let Babel's Library guess</option><option value="1">Fiction</option><option value="0">Non-fiction</option></select></label>
  <label class="full">Title<input name="title" required></label>
  <label class="full">Authors (one per line)<textarea name="authors" rows="2"></textarea></label>
  <label>Year<input name="year"></label><label>Publisher<input name="publisher"></label>
  <label>Genre<input name="genre" placeholder="optional"></label><label>ISBN<input name="isbn"></label>
  <label class="full">Journal (articles)<input name="journal"></label>
  <label class="full">Short description (helps tagging)<textarea name="summary" rows="2"></textarea></label>
  <label class="full"><span><input type="checkbox" name="physical" checked> I own a physical copy</span></label>
  <div class="full row"><button class="btn primary">Add to library</button></div>`;

function lookupCard(d) {
  return `<div class="lookup-card"><div class="d-top">${coverHTML({ ...d, id: 0, has_cover: false })}<div>
    <h2>${esc(d.title || "Untitled")}</h2><div class="by">${esc((d.authors || []).join(", "))}${d.year ? ", " + esc(d.year) : ""}</div>
    <div class="by">${esc(d.journal || d.publisher || "")}</div><div class="hint">${d.kind === "book" ? "Book" : d.kind === "graphic" ? "Graphic novel" : "Article"}${d.doi ? " · DOI " + esc(d.doi) : ""}${d.isbn ? " · ISBN " + esc(d.isbn) : ""}</div>
    </div></div>
    <label class="row"><input type="checkbox" id="lkPhysical" ${d.kind === "book" ? "checked" : ""}> I own a physical copy</label>
    <div class="row" style="margin-top:10px"><button class="btn primary" id="lkSave">Add to library</button></div></div>`;
}

/* ---------------- settings ---------------- */
function setThemeAttr(key) {
  key = themeKey(key);
  document.documentElement.dataset.theme = key;
  try { localStorage.setItem("inkwell-theme", key); } catch (e) {}
  // the browser's start page (an iframe) follows straight away
  try { const f = document.querySelector("#ibStart"); if (f && f.contentDocument) f.contentDocument.documentElement.dataset.theme = key; } catch (e) {}
  return key;
}
// Settings → Look: a click switches at once and is saved straight away (the widget follows on its next refresh)
function applyTheme(key) {
  key = setThemeAttr(key);
  if (S.settings) S.settings.theme = key;
  api.send("POST", "/api/settings", { theme: key }).catch(() => {});
  $$(".theme-opt").forEach((b) => b.classList.toggle("on", b.dataset.theme === key));
  render();
  window.Reader && Reader.onTheme && Reader.onTheme();
}
function renderThemePicker() {
  const cur = document.documentElement.dataset.theme;
  $("#themePicker").innerHTML = Object.entries(THEMES).map(([k, t]) => `<button class="theme-opt ${k === cur ? "on" : ""}" data-theme="${k}" type="button">
    <div class="sw">${t.swatch.map((c) => `<i style="background:${c}"></i>`).join("")}</div>
    <div class="nm"><b>${esc(t.name)}</b><small>inspired by ${esc(t.inspired)}</small></div></button>`).join("");
}

/* Your search sites: [{name, url (with {q}), cats: ["book","manga",...]}], shown on catalogue "More info" pages */
const SS_CATS = [["book", "Books"], ["manga", "Manga"], ["comic", "Comics"], ["movie", "Movies"], ["tv", "TV"]];
function ssRow(site = {}) {
  const cats = site.cats || SS_CATS.map(([k]) => k);
  return `<div class="ss-row"><input class="ss-name" placeholder="Name (e.g. My library)" value="${esc(site.name || "")}">
    <input class="ss-url" placeholder="https://…/search?q={q}" spellcheck="false" value="${esc(site.url || "")}">
    <div class="ss-cats">${SS_CATS.map(([k, l]) => `<label><input type="checkbox" value="${k}" ${cats.includes(k) ? "checked" : ""}>${l}</label>`).join("")}</div>
    <button class="icon-btn sm ss-del" type="button" title="Remove this site">✕</button></div>`;
}
function renderSearchSites(list) {
  $("#searchSites").innerHTML = (list || []).map(ssRow).join("") || `<p class="hint ss-none">No sites yet.</p>`;
}
function readSearchSites() {
  const out = [];
  for (const r of $$("#searchSites .ss-row")) {
    const name = r.querySelector(".ss-name").value.trim(), url = r.querySelector(".ss-url").value.trim();
    if (!name && !url) continue;
    if (!/^https?:\/\/\S+$/i.test(url)) throw new Error(`“${name || url}”: the address must start with https:// or http://`);
    if (!url.includes("{q}") && !url.includes("{author}")) throw new Error(`“${name || url}”: put {q} in the address where the title goes`);
    out.push({ name: name || new URL(url.replace(/\{\w+\}/g, "x")).hostname.replace(/^www\./, ""), url,
      cats: [...r.querySelectorAll(".ss-cats input:checked")].map((c) => c.value) });
  }
  return out;
}

/* The Discover button lights up and shakes when the catalogue's shelves have new titles ready, until it's opened */
const CAT_SEEN = "inkwell-catalogue-seen";
let catFresh = 0;
async function watchCatalogue() {
  const check = async () => {
    try {
      const { updated_at: t } = await api.get("/api/discover/fresh");
      let seen = 0;
      try { seen = Number(localStorage.getItem(CAT_SEEN)) || 0; } catch (e) {}
      if (!seen) { try { localStorage.setItem(CAT_SEEN, String(t || Date.now() / 1000)); } catch (e) {} return; }   // first run: nothing to announce
      if (t > seen && !catFresh) { catFresh = t; markCatalogue(true); }
    } catch (e) {}
  };
  check();
  setInterval(check, 120000);
  setInterval(() => { if (catFresh) shakeCatalogue(); }, 20000);
}
function shakeCatalogue() {
  const b = $("#discoverBtn");
  b.classList.remove("shake"); void b.offsetWidth; b.classList.add("shake");
}
function markCatalogue(on) {
  const b = $("#discoverBtn");
  b.classList.toggle("fresh", on);
  b.title = on ? "New titles on the catalogue's shelves: have a look" : "Find books online and keep a wishlist";
  if (on) shakeCatalogue();
}
function catalogueSeen() {
  if (!catFresh) return;
  try { localStorage.setItem(CAT_SEEN, String(catFresh)); } catch (e) {}
  catFresh = 0;
  markCatalogue(false);
}

/* Settings → Phone: pairing code, paired phones, away-from-home access (phonesync.py) */
function paintPhone(p, code) {
  const seen = (t) => (t ? ago(t) : "never");
  $("#phoneBox").innerHTML = `
    <div class="ph-pair">${code ? `<div class="ph-code" title="Type this in the phone app (valid for 10 minutes)">${code.replace(/(\d{3})(\d{3})/, "$1 $2")}</div>
      <div class="hint">Computer address on your Wi-Fi: <b>${esc((p.addresses || [])[0] || "unknown")}</b> (the app usually finds it by itself). Valid for 10 minutes.</div>
      <div class="hint">iPhone or iPad: type the same code in the web app. ${p.remote && p.remote_url ? `It finds this computer by itself (if not, its away-from-home address is <b>${esc(p.remote_url)}</b>).` : "<b>Switch on “Reach this library from anywhere” first</b>: the iPhone app reaches the computer that way."}</div>`
      : `<button class="btn primary" type="button" id="phonePair">Pair a phone…</button>`}</div>
    <p class="hint">On an iPhone or iPad, open <b>flightissa2000-hash.github.io/babels-library-web</b> in Safari, tap Share → <b>Add to Home Screen</b>, then open it from the Home Screen and pair it there.</p>
    ${(p.devices || []).length ? `<ul class="ph-devs">${p.devices.map((d) => `<li><b>📱 ${esc(d.name)}</b><span class="hint">last synced ${esc(seen(d.last_seen))}${d.queued ? ` · ${d.queued} file${d.queued === 1 ? "" : "s"} waiting to send` : ""}</span>
      <button class="btn sm" type="button" data-phone-forget="${esc(d.id)}">Unpair</button></li>`).join("")}</ul>` : `<p class="hint">No phones paired yet.</p>`}`;
  $("#phoneRemote").checked = !!p.remote;
  $("#phoneRemoteNote").textContent = p.remote ? (p.remote_url ? "(on: phones can reach it now)" : p.remote_error ? `(couldn't start: ${p.remote_error})` : "(starting…)") : "";
}
async function loadPhone(code) { try { paintPhone(await api.get("/api/phone"), code); } catch (e) { $("#phoneBox").textContent = e.message; } }

async function openSettings() {
  const s = S.settings = await api.get("/api/settings");
  renderThemePicker();
  renderSearchSites(s.search_sites);
  loadPhone();
  $("#adblockOn").checked = s.adblock !== false;
  $("#newsAlertsOn").checked = !!s.news_alerts;
  api.get("/api/adblock").then((a) => {
    $("#adblockStatus").textContent = a.loading && a.domains < 1000 ? "(fetching the block lists…)"
      : `(${a.domains.toLocaleString()} ad and tracker sites blocked${a.updated ? ", lists from " + new Date(a.updated * 1000).toLocaleDateString() : ""})`;
  }).catch(() => {});
  const f = $("#settingsForm");
  f.querySelector("[name=watch_folder]").value = s.watch_folder;
  f.querySelector("[name=inbox_move]").checked = !!s.inbox_move;
  $("#libFolder").textContent = s.library_folder;
  f.querySelector("[name=watch_enabled]").checked = !!s.watch_enabled;
  f.querySelector("[name=watch_interval]").value = s.watch_interval;
  f.querySelector("[name=auto_lookup]").checked = !!s.auto_lookup;
  $("#ollamaUrl").value = s.ollama_url;
  $("#dvKeys [name=nyt_key]").value = s.nyt_key || "";
  $("#dvKeys [name=hardcover_token]").value = s.hardcover_token || "";
  $("#dvKeyResult").textContent = "";
  const df = $("#deskForm");
  ["widget_locked", "main_fullscreen"].forEach((k) => df.querySelector(`[name=${k}]`).checked = !!s[k]);
  api.get("/api/desktop/startup").then((r) => { $("#startWithWindows").checked = !!r.on; }).catch(() => {});
  df.querySelector("[name=widget_autohide]").checked = s.widget_autohide !== false;
  df.querySelector("[name=start_mode]").value = s.start_mode || "full";
  df.querySelector("[name=widget_corner]").value = s.widget_corner || "top-right";
  const st = await api.get("/api/status");
  const models = st.ollama_models;
  $("#ollamaModel").innerHTML = (models && models.length ? models : [s.ollama_model]).map((m) => `<option ${m === s.ollama_model || m.split(":")[0] === s.ollama_model ? "selected" : ""}>${esc(m)}</option>`).join("");
  $("#aiStatus").innerHTML = models
    ? `<span class="dot"></span><b>Local AI connected.</b> Ollama is running with ${models.length} model${models.length === 1 ? "" : "s"}. New items are read and tagged by the model you pick below, entirely on this computer.`
    : `<span class="dot off"></span><b>Using the built-in analyser.</b> It works offline but is less accurate. For smarter, still-offline tagging, install <a href="https://ollama.com" target="_blank" rel="noopener">Ollama</a> and run <code>ollama pull llama3.2</code>, then reopen Settings.`;
  updateBibLink();
  $("#settingsDialog").showModal();
}
function updateBibLink() { $("#bibLink").href = "/api/export/citations?style=" + encodeURIComponent($("#bibStyle").value); }

/* ---------------- status polling ---------------- */
let lastStatusT = 0, lastAnalyzing = -1;
async function poll() {
  try {
    const st = await api.get("/api/status?since=" + lastStatusT);
    if (!lastStatusT) st.activity = [];
    lastStatusT = st.now;
    const ai = st.ollama_models ? `<span><span class="dot"></span>Local AI: <b>Ollama</b></span>` : `<span><span class="dot off"></span>Tagging: <b>built-in analyser</b></span>`;
    const inbox = st.watch_enabled ? `<span><span class="dot ${st.watch_error ? "off" : ""}"></span>Watching <b>${esc(st.watch_folder)}</b></span>` : `<span><span class="dot off"></span>Inbox folder paused</span>`;
    const ab = st.audiobook || {};
    const abLine = ab.running ? `<span class="job"><span class="dot busy"></span>Making audiobook: <b>${esc((ab.title || "").slice(0, 40))}</b>${ab.total ? ` · ${Math.round(100 * ab.done / ab.total)}%` : ""}${ab.chapter ? " · " + esc(ab.chapter.slice(0, 40)) : ""}<i class="jobbar"><i style="width:${ab.total ? Math.round(100 * ab.done / ab.total) : 3}%"></i></i></span>`
      : ab.setup ? `<span class="job"><span class="dot busy"></span>${esc(ab.setup)}</span>` : "";
    S.abState = ab;
    if (ab.running !== S._abWas) { if (S._abWas) loadItems(); S._abWas = ab.running; }
    if ($("#dAudio") && (ab.running || ab.setup || S._abPaint)) { S._abPaint = ab.running || ab.setup; const it2 = S.items.find((x) => x.id === Number($("#dAudio").dataset.id)); if (it2) paintAudioSection(it2); }
    paintDock(st, ab);
    const busy = st.analyzing ? `<span><span class="dot busy"></span>Sorting <b>${st.analyzing}</b> ${st.analyzing === 1 ? "item" : "items"}…</span>` : "";
    const j = st.job || {};
    S.jobRunning = !!(j.running || st.analyzing);
    const job = j.running ? `<span class="job"><span class="dot busy"></span>${esc(j.label)}: <b>${j.done} of ${j.total || "…"}</b>${j.current ? " · " + esc(j.current.slice(0, 50)) : ""}<i class="jobbar"><i style="width:${j.total ? Math.round(100 * j.done / j.total) : 5}%"></i></i></span>` : "";
    const lib = `<span class="libchip">Library folder <b>${esc(st.library_folder)}</b> <button class="btn sm" data-action="switch-lib">Change</button></span>`;
    // library folder, tagging engine and inbox now live in Settings; the bar only shows work in progress
    $("#statusline").innerHTML = "";  // work in progress shows in the dock at the bottom right
    S.status = st;
    if ($("#inboxStatus")) $("#inboxStatus").innerHTML = inbox + ai;
    renderJobInDialog(j);
    if (j.running) S.jobWasRunning = true;
    else if (S.jobWasRunning) { S.jobWasRunning = false; await loadItems(); }
    for (const a of st.activity) if (a.kind !== "sorted" || a.msg) toast(a.msg, a.kind === "error" ? "error" : "");
    if (st.activity.length || st.analyzing !== lastAnalyzing) { lastAnalyzing = st.analyzing; await loadItems(); }
  } catch (e) { $("#statusline").innerHTML = `<span><span class="dot off"></span>Can't reach the Babel's Library server. Is it still running?</span>`; }
  setTimeout(poll, S.status && ((S.status.job || {}).running || S.status.analyzing || (S.status.audiobook || {}).running) ? 1200 : 3000);
}

/* ---------------- work dock: imports, sorting and audiobooks, bottom right ---------------- */
function paintDock(st, ab) {
  let dock = $("#workDock");
  if (!dock) { dock = document.createElement("aside"); dock.id = "workDock"; dock.className = "work-dock"; dock.setAttribute("aria-live", "polite"); document.body.append(dock); }
  const cards = [];
  const card = (id, ico, title, sub, done, total, foot) => {
    const pct = total ? Math.min(100, Math.round(100 * done / total)) : null;
    cards.push(`<div class="wd-card" data-wd="${id}">
      <div class="wd-top"><span class="wd-ico">${ico}</span><div class="wd-tt"><b>${esc(title)}</b>${sub ? `<small>${esc(sub)}</small>` : ""}</div>${pct != null ? `<span class="wd-pct">${pct}<i>%</i></span>` : ""}</div>
      <div class="wd-bar ${pct == null ? "indet" : ""}"><i style="width:${pct ?? 30}%"></i></div>
      ${foot ? `<div class="wd-foot">${foot}</div>` : ""}</div>`);
  };
  const j = st.job || {};
  if (j.running) {
    const bits = [j.added ? `${j.added} added` : "", j.skipped ? `${j.skipped} already there` : "", j.errors ? `${j.errors} couldn't be read` : ""].filter(Boolean).join(" · ");
    card("job", "⇣", j.label || "Working", j.current || "", j.done || 0, j.total || 0,
      `<span>${j.total ? `${j.done} of ${j.total}` : "Getting ready…"}</span><span>${esc(bits)}</span>`);
  }
  if (st.analyzing) card("sort", "✦", `Sorting ${st.analyzing} ${st.analyzing === 1 ? "item" : "items"}`, "Reading titles, covers, series and subjects", 0, 0, "");
  if (ab && ab.running) card("ab", "🎧", "Making an audiobook", [ab.title, ab.chapter].filter(Boolean).join(" · "), ab.done || 0, ab.total || 0, "");
  else if (ab && ab.setup) card("ab", "🎧", "Audiobooks", ab.setup, 0, 0, "");
  const sig = cards.length ? cards.join("") : "";
  if (dock._sig === sig) return;
  dock._sig = sig;
  if (!cards.length) { dock.classList.remove("on"); return; }
  // update in place so the bars glide instead of jumping
  const old = new Map([...dock.querySelectorAll(".wd-card")].map((c) => [c.dataset.wd, c]));
  const tmp = document.createElement("div"); tmp.innerHTML = sig;
  const next = [...tmp.children].map((c) => {
    const o = old.get(c.dataset.wd);
    if (!o) return c;
    o.querySelector(".wd-top").innerHTML = c.querySelector(".wd-top").innerHTML;
    const ob = o.querySelector(".wd-bar"), nb = c.querySelector(".wd-bar");
    ob.className = nb.className; ob.firstElementChild.style.width = nb.firstElementChild.style.width;
    const of = o.querySelector(".wd-foot"), nf = c.querySelector(".wd-foot");
    if (of && nf) of.innerHTML = nf.innerHTML; else if (nf) o.append(nf); else if (of) of.remove();
    return o;
  });
  dock.replaceChildren(...next);
  dock.classList.add("on");
}

/* ---------------- events ---------------- */
function bind() {
  document.addEventListener("click", async (e) => {
    const t = e.target.closest("[data-tag],[data-read],[data-play-one],[data-detail],[data-open],[data-copy],[data-action],[data-close-drawer],.theme-opt,.tabs button");
    if (!t) return;
    if (t.matches(".theme-opt")) return applyTheme(t.dataset.theme);
    if (t.matches(".tabs button")) {
      const box = t.closest("dialog");
      $$(".tabs button", box).forEach((b) => b.classList.toggle("on", b === t));
      $$(".tab", box).forEach((p) => p.classList.toggle("on", p.dataset.pane === t.dataset.tab));
      return;
    }
    if (t.dataset.tag !== undefined && !e.target.closest("[data-rmtag]")) { e.stopPropagation(); S.tag = t.dataset.tag; closeDrawer(); render(); return; }
    if (t.dataset.copy !== undefined) { await navigator.clipboard.writeText(t.dataset.copy).catch(() => {}); toast("Citation copied"); return; }
    if (t.dataset.read) { const it = S.items.find((i) => i.id == t.dataset.read); closeDrawer(); Reader.open(it); return; }
    if (t.dataset.playOne) { const it = S.items.find((i) => i.id == t.dataset.playOne); const al = Media.albums(S.items).find((a) => a.tracks.includes(it)); Media.play(al ? al.tracks : [it], al ? al.tracks.indexOf(it) : 0); return; }
    if (t.dataset.detail) return openDrawer(Number(t.dataset.detail));
    if (t.hasAttribute("data-close-drawer")) return closeDrawer();
    if (t.dataset.action === "add") return $("#addBtn").click();
    if (t.dataset.action === "reveal-lib") return api.send("POST", "/api/reveal", {});
    if (t.dataset.action === "switch-lib") return openLibSwitch();
    if (t.dataset.action === "rescan") {
      try { await api.send("POST", "/api/library/rescan", {}); toast("Refreshing the library… progress shows at the top."); }
      catch (err) { toast(err.message, "error"); }
      return;
    }
    if (t.dataset.action === "reveal-item") return api.send("POST", "/api/reveal", { id: Number(t.dataset.id) });
    if (t.dataset.action === "clear") { S.tag = null; S.q = ""; $("#search").value = ""; render(); return; }
    if (t.dataset.open) {
      if (t.dataset.heist && S.view === "heist" && Number(t.dataset.heist) !== S.heistSel) {
        S.heistSel = Number(t.dataset.heist);
        $$(".heist-row").forEach((r) => r.classList.toggle("sel", r === t));
        renderStage();
        return;
      }
      openDrawer(Number(t.dataset.open));
    }
  });
  document.addEventListener("mouseover", (e) => {
    const r = e.target.closest(".heist-row");
    if (r && Number(r.dataset.heist) !== S.heistSel) { S.heistSel = Number(r.dataset.heist); $$(".heist-row").forEach((x) => x.classList.toggle("sel", x === r)); renderStage(); }
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && $("#drawer").classList.contains("open") && $("#reader").hidden) closeDrawer();
    if (e.key === "/" && document.activeElement.tagName !== "INPUT" && document.activeElement.tagName !== "TEXTAREA" && $("#reader").hidden) { e.preventDefault(); $("#search").focus(); }
  });
  // the logo is the way home: what you were last reading and watching
  $("#brand").onclick = () => { S.tag = null; S.q = ""; $("#search").value = ""; S.kind = "all"; S.home = true; $$("#kindSeg button").forEach((b) => b.classList.toggle("on", b.dataset.kind === "all")); $$("#areaSeg button").forEach((b) => b.classList.remove("on")); closeDrawer(); render(); };
  let searchT = null;
  $("#search").addEventListener("input", (e) => { S.q = e.target.value; if (S.home) leaveHome(); clearTimeout(searchT); searchT = setTimeout(render, 140); });
  $("#kindSeg").onclick = (e) => { const b = e.target.closest("button"); if (!b) return; S.home = false; S.kind = b.dataset.kind; $$("#kindSeg button").forEach((x) => x.classList.toggle("on", x === b)); render(); };
  $("#areaSeg").onclick = (e) => { const b = e.target.closest("button"); if (b) { S.home = false; setArea(b.dataset.area); } };
  Media.bindPlayer();
  Coll.bind();
  $("#libGo").onclick = applyLibSwitch;
  $("#viewSeg").onclick = (e) => { const b = e.target.closest("button"); if (!b) return; setView(b.dataset.view); };
  Wheel.bind();
  $("#journalBtn").onclick = () => ($("#jbModal.open") ? Journal.close() : Journal.openHere());
  // the top bar stays one row: tighten it a step at a time until it fits (and loosen it again when there's room)
  const fitTopbar = () => {
    const t = $(".topbar");
    t.classList.remove("tight", "tighter", "tightest");
    for (const c of ["tight", "tighter", "tightest"]) { if (t.scrollWidth <= t.clientWidth + 1) break; t.classList.add(c); }
  };
  new ResizeObserver(fitTopbar).observe($(".topbar"));
  new MutationObserver(() => requestAnimationFrame(fitTopbar)).observe($(".topbar"), { childList: true, subtree: true, attributes: true, attributeFilter: ["hidden"] });
  document.addEventListener("click", () => setTimeout(fitTopbar, 50));       // (the bar's contents change with what you click)
  $("#discoverBtn").onclick = () => { catalogueSeen(); Discover.open(); };
  $("#newsBtn").onclick = () => News.open();
  watchCatalogue();
  // the browser opens inside this window (inbrowser.js); without the desktop app, in your own web browser
  $("#browserBtn").onclick = () => S.desktopMode === "native" ? Browser.toggle() : fetch("/api/browser/open", { method: "POST", headers: { "X-Babel": "1", "Content-Type": "application/json" }, body: "{}" })
    .then((r) => r.json()).then((r) => toast(r.where === "browser" ? "Opened in your web browser" : "Opening the browser…")).catch((e) => toast(e.message, "error"));
  document.addEventListener("click", (e) => { const f = e.target.closest("[data-dv-find]"); if (f) Journal.preview(f.dataset.dvFind); });
  document.addEventListener("click", async (e) => {
    const b = e.target.closest("[data-own]");
    if (!b) return;
    const id = Number(b.dataset.own);
    b.disabled = true;
    try {
      const r = await api.send("POST", `/api/items/${id}/own`, {});
      toast(`On your shelf as a physical copy${r.linked ? ", with your journal pages" : ""}. Fetching its cover and sorting it…`);
      await loadItems(); openDrawer(id, true);
      setTimeout(async () => { await loadItems(); }, 6000);
    } catch (err) { b.disabled = false; toast(err.message, "error"); }
  });
  document.addEventListener("keydown", (e) => {
    if ((e.key === "j" || e.key === "J") && !e.ctrlKey && !e.metaKey && !e.altKey && !e.target.matches?.("input,textarea,select,[contenteditable]") && $("#reader").hidden && !$("#jbModal.open")) { e.preventDefault(); Journal.openHere(); }
  });
  $("#groupBy").onchange = (e) => { S.groupBy = e.target.value; savePrefs(); render(); };
  $("#sortBy").onchange = (e) => { S.sortBy = e.target.value; savePrefs(); render(); };
  $("#addBtn").onclick = async () => {
    const st = await api.get("/api/status");
    const s = S.settings = await api.get("/api/settings");
    $("#inboxPath").textContent = st.watch_folder;
    $$(".libPath").forEach((e) => e.textContent = st.library_folder);
    $("#zoteroDir").value ||= s.zotero_dir;
    $("#calibreDir").value ||= s.calibre_dir;
    $("#manualForm").innerHTML ||= MANUAL_FIELDS;
    $("#addDialog").showModal();
  };
  bindImports();
  $("#settingsBtn").onclick = openSettings;
  $("#bibStyle").onchange = updateBibLink;
  $("#openInbox").onclick = () => api.send("POST", "/api/open-inbox");

  const dz = $("#dropZone");
  $("#fileInput").onchange = (e) => uploadFiles([...e.target.files]);
  ["dragenter", "dragover"].forEach((ev) => window.addEventListener(ev, (e) => { if ([...(e.dataTransfer?.types || [])].includes("Files")) { e.preventDefault(); dz.classList.add("over"); } }));
  window.addEventListener("dragleave", () => dz.classList.remove("over"));
  window.addEventListener("drop", (e) => { if (!e.dataTransfer?.files?.length) return; e.preventDefault(); dz.classList.remove("over"); if (!$("#reader").hidden) return; uploadFiles([...e.dataTransfer.files]); toast(`Adding ${e.dataTransfer.files.length} file(s)…`); });

  $("#lookupForm").onsubmit = async (e) => {
    e.preventDefault();
    const out = $("#lookupResult");
    out.innerHTML = '<p class="hint">Looking it up…</p>';
    try {
      const d = await api.send("POST", "/api/lookup", { query: $("#lookupInput").value });
      out.innerHTML = lookupCard(d);
      $("#lkSave").onclick = async () => {
        const body = { ...d, physical: $("#lkPhysical").checked, _cover_url: d.cover_url, _description: d.description, _download: $("#lookupDownload").checked && d.kind !== "book" };
        delete body.cover_url; delete body.description; delete body.subjects;
        if (d.description) body.summary = d.description.slice(0, 600);
        const it = await api.send("POST", "/api/items", body);
        toast(`Added “${it.title}”`); $("#addDialog").close(); out.innerHTML = ""; $("#lookupInput").value = ""; loadItems();
      };
    } catch (err) { out.innerHTML = `<p class="hint">${esc(err.message.includes("Tunnel") || err.message.includes("urlopen") ? "Couldn't reach the catalogue. Check your internet connection, or use “Type it in”." : err.message)}</p>`; }
  };
  $("#manualForm").onsubmit = async (e) => {
    e.preventDefault();
    const body = Object.fromEntries(new FormData(e.target).entries());
    body.authors = (body.authors || "").split(/\n|;/).map((s) => s.trim()).filter(Boolean);
    body.physical = e.target.physical.checked;
    body.fiction = body.fiction === "" ? null : Number(body.fiction);
    if (!body.genre) delete body.genre;
    const it = await api.send("POST", "/api/items", body);
    toast(`Added “${it.title}”`); e.target.reset(); $("#addDialog").close(); loadItems();
  };
  $("#dvTestKeys").onclick = async () => {
    const out = $("#dvKeyResult");
    out.textContent = "Saving and testing… (this can take half a minute)";
    try {
      S.settings = await api.send("POST", "/api/settings", { nyt_key: $("#dvKeys [name=nyt_key]").value.trim(), hardcover_token: $("#dvKeys [name=hardcover_token]").value.trim() });
      const r = await api.send("POST", "/api/discover/test-keys", {});
      out.textContent = [r.nyt && `NYT: ${r.nyt}`, r.hardcover && `Hardcover: ${r.hardcover}`].filter(Boolean).join(" · ") || "No keys entered.";
    } catch (e) { out.textContent = e.message; }
  };
  $("#phoneBox").onclick = async (e) => {
    if (e.target.closest("#phonePair")) {
      const r = await api.send("POST", "/api/phone/code", {});
      paintPhone(r, r.code);
      // the list updates by itself once the phone has paired
      const before = (r.devices || []).length, t0 = Date.now();
      const tick = async () => {
        if (!$("#settingsDialog").open || Date.now() - t0 > 600000) return;
        const p = await api.get("/api/phone").catch(() => null);
        if (p && (p.devices || []).length > before) { paintPhone(p); toast(`Paired with ${p.devices[p.devices.length - 1].name}`); return; }
        setTimeout(tick, 2000);
      };
      setTimeout(tick, 2000);
    }
    const f = e.target.closest("[data-phone-forget]");
    if (f && confirm("Unpair this phone? It will stop syncing until it's paired again.")) paintPhone(await api.send("DELETE", `/api/phone/devices/${f.dataset.phoneForget}`));
  };
  $("#phoneRemote").onchange = async (e) => {
    paintPhone(await api.send("POST", "/api/phone/remote", { on: e.target.checked }));
    if (e.target.checked) setTimeout(() => loadPhone(), 8000);
  };
  $("#ssAdd").onclick = () => { $("#searchSites .ss-none")?.remove(); $("#searchSites").insertAdjacentHTML("beforeend", ssRow()); $("#searchSites .ss-row:last-child .ss-name").focus(); };
  $("#searchSites").onclick = (e) => { const d = e.target.closest(".ss-del"); if (d) d.closest(".ss-row").remove(); };
  $("#saveSettings").onclick = async () => {
    const f = $("#settingsForm");
    let sites;
    try { sites = readSearchSites(); } catch (err) { return toast(err.message, "error"); }
    S.settings = await api.send("POST", "/api/settings", {
      search_sites: sites,
      watch_folder: f.querySelector("[name=watch_folder]").value, watch_enabled: f.querySelector("[name=watch_enabled]").checked,
      inbox_move: f.querySelector("[name=inbox_move]").checked,
      watch_interval: Number(f.querySelector("[name=watch_interval]").value) || 10, auto_lookup: f.querySelector("[name=auto_lookup]").checked,
      ollama_url: $("#ollamaUrl").value, ollama_model: $("#ollamaModel").value,
      start_mode: $("#deskForm [name=start_mode]").value, main_fullscreen: $("#deskForm [name=main_fullscreen]").checked,
      widget_autohide: $("#deskForm [name=widget_autohide]").checked, adblock: $("#adblockOn").checked, news_alerts: $("#newsAlertsOn").checked,
      nyt_key: $("#dvKeys [name=nyt_key]").value.trim(), hardcover_token: $("#dvKeys [name=hardcover_token]").value.trim(),
    });
    if (S.desktop) {
      const df = $("#deskForm");
      api.send("POST", "/api/desktop/widget", { action: "lock", value: df.querySelector("[name=widget_locked]").checked });
      api.send("POST", "/api/desktop/startup", { on: $("#startWithWindows").checked }).catch((e) => toast(e.message, "error"));
      const corner = df.querySelector("[name=widget_corner]").value;
      if (corner !== "custom" && corner !== S.settings.widget_corner) api.send("POST", "/api/desktop/widget", { action: "snap", value: corner });
    }
    $("#settingsDialog").close(); toast("Settings saved");
  };
}

/* ---------------- audiobooks ---------------- */
async function ttsInfo(force) {
  if (!S.tts || force) { try { S.tts = await api.get("/api/tts"); } catch (e) { S.tts = { voices: [], deps: false }; } }
  return S.tts;
}
async function paintAudioSection(it) {
  const box = $("#dAudio");
  if (!box) return;
  const ab = S.abState || {};
  const mine = ab.running && ab.item === it.id;
  let status = mine ? "building" : it.audio_status;
  // "building" with nothing actually running (the app was closed mid-way): it's paused, not stuck
  if (status === "building" && !mine && S.abState && !S.abState.running) status = "partial";
  let html = `<h4>Audiobook</h4>`;
  if (status === "queued" || status === "building") {
    const pct = mine && ab.total ? Math.round(100 * ab.done / ab.total) : 0;
    html += `<p class="hint">${status === "queued" ? "Waiting for another audiobook to finish…" : esc(ab.setup || ab.chapter || "Starting…")}</p>
      <div class="ab-bar"><i style="width:${pct}%"></i></div><p class="hint">${pct}% · runs in the background, you can keep reading or close this panel. Stopping keeps the finished chapters.</p>
      <button class="btn sm" data-ab="cancel">Stop</button>`;
  } else if (status === "partial") {
    let p = null;
    try { p = await api.get(`/api/items/${it.id}/audiobook/progress`); } catch (e) {}
    const pct = p ? p.pct : 0;
    html += `<p class="hint">Paused${p ? ` after ${p.chapters_done} of ${p.chapters} chapters` : ""}.${ab.error ? ` <span class="error-text">${esc(ab.error)}</span>` : ""}</p>
      <div class="ab-bar"><i style="width:${pct}%"></i></div><p class="hint">${pct}% made. Carry on where it stopped, or start again.</p>
      <div class="row wrap"><button class="btn sm primary" data-ab="resume" data-voice="${esc(p?.voice || "")}" data-speed="${p?.speed || ""}">Carry on</button>
      <button class="btn sm" data-ab="restart">Start over</button><button class="btn sm danger" data-ab="discard">Discard</button></div>`;
  } else if (status === "ready") {
    let m = null;
    try { m = S._abm && S._abm.item === it.id ? S._abm : (S._abm = await api.get(`/api/items/${it.id}/audiobook`)); } catch (e) {}
    const hrs = m ? m.chapters.reduce((a, c) => a + c.duration, 0) : 0;
    const pos = it.audio_pos;
    html += `<p>${m ? `${m.chapters.length} chapters · ${Media.fmtTime(hrs)}` : ""}${pos && !pos.done && (pos.ch || pos.t > 20) ? ` · you're at chapter ${pos.ch + 1}` : ""}${pos && pos.done ? " · finished" : ""}</p>
      ${m ? `<ol class="tracklist ab-chapters">${m.chapters.map((c, i) => `<li><button class="trk" data-ab-ch="${i}"><span class="tn">${i + 1}</span><span class="tt">${esc(c.title)}</span><span class="td">${Media.fmtTime(c.duration)}</span></button></li>`).join("")}</ol>` : ""}
      <div class="row wrap"><button class="btn sm" data-ab="remake">Make again with another voice…</button><button class="btn sm danger" data-ab="delete">Delete audiobook</button></div>`;
  } else {
    const t = await ttsInfo();
    const vs = (t.voices || []).map((v) => `<option value="${v.id}" ${v.id === (S.settings.tts_voice || "en_US-lessac-medium") ? "selected" : ""}>${esc(v.label)}${v.installed ? "" : " (download)"}</option>`).join("");
    html += `<p class="hint">Turn this ${it.file_type === "pdf" ? "PDF" : "book"} into an audiobook read by a natural-sounding voice that runs on this computer.
      It's saved in your library's Audiobooks folder, one file per chapter, and plays in the music bar and widget (never in Music or shuffle).
      A novel takes roughly 30–60 minutes to make in the background.${t.deps ? "" : " The first time, the voice engine (about 80 MB) is downloaded."}</p>
      ${status === "error" ? `<p class="error-text">The last attempt failed. ${esc((ab && ab.error) || "")}</p>` : ""}
      <div class="ab-form"><label>Voice <select id="abVoice">${vs}</select></label>
      <label>Speed <select id="abSpeed">${[0.85, 1, 1.1, 1.2, 1.35].map((x) => `<option value="${x}" ${Number(S.settings.tts_speed || 1) === x ? "selected" : ""}>${x === 1 ? "Normal" : x + "×"}</option>`).join("")}</select></label>
      <button class="btn primary" data-ab="make" ${it._fresh ? `data-fresh="1"` : ""}>${it._fresh ? "Start over" : "Make audiobook"}</button></div>`;
  }
  box.innerHTML = html;
}
document.addEventListener("click", async (e) => {
  const b = e.target.closest("[data-ab],[data-ab-ch],[data-listen]");
  if (!b) return;
  if (b.dataset.listen) { Player.playAudiobook(Number(b.dataset.listen)); toast("Playing the audiobook"); return; }
  const box = $("#dAudio");
  const id = box ? Number(box.dataset.id) : null;
  if (!id) return;
  if (b.dataset.abCh !== undefined) { Player.playAudiobook(id, { ch: Number(b.dataset.abCh), t: 0 }); return; }
  const act = b.dataset.ab;
  try {
    if (act === "make") {
      await api.send("POST", `/api/items/${id}/audiobook`, { voice: $("#abVoice").value, speed: Number($("#abSpeed").value), fresh: !!b.dataset.fresh });
      S.settings.tts_voice = $("#abVoice").value; S.settings.tts_speed = Number($("#abSpeed").value);
      toast("Making the audiobook in the background. Progress shows at the top.");
      S.abState = { running: true, item: id, chapter: "Starting…", done: 0, total: 0 };
      await loadItems(); openDrawer(id, true);
    } else if (act === "resume") {
      await api.send("POST", `/api/items/${id}/audiobook`, { voice: b.dataset.voice || undefined, speed: Number(b.dataset.speed) || undefined });
      S.abState = { running: true, item: id, chapter: "Carrying on…", done: 0, total: 0 };
      toast("Carrying on with the audiobook"); await loadItems(); openDrawer(id, true);
    } else if (act === "restart") {
      const it = S.items.find((x) => x.id === id);
      paintAudioSection({ ...it, audio_status: null, _fresh: true });
    } else if (act === "discard") {
      if (!b.dataset.armed) { b.dataset.armed = "1"; b.textContent = "Click again to discard"; return; }
      await api.send("POST", `/api/items/${id}/audiobook/discard`, {}); toast("Discarded"); await loadItems(); openDrawer(id, true);
    } else if (act === "cancel") {
      await api.send("POST", `/api/items/${id}/audiobook/cancel`, {}); toast("Stopping after this sentence. Finished chapters are kept.");
      setTimeout(async () => { S.abState = { ...(S.abState || {}), running: false }; await loadItems(); openDrawer(id, true); }, 1500);
    } else if (act === "delete") {
      if (!b.dataset.armed) { b.dataset.armed = "1"; b.textContent = "Click again to delete"; return; }
      await api.send("DELETE", `/api/items/${id}/audiobook`); S._abm = null; toast("Audiobook deleted"); await loadItems(); openDrawer(id, true);
    } else if (act === "remake") {
      const it = S.items.find((x) => x.id === id);
      paintAudioSection({ ...it, audio_status: null });
    }
  } catch (err) { toast(err.message, "error"); }
});

function setArea(a) {
  if (a === "media") a = "video";
  if (a === "read" || a === "journal") a = "books";   // the journal is a book you open from the top bar now
  if (!AREA_KINDS[a]) a = "books";
  if (S.area && S.area !== a) { try { localStorage.setItem("inkwell-group-" + S.area, S.groupBy); } catch (e) {} }
  S.area = a;
  try { const g = localStorage.getItem("inkwell-group-" + a); if (g) S.groupBy = g; } catch (e) {}
  S.kind = "all";
  $$("#areaSeg button").forEach((b) => b.classList.toggle("on", b.dataset.area === a));
  const kinds = AREA_KINDS[a];
  const tabs = KIND_TABS[a] || kinds.map((k) => [k, KIND_LABEL[k]]);
  $("#kindSeg").innerHTML = `<button data-kind="all" class="on">All</button>` + tabs.map(([k, l]) => `<button data-kind="${k}">${l}</button>`).join("");
  $("#kindSeg").hidden = tabs.length < 2;
  const groupOpts = a === "music"
    ? [["auto", "Albums"], ["genre", "Genre"], ["author", "Artist"], ["year", "Year"]]
    : a === "video"
    ? [["auto", "Genre"], ["series", "Film series"], ["year", "Year"], ["none", "No grouping"]]
    : a === "articles"
    ? [["subject", "Subject"], ["journal", "Journal"], ["year", "Year"], ["author", "Author"], ["tag", "Tag"], ["collection", "Collection"]]
    : [["subject", "Subject"], ["year", "Year"], ["fiction", "Fiction or non-fiction"], ["author", "Author"], ["tag", "Tag"], ["collection", "Collection"]];
  $("#groupBy").innerHTML = groupOpts.map(([v, l]) => `<option value="${v}">${l}</option>`).join("");
  if (!groupOpts.some(([v]) => v === S.groupBy)) S.groupBy = groupOpts[0][0];
  $("#groupBy").value = S.groupBy;
  $("#viewSeg").hidden = true;   // Cards is the only view now
  $("#search").placeholder = a === "articles" ? "Search articles, authors, journals, tags…" : a === "books" ? "Search books, authors, series…" : a === "music" ? "Search songs, albums, artists…" : a === "video" ? "Search shows and films…" : a === "journal" ? "Search your journal…" : "Search titles, authors, tags…";
  try { localStorage.setItem("inkwell-area", a); } catch (e) {}
  closeDrawer();
  render();
}

async function openLibSwitch() {
  const st = await api.get("/api/status");
  $("#libCurrent").textContent = st.library_folder;
  $("#libNew").value = "";
  $("#libDialog").showModal();
}
async function applyLibSwitch() {
  const folder = $("#libNew").value.trim();
  if (!folder) return toast("Choose a folder first.", "error");
  try {
    await api.send("POST", "/api/library/switch", { folder, mode: $("input[name=libMode]:checked").value, scan: $("#libScan").checked });
    $("#libDialog").close();
    $$(".libPath").forEach((e) => e.textContent = folder);
    toast($("input[name=libMode]:checked").value === "move" ? "Moving your library. Progress shows at the top." : "Library folder changed");
  } catch (err) { toast(err.message, "error"); }
}

function setView(v) {
  S.view = v;
  $$("#viewSeg button").forEach((b) => b.classList.toggle("on", b.dataset.view === v));
  savePrefs();
  render();
}
function savePrefs() {
  try { localStorage.setItem("inkwell-prefs", JSON.stringify({ view: S.view, groupBy: S.groupBy, sortBy: S.sortBy })); } catch (e) {}
  api.send("POST", "/api/settings", { view: S.view, group_by: S.groupBy }).catch(() => {});
}

(async function init() {
  S.settings = await api.get("/api/settings").catch(() => ({}));
  let p = {};
  try { p = JSON.parse(localStorage.getItem("inkwell-prefs") || "{}"); } catch (e) {}
  S.view = "heist";   // Cards
  S.groupBy = p.groupBy || S.settings.group_by || "auto";
  S.sortBy = p.sortBy || "added";
  setThemeAttr(S.settings.theme);
  if (!["subject", "year", "fiction", "author", "tag", "collection", "journal"].includes(S.groupBy)) S.groupBy = "subject";
  $("#groupBy").value = S.groupBy; $("#sortBy").value = S.sortBy;
  $$("#viewSeg button").forEach((b) => b.classList.toggle("on", b.dataset.view === S.view));
  TAX = await api.get("/api/genres").catch(() => TAX);
  bind();
  let area = "books"; try { area = localStorage.getItem("inkwell-area") || "books"; } catch (e) {}
  setArea(area);
  await loadItems();
  poll();
  if (!MINI) { setTimeout(checkExpiring, 6000); setInterval(checkExpiring, 3600e3); }
  // desktop app extras
  try {
    const d = await api.get("/api/desktop");
    S.desktopMode = d.mode;
    if (d.mode !== "native" && !MINI) Player.startCmdPolling();  // widget remote control without the desktop bridge
    if (d.mode !== "browser") {
      S.desktop = true;
      $("#fsBtn").hidden = false; $("#widgetBtn").hidden = false; $("#deskSettings").hidden = false;
      $("#fsBtn").onclick = () => api.send("POST", "/api/desktop/fullscreen");
      $("#widgetBtn").onclick = () => api.send("POST", "/api/desktop/widget", { action: "show" });
      $("#showWidget").onclick = () => api.send("POST", "/api/desktop/widget", { action: "show" });
      document.addEventListener("keydown", (e) => { if (e.key === "F11") { e.preventDefault(); api.send("POST", "/api/desktop/fullscreen"); } });
    }
  } catch (e) {}
  const want = new URLSearchParams(location.search).get("read");
  if (want) window.inkwellOpenItem(Number(want));
})();

// called by the desktop widget (double-click an item)
window.inkwellOpenItem = (id) => {
  const it = S.items.find((i) => i.id === id);
  if (!it) return;
  if (!$("#reader").hidden && window.Reader) $("#readerClose").click();
  if (it.has_file) setTimeout(() => Reader.open(it), 50);
  else openDrawer(id);
};


/* ---------------- folder scan & Zotero / Calibre import ---------------- */
function renderJobInDialog(j) {
  const target = { "Folder scan": "#scanResult", "Zotero import": "#zoteroResult", "Calibre import": "#calibreResult" }[j.label];
  if (!target) return;
  const el = $(target);
  if (j.running) el.innerHTML = `<div class="jobbar big"><i style="width:${j.total ? Math.round(100 * j.done / j.total) : 3}%"></i></div><p class="hint">${j.done} of ${j.total || "…"} · ${esc((j.current || "").slice(0, 60))}</p>`;
  else if (j.finished_at && el.dataset.shown !== String(j.finished_at)) {
    el.dataset.shown = String(j.finished_at);
    el.innerHTML = `<p><b>Done.</b> Added ${j.added}, ${j.skipped} were already in your library${j.errors ? `, ${j.errors} couldn't be read` : ""}.</p>`;
  }
}

function bindImports() {
  if (S.importsBound) return;
  S.importsBound = true;
  document.addEventListener("click", async (e) => {
    const b = e.target.closest("[data-pick]");
    if (!b) return;
    try {
      const r = await api.send("POST", "/api/pick-folder", {});
      if (r.path) { const inp = $(b.dataset.pick); inp.value = r.path; inp.dispatchEvent(new Event("input", { bubbles: true })); }
    } catch (err) { toast(err.message, "error"); }
  });
  $("#scanGo").disabled = false;
  // phones and e-readers on USB have no drive letter; browse them through the server
  let devPath = [];
  const devShow = async () => {
    const box = $("#devBrowse"), list = $("#devList");
    box.hidden = false;
    $("#devCrumbs").innerHTML = [`<button type="button" data-dev-crumb="0">This PC</button>`, ...devPath.map((n, i) => `<button type="button" data-dev-crumb="${i + 1}">${esc(n)}</button>`)].join("<span>›</span>");
    $("#devUse").disabled = devPath.length < 2;
    list.innerHTML = `<p class="hint">Looking…</p>`;
    try {
      const r = await api.send("POST", "/api/devices/browse", { path: devPath.length ? "This PC\\" + devPath.join("\\") : "" });
      const fs = devPath.length ? r.folders : r.folders.filter((f) => f.device);
      list.innerHTML = fs.length ? fs.map((f) => `<button type="button" class="dev-item" data-dev-open="${esc(f.name)}">📁 ${esc(f.name)}</button>`).join("")
        : `<p class="hint">${devPath.length ? "No folders in here." : "No phone or e-reader found. Plug it in, unlock it and choose “File transfer” on it, then try again."}</p>`;
    } catch (err) { list.innerHTML = `<p class="hint">${esc(err.message)}</p>`; }
  };
  $("#devBtn").onclick = () => { devPath = []; devShow(); };
  $("#devClose").onclick = () => { $("#devBrowse").hidden = true; };
  $("#devBrowse").addEventListener("click", (e) => {
    const o = e.target.closest("[data-dev-open]"), c = e.target.closest("[data-dev-crumb]");
    if (o) { devPath.push(o.dataset.devOpen); devShow(); }
    else if (c) { devPath = devPath.slice(0, Number(c.dataset.devCrumb)); devShow(); }
  });
  $("#devUse").onclick = () => {
    $("#scanFolder").value = "This PC\\" + devPath.join("\\");
    $("#devBrowse").hidden = true;
    $("#scanCheck").click();
  };
  $("#scanCheck").onclick = async () => {
    const out = $("#scanResult");
    try {
      out.innerHTML = `<p class="hint">Checking…</p>`;
      const r = await api.send("POST", "/api/scan/preview", { folder: $("#scanFolder").value.trim() });
      const parts = Object.entries(r.by_kind).map(([k, n]) => `${n} ${(KIND_LABEL[k] || k).toLowerCase()}`);
      out.innerHTML = r.total
        ? `<p>Found <b>${r.total}</b> files (${parts.join(", ")}). Anything already in your library is skipped.</p>${r.inside_library ? `<p class="hint">This folder is inside your library folder, so files stay where they are.</p>` : ""}${r.device ? `<p class="hint">This is on a device, so the files are copied off it; nothing on the device is changed.</p>` : ""}`
        : `<p>No books, articles, comics, music or video files in that folder.</p>`;
    } catch (err) { out.innerHTML = `<p class="hint">${esc(err.message)}</p>`; }
  };
  $("#scanGo").onclick = async () => {
    try {
      await api.send("POST", "/api/scan", { folder: $("#scanFolder").value.trim(), move: $("#scanMove").checked });
      $("#scanResult").innerHTML = `<p class="hint">Starting…</p>`;
    } catch (err) { toast(err.message, "error"); }
  };
  for (const src of ["zotero", "calibre"]) {
    const dir = $(`#${src}Dir`), out = $(`#${src}Result`), go = $(`[data-import-go=${src}]`);
    go.disabled = false;
    $(`[data-import-check=${src}]`).onclick = async () => {
      try {
        const r = await api.send("POST", `/api/import/${src}/preview`, { folder: dir.value.trim() });
        out.innerHTML = `<p>Found <b>${r.total}</b> items: ${r.with_files} with files, ${r.without_files} without. Items already in your library are skipped.</p>`;
      } catch (err) { out.innerHTML = `<p class="hint">${esc(err.message)}</p>`; }
    };
    go.onclick = async () => {
      out.innerHTML = `<p class="hint">Reading your ${src === "zotero" ? "Zotero" : "Calibre"} library…</p>`;
      try {
        await api.send("POST", `/api/import/${src}/preview`, { folder: dir.value.trim() });
        await api.send("POST", `/api/import/${src}`, { folder: dir.value.trim(), download_oa: src === "zotero" && $("#zoteroOA").checked, move: $(`#${src}Move`).checked });
        out.innerHTML = `<p class="hint">Importing… progress shows here and at the top of the library.</p>`;
      } catch (err) { out.innerHTML = `<p class="error-text">${esc(err.message)}</p>`; }
    };
  }
}
