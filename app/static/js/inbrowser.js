/* The browser inside the library window. This page draws the bar (so it follows the theme); the website itself is a
   second WebView2 the app lays over #ibHole (inapp.py). The start page, history and passwords are browser.html,
   shown in an iframe in the same hole. Everything talks to the app through /api/browser/view.
   Split view (⧉, like Firefox's): a second hole on the right with its own website view ("side"); the bar works on
   whichever half you used last. */
const Browser = (() => {
  const B = { on: false, hidden: false, offer: null, split: false, act: "main",
    mode: { main: "start", side: "start" }, st: { main: {}, side: {} } };
  const send = (d) => fetch("/api/browser/view", { method: "POST", headers: { "X-Babel": "1", "Content-Type": "application/json" }, body: JSON.stringify(d) }).catch(() => {});
  const hole = (p) => $(p === "side" ? "#ibHole2" : "#ibHole");
  const frame = (p) => $(p === "side" ? "#ibStart2" : "#ibStart");

  function el() {
    let m = $("#inBrowser");
    if (m) return m;
    m = document.createElement("section");
    m.id = "inBrowser"; m.className = "ib"; m.hidden = true;
    // (data-label: the words the Side rail and TV set layouts show under or beside each control; --i: its place in the Orb's fan)
    m.innerHTML = `<div class="ib-bar">
        <button class="ib-orb" data-ib="orb" title="The browser's controls">◉</button>
        <span class="ib-brand">BABEL-VISION</span>
        <button class="ib-btn" data-ib="back" data-label="Back" style="--i:0" title="Back (Alt+←)">◀</button><button class="ib-btn" data-ib="forward" data-label="Forward" style="--i:1" title="Forward (Alt+→)">▶</button>
        <button class="ib-btn" data-ib="reload" data-label="Reload" style="--i:2" title="Reload (F5)">⟳</button><button class="ib-btn" data-ib="home" data-label="Start" style="--i:3" title="Start page">⌂</button>
        <form class="ib-addr" id="ibForm"><span class="ib-mark" id="ibMark">⌕</span><input id="ibAddr" placeholder="Search with DuckDuckGo, or type an address" autocomplete="off" spellcheck="false">
          <button type="button" class="ib-w" data-ib="wiki" title="Search Wikipedia for what's typed">W</button></form>
        <button class="ib-btn ib-star" data-ib="star" data-label="Bookmark" style="--i:9" title="Bookmark this page (it shows on the start page)">☆</button>
        <button class="ib-btn ib-splitbtn" data-ib="split" data-label="Split view" style="--i:4" title="Split view: another page side by side; press again to go back to one (keeps the half you're using) (Ctrl+Shift+S)">⧉</button>
        <button class="ib-btn ib-save" data-ib="savepage" data-label="Save it" style="--i:5" title="Save this article to your library, to read offline (its web address is kept)">⤓</button>
        <button class="ib-btn ib-key" data-ib="key" data-label="Password" style="--i:6" title="Fill in a saved password for this site">🔑</button>
        <button class="ib-btn" data-ib="history" data-label="History" style="--i:7" title="History and saved passwords">☰</button>
        <button class="ib-btn ib-close" data-ib="close" data-label="Close tab" style="--i:8" title="Close this page and go back to the start page (Esc or the library's own buttons leave the browser)">✕</button></div>
      <div class="ib-load" id="ibLoad"><i></i></div>
      <div class="ib-strip" id="ibStrip" hidden></div>
      <div class="ib-panes" id="ibPanes">
        <div class="ib-hole" id="ibHole" data-pane="main"><div class="ib-phead"><span class="ib-pt">Start page</span><button class="ib-pclose" data-ib="closepane" data-pane="main" title="Close this half">✕</button></div><iframe id="ibStart" title="Start page"></iframe></div>
        <div class="ib-divider" id="ibDiv" hidden title="Drag to resize"></div>
        <div class="ib-hole" id="ibHole2" data-pane="side" hidden><div class="ib-phead"><span class="ib-pt">Start page</span><button class="ib-pclose" data-ib="closepane" data-pane="side" title="Close this half">✕</button></div><iframe id="ibStart2" title="Start page"></iframe></div>
      </div>`;
    document.body.append(m);
    setLayout();
    $("#ibAddr", m).addEventListener("focus", () => { if (m.dataset.blayout === "orb") fan(true); });
    m.addEventListener("click", click);
    $("#ibForm", m).onsubmit = (e) => { e.preventDefault(); go($("#ibAddr").value); };
    $("#ibAddr", m).onkeydown = (e) => { if (e.key === "Escape") { e.target.value = B.mode[B.act] === "web" ? cur().url || "" : ""; e.target.blur(); } };
    const ro = new ResizeObserver(place);
    ro.observe($("#ibHole", m)); ro.observe($("#ibHole2", m));
    addEventListener("resize", place);
    m.addEventListener("pointerdown", (e) => { const h = e.target.closest(".ib-hole"); if (h) focusPane(h.dataset.pane); });
    divider($("#ibDiv", m));
    // the website view sits on top of the page: step it aside while a dialog, the reader or a panel is open
    // (a picture of the page stands in for it meanwhile, so the panel has the page behind it rather than a black hole)
    setInterval(() => {
      if (!B.on) return;
      const h = covered();
      if (h === B.hidden) return;
      B.hidden = h;
      if (h) for (const p of panes()) { if (B.mode[p] === "web") send({ cmd: "freeze", pane: p }); }
      else { unfreeze(); place(); }
    }, 120);
    return m;
  }
  // (the Orb's open fan too: while you pick a control the page under it stands still as a picture, so the fan shows whole)
  const covered = () => !!document.querySelector("dialog[open], .dv.open, #nwModal.open, .jb-snip, #jbPreview.open, .drawer.open, .jb-pv.open, .dvi.open, #inBrowser[data-blayout=orb] .ib-bar.fan") || ($("#reader") && !$("#reader").hidden);
  // the floating journal (and its bookmark) aren't covered by the website: the site view is cut around them and keeps going
  // (so is the Orb layout's orb, its fan of controls and its address bubble, which float over the website)
  // (a piece still fading in, like the tabs and the move handle while the cover swings open, isn't cut out yet: the
  // hole would show an empty patch of the app; the cover itself is, so it isn't hidden behind the website as it swings)
  const seen = (el) => { let o = 1; for (let e = el; e && e !== document.body; e = e.parentElement) o *= Number(getComputedStyle(e).opacity); return o > 0.1; };
  const cuts = () => [...document.querySelectorAll("#jbModal.open .jb-book, #jbModal.open .jb-tab, #jbModal.open .jb-tuck, #jbModal.open .jb-grip, #jbModal.open .jb-grab, #jbModal.open .jb-polbig, #jbModal.open .jb-lid, #jbPull:not(.out)"
      + ", #inBrowser[data-blayout=orb] .ib-orb")]
    .filter((el) => getComputedStyle(el).visibility !== "hidden" && getComputedStyle(el).display !== "none" && seen(el))
    .map((el) => { const r = el.getBoundingClientRect(); return { x: r.left, y: r.top, w: r.width, h: r.height }; });
  let movedRaf = 0;
  addEventListener("journal-moved", () => { if (B.on && !movedRaf) movedRaf = requestAnimationFrame(() => { movedRaf = 0; place(); }); });
  const panes = () => (B.split ? ["main", "side"] : ["main"]);
  const PHEAD = 28;
  const paneTitle = (p) => { const t = hole(p)?.querySelector(".ib-pt"); if (t) t.textContent = B.mode[p] === "web" ? B.st[p].title || B.st[p].url || "…" : "Start page"; };
  const cur = () => B.st[B.act] || {};

  /* the line between the halves: drag it to give one more room */
  function divider(d) {
    let raf = 0;
    d.addEventListener("pointerdown", (e) => {
      e.preventDefault();
      d.setPointerCapture(e.pointerId);
      d.classList.add("drag");
      const box = $("#ibPanes").getBoundingClientRect();
      const move = (ev) => {
        const f = Math.min(0.8, Math.max(0.2, (ev.clientX - box.left) / box.width));
        $("#ibHole").style.flex = `0 0 ${(f * 100).toFixed(2)}%`;
        if (!raf) raf = requestAnimationFrame(() => { raf = 0; place(); });
      };
      const up = () => { d.classList.remove("drag"); d.removeEventListener("pointermove", move); d.removeEventListener("pointerup", up); try { localStorage.setItem("inkwell-split", $("#ibHole").style.flex); } catch (err) {} };
      d.addEventListener("pointermove", move);
      d.addEventListener("pointerup", up);
    });
  }

  function place() {
    const m = $("#inBrowser");
    if (!m || !B.on) return;
    m.style.top = ($(".topbar")?.getBoundingClientRect().bottom || 0) + "px";
    const cut = cuts();
    for (const p of panes()) {
      const r = hole(p).getBoundingClientRect(), pad = B.split ? PHEAD : 0;     // each half's header: its title, ✕, and (coloured) which half the bar works on
      send({ cmd: "place", pane: p, rect: { x: r.left, y: r.top + pad, w: r.width, h: r.height - pad }, cut, dpr: devicePixelRatio, show: B.mode[p] === "web" && !B.hidden });
    }
  }

  function show() {
    el().hidden = false;
    B.on = true;
    document.body.classList.add("ib-on");
    $("#browserBtn")?.classList.add("on");
    requestAnimationFrame(place);
  }
  function open(url) {
    show();
    if (url) go(url); else if (B.mode.main !== "web" || !B.st.main.url) home("start", "main");
  }
  function close() {
    if (!B.on) return;
    B.on = false;
    send({ cmd: "hide" });
    if (B.split) send({ cmd: "hide", pane: "side" });
    $("#inBrowser").hidden = true;
    document.body.classList.remove("ib-on");
    $("#browserBtn")?.classList.remove("on");
  }
  function home(tab = "start", p = B.act) {
    show();
    B.mode[p] = "start";
    send({ cmd: "hide", pane: p });
    frame(p).src = `/browser.html?embed=1${p === "side" ? "&pane=side" : ""}#${tab}`;
    paneTitle(p);
    focusPane(p);
    $("#ibAddr").value = "";
    paintBar();
    setTimeout(() => $("#ibAddr").focus(), 60);
  }
  function go(text, wiki = false, p = B.act) {
    text = String(text || "").trim();
    if (!text) return;
    show();
    B.mode[p] = "web";
    frame(p).removeAttribute("src");
    $("#ibAddr").blur();
    focusPane(p);
    send({ cmd: "go", text, wiki, pane: p });
    if ($("#inBrowser").dataset.blayout === "orb") fan(false);     // (the Orb folds its controls away once you're off)
    place();
  }

  function focusPane(p) {
    if (p !== "side" || !B.split) p = "main";
    B.act = p;
    hole("main").classList.toggle("act", p === "main");
    hole("side").classList.toggle("act", p === "side");
    paintBar();
  }
  function split(on = !B.split) {
    el();
    B.split = on;
    $("#ibPanes").classList.toggle("split", on);
    $("#ibDiv").hidden = $("#ibHole2").hidden = !on;
    $("#inBrowser .ib-splitbtn").classList.toggle("on", on);
    if (on) {
      let f = ""; try { f = localStorage.getItem("inkwell-split") || ""; } catch (e) {}
      $("#ibHole").style.flex = f || "0 0 50%";
      home("start", "side");          // the right half starts on the start page: pick or search for its page there
    } else {
      // the half you were using stays: if that was the right one, its page moves to the whole window
      const keep = B.act === "side" && B.mode.side === "web" ? B.st.side.url : "";
      $("#ibHole").style.flex = "";
      send({ cmd: "hide", pane: "side" });
      frame("side").removeAttribute("src");
      B.mode.side = "start"; B.st.side = {};
      hole("side").style.backgroundImage = "";
      focusPane("main");
      if (keep) go(keep, false, "main");
    }
    requestAnimationFrame(place);
  }

  function paintBar() {
    if (!$("#ibAddr")) return;
    const s = cur(), web = B.mode[B.act] === "web";
    const a = $("#ibAddr");
    if (document.activeElement !== a) a.value = web ? s.url || "" : "";
    $$('#inBrowser [data-ib="back"]').forEach((b) => (b.disabled = web ? !s.back : !s.url));
    $$('#inBrowser [data-ib="forward"]').forEach((b) => (b.disabled = !web || !s.forward));
    const star = $("#inBrowser .ib-star");
    if (star) { star.textContent = web && s.starred ? "★" : "☆"; star.classList.toggle("lit", web && !!s.starred); }
    const key = $("#inBrowser .ib-key");
    if (key) key.classList.toggle("lit", web && !!(s.logins || []).length);
    $("#ibMark").textContent = web && /^https:/.test(s.url || "") ? "🔒" : "⌕";
    $("#ibLoad").classList.toggle("on", web && !!s.loading);
  }
  function strip(html) {
    const st = $("#ibStrip");
    st.innerHTML = html || "";
    st.hidden = !html;
    requestAnimationFrame(place);
  }

  async function click(e) {
    const b = e.target.closest("[data-ib]");
    if (!b) return;
    const k = b.dataset.ib, p = B.act, web = B.mode[p] === "web";
    if (k === "back") return web ? send({ cmd: "back", pane: p }) : cur().url && (B.mode[p] = "web", frame(p).removeAttribute("src"), place(), paintBar());
    if (k === "forward") return send({ cmd: "forward", pane: p });
    if (k === "reload") return web ? send({ cmd: "reload", pane: p }) : frame(p).contentWindow.location.reload();
    if (k === "home") return home();
    if (k === "history") return home("history");
    // ✕ closes the page you're on: in split view that half (the other stays), otherwise back to the start page
    if (k === "close") return B.split ? (focusPane(p === "main" ? "side" : "main"), split(false)) : home("start", p);
    if (k === "orb") return fan();
    if (k === "star") {         // bookmark the page you're on (or take its bookmark away)
      if (!web || !cur().url) return toast("Open a page first");
      const on = !cur().starred;
      await fetch("/api/browser/bookmarks", { method: on ? "POST" : "DELETE", headers: { "X-Babel": "1", "Content-Type": "application/json" }, body: JSON.stringify({ url: cur().url, title: cur().title }) });
      cur().starred = on; paintBar();
      return toast(on ? "Bookmarked: it's on your start page" : "Bookmark removed");
    }
    if (k === "split") return split();
    if (k === "closepane") { focusPane(b.dataset.pane === "main" ? "side" : "main"); return split(false); }   // the other half stays
    if (k === "wiki") {
      const v = $("#ibAddr").value.trim();
      return v && v !== cur().url ? go(v, true) : go("https://en.wikipedia.org/");
    }
    if (k === "key") {
      const l = cur().logins || [];
      if (!web || !l.length) return strip(`<span>No saved password for ${esc(cur().site || "this page")}.</span><button class="btn sm" data-ib="pwlist">Open saved passwords</button><button class="btn sm" data-ib="nostrip">✕</button>`);
      if (l.length === 1) return send({ cmd: "fill", id: l[0].id, pane: p });
      return strip(`<span>Sign in as</span>${l.map((x) => `<button class="btn sm" data-ib="fill" data-id="${x.id}">${esc(x.username || "(no username)")}</button>`).join("")}<button class="btn sm" data-ib="nostrip">✕</button>`);
    }
    if (k === "savepage") {
      if (!web || !cur().url) return toast("Open an article first");
      return strip(`<span>Keep <b>${esc(cur().title || cur().url)}</b></span><button class="btn sm" data-ib="savekeep" data-days="">For good</button><button class="btn sm" data-ib="savekeep" data-days="30">For 30 days</button><button class="btn sm" data-ib="nostrip">✕</button>`);
    }
    if (k === "savekeep") {
      const sb = $("#inBrowser [data-ib=savepage]"), days = Number(b.dataset.days) || null;
      if (sb) { sb.disabled = true; sb.classList.add("busy"); }
      strip(`<span>Saving <b>${esc(cur().title || cur().url)}</b> to your library${days ? " for 30 days (you'll be asked before it goes)" : ""}…</span>`);
      return send({ cmd: "savepage", pane: p, days });
    }
    if (k === "open") { close(); return openDrawer(Number(b.dataset.id)); }
    if (k === "fill") { strip(""); return send({ cmd: "fill", id: b.dataset.id, pane: p }); }
    if (k === "pwlist") { strip(""); return home("passwords"); }
    if (k === "nostrip") return strip("");
    if (k === "save") { send({ cmd: "save", token: B.offer, pane: B.offerPane }); B.offer = null; strip(""); return toast("Password saved"); }
  }

  /* the browser's layout (🧭 Layout on its start page): Standard, Bottom bar, Side rail, Orb or TV set */
  function setLayout(s) {
    if (s == null) { try { s = localStorage.getItem("inkwell-blayout") || "standard"; } catch (e) { s = "standard"; } }
    const m = $("#inBrowser");
    if (!m) return;
    if (["bottom", "rail", "orb", "tv"].includes(s)) m.dataset.blayout = s; else delete m.dataset.blayout;
    fan(false);
    requestAnimationFrame(place);
  }
  addEventListener("storage", (e) => { if (e.key === "inkwell-blayout") setLayout(); });
  /* the Orb: click it to fan the controls out around it (and the address bubble beside it); click it again to fold them */
  function fan(open) {
    const bar = $("#inBrowser .ib-bar");
    if (!bar) return;
    bar.classList.toggle("fan", open == null ? !bar.classList.contains("fan") : open);
    requestAnimationFrame(place);
  }

  // from the app (inapp.py); the split view's right half adds "side"
  function state(s, p = "main") { B.st[p] = s; paneTitle(p); if (p === B.act) paintBar(); }
  function focused(_, p = "main") { focusPane(p); }
  function frozen(data, p = "main") { const h = hole(p); if (h && B.hidden) h.style.backgroundImage = data ? `url("${data}")` : ""; }
  function unfreeze() { for (const p of ["main", "side"]) { const h = hole(p); if (h) h.style.backgroundImage = ""; } }
  function saved(r) {
    const b = $("#inBrowser .ib-save");
    if (b) { b.disabled = false; b.classList.remove("busy"); }
    if (!r.ok) return strip(`<span>Couldn't save this page: ${esc(r.error || "")}</span><button class="btn sm" data-ib="nostrip">✕</button>`);
    strip(`<span>${r.new ? "Saved" : "Already in your library:"} <b>${esc(r.title)}</b>${r.new ? " · filed with your articles, readable offline" : ""}</span>
      <button class="btn sm primary" data-ib="open" data-id="${r.id}">Show it</button><button class="btn sm" data-ib="nostrip">✕</button>`);
    if (window.loadItems) loadItems();
  }
  function offerSave(o, p = "main") {
    B.offer = o.token; B.offerPane = p;
    strip(`<span>${o.update ? "Update the saved password" : "Save the password"} for <b>${esc(o.username || "this login")}</b> on ${esc(o.site)}?</span>
      <button class="btn sm primary" data-ib="save">${o.update ? "Update" : "Save"}</button><button class="btn sm" data-ib="nostrip">Not now</button>
      <small>Kept encrypted for your Windows account on this computer.</small>`);
  }

  document.addEventListener("keydown", (e) => {
    if (!B.on || covered()) return;
    if (e.key === "Escape" && document.activeElement !== $("#ibAddr")) close();
    if (e.altKey && e.key === "ArrowLeft") send({ cmd: "back", pane: B.act });
    if (e.altKey && e.key === "ArrowRight") send({ cmd: "forward", pane: B.act });
    if (e.ctrlKey && e.shiftKey && e.key.toLowerCase() === "s") { e.preventDefault(); split(); }
    if ((e.ctrlKey && e.key.toLowerCase() === "l") || e.key === "F6") { e.preventDefault(); $("#ibAddr").focus(); $("#ibAddr").select(); }
  });
  // the parts of the top bar that lead somewhere in the library take you back to it; Settings, News, Journal and the
  // other panels open over the browser, which waits behind them
  document.addEventListener("click", (e) => { if (B.on && e.target.closest("#brand, #areaSeg, #kindSeg, #viewSeg, #search, #groupBy")) close(); }, true);

  return { open, close, go, home, state, focused, focusPane, split, setLayout, offerSave, saved, frozen, toggle: () => (B.on ? close() : open()), get on() { return B.on; }, get splitOn() { return B.split; } };
})();
window.Browser = Browser;      // the app (inapp.py) and the start page in the iframe reach it as window.Browser
