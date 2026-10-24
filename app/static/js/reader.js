/* Babel's Library reader: PDF (pdf.js), EPUB (epub.js), comics (CBZ/CBR via libarchive.js) and video.
   Layouts: scrolling, one page, two pages. Highlights + titled notes, pins anywhere, figure zoom. */
(function () {
  const R = { item: null, anns: [], kind: null, pdf: null, pages: [], book: null, rendition: null, pending: null,
              activeId: null, saveT: null, pinMode: false, comic: null, page: 0, rtl: false, curPage: 1 };
  window.readerItem = () => ($("#reader") && !$("#reader").hidden ? R.item : null);    // (the floating journal opens on it)
  const HL = { yellow: "--hl-yellow", green: "--hl-green", blue: "--hl-blue", pink: "--hl-pink" };
  const cssVar = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
  const hlColor = (c) => cssVar(HL[c] || HL.yellow);
  const doc = () => $("#readerDoc");
  const isPin = (a) => a.locator && a.locator.type === "pin";
  const isBm = (a) => a.locator && a.locator.type === "bookmark";
  const COMIC = ["cbz", "cbr", "cb7", "cbt"];
  const typeKey = () => (R.kind === "comic" ? "comic" : R.kind);

  /* ---------- per-format layout preferences ---------- */
  const DEFAULT_MODE = { pdf: "scroll", epub: "single", comic: "single" };
  const DEFAULT_WIDTH = { pdf: 80, epub: 70, comic: 100 };
  function pref(key, kind, def) {
    try { const v = JSON.parse(localStorage.getItem("inkwell-" + key) || "{}")[kind]; return v ?? def; } catch (e) { return def; }
  }
  function setPref(key, kind, val) {
    try { const o = JSON.parse(localStorage.getItem("inkwell-" + key) || "{}"); o[kind] = val; localStorage.setItem("inkwell-" + key, JSON.stringify(o)); } catch (e) {}
  }
  const mode = () => pref("mode", typeKey(), DEFAULT_MODE[typeKey()] || "scroll");
  const width = () => pref("width", typeKey(), DEFAULT_WIDTH[typeKey()] || 80);

  /* ---------- open / close ---------- */
  async function open(item) {
    if (!item || !item.has_file) return;
    if (item.kind === "music") { const al = Media.albums(S.items).find((x) => x.tracks.some((t) => t.id === item.id)); Media.play(al ? al.tracks : [item], al ? al.tracks.findIndex((t) => t.id === item.id) : 0); return; }
    if (R.item) await close(true);
    // always start from the newest saved position (the library list can be a few seconds behind)
    try { const fresh = await api.get(`/api/items/${item.id}`); item = { ...item, last_location: fresh.last_location, progress: fresh.progress, audio_status: fresh.audio_status }; } catch (e) {}
    R.item = item;
    R.opened = false;
    R.relaying = false; clearTimeout(R._rz); R._rz = null; doc().classList.remove("relaying");
    R.savedLoc = String(item.last_location || "");
    R.activeId = null;
    setPinMode(false);
    $("#reader").hidden = false;
    document.body.style.overflow = "hidden";
    $("#readerTitle").textContent = item.title || "Untitled";
    $("#exportMd").href = `/api/export/annotations?format=md&items=${item.id}`;
    $("#exportJson").href = `/api/export/annotations?format=json&items=${item.id}`;
    doc().innerHTML = `<p class="hint" style="text-align:center;margin-top:20vh">Opening…</p>`;
    const comic = COMIC.includes(item.file_type);
    const video = ["tv", "movie"].includes(item.kind);
    R.kind = item.file_type === "pdf" ? "pdf" : item.file_type === "epub" ? "epub" : comic ? "comic" : "video";
    $("#reader").classList.toggle("is-comic", comic);
    $("#reader").classList.toggle("is-video", video);
    $("#reader").classList.toggle("notes-hidden", video || !R.notesOpen);
    // manga that came as a PDF (Goodnight Punpun, BLAME!) reads right to left too
    const pdfComic = R.kind === "pdf" && item.kind === "graphic";
    if (pdfComic) { R.rtl = item.direction === "rtl"; updateComicButtons(); } else if (R.kind === "pdf") R.rtl = false;
    $("#rDir").hidden = !(comic || pdfComic);
    $("#rPin").hidden = comic || video;
    $("#rMark").hidden = video;
    $("#rView").hidden = video;
    $("#toggleNotes").hidden = video;
    $("#rFontRow").hidden = R.kind !== "epub";
    syncViewMenu();
    syncArrows();
    $("#rListen").hidden = item.audio_status !== "ready";
    R.abm = null; R.abLast = null;
    R.anns = video ? [] : await api.get(`/api/items/${item.id}/annotations`);
    renderNotes();
    api.send("PATCH", `/api/items/${item.id}`, { opened: true }).catch(() => {});
    $("#rPrev").title = video ? "Previous episode" : "Previous";
    $("#rNext").title = video ? "Next episode" : "Next";
    $("#rToc").innerHTML = $("#rToc").innerHTML.replace(/(Contents|Episodes)$/, video ? "Episodes" : "Contents");
    let tocOpen = false; try { tocOpen = localStorage.getItem("inkwell-toc-open") === "1"; } catch (e) {}
    $("#tocPanel").hidden = true;
    try {
      if (R.kind === "pdf") await openPdf(item);
      else if (R.kind === "epub") await openEpub(item);
      else if (R.kind === "comic") await openComic(item);
      else openVideo(item);
      if (tocOpen) toggleToc(true);
    } catch (e) {
      console.error(e);
      doc().innerHTML = `<div class="empty"><h2>Couldn't open this file</h2><p>${esc(e.message || e)}</p></div>`;
    }
  }

  async function close(keepOpen) {
    if (MINI && keepOpen !== true) {
      await saveNow();
      const res = await api.send("POST", "/api/desktop/reader", { action: "close" }).catch(() => ({}));
      if (!res.ok) window.close();
      return;
    }
    hidePop();
    $("#viewPop").hidden = true;
    await saveNow();  // don't lose the last few seconds of reading position
    if (R.pdf) { R.pdf.destroy(); R.pdf = null; R.pre = null; }
    if (R.book) { R.book.destroy(); R.book = null; R.rendition = null; }
    if (R.comic) { R.comic.close(); R.comic = null; }
    const v = doc().querySelector("video");
    if (v) { v.pause(); v.removeAttribute("src"); v.load(); }
    R.observer && R.observer.disconnect();
    doc().innerHTML = "";
    doc().onscroll = null;
    R.item = null;
    if (keepOpen === true) return;
    $("#reader").classList.remove("immersive", "peek");
    document.body.classList.remove("reader-immersive", "peek-player");
    $("#reader").hidden = true;
    document.body.style.overflow = "";
    loadItems();
  }

  function saveProgress(location, progress) {
    clearTimeout(R.saveT);
    if (document.visibilityState === "hidden" || R.relaying) return;  // a hidden window isn't being read
    const id = R.item.id;
    R.savedLoc = String(location);
    R.pendingSave = () => api.send("PATCH", `/api/items/${id}`, { last_location: String(location), progress }).catch(() => {});
    R.saveT = setTimeout(() => { const f = R.pendingSave; R.pendingSave = null; f && f(); }, 700);
  }
  function saveNow() {
    clearTimeout(R.saveT);
    const v = doc().querySelector("video");
    if (v && R.item && v.duration) R.pendingSave = () => api.send("PATCH", `/api/items/${R.item.id}`, { last_location: v.currentTime.toFixed(0), progress: v.currentTime / v.duration }).catch(() => {});
    const f = R.pendingSave; R.pendingSave = null;
    return f ? f() : Promise.resolve();
  }

  function setPinMode(on) {
    R.pinMode = on;
    $("#rPin").classList.toggle("on", on);
    $("#reader").classList.toggle("pin-mode", on);
    $("#rPin").setAttribute("aria-pressed", on ? "true" : "false");
  }

  async function createAnn(body) {
    const a = await api.send("POST", `/api/items/${R.item.id}/annotations`, { title: "", note: "", quote: "", color: "yellow", ...body });
    R.anns.push(a);
    $("#reader").classList.remove("notes-hidden");
    renderNotes();
    redraw();
    activate(a.id, true);
    if (isPin(a)) setTimeout(() => $(`.note[data-id="${a.id}"] .n-note`)?.focus({ preventScroll: true }), 50);
    return a;
  }

  /* ---------- view menu ---------- */
  function syncViewMenu() {
    $$("#rMode button").forEach((b) => b.classList.toggle("on", b.dataset.mode === mode()));
    $("#rWidth").value = width();
    $("#rFont").value = pref("font", "epub", 105);
  }
  function setMode(m) {
    setPref("mode", typeKey(), m);
    syncViewMenu();
    syncArrows();
    relayout();
  }
  function relayout() {
    if (R.kind === "pdf") return R.pdf ? layoutPdf(R.curPage || 1) : undefined;   // closed while a re-layout was waiting
    else if (R.kind === "epub") return rebuildEpub();
    else if (R.kind === "comic") return renderComic();
  }

  /* Changing the window size (mini reader <-> full screen) used to re-lay the book out several times while the
     window was still growing, each time from a slightly different spot. Now: note the exact spot first, hide the
     page, wait for the size to stop changing, lay out once at that spot, then fade back in. */
  function capturePos() {
    const d = doc();
    if (R.kind === "pdf" && mode() === "scroll" && R.pages) {
      let topPg = 1;
      for (const p of R.pages) { if (p && p.el.offsetTop <= d.scrollTop + 24) topPg = p.num; else if (p) break; }
      const pe = R.pages[topPg - 1]?.el;
      R.curPage = topPg;
      R.startFrac = pe ? Math.max(0, Math.min(0.99, (d.scrollTop + 24 - pe.offsetTop) / pe.offsetHeight)) : 0;
    } else if (R.kind === "comic" && mode() === "scroll") {
      let topPg = R.page || 0;
      for (const el of $$(".comic-page", d)) { if (el.offsetTop <= d.scrollTop + 2) topPg = Number(el.dataset.page) - 1; else break; }
      const tEl = d.querySelector(`.comic-page[data-page="${topPg + 1}"]`);
      R.page = topPg;
      R.startFrac = tEl ? Math.max(0, Math.min(0.99, (d.scrollTop - tEl.offsetTop) / tEl.offsetHeight)) : 0;
    }
  }
  function softRelayout() {
    const shown = () => requestAnimationFrame(() => doc().classList.remove("reflow"));
    if (!R.item || R.relaying) return shown();
    if (R.kind === "epub" && R.rendition && mode() !== "scroll") {
      const cfi = R.loc?.start?.cfi;
      try {
        R.rendition.resize();
        if (cfi) R.rendition.display(cfi).then(() => prepSnap()).catch(() => {}).finally(shown);
        else shown();
      } catch (e) { shown(); queueRelayout(); }
      return;
    }
    if (R.kind === "epub") { try { R.rendition?.resize(); } catch (e) { queueRelayout(); } return shown(); }
    Promise.resolve(relayout()).catch(() => {}).finally(shown);
  }
  function queueRelayout(expectResize) {
    if (!R.item || R.kind === "video") return;
    if (expectResize) R.waitSizeUntil = Date.now() + 700;  // the window is about to change size; don't lay out before it does
    if (!R.relaying) {
      R.relaying = true;
      capturePos();
      R.restoring = true; R.pdfRestoring = true; R.comicRestoring = true;  // ignore positions reported mid-resize
      doc().classList.add("relaying");
    }
    const size = () => `${window.innerWidth}x${window.innerHeight}`;
    let last = size();
    if (expectResize) R.sizeBefore = last;
    clearTimeout(R._rz);
    const check = () => {
      const now = size();
      if (now !== last) { last = now; R._rz = setTimeout(check, 80); return; }
      if (R.waitSizeUntil && now === R.sizeBefore && Date.now() < R.waitSizeUntil) { R._rz = setTimeout(check, 40); return; }
      R.waitSizeUntil = 0;
      R._rz = null;
      R.quickRestore = true;
      Promise.resolve(relayout()).catch(() => {}).then(() => {
        if (R._rz) return;  // another resize started meanwhile
        R.relaying = false;
        requestAnimationFrame(() => doc().classList.remove("relaying"));
      });
    };
    R._rz = setTimeout(check, 90);
  }

  /* ---------- pins (shared by PDF pages and comic pages) ---------- */
  function pinNumber(a) { return sortAnns().filter(isPin).indexOf(a) + 1; }

  function drawPins(layer, pageNum) {
    if (!layer) return;
    layer.innerHTML = "";
    for (const a of R.anns.filter((x) => isPin(x) && x.locator.page === pageNum)) {
      const b = document.createElement("button");
      b.className = "pin" + (a.id === R.activeId ? " active" : "");
      b.dataset.ann = a.id;
      b.style.left = a.locator.x * 100 + "%";
      b.style.top = a.locator.y * 100 + "%";
      b.style.setProperty("--pin", hlColor(a.color));
      b.title = (a.title || a.note || "Pin").slice(0, 120) + " (drag to move)";
      b.innerHTML = `<span>${pinNumber(a)}</span>`;
      layer.append(b);
    }
  }

  function pageCoords(e, pageEl) {
    const b = pageEl.getBoundingClientRect();
    return { x: Math.min(.99, Math.max(.01, (e.clientX - b.left) / b.width)), y: Math.min(.99, Math.max(.01, (e.clientY - b.top) / b.height)) };
  }

  function bindPinDragging(root) {
    root.addEventListener("pointerdown", (e) => {
      const pin = e.target.closest(".pin");
      if (!pin) return;
      e.preventDefault();
      e.stopPropagation();
      const a = R.anns.find((x) => x.id === Number(pin.dataset.ann));
      const pageEl = pin.closest("[data-page]");
      let moved = false;
      const sx = e.clientX, sy = e.clientY;
      pin.setPointerCapture(e.pointerId);
      const move = (ev) => {
        if (!moved && Math.hypot(ev.clientX - sx, ev.clientY - sy) < 4) return;
        moved = true;
        const c = pageCoords(ev, pageEl);
        pin.style.left = c.x * 100 + "%";
        pin.style.top = c.y * 100 + "%";
        pin.classList.add("dragging");
      };
      const up = (ev) => {
        pin.removeEventListener("pointermove", move);
        pin.removeEventListener("pointerup", up);
        pin.classList.remove("dragging");
        if (moved) {
          const c = pageCoords(ev, pageEl);
          a.locator = { ...a.locator, x: c.x, y: c.y };
          api.send("PATCH", `/api/annotations/${a.id}`, { locator: a.locator });
        }
        activate(a.id, true);
      };
      pin.addEventListener("pointermove", move);
      pin.addEventListener("pointerup", up);
    });
  }

  /* ---------- PDF ---------- */
  async function openPdf(item) {
    const pdf = await pdfjsLib.getDocument({ url: `/api/items/${item.id}/file` }).promise;
    const base = (await pdf.getPage(1)).getViewport({ scale: 1 });
    R.baseSize = { w: base.width, h: base.height };
    R.pdf = pdf;          // only now: a re-layout that fires in between needs the page size
    R.pre = new Map();
    // saved as "page" or "page:fraction-of-page-scrolled" so scrolling mode reopens at the exact spot
    R.startFrac = parseFloat(String(item.last_location || "").split(":")[1]) || 0;
    layoutPdf(Math.min(R.pdf.numPages, parseInt(item.last_location) || 1));
  }

  // page modes leave a margin on each side for the page-turn arrows
  const ARROW_GUTTER = 58;
  const pagedMode = () => mode() !== "scroll" && R.kind !== "video";
  const innerW = () => doc().clientWidth - (pagedMode() ? ARROW_GUTTER * 2 : 0);
  function syncArrows() {
    const on = !!R.item && pagedMode();
    $("#reader").classList.toggle("has-arrows", on);
  }

  function pdfScale(perRow) {
    const box = doc();
    const availW = (innerW() - 48) * width() / 100 / perRow;
    let s = availW / R.baseSize.w;
    if (mode() !== "scroll") {
      const cs = getComputedStyle(box);   // leave room for the book's cover around the pages
      s = Math.min(s, (box.clientHeight - parseFloat(cs.paddingTop) - parseFloat(cs.paddingBottom) - 40) / R.baseSize.h);
    }
    return Math.max(0.3, Math.min(4, s));
  }

  function newPdfPage(num, scale) {
    const el = document.createElement("div");
    el.className = "pdf-page";
    el.dataset.page = num;
    el.style.width = R.baseSize.w * scale + "px";
    el.style.height = R.baseSize.h * scale + "px";
    el.innerHTML = `<span class="pnum">${num}</span><button class="page-zoom" title="Zoom into this page" data-zoom-page="${num}">⤢</button>`;
    return { num, el, rendered: false, scale };
  }

  function layoutPdf(startPage) {
    R.observer && R.observer.disconnect();
    doc().innerHTML = "";
    doc().onscroll = null;
    R.pages = new Array(R.pdf.numPages);
    const m = mode();
    doc().classList.toggle("paged", m !== "scroll");
    if (m === "scroll") {
      const scale = pdfScale(1);
      R.observer = new IntersectionObserver((entries) => {
        for (const en of entries) if (en.isIntersecting) renderPdfPage(R.pages[Number(en.target.dataset.page) - 1]);
      }, { root: doc(), rootMargin: "800px 0px" });
      for (let i = 1; i <= R.pdf.numPages; i++) {
        const p = newPdfPage(i, scale);
        doc().append(p.el);
        R.pages[i - 1] = p;
        R.observer.observe(p.el);
      }
      doc().onscroll = onPdfScroll;
      R.pdfRestoring = true;
      requestAnimationFrame(() => {
        const el = R.pages[startPage - 1]?.el;
        if (el) doc().scrollTop = el.offsetTop - 24 + (R.startFrac || 0) * el.offsetHeight;
        R.startFrac = 0;
        R.pdfRestoring = false;
        onPdfScroll();
      });
    } else {
      showPdfSpread(startPage);
    }
  }

  function spreadFor(n, total, double) {
    if (!double || n === 1) return [n];
    const start = n % 2 === 0 ? n : n - 1;
    return start + 1 <= total ? [start, start + 1] : [start];
  }

  function showPdfSpread(n) {
    const total = R.pdf.numPages;
    n = Math.max(1, Math.min(total, n));
    const nums = spreadFor(n, total, mode() === "double");
    // like a real book: the title page (or a last page on its own) sits on one side of an open spread, the other side
    // left blank, so turning it is an ordinary leaf turn instead of a lone page jumping into a two-page spread
    const lone = mode() === "double" && nums.length === 1 && total > 1;
    const scale = pdfScale(lone ? 2 : nums.length);
    const spread = document.createElement("div");
    spread.className = "pdf-spread";
    doc().innerHTML = "";
    doc().append(spread);
    let first = null;
    for (const num of R.rtl ? [...nums].reverse() : nums) {   // right to left: the first page of a spread is on the right
      const p = newPdfPage(num, scale);
      R.pages[num - 1] = p;
      spread.append(p.el);
      renderPdfPage(p);
      first = first || p;
    }
    if (lone) {
      const blank = document.createElement("div");
      blank.className = "pdf-page pdf-blank";
      const fit = () => { blank.style.width = first.el.offsetWidth + "px"; blank.style.height = first.el.offsetHeight + "px"; };
      fit();
      new ResizeObserver(fit).observe(first.el);
      // the title page is a right-hand page (left-hand for right-to-left books); a last page on its own, the other way
      const onLeft = (nums[0] === 1) !== !!R.rtl;
      onLeft ? spread.prepend(blank) : spread.append(blank);
    }
    R.curPage = nums[0];
    if (!R.opened) { bookIntro(); bookOpen(); }
    markTocCurrent();
    paintMarks();
    $("#rPos").textContent = `${nums.join("–")} / ${total}`;
    if (!R.turning) prepSnap(350);
    prerenderAround(nums, total);
    saveProgress(nums[0], total > 1 ? (nums[nums.length - 1] - 1) / (total - 1) : 1);
  }

  async function renderPdfPage(p) {
    if (!p || p.rendered || !R.pdf) return;
    p.rendered = true;
    const page = await R.pdf.getPage(p.num);
    const vp = page.getViewport({ scale: p.scale });
    const dpr = window.devicePixelRatio || 1;
    const el = p.el;
    el.style.width = vp.width + "px";
    el.style.height = vp.height + "px";
    el.style.setProperty("--scale-factor", vp.scale);
    const canvas = document.createElement("canvas");
    canvas.width = Math.floor(vp.width * dpr);
    canvas.height = Math.floor(vp.height * dpr);
    canvas.style.width = vp.width + "px";
    canvas.style.height = vp.height + "px";
    const tint = (THEMES[document.documentElement.dataset.theme] || {}).pageTint;
    if (tint) canvas.style.filter = tint;
    const text = document.createElement("div");
    text.className = "textLayer";
    const hl = document.createElement("div");
    hl.className = "hl-layer";
    const figs = document.createElement("div");
    figs.className = "fig-layer";
    const pins = document.createElement("div");
    pins.className = "pin-layer";
    el.prepend(canvas, text, hl, figs, pins);
    const ready = R.pre && R.pre.get(preKey(p.num, p.scale));
    if (ready) canvas.getContext("2d").drawImage(await ready, 0, 0);       // drawn ahead of time: shows at once
    else await page.render({ canvasContext: canvas.getContext("2d"), viewport: vp, transform: dpr !== 1 ? [dpr, 0, 0, dpr, 0, 0] : null }).promise;
    const task = pdfjsLib.renderTextLayer({ textContentSource: page.streamTextContent(), container: text, viewport: vp, textDivs: [] });
    await task.promise.catch(() => {});
    drawPdfAnnotations(p.num);
    // comics and manga are pictures from edge to edge: looking for figures in them only costs time
    if (R.item?.kind !== "graphic") findFigures(page, vp, figs, p.num).catch(() => {});
  }
  /* the pages you'll turn to next are drawn ahead into spare canvases (paged mode), so a turn shows them instantly */
  const preKey = (num, scale) => num + "@" + scale.toFixed(4);
  function prerender(num, scale) {
    if (!R.pdf || num < 1 || num > R.pdf.numPages) return;
    R.pre = R.pre || new Map();
    const key = preKey(num, scale);
    if (R.pre.has(key)) return;
    R.pre.set(key, (async () => {
      const page = await R.pdf.getPage(num);
      const vp = page.getViewport({ scale }), dpr = window.devicePixelRatio || 1;
      const c = document.createElement("canvas");
      c.width = Math.floor(vp.width * dpr); c.height = Math.floor(vp.height * dpr);
      await page.render({ canvasContext: c.getContext("2d"), viewport: vp, transform: dpr !== 1 ? [dpr, 0, 0, dpr, 0, 0] : null }).promise;
      return c;
    })());
    if (R.pre.size > 10) R.pre.delete(R.pre.keys().next().value);        // only the few around where you are
  }
  function prerenderAround(nums, total) {
    const double = mode() === "double";
    const nextFirst = nums[nums.length - 1] + 1, prevLast = nums[0] - 1;
    const ahead = [...spreadFor(nextFirst, total, double), ...(nextFirst <= total ? spreadFor(spreadFor(nextFirst, total, double).slice(-1)[0] + 1, total, double) : [])];
    const back = prevLast >= 1 ? spreadFor(prevLast, total, double) : [];
    clearTimeout(R.preT);
    R.preT = setTimeout(() => {
      for (const n of [...ahead, ...back]) {
        if (n < 1 || n > total) continue;
        const sp = spreadFor(n, total, double);
        prerender(n, pdfScale(double && sp.length === 1 && total > 1 ? 2 : sp.length));
      }
    }, 250);
  }

  /* images inside the PDF page become clickable figures */
  async function findFigures(page, vp, layer, num) {
    const ops = await page.getOperatorList();
    const O = pdfjsLib.OPS;
    const paint = new Set([O.paintImageXObject, O.paintInlineImageXObject, O.paintImageMaskXObject, O.paintImageXObjectRepeat, O.paintJpegXObject].filter((x) => x !== undefined));
    const mul = (a, b) => [a[0] * b[0] + a[2] * b[1], a[1] * b[0] + a[3] * b[1], a[0] * b[2] + a[2] * b[3], a[1] * b[2] + a[3] * b[3], a[0] * b[4] + a[2] * b[5] + a[4], a[1] * b[4] + a[3] * b[5] + a[5]];
    let ctm = [1, 0, 0, 1, 0, 0];
    const stack = [];
    const boxes = [];
    for (let i = 0; i < ops.fnArray.length; i++) {
      const fn = ops.fnArray[i];
      if (fn === O.save) stack.push(ctm);
      else if (fn === O.restore) ctm = stack.pop() || [1, 0, 0, 1, 0, 0];
      else if (fn === O.transform) ctm = mul(ctm, ops.argsArray[i]);
      else if (paint.has(fn)) {
        const pts = [[0, 0], [1, 0], [0, 1], [1, 1]].map(([x, y]) => [ctm[0] * x + ctm[2] * y + ctm[4], ctm[1] * x + ctm[3] * y + ctm[5]]);
        const xs = pts.map((q) => q[0]), ys = pts.map((q) => q[1]);
        const r = vp.convertToViewportRectangle([Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)]);
        const x1 = Math.min(r[0], r[2]), y1 = Math.min(r[1], r[3]), x2 = Math.max(r[0], r[2]), y2 = Math.max(r[1], r[3]);
        const w = (x2 - x1) / vp.width, h = (y2 - y1) / vp.height;
        if (w > 0.12 && h > 0.06 && w < 0.98) boxes.push({ x: x1 / vp.width, y: y1 / vp.height, w, h });
      }
    }
    layer.innerHTML = "";
    for (const b of boxes.slice(0, 12)) {
      const f = document.createElement("button");
      f.className = "fig";
      f.title = "Click to view this figure full screen";
      f.style.cssText = `left:${b.x * 100}%;top:${b.y * 100}%;width:${b.w * 100}%;height:${b.h * 100}%`;
      f.onclick = (e) => { e.stopPropagation(); if (!R.pinMode) zoomPdfRegion(num, b); };
      layer.append(f);
    }
  }

  async function zoomPdfRegion(num, box) {
    const page = await R.pdf.getPage(num);
    const base = page.getViewport({ scale: 1 });
    const target = Math.min(6, 2600 / (base.width * (box ? box.w : 1)));
    const vp = page.getViewport({ scale: target });
    const c = document.createElement("canvas");
    c.width = Math.floor(vp.width); c.height = Math.floor(vp.height);
    await page.render({ canvasContext: c.getContext("2d"), viewport: vp }).promise;
    let out = c;
    if (box) {
      out = document.createElement("canvas");
      const pad = 0.01;
      const sx = Math.max(0, (box.x - pad) * c.width), sy = Math.max(0, (box.y - pad) * c.height);
      const sw = Math.min(c.width - sx, (box.w + 2 * pad) * c.width), sh = Math.min(c.height - sy, (box.h + 2 * pad) * c.height);
      out.width = sw; out.height = sh;
      out.getContext("2d").drawImage(c, sx, sy, sw, sh, 0, 0, sw, sh);
    }
    Lightbox.show(out.toDataURL("image/png"), box ? `Figure on page ${num}` : `Page ${num}`);
  }

  function drawPdfAnnotations(num) {
    const pages = num ? [R.pages[num - 1]] : R.pages;
    for (const p of pages) {
      const layer = p && p.el.querySelector(".hl-layer");
      if (!layer) continue;
      layer.innerHTML = "";
      for (const a of R.anns) {
        for (const r of (a.locator.rects || []).filter((r) => r.p === p.num)) {
          const d = document.createElement("div");
          d.className = "hl";
          d.dataset.ann = a.id;
          d.style.cssText = `left:${r.x * 100}%;top:${r.y * 100}%;width:${r.w * 100}%;height:${r.h * 100}%;background:${hlColor(a.color)};opacity:${a.id === R.activeId ? 1 : .8}`;
          d.title = a.title || a.note || "Highlight";
          d.onclick = (e) => { e.stopPropagation(); activate(a.id, true); };
          layer.append(d);
        }
      }
      drawPins(p.el.querySelector(".pin-layer"), p.num);
    }
  }

  function onPdfScroll() {
    if (R.pdfRestoring) return;
    const top = doc().scrollTop + doc().clientHeight / 3;
    let cur = 1;
    for (const p of R.pages) { if (p && p.el.offsetTop <= top) cur = p.num; else if (p) break; }
    // where the top of the window is, for reopening at exactly this spot
    let topPg = 1;
    for (const p of R.pages) { if (p && p.el.offsetTop <= doc().scrollTop + 24) topPg = p.num; else if (p) break; }
    const pe = R.pages[topPg - 1]?.el;
    const frac = pe ? Math.max(0, Math.min(0.99, (doc().scrollTop + 24 - pe.offsetTop) / pe.offsetHeight)) : 0;
    if (cur !== R.curPage) { R.curPage = cur; markTocCurrent(); }
    $("#rPos").textContent = `${cur} / ${R.pdf.numPages}`;
    if (R.item) saveProgress(frac > 0.01 ? `${topPg}:${frac.toFixed(3)}` : topPg, R.pdf.numPages > 1 ? (cur - 1) / (R.pdf.numPages - 1) : 1);
  }

  function pdfSelection() {
    const sel = window.getSelection();
    if (!sel || sel.isCollapsed || !sel.rangeCount) return null;
    const range = sel.getRangeAt(0);
    const startPage = range.startContainer.parentElement?.closest(".pdf-page");
    if (!startPage || !doc().contains(startPage)) return null;
    const quote = sel.toString().replace(/\s+/g, " ").trim();
    if (!quote) return null;
    const rects = [];
    const pageBoxes = R.pages.filter((p) => p && p.rendered).map((p) => ({ p, b: p.el.getBoundingClientRect() }));
    for (const cr of range.getClientRects()) {
      if (cr.width < 1 || cr.height < 1) continue;
      const cx = cr.left + cr.width / 2, cy = cr.top + cr.height / 2;
      const hit = pageBoxes.find(({ b }) => cx >= b.left && cx <= b.right && cy >= b.top && cy <= b.bottom);
      if (!hit) continue;
      const b = hit.b;
      const r = { p: hit.p.num, x: (cr.left - b.left) / b.width, y: (cr.top - b.top) / b.height, w: cr.width / b.width, h: cr.height / b.height };
      const prev = rects.find((q) => q.p === r.p && Math.abs(q.y - r.y) < r.h * 0.5 && r.x <= q.x + q.w + 0.01 && r.x + r.w >= q.x - 0.01);
      if (prev) { const x2 = Math.max(prev.x + prev.w, r.x + r.w); prev.x = Math.min(prev.x, r.x); prev.w = x2 - prev.x; prev.h = Math.max(prev.h, r.h); }
      else rects.push(r);
    }
    if (!rects.length) return null;
    const last = range.getClientRects();
    const lr = last[last.length - 1];
    return { quote, locator: { page: rects[0].p, rects }, at: { x: lr.right, y: lr.bottom } };
  }

  /* ---------- EPUB ---------- */
  /* epub.js re-displays the chapter start whenever the window size changes, and trims chapters it thinks are
     off screen (adjusting the scroll position by a sometimes-wrong height). In scrolling mode both make the
     book jump back to the top of the chapter, so: keep the reading position on resize, and keep chapters loaded. */
  if (window.ePub && ePub.Rendition && !ePub.Rendition.prototype._inkPatched) {
    const origResized = ePub.Rendition.prototype.onResized;
    ePub.Rendition.prototype.onResized = function (size, epubcfi) {
      // scrolling mode: the views were cleared; show the exact spot that was on screen (not the chapter start)
      if (String(this.settings.flow || "").startsWith("scrolled") && R.startCfi) return origResized.call(this, size, R.startCfi);
      return origResized.call(this, size, epubcfi);
    };
    ePub.Rendition.prototype._inkPatched = true;
  }

  async function openEpub(item) {
    const buf = await (await fetch(`/api/items/${item.id}/file`)).arrayBuffer();
    R.book = ePub(buf);
    R.startCfi = item.last_location && item.last_location.startsWith("epubcfi") ? item.last_location : undefined;
    await buildEpub();
    R.book.ready.then(() => R.book.locations.generate(1200)).then(() => R.loc && R.rendition && R.rendition.emit("relocated", R.loc)).catch(() => {});
  }

  async function buildEpub() {
    R.abLast = null; R.abCfi = null;
    const m = mode();
    const maxW = Math.round((innerW() - 40) * width() / 100);
    doc().classList.toggle("paged", m !== "scroll");
    doc().innerHTML = m === "scroll"
      ? `<div class="epub-wrap ${m}" style="max-width:${maxW}px"><div id="epubView"></div></div>`
      : `<div class="epub-wrap ${m} rbook" style="max-width:${maxW}px">
          <div class="bk-head"><span class="bk-hl">${esc(R.item?.title || "")}</span><span class="bk-hr" id="bkChap"></span></div>
          <div id="epubView"></div>
          <div class="bk-foot"><span id="bkPgL"></span><span id="bkPgR"></span></div>
          <div class="bk-curve"></div><div class="rb-marks" id="bkMarks"></div>
        </div>`;
    bookIntro();
    const opts = m === "scroll"
      ? { width: "100%", height: "100%", flow: "scrolled", manager: "continuous", allowScriptedContent: false, ignoreClass: "ink-pin" }
      : { width: "100%", height: "100%", flow: "paginated", spread: m === "double" ? "always" : "none", minSpreadWidth: 0, allowScriptedContent: false, ignoreClass: "ink-pin" };
    R.rendition = R.book.renderTo("epubView", opts);
    applyEpubTheme();
    R.rendition.hooks.content.register((contents) => {
      const d = contents.document;
      const ff = d.createElement("style");   // the book face isn't otherwise available inside the page
      ff.textContent = `@font-face{font-family:"Libre Baskerville";src:url("${location.origin}/vendor/fonts/libre-baskerville-latin-400-normal.woff2") format("woff2");font-weight:400}
        @font-face{font-family:"Libre Baskerville";src:url("${location.origin}/vendor/fonts/libre-baskerville-latin-700-normal.woff2") format("woff2");font-weight:700}
        body{text-rendering:optimizeLegibility;hyphens:auto} p{text-align:justify}`;
      d.head.append(ff);
      d.addEventListener("keydown", keyNav);
      d.addEventListener("wheel", pauseFollow, { passive: true });
      d.addEventListener("mousedown", hidePop);
      const st = d.createElement("style");
      st.textContent = `.ink-pin{position:absolute;z-index:5;width:22px;height:22px;margin:-24px 0 0 -11px;border-radius:50% 50% 50% 0;transform:rotate(-45deg);
        border:2px solid rgba(0,0,0,.65);cursor:pointer;box-shadow:0 2px 6px rgba(0,0,0,.4);font:700 11px/18px sans-serif;text-align:center;color:#111}
        .ink-pin span{display:inline-block;transform:rotate(45deg)} .ink-pin.active{outline:3px solid #fff}
        img,svg image{cursor:zoom-in} body.ink-pin-mode, body.ink-pin-mode *{cursor:crosshair !important}`;
      d.head.append(st);
      d.body.classList.toggle("ink-pin-mode", R.pinMode);
      d.addEventListener("click", (e) => {
        const pin = e.target.closest?.(".ink-pin");
        if (pin) { e.preventDefault(); activate(Number(pin.dataset.ann), true); return; }
        if (R.pinMode) return epubPinAt(contents, e);
        const img = e.target.closest?.("img") || (e.target.tagName === "image" ? e.target : null);
        if (img) {
          e.preventDefault();
          const src = img.currentSrc || img.src || img.getAttribute("href") || img.getAttributeNS("http://www.w3.org/1999/xlink", "href");
          if (src) return Lightbox.show(src, img.alt || "");
        }
        if (e.target.closest?.("a[href]")) return;
        if (mode() !== "scroll" && d.getSelection().isCollapsed) {
          const fr = contents.document.defaultView.frameElement.getBoundingClientRect();
          const box = $("#epubView").getBoundingClientRect();
          const x = (fr.left + e.clientX - box.left) / box.width;
          if (x < 0.33) goSide("left");
          else if (x > 0.67) goSide("right");
        }
      });
      drawEpubPins(contents);
    });
    R.rendition.on("selected", (cfi, contents) => {
      if (R.pinMode) return;
      const sel = contents.window.getSelection();
      const quote = sel.toString().replace(/\s+/g, " ").trim();
      if (!quote) return;
      const rr = sel.getRangeAt(0).getBoundingClientRect();
      const fr = contents.document.defaultView.frameElement.getBoundingClientRect();
      R.pending = { quote, locator: { cfi, label: chapterLabel() }, contents };
      showPop(fr.left + rr.right, fr.top + rr.bottom);
    });
    R.rendition.on("relocated", (loc) => {
      if (R.restoring) return;  // ignore the in-between positions while jumping to where you left off
      R.loc = loc;
      R.startCfi = loc.start.cfi;
      const pct = R.book.locations.length() ? R.book.locations.percentageFromCfi(loc.start.cfi) : null;
      $("#rPos").textContent = [chapterLabel(), pct != null ? Math.round(pct * 100) + "%" : ""].filter(Boolean).join(" · ");
      saveProgress(loc.start.cfi, pct ?? R.item.progress ?? 0);
      markTocCurrent();
      bookChrome(loc);
      if (!R.turning) prepSnap();
    });

    R.restoring = true;
    try {
      await R.rendition.display(R.startCfi);
      if (R.startCfi) {
        // the page finishes laying out (fonts, theme, images) after the first jump, which shifts the text;
        // jump again once it has settled so you land exactly where you left off
        const quick = R.quickRestore; R.quickRestore = false;  // re-laying out an open book: fonts and images are already loaded
        for (let pass = 0; pass < 2; pass++) {
          const docs = (R.rendition.getContents() || []).map((c) => c.document).filter(Boolean);
          await Promise.all(docs.map((d) => (d.fonts && d.fonts.ready) || null));
          await Promise.all(docs.flatMap((d) => [...d.images].filter((im) => !im.complete).map((im) => new Promise((res) => { im.onload = im.onerror = res; setTimeout(res, 1500); }))));
          await new Promise((res) => setTimeout(res, quick ? 30 : 150));
          if (!R.rendition) break;
          await R.rendition.display(R.startCfi);
        }
      }
    } finally {
      setTimeout(() => {
        R.restoring = false;
        try { const l = R.rendition && R.rendition.currentLocation(); if (l && l.start) { R.loc = l; $("#rPos").textContent = chapterLabel(); bookChrome(l); } } catch (e) {}
      }, 400);
      bookOpen();
    }
    if (m === "scroll" && R.rendition.manager) R.rendition.manager.trim = () => Promise.resolve();
    R.lastWidth = doc().clientWidth;
    for (const a of R.anns) addEpubHighlight(a);
    if (!$("#tocPanel").hidden) buildToc();
  }

  async function rebuildEpub() {
    if (!R.book) return;
    try { R.rendition && R.rendition.destroy(); } catch (e) {}
    await buildEpub();
  }

  function epubPinAt(contents, e) {
    const d = contents.document;
    let range = d.caretRangeFromPoint ? d.caretRangeFromPoint(e.clientX, e.clientY) : null;
    if (!range && d.caretPositionFromPoint) {
      const pos = d.caretPositionFromPoint(e.clientX, e.clientY);
      if (pos) { range = d.createRange(); range.setStart(pos.offsetNode, pos.offset); }
    }
    if (!range) return;
    const node = range.startContainer;
    if (node.nodeType === 3 && range.startOffset < node.length) range.setEnd(node, range.startOffset + 1);
    let cfi;
    try { cfi = contents.cfiFromRange(range, "ink-pin"); } catch (err) { return; }
    createAnn({ locator: { type: "pin", cfi, label: chapterLabel() } });
  }

  function drawEpubPins(contents) {
    const list = contents ? [contents] : (R.rendition?.getContents() || []);
    for (const c of list) {
      const d = c.document;
      if (!d || !d.body) continue;
      d.querySelectorAll(".ink-pin").forEach((n) => n.remove());
      d.body.classList.toggle("ink-pin-mode", R.pinMode);
      if (getComputedStyle(d.body).position === "static") d.body.style.position = "relative";
      for (const a of R.anns.filter((x) => isPin(x) && x.locator.cfi)) {
        let range;
        try { range = c.range(a.locator.cfi, "ink-pin"); } catch (e) { continue; }
        if (!range) continue;
        const r = range.getBoundingClientRect();
        if (!r || (!r.width && !r.height && !r.left)) continue;
        const b = d.body.getBoundingClientRect();
        const pin = d.createElement("div");
        pin.className = "ink-pin" + (a.id === R.activeId ? " active" : "");
        pin.dataset.ann = a.id;
        pin.style.left = (r.left - b.left) + "px";
        pin.style.top = (r.top - b.top) + "px";
        pin.style.background = hlColor(a.color);
        pin.title = a.title || a.note || "Pin";
        pin.innerHTML = `<span>${pinNumber(a)}</span>`;
        d.body.append(pin);
      }
    }
  }

  function chapterLabel() {
    try {
      const href = R.rendition.currentLocation()?.start?.href;
      const flat = (items) => items.flatMap((i) => [i, ...flat(i.subitems || [])]);
      const hit = flat(R.book.navigation?.toc || []).find((t) => href && t.href.split("#")[0].endsWith(href.split("/").pop()));
      return hit ? hit.label.trim() : "";
    } catch (e) { return ""; }
  }

  function applyEpubTheme() {
    if (!R.rendition) return;
    // every book reads on the same cream paper, set in a book face (like the journal)
    const t = { bg: "#f4efe2", ink: "#2d2a26", font: "'Libre Baskerville', Georgia, serif" };
    R.rendition.themes.register("ink", { body: { background: t.bg + " !important", color: t.ink + " !important", "font-family": t.font + " !important", "line-height": "1.65", padding: "0 12px !important" }, "a": { color: "inherit" }, "img": { "max-width": "100% !important" }, "::selection": { background: "rgba(120,160,255,.35)" } });
    R.rendition.themes.select("ink");
    R.rendition.themes.fontSize(pref("font", "epub", 105) + "%");
    const f = document.getElementById("epubView");
    if (f) f.style.background = t.bg;
  }

  function addEpubHighlight(a) {
    if (!R.rendition || !a.locator.cfi || isPin(a) || isBm(a)) return;
    try { R.rendition.annotations.remove(a.locator.cfi, "highlight"); } catch (e) {}
    R.rendition.annotations.highlight(a.locator.cfi, { id: a.id }, () => activate(a.id, true), "ink-hl", { fill: hlColor(a.color), "fill-opacity": a.id === R.activeId ? "0.6" : "0.4", "mix-blend-mode": "multiply" });
  }

  /* ---------- Comics (CBZ / CBR) ---------- */
  async function openComic(item) {
    R.comic = await Comic.open(item.id);
    if (!R.comic.count) throw new Error("No pages were found in this archive.");
    R.page = Math.min(R.comic.count - 1, Math.max(0, (parseInt(item.last_location) || 1) - 1));
    R.startFrac = parseFloat(String(item.last_location || "").split(":")[1]) || 0;
    R.rtl = item.direction === "rtl";
    updateComicButtons();
    renderComic();
    if (!R.anns.length) toast("Click anywhere on a page to pin a note there.");
  }

  function comicPages() {
    const p = R.page, n = R.comic.count;
    if (mode() !== "double" || p === 0) return [p];
    const start = p % 2 === 1 ? p : p - 1;
    return start + 1 < n ? [start, start + 1] : [start];
  }

  function pageEl(i) {
    return `<div class="comic-page" data-page="${i + 1}"><img alt="Page ${i + 1}" draggable="false"><div class="pin-layer"></div><button class="page-zoom" title="View this page full screen" data-zoom-comic="${i}">⤢</button></div>`;
  }

  async function renderComic() {
    if (!R.comic) return;
    R.observer && R.observer.disconnect();
    doc().onscroll = null;
    const m = mode();
    const maxW = Math.round((innerW() - 40) * width() / 100);
    doc().classList.toggle("paged", m !== "scroll");
    if (m === "scroll") {
      doc().innerHTML = `<div class="comic-strip" style="max-width:${maxW}px">${Array.from({ length: R.comic.count }, (_, i) => pageEl(i)).join("")}</div>`;
      R.observer = new IntersectionObserver((entries) => {
        for (const en of entries) if (en.isIntersecting) loadComicPage(en.target);
      }, { root: doc(), rootMargin: "1200px 0px" });
      $$(".comic-page", doc()).forEach((el) => R.observer.observe(el));
      R.comicRestoring = true;
      const settle = () => {
        const el = doc().querySelector(`.comic-page[data-page="${R.page + 1}"]`);
        if (el) doc().scrollTop = el.offsetTop + (R.startFrac || 0) * el.offsetHeight;
      };
      requestAnimationFrame(() => {
        settle();
        // pages above get their real height as their images load; keep the spot steady while that happens
        const until = Date.now() + 2500;
        const keep = setInterval(() => { if (Date.now() > until || !R.comic) { clearInterval(keep); R.comicRestoring = false; R.startFrac = 0; return; } settle(); }, 200);
        doc().addEventListener("wheel", () => { clearInterval(keep); R.comicRestoring = false; R.startFrac = 0; }, { once: true, passive: true });
      });
      doc().onscroll = () => {
        if (R.comicRestoring) return;
        const mid = doc().scrollTop + doc().clientHeight / 2;
        let cur = 0, topPg = 0;
        for (const el of $$(".comic-page", doc())) {
          if (el.offsetTop <= doc().scrollTop + 2) topPg = Number(el.dataset.page) - 1;
          if (el.offsetTop <= mid) cur = Number(el.dataset.page) - 1; else break;
        }
        const tEl = doc().querySelector(`.comic-page[data-page="${topPg + 1}"]`);
        const frac = tEl ? Math.max(0, Math.min(0.99, (doc().scrollTop - tEl.offsetTop) / tEl.offsetHeight)) : 0;
        if (cur !== R.page) { R.page = cur; markTocCurrent(); }
        $("#rPos").textContent = `${cur + 1} / ${R.comic.count}`;
        saveProgress(`${topPg + 1}:${frac.toFixed(3)}`, R.comic.count > 1 ? cur / (R.comic.count - 1) : 1);
      };
      return;
    }
    const pages = comicPages();
    R.page = pages[0];
    const shown = R.rtl ? [...pages].reverse() : pages;
    doc().innerHTML = `<div class="comic-stage" style="--maxw:${Math.floor(maxW / shown.length)}px">${shown.map(pageEl).join("")}</div>`;
    for (const el of $$(".comic-page", doc())) await loadComicPage(el);
    const last = pages[pages.length - 1];
    $("#rPos").textContent = `${pages.map((i) => i + 1).join("–")} / ${R.comic.count}`;
    saveProgress(R.page + 1, R.comic.count > 1 ? last / (R.comic.count - 1) : 1);
    for (let k = 1; k <= 2; k++) if (last + k < R.comic.count) R.comic.url(last + k);
  }

  async function loadComicPage(el) {
    if (el.dataset.loaded) return;
    el.dataset.loaded = "1";
    const i = Number(el.dataset.page) - 1;
    el.querySelector("img").src = await R.comic.url(i);
    drawPins(el.querySelector(".pin-layer"), i + 1);
  }

  function comicStep(dir) {
    if (mode() === "scroll") {
      const target = Math.max(0, Math.min(R.comic.count - 1, R.page + dir));
      doc().querySelector(`.comic-page[data-page="${target + 1}"]`)?.scrollIntoView({ behavior: "smooth" });
      return;
    }
    const pages = comicPages();
    if (dir > 0) R.page = Math.min(R.comic.count - 1, pages[pages.length - 1] + 1);
    else R.page = Math.max(0, pages[0] - (mode() === "double" && pages[0] > 1 ? 2 : 1));
    renderComic();
  }

  function updateComicButtons() {
    $("#rDir").textContent = R.rtl ? "Right to left" : "Left to right";
    $("#rDir").title = "Reading direction (manga usually reads right to left)";
  }

  /* ---------- Video ---------- */
  function openVideo(item) {
    doc().classList.remove("paged");
    const start = parseFloat(item.last_location) || 0;
    const skip = (s) => `<button class="v-skip" data-vskip="${s}" title="${s < 0 ? "Back" : "Forward"} ${Math.abs(s)} seconds">${s < 0 ? `↺ ${-s}` : `${s} ↻`}</button>`;
    doc().innerHTML = `<div class="video-wrap"><div class="v-box"><video id="vid" controls autoplay preload="metadata" src="/api/items/${item.id}/file"></video><span class="v-flash" id="vFlash"></span></div>
      <div class="v-skips">${[-30, -15, -5].map(skip).join("")}<span class="v-gap"></span>${[5, 15, 30].map(skip).join("")}</div>
      ${item.summary ? `<p class="video-syn">${esc(item.summary)}</p>` : ""}</div>`;
    const v = $("#vid");
    // skipping: the buttons, or ← → (5 s) and Shift+← → (30 s); a little badge shows how far
    const jump = (s) => {
      if (!v.duration) return;
      v.currentTime = Math.max(0, Math.min(v.duration - 0.5, v.currentTime + s));
      const f = $("#vFlash");
      f.textContent = (s > 0 ? "+" : "−") + Math.abs(s) + " s";
      f.className = "v-flash on " + (s > 0 ? "r" : "l");
      clearTimeout(jump.t); jump.t = setTimeout(() => (f.className = "v-flash"), 600);
    };
    doc().querySelector(".v-skips").onclick = (e) => { const b = e.target.closest("[data-vskip]"); if (b) jump(Number(b.dataset.vskip)); };
    R.videoJump = jump;
    v.addEventListener("loadedmetadata", () => { if (start > 5 && start < v.duration - 10) v.currentTime = start; });
    v.addEventListener("play", () => Player.pause());
    v.addEventListener("timeupdate", () => {
      $("#rPos").textContent = `${R.vidPrefix || ""}${Media.fmtTime(v.currentTime)} / ${Media.fmtTime(v.duration)}`;
      if (!v.duration) return;
      if (Math.abs((R._lastSave || 0) - v.currentTime) > 10) { R._lastSave = v.currentTime; saveProgress(v.currentTime.toFixed(0), v.currentTime / v.duration); }
    });
    v.addEventListener("error", () => {
      doc().querySelector(".video-wrap").insertAdjacentHTML("beforeend", `<p class="hint">This video's format can't be played inside Babel's Library. <button class="btn sm" data-action="reveal-item" data-id="${item.id}">Show the file</button> to open it in your video player.</p>`);
    });
    setupTracks(item, v);
    if (item.kind === "tv") $("#readerTitle").textContent = [item.series, `S${item.season || 1}E${item.episode ?? "?"}`, item.title].filter(Boolean).join(" · ");
    const sib = videoSiblings(item);
    const nx = sib[sib.findIndex((x) => x.id === item.id) + 1];
    R.vidPrefix = sib.length ? `${sib.findIndex((x) => x.id === item.id) + 1} of ${sib.length} · ` : "";
    R._lastSave = 0;
    v.addEventListener("ended", () => {
      saveProgress(v.duration.toFixed(0), 1);
      if (!nx) return;
      const box = document.createElement("div");
      box.className = "up-next";
      let n = 8;
      box.innerHTML = `<span>Up next</span><b>${esc((nx.kind === "tv" ? epLabel(nx) + " · " : "") + nx.title)}</b><span class="un-c">Playing in ${n}s</span>
        <span class="row"><button class="btn primary sm" data-un="go">Play now</button><button class="btn sm" data-un="stop">Cancel</button></span>`;
      doc().querySelector(".video-wrap").append(box);
      const t = setInterval(() => { n--; box.querySelector(".un-c").textContent = `Playing in ${n}s`; if (n <= 0) { clearInterval(t); if (R.item === item) open(nx); } }, 1000);
      box.onclick = (e) => { const b = e.target.closest("[data-un]"); if (!b) return; clearInterval(t); if (b.dataset.un === "go") open(nx); else box.remove(); };
    });
  }

  /* audio language + subtitles. Preference is remembered per show (or per movie). */
  const trackKey = (item) => "inkwell-tracks:" + (item.series ? "s:" + item.series.toLowerCase() : "i:" + item.id);
  const trackPref = (item) => { try { return JSON.parse(localStorage.getItem(trackKey(item)) || "{}"); } catch (e) { return {}; } };
  const saveTrackPref = (item, p) => { try { localStorage.setItem(trackKey(item), JSON.stringify({ ...trackPref(item), ...p })); } catch (e) {} };

  async function setupTracks(item, v) {
    let info = { audio: [], subtitles: [] };
    try { info = await api.get(`/api/items/${item.id}/tracks`); } catch (e) {}
    if (R.item !== item) return;
    const subsList = info.subtitles.filter((t) => t.supported);
    subsList.forEach((t) => {
      const tr = document.createElement("track");
      tr.kind = "subtitles"; tr.label = t.label; tr.srclang = (t.lang || "und").slice(0, 3); tr.src = `/api/items/${item.id}/subs/${t.id}.vtt`;
      tr.dataset.sid = t.id;
      v.appendChild(tr);
    });
    const pref = trackPref(item);
    const hasAudioApi = !!v.audioTracks;
    const bar = document.createElement("div");
    bar.className = "video-bar";
    const audioOpts = () => {
      if (hasAudioApi && v.audioTracks.length > 1) {
        return Array.from(v.audioTracks).map((t, i) => {
          const named = info.audio[i];
          return `<option value="${i}" ${t.enabled ? "selected" : ""}>${esc(named?.label || t.label || t.language || "Track " + (i + 1))}</option>`;
        }).join("");
      }
      return "";
    };
    const subOpts = `<option value="off">Off</option>` + subsList.map((t) => `<option value="${t.id}">${esc(t.label)}</option>`).join("");
    bar.innerHTML = `<label class="vb-field"><span>Audio</span><select id="vAudio"></select></label>
      <label class="vb-field"><span>Subtitles</span><select id="vSubs">${subOpts}</select></label>
      <span class="vb-note" id="vNote"></span>`;
    v.parentElement.insertBefore(bar, v.nextSibling);
    const fillAudio = () => {
      const opts = audioOpts();
      const sel = $("#vAudio");
      if (opts) { sel.innerHTML = opts; sel.disabled = false; $("#vNote").textContent = ""; }
      else if (info.audio.length > 1) {
        sel.innerHTML = info.audio.map((a, i) => `<option value="${i}" ${a.default ? "selected" : ""}>${esc(a.label)}</option>`).join("");
        sel.disabled = true;
        $("#vNote").textContent = "Restart Babel's Library from its shortcut to switch audio languages.";
      } else { sel.innerHTML = `<option>${esc(info.audio[0]?.label || "Default")}</option>`; sel.disabled = true; }
    };
    const pickAudio = (i) => {
      if (!hasAudioApi) return;
      const t = v.currentTime;
      Array.from(v.audioTracks).forEach((a, j) => { a.enabled = j === i; });
      if (t) v.currentTime = t;  // nudge the decoder so the switch is immediate
    };
    const pickSub = (sid) => {
      Array.from(v.textTracks).forEach((tt, j) => {
        const el = v.querySelectorAll("track")[j];
        tt.mode = el && el.dataset.sid === sid ? "showing" : "disabled";
      });
    };
    const applyPref = () => {
      fillAudio();
      if (hasAudioApi && v.audioTracks.length > 1 && pref.audioLang) {
        const idx = info.audio.findIndex((a) => a.lang === pref.audioLang && (!pref.audioLabel || a.label === pref.audioLabel));
        const i = idx >= 0 ? idx : info.audio.findIndex((a) => a.lang === pref.audioLang);
        if (i >= 0 && i < v.audioTracks.length) { pickAudio(i); $("#vAudio").value = String(i); }
      }
    };
    v.addEventListener("loadedmetadata", applyPref);
    if (v.readyState >= 1) applyPref();
    if (hasAudioApi) { v.audioTracks.onaddtrack = fillAudio; }
    // subtitles: saved choice, else a default/forced track flagged in the file
    let want = "off";
    if (pref.subLang === "off") want = "off";
    else if (pref.subLang) want = (subsList.find((t) => t.lang === pref.subLang && t.label === pref.subLabel) || subsList.find((t) => t.lang === pref.subLang) || {}).id || "off";
    else want = (subsList.find((t) => t.default) || {}).id || "off";
    $("#vSubs").value = want;
    setTimeout(() => pickSub(want), 0);
    $("#vAudio").onchange = (e) => {
      const i = Number(e.target.value);
      pickAudio(i);
      saveTrackPref(item, { audioLang: info.audio[i]?.lang || null, audioLabel: info.audio[i]?.label || null });
    };
    $("#vSubs").onchange = (e) => {
      const sid = e.target.value;
      pickSub(sid);
      const t = subsList.find((x) => x.id === sid);
      saveTrackPref(item, { subLang: t ? t.lang : "off", subLabel: t ? t.label : null });
    };
    const unsupported = info.subtitles.filter((t) => !t.supported).length;
    if (unsupported && !subsList.length) $("#vNote").textContent = "This file's subtitles are pictures (PGS/VobSub), which Babel's Library can't show yet.";
  }

  /* ---------- immersive reading ---------- */
  function setImmersive(on) {
    $("#reader").classList.toggle("immersive", on);
    $("#reader").classList.remove("peek");
    document.body.classList.toggle("reader-immersive", on);
    document.body.classList.remove("peek-player");
    if (on && !R._immHint) { R._immHint = true; toast("Toolbar hidden. Move the mouse to the top edge to bring it back, or press H / Esc."); }
    setTimeout(relayout, 260);
  }

  /* ---------- audiobook: play from here, and highlight the sentence being read ---------- */
  async function abManifest() {
    if (R.abm && R.abm.item === R.item.id) return R.abm;
    try { R.abm = await api.get(`/api/items/${R.item.id}/audiobook`); } catch (e) { R.abm = null; }
    return R.abm;
  }
  const normT = (s) => (s || "").replace(/[\u00ad\u200b]/g, "").replace(/\s+/g, " ").trim();
  async function listenHere() {
    const m = await abManifest();
    if (!m) return toast("This book has no audiobook yet.", "error");
    const np = Player.nowPlaying();
    if (np.track && np.track.ab === R.item.id) { Player.toggle(); return; }
    // start at the chapter you're reading
    let ch = 0;
    if (R.kind === "epub") {
      const href = currentHref().split("/").pop();
      const i = m.chapters.findIndex((c) => c.sentences.some((s) => (s.href || "").split("/").pop() === href));
      ch = Math.max(0, i);
    } else if (R.kind === "pdf") {
      const pg = R.curPage || 1;
      m.chapters.forEach((c, i) => { if ((c.page || 1) <= pg) ch = i; });
    }
    Player.playAudiobook(R.item.id, { ch, t: 0 });
    R.abFollowPause = 0;
  }
  function abTick() {
    if (!R.item || !(R.kind === "epub" || R.kind === "pdf")) return;
    const np = Player.nowPlaying();
    const t = np.track;
    const mine = t && t.ab === R.item.id;
    $("#rListen").textContent = mine && np.playing ? "❚❚ Pause" : "🎧 Listen";
    if (!mine) { if (R.abLast) clearAbHighlight(); return; }
    abManifest().then((m) => {
      if (!m) return;
      const ch = m.chapters[t.ch];
      if (!ch) return;
      const k = ch.sentences.findIndex((s) => np.time >= s.t0 - 0.05 && np.time < s.t1 + 0.25);
      if (k < 0) return;
      const key = t.ch + ":" + k;
      if (key === R.abLast) return;
      R.abLast = key;
      showAbSentence(ch.sentences[k], t.ch, k);
    });
  }
  function clearAbHighlight() {
    R.abLast = null;
    if (R.abCfi && R.rendition) { try { R.rendition.annotations.remove(R.abCfi, "highlight"); } catch (e) {} }
    R.abCfi = null;
    $$(".tts-layer", doc()).forEach((l) => (l.innerHTML = ""));
  }
  // map a sentence to a DOM Range inside a document (whitespace-insensitive search)
  function findTextRange(rootEl, text, fromNode) {
    const want = normT(text);
    if (!want) return null;
    const walker = rootEl.ownerDocument.createTreeWalker(rootEl, NodeFilter.SHOW_TEXT);
    const nodes = [];
    let flat = "", map = [];
    let lastSpace = true;
    for (let n = walker.nextNode(); n; n = walker.nextNode()) {
      if (n.parentElement && n.parentElement.closest("script,style,.ink-pin,sup")) continue;
      const v = n.nodeValue;
      for (let i = 0; i < v.length; i++) {
        let ch = v[i];
        if (ch === "\u00ad" || ch === "\u200b") continue;
        if (/\s/.test(ch)) { if (lastSpace) continue; ch = " "; lastSpace = true; } else lastSpace = false;
        flat += ch; map.push([n, i]);
      }
      nodes.push(n);
    }
    let at = flat.indexOf(want);
    let len = want.length;
    if (at < 0) { const head = want.slice(0, 48); at = flat.indexOf(head); len = Math.min(want.length, flat.length - at); }
    if (at < 0) return null;
    const a = map[at], b = map[Math.min(map.length - 1, at + len - 1)];
    const range = rootEl.ownerDocument.createRange();
    range.setStart(a[0], a[1]);
    range.setEnd(b[0], b[1] + 1);
    return range;
  }
  async function showAbSentence(s, chIndex, k) {
    const follow = Date.now() > (R.abFollowPause || 0);
    if (R.kind === "epub" && R.rendition) {
      const href = (s.href || "").split("/").pop();
      let contents = R.rendition.getContents().find((c) => (R.book.spine.get(c.sectionIndex)?.href || "").split("/").pop() === href);
      if (!contents) {
        if (!follow) return;
        const sec = R.book.spine.spineItems.find((x) => x.href.split("/").pop() === href);
        if (!sec) return;
        R._abNav = true;
        await R.rendition.display(sec.href);
        R._abNav = false;
        R.abLast = null;  // try again once the chapter is on screen
        return;
      }
      const range = findTextRange(contents.document.body, s.text);
      if (!range) return;
      let cfi;
      try { cfi = contents.cfiFromRange(range); } catch (e) { return; }
      if (R.abCfi) { try { R.rendition.annotations.remove(R.abCfi, "highlight"); } catch (e) {} }
      R.abCfi = cfi;
      R.rendition.annotations.highlight(cfi, {}, null, "tts-hl", { fill: "rgb(255, 210, 64)", "fill-opacity": "0.45", "mix-blend-mode": "multiply" });
      if (follow) {
        const loc = R.rendition.currentLocation();
        let visible = true;
        try {
          const C = new ePub.CFI();
          visible = loc && loc.start && C.compare(cfi, loc.start.cfi) >= 0 && C.compare(cfi, loc.end.cfi) <= 0;
        } catch (e) {}
        if (mode() === "scroll") {
          const r = range.getBoundingClientRect();
          const fr = contents.document.defaultView.frameElement.getBoundingClientRect();
          const box = doc().querySelector(".epub-container")?.getBoundingClientRect() || doc().getBoundingClientRect();
          const top = fr.top + r.top;
          visible = top > box.top + 30 && top + r.height < box.bottom - 40;
          if (!visible) { const cont = doc().querySelector(".epub-container"); if (cont) { R._abNav = true; cont.scrollBy({ top: top - box.top - box.height * 0.3, behavior: "smooth" }); setTimeout(() => (R._abNav = false), 800); } }
        } else if (!visible) { R._abNav = true; await R.rendition.display(cfi); R._abNav = false; }
      }
    } else if (R.kind === "pdf") {
      const pg = s.page || 1;
      let p = R.pages[pg - 1];
      if ((!p || !p.el.isConnected || !p.el.querySelector(".textLayer span")) && follow) {
        R._abNav = true; goToPage(pg); R._abNav = false;
        R.abLast = null;
        return;
      }
      if (!p) return;
      const tl = p.el.querySelector(".textLayer");
      if (!tl) { R.abLast = null; return; }
      const range = findTextRange(tl, s.text);
      let layer = p.el.querySelector(".tts-layer");
      $$(".tts-layer", doc()).forEach((l) => (l.innerHTML = ""));
      if (!range) return;
      if (!layer) { layer = document.createElement("div"); layer.className = "tts-layer"; p.el.append(layer); }
      const base = p.el.getBoundingClientRect();
      layer.innerHTML = [...range.getClientRects()].filter((r) => r.width > 1).map((r) =>
        `<i style="left:${r.left - base.left}px;top:${r.top - base.top}px;width:${r.width}px;height:${r.height}px"></i>`).join("");
      if (follow && mode() === "scroll") {
        const first = range.getBoundingClientRect(), box = doc().getBoundingClientRect();
        if (first.top < box.top + 30 || first.bottom > box.bottom - 40) doc().scrollBy({ top: first.top - box.top - box.height * 0.3, behavior: "smooth" });
      }
    }
  }
  setInterval(abTick, 400);
  // if you turn pages or scroll yourself, stop following the audio for a while
  const pauseFollow = () => { if (!R._abNav) R.abFollowPause = Date.now() + 12000; };

  /* ---------- table of contents ---------- */
  const skey = (n) => (n || "").toLowerCase().replace(/\((?:19|20)\d\d\)|\b(?:19|20)\d\d\b/g, " ").replace(/[^a-z0-9]+/g, "");
  function videoSiblings(item) {
    let list = [];
    if (S.coll && (item.collections || []).includes(S.coll)) list = S.items.filter((i) => VIDEO_KINDS.includes(i.kind) && (i.collections || []).includes(S.coll));
    else if (item.kind === "tv") list = S.items.filter((i) => i.kind === "tv" && skey(i.series) === skey(item.series));
    else if (item.series) list = S.items.filter((i) => i.kind === "movie" && i.series === item.series);
    list = list.filter((i) => i.has_file).sort((a, b) => skey(a.series).localeCompare(skey(b.series)) || (a.season || 0) - (b.season || 0) ||
      (a.episode ?? 1e9) - (b.episode ?? 1e9) || (a.series_index || 0) - (b.series_index || 0) || (parseInt(a.year) || 0) - (parseInt(b.year) || 0) || (a.title || "").localeCompare(b.title || ""));
    return list.length > 1 ? list : [];
  }
  const epLabel = (e) => e.kind === "tv" ? `S${e.season || 1} · E${e.episode ?? "?"}` : (e.year || "");
  function playSibling(dir) {
    const list = videoSiblings(R.item);
    const i = list.findIndex((x) => x.id === R.item.id);
    const nx = list[i + dir];
    if (nx) open(nx); else toast(dir > 0 ? "That's the last one." : "That's the first one.");
  }

  function currentHref() {
    try { return (R.rendition.currentLocation()?.start?.href || "").split("#")[0]; } catch (e) { return ""; }
  }
  function markTocCurrent() {
    try { paintMarks(); } catch (e) {}
    const box = $("#tocList");
    if ($("#tocPanel").hidden || !box) return;
    let on = null;
    if (R.kind === "epub") {
      const href = currentHref().split("/").pop();
      for (const b of $$("[data-toc-href]", box)) if (href && b.dataset.tocHref.split("#")[0].split("/").pop() === href) { on = on || b; }
    } else if (R.kind === "pdf" || R.kind === "comic") {
      const cur = R.kind === "pdf" ? R.curPage || 1 : (R.page || 0) + 1;
      for (const b of $$("[data-toc-page]", box)) if (Number(b.dataset.tocPage) <= cur) on = b;
    } else on = box.querySelector(`[data-toc-item="${R.item.id}"]`);
    $$(".toc-row.on", box).forEach((b) => b.classList.remove("on"));
    if (on) { on.classList.add("on"); if (!box.matches(":hover")) on.scrollIntoView({ block: "nearest" }); }
  }

  async function buildToc() {
    const box = $("#tocList");
    const item = R.item;
    if (!item) return;
    $("#tocJump").hidden = !(R.kind === "pdf" || R.kind === "comic");
    $("#tocTitle").textContent = R.kind === "video" ? (item.kind === "tv" ? item.series || "Episodes" : S.coll ? "Collection" : "Films") : "Contents";
    box.innerHTML = `<p class="hint">Loading…</p>`;
    let html = "";
    if (R.kind === "epub") {
      try { await R.book.loaded.navigation; } catch (e) {}
      const toc = R.book.navigation?.toc || [];
      const row = (t, d) => `<li><button class="toc-row" data-toc-href="${esc(t.href)}" style="--d:${d}">${esc((t.label || "").trim() || "Untitled section")}</button>${t.subitems && t.subitems.length ? `<ol>${t.subitems.map((x) => row(x, d + 1)).join("")}</ol>` : ""}</li>`;
      html = toc.length ? `<ol class="toc-tree">${toc.map((t) => row(t, 0)).join("")}</ol>`
        : `<ol class="toc-tree">${R.book.spine.spineItems.filter((x) => x.linear !== "no").map((x, i) => `<li><button class="toc-row" data-toc-href="${esc(x.href)}">Section ${i + 1}</button></li>`).join("")}</ol>`;
    } else if (R.kind === "pdf") {
      let outline = null;
      try { outline = await R.pdf.getOutline(); } catch (e) {}
      R.tocDest = [];
      const row = (o, d) => { const k = R.tocDest.push(o.dest) - 1; return `<li><button class="toc-row" data-toc-dest="${k}" style="--d:${d}">${esc((o.title || "").trim() || "Untitled")}</button>${o.items && o.items.length ? `<ol>${o.items.map((x) => row(x, d + 1)).join("")}</ol>` : ""}</li>`; };
      html = outline && outline.length ? `<ol class="toc-tree">${outline.map((o) => row(o, 0)).join("")}</ol>` : "";
      html += `<h4 class="toc-sub">Pages</h4><div class="toc-pages">${Array.from({ length: R.pdf.numPages }, (_, i) => `<button class="toc-row pg" data-toc-page="${i + 1}">${i + 1}</button>`).join("")}</div>`;
      // resolve outline entries to page numbers in the background so the current section can be highlighted
      R.tocDest.forEach(async (dest, k) => {
        try {
          const d = typeof dest === "string" ? await R.pdf.getDestination(dest) : dest;
          const n = (await R.pdf.getPageIndex(d[0])) + 1;
          const b = box.querySelector(`[data-toc-dest="${k}"]`);
          if (b) { b.dataset.tocPage = n; b.insertAdjacentHTML("beforeend", `<span class="toc-pn">${n}</span>`); }
        } catch (e) {}
      });
    } else if (R.kind === "comic") {
      html = `<div class="toc-pages">${Array.from({ length: R.comic.count }, (_, i) => `<button class="toc-row pg" data-toc-page="${i + 1}">${i + 1}</button>`).join("")}</div>`;
    } else {
      const list = videoSiblings(item);
      html = list.length ? `<ol class="toc-eps">${list.map((e) => `<li><button class="toc-row ep ${e.watched ? "done" : ""}" data-toc-item="${e.id}">
          <span class="ep-code">${esc(epLabel(e))}</span><span class="ep-t">${esc(e.kind === "tv" ? e.title : e.title)}</span>${e.watched ? `<span class="ep-w">✓</span>` : e.progress > 0.02 ? `<span class="ep-p">${Math.round(e.progress * 100)}%</span>` : ""}</button></li>`).join("")}</ol>`
        : `<p class="hint">This isn't part of a show, film series or open collection.</p>`;
    }
    box.innerHTML = html;
    if (R.kind === "pdf" || R.kind === "comic") $("#tocPage").max = R.kind === "pdf" ? R.pdf.numPages : R.comic.count;
    markTocCurrent();
  }

  function goToPage(n) {
    if (R.kind === "pdf") {
      n = Math.max(1, Math.min(R.pdf.numPages, n));
      if (mode() === "scroll") R.pages[n - 1]?.el.scrollIntoView(); else showPdfSpread(n);
    } else if (R.kind === "comic") {
      n = Math.max(1, Math.min(R.comic.count, n));
      if (mode() === "scroll") doc().querySelector(`.comic-page[data-page="${n}"]`)?.scrollIntoView();
      else { R.page = n - 1; renderComic(); }
    }
    setTimeout(markTocCurrent, 300);
  }

  function toggleToc(show) {
    const p = $("#tocPanel");
    p.hidden = show === undefined ? !p.hidden : !show;
    $("#rToc").classList.toggle("on", !p.hidden);
    try { localStorage.setItem("inkwell-toc-open", p.hidden ? "0" : "1"); } catch (e) {}
    if (!p.hidden) buildToc();
  }

  /* ---------- the book around the pages: running heads, page numbers, chapter tabs, turning leaves ---------- */
  function bookChrome(loc) {
    const ch = $("#bkChap");
    if (!ch) return;
    ch.textContent = chapterLabel() || "";
    const a = loc?.start?.displayed, b = loc?.end?.displayed;
    $("#bkPgL").textContent = a ? a.page : "";
    $("#bkPgR").textContent = mode() === "double" && b && b.page !== a?.page ? b.page : "";
    paintMarks();
  }
  /* ---------- bookmarks: a coloured tab stuck to the edge of a page ---------- */
  const bookmarks = () => sortAnns().filter(isBm);
  function onPage(a) {
    const loc = a.locator || {};
    if (R.kind === "epub") {
      const l = R.loc || R.rendition?.currentLocation();
      if (!l || !l.start || !loc.cfi) return false;
      try {
        const c = new ePub.CFI();
        return c.compare(loc.cfi, l.start.cfi) >= 0 && c.compare(loc.cfi, l.end.cfi) <= 0;
      } catch (e) { return loc.cfi === l.start.cfi; }
    }
    if (R.kind === "pdf") {
      if (mode() === "scroll") return loc.page === R.curPage;
      return spreadFor(R.curPage || 1, R.pdf.numPages, mode() === "double").includes(loc.page);
    }
    if (R.kind === "comic") return loc.page === (R.page || 0) + 1;
    return false;
  }
  function paintMarks() {
    const here = bookmarks().filter(onPage);
    const btn = $("#rMark");
    if (btn) { btn.classList.toggle("on", here.length > 0); btn.setAttribute("aria-pressed", here.length ? "true" : "false"); btn.title = here.length ? "Remove the bookmark on this page (B)" : "Bookmark this page (B)"; }
    let box = $("#bkMarks");
    const host = doc().querySelector(".pdf-spread");
    if (!box && host) { box = document.createElement("div"); box.className = "rb-marks"; box.id = "bkMarks"; host.append(box); }
    if (!box) return;
    const all = bookmarks();
    const wrap = box.parentElement;
    wrap.querySelectorAll(".rb-flag").forEach((f) => f.remove());
    all.forEach((a, i) => {
      if (!onPage(a)) return;
      const f = document.createElement("i");
      f.className = "rb-flag";
      f.style.cssText = `--bm:${hlColor(a.color)};top:${44 + i * 42}px`;
      wrap.append(f);
    });
    box.innerHTML = all.map((a, i) => {
      const loc = a.locator || {};
      const lab = a.title || (loc.page ? `p. ${loc.page}` : loc.label || "Bookmark");
      return `<button class="rb-mark ${onPage(a) ? "on" : ""}" data-bk-mark="${a.id}" style="--bm:${hlColor(a.color)};--i:${i}" aria-label="${esc(lab)}"><span class="rb-ab">${esc(lab)}</span></button>`;
    }).join("");
  }
  async function toggleBookmark() {
    if (!R.item || R.kind === "video") return;
    const here = bookmarks().filter(onPage);
    if (here.length) {
      for (const a of here) { await api.send("DELETE", `/api/annotations/${a.id}`); R.anns = R.anns.filter((x) => x.id !== a.id); }
      toast("Bookmark removed");
    } else {
      let locator;
      if (R.kind === "epub") { const l = R.loc || R.rendition?.currentLocation(); if (!l?.start) return; locator = { type: "bookmark", cfi: l.start.cfi, label: chapterLabel() }; }
      else if (R.kind === "pdf") locator = { type: "bookmark", page: R.curPage || 1 };
      else if (R.kind === "comic") locator = { type: "bookmark", page: (R.page || 0) + 1 };
      const colors = Object.keys(HL);
      const title = R.kind === "epub" ? (chapterLabel() || "Bookmark") : `p. ${locator.page}`;
      const a = await api.send("POST", `/api/items/${R.item.id}/annotations`, { title, note: "", quote: "", color: colors[bookmarks().length % colors.length], locator });
      R.anns.push(a);
      toast("Page bookmarked");
    }
    renderNotes();
    paintMarks();
  }
  document.addEventListener("click", (e) => {
    const m = e.target.closest?.("[data-bk-mark]");
    if (!m) return;
    const a = R.anns.find((x) => x.id === Number(m.dataset.bkMark));
    e.stopPropagation();
    if (a) { jumpTo(a); setTimeout(paintMarks, 400); }
  });
  /* Page turn, like a real book: a snapshot of the open spread is kept ready (hidden) on top of the pages.
     When you turn, the snapshot shows, the real pages move on underneath, and the snapshot's page lifts and
     swings over the spine, showing the old page on its front and the new page on its back. */
  const reducedMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const bookHost = () => doc().querySelector(".epub-wrap.rbook, .pdf-spread");
  function snapLayer(host, half) {
    const W = host.offsetWidth, H = host.offsetHeight;
    const c = host.cloneNode(true);
    const view = host.querySelector("#epubView"), cView = c.querySelector("#epubView");
    c.querySelectorAll(".rb-marks,.bk-snap,.bk-lid,.rb-flag,.ink-pin").forEach((x) => x.remove());
    c.removeAttribute("id"); c.querySelectorAll("[id]").forEach((x) => x.removeAttribute("id"));
    c.classList.add("bk-clone");
    c.style.cssText += `;position:absolute;left:${half ? -W / 2 : 0}px;top:0;width:${W}px;height:${H}px;margin:0;max-width:none;transform:none;animation:none;box-shadow:none`;
    if (R.kind === "pdf") {
      const src = [...host.querySelectorAll("canvas")], dst = [...c.querySelectorAll("canvas")];
      dst.forEach((d, i) => { const sc = src[i]; if (!sc) return; d.width = sc.width; d.height = sc.height; try { d.getContext("2d").drawImage(sc, 0, 0); } catch (e) {} });
      c.querySelectorAll(".textLayer,.hl,.pin").forEach((x) => x.remove());
      return { el: c, ready: Promise.resolve() };
    }
    const fr = view?.querySelector("iframe"), d = fr?.contentDocument;
    if (!fr || !d || !cView) return { el: c, ready: Promise.resolve() };
    const vr = view.getBoundingClientRect(), r = fr.getBoundingClientRect();
    cView.innerHTML = "";
    cView.style.cssText += `;position:relative;overflow:hidden;width:${view.offsetWidth}px;height:${view.offsetHeight}px;flex:none`;
    const m = document.createElement("iframe");
    m.setAttribute("sandbox", "allow-same-origin");
    m.setAttribute("tabindex", "-1");
    m.style.cssText = `position:absolute;left:${r.left - vr.left}px;top:${r.top - vr.top}px;width:${r.width}px;height:${r.height}px;border:0;pointer-events:none;background:transparent`;
    const ready = new Promise((res) => { m.onload = res; setTimeout(res, 700); });
    // <base> so the page's fonts and pictures load from the same place as in the real page
    // the reader's theme is added as live CSS rules (not text), so copy every rule across too
    let rules = "";
    for (const sh of d.styleSheets) { try { rules += [...sh.cssRules].map((r) => r.cssText).join("\n") + "\n"; } catch (e) {} }
    m.srcdoc = "<!DOCTYPE html>" + d.documentElement.outerHTML
      .replace(/<head([^>]*)>/i, `<head$1><base href="${esc(d.baseURI || location.href)}">`)
      .replace(/<\/head>/i, `<style>${rules.replace(/<\/style/gi, "<\\/style")}</style></head>`);
    cView.append(m);
    return { el: c, ready };
  }
  function placeSnap(snap, host) {
    if (R.kind !== "pdf") { snap.style.cssText = "left:0;top:0;right:0;bottom:0"; host.append(snap); return; }
    const par = host.parentElement;            // a PDF spread is replaced on every turn, so the snapshot sits beside it
    if (getComputedStyle(par).position === "static") par.style.position = "relative";
    snap.style.cssText = `left:${host.offsetLeft}px;top:${host.offsetTop}px;width:${host.offsetWidth}px;height:${host.offsetHeight}px`;
    par.append(snap);
  }
  function prepSnap(delay = 260) {
    clearTimeout(R.snapT);
    if (R.snap && !R.turning) { R.snap.el.remove(); R.snap = null; }
    R.snapT = setTimeout(buildSnap, delay);
  }
  function buildSnap() {
    const host = bookHost();
    if (!host || R.turning || mode() !== "double" || reducedMotion()) return;
    if (R.kind === "pdf" && host.querySelectorAll("canvas").length < host.querySelectorAll(".pdf-page:not(.pdf-blank)").length) return prepSnap(250);
    doc().querySelectorAll(".bk-snap:not(.live)").forEach((x) => x.remove());
    R.snapGen = (R.snapGen || 0) + 1;
    const snap = document.createElement("div");
    snap.className = "bk-snap";
    const waits = [0, 1].map((h) => {
      const half = document.createElement("div");
      half.className = `bk-half ${h ? "r" : "l"}`;
      const L = snapLayer(host, h);
      half.innerHTML = `<div class="bk-pf"></div><div class="bk-pf bk-pb"></div>`;
      half.firstChild.append(L.el);
      snap.append(half);
      return L.ready;
    });
    placeSnap(snap, host);
    const rec = { el: snap, ok: false, w: host.offsetWidth, h: host.offsetHeight };
    R.snap = rec;
    Promise.all(waits).then(() => { rec.ok = true; });
  }
  function turnLeaf(dir, go) {
    const host = bookHost(), s = R.snap;
    const fresh = s && s.ok && s.el.isConnected && host && s.w === host.offsetWidth && s.h === host.offsetHeight;
    if (!host || mode() !== "double" || reducedMotion() || R.turning || !fresh) { go?.(); prepSnap(); return; }
    R.turning = true; R.snap = null;
    const snap = s.el, leaf = snap.querySelector(dir > 0 ? ".bk-half.r" : ".bk-half.l"), back = leaf.querySelector(".bk-pb");
    snap.classList.add("live", dir > 0 ? "fwd" : "back");
    const fillBack = () => {
      const h2 = bookHost();
      if (!h2 || !snap.isConnected) return;
      const L = snapLayer(h2, dir > 0 ? 0 : 1);
      back.append(L.el);
      L.ready.then(() => back.classList.add("ok"));
    };
    if (R.kind === "epub" && R.rendition?.once) R.rendition.once("relocated", () => requestAnimationFrame(() => requestAnimationFrame(fillBack)));
    go?.();
    if (R.kind === "pdf") {
      if (!snap.isConnected) doc().append(snap);       // a new PDF spread replaces the old one: keep the snapshot on top
      const wait = (n) => { const h2 = bookHost(); if (h2 && h2.querySelectorAll("canvas").length >= h2.querySelectorAll(".pdf-page:not(.pdf-blank)").length) fillBack(); else if (n < 12) setTimeout(() => wait(n + 1), 40); };
      wait(0);
    }
    requestAnimationFrame(() => leaf.classList.add("turning"));
    let done = false;
    const end = () => { if (done) return; done = true; snap.remove(); R.turning = false; prepSnap(120); };
    leaf.addEventListener("animationend", (e) => { if (e.target === leaf) end(); });
    setTimeout(end, 1100);
  }
  window.addEventListener("resize", () => prepSnap(400));
  /* opening a book: it's carried in closed, then the cover swings open once the pages are ready */
  function bookIntro() {
    const host = doc().querySelector(".epub-wrap.rbook, .pdf-spread");
    if (!host || R.opened || window.matchMedia("(prefers-reduced-motion: reduce)").matches || innerWidth < 700) { R.opened = true; return; }
    R.opened = true;
    const double = host.classList.contains("double") || host.querySelectorAll(".pdf-page:not(.pdf-blank)").length > 1;
    host.classList.toggle("is-double", double);
    const lid = document.createElement("div");
    lid.className = `bk-lid ${double ? "dbl" : "sgl"}`;
    const by = (R.item?.authors || [])[0] || "";
    lid.innerHTML = `<div class="bk-lid-front"><span class="bk-lid-rule"></span><b>${esc(R.item?.title || "")}</b><span class="bk-lid-rule"></span>${by ? `<em>${esc(by)}</em>` : ""}</div><div class="bk-lid-back"></div>`;
    host.append(lid);
    doc().classList.add("bk-intro");
  }
  function bookOpen() {
    const d = doc();
    if (!d.classList.contains("bk-intro") || d.classList.contains("bk-open")) return;
    setTimeout(() => {
      d.classList.add("bk-open");
      setTimeout(() => { d.querySelectorAll(".bk-lid").forEach((x) => x.remove()); d.classList.remove("bk-intro", "bk-open"); }, 1000);
    }, 380);
  }

  /* ---------- navigation ---------- */
  function goSide(side) {
    pauseFollow();
    if (R.kind === "comic") return comicStep((side === "right") !== R.rtl ? 1 : -1);
    if ((side === "right") !== (R.kind === "pdf" && R.rtl)) next(); else prev();
  }
  function next() {
    if (R.kind === "video") return playSibling(1);
    if (R.kind === "epub") turnLeaf(1, () => R.rendition?.next());
    else if (R.kind === "comic") comicStep(1);
    else if (R.kind === "pdf") {
      if (mode() === "scroll") R.pages[Math.min(R.pages.length - 1, R.curPage || 1)]?.el.scrollIntoView({ behavior: "smooth" });
      else { const s = spreadFor(R.curPage, R.pdf.numPages, mode() === "double"); turnLeaf(R.rtl ? -1 : 1, () => showPdfSpread(s[s.length - 1] + 1)); }
    }
  }
  function prev() {
    if (R.kind === "video") return playSibling(-1);
    if (R.kind === "epub") turnLeaf(-1, () => R.rendition?.prev());
    else if (R.kind === "comic") comicStep(-1);
    else if (R.kind === "pdf") {
      if (mode() === "scroll") R.pages[Math.max(0, (R.curPage || 1) - 2)]?.el.scrollIntoView({ behavior: "smooth" });
      else { const n = R.curPage - (mode() === "double" && R.curPage > 2 ? 2 : 1); turnLeaf(R.rtl ? 1 : -1, () => showPdfSpread(n)); }
    }
  }
  function keyNav(e) {
    if (e.target.matches?.("input,textarea,select")) return;
    if (R.kind === "video") {
      if ((e.key === "ArrowRight" || e.key === "ArrowLeft") && R.videoJump) { e.preventDefault(); R.videoJump((e.key === "ArrowRight" ? 1 : -1) * (e.shiftKey ? 30 : 5)); }
      return;
    }
    if (e.key === "ArrowRight") { e.preventDefault(); goSide("right"); }
    else if (e.key === "ArrowLeft") { e.preventDefault(); goSide("left"); }
    else if ((e.key === "PageDown" || e.key === " ") && mode() !== "scroll") { e.preventDefault(); next(); }
    else if (e.key === "PageUp" && mode() !== "scroll") { e.preventDefault(); prev(); }
    else if (e.key === "Delete" && R.activeId) { e.preventDefault(); deleteAnn(R.activeId); }
  }

  /* ---------- selection popup ---------- */
  function showPop(x, y) {
    const pop = $("#selPop");
    pop.hidden = false;
    const w = pop.offsetWidth || 220;
    pop.style.left = Math.max(8, Math.min(window.innerWidth - w - 8, x - w / 2)) + "px";
    pop.style.top = Math.min(window.innerHeight - 50, y + 10) + "px";
  }
  function hidePop() { $("#selPop").hidden = true; }

  async function createFromPending(color) {
    const p = R.pending;
    if (!p) return;
    hidePop();
    const wantsNote = color === "note";
    R.pending = null;
    if (R.kind === "pdf") window.getSelection().removeAllRanges();
    else { try { p.contents.window.getSelection().removeAllRanges(); } catch (e) {} }
    const a = await createAnn({ quote: p.quote, color: wantsNote ? "yellow" : color, locator: p.locator });
    if (wantsNote) $(`.note[data-id="${a.id}"] .n-title`)?.focus();
  }

  /* ---------- notes panel ---------- */
  function sortAnns() {
    return [...R.anns].sort((a, b) => {
      const la = a.locator || {}, lb = b.locator || {};
      if (R.kind === "pdf" || R.kind === "comic") {
        const pa = la.page || (la.rects || [{}])[0].p || 0, pb = lb.page || (lb.rects || [{}])[0].p || 0;
        const ya = la.y ?? (la.rects || [{}])[0].y ?? 0, yb = lb.y ?? (lb.rects || [{}])[0].y ?? 0;
        return (pa - pb) || (ya - yb) || (a.id - b.id);
      }
      if (la.cfi && lb.cfi) { try { return new ePub.CFI().compare(la.cfi, lb.cfi); } catch (e) {} }
      return (la.cfi ? 1 : 0) - (lb.cfi ? 1 : 0) || a.created_at - b.created_at;
    });
  }

  const TRASH = `<svg viewBox="0 0 24 24" width="15" height="15"><path d="M9 3h6l1 2h4v2H4V5h4zm-3 6h12l-1 12H7z"/></svg>`;
  function renderNotes() {
    $("#noteCount").textContent = R.anns.length ? `(${R.anns.length})` : "";
    $("#notesHint").hidden = R.anns.length > 0;
    $("#notesHint").textContent = R.kind === "comic"
      ? "Click anywhere on a page to pin a note there. Drag pins to move them."
      : "Select text to highlight it, or use Pin to drop a comment anywhere on the page.";
    $("#notesList").innerHTML = sortAnns().map((a) => {
      const loc = a.locator || {};
      const where = loc.page ? `p. ${loc.page}` : (loc.label || "");
      const kind = isPin(a) ? `Pin ${pinNumber(a)}` : isBm(a) ? "🔖 Bookmark" : loc.type === "note" ? "Note" : "";
      return `<li class="note ${isPin(a) ? "is-pin" : ""} ${a.id === R.activeId ? "active" : ""}" data-id="${a.id}" style="--hl:var(${HL[a.color] || HL.yellow})">
        <div class="n-top"><input class="n-title" value="${esc(a.title)}" placeholder="Add a title (optional)" aria-label="Annotation title">
          <button class="icon-btn n-del" data-del title="Delete this annotation (Delete key)" aria-label="Delete">${TRASH}</button></div>
        ${a.quote ? `<blockquote title="Jump to this passage">${esc(a.quote)}</blockquote>` : ""}
        <textarea class="n-note" placeholder="${isPin(a) ? "Write a comment…" : "Write a note…"}" aria-label="Note">${esc(a.note)}</textarea>
        <div class="n-foot"><span>${esc([kind, where].filter(Boolean).join(" · "))}</span>
          <span class="n-colors">${Object.keys(HL).map((c) => `<button data-c="${c}" class="${a.color === c ? "on" : ""}" style="background:var(${HL[c]})" title="${c}"></button>`).join("")}</span></div></li>`;
    }).join("");
  }

  async function deleteAnn(id) {
    const a = R.anns.find((x) => x.id === id);
    if (!a) return;
    await api.send("DELETE", `/api/annotations/${a.id}`);
    R.anns = R.anns.filter((x) => x.id !== a.id);
    if (R.kind === "epub" && !isPin(a)) try { R.rendition.annotations.remove(a.locator.cfi, "highlight"); } catch (err) {}
    if (R.activeId === id) R.activeId = null;
    renderNotes();
    redraw();
    undoToast(a);
  }

  function undoToast(a) {
    const t = document.createElement("div");
    t.className = "toast";
    t.innerHTML = `${isPin(a) ? "Pin" : "Annotation"} deleted <button class="btn sm">Undo</button>`;
    t.querySelector("button").onclick = async () => {
      t.remove();
      const back = await api.send("POST", `/api/items/${R.item.id}/annotations`, { title: a.title, note: a.note, quote: a.quote, color: a.color, locator: a.locator });
      R.anns.push(back);
      renderNotes();
      redraw();
    };
    $("#toasts").append(t);
    setTimeout(() => t.remove(), 6000);
  }

  function redraw() {
    if (R.kind === "pdf") drawPdfAnnotations();
    else if (R.kind === "epub") { R.anns.forEach(addEpubHighlight); drawEpubPins(); }
    else if (R.kind === "comic") $$(".comic-page", doc()).forEach((el) => drawPins(el.querySelector(".pin-layer"), Number(el.dataset.page)));
  }

  function activate(id, scrollPanel) {
    R.activeId = id;
    $$(".note").forEach((n) => n.classList.toggle("active", Number(n.dataset.id) === id));
    if (scrollPanel) {
      $("#reader").classList.remove("notes-hidden");
      $(`.note[data-id="${id}"]`)?.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
    redraw();
  }

  function jumpTo(a) {
    activate(a.id, false);
    const loc = a.locator || {};
    if (R.kind === "pdf") {
      const r = isPin(a) || isBm(a) ? { p: loc.page, y: loc.y || 0 } : (loc.rects || [])[0];
      if (!r) return;
      if (mode() !== "scroll") { showPdfSpread(r.p); return; }
      const p = R.pages[r.p - 1];
      if (p) doc().scrollTo({ top: p.el.offsetTop + r.y * p.el.offsetHeight - 120, behavior: "smooth" });
    } else if (R.kind === "comic" && loc.page) {
      R.page = loc.page - 1;
      if (mode() === "scroll") doc().querySelector(`.comic-page[data-page="${loc.page}"]`)?.scrollIntoView({ behavior: "smooth" });
      else renderComic();
    } else if (loc.cfi) R.rendition.display(loc.cfi).then(() => setTimeout(() => drawEpubPins(), 50));
  }

  const debounced = {}, pendingFields = {};
  function patchAnn(a, fields) {
    Object.assign(a, fields);
    pendingFields[a.id] = { ...(pendingFields[a.id] || {}), ...fields };
    clearTimeout(debounced[a.id]);
    debounced[a.id] = setTimeout(() => {
      const f = pendingFields[a.id]; delete pendingFields[a.id];
      api.send("PATCH", `/api/annotations/${a.id}`, f).catch((e) => toast(e.message, "error"));
    }, 450);
  }

  /* ---------- full screen / window ---------- */
  async function toggleFull() {
    queueRelayout(true);  // hide and remember the spot before the window starts changing size
    if (MINI && S.desktop) { await api.send("POST", "/api/desktop/reader", { action: "fullscreen" }); return; }
    if (S.desktop) { await api.send("POST", "/api/desktop/fullscreen"); return; }
    if (document.fullscreenElement) await document.exitFullscreen();
    else await $("#reader").requestFullscreen().catch(() => {});
    queueRelayout();
  }

  /* ---------- wire up ---------- */
  function bind() {
    $("#readerClose").onclick = () => close();
    if (MINI) { $("#readerClose").textContent = "Close"; $("#readerClose").title = "Close the reader window"; }
    $("#rNext").onclick = () => goSide("right");
    $("#rPrev").onclick = () => goSide("left");
    $("#rFull").onclick = toggleFull;
    $("#rView").onclick = (e) => { e.stopPropagation(); $("#viewPop").hidden = !$("#viewPop").hidden; };
    document.addEventListener("click", (e) => { if (!e.target.closest(".view-wrap")) $("#viewPop").hidden = true; });
    $("#rMode").onclick = (e) => { const b = e.target.closest("button"); if (b) setMode(b.dataset.mode); };
    let wt;
    $("#rWidth").oninput = (e) => { setPref("width", typeKey(), Number(e.target.value)); clearTimeout(wt); wt = setTimeout(relayout, 150); };
    $("#rFont").oninput = (e) => { setPref("font", "epub", Number(e.target.value)); R.rendition?.themes.fontSize(e.target.value + "%"); setTimeout(() => drawEpubPins(), 300); };
    $("#rMark").onclick = () => toggleBookmark();
    $("#rPin").onclick = () => { setPinMode(!R.pinMode); hidePop(); if (R.kind === "epub") drawEpubPins(); if (R.pinMode) toast("Click anywhere on the page to drop a pin."); };
    $("#rDir").onclick = () => {
      R.rtl = !R.rtl;
      updateComicButtons();
      if (R.kind === "pdf") showPdfSpread(R.curPage || 1); else renderComic();
      api.send("PATCH", `/api/items/${R.item.id}`, { direction: R.rtl ? "rtl" : "ltr" });
    };
    $("#toggleNotes").onclick = () => { R.notesOpen = $("#reader").classList.toggle("notes-hidden") === false; };
    doc().addEventListener("wheel", pauseFollow, { passive: true });
    $("#pgLeft").onclick = () => goSide("left");
    $("#pgRight").onclick = () => goSide("right");
    $("#rHide").onclick = () => setImmersive(true);
    $("#rListen").onclick = () => listenHere();
    // immersive: the toolbar slides away; it peeks back when the mouse reaches the top edge
    $("#reader").addEventListener("mousemove", (e) => {
      if (!$("#reader").classList.contains("immersive")) return;
      $("#reader").classList.toggle("peek", e.clientY < 56);
      document.body.classList.toggle("peek-player", window.innerHeight - e.clientY < 80);
    });
    $("#rToc").onclick = () => toggleToc();
    $("#tocClose").onclick = () => toggleToc(false);
    $("#tocGo").onclick = () => goToPage(Number($("#tocPage").value) || 1);
    $("#tocPage").onkeydown = (e) => { if (e.key === "Enter") goToPage(Number(e.target.value) || 1); };
    $("#tocList").onclick = async (e) => {
      const b = e.target.closest(".toc-row");
      if (!b) return;
      if (b.dataset.tocHref) { await R.rendition.display(b.dataset.tocHref); setTimeout(markTocCurrent, 200); }
      else if (b.dataset.tocItem) { const it = S.items.find((x) => x.id === Number(b.dataset.tocItem)); if (it && it.id !== R.item.id) open(it); }
      else if (b.dataset.tocPage) goToPage(Number(b.dataset.tocPage));
      else if (b.dataset.tocDest !== undefined) {
        try {
          const dest = R.tocDest[Number(b.dataset.tocDest)];
          const d = typeof dest === "string" ? await R.pdf.getDestination(dest) : dest;
          goToPage((await R.pdf.getPageIndex(d[0])) + 1);
        } catch (err) { toast("That entry doesn't point to a page.", "error"); }
      }
    };
    // opening Contents or Notes narrows the page area without resizing the window: lay the book out again then
    // too, or the text keeps its old width and slides out of line with the book drawn around it
    if (window.ResizeObserver && !R._ro) {
      R._ro = new ResizeObserver(() => {
        const d = doc(), w = d.clientWidth, h = d.clientHeight;
        const changed = Math.abs(w - (R._ow ?? w)) > 3 || Math.abs(h - (R._oh ?? h)) > 3;
        R._ow = w; R._oh = h;
        if (!changed || !R.item || R.kind === "video" || $("#reader").hidden) return;
        if (R.relaying) return queueRelayout();
        // the book stays on screen: it is re-fitted to the new space instead of being hidden and rebuilt.
        // Until then only the text is hidden (this runs before the frame is drawn), so it never shows
        // laid out for the old width, spilling over the spine
        if (R.kind === "epub") d.classList.add("reflow");
        clearTimeout(R._softT);
        R._softT = setTimeout(softRelayout, 140);
      });
      R._ro.observe(doc());
    }
    window.addEventListener("resize", () => {
      if (!R.item || R.kind === "video") return;
      // in scrolling mode a book only needs re-laying out if it got narrower or wider
      if (!R.relaying && R.kind === "epub" && mode() === "scroll" && Math.abs(doc().clientWidth - (R.lastWidth || 0)) < 40) return;
      queueRelayout();
    });
    // another window (the mini reader or the main one) may have moved on in this book while this one was hidden
    document.addEventListener("visibilitychange", async () => {
      if (document.visibilityState !== "visible" || !R.item || R.kind === "video") return;
      const id = R.item.id;
      let fresh;
      try { fresh = await api.get(`/api/items/${id}`); } catch (e) { return; }
      const loc = String(fresh.last_location || "");
      if (!R.item || R.item.id !== id || !loc || loc === R.savedLoc) return;
      if (R.kind === "epub") { if (!loc.startsWith("epubcfi") || loc === R.startCfi) return; }
      R.relaying = true;
      R.restoring = true; R.pdfRestoring = true; R.comicRestoring = true;
      doc().classList.add("relaying");
      if (R.kind === "epub") R.startCfi = loc;
      else {
        const n = parseInt(loc) || 1;
        R.startFrac = parseFloat(loc.split(":")[1]) || 0;
        if (R.kind === "pdf") R.curPage = n; else R.page = n - 1;
      }
      R.savedLoc = loc;
      queueRelayout();
    });
    document.addEventListener("keydown", (e) => {
      if ($("#reader").hidden || !$("#lightbox").hidden) return;
      if (e.key === "Escape") {
        if (!$("#selPop").hidden) hidePop();
        else if (!$("#viewPop").hidden) $("#viewPop").hidden = true;
        else if (R.pinMode) setPinMode(false);
        else if ($("#reader").classList.contains("immersive")) setImmersive(false);
        else close();
        return;
      }
      if ((e.key === "b" || e.key === "B") && !e.target.matches?.("input,textarea,select") && !e.ctrlKey && !e.metaKey) { toggleBookmark(); return; }
      if ((e.key === "h" || e.key === "H") && !e.target.matches?.("input,textarea,select") && !e.ctrlKey && !e.metaKey) {
        setImmersive(!$("#reader").classList.contains("immersive"));
        return;
      }
      keyNav(e);
    });
    bindPinDragging(doc());
    doc().addEventListener("click", (e) => {
      if (e.target.closest(".pin,.hl,.fig,.rb-marks")) return;   // bookmark tabs aren't page-turn zones
      const z = e.target.closest("[data-zoom-page],[data-zoom-comic]");
      if (z) {
        e.stopPropagation();
        if (z.dataset.zoomPage) zoomPdfRegion(Number(z.dataset.zoomPage), null);
        else R.comic.url(Number(z.dataset.zoomComic)).then((u) => Lightbox.show(u, `Page ${Number(z.dataset.zoomComic) + 1}`));
        return;
      }
      if (R.kind === "comic") {
        const pageEl2 = e.target.closest(".comic-page");
        if (pageEl2) { createAnn({ locator: { type: "pin", page: Number(pageEl2.dataset.page), ...pageCoords(e, pageEl2) } }); return; }
        if (mode() !== "scroll") { const b = doc().getBoundingClientRect(); goSide(e.clientX < b.left + b.width / 2 ? "left" : "right"); }
        return;
      }
      if (R.kind === "pdf") {
        const pg = e.target.closest(".pdf-page");
        if (R.pinMode) {
          if (pg) createAnn({ locator: { type: "pin", page: Number(pg.dataset.page), ...pageCoords(e, pg) } });
          return;
        }
        if (mode() !== "scroll" && window.getSelection().isCollapsed) {
          const b = doc().getBoundingClientRect();
          const x = (e.clientX - b.left) / b.width;
          if (x < 0.33) goSide("left");
          else if (x > 0.67) goSide("right");
        }
      }
    });
    doc().addEventListener("mouseup", () => {
      if (R.kind !== "pdf" || R.pinMode) return;
      setTimeout(() => {
        const s = pdfSelection();
        if (!s) return hidePop();
        R.pending = s;
        showPop(s.at.x, s.at.y);
      }, 10);
    });
    doc().addEventListener("mousedown", (e) => { if (!e.target.closest("#selPop")) hidePop(); });
    const pop = $("#selPop");
    pop.addEventListener("mousedown", (e) => e.preventDefault());
    pop.addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) createFromPending(b.dataset.color); });

    const list = $("#notesList");
    list.addEventListener("input", (e) => {
      const li = e.target.closest(".note");
      const a = R.anns.find((x) => x.id === Number(li.dataset.id));
      if (e.target.matches(".n-title")) patchAnn(a, { title: e.target.value });
      if (e.target.matches(".n-note")) patchAnn(a, { note: e.target.value });
    });
    list.addEventListener("click", async (e) => {
      const li = e.target.closest(".note");
      if (!li) return;
      const a = R.anns.find((x) => x.id === Number(li.dataset.id));
      if (e.target.closest("[data-del]")) return deleteAnn(a.id);
      if (e.target.closest("blockquote")) return jumpTo(a);
      const c = e.target.closest("[data-c]");
      if (c) { await api.send("PATCH", `/api/annotations/${a.id}`, { color: c.dataset.c }); a.color = c.dataset.c; renderNotes(); activate(a.id, false); return; }
      if (!e.target.matches("input,textarea")) jumpTo(a);
    });
    list.addEventListener("focusin", (e) => { const li = e.target.closest(".note"); if (li && Number(li.dataset.id) !== R.activeId) activate(Number(li.dataset.id), false); });
  }

  window.Reader = {
    open,
    onTheme() {
      if (!R.item) return;
      if (R.kind === "epub") { applyEpubTheme(); R.anns.forEach(addEpubHighlight); setTimeout(() => drawEpubPins(), 300); }
      else if (R.kind === "comic") renderComic();
      else if (R.pdf) layoutPdf(R.curPage || 1);
    },
  };
  bind();
})();

