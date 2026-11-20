/* The corkboard: a cork wall to think on. Post-it notes, clippings from web pages and books, links, pictures and
   things from the library, tied together with red string. Drag the wall to move around, the wheel to zoom. The board
   is kept as you go (corkboard.py, per profile); "Save board" keeps a named copy, "Boards" opens one again, "Clear"
   empties the wall. Things arrive from the browser's 📌, the reader's selection 📌, and an item's 📌 Corkboard. */
const Cork = (() => {
  const C = { on: false, b: null, loadedAt: 0, saveT: 0, tieFrom: null, tieMode: false, dirtySinceSave: false, drag: null };
  const W = { note: 210, snippet: 260, link: 240, media: 170, image: 230 };
  const host = (u) => { try { return new URL(u).hostname.replace(/^www\./, ""); } catch (e) { return ""; } };
  // a link without a title: its last part, readable ("…/wiki/Magnetic_skyrmion" → "Magnetic skyrmion")
  const slugTitle = (u) => { try { const p = decodeURIComponent(new URL(u).pathname).split("/").filter(Boolean).pop() || ""; return p.replace(/\.\w{2,5}$/, "").replace(/[-_+]+/g, " ").trim() || host(u); } catch (e) { return u || ""; } };
  const card = (id) => C.b.items.find((c) => c.id === id);
  const root = () => $("#corkboard") || build();

  function build() {
    const s = document.createElement("section");
    s.id = "corkboard"; s.className = "ck"; s.hidden = true;
    s.innerHTML = `<div class="ck-bar">
        <span class="ck-logo">📌</span><input class="ck-name" id="ckName" placeholder="Untitled board" aria-label="Board name" maxlength="120">
        <div class="ck-add">
          <button class="btn sm" data-ck="note" title="A post-it note">📝 Note</button>
          <button class="btn sm" data-ck="library" title="Pin something from your library">📚 From library</button>
          <button class="btn sm" data-ck="paste" title="Pin what's on the clipboard (text, a link or a picture)">📋 Paste</button>
          <button class="btn sm ck-tie" data-ck="string" aria-pressed="false" title="Tie red string: drag from a pin to another thing, or turn this on and click one, then the other">🧵 String</button>
        </div>
        <span class="spacer"></span>
        <div class="ck-zoom"><button class="btn sm" data-ck="zout" title="Zoom out">−</button><button class="btn sm" data-ck="fit" title="Show everything">Fit</button><button class="btn sm" data-ck="zin" title="Zoom in">+</button></div>
        <button class="btn sm" data-ck="save" title="Keep this board under a name">💾 Save board</button>
        <button class="btn sm" data-ck="boards" title="Your saved boards">🗂 Boards</button>
        <button class="btn sm" data-ck="clear" title="Take everything off the board">Clear</button>
        <button class="icon-btn" data-ck="close" title="Close the corkboard (Esc)">✕</button>
      </div>
      <div class="ck-stage" id="ckStage">
        <div class="ck-world" id="ckWorld"><svg class="ck-strings" id="ckStrings" width="1" height="1"></svg><div id="ckCards"></div></div>
        <div class="ck-empty" id="ckEmpty"><b>An empty corkboard</b><span>Add a note, pin something from your library, paste a picture or a link, or use 📌 in the browser and the reader. Tie things together: drag from one thing's pin to another (or use 🧵 String), and pluck the string to see it swing.</span></div>
        <div class="ck-hint" id="ckHint" hidden></div>
      </div>
      <div class="ck-pop" id="ckPop" hidden></div>`;
    document.body.append(s);
    s.addEventListener("click", onClick);
    s.addEventListener("input", onInput);
    s.addEventListener("dblclick", onDbl);
    $("#ckStage").addEventListener("pointerdown", onDown);
    $("#ckStage").addEventListener("wheel", onWheel, { passive: false });
    // (a drop here is for the board, not "add this file to the library")
    for (const t of ["dragenter", "dragover", "dragleave"]) $("#ckStage").addEventListener(t, (e) => { e.preventDefault(); e.stopPropagation(); });
    $("#ckStage").addEventListener("drop", onDrop);
    $("#ckName").addEventListener("change", () => { C.b.name = $("#ckName").value.trim(); changed(); });
    return s;
  }

  /* ---------------- open / close / save */
  async function open() {
    root();
    if (window.Browser && Browser.on) Browser.close();
    try { C.b = await api.get("/api/corkboard"); } catch (e) { return toast(e.message, "error"); }
    C.loadedAt = Date.now() / 1000;
    C.on = true;
    root().hidden = false;
    document.body.classList.add("cork-on");
    $("#corkBtn")?.classList.add("on");
    render();
  }
  function close() {
    if (!C.on) return;
    flush();
    C.on = false; setTie(false);
    root().hidden = true; $("#ckPop").hidden = true;
    document.body.classList.remove("cork-on");
    $("#corkBtn")?.classList.remove("on");
  }
  function changed(redraw = false) {
    C.dirtySinceSave = true;
    if (redraw) render();
    clearTimeout(C.saveT);
    C.saveT = setTimeout(flush, 700);
  }
  function flush() {
    clearTimeout(C.saveT); C.saveT = 0;
    if (!C.b) return Promise.resolve();
    const body = { board: C.b, loaded_at: C.loadedAt };
    return api.send("PUT", "/api/corkboard", body).catch((e) => toast("The corkboard couldn't be saved: " + e.message, "error"));
  }
  async function reload() {
    await flush();
    C.b = await api.get("/api/corkboard"); C.loadedAt = Date.now() / 1000;
    render();
  }

  /* ---------------- drawing */
  function inner(c) {
    const t = esc(c.title || "");
    if (c.type === "note") return `<div class="ck-text" contenteditable="true" spellcheck="true" data-ph="Write something…">${esc(c.text || "")}</div>`;
    if (c.type === "snippet") return `${c.image ? `<img class="ck-snipimg" src="${esc(c.image)}" alt="" loading="lazy">` : ""}<blockquote class="ck-quote">${esc(c.text || "")}</blockquote>
      ${t || c.url ? `<button class="ck-src" data-ck="src" title="Double-click to open">— ${t || esc(host(c.url))}${c.url && t ? ` <small>${esc(host(c.url))}</small>` : ""}</button>` : ""}`;
    if (c.type === "link") return `${c.image ? `<img class="ck-linkimg" src="${esc(c.image)}" alt="" loading="lazy">` : `<div class="ck-linkimg ck-globe">🌐</div>`}
      <button class="ck-src ck-linkt" data-ck="src" title="Double-click to open"><b>${t || esc(slugTitle(c.url))}</b><small>${esc(host(c.url))}</small></button>`;
    if (c.type === "media") {
      const it = S.items.find((i) => i.id === c.item_id);
      return `<div class="ck-cov">${it ? coverHTML(it) : `<div class="cover"><div class="gen-cover"><div class="t">${t}</div></div></div>`}</div>
        <b class="ck-mt">${esc(it ? it.title : c.title || "")}</b><small>${esc(it ? authorLine(it) : c.author || "")}</small>`;
    }
    if (c.type === "image") return `<img class="ck-photo" src="${esc(c.url || "")}" alt="" loading="lazy" draggable="false"><div class="ck-cap" contenteditable="true" data-ph="Add a caption">${esc(c.text || "")}</div>`;
    return "";
  }
  function cardHTML(c) {
    const colors = c.type === "note" ? `<span class="ck-colors">${["yellow", "pink", "blue", "green", "orange", "purple"].map((k) => `<button class="ck-dot n-${k}" data-ck="color" data-color="${k}" title="${k}"></button>`).join("")}</span>` : "";
    return `<div class="ck-card t-${c.type} ${c.type === "note" ? "n-" + (c.color || "yellow") : ""} ${C.tieFrom === c.id ? "tying" : ""} ${C.sel && C.sel.kind === "card" && C.sel.id === c.id ? "sel" : ""}" data-id="${c.id}"
        style="left:${c.x}px;top:${c.y}px;width:${c.w || W[c.type]}px;--r:${c.r || 0}deg">
      <span class="ck-pin"></span>${inner(c)}
      <div class="ck-tools">${colors}<button data-ck="tie" title="Tie a string from here">🧵</button><button data-ck="del" title="Take it off the board">✕</button></div></div>`;
  }
  function render() {
    if (!C.b) return;
    const v = C.b.view;
    $("#ckWorld").style.transform = `translate(${v.x}px, ${v.y}px) scale(${v.z})`;
    $("#ckCards").innerHTML = C.b.items.map(cardHTML).join("");
    $("#ckEmpty").hidden = C.b.items.length > 0;
    if (document.activeElement !== $("#ckName")) $("#ckName").value = C.b.name || "";
    drawStrings();
  }
  // a string runs from pin to pin, sagging a little under its own weight
  function pinOf(id) {
    const el = $(`#ckCards [data-id="${id}"]`), c = card(id);
    if (!el || !c) return null;
    return { x: c.x + el.offsetWidth / 2, y: c.y + 10 };
  }
  /* The string is real string: each one is a rope of little beads (Verlet), hanging slack between its two pins
     under gravity. Moving a card swings it, plucking it makes it wobble, and it settles by itself. The loop only
     runs while something is still moving. */
  const ROPE = { n: 16, g: 0.5, damp: 0.985, iters: 14, slack: 1.07 };
  const ropes = new Map();          // string id -> beads [{x, y, px, py}]
  let loopId = 0, still = 0;
  function rope(id, a, b) {
    let p = ropes.get(id);
    if (!p) {
      p = [];
      for (let i = 0; i <= ROPE.n; i++) { const t = i / ROPE.n, x = a.x + (b.x - a.x) * t, y = a.y + (b.y - a.y) * t; p.push({ x, y, px: x, py: y - 2 }); }
      ropes.set(id, p);
    }
    return p;
  }
  function stepRope(p, a, b, grab) {
    const last = p.length - 1;
    let moving = 0;
    for (let i = 1; i < last; i++) {
      const q = p[i], vx = (q.x - q.px) * ROPE.damp, vy = (q.y - q.py) * ROPE.damp;
      q.px = q.x; q.py = q.y; q.x += vx; q.y += vy + ROPE.g;
      moving += Math.abs(vx) + Math.abs(vy);
    }
    const seg = (Math.hypot(b.x - a.x, b.y - a.y) * ROPE.slack + 24) / last;      // (always a little slack, so it hangs)
    for (let k = 0; k < ROPE.iters; k++) {
      p[0].x = a.x; p[0].y = a.y; p[last].x = b.x; p[last].y = b.y;
      if (grab) { p[grab.i].x = grab.x; p[grab.i].y = grab.y; }
      for (let i = 0; i < last; i++) {
        const u = p[i], v = p[i + 1], dx = v.x - u.x, dy = v.y - u.y, d = Math.hypot(dx, dy) || 0.001, f = (d - seg) / d / 2;
        const fu = i === 0 || (grab && grab.i === i) ? 0 : f, fv = i + 1 === last || (grab && grab.i === i + 1) ? 0 : f;
        const w = fu && fv ? 1 : 2;               // (a fixed end: the free one takes the whole correction)
        u.x += dx * fu * w; u.y += dy * fu * w; v.x -= dx * fv * w; v.y -= dy * fv * w;
      }
    }
    return moving;
  }
  function pathOf(p) {
    let d = `M${p[0].x.toFixed(1)},${p[0].y.toFixed(1)}`;
    for (let i = 1; i < p.length - 1; i++) { const mx = (p[i].x + p[i + 1].x) / 2, my = (p[i].y + p[i + 1].y) / 2; d += ` Q${p[i].x.toFixed(1)},${p[i].y.toFixed(1)} ${mx.toFixed(1)},${my.toFixed(1)}`; }
    const z = p[p.length - 1];
    return d + ` L${z.x.toFixed(1)},${z.y.toFixed(1)}`;
  }
  function frame() {
    loopId = 0;
    if (!C.b || !C.on) return;
    const out = [], live = new Set();
    let moving = 0;
    const list = [...C.b.strings];
    const aim = C.drag && C.drag.kind === "tie" ? { from: C.drag.from, x: C.drag.wx, y: C.drag.wy } : C.tieFrom && C.aim ? { from: C.tieFrom, x: C.aim.x, y: C.aim.y } : null;
    if (aim) list.push({ id: "_tie", a: aim.from, b: null });
    for (const s of list) {
      const a = pinOf(s.a), b = s.b ? pinOf(s.b) : { x: aim.x, y: aim.y };
      if (!a || !b) continue;
      live.add(s.id);
      const p = rope(s.id, a, b);
      const grab = C.drag && C.drag.kind === "pluck" && C.drag.id === s.id ? C.drag.grab : null;
      moving += stepRope(p, a, b, grab);
      const d = pathOf(p);
      out.push(`<path class="ck-shadow" d="${d}" transform="translate(3,5)"/><path class="ck-yarn${s.id === "_tie" ? " tying" : ""}${C.sel && C.sel.kind === "string" && C.sel.id === s.id ? " sel" : ""}" d="${d}"/>${s.id === "_tie" ? "" : `<path class="ck-hit" d="${d}" data-string="${s.id}"/>`}`);
    }
    for (const id of ropes.keys()) if (!live.has(id)) ropes.delete(id);
    $("#ckStrings").innerHTML = out.join("");
    still = moving < 0.4 * Math.max(1, list.length) && !C.drag && !aim ? still + 1 : 0;
    if (still < 40) loopId = requestAnimationFrame(frame);       // (settled: stop until something moves it)
  }
  function drawStrings() { still = 0; if (!loopId) loopId = requestAnimationFrame(frame); }
  function nearestBead(id, x, y) {
    const p = ropes.get(id);
    if (!p) return 0;
    let best = 1, bd = Infinity;
    for (let i = 1; i < p.length - 1; i++) { const d = Math.hypot(p[i].x - x, p[i].y - y); if (d < bd) { bd = d; best = i; } }
    return best;
  }

  /* ---------------- adding things */
  async function pin(c) {
    try {
      if (C.on) { const s = freeSpot(W[c.type] || 220, c.type === "media" ? 300 : 210); c = { ...c, x: Math.round(s.x), y: Math.round(s.y) }; }   // (on screen: a free spot you can see)
      const made = await api.send("POST", "/api/corkboard/add", c);
      if (C.on) { await flush(); C.b.items.push(made); render(); flash(made.id); }
      return made;
    } catch (e) { toast(e.message, "error"); }
  }
  function flash(id) { const el = $(`#ckCards [data-id="${id}"]`); if (el) { el.classList.add("new"); setTimeout(() => el.classList.remove("new"), 1600); } }
  function centre() { const r = $("#ckStage").getBoundingClientRect(), v = C.b.view; return { x: (r.width / 2 - v.x) / v.z, y: (r.height / 2 - v.y) / v.z }; }
  // somewhere near the middle that nothing else covers (spiralling out from the middle)
  function freeSpot(w, h) {
    const p = centre(), boxes = $$("#ckCards .ck-card").map((el) => { const c = card(el.dataset.id); return c && { x: c.x, y: c.y, w: el.offsetWidth, h: el.offsetHeight }; }).filter(Boolean);
    for (let i = 0; i < 160; i++) {
      const a = i * 2.39996, rad = 18 * Math.sqrt(i) * 6;
      const x = p.x + Math.cos(a) * rad - w / 2, y = p.y + Math.sin(a) * rad * 0.75 - h / 2;
      if (boxes.every((b) => x + w + 24 < b.x || b.x + b.w + 24 < x || y + h + 24 < b.y || b.y + b.h + 24 < y)) return { x, y };
    }
    return { x: p.x - w / 2 + Math.random() * 80 - 40, y: p.y - h / 2 + Math.random() * 80 - 40 };
  }
  function local(c, at) {
    const n = { id: Math.random().toString(16).slice(2, 14), r: Math.round((Math.random() * 8 - 4) * 10) / 10, added_at: Date.now() / 1000, ...c };
    const w = W[n.type] || 200, h = n.type === "media" ? 300 : 190;
    const p = at ? { x: at.x - w / 2, y: at.y - 40 } : freeSpot(w, h);
    n.x = Math.round(p.x); n.y = Math.round(p.y);
    C.b.items.push(n); changed(true); flash(n.id);
    return n;
  }
  async function upload(blob) {
    const r = await fetch("/api/corkboard/media", { method: "POST", body: blob });
    const j = await r.json();
    if (!r.ok) throw new Error(j.error || r.statusText);
    return j.url;
  }
  async function fromText(text, at) {
    const t = (text || "").trim();
    if (!t) return;
    if (/^https?:\/\/\S+$/.test(t)) return local({ type: /\.(png|jpe?g|gif|webp)(\?|$)/i.test(t) ? "image" : "link", url: t, title: "" }, at);
    local({ type: "note", text: t, color: "yellow" }, at);
  }
  async function onDrop(e) {
    e.preventDefault(); e.stopPropagation();
    const at = toWorld(e.clientX, e.clientY);
    const files = [...(e.dataTransfer.files || [])].filter((f) => f.type.startsWith("image/"));
    for (const f of files) { try { local({ type: "image", url: await upload(f) }, at); } catch (err) { toast(err.message, "error"); } }
    if (files.length) return;
    const id = e.dataTransfer.getData("text/babel-item");
    if (id) return pinMedia(Number(id), at);
    fromText(e.dataTransfer.getData("text/uri-list") || e.dataTransfer.getData("text/plain"), at);
  }
  document.addEventListener("paste", async (e) => {
    if (!C.on || e.target.closest?.("[contenteditable], input, textarea")) return;
    const img = [...(e.clipboardData?.items || [])].find((i) => i.type.startsWith("image/"));
    if (img) { e.preventDefault(); try { local({ type: "image", url: await upload(img.getAsFile()) }); } catch (err) { toast(err.message, "error"); } return; }
    const t = e.clipboardData?.getData("text/plain");
    if (t) { e.preventDefault(); fromText(t); }
  });
  async function pasteButton() {
    try {
      if (navigator.clipboard.read) {
        for (const item of await navigator.clipboard.read()) {
          const type = item.types.find((t) => t.startsWith("image/"));
          if (type) return local({ type: "image", url: await upload(await item.getType(type)) });
        }
      }
      const t = await navigator.clipboard.readText();
      if (t) return fromText(t);
      toast("The clipboard is empty");
    } catch (e) { toast("Press Ctrl+V on the board to paste", "error"); }
  }
  function pinMedia(id, at) {
    const it = S.items.find((i) => i.id === id);
    if (!it) return;
    local({ type: "media", item_id: id, title: it.title || "", kind: it.kind || "", author: (it.authors || []).join(", ") }, at);
  }

  /* ---------------- moving around: drag the wall, wheel to zoom */
  function toWorld(cx, cy) { const r = $("#ckStage").getBoundingClientRect(), v = C.b.view; return { x: (cx - r.left - v.x) / v.z, y: (cy - r.top - v.y) / v.z }; }
  function zoomAt(z, cx, cy) {
    const v = C.b.view, r = $("#ckStage").getBoundingClientRect();
    z = Math.min(3, Math.max(0.15, z));
    const px = cx - r.left, py = cy - r.top;
    v.x = px - (px - v.x) * (z / v.z); v.y = py - (py - v.y) * (z / v.z); v.z = z;
    $("#ckWorld").style.transform = `translate(${v.x}px, ${v.y}px) scale(${v.z})`;
    changed();
  }
  function onWheel(e) {
    if (e.target.closest(".ck-text, .ck-quote, .ck-cap") && !e.ctrlKey) return;     // (long text scrolls)
    e.preventDefault();
    zoomAt(C.b.view.z * Math.exp(-e.deltaY * 0.0015), e.clientX, e.clientY);
  }
  function fit() {
    if (!C.b.items.length) { C.b.view = { x: 0, y: 0, z: 1 }; render(); return changed(); }
    const els = $$("#ckCards .ck-card");
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (const el of els) { const c = card(el.dataset.id); x0 = Math.min(x0, c.x); y0 = Math.min(y0, c.y); x1 = Math.max(x1, c.x + el.offsetWidth); y1 = Math.max(y1, c.y + el.offsetHeight); }
    const r = $("#ckStage").getBoundingClientRect();
    const z = Math.min(1.4, Math.max(0.15, Math.min((r.width - 80) / (x1 - x0), (r.height - 80) / (y1 - y0))));
    C.b.view = { z, x: (r.width - (x1 - x0) * z) / 2 - x0 * z, y: (r.height - (y1 - y0) * z) / 2 - y0 * z };
    render(); changed();
  }
  function onDown(e) {
    if (e.button !== 0) return;
    // a pin wins over the string tied to it (the string's end lies on top of the pin)
    const pinEl = document.elementsFromPoint(e.clientX, e.clientY).find((x) => x.classList && x.classList.contains("ck-pin"));
    const tgt = pinEl || e.target;
    const el = tgt.closest(".ck-card");
    const str = pinEl ? null : e.target.closest("[data-string]");
    if (C.tieFrom && el && !e.target.closest("[data-ck], [contenteditable]")) {     // a pin is waiting: this one is its partner
      e.preventDefault(); C.tiedAt = Date.now(); return tieTo(el.dataset.id);
    }
    if (str) {                                                      // pluck the string (a click without pulling: select it)
      const w = toWorld(e.clientX, e.clientY);
      C.drag = { kind: "pluck", id: str.dataset.string, sx: e.clientX, sy: e.clientY, cx: e.clientX, cy: e.clientY, moved: false, grab: { i: nearestBead(str.dataset.string, w.x, w.y), x: w.x, y: w.y } };
      $("#ckStage").setPointerCapture(e.pointerId); e.preventDefault(); drawStrings();
      return;
    }
    if (el && pinEl) {                       // drag from a card's pin to another card: tie a string
      const w = toWorld(e.clientX, e.clientY);
      C.drag = { kind: "tie", from: el.dataset.id, sx: e.clientX, sy: e.clientY, wx: w.x, wy: w.y, moved: false };
      el.classList.add("tying"); hint("Let go on the thing to tie it to.");
      $("#ckStage").setPointerCapture(e.pointerId); e.preventDefault(); drawStrings();
      return;
    }
    if (el && !e.target.closest(".ck-tools")) select({ kind: "card", id: el.dataset.id });     // (pressing a card selects it: Delete removes it)
    else if (!el) select(null);
    if (e.target.closest("[contenteditable], .ck-tools button, a, input")) return;      // (the title of a link or quote is part of the card: drag it, double-click to open)
    if (el) {
      if (C.tieMode || C.tieFrom) return;                     // (a click ties the string)
      const c = card(el.dataset.id);
      C.drag = { kind: "card", c, el, sx: e.clientX, sy: e.clientY, ox: c.x, oy: c.y, moved: false };
      el.classList.add("lifting");
      // the card comes to the front
      C.b.items.splice(C.b.items.indexOf(c), 1); C.b.items.push(c); el.parentNode.append(el);
    } else {
      C.drag = { kind: "pan", sx: e.clientX, sy: e.clientY, ox: C.b.view.x, oy: C.b.view.y, moved: false };
      $("#ckStage").classList.add("panning");
    }
    $("#ckStage").setPointerCapture(e.pointerId);
    e.preventDefault();
  }
  addEventListener("pointermove", (e) => {
    const d = C.drag;
    if (!d && C.on && C.tieFrom) { C.aim = toWorld(e.clientX, e.clientY); return drawStrings(); }
    if (!d) return;
    const dx = e.clientX - d.sx, dy = e.clientY - d.sy;
    if (Math.abs(dx) + Math.abs(dy) > 3) d.moved = true;
    if (d.kind === "tie" || d.kind === "pluck") {
      const w = toWorld(e.clientX, e.clientY);
      if (d.kind === "tie") { d.wx = w.x; d.wy = w.y; const over = document.elementFromPoint(e.clientX, e.clientY)?.closest?.(".ck-card");
        $$("#ckCards .tie-target").forEach((x) => x !== over && x.classList.remove("tie-target")); if (over && over.dataset.id !== d.from) over.classList.add("tie-target"); }
      else { d.grab.x = w.x; d.grab.y = w.y; d.cx = e.clientX; d.cy = e.clientY; }
      drawStrings();
    } else if (d.kind === "card") {
      d.c.x = Math.round(d.ox + dx / C.b.view.z); d.c.y = Math.round(d.oy + dy / C.b.view.z);
      d.el.style.left = d.c.x + "px"; d.el.style.top = d.c.y + "px";
      drawStrings();
    } else {
      C.b.view.x = d.ox + dx; C.b.view.y = d.oy + dy;
      $("#ckWorld").style.transform = `translate(${C.b.view.x}px, ${C.b.view.y}px) scale(${C.b.view.z})`;
    }
  });
  addEventListener("pointerup", (e) => {
    const d = C.drag;
    if (!d) return;
    C.drag = null;
    if (d.kind === "pluck") { if (!d.moved) select({ kind: "string", id: d.id }); drawStrings(); return; }     // (let go: it springs back and wobbles)
    if (d.kind === "tie") {
      $$("#ckCards .tying, #ckCards .tie-target").forEach((x) => x.classList.remove("tying", "tie-target"));
      hint(C.tieMode ? "Click the first thing to tie, then the second. Esc to stop." : "");
      const over = document.elementFromPoint(e.clientX, e.clientY)?.closest?.(".ck-card");
      const tmp = ropes.get("_tie"); ropes.delete("_tie");
      if (over && over.dataset.id !== d.from && !C.b.strings.some((s) => (s.a === d.from && s.b === over.dataset.id) || (s.a === over.dataset.id && s.b === d.from))) {
        const id = Math.random().toString(16).slice(2, 12);
        if (tmp) ropes.set(id, tmp);                                 // (the string you were holding is the one that's tied: it keeps swinging)
        C.b.strings.push({ id, a: d.from, b: over.dataset.id, color: "red" });
        changed();
      } else if (!d.moved) { C.tiedAt = Date.now(); C.tieFrom = d.from; C.aim = toWorld(e.clientX, e.clientY); $(`#ckCards [data-id="${d.from}"]`)?.classList.add("tying"); hint("Now click another pin (or anything) to tie it to. Esc to stop."); }
      drawStrings();
      return;
    }
    $("#ckStage")?.classList.remove("panning");
    if (d.el) d.el.classList.remove("lifting");
    if (d.moved) changed();
  });
  /* selecting: click a card or a string; Delete (or Backspace) takes it off the board */
  function select(sel) {
    C.sel = sel;
    $$("#ckCards .sel").forEach((x) => x.classList.remove("sel"));
    if (sel && sel.kind === "card") $(`#ckCards [data-id="${sel.id}"]`)?.classList.add("sel");
    if (!C.tieFrom && !C.tieMode) hint(sel ? (sel.kind === "string" ? "String selected: Delete cuts it." : "Selected: Delete takes it off the board.") : "");
    drawStrings();
  }
  function removeSel() {
    const sel = C.sel;
    if (!sel) return false;
    if (sel.kind === "card") { C.b.items = C.b.items.filter((x) => x.id !== sel.id); C.b.strings = C.b.strings.filter((x) => x.a !== sel.id && x.b !== sel.id); }
    else C.b.strings = C.b.strings.filter((x) => x.id !== sel.id);
    C.sel = null; hint("");
    changed(true);
    return true;
  }

  /* ---------------- string */
  function setTie(on) {
    C.tieMode = on; C.tieFrom = null; C.aim = null; ropes.delete("_tie");
    $("#corkboard [data-ck=string]")?.setAttribute("aria-pressed", on ? "true" : "false");
    $("#ckStage")?.classList.toggle("tie-mode", on);
    hint(on ? "Click the first thing to tie, then the second. Esc to stop." : "");
    $$("#ckCards .tying").forEach((x) => x.classList.remove("tying"));
  }
  function hint(t) { const h = $("#ckHint"); if (!h) return; h.textContent = t; h.hidden = !t; }
  function tieTo(id) {
    if (C.tieFrom === id) { setTie(C.tieMode); return drawStrings(); }      // (the same pin again: never mind)
    if (!C.tieFrom) { C.tieFrom = id; $(`#ckCards [data-id="${id}"]`)?.classList.add("tying"); hint("Now click the thing to tie it to."); return; }
    if (C.tieFrom !== id && !C.b.strings.some((s) => (s.a === C.tieFrom && s.b === id) || (s.a === id && s.b === C.tieFrom))) {
      const sid = Math.random().toString(16).slice(2, 12), tmp = ropes.get("_tie");
      if (tmp) { ropes.delete("_tie"); ropes.set(sid, tmp); }
      C.b.strings.push({ id: sid, a: C.tieFrom, b: id, color: "red" });
      changed();
    }
    C.aim = null;
    const keep = C.tieMode;
    setTie(keep);
    drawStrings();
  }

  /* ---------------- clicks */
  async function onClick(e) {
    const t = e.target;
    if (t.closest?.("[data-string]")) return;          // (handled on pointerup: pluck or cut)
    if (Date.now() - (C.tiedAt || 0) < 400) return;   // (the click that just tied a string)
    const b = t.closest("[data-ck]");
    const el = t.closest(".ck-card");
    if ((C.tieMode || C.tieFrom) && el && !b) return tieTo(el.dataset.id);
    if (!b) { if (!t.closest("#ckPop")) $("#ckPop").hidden = true; return; }
    const k = b.dataset.ck;
    if (k === "close") return close();
    if (k === "note") return local({ type: "note", text: "", color: "yellow" }) && setTimeout(() => $$("#ckCards .t-note .ck-text").pop()?.focus(), 50);
    if (k === "paste") return pasteButton();
    if (k === "string") return setTie(!C.tieMode);
    if (k === "zin" || k === "zout") { const r = $("#ckStage").getBoundingClientRect(); return zoomAt(C.b.view.z * (k === "zin" ? 1.25 : 0.8), r.left + r.width / 2, r.top + r.height / 2); }
    if (k === "fit") return fit();
    if (k === "library") return libraryPicker(b);
    if (k === "save") return saveBoard(b);
    if (k === "boards") return boardsMenu(b);
    if (k === "clear") return clearMenu(b);
    if (!el) return;
    const c = card(el.dataset.id);
    if (k === "del") { C.b.items = C.b.items.filter((x) => x !== c); C.b.strings = C.b.strings.filter((x) => x.a !== c.id && x.b !== c.id); return changed(true); }
    if (k === "tie") return tieTo(c.id);
    if (k === "color") { c.color = b.dataset.color; el.className = el.className.replace(/n-\w+/, "n-" + c.color); return changed(); }
    if (k === "src" && e.detail === -1) {         // (opening is on double-click: see onDbl)
      if (c.item_id && window.Reader) { const it = S.items.find((i) => i.id === c.item_id); if (it) { close(); return Reader.open(it); } }
      if (c.url && window.Browser) { close(); Browser.open(); return Browser.go(c.url); }
    }
  }
  function onDbl(e) {
    const el = e.target.closest(".ck-card");
    if (!el || e.target.closest("[contenteditable]")) return;
    const c = card(el.dataset.id);
    if (e.target.closest("[data-ck=src]")) return openSrc(c);
    if (c.type === "media" && c.item_id) { openDrawer(c.item_id); }
    else if (c.type === "image") { el.classList.toggle("big"); }
  }
  function openSrc(c) {
    if (c.item_id && window.Reader) { const it = S.items.find((i) => i.id === c.item_id); if (it) { close(); return Reader.open(it); } }
    if (c.url && window.Browser) { close(); Browser.open(); return Browser.go(c.url); }
  }
  function onInput(e) {
    const el = e.target.closest(".ck-card");
    if (!el) return;
    const c = card(el.dataset.id);
    if (e.target.matches(".ck-text, .ck-cap")) { c.text = e.target.innerText; changed(); }
  }
  function stringMenu(id, e) {
    pop(`<div class="ck-row"><b>Red string</b><button class="btn sm" data-cut="${id}">✂ Cut it</button></div>`, e.clientX, e.clientY);
    $("#ckPop [data-cut]").onclick = () => { C.b.strings = C.b.strings.filter((s) => s.id !== id); $("#ckPop").hidden = true; drawStrings(); changed(); };
  }

  /* ---------------- the pop-up panels */
  function pop(html, x, y, anchor) {
    const p = $("#ckPop");
    p.innerHTML = html; p.hidden = false;
    const r = anchor ? anchor.getBoundingClientRect() : { left: x, bottom: y };
    const host = root().getBoundingClientRect();
    p.style.left = Math.max(8, Math.min(r.left - host.left, host.width - p.offsetWidth - 8)) + "px";
    p.style.top = (r.bottom - host.top + 6) + "px";
    return p;
  }
  function libraryPicker(btn) {
    const p = pop(`<input class="ck-find" placeholder="Find a book, paper, film or album…" autofocus><div class="ck-list"></div>`, 0, 0, btn);
    const list = p.querySelector(".ck-list"), inp = p.querySelector("input");
    const draw = () => {
      const q = inp.value.toLowerCase().split(/\s+/).filter(Boolean);
      const hits = S.items.filter((i) => !String(i.source || "").startsWith("reading-copy:") && q.every((w) => [i.title, (i.authors || []).join(" "), i.series, i.album].join(" ").toLowerCase().includes(w)))
        .sort((a, b) => (b.opened_at || 0) - (a.opened_at || 0)).slice(0, 40);
      list.innerHTML = hits.map((i) => `<button class="ck-hit-row" data-ckpick="${i.id}"><span class="ck-mini">${coverHTML(i)}</span><span><b>${esc(i.title || "Untitled")}</b><small>${esc(authorLine(i))} · ${esc(KIND_LABEL[i.kind] || i.kind)}</small></span></button>`).join("") || `<p class="hint">Nothing matches.</p>`;
    };
    inp.oninput = draw; draw(); inp.focus();
    list.onclick = (e) => { const r = e.target.closest("[data-ckpick]"); if (r) { pinMedia(Number(r.dataset.ckpick)); p.hidden = true; } };
  }
  async function saveBoard(btn) {
    const p = pop(`<form class="ck-row"><input class="ck-find" value="${esc(C.b.name || "")}" placeholder="Name this board" maxlength="120" required><button class="btn sm primary">Save</button></form>
      <p class="hint">Saving with a name you've used before saves over that board.</p>`, 0, 0, btn);
    const inp = p.querySelector("input"); inp.focus(); inp.select();
    p.querySelector("form").onsubmit = async (e) => {
      e.preventDefault();
      try {
        await flush();
        const r = await api.send("POST", "/api/corkboards", { name: inp.value, board: C.b });
        C.b.name = r.name; C.b.saved_id = r.id; C.dirtySinceSave = false; $("#ckName").value = r.name;
        p.hidden = true; toast(`Saved “${r.name}”`);
      } catch (err) { toast(err.message, "error"); }
    };
  }
  async function boardsMenu(btn) {
    let list = [];
    try { list = await api.get("/api/corkboards"); } catch (e) {}
    const when = (t) => new Date(t * 1000).toLocaleDateString([], { month: "short", day: "numeric", year: "numeric" });
    const p = pop(`<b class="ck-ph">Saved boards</b>${list.length ? list.map((s) => `<div class="ck-row ck-brow"><button class="ck-open" data-open-board="${s.id}"><b>${esc(s.name)}</b><small>${s.cards} thing${s.cards === 1 ? "" : "s"} · ${s.strings} string${s.strings === 1 ? "" : "s"} · ${when(s.saved_at)}</small></button><button class="icon-btn sm" data-del-board="${s.id}" title="Delete this saved board">🗑</button></div>`).join("") : `<p class="hint">No saved boards yet. Use 💾 Save board to keep this one.</p>`}`, 0, 0, btn);
    p.onclick = async (e) => {
      const o = e.target.closest("[data-open-board]"), d = e.target.closest("[data-del-board]");
      if (d) {
        const s = list.find((x) => x.id === d.dataset.delBoard);
        if (!confirm(`Delete the saved board “${s ? s.name : ""}”? This can't be undone.`)) return;
        await api.send("DELETE", `/api/corkboards/${d.dataset.delBoard}`); return boardsMenu(btn);
      }
      if (!o) return;
      if (C.b.items.length && C.dirtySinceSave && !confirm("The board on screen will be replaced by this one. Its changes since you last saved it aren't kept under a name. Open the saved board anyway?")) return;
      await flush();
      C.b = await api.send("POST", `/api/corkboards/${o.dataset.openBoard}/open`); C.loadedAt = Date.now() / 1000; C.dirtySinceSave = false;
      p.hidden = true; render(); setTimeout(fit, 60);
    };
  }
  function clearMenu(btn) {
    const p = pop(`<b class="ck-ph">Clear the whole board?</b><p class="hint">Everything on it comes off${C.b.saved_id && !C.dirtySinceSave ? " (it's saved as “" + esc(C.b.name) + "”)" : C.b.items.length ? ". It isn't saved under a name" : ""}.</p>
      <div class="ck-row"><button class="btn sm" data-c="save">💾 Save it first</button><button class="btn sm danger" data-c="clear">Clear the board</button><button class="btn sm" data-c="no">Cancel</button></div>`, 0, 0, btn);
    p.onclick = async (e) => {
      const k = e.target.closest("[data-c]")?.dataset.c;
      if (k === "no") p.hidden = true;
      if (k === "save") return saveBoard($("#corkboard [data-ck=save]"));
      if (k === "clear") { clearTimeout(C.saveT); C.b = await api.send("POST", "/api/corkboard/clear"); C.loadedAt = Date.now() / 1000; C.dirtySinceSave = false; p.hidden = true; render(); toast("The corkboard is clear"); }
    };
  }

  document.addEventListener("keydown", (e) => {
    if (!C.on) return;
    const typing = e.target.closest?.("[contenteditable], input, textarea, select");
    if ((e.key === "Delete" || e.key === "Backspace") && !typing && C.sel) { e.preventDefault(); removeSel(); return; }
    if (e.key === "Escape") {
      if (!$("#ckPop").hidden) { $("#ckPop").hidden = true; return; }
      if (C.tieMode || C.tieFrom) { setTie(false); return drawStrings(); }
      if (C.sel) return select(null);
      if (!e.target.closest?.("[contenteditable], input")) close();
      else e.target.blur();
    }
  });
  addEventListener("beforeunload", () => { if (C.saveT) flush(); });

  // from the browser (inapp.py): something was pinned there
  function pinned(d) {
    if (!d || !d.ok) return toast("Couldn't pin that: " + ((d && d.error) || "the page didn't answer"), "error");
    toast(d.kind === "snippet" ? "📌 Pinned the selected text to the corkboard" : "📌 Pinned this page to the corkboard");
    if (C.on) reload();
  }
  return { open, close, toggle: () => (C.on ? close() : open()), pin, pinned, get on() { return C.on; } };
})();
