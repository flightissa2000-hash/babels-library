/* The sleep screen: when Babel's Library is full screen and the mouse and keyboard have been left alone for a while
   (Settings → Desktop: on/off and how long), the time, the date and this week's challenge come
   up, drawn in your theme. Galaxy goes through ESA's space photos (100 picked at random from the Hubble and Webb
   top-100s, kept on this computer by spacephotos.py). Any key, click or move of the mouse wakes it.
   It waits while a video plays here, while a website in the browser is playing sound, and (longer) while a book is open.
   Idle time comes from Windows (GET /api/desktop/idle), so using a website in the browser counts as being here. */
const Sleep = window.Sleep = (() => {
  const KEY = "inkwell-sleep";
  const cfg = Object.assign({ on: true, after: 10 }, (() => { try { return JSON.parse(localStorage.getItem(KEY) || "{}"); } catch (e) { return {}; } })());
  const saveCfg = () => { try { localStorage.setItem(KEY, JSON.stringify(cfg)); } catch (e) {} };
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
  let dimT = 0, el = null, on = false, since = 0, theme = "", timers = [], photos = null, deck = [], shownAt = 0;

  const rnd = (a, b) => a + Math.random() * (b - a);
  const isFull = (srv) => srv || (Math.abs(innerWidth - screen.width) < 3 && Math.abs(innerHeight - screen.height) < 3);
  const videoPlaying = () => [...document.querySelectorAll("video, audio.video")].some((v) => !v.paused && !v.ended && v.readyState > 2 && v.tagName === "VIDEO");
  const readerOpen = () => { const r = document.getElementById("reader"); return !!r && !r.hidden; };

  function build() {
    el = document.createElement("div");
    el.id = "sleepScreen";
    el.innerHTML = `<div class="sl-scene"></div>
      <main class="sl-card"><div class="sl-term">
        <span class="sl-p">date +%R</span>
        <div class="sl-clock"></div><div class="sl-date"></div>
        <div class="sl-chal" hidden></div>
        <span class="sl-p sl-last">sleep ∞ <span class="sl-cur"></span></span>
      </div></main>
      <div class="sl-cap" hidden><b></b><small></small></div>
      <div class="sl-wake">Move the mouse or press a key to wake</div>`;
    document.body.append(el);
    // waking: the click or key that wakes it does only that (it doesn't land on whatever is under the screen)
    const wake = (e) => { if (!on) return; e.preventDefault(); e.stopPropagation(); hide(); };
    el.addEventListener("pointerdown", wake, true);
    el.addEventListener("wheel", wake, { passive: false });
    let mx = null, my = null;
    el.addEventListener("pointermove", (e) => {
      if (!on || Date.now() - shownAt < 1200) return;                 // (the screen coming up can nudge the pointer)
      if (mx === null) { mx = e.clientX; my = e.clientY; return; }
      if (Math.hypot(e.clientX - mx, e.clientY - my) > 12) { mx = my = null; hide(); }
    });
    addEventListener("keydown", (e) => { if (on) { e.preventDefault(); e.stopImmediatePropagation(); hide(); } }, true);
  }

  /* ---- the scenes */
  function scene(t) {
    const sc = el.querySelector(".sl-scene");
    let h = "";
    if (t === "galaxy") {
      h = `<div class="sl-ph a"></div><div class="sl-ph b"></div><div class="sl-veil"></div><canvas class="sl-stars"></canvas>`;
    } else if (t === "gruvbox") {
      h = `<div class="sl-scan"></div>`;
    } else {
      for (let i = 0; i < 60; i++) h += `<i class="sl-star" style="left:${rnd(0, 100)}%;top:${rnd(0, 55)}%;animation-delay:${rnd(0, 4)}s"></i>`;
      h += `<div class="sl-moon"></div>`;
      for (let i = 0; i < 6; i++) h += `<div class="sl-cloud" style="top:${rnd(6, 40)}%;width:${rnd(120, 240)}px;animation-duration:${rnd(90, 170)}s;animation-delay:-${rnd(0, 170)}s"></div>`;
      let town = "";
      const n = 16;
      for (let i = 0; i < n; i++) {
        const ht = rnd(40, 100);
        let wins = "";
        for (let r = 0; r < Math.floor(ht / 22); r++) for (let c = 0; c < 3; c++) if (Math.random() < .65) wins += `<i class="sl-win${Math.random() < .3 ? " off" : ""}" style="left:${16 + c * 28}%;bottom:${12 + r * 19}%"></i>`;
        town += `<div class="sl-house" style="height:${ht}%;--w:${Math.round(innerWidth / n)}px">${wins}</div>`;
      }
      h += `<div class="sl-town">${town}</div>`;
      for (let i = 0; i < 3; i++) h += `<span class="sl-zz" style="left:${36 + i * 12}%;bottom:${26 + i * 2}vh;animation-delay:${i * 2.3}s">z</span>`;
    }
    sc.innerHTML = h;
    if (t === "galaxy") { twinkle(); slides(); }
  }
  // (Galaxy) small stars breathing over the photo
  function twinkle() {
    const c = el.querySelector(".sl-stars"), x = c.getContext("2d");
    c.width = innerWidth * devicePixelRatio; c.height = innerHeight * devicePixelRatio;
    const st = Array.from({ length: 140 }, () => ({ x: Math.random() * c.width, y: Math.random() * c.height, r: (Math.random() * 1.2 + .3) * devicePixelRatio, p: Math.random() * 6.28, s: .4 + Math.random() * 1.2 }));
    let last = 0;
    const draw = (t) => {
      if (!on || theme !== "galaxy") return;
      requestAnimationFrame(draw);
      if (t - last < 66) return;
      last = t;
      x.clearRect(0, 0, c.width, c.height);
      x.fillStyle = "#fff";
      for (const s of st) { x.globalAlpha = .2 + .5 * Math.abs(Math.sin(s.p + t / 1000 * s.s)); x.beginPath(); x.arc(s.x, s.y, s.r, 0, 6.29); x.fill(); }
    };
    requestAnimationFrame(draw);
  }
  // (Galaxy) the photos: a random one every 30 seconds, fading across with a slow drift and zoom
  const FALLBACK = [{ src: "/sky/milkyway.jpg", title: "The Milky Way", credit: "ESO/S. Brunier" }];
  async function slides() {
    if (!photos || photos.length < 100) {
      try { const d = await (await fetch("/api/sleep/photos", { cache: "no-store" })).json(); photos = (d.photos || []).map((p) => ({ src: `/api/sleep/photo/${encodeURIComponent(p.id)}`, title: p.title, credit: p.credit })); } catch (e) { photos = photos || []; }
    }
    let flip = false;
    const next = () => {
      if (!on || theme !== "galaxy") return;
      const pool = photos.length ? photos : FALLBACK;
      if (!deck.length) deck = pool.slice().sort(() => Math.random() - .5);
      const p = deck.pop();
      const img = new Image();
      img.onload = () => {
        if (!on || theme !== "galaxy") return;
        flip = !flip;
        const show = el.querySelector(flip ? ".sl-ph.a" : ".sl-ph.b"), hideEl = el.querySelector(flip ? ".sl-ph.b" : ".sl-ph.a");
        if (!show) return;
        show.style.backgroundImage = `url("${p.src}")`;
        // each photo drifts its own way
        show.style.setProperty("--x0", rnd(-3, 3) + "%"); show.style.setProperty("--y0", rnd(-3, 3) + "%");
        show.style.setProperty("--x1", rnd(-3, 3) + "%"); show.style.setProperty("--y1", rnd(-3, 3) + "%");
        show.classList.remove("on"); void show.offsetWidth; show.classList.add("on");
        hideEl.classList.remove("on");
        const cap = el.querySelector(".sl-cap");
        cap.hidden = false;
        cap.querySelector("b").textContent = p.title || "";
        cap.querySelector("small").textContent = p.credit ? `Image: ${p.credit} (CC BY 4.0)` : "";
      };
      img.onerror = () => { photos = photos.filter((x) => x !== p); setTimeout(next, 200); };
      img.src = p.src;
    };
    next();
    timers.push(setInterval(next, 30000));
  }
  // (Word Town) the town goes to bed: windows go dark one by one, now and then one comes back on
  function townTick() {
    if (theme !== "galaxy" && theme !== "gruvbox") {
      const lit = [...el.querySelectorAll(".sl-win:not(.off)")], dark = [...el.querySelectorAll(".sl-win.off")];
      if (lit.length > 3 && Math.random() < .8) lit[Math.floor(Math.random() * lit.length)].classList.add("off");
      else if (dark.length) dark[Math.floor(Math.random() * dark.length)].classList.remove("off");
    }
  }

  /* ---- what it says */
  function tick() {
    const d = new Date();
    const parts = new Intl.DateTimeFormat([], { hour: "numeric", minute: "2-digit" }).formatToParts(d);
    const hm = parts.filter((p) => p.type !== "dayPeriod").map((p) => p.value).join("").trim();
    const ap = (parts.find((p) => p.type === "dayPeriod") || {}).value || "";
    el.querySelector(".sl-clock").innerHTML = `${esc(hm)}${ap ? `<small>${esc(ap)}</small>` : ""}`;
    el.querySelector(".sl-date").textContent = d.toLocaleDateString([], { weekday: "long", month: "long", day: "numeric" });
  }
  function fill() {
    let ch = null;           // (Bulletin is app.js's own: not on window)
    try { ch = typeof Bulletin !== "undefined" && Bulletin.current ? Bulletin.current() : null; } catch (e) {}
    const c = el.querySelector(".sl-chal");
    c.hidden = !ch;
    if (ch) c.textContent = (theme === "gruvbox" ? "# " : "★ ") + "This week: " + ({ finish: "finish", start: "start", revisit: "revisit" }[ch.type] || "open") + " " + ch.title;
  }
  // a little somewhere else every minute, so nothing burns into the screen
  function drift() {
    const k = Math.min(innerWidth, innerHeight);
    el.style.setProperty("--dx", Math.round((Math.random() - .5) * k * .2) + "px");
    el.style.setProperty("--dy", Math.round((Math.random() - .5) * k * .18) + "px");
  }

  function show() {
    if (on) return;
    if (!el) build();
    on = true; shownAt = Date.now();
    const t = document.documentElement.dataset.theme || "wordtown";
    theme = t; el.dataset.t = t;
    scene(t); tick(); fill(); drift();
    el.classList.add("on");
    document.documentElement.classList.add("sleeping");
    const w = el.querySelector(".sl-wake"); w.classList.add("show"); setTimeout(() => w.classList.remove("show"), 4000);
    timers.push(setInterval(tick, 5000), setInterval(drift, 60000), setInterval(townTick, 9000), setInterval(fill, 5 * 60000));
    // the screen itself dims (the monitor's own brightness, put back on waking); if it can't, the page darkens instead
    dimT = setTimeout(() => {
      if (!on) return;
      fetch("/api/sleep/dim", { method: "POST" }).then((r) => r.json()).then((d) => { if (on) el.classList.toggle("soft", !d.ok); })
        .catch(() => { if (on) el.classList.add("soft"); });
    }, 1500);
    // something else woke the computer up (a key in another window, say): back to the library
    timers.push(setInterval(async () => { try { const d = await api.get("/api/desktop/idle"); if (d.idle < 1.5 && Date.now() - shownAt > 3000) hide(); } catch (e) {} }, 2000));
  }
  function hide() {
    if (!on) return;
    on = false;
    timers.forEach(clearInterval); timers = [];
    clearTimeout(dimT);
    undim();
    el.classList.remove("on", "soft");
    document.documentElement.classList.remove("sleeping");
    setTimeout(() => { if (!on && el) el.querySelector(".sl-scene").innerHTML = ""; }, 700);
    since = Date.now();
  }

  // every 15 seconds: time to sleep?
  async function check() {
    if (on || !cfg.on || document.hidden) return;
    if (Date.now() - since < 30000) return;
    let d;
    try { d = await api.get("/api/desktop/idle"); } catch (e) { return; }
    if (!isFull(d.fullscreen) || d.playing || videoPlaying()) return;
    const need = cfg.after * 60 * (readerOpen() ? 3 : 1);
    if (d.idle >= need) show();
  }
  setInterval(check, 15000);
  // back to full brightness: on waking, and whenever the page (re)loads, in case it closed while the screen was dimmed
  function undim() { fetch("/api/sleep/undim", { method: "POST", keepalive: true }).catch(() => {}); }
  undim();
  addEventListener("pagehide", () => { if (on) undim(); });

  // Settings → Desktop
  function settings() {
    const box = document.getElementById("sleepSet");
    if (!box) return;
    box.innerHTML = `<label><input type="checkbox" id="sleepOn" ${cfg.on ? "checked" : ""}> Sleep screen when Babel's Library is full screen and left alone for
      <select id="sleepAfter">${[2, 5, 10, 15, 20, 30, 45, 60].map((m) => `<option value="${m}" ${m === cfg.after ? "selected" : ""}>${m} min</option>`).join("")}</select></label>
      <button class="btn" type="button" id="sleepPreview">Show it now</button>
      <span class="hint">The time and this week's challenge, in your theme (Galaxy goes through ESA's Hubble and Webb photos), with the screen dimmed until you wake it. It waits while a video or a website is playing.</span>`;
    box.querySelector("#sleepOn").onchange = (e) => { cfg.on = e.target.checked; saveCfg(); };
    box.querySelector("#sleepAfter").onchange = (e) => { cfg.after = Number(e.target.value); saveCfg(); };
    box.querySelector("#sleepPreview").onclick = () => setTimeout(show, 150);
  }
  settings();

  return { show, hide, get on() { return on; }, cfg };
})();