/* ---------- full-screen image viewer: wheel or +/- to zoom, drag to pan ---------- */
window.Lightbox = (() => {
  let z = 1, x = 0, y = 0, drag = null;
  const img = () => $("#lbImg");
  const apply = () => { img().style.transform = `translate(${x}px, ${y}px) scale(${z})`; };
  function show(src, cap) {
    $("#lbCap").textContent = cap || "";
    z = 1; x = 0; y = 0;
    img().src = src;
    apply();
    $("#lightbox").hidden = false;
  }
  function hide() { $("#lightbox").hidden = true; img().removeAttribute("src"); }
  function zoomBy(f) { z = Math.max(0.5, Math.min(8, z * f)); apply(); }
  document.addEventListener("DOMContentLoaded", () => {});
  setTimeout(() => {
    $("#lbClose").onclick = hide;
    $("#lbIn").onclick = () => zoomBy(1.25);
    $("#lbOut").onclick = () => zoomBy(0.8);
    $("#lbFit").onclick = () => { z = 1; x = 0; y = 0; apply(); };
    $("#lbStage").addEventListener("wheel", (e) => { e.preventDefault(); zoomBy(e.deltaY < 0 ? 1.12 : 0.89); }, { passive: false });
    $("#lbStage").addEventListener("pointerdown", (e) => { drag = { sx: e.clientX - x, sy: e.clientY - y }; $("#lbStage").setPointerCapture(e.pointerId); });
    $("#lbStage").addEventListener("pointermove", (e) => { if (drag) { x = e.clientX - drag.sx; y = e.clientY - drag.sy; apply(); } });
    $("#lbStage").addEventListener("pointerup", () => { drag = null; });
    $("#lbStage").addEventListener("dblclick", () => { z = z > 1 ? 1 : 2.5; if (z === 1) { x = 0; y = 0; } apply(); });
    document.addEventListener("keydown", (e) => {
      if ($("#lightbox").hidden) return;
      if (e.key === "Escape") { e.stopPropagation(); hide(); }
      if (e.key === "+" || e.key === "=") zoomBy(1.25);
      if (e.key === "-") zoomBy(0.8);
    }, true);
  }, 0);
  return { show, hide };
})();
