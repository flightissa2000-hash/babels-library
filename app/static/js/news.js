/* The News: the Babel Gazette, laid out like the Discover catalogue. Two desks, each a stack of rows you scroll
   sideways: Science (by subject, from established newsrooms) and Local (things to do around town first, then your
   county, city, state and country). A story opens inside the paper; ⤓ Keep files it in the library as an article. */
const News = (() => {
  const N = { desk: "science", sci: null, loc: null, editing: false, reading: null };
  const KIND = { vote: "Vote", ordinance: "Ordinance", meeting: "Meeting", election: "Election", budget: "Budget", event: "Event" };
  const LEVEL = { events: "Out & about", county: "County", city: "City", state: "State", country: "Country" };
  const ago = (t) => { if (!t) return ""; const s = Date.now() / 1000 - t; return s < 3600 ? Math.max(1, Math.round(s / 60)) + " min ago" : s < 86400 ? Math.round(s / 3600) + " h ago" : s < 172800 ? "yesterday" : s < 86400 * 7 ? Math.round(s / 86400) + " days ago" : new Date(t * 1000).toLocaleDateString(); };
  const get = (p) => fetch(p).then((r) => r.json().then((d) => { if (!r.ok) throw new Error(d.error || r.statusText); return d; }));
  let shown = [];       // the stories on the page, for opening one

  function sheet() {
    let m = $("#nwModal");
    if (m) return m;
    m = document.createElement("div");
    m.id = "nwModal"; m.className = "nw";
    const d = new Date();
    m.innerHTML = `<div class="nw-scrim" data-nw-close></div><div class="nw-paper">
      <header class="nw-mast"><div class="nw-ear"><span>${esc(d.toLocaleDateString([], { weekday: "long", month: "long", day: "numeric", year: "numeric" }))}</span><span>Vol. ${d.getFullYear() - 2025} · No. ${Math.ceil((d - new Date(d.getFullYear(), 0, 1)) / 864e5)}</span><button data-nw-close title="Fold it up (Esc)">✕ Fold up</button></div>
        <h1>The Babel <em>Gazette</em></h1>
        <nav class="nw-desks"><button data-nw-desk="science">Science desk</button><button data-nw-desk="local">Local desk</button></nav></header>
      <div class="nw-body" id="nwBody"></div><div class="nw-reader" id="nwReader" hidden></div></div>`;
    document.body.append(m);
    m.addEventListener("click", click);
    m.addEventListener("submit", submit);
    return m;
  }
  // new events from the background watcher: a count on the News button, and a note the first time each turns up
  const SEEN = "babel.newsAlertsSeen";
  const seenAt = () => { try { return Number(localStorage.getItem(SEEN)) || 0; } catch (e) { return 0; } };
  let told = 0;
  async function watch() {
    if (typeof MINI !== "undefined" && MINI) return;
    try {
      const since = seenAt() || Date.now() / 1000 - 86400;
      const r = await get(`/api/news/alerts?since=${since}`);
      const b = $("#newsBtn");
      if (b) {
        let dot = b.querySelector(".nw-badge");
        if (!dot) { dot = document.createElement("i"); dot.className = "nw-badge"; b.append(dot); }
        dot.textContent = r.items.length > 9 ? "9+" : r.items.length || "";
        dot.hidden = !r.on || !r.items.length;
        b.dataset.t0 ||= b.title;
        b.title = r.on && r.items.length ? `${r.items.length} new event${r.items.length > 1 ? "s" : ""} in the News` : b.dataset.t0;
      }
      const fresh = r.on ? r.items.filter((x) => x.at > told) : [];
      if (told && fresh.length) toast(fresh.length === 1 ? `New event: ${fresh[0].title}` : `${fresh.length} new events in the News`);
      told = Math.max(told || r.now, ...r.items.map((x) => x.at));
    } catch (e) {}
  }
  setTimeout(watch, 4000); setInterval(watch, 10 * 60 * 1000);

  function open(desk) {
    const m = sheet();
    if (desk) N.desk = desk;
    try { localStorage.setItem(SEEN, String(Date.now() / 1000)); } catch (e) {}
    $("#newsBtn .nw-badge")?.setAttribute("hidden", "");
    if (!desk && $("#newsBtn")?.title.match(/new event/)) N.desk = "local";
    paint();
    requestAnimationFrame(() => m.classList.add("open"));
  }
  function close() {
    if (N.reading) { shut(); return true; }
    const m = $("#nwModal"); if (m && m.classList.contains("open")) { m.classList.remove("open"); return true; } return false;
  }

  const card = (s, lead = false) => {
    const i = shown.push(s) - 1;
    return `<article class="nw-card ${lead ? "lead" : ""} ${s.image ? "" : "noimg"}" data-nw-open="${i}">
      ${s.image ? `<span class="nw-pic"><img loading="lazy" alt="" src="${esc(s.image)}" onerror="this.parentElement.remove()"></span>` : ""}
      <span class="nw-txt">${s.kind ? `<span class="nw-kind k-${s.kind}">${KIND[s.kind] || s.kind}</span>` : ""}
        <h3>${esc(s.title)}</h3><span class="nw-by">${esc(s.source)}${s.date ? " · " + ago(s.date) : ""}</span>
        ${s.summary && (lead || !s.image) ? `<span class="nw-sum">${esc(s.summary)}</span>` : ""}</span></article>`;
  };
  const row = (key, label, sub, items, lead) => `<section class="nw-row r-${key}"><header><h2>${sub ? `<small>${esc(sub)}</small>` : ""}${esc(label)}</h2>
      <span class="nw-arrows"><button data-nw-scroll="-1" aria-label="Back">‹</button><button data-nw-scroll="1" aria-label="More">›</button></span></header>
      ${items.length ? `<div class="nw-strip">${items.map((s, i) => card(s, lead && i === 0 && !!s.image)).join("")}</div>` : `<p class="nw-note">Nothing here right now.</p>`}</section>`;
  const note = (t) => `<p class="nw-note">${t}</p>`;

  async function paint() {
    const m = sheet(), body = $("#nwBody");
    m.querySelectorAll("[data-nw-desk]").forEach((b) => b.classList.toggle("on", b.dataset.nwDesk === N.desk));
    shown = [];
    if (N.desk === "science") {
      if (!N.sci) { body.innerHTML = note("The presses are rolling…"); try { N.sci = await get("/api/news/science" + (N.fresh ? "?fresh=1" : "")); N.fresh = false; } catch (e) { return (body.innerHTML = note(esc(e.message))); } }
      body.innerHTML = `<div class="nw-where"><span>The <b>Science desk</b></span><button class="btn sm" data-nw-refresh>↻ Fresh edition</button></div><p class="nw-masthead-note">Research news straight from the universities, labs and agencies that did the work: MIT, NIH, NASA, ESA, Harvard, Cambridge, and the press releases gathered by Phys.org, ScienceDaily and Medical Xpress.</p>`
        + N.sci.sections.map((s, i) => row(s.key, s.label, "", s.items, i === 0)).join("");
      return;
    }
    if (!N.loc) { body.innerHTML = note("Calling the newsroom…"); try { N.loc = await get("/api/news/local" + (N.fresh ? "?fresh=1" : "")); N.fresh = false; } catch (e) { return (body.innerHTML = note(esc(e.message))); } }
    const p = N.loc.place;
    if (!p.county || N.editing) {
      body.innerHTML = `<form class="nw-place" id="nwPlace"><h2>Where's home?</h2><p>Type your county and state. The Local desk finds things to do around town, and follows the county board, the city council, the statehouse and the national news.</p>
        <label>County<input name="county" value="${esc(p.county)}" placeholder="Pinellas County" required></label>
        <label>State<input name="state" value="${esc(p.state)}" placeholder="Florida"></label>
        <label>City <small>(optional: the county seat otherwise)</small><input name="city" value="${esc(p.city)}" placeholder="${esc(p.seat || "St. Petersburg")}"></label>
        <label>Country<input name="country" value="${esc(p.country || "United States")}"></label>
        <div><button class="btn primary">Start delivery</button>${p.county ? ` <button type="button" class="btn" data-nw-cancel>Cancel</button>` : ""}</div></form>`;
      return;
    }
    const where = [p.county, p.city || p.seat, p.state].filter(Boolean).join(" · ");
    body.innerHTML = `<div class="nw-where"><span>Covering <b>${esc(where)}</b></span><button class="btn sm" data-nw-edit>Change place</button><button class="btn sm" data-nw-refresh>↻ Fresh edition</button></div>`
      + N.loc.sections.map((s) => row(s.key, s.label, LEVEL[s.key], s.items, s.key === "events")).join("");
  }

  /* reading a story inside the paper */
  async function read(s) {
    const r = $("#nwReader");
    N.reading = s;
    r.hidden = false;
    r.scrollTop = 0;
    const bar = `<div class="nw-rbar"><button data-nw-back>← Back to the paper</button><span></span><button data-nw-keep="${esc(s.link)}">⤓ Keep</button><button data-nw-orig="${esc(s.link)}">Open the original ↗</button></div>`;
    r.innerHTML = bar + `<div class="nw-rpage"><p class="nw-rkicker">${esc(s.source)}${s.date ? " · " + ago(s.date) : ""}</p><h1>${esc(s.title)}</h1>${s.summary ? `<p class="nw-rdek">${esc(s.summary)}</p>` : ""}${note("Setting the type…")}</div>`;
    try {
      const a = await get("/api/news/article?" + new URLSearchParams({ url: s.link }));
      if (N.reading !== s) return;
      r.querySelector("[data-nw-orig]").dataset.nwOrig = a.url;
      r.querySelector("[data-nw-keep]").dataset.nwKeep = a.url;
      const text = a.blocks.map((b) => b.t === "h2" || b.t === "h3" ? `<h3>${esc(b.x)}</h3>` : b.t === "blockquote" ? `<blockquote>${esc(b.x)}</blockquote>` : b.t === "li" ? `<p class="li">• ${esc(b.x)}</p>` : `<p>${esc(b.x)}</p>`).join("");
      const short = a.blocks.reduce((n, b) => n + b.x.length, 0) < 900;
      r.innerHTML = bar + `<div class="nw-rpage"><p class="nw-rkicker">${esc(a.site || s.source)}${s.date ? " · " + ago(s.date) : ""}</p>
        <h1>${esc(a.title || s.title)}</h1>${a.dek || s.summary ? `<p class="nw-rdek">${esc(a.dek || s.summary)}</p>` : ""}${a.by ? `<p class="nw-rby">By ${esc(a.by)}</p>` : ""}
        ${a.image ? `<figure><img alt="" src="${esc(a.image)}" onerror="this.parentElement.remove()"></figure>` : ""}
        <div class="nw-rtext">${text}</div>
        ${short ? `<p class="nw-rmore">${a.blocks.length ? "That's all the site lets through here." : "This site doesn't let its stories be read outside its pages."} <button data-nw-orig="${esc(a.url)}">Read it on ${esc(a.site || "the site")} ↗</button></p>` : ""}</div>`;
    } catch (e) {
      if (N.reading !== s) return;
      r.querySelector(".nw-rpage").insertAdjacentHTML("beforeend", `<p class="nw-rmore">Couldn't fetch the story (${esc(e.message)}). <button data-nw-orig="${esc(s.link)}">Read it on the site ↗</button></p>`);
      r.querySelector(".nw-rpage .nw-note")?.remove();
    }
  }
  function shut() { N.reading = null; const r = $("#nwReader"); if (r) { r.hidden = true; r.innerHTML = ""; } }

  async function click(e) {
    const t = e.target;
    if (t.closest("[data-nw-close]")) return close();
    const d = t.closest("[data-nw-desk]"); if (d) { shut(); N.desk = d.dataset.nwDesk; N.editing = false; return paint(); }
    const o = t.closest("[data-nw-open]"); if (o) return read(shown[Number(o.dataset.nwOpen)]);
    if (t.closest("[data-nw-back]")) return shut();
    const sc = t.closest("[data-nw-scroll]");
    if (sc) { const strip = sc.closest(".nw-row").querySelector(".nw-strip"); if (strip) strip.scrollBy({ left: Number(sc.dataset.nwScroll) * strip.clientWidth * 0.85, behavior: "smooth" }); return; }
    const og = t.closest("[data-nw-orig]");
    if (og) { const u = og.dataset.nwOrig; close(); close(); return window.Browser && S.desktopMode === "native" ? Browser.open(u) : window.open(u, "_blank"); }
    const k = t.closest("[data-nw-keep]");
    if (k) {
      const days = await askKeep("Keep this story?", "Save it in your library for good, or for 30 days (you'll be asked before it's removed).",
        [["For good", 0], ["For 30 days", 30]]);
      if (days == null) return;
      k.disabled = true; k.textContent = "Saving…";
      try { await api.send("POST", "/api/news/save", { url: k.dataset.nwKeep, days: days || null }); k.textContent = "✓ Kept"; toast("Saving it to your library: it'll appear under Articles in a few seconds"); setTimeout(() => window.loadItems && loadItems(), 15000); }
      catch (err) { k.disabled = false; k.textContent = "⤓ Keep"; toast(err.message, "error"); }
      return;
    }
    if (t.closest("[data-nw-edit]")) { N.editing = true; return paint(); }
    if (t.closest("[data-nw-cancel]")) { N.editing = false; return paint(); }
    // ↻ Fresh edition: this desk's stories fetched again (not the half-hour-old copies)
    if (t.closest("[data-nw-refresh]")) { if (N.desk === "science") N.sci = null; else N.loc = null; N.fresh = true; return paint(); }
  }
  async function submit(e) {
    if (e.target.id !== "nwPlace") return;
    e.preventDefault();
    const f = e.target, btn = f.querySelector(".btn.primary");
    btn.disabled = true; btn.textContent = "Finding your county…";
    try {
      await api.send("POST", "/api/news/place", { county: f.county.value, state: f.state.value, city: f.city.value, country: f.country.value });
      N.editing = false; N.loc = null; paint();
    } catch (err) { btn.disabled = false; btn.textContent = "Start delivery"; toast(err.message, "error"); }
  }
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && close()) e.stopPropagation(); }, true);
  return { open, close };
})();
