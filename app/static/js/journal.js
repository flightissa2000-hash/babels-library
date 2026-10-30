/* Babel's Library: the review journal, drawn as a real book.
   Contents pages list everything you've finished (or are reading, or dropped); each title has a two-page spread:
   its details on the left, your dated entries on the right. Pages turn; thumb tabs jump to a section. */
const Journal = (() => {
  const J = { rows: [], loaded: false, status: "all", q: "", spread: 0, cache: new Map(), byItem: new Map(), previewUrl: null, photos: new Map() };
  const KIND_NAMES = { book: "Books", movie: "Films", show: "Shows", game: "Games", other: "Other", writing: "Writing" };
  const KIND_ONE = { book: "Book", movie: "Film", show: "Show", game: "Game", other: "Other", writing: "Writing" };
  const KIND_ICON = { book: "📖", movie: "🎬", show: "📺", game: "🎮", other: "✦", writing: "✍" };
  const KIND_TAB = { book: "#9fd18b", movie: "#f2b06b", show: "#b9a3e8", game: "#8fc9e8", other: "#e8a3b6", writing: "#a9c4e6" };
  /* two notebooks: the review journal (what you read and watch), and the writing notebook (anything else: ideas,
     drafts, and the quick notes collected from the phone). The writing notebook's pages are kind "writing". */
  let BOOK = "reviews";
  try { BOOK = localStorage.getItem("inkwell-jbook") === "writing" ? "writing" : "reviews"; } catch (e) {}
  const W = () => BOOK === "writing";
  const inBookRows = () => J.rows.filter((r) => (r.kind === "writing") === W());
  const STATUS = { finished: "Finished", reading: "Reading", hold: "On hold", dropped: "Dropped" };
  // contents lines that fit on a page (the book is as tall as the window allows)
  const linesPerPage = () => {
    const h = J.modal ? BOOK_H : Math.max(520, Math.min(860, window.innerHeight - 175));
    return window.innerWidth < 820 ? 22 : Math.max(10, Math.floor((h - 160) / 23.5) - 1);
  };

  /* ---------------- little helpers ---------------- */
  const fmtDay = (iso) => {
    if (!iso) return "";
    const d = new Date(iso + "T12:00:00");
    return isNaN(d) ? iso : d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
  };
  const fmtStamp = (t) => {
    const d = new Date(t * 1000);
    return { day: d.toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long", year: "numeric" }),
             time: d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" }) };
  };
  const domain = (u) => { try { return new URL(u).hostname.replace(/^www\.|^en\.(m\.)?/, ""); } catch (e) { return ""; } };
  const today = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`; };
  function md(text) {
    let h = esc(text || "");
    h = h.replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g, (m, t, u) => `<a href="#" data-preview="${u}">${t}</a>`);
    h = h.replace(/\[\[([^\]|]+)(?:\|([^\]]+))?\]\]/g, (m, a, b) => `<em class="jr-wiki">${b || a}</em>`);
    h = h.replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>").replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<i>$2</i>");
    // "Fig. 2" (or "figure 2", "[fig 2]") points at that photo on the left page
    h = h.replace(/(^|[\s(—–-])\[?fig(?:ure)?\.?\s?(\d{1,3})\]?/gi, (m, pre, n) => `${pre}<a href="#" class="jb-figref" data-figref="${n}">Fig.&nbsp;${n}</a>`);
    return h.split(/\n\s*\n/).map((p) => `<p>${p.trim().replace(/\n/g, "<br>")}</p>`).join("");
  }
  const statusOfRow = (r) => r.status || (r.finished ? "finished" : "");

  async function load() {
    J.rows = await api.get("/api/log");
    J.byItem = new Map(J.rows.filter((r) => r.item_id).map((r) => [r.item_id, r]));
    J.loaded = true;
    return J.rows;
  }
  /* status of a library item, for the little badges on Books */
  function statusOf(it) {
    const r = J.byItem.get(it.id);
    const s = r && statusOfRow(r);
    if (s) return s;
    if (it.progress > 0.02 && it.progress < 0.97) return "reading";
    return "";
  }

  /* ---------------- the pages ---------------- */
  function visibleRows() {
    const q = (J.q || "").toLowerCase().trim();
    return inBookRows().filter((r) => (W() || J.status === "all" || statusOfRow(r) === J.status) && (!q || (r.title || "").toLowerCase().includes(q)));
  }
  const ORDER = ["book", "movie", "show", "game", "other", "writing"];
  const sortRows = (a, b) => (b.finished || "").localeCompare(a.finished || "") || (a.title || "").localeCompare(b.title || "");

  /* pages: [{type:"intro"}, {type:"toc", lines}, ..., {type:"info", row}, {type:"notes", row}, ...] */
  function buildPages() {
    const rows = visibleRows();
    const kinds = ORDER.filter((k) => rows.some((r) => r.kind === k));
    const titles = kinds.flatMap((k) => rows.filter((r) => r.kind === k).sort(sortRows));
    // contents lines
    const lines = [];
    for (const k of kinds) {
      lines.push({ head: k });
      for (const r of titles.filter((x) => x.kind === k)) lines.push({ row: r });
    }
    const LINES = linesPerPage();
    const tocPages = [];
    for (let i = 0; i < Math.max(1, lines.length); i += LINES) {
      const chunk = lines.slice(i, i + LINES);
      if (chunk.length > 1 && chunk[chunk.length - 1].head) { chunk.pop(); i--; }   // no heading alone at the foot of a page
      tocPages.push(chunk);
    }
    const pages = [{ type: "intro" }, ...tocPages.map((l) => ({ type: "toc", lines: l }))];
    if (pages.length % 2) pages.push({ type: "blank" });   // every title starts on a left page
    J.yearPage = W() ? 0 : pages.length;   // the year in review: a spread of its own, right after the contents
    if (!W()) pages.push({ type: "yearl" }, { type: "yearr" });
    J.pageOf = new Map();
    J.kindPage = {};
    for (const k of kinds) {
      const at = lines.findIndex((l) => l.head === k);
      J.kindPage[k] = 1 + tocPages.findIndex((pg) => pg.some((l) => l.head === k));
    }
    for (const r of titles) {
      J.pageOf.set(r.id, pages.length);
      pages.push({ type: "info", row: r }, { type: "notes", row: r });
    }
    J.pages = pages;
    J.kinds = kinds;
    return pages;
  }

  function pageHTML(p, n) {
    if (!p) return `<div class="jb-pg jb-empty"></div>`;
    let body = "";
    if (p.type === "intro") body = introPage();
    else if (p.type === "toc") body = tocPage(p.lines);
    else if (p.type === "info") body = infoPage(p.row);
    else if (p.type === "notes") body = notesPage(p.row);
    else if (p.type === "yearl") body = yearLeft();
    else if (p.type === "yearr") body = yearRight();
    else body = `<div class="jb-blankart">❦</div>`;
    return `<div class="jb-pg jb-${p.type}" data-page="${n}">${body}</div>`;
  }

  function introPage() {
    if (W()) {
      const rows = inBookRows();
      return `<h1 class="jb-h1">WRITING NOTEBOOK</h1>
        <div class="jb-sub">ideas, drafts, plans, and the quick notes from your phone</div>
        <label class="jb-search"><span>⌕</span><input id="jbSearch" value="${esc(J.q)}" placeholder="write a title to find it…" autocomplete="off"></label>
        <div class="jb-count">${rows.length} ${rows.length === 1 ? "PAGE" : "PAGES"} · ${rows.reduce((n, r) => n + (r.entries || 0), 0)} ENTRIES</div>
        <div class="jb-actions"><button class="jb-ink" data-jw-new>＋ A new page</button><button class="jb-ink" data-jb-book="reviews">📔 The review journal</button></div>`;
    }
    const year = String(new Date().getFullYear());
    const cnt = (k, s) => J.rows.filter((r) => r.kind === k && (!s || (r.finished || "").startsWith(year))).length;
    const st = (s) => J.rows.filter((r) => statusOfRow(r) === s).length;
    return `<h1 class="jb-h1">REVIEW JOURNAL</h1>
      <div class="jb-sub">everything you've read and watched, in your own words</div>
      <label class="jb-search"><span>⌕</span><input id="jbSearch" value="${esc(J.q)}" placeholder="write a title to find it…" autocomplete="off"></label>
      <div class="jb-count">${J.rows.length} TITLES · ${J.rows.filter((r) => r.entries).length} WITH REVIEWS</div>
      <div class="jb-year">
        ${ORDER.filter((k) => cnt(k)).map((k) => `<div><b>${cnt(k, true)}</b><span>${KIND_NAMES[k].toLowerCase()} in ${year}</span><em>${cnt(k)} in all</em></div>`).join("")}
      </div>
      <div class="jb-filter">${[["all", "Everything", J.rows.length], ["finished", "Finished", st("finished")], ["reading", "Reading", st("reading")], ["hold", "On hold", st("hold")], ["dropped", "Dropped", st("dropped")]]
        .map(([v, l, n]) => `<button class="jb-chip ${J.status === v ? "on" : ""}" data-jb-status="${v}">${l} <small>${n}</small></button>`).join("")}</div>
      <div class="jb-actions"><button class="jb-ink" data-jr-new>＋ Log something new</button><button class="jb-ink" data-jr-import>Import from Obsidian…</button><button class="jb-ink" data-jb-book="writing">✍ The writing notebook</button></div>`;
  }

  function tocPage(lines) {
    if (!lines.length) return `<h2 class="jb-h2">Contents</h2><p class="jb-none">${J.rows.length ? "Nothing matches." : "Nothing logged yet. Log something you've finished, or import your notes from Obsidian."}</p>`;
    return `<h2 class="jb-h2">Contents</h2>` + lines.map((l) => l.head
      ? `<div class="jb-sec"><span>${KIND_ICON[l.head]}</span>${KIND_NAMES[l.head]}</div>`
      : tocLine(l.row)).join("");
  }
  function tocLine(r) {
    const s = statusOfRow(r);
    return `<button class="jb-line" data-jb-go="${r.id}">
      <span class="jb-lt">${esc(r.title)}</span>
      <span class="jb-dots"></span>
      ${s && s !== "finished" ? `<span class="jb-st st-${s}">${STATUS[s]}</span>` : ""}
      ${r.kind === "movie" && r.score != null ? `<span class="jb-sc">${+r.score}</span>` : ""}
      <span class="jb-pn" title="${r.entries ? r.entries + (r.entries === 1 ? " entry" : " entries") : "no entries yet"}">${r.entries ? `✎ ${r.entries}` : ""}</span></button>`;
  }

  function infoPage(r) {
    const lib = r.item_id && S.items.find((i) => i.id === r.item_id);
    const s = statusOfRow(r);
    const cover = lib && lib.has_cover ? `<img src="/api/items/${lib.id}/cover?v=${lib.cover_v || 0}" alt="">` : "";
    return `<div class="jb-kick">${KIND_ICON[r.kind] || "✦"} ${(KIND_ONE[r.kind] || "Entry").toUpperCase()}</div>
      <textarea class="jb-title" data-jb-field="title" rows="2" spellcheck="false">${esc(r.title)}</textarea>
      ${r.kind === "writing" ? `<div class="jb-fields"><label><span>Begun</span><em>${esc(new Date((r.created_at || 0) * 1000).toLocaleDateString(undefined, { day: "numeric", month: "long", year: "numeric" }))}</em></label>
        <label><span>Link</span><input data-jb-field="link" value="${esc(r.link || "")}" placeholder="https://…"></label></div>${figsHTML(r.id)}
        <button class="jb-remove" data-jb-del="${r.id}">tear out this page</button>` : `<div class="jb-stamps">${Object.entries(STATUS).map(([k, l]) => `<button class="jb-stamp st-${k} ${s === k ? "on" : ""}" data-jb-setstatus="${k}">${l}</button>`).join("")}</div>
      ${cover ? `<div class="jb-photo">${cover}<span class="jb-tape"></span></div>` : ""}
      <div class="jb-fields">
        <label><span>Type</span><select data-jb-field="kind">${Object.keys(KIND_ONE).map((k) => `<option value="${k}" ${k === r.kind ? "selected" : ""}>${KIND_ONE[k]}</option>`).join("")}</select></label>
        <label><span>Finished</span><input type="date" data-jb-field="finished" value="${esc(r.finished || "")}"><button class="jb-mini" data-jb-today>today</button></label>
        ${r.kind !== "movie" ? "" : `<label><span>My score</span><input type="number" min="0" max="10" step="0.5" data-jb-field="score" value="${r.score ?? ""}" placeholder="–"><em>/ 10</em></label>`}
        <label><span>Link</span><input data-jb-field="link" value="${esc(r.link || "")}" placeholder="https://…">${r.link ? `<button class="jb-mini" data-preview="${esc(r.link)}">preview</button>` : ""}</label>
      </div>
      ${r.kind === "other" ? figsHTML(r.id) : ""}
      ${lib ? `<div class="jb-lib">In your library: <b>${esc(lib.title)}</b><span><button class="jb-mini" data-jb-lib="${lib.id}">details</button>${lib.has_file ? `<button class="jb-mini" data-read="${lib.id}">${["movie", "tv"].includes(lib.kind) ? "watch" : "read"}</button>` : ""}</span></div>` : ""}
      <button class="jb-remove" data-jb-del="${r.id}">remove from the journal</button>`}`;
  }

  function notesPage(r) {
    const log = J.cache.get(r.id);
    if (!log) { fetchLog(r.id); return `<div class="jb-loading">…</div>`; }
    const es = log.journal || [];
    return `<div class="jb-notes-h"><span>${esc(r.title)}</span><em>${es.length ? `${es.length} ${es.length === 1 ? "entry" : "entries"}` : "no entries yet"}</em></div>
      <div class="jb-entries" data-jb-entries="${r.id}">
        ${es.map((e) => {
          const st = fmtStamp(e.created_at);
          const imp = e.source && e.source.startsWith("obsidian:");
          return `<article class="jb-entry" data-entry="${e.id}">
            <header><time>${esc(st.day)}</time>${imp ? `<em title="Imported from your Obsidian note">from your notes</em>` : `<span>${esc(st.time)}</span>`}
              <span class="jb-eact"><button class="jb-mini" data-jb-edit="${e.id}">edit</button><button class="jb-mini" data-jb-edel="${e.id}">delete</button></span></header>
            <div class="jb-body">${md(e.body)}</div></article>`;
        }).join(`<div class="jb-fleuron">❦</div>`)}
        <form class="jb-write" data-jb-write="${r.id}">
          <div class="jb-wdate">${esc(fmtStamp(Date.now() / 1000).day)}</div>
          <textarea placeholder="write today's entry here… (Ctrl+Enter)"></textarea>
          <div class="jb-wrow"><button class="jb-ink" type="submit">add entry</button></div>
        </form>
      </div>`;
  }

  /* ---------------- year in review ---------------- */
  const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
  function yearsLogged() {
    const ys = new Set(J.rows.map((r) => (r.finished || "").slice(0, 4)).filter((y) => /^\d{4}$/.test(y)));
    ys.add(String(new Date().getFullYear()));
    return [...ys].map(Number).sort((a, b) => b - a);
  }
  const inYear = (y) => J.rows.filter((r) => (r.finished || "").startsWith(String(y)));
  function yearLeft() {
    const years = yearsLogged();
    const y = J.year || years[0];
    const rows = inYear(y);
    const done = rows.filter((r) => statusOfRow(r) !== "dropped");
    const dropped = rows.filter((r) => statusOfRow(r) === "dropped");
    const by = (k) => done.filter((r) => r.kind === k);
    const films = by("movie").filter((r) => r.score != null);
    const avg = films.length ? (films.reduce((a, r) => a + Number(r.score), 0) / films.length).toFixed(1) : null;
    const best = [...films].sort((a, b) => b.score - a.score).slice(0, 3);
    const perMonth = MONTHS.map((_, i) => rows.filter((r) => Number(r.finished.slice(5, 7)) === i + 1).length);
    const busiest = Math.max(...perMonth);
    const reviews = rows.reduce((a, r) => a + (r.entries || 0), 0);
    const i = years.indexOf(y);
    return `<div class="jb-kick">YEAR IN REVIEW</div>
      <div class="jb-yearnav">
        <button class="jb-turnyr" ${i < years.length - 1 ? `data-jb-year="${years[i + 1]}"` : "disabled"} title="Earlier year">‹</button>
        <b>${y}</b>
        <button class="jb-turnyr" ${i > 0 ? `data-jb-year="${years[i - 1]}"` : "disabled"} title="Later year">›</button>
      </div>
      <div class="jb-yrs">${years.map((x) => `<button class="jb-chip ${x === y ? "on" : ""}" data-jb-year="${x}">${x}</button>`).join("")}</div>
      ${rows.length ? `
      <div class="jb-year jb-ybig">${ORDER.filter((k) => by(k).length).map((k) => `<div><b>${by(k).length}</b><span>${KIND_ICON[k]} ${KIND_NAMES[k].toLowerCase()}</span></div>`).join("")}</div>
      <p class="jb-ysum">You finished <b>${done.length}</b> ${done.length === 1 ? "thing" : "things"} in ${y}${dropped.length ? ` and set <b>${dropped.length}</b> aside` : ""}, and wrote <b>${reviews}</b> journal ${reviews === 1 ? "entry" : "entries"} about them.</p>
      <div class="jb-months">${perMonth.map((n, m) => `<div title="${MONTHS[m]}: ${n}"><i style="height:${busiest ? Math.round(100 * n / busiest) : 0}%"></i><span>${MONTHS[m][0]}</span></div>`).join("")}</div>
      ${avg ? `<div class="jb-ysub">Films: average score <b>${avg}</b> / 10</div>
        <div class="jb-ybest">${best.map((r, n) => `<button class="jb-line" data-jb-go="${r.id}"><span class="jb-lt">${["🥇", "🥈", "🥉"][n]} ${esc(r.title)}</span><span class="jb-dots"></span><span class="jb-sc">${+r.score}</span></button>`).join("")}</div>` : ""}`
      : `<p class="jb-none">Nothing finished in ${y} yet.</p>`}`;
  }
  function yearRight() {
    const y = J.year || yearsLogged()[0];
    const rows = inYear(y).sort((a, b) => a.finished.localeCompare(b.finished));
    if (!rows.length) return `<h2 class="jb-h2">${y}, month by month</h2><p class="jb-none">Finish something and give it a date, and it'll be listed here.</p>`;
    const out = [];
    MONTHS.forEach((name, m) => {
      const list = rows.filter((r) => Number(r.finished.slice(5, 7)) === m + 1);
      if (!list.length) return;
      out.push(`<div class="jb-sec">${name}</div>` + list.map((r) => {
        const s = statusOfRow(r);
        return `<button class="jb-line" data-jb-go="${r.id}"><span class="jb-lt">${KIND_ICON[r.kind] || "✦"} ${esc(r.title)}</span><span class="jb-dots"></span>
          ${s === "dropped" ? `<span class="jb-st st-dropped">Dropped</span>` : ""}${r.kind === "movie" && r.score != null ? `<span class="jb-sc">${+r.score}</span>` : ""}<span class="jb-pn">${Number(r.finished.slice(8, 10))}</span></button>`;
      }).join(""));
    });
    return `<h2 class="jb-h2">${y}, month by month</h2>${out.join("")}`;
  }

  async function fetchLog(id) {
    if (J.fetching?.has(id)) return;
    (J.fetching ||= new Set()).add(id);
    try { J.cache.set(id, await api.get(`/api/log/${id}`)); } catch (e) {}
    J.fetching.delete(id);
    // fill in any page now showing this title
    document.querySelectorAll(`.jb-pg.jb-notes`).forEach((pg) => {
      const p = J.pages[Number(pg.dataset.page)];
      if (p && p.row.id === id) pg.outerHTML = pageHTML(p, Number(pg.dataset.page));
    });
    paintFigs(id);       // (photos the entries mention get their border lit)
  }

  /* ---------------- photos: screen snips as polaroids under a note's details, numbered as figures ---------------- */
  const TILTS = [-3, 2.2, -1.4, 3, -2.4, 1.2];
  const citedIn = (id) => {
    const s = new Set();
    for (const e of J.cache.get(id)?.journal || []) for (const m of (e.body || "").matchAll(/(?:^|[\s(\[—–-])fig(?:ure)?\.?\s?(\d{1,3})/gi)) s.add(Number(m[1]));
    return s;
  };
  function figsHTML(id) {
    const ps = J.photos.get(id);
    if (!ps) fetchPhotos(id);
    const cited = citedIn(id);
    return `<div class="jb-figs" data-jb-figs="${id}">
      ${(ps || []).map((p, i) => `<figure class="jb-pol ${cited.has(p.n) ? "cited" : ""}" data-fig="${p.n}" style="--tilt:${TILTS[i % TILTS.length]}deg"
          title="Fig. ${p.n}${p.caption ? ": " + esc(p.caption) : ""}. Click to mention it in today's entry.">
        <img src="/api/log/${id}/photos/${p.n}.img" alt="" draggable="false"><figcaption><b>Fig. ${p.n}</b>${p.caption ? " " + esc(p.caption) : ""}</figcaption>
        <button class="jb-polzoom" data-jb-polbig="${p.n}" title="Look closer, write a caption">⤢</button></figure>`).join("")}
      <button class="jb-snapbtn" data-jb-snap="${id}" title="Take a picture of part of the screen: drag over the part you want (Esc cancels)"><span>📷</span>Photo</button></div>`;
  }
  async function fetchPhotos(id) {
    if (J.photoFetch?.has(id)) return;
    (J.photoFetch ||= new Set()).add(id);
    try { J.photos.set(id, await api.get(`/api/log/${id}/photos`)); } catch (e) { J.photos.set(id, []); }
    J.photoFetch.delete(id);
    paintFigs(id);
  }
  function paintFigs(id) { document.querySelectorAll(`[data-jb-figs="${id}"]`).forEach((el) => (el.outerHTML = figsHTML(id))); }
  /* light up a figure while its mention is pointed at (or flash it when the mention is clicked) */
  function lightFig(el, on, flash) {
    const pg = el.closest(".jb-spread") || host();
    pg?.querySelectorAll(`.jb-pol[data-fig="${el.dataset.figref}"]`).forEach((p) => {
      p.classList.toggle("lit", on);
      if (flash) { p.classList.remove("flash"); void p.offsetWidth; p.classList.add("flash"); p.scrollIntoView({ block: "nearest", behavior: "smooth" }); }
    });
  }
  document.addEventListener("mouseover", (e) => { const r = e.target.closest?.(".jb-figref"); if (r) lightFig(r, true); });
  document.addEventListener("mouseout", (e) => { const r = e.target.closest?.(".jb-figref"); if (r) lightFig(r, false); });
  // while you write, the figures your draft mentions light up too
  document.addEventListener("input", (e) => {
    const ta = e.target.closest?.("[data-jb-write] textarea");
    if (!ta) return;
    const draft = new Set([...ta.value.matchAll(/(?:^|[\s(\[—–-])fig(?:ure)?\.?\s?(\d{1,3})/gi)].map((m) => m[1]));
    ta.closest(".jb-spread")?.querySelectorAll(".jb-pol").forEach((p) => p.classList.toggle("lit", draft.has(p.dataset.fig)));
  });

  /* the photo button: the journal steps aside, the window is pictured, and you drag over the part you want */
  async function snip(id) {
    const m = $("#jbModal"), tab = $("#jbPull");
    m.style.visibility = "hidden"; if (tab) tab.style.visibility = "hidden"; dispatchEvent(new Event("journal-moved"));
    document.body.classList.add("jb-snapping");
    let shot;
    try {
      await new Promise((r) => setTimeout(r, 300));            // let the window (and the website, uncut) repaint without the journal
      shot = (await api.send("POST", "/api/desktop/snap", {})).data;
    } catch (err) {
      toast(err.message, "error");
    } finally {
      document.body.classList.remove("jb-snapping");
    }
    if (!shot) { m.style.visibility = ""; if (tab) tab.style.visibility = ""; dispatchEvent(new Event("journal-moved")); return; }
    const ov = document.createElement("div");
    ov.className = "jb-snip";
    ov.innerHTML = `<img src="${shot}" alt=""><div class="jb-sniphint">Drag over the part you want · Esc cancels</div><div class="jb-snipbox" hidden></div>`;
    document.body.append(ov);
    const box = ov.querySelector(".jb-snipbox"), img = ov.querySelector("img");
    const done = async (rect) => {
      ov.remove();
      removeEventListener("keydown", esc, true);
      m.style.visibility = ""; if (tab) tab.style.visibility = ""; dispatchEvent(new Event("journal-moved"));
      if (!rect) return;
      await img.decode().catch(() => {});
      const k = img.naturalWidth / innerWidth;
      const c = document.createElement("canvas");
      c.width = Math.round(rect.w * k); c.height = Math.round(rect.h * k);
      c.getContext("2d").drawImage(img, rect.x * k, rect.y * k, c.width, c.height, 0, 0, c.width, c.height);
      try {
        J.photos.set(id, await api.send("POST", `/api/log/${id}/photos`, { data: c.toDataURL("image/png"), w: c.width, h: c.height }));
        paintFigs(id);
        const n = Math.max(...J.photos.get(id).map((p) => p.n));
        const p = host()?.querySelector(`[data-jb-figs="${id}"] .jb-pol[data-fig="${n}"]`);
        if (p) { p.classList.add("flash", "new"); p.scrollIntoView({ block: "nearest" }); }
        toast(`Saved as Fig. ${n}: write "Fig. ${n}" in an entry to point at it`);
      } catch (err) { toast(err.message, "error"); }
    };
    const esc = (e) => { if (e.key === "Escape") { e.stopPropagation(); e.preventDefault(); done(null); } };
    addEventListener("keydown", esc, true);
    let x0, y0;
    ov.addEventListener("pointerdown", (e) => {
      e.preventDefault();
      ov.setPointerCapture(e.pointerId);
      x0 = e.clientX; y0 = e.clientY;
      Object.assign(box.style, { left: x0 + "px", top: y0 + "px", width: "0px", height: "0px" });
      box.hidden = false;
      ov.classList.add("dragging");
    });
    ov.addEventListener("pointermove", (e) => {
      if (x0 == null) return;
      Object.assign(box.style, { left: Math.min(x0, e.clientX) + "px", top: Math.min(y0, e.clientY) + "px", width: Math.abs(e.clientX - x0) + "px", height: Math.abs(e.clientY - y0) + "px" });
    });
    ov.addEventListener("pointerup", (e) => {
      if (x0 == null) return;
      const r = { x: Math.min(x0, e.clientX), y: Math.min(y0, e.clientY), w: Math.abs(e.clientX - x0), h: Math.abs(e.clientY - y0) };
      x0 = null;
      done(r.w > 8 && r.h > 8 ? r : null);
    });
  }

  /* a closer look at one photo: its caption, and taking it out */
  function polBig(id, n) {
    const p = (J.photos.get(id) || []).find((x) => x.n === n);
    if (!p) return;
    const body = $("#jbModal .jb-winbody") || host();
    body.querySelector(".jb-polbig")?.remove();
    const v = document.createElement("div");
    v.className = "jb-polbig";
    v.innerHTML = `<figure class="jb-pol big"><img src="/api/log/${id}/photos/${n}.img" alt="">
        <figcaption><b>Fig. ${n}</b><input data-jb-cap value="${esc(p.caption || "")}" placeholder="write a caption…" maxlength="200"></figcaption></figure>
      <div class="jb-polbtns"><button class="jb-ink" data-jb-polref="${n}">mention it in today's entry</button><button class="jb-mini" data-jb-polrm="${n}">remove photo</button><button class="jb-mini" data-jb-polclose>close</button></div>`;
    v.dataset.id = id;
    body.append(v);
    const cap = v.querySelector("[data-jb-cap]");
    cap.onchange = async () => { J.photos.set(id, await api.send("PATCH", `/api/log/${id}/photos/${n}`, { caption: cap.value.trim() })); paintFigs(id); toast("Caption saved"); };
    cap.focus();
  }
  /* "Fig. 3" goes into today's entry, where the cursor is */
  function mention(id, n) {
    const ta = host()?.querySelector(`[data-jb-write="${id}"] textarea`);
    if (!ta) return toast("Turn to this title's entries to write about it.");
    const at = ta.selectionStart ?? ta.value.length, before = ta.value.slice(0, at), word = `${/\S$/.test(before) ? " " : ""}Fig. ${n}`;
    ta.value = before + word + ta.value.slice(ta.selectionEnd ?? at);
    ta.focus();
    ta.setSelectionRange(at + word.length, at + word.length);
    ta.dispatchEvent(new Event("input", { bubbles: true }));
  }

  /* ---------------- the book itself ---------------- */
  function bookHTML() {
    const tabs = [["contents", "Contents", "#f3e7c4"], ...(W() ? [] : [["year", "Year in review", "#f2d27a"]]), ...J.kinds.filter((k) => !W() || k !== "writing").map((k) => [k, KIND_NAMES[k], KIND_TAB[k]]),
      W() ? ["@reviews", "📔 Reviews", "#e9d9b0"] : ["@writing", "✍ Writing", KIND_TAB.writing]];
    return `<div class="jb-book" tabindex="0">
      <div class="jb-cover"></div>
      <div class="jb-spread"><div class="jb-side jb-l"></div><div class="jb-side jb-r"></div></div>
      <div class="jb-gutter"></div><div class="jb-ribbon"></div>
      <div class="jb-tabs">${tabs.map(([k, l, c]) => `<button class="jb-tab" data-jb-tab="${k}" style="--tab:${c}">${l}</button>`).join("")}</div>
      <button class="jb-turn jb-prev" data-jb-turn="-1" title="Previous page (←)">‹</button>
      <button class="jb-turn jb-next" data-jb-turn="1" title="Next page (→)">›</button>
    </div>`;
  }

  function host() { return J.modal ? $("#jbModalBook") : $("#library .jb-desk"); }

  function paintSpread(animate = 0) {
    const h = host();
    if (!h) return;
    const book = h.querySelector(".jb-book");
    const L = book.querySelector(".jb-l"), R = book.querySelector(".jb-r");
    const n = J.spread * 2;
    const newL = pageHTML(J.pages[n], n), newR = pageHTML(J.pages[n + 1], n + 1);
    book.querySelector(".jb-prev").disabled = J.spread <= 0;
    book.querySelector(".jb-next").disabled = (J.spread + 1) * 2 >= J.pages.length;
    // which tab is "open"
    const p = J.pages[n];
    const at = p && (p.type === "info" || p.type === "notes") ? p.row.kind : p && p.type === "yearl" ? "year" : "contents";
    book.querySelectorAll(".jb-tab").forEach((t) => t.classList.toggle("on", t.dataset.jbTab === at));
    if (!animate || window.matchMedia("(prefers-reduced-motion: reduce)").matches || window.innerWidth < 820) {
      L.innerHTML = newL; R.innerHTML = newR; return;
    }
    // turn a leaf: forward, the right page lifts and lands on the left; back, the reverse
    book.querySelectorAll(".jb-leaf").forEach((x) => x.remove());
    const leaf = document.createElement("div");
    leaf.className = `jb-leaf ${animate > 0 ? "fwd" : "back"}`;
    if (animate > 0) {
      leaf.innerHTML = `<div class="jb-face jb-front">${R.innerHTML}</div><div class="jb-face jb-backf">${newL}</div>`;
      R.innerHTML = newR;
    } else {
      leaf.innerHTML = `<div class="jb-face jb-front">${L.innerHTML}</div><div class="jb-face jb-backf">${newR}</div>`;
      L.innerHTML = newL;
    }
    book.querySelector(".jb-spread").append(leaf);
    leaf.addEventListener("animationend", () => {
      if (animate > 0) L.innerHTML = newL; else R.innerHTML = newR;
      leaf.remove();
    }, { once: true });
  }

  function goSpread(s, dir) {
    const max = Math.max(0, Math.ceil(J.pages.length / 2) - 1);
    s = Math.max(0, Math.min(max, s));
    if (s === J.spread) return;
    const d = dir || (s > J.spread ? 1 : -1);
    J.spread = s;
    paintSpread(d);
  }
  const goTitle = (id) => { const p = J.pageOf.get(id); if (p != null) goSpread(Math.floor(p / 2)); };

  /* ---------------- Journal area (inline) ---------------- */
  async function render(lib) {
    J.modal = false;
    if (!J.loaded) { lib.innerHTML = `<div class="jb-desk"><p class="hint">Opening your journal…</p></div>`; await load(); }
    if (S.area !== "journal") return;
    buildPages();
    J.spread = Math.min(J.spread, Math.max(0, Math.ceil(J.pages.length / 2) - 1));
    lib.innerHTML = `<div class="jb-desk">${bookHTML()}</div>`;
    paintSpread(0);
  }

  /* ---------------- the book, pulled out and set down on top of whatever you're doing ----------------
     Just the book (no window around it): it sits over the reader, a video or the browser without stopping them and
     without a backdrop. Drag it by its cover, resize it from the corner grip, tuck it away with the ribbon at the top;
     the book is drawn at one size and scaled to the size you give it. */
  const BOOK_W = 1300, BOOK_H = 780;
  const geom = () => {
    let g = null;
    try { g = JSON.parse(localStorage.getItem("inkwell-jwin") || "null"); } catch (e) {}
    const w = Math.min(innerWidth - 20, g?.w || Math.round(Math.min(980, innerWidth * 0.62)));
    const h = Math.min(innerHeight - 20, g?.h || Math.round(w * (BOOK_H / BOOK_W)));
    const x = Math.max(0, Math.min(innerWidth - 80, g?.x ?? innerWidth - w - 24));
    const y = Math.max(0, Math.min(innerHeight - 40, g?.y ?? 80));
    return { x, y, w, h };
  };
  function fit() {
    const body = $("#jbModal .jb-winbody"), book = $("#jbModalBook");
    if (!body || !book) return;
    const z = Math.max(0.2, Math.min(body.clientWidth / BOOK_W, body.clientHeight / BOOK_H)).toFixed(4);
    book.style.zoom = z;
    $("#jbWin").style.setProperty("--z", z);           // (the ribbon and the corner grip sit on the book's corners)
  }
  function keepGeom() {
    const w = $("#jbWin");
    if (!w) return;
    try { localStorage.setItem("inkwell-jwin", JSON.stringify({ x: w.offsetLeft, y: w.offsetTop, w: w.offsetWidth, h: w.offsetHeight })); } catch (e) {}
    dispatchEvent(new Event("journal-moved"));          // (the browser cuts the window out of the website it shows)
  }
  function floatWin() {
    let m = $("#jbModal");
    if (m) return m;
    m = document.createElement("div"); m.id = "jbModal"; m.className = "jb-modal jb-floating";
    m.innerHTML = `<div class="jb-win" id="jbWin">
        <div class="jb-winbody"><div class="jb-modal-in" id="jbModalBook"></div></div>
        <button class="jb-tuck" data-jb-close title="Tuck it away (Esc while you're in it)"><span>✕</span></button>
        <span class="jb-grab" title="Drag to move the journal">✥ move</span>
        <span class="jb-grip" title="Drag to resize"></span></div>`;
    document.body.append(m);
    const win = $("#jbWin"), g = geom();
    Object.assign(win.style, { left: g.x + "px", top: g.y + "px", width: g.w + "px", height: g.h + "px" });
    new ResizeObserver(() => { fit(); clearTimeout(J._gt); J._gt = setTimeout(keepGeom, 150); dispatchEvent(new Event("journal-moved")); }).observe(win);
    const drag = (el, onMove, only) => el.addEventListener("pointerdown", (e) => {
      if (e.button !== 0 || (only && !e.target.matches(only))) return;
      e.preventDefault();
      // (captured on the very thing grabbed: the journal's frame lets clicks through to the page, so it can't hold a drag itself)
      const g = e.target;
      g.setPointerCapture(e.pointerId);
      const s = { x: e.clientX, y: e.clientY, l: win.offsetLeft, t: win.offsetTop, w: win.offsetWidth, h: win.offsetHeight };
      win.classList.add("moving");
      const mv = (ev) => { onMove(ev.clientX - s.x, ev.clientY - s.y, s); dispatchEvent(new Event("journal-moved")); };
      const up = () => { win.classList.remove("moving"); g.removeEventListener("pointermove", mv); g.removeEventListener("pointerup", up); g.removeEventListener("pointercancel", up); keepGeom(); };
      g.addEventListener("pointermove", mv);
      g.addEventListener("pointerup", up);
      g.addEventListener("pointercancel", up);
    });
    // pick it up by the move tab on top, or by its cover (the leather around the pages, the spine)
    const move = (dx, dy, s) => {
      win.style.left = Math.max(-s.w + 80, Math.min(innerWidth - 80, s.l + dx)) + "px";
      win.style.top = Math.max(-20, Math.min(innerHeight - 60, s.t + dy)) + "px";
    };
    drag(win.querySelector(".jb-grab"), move);
    drag(win.querySelector(".jb-winbody"), move, ".jb-cover, .jb-book, .jb-gutter, .jb-spread, .jb-ribbon");
    // resize from the corner grip, keeping the book's shape
    drag(win.querySelector(".jb-grip"), (dx, dy, s) => {
      const w = Math.max(360, Math.min(innerWidth - s.l, s.w + Math.max(dx, dy * BOOK_W / BOOK_H)));
      win.style.width = w + "px";
      win.style.height = Math.round(w * BOOK_H / BOOK_W) + "px";
    });
    // keys typed in the journal stay in the journal (the reader or video underneath doesn't see them)
    m.addEventListener("keydown", (e) => { if (e.key !== "Escape") e.stopPropagation(); });
    return m;
  }
  /* (the Journal button at the top, or J) opens it on whatever you're busy with: the book or video in the reader, the item in Details, or the contents */
  async function openHere() {
    await load();
    const reading = window.readerItem && window.readerItem();
    const it = reading || (S.openId && S.items.find((x) => x.id === S.openId));
    const row = it && J.byItem.get(it.id);
    if (!row && reading) return openForItem(reading, { write: true });     // pulled out over a book: its pages, ready to write
    return open(row ? row.id : null);
  }

  async function open(logId) {
    await load();
    J.status = "all"; J.q = "";
    J.modal = true;
    const lr = logId && J.rows.find((r) => r.id === logId);
    if (lr) BOOK = lr.kind === "writing" ? "writing" : "reviews";        // (in whichever notebook it's in)
    buildPages();
    const m = floatWin();
    const already = m.classList.contains("open");
    J.modal = true;
    $("#jbModalBook").innerHTML = bookHTML();
    const p = J.pageOf.get(logId);
    J.spread = p != null ? Math.floor(p / 2) : 0;
    paintSpread(0);
    // the book's cover swings open where it lies (it used to be carried in from below the screen, which only
    // suited the old full-window pop-up)
    const book = $("#jbModalBook .jb-book");
    if (!already && !window.matchMedia("(prefers-reduced-motion: reduce)").matches && window.innerWidth >= 820) {
      const lid = document.createElement("div");
      lid.className = "jb-lid";
      lid.innerHTML = `<div class="jb-lid-front"><span class="jb-lid-rule"></span><b>${W() ? "WRITING<br>NOTEBOOK" : "REVIEW<br>JOURNAL"}</b><span class="jb-lid-rule"></span><em>Babel's Library</em></div><div class="jb-lid-back"></div>`;
      book.querySelector(".jb-spread").append(lid);
      book.classList.add("opening");
      lid.addEventListener("animationend", (e) => { if (e.target === lid) { book.classList.remove("opening"); lid.remove(); } });
    }
    m.classList.remove("closing");
    fit();
   requestAnimationFrame(() => { m.classList.add("open"); dispatchEvent(new Event("journal-moved")); });
  }
  function closeModal() {
    const m = $("#jbModal");
    if (!m || !m.classList.contains("open")) return false;
    m.classList.add("closing");
    setTimeout(() => { m.classList.remove("open", "closing"); dispatchEvent(new Event("journal-moved")); }, 320);
   J.modal = false;
    if (S.openId && $("#dJournal")) { const it = S.items.find((x) => x.id === S.openId); if (it) paintItemSection(it); }
    if (S.view === "heist" && $("#stageJr")) { const it = S.items.find((x) => x.id === Number($("#stageJr").dataset.id)); if (it) paintStage(it); }
    if (S.area === "journal") render($("#library"));
    return true;
  }
  async function openForItem(item, opts = {}) {
    const log = await api.send("POST", `/api/items/${item.id}/log`, opts.status ? { status: opts.status } : {});
    J.cache.delete(log.id);
    await open(log.id);
    if (opts.write) setTimeout(() => host()?.querySelector(".jb-write textarea")?.focus(), 700);
  }

  /* refresh data and repaint in place (after an edit) */
  async function reloadRow(id, keepSpread = true) {
    J.cache.delete(id);
    await load();
    buildPages();
    if (keepSpread) {
      const p = J.pageOf.get(id);
      if (p != null) J.spread = Math.floor(p / 2);
    }
    paintSpread(0);
  }

  /* ---------------- link preview: a sheet of paper on the desk ---------------- */
  function preview(url) {
    if (!url || !/^https?:\/\//.test(url)) return toast("That isn't a web link.", "error");
    J.previewUrl = url;
    let pv = $("#jbPreview");
    if (!pv) {
      pv = document.createElement("div"); pv.id = "jbPreview"; pv.className = "jb-pv";
      document.body.append(pv);
    }
    pv.innerHTML = `<div class="jb-scrim" data-jb-pvclose></div>
      <div class="jb-sheet">
        <div class="jb-rings">${"<i></i>".repeat(18)}</div>
        <div class="jb-sheet-h"><b>${esc(domain(url))}</b><span title="${esc(url)}">${esc(url)}</span></div>
        <div class="jb-sheet-tabs"><button data-jb-pvout style="--tab:#9fd18b">Open in browser</button><button data-jb-pvclose style="--tab:#f2b06b">Put away</button></div>
        <div class="jb-sheet-body"><div class="jb-pvload">Loading the page…</div>
          <iframe sandbox="allow-popups allow-popups-to-escape-sandbox" referrerpolicy="no-referrer" src="/api/webpreview?url=${encodeURIComponent(url)}"></iframe></div>
      </div>`;
    pv.querySelector("iframe").addEventListener("load", () => pv.querySelector(".jb-pvload")?.remove());
    requestAnimationFrame(() => pv.classList.add("open"));
  }
  function closePreview() { const pv = $("#jbPreview"); if (!pv || !pv.classList.contains("open")) return false; pv.classList.remove("open"); setTimeout(() => { if (!pv.classList.contains("open")) pv.innerHTML = ""; }, 300); return true; }

  /* ---------------- Details drawer: this item's review ---------------- */
  async function paintItemSection(it) {
    const el = $("#dJournal");
    if (!el) return;
    let log = null;
    try { log = await api.get(`/api/items/${it.id}/log`); } catch (e) {}
    if (!$("#dJournal") || Number($("#dJournal").dataset.id) !== it.id) return;
    const n = log ? (log.journal || []).length : 0;
    const last = n ? log.journal[n - 1] : null;
    const s = log ? statusOfRow(log) : (it.progress > 0.02 && it.progress < 0.97 ? "reading" : "");
    el.innerHTML = `<h4>Review journal</h4>
      <div class="jr-status">${Object.entries(STATUS).map(([k, l]) => `<button class="jb-stamp st-${k} ${s === k ? "on" : ""}" data-jr-itemstatus="${k}" data-id="${it.id}">${l}</button>`).join("")}
        ${log && log.finished ? `<span class="hint">finished ${esc(fmtDay(log.finished))}${log.kind === "movie" && log.score != null ? ` · ${+log.score}/10` : ""}</span>` : ""}</div>
      ${last ? `<blockquote class="jr-snip"><time>${esc(fmtStamp(last.created_at).day)}</time>${esc(last.body.slice(0, 260))}${last.body.length > 260 ? "…" : ""}</blockquote>` : `<p class="hint">No review yet.</p>`}
      <div class="row wrap"><button class="btn primary sm" data-jr-item="${it.id}">${n ? `Open journal (${n} ${n === 1 ? "entry" : "entries"})` : "Write a review"}</button></div>`;
  }

  /* ---------------- calling-card stage (Cards view) ---------------- */
  async function paintStage(it) {
    const box = $("#stageJr");
    if (!box || !["book", "graphic", "movie", "tv"].includes(it.kind)) return;
    let log = null;
    try { log = await api.get(`/api/items/${it.id}/log`); } catch (e) {}
    const el = $("#stageJr");
    if (!el || Number(el.dataset.id) !== it.id) return;
    const entries = (log && log.journal) || [];
    const s = log ? statusOfRow(log) : statusOf(it);
    const open = el.dataset.expanded === "1";   // starts folded; click the header to read it
    const stamps = `<span class="sj-stamps">${Object.entries(STATUS).map(([k, l]) => `<button class="jb-stamp sm st-${k} ${s === k ? "on" : ""}" data-jr-itemstatus="${k}" data-id="${it.id}">${l}</button>`).join("")}</span>`;
    const meta = entries.length ? `${entries.length} ${entries.length === 1 ? "entry" : "entries"}${log.finished ? ` · finished ${esc(fmtDay(log.finished))}` : ""}${log.kind === "movie" && log.score != null ? ` · ${+log.score}/10` : ""}` : "no entries yet";
    el.classList.toggle("open", open);
    el.innerHTML = `<h4><button class="sj-toggle" data-sj-toggle aria-expanded="${open}"><span class="sj-chev">▸</span>✎ Review journal <small>${meta}</small></button><span class="spacer"></span>${stamps}${log ? `<button class="btn sm" data-jb-open="${log.id}">Open the journal</button>` : ""}</h4>
      ${open ? `${entries.length ? `<div class="sj-list">${entries.map((e) => `<article class="jb-entry"><header><time>${esc(fmtStamp(e.created_at).day)}</time></header><div class="jb-body">${md(e.body)}</div></article>`).join(`<div class="jb-fleuron">❦</div>`)}</div>` : ""}${writeBox(it, true)}` : ""}`;
    const list = el.querySelector(".sj-list");
    if (list) list.scrollTop = list.scrollHeight;
  }
  const writeBox = (it, quiet) => `${quiet ? "" : `<h4>✎ Review journal</h4>`}<form class="sj-write" data-sj-item="${it.id}">
      <textarea placeholder="Add today's thoughts… (Ctrl+Enter)"></textarea>
      <div class="row"><span class="hint">${esc(fmtStamp(Date.now() / 1000).day)}</span><span class="spacer"></span><button class="btn sm primary" type="submit">Add entry</button></div></form>`;

  /* ---------------- import & new ---------------- */
  async function importDialog() {
    let d = $("#jrImport");
    if (!d) {
      d = document.createElement("dialog"); d.id = "jrImport"; d.className = "dlg";
      d.innerHTML = `<form method="dialog" class="dlg-head"><h2>Import from Obsidian</h2><button class="icon-btn" value="cancel" title="Close">✕</button></form>
        <p class="hint">Pick the folder with your notes (or the folder they sit in). Tables with a <b>Title</b> column (and Link, Thoughts, Score, Date finished) become your log; each <b>[[note]]</b> becomes that title's journal, one entry per sitting. Your notes aren't changed, and importing again only adds what's new.</p>
        <div class="row"><input id="jrImpFolder" style="flex:1" placeholder="Folder with your Obsidian notes"><button class="btn" type="button" data-pick="#jrImpFolder">Browse…</button></div>
        <div class="row" style="margin-top:12px"><span class="spacer"></span><button class="btn primary" type="button" id="jrImpGo">Import</button></div>
        <div class="import-result" id="jrImpOut"></div>`;
      document.body.append(d);
      d.querySelector("#jrImpGo").onclick = async () => {
        const out = d.querySelector("#jrImpOut");
        out.innerHTML = `<p class="hint">Importing…</p>`;
        try {
          const r = await api.send("POST", "/api/log/import-obsidian", { folder: d.querySelector("#jrImpFolder").value.trim() });
          out.innerHTML = `<p>Added <b>${r.logged}</b> to your journal${r.updated ? `, filled in ${r.updated}` : ""}, with <b>${r.reviews}</b> reviews. ${r.linked} matched books or films in your library.</p>`;
          J.loaded = false; J.cache.clear();
          if (S.area === "journal") render($("#library"));
        } catch (err) { out.innerHTML = `<p class="hint">${esc(err.message)}</p>`; }
      };
    }
    d.querySelector("#jrImpFolder").value = (S.settings && S.settings.obsidian_folder) || "";
    d.querySelector("#jrImpOut").innerHTML = "";
    d.showModal();
  }
  /* the writing notebook: a new page, asked for in a small card */
  function newPage() {
    const d = document.createElement("dialog"); d.className = "dlg";
    d.innerHTML = `<form method="dialog" class="jw-new"><div class="dlg-head"><h2>A new page</h2></div>
      <label class="full">What's it about?<input name="t" placeholder="An idea, a plan, a draft, a trip…" style="width:100%" required></label>
      <div class="row" style="margin-top:12px;justify-content:flex-end;gap:8px"><button class="btn" value="no" formnovalidate>Cancel</button><button class="btn primary" value="ok">Add the page</button></div></form>`;
    document.body.append(d);
    d.addEventListener("close", async () => {
      const title = d.querySelector("[name=t]").value.trim(), ok = d.returnValue === "ok";
      d.remove();
      if (!ok || !title) return;
      try {
        const r = await api.send("POST", "/api/log", { title, kind: "writing", status: "" });
        J.q = ""; await load(); buildPages();
        const p = J.pageOf.get(r.id);
        if (p != null) { if (!host() || (!$("#jbModal.open") && S.area !== "journal")) return open(r.id); goSpread(Math.floor(p / 2), 1); }
      } catch (err) { toast(err.message, "error"); }
    });
    d.showModal();
  }
  async function newEntry() {
    const v = await askNew();
    if (!v) return;
    if (!J.loaded) await load();
    // already in the journal? just turn to it
    const have = v.item_id && J.byItem.get(v.item_id);
    let id = have ? have.id : null;
    if (!id) {
      const r = await api.send("POST", "/api/log", { title: v.title, kind: v.kind, status: v.status, item_id: v.item_id || null, finished: v.status === "finished" ? today() : null });
      id = r.id;
    } else if (v.status) {
      await api.send("PATCH", `/api/log/${id}`, v.status === "finished" && !have.finished ? { status: v.status, finished: today() } : { status: v.status });
    }
    J.q = ""; J.status = "all";
    await load(); buildPages();
    const p = J.pageOf.get(id);
    if (p != null) { if (!host() || !$("#jbModal.open")) return open(id); goSpread(Math.floor(p / 2), 1); }
  }

  /* pick from the library (by category) or type any title */
  const PICK_KINDS = [["book", "Books", "📖"], ["graphic", "Graphic novels", "🗯"], ["movie", "Films", "🎬"], ["tv", "TV shows", "📺"]];
  function pickItems(kind, cat, q) {
    let list = S.items.filter((i) => i.kind === kind);
    if (kind === "tv") {   // one entry per show, not per episode
      const seen = new Map();
      for (const i of list) { const k = (i.series || i.title || "").toLowerCase(); if (!seen.has(k)) seen.set(k, { ...i, title: i.series || i.title }); }
      list = [...seen.values()];
    }
    if (cat) list = list.filter((i) => (i.genre || i.subject || "Other") === cat);
    if (q) { const w = q.toLowerCase(); list = list.filter((i) => [i.title, i.series, (i.authors || []).join(" ")].join(" ").toLowerCase().includes(w)); }
    return list.sort((a, b) => (a.series || a.title || "").localeCompare(b.series || b.title || "") || (a.series_index || 0) - (b.series_index || 0));
  }
  function askNew() {
    return new Promise((res) => {
      const st = { tab: "lib", kind: "book", cat: "", q: "", pick: null };
      const d = document.createElement("dialog"); d.className = "dlg wide jb-pickdlg";
      d.innerHTML = `<div class="dlg-head"><h2>Log something</h2><button class="icon-btn" type="button" data-x title="Close">✕</button></div>
        <div class="seg jb-picktabs"><button type="button" data-ptab="lib" class="on">From your library</button><button type="button" data-ptab="free">Something else</button><button type="button" data-ptab="note">✦ A note (not media)</button></div>
        <div class="jb-pane" data-pane="lib">
          <div class="jb-pickbar">
            <div class="seg" data-kinds>${PICK_KINDS.map(([k, l, ic]) => `<button type="button" data-pkind="${k}" class="${k === "book" ? "on" : ""}">${ic} ${l}</button>`).join("")}</div>
            <select data-pcat></select>
            <input type="search" data-pq placeholder="Search titles, authors, series…">
          </div>
          <div class="jb-picklist" data-plist></div>
        </div>
        <div class="jb-pane" data-pane="free" hidden>
          <label class="full">Title<input data-ft placeholder="A book, film or show that isn't in your library" style="width:100%"></label>
          <label style="margin-top:10px;display:block">Type <select data-fk>${Object.keys(KIND_ONE).map((k) => `<option value="${k}">${KIND_ONE[k]}</option>`).join("")}</select></label>
        </div>
        <div class="jb-pane" data-pane="note" hidden>
          <label class="full">What's it about?<input data-nt placeholder="A trip, a project, an idea, a recipe… anything" style="width:100%"></label>
          <p class="hint">Filed under Other. Add dated entries to it like any journal page; it has no reading status.</p>
        </div>
        <div class="row jb-pickfoot"><span class="jb-picked" data-picked>Pick something above</span><span class="spacer"></span>
          <label>Status <select data-ps><option value="finished">Finished today</option><option value="reading">Reading / watching</option><option value="hold">On hold</option><option value="dropped">Dropped</option></select></label>
          <button class="btn" type="button" data-x>Cancel</button><button class="btn primary" type="button" data-ok>Add to the journal</button></div>`;
      document.body.append(d);
      const cats = () => {
        const counts = {};
        for (const i of pickItems(st.kind, "", "")) { const c = i.genre || i.subject || "Other"; counts[c] = (counts[c] || 0) + 1; }
        d.querySelector("[data-pcat]").innerHTML = `<option value="">Every category</option>` + Object.keys(counts).sort().map((c) => `<option value="${esc(c)}" ${c === st.cat ? "selected" : ""}>${esc(c)} (${counts[c]})</option>`).join("");
      };
      const list = () => {
        const items = pickItems(st.kind, st.cat, st.q).slice(0, 300);
        d.querySelector("[data-plist]").innerHTML = items.length ? items.map((i) => {
          const inJ = J.byItem.get(i.id);
          const by = st.kind === "tv" ? "" : (i.authors || []).slice(0, 2).join(", ");
          return `<button type="button" class="jb-pick ${st.pick && st.pick.item_id === i.id ? "on" : ""}" data-jbpick="${i.id}">
            ${i.has_cover ? `<img alt="" loading="lazy" src="/api/items/${i.id}/cover?v=${i.cover_v || 0}">` : `<i class="jb-pcov" style="--c:${typeof colorFor === "function" ? colorFor(i) : "#ccc"}">${esc((i.title || "?")[0])}</i>`}
            <span><b>${esc(i.title || "Untitled")}</b><small>${esc([by, i.series && st.kind !== "tv" ? i.series + (i.series_index ? " #" + +i.series_index : "") : "", i.year].filter(Boolean).join(" · "))}</small></span>
            ${inJ ? `<em class="jb-st st-${statusOfRow(inJ) || "finished"}">${STATUS[statusOfRow(inJ)] || "In journal"}</em>` : ""}</button>`;
        }).join("") : `<p class="hint" style="padding:20px">Nothing here.</p>`;
      };
      const setPicked = () => { d.querySelector("[data-picked]").innerHTML = st.pick ? `Picked: <b>${esc(st.pick.title)}</b>` : "Pick something above"; };
      cats(); list();
      const done = (v) => { d.close(); d.remove(); res(v); };
      d.addEventListener("click", (e) => {
        const t = e.target;
        if (t.closest("[data-x]")) return done(null);
        const pt = t.closest("[data-ptab]");
        if (pt) { st.tab = pt.dataset.ptab; d.querySelectorAll("[data-ptab]").forEach((b) => b.classList.toggle("on", b === pt)); d.querySelectorAll(".jb-pane").forEach((p) => (p.hidden = p.dataset.pane !== st.tab)); if (st.tab === "free") d.querySelector("[data-ft]").focus(); if (st.tab === "note") d.querySelector("[data-nt]").focus(); d.querySelector("[data-ps]").closest("label").hidden = st.tab === "note"; d.querySelector("[data-picked]").hidden = st.tab !== "lib"; return; }
        const pk = t.closest("[data-pkind]");
        if (pk) { st.kind = pk.dataset.pkind; st.cat = ""; d.querySelectorAll("[data-pkind]").forEach((b) => b.classList.toggle("on", b === pk)); cats(); list(); return; }
        const pi = t.closest("[data-jbpick]");
        if (pi) {
          const it = pickItems(st.kind, st.cat, st.q).find((x) => x.id === Number(pi.dataset.jbpick));
          st.pick = it ? { item_id: it.id, title: it.title, kind: { book: "book", graphic: "book", movie: "movie", tv: "show" }[st.kind] } : null;
          d.querySelectorAll("[data-jbpick]").forEach((b) => b.classList.toggle("on", b === pi)); setPicked();
          const inJ = it && J.byItem.get(it.id);
          if (inJ) d.querySelector("[data-ps]").value = statusOfRow(inJ) || "finished";
          return;
        }
        if (t.closest("[data-ok]")) {
          const status = d.querySelector("[data-ps]").value;
          if (st.tab === "lib") { if (!st.pick) return toast("Pick something from your library first.", "error"); return done({ ...st.pick, status }); }
          if (st.tab === "note") { const title = d.querySelector("[data-nt]").value.trim(); if (!title) return toast("Give it a title.", "error"); return done({ title, kind: "other", status: "" }); }
          const title = d.querySelector("[data-ft]").value.trim();
          if (!title) return toast("Give it a title.", "error");
          return done({ title, kind: d.querySelector("[data-fk]").value, status });
        }
      });
      d.querySelector("[data-pcat]").onchange = (e) => { st.cat = e.target.value; list(); };
      d.querySelector("[data-pq]").oninput = (e) => { st.q = e.target.value.trim(); list(); };
      d.addEventListener("cancel", (e) => { e.preventDefault(); done(null); });
      d.addEventListener("dblclick", (e) => { if (e.target.closest("[data-jbpick]")) d.querySelector("[data-ok]").click(); });
      d.showModal();
    });
  }

  /* ---------------- events ---------------- */
  const inBook = (t) => t.closest?.(".jb-book");
  async function saveField(id, field, value) {
    await api.send("PATCH", `/api/log/${id}`, { [field]: value });
    J.cache.delete(id);
    const r = J.rows.find((x) => x.id === id);
    if (r) { r[field] = field === "score" ? (value === "" ? null : Number(value)) : value; if (field === "finished" && value) r.status = "finished"; }
    J.byItem = new Map(J.rows.filter((x) => x.item_id).map((x) => [x.item_id, x]));
    toast("Saved");
    if (["kind", "title"].includes(field)) reloadRow(id);
    else if (field === "finished") { const pg = host()?.querySelector(".jb-info"); if (pg) pg.outerHTML = pageHTML(J.pages[Number(pg.dataset.page)], Number(pg.dataset.page)); }
  }
  const rowOfPage = (el) => { const pg = el.closest(".jb-pg"); return pg ? J.pages[Number(pg.dataset.page)]?.row : null; };

  document.addEventListener("click", async (e) => {
    const t = e.target;
    if (t.closest("[data-jb-close]")) return closeModal();
    if (t.closest("[data-jb-pvclose]")) return closePreview();
    if (t.closest("[data-jb-pvout]")) return api.send("POST", "/api/open-url", { url: J.previewUrl }).catch((err) => toast(err.message, "error"));
    const pv = t.closest("[data-preview]");
    if (pv && (inBook(t) || t.closest("#library") || t.closest("#stageJr"))) { e.preventDefault(); e.stopPropagation(); return preview(pv.dataset.preview); }
    const ob = t.closest("[data-jb-open]");
    if (ob) return open(Number(ob.dataset.jbOpen));
    const it = t.closest("[data-jr-item]");
    if (it) { const item = S.items.find((x) => x.id === Number(it.dataset.jrItem)); if (item) openForItem(item, { write: true }); return; }
    const ist = t.closest("[data-jr-itemstatus]");
    if (ist) {
      const item = S.items.find((x) => x.id === Number(ist.dataset.id));
      if (!item) return;
      const st = ist.dataset.jrItemstatus;
      await api.send("POST", `/api/items/${item.id}/log`, st === "finished" ? { status: st, finished: today() } : { status: st });
      await load(); toast(`Marked ${STATUS[st].toLowerCase()}`);
      if ($("#dJournal")) paintItemSection(item);
      if ($("#stageJr") && Number($("#stageJr").dataset.id) === item.id) paintStage(item);
      if (typeof renderLib === "function" && S.area !== "journal") { const y = scrollY; renderLib(); scrollTo(0, y); }
      return;
    }
    if (t.closest("[data-sj-toggle]")) {
      const box = $("#stageJr");
      box.dataset.expanded = box.dataset.expanded === "1" ? "" : "1";
      const item = S.items.find((x) => x.id === Number(box.dataset.id));
      if (item) await paintStage(item);
      if (box.dataset.expanded) box.querySelector("textarea")?.focus({ preventScroll: true });
      return;
    }
    if (t.closest("[data-jr-new]")) return newEntry();
    if (t.closest("[data-jw-new]")) return newPage();
    const bk = t.closest("[data-jb-book]") || (t.closest("[data-jb-tab]") && t.closest("[data-jb-tab]").dataset.jbTab.startsWith("@") && t.closest("[data-jb-tab]"));
    if (bk) {             // the other notebook
      BOOK = (bk.dataset.jbBook || bk.dataset.jbTab.slice(1)) === "writing" ? "writing" : "reviews";
      try { localStorage.setItem("inkwell-jbook", BOOK); } catch (e) {}
      J.q = ""; buildPages(); J.spread = 0; host().innerHTML = bookHTML(); return paintSpread(0);
    }
    if (t.closest("[data-jr-import]")) return importDialog();
    // ---- photos (figures) ----
    const fr = t.closest(".jb-figref");
    if (fr) { e.preventDefault(); return lightFig(fr, true, true); }
    const sn = t.closest("[data-jb-snap]");
    if (sn) return snip(Number(sn.dataset.jbSnap));
    const big = t.closest(".jb-polbig");
    if (big) {
      const id = Number(big.dataset.id);
      const ref = t.closest("[data-jb-polref]");
      if (ref) { big.remove(); return mention(id, Number(ref.dataset.jbPolref)); }
      if (t.closest("[data-jb-polclose]")) return big.remove();
      const rm = t.closest("[data-jb-polrm]");
      if (rm) {
        if (!rm.dataset.armed) { rm.dataset.armed = 1; rm.textContent = "click again to remove it"; setTimeout(() => { delete rm.dataset.armed; rm.textContent = "remove photo"; }, 3000); return; }
        J.photos.set(id, await api.send("DELETE", `/api/log/${id}/photos/${rm.dataset.jbPolrm}`));
        big.remove(); paintFigs(id); return toast("Photo removed");
      }
      if (t === big) return big.remove();
      return;
    }
    const pz = t.closest("[data-jb-polbig]");
    if (pz) return polBig(Number(pz.closest("[data-jb-figs]").dataset.jbFigs), Number(pz.dataset.jbPolbig));
    const pol = t.closest(".jb-figs .jb-pol");
    if (pol) return mention(Number(pol.closest("[data-jb-figs]").dataset.jbFigs), Number(pol.dataset.fig));
    if (!inBook(t)) return;
    // ---- inside the book ----
    const turn = t.closest("[data-jb-turn]");
    if (turn) return goSpread(J.spread + Number(turn.dataset.jbTurn));
    const tab = t.closest("[data-jb-tab]");
    if (tab) { const k = tab.dataset.jbTab; return goSpread(k === "contents" ? 0 : k === "year" ? Math.floor(J.yearPage / 2) : Math.floor((J.kindPage[k] || 0) / 2)); }
    const yr = t.closest("[data-jb-year]");
    if (yr) {
      J.year = Number(yr.dataset.jbYear);
      const book = host()?.querySelector(".jb-book");
      if (book) { book.querySelector(".jb-l").innerHTML = pageHTML(J.pages[J.yearPage], J.yearPage); book.querySelector(".jb-r").innerHTML = pageHTML(J.pages[J.yearPage + 1], J.yearPage + 1); }
      return;
    }
    const go = t.closest("[data-jb-go]");
    if (go) return goTitle(Number(go.dataset.jbGo));
    const fs = t.closest("[data-jb-status]");
    if (fs) { J.status = fs.dataset.jbStatus; buildPages(); J.spread = 0; host().innerHTML = bookHTML(); return paintSpread(0); }
    const ss = t.closest("[data-jb-setstatus]");
    if (ss) {
      const r = rowOfPage(ss); if (!r) return;
      const st = ss.dataset.jbSetstatus;
      const body = st === "finished" && !r.finished ? { status: st, finished: today() } : { status: st };
      await api.send("PATCH", `/api/log/${r.id}`, body);
      Object.assign(r, body);
      J.byItem = new Map(J.rows.filter((x) => x.item_id).map((x) => [x.item_id, x]));
      toast(`Marked ${STATUS[st].toLowerCase()}`);
      const pg = ss.closest(".jb-pg"); pg.outerHTML = pageHTML(J.pages[Number(pg.dataset.page)], Number(pg.dataset.page));
      return;
    }
    if (t.closest("[data-jb-today]")) { const r = rowOfPage(t); if (r) saveField(r.id, "finished", today()); return; }
    const lb = t.closest("[data-jb-lib]");
    if (lb) { closeModal(); return openDrawer(Number(lb.dataset.jbLib)); }
    const dl = t.closest("[data-jb-del]");
    if (dl) {
      if (!dl.dataset.armed) { dl.dataset.armed = 1; dl.textContent = "click again to remove it and its entries"; setTimeout(() => { delete dl.dataset.armed; dl.textContent = "remove from the journal"; }, 3000); return; }
      await api.send("DELETE", `/api/log/${dl.dataset.jbDel}`); toast("Removed");
      await load(); buildPages(); return paintSpread(0);
    }
    const ed = t.closest("[data-jb-edit]");
    if (ed) {
      const r = rowOfPage(ed), entry = J.cache.get(r.id)?.journal.find((x) => x.id === Number(ed.dataset.jbEdit));
      if (!entry) return;
      ed.closest(".jb-entry").querySelector(".jb-body").innerHTML = `<textarea class="jb-edit" rows="${Math.min(16, entry.body.split("\n").length + 3)}">${esc(entry.body)}</textarea><div class="jb-wrow"><button class="jb-mini" data-jb-cancel>cancel</button><button class="jb-ink" data-jb-save="${entry.id}">save</button></div>`;
      return;
    }
    if (t.closest("[data-jb-cancel]")) { const r = rowOfPage(t); return reloadRow(r.id); }
    const sv = t.closest("[data-jb-save]");
    if (sv) { const r = rowOfPage(sv); await api.send("PATCH", `/api/journal/${sv.dataset.jbSave}`, { body: sv.closest(".jb-entry").querySelector("textarea").value }); toast("Saved"); return reloadRow(r.id); }
    const de = t.closest("[data-jb-edel]");
    if (de) {
      if (!de.dataset.armed) { de.dataset.armed = 1; de.textContent = "sure?"; setTimeout(() => { delete de.dataset.armed; de.textContent = "delete"; }, 3000); return; }
      const r = rowOfPage(de); await api.send("DELETE", `/api/journal/${de.dataset.jbEdel}`); return reloadRow(r.id);
    }
  });

  document.addEventListener("change", (e) => {
    const f = e.target.closest?.("[data-jb-field]");
    if (!f) return;
    const r = rowOfPage(f);
    if (r) saveField(r.id, f.dataset.jbField, f.value.trim());
  });
  document.addEventListener("input", (e) => {
    if (e.target.id !== "jbSearch") return;
    J.q = e.target.value;
    clearTimeout(J._qt);
    J._qt = setTimeout(() => {
      buildPages();
      const book = host()?.querySelector(".jb-book");
      if (!book) return;
      book.querySelector(".jb-r").innerHTML = pageHTML(J.pages[1], 1);
    }, 160);
  });
  document.addEventListener("submit", async (e) => {
    const w = e.target.closest?.("[data-jb-write]");
    const f = e.target.closest?.("[data-sj-item]");
    if (!w && !f) return;
    e.preventDefault();
    const ta = (w || f).querySelector("textarea");
    const body = ta.value.trim();
    if (!body) return;
    if (w) {
      const id = Number(w.dataset.jbWrite);
      await api.send("POST", `/api/log/${id}/journal`, { body });
      toast("Added to the journal");
      await reloadRow(id);
      const list = host()?.querySelector(`[data-jb-entries="${id}"]`);
      if (list) list.scrollTop = list.scrollHeight;
    } else {
      const id = Number(f.dataset.sjItem);
      await api.send("POST", `/api/items/${id}/log`, { body });
      J.loaded = false; toast("Added to the journal");
      const box = $("#stageJr"); if (box) box.dataset.expanded = "1";
      const item = S.items.find((x) => x.id === id);
      if (item) paintStage(item);
    }
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey) && e.target.closest?.("[data-jb-write],[data-sj-item]")) { e.preventDefault(); e.target.closest("form").requestSubmit(); return; }
    // the floating journal only answers keys while you're in it; otherwise they belong to what's underneath
    const inWin = !!e.target.closest?.("#jbModal") || !!document.activeElement?.closest?.("#jbModal");
    if (e.key === "Escape") { if (closePreview() || ((inWin || !J.modal) && closeModal())) { e.stopPropagation(); return; } }
    const typing = e.target.matches?.("input,textarea,select");
    if (typing || !host()) return;
    if (J.modal ? !inWin : S.area !== "journal") return;
    if (e.key === "ArrowRight" || e.key === "PageDown") { e.preventDefault(); goSpread(J.spread + 1); }
    if (e.key === "ArrowLeft" || e.key === "PageUp") { e.preventDefault(); goSpread(J.spread - 1); }
    if (e.key === "Home") goSpread(0);
  }, true);

 return { render: (lib) => render(lib), refresh: () => S.area === "journal" && render($("#library")), open, openHere, close: closeModal, openForItem, paintItemSection, paintStage,
    preview, statusOf, rowFor: (it) => J.byItem.get(it.id) || null, load, invalidate: () => { J.loaded = false; J.cache.clear(); }, STATUS };
})();
