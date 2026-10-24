/* Babel's Library music player, shared by the main window and the desktop widget.
   The main window always owns the audio (it keeps running while hidden, so switching to the widget never
   interrupts the music). The widget is a remote control: it sends commands and shows the main window's state. */
const Player = (() => {
  const q = (s) => document.querySelector(s);
  const escH = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const fmt = (s) => { if (!isFinite(s) || s < 0) return "0:00"; s = Math.floor(s); const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), x = String(s % 60).padStart(2, "0"); return h ? `${h}:${String(m).padStart(2, "0")}:${x}` : `${m}:${x}`; };
  const slim = (t) => ({ ...(t.ab ? { ab: t.ab, ch: t.ch, src: t.src } : {}), id: t.id, title: t.title, authors: t.authors || [], album: t.album || "", album_artist: t.album_artist || "", has_cover: !!t.has_cover, cover_v: t.cover_v || "", duration: t.duration || 0, track: t.track || null, disc: t.disc || null });

  const P = { tracks: [], order: [], pos: 0, shuffle: false, uid: 0 };
  let audio = null, onChange = () => {}, saveT = null, lastSaved = 0;
  let remote = false, RS = null, pollT = null, tickT = null;  // remote-control mode (widget)
  try { P.shuffle = localStorage.getItem("inkwell-shuffle") === "1"; } catch (e) {}

  // The slider is a position (0..1); loudness is heard logarithmically, so map it onto a 36 dB range.
  // Linear volume crowds all the audible change into the left fifth and seems to cut out early.
  const gain = (p) => (p <= 0.004 ? 0 : Math.pow(10, (-36 * (1 - p)) / 20));
  let volPos = 1;
  function setVol(p) {
    volPos = Math.max(0, Math.min(1, Number(p) || 0));
    if (audio) audio.volume = gain(volPos);
    try { localStorage.setItem("inkwell-volpos", volPos); } catch (e) {}
  }
  const cur = () => P.tracks[P.order[P.pos]];
  const shuffled = (arr) => { const a = [...arr]; for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; } return a; };
  const tag = (t) => ({ ...slim(t), _u: ++P.uid });

  function setList(list, start = 0, shuffle = P.shuffle) {
    P.tracks = list.map(tag);
    P.shuffle = shuffle;
    remember();
    const idx = P.tracks.map((_, i) => i);
    if (shuffle) {
      const first = Math.min(start, idx.length - 1);
      P.order = start >= 0 && list.length ? [first, ...shuffled(idx.filter((i) => i !== first))] : shuffled(idx);
      P.pos = 0;
    } else { P.order = idx; P.pos = Math.max(0, Math.min(start, idx.length - 1)); }
  }

  /* --- remote control (widget) --- */
  function sendCmd(c) {
    return fetch("/api/player/cmd", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(c) })
      .then(() => { setTimeout(pollRemote, 250); setTimeout(pollRemote, 900); }).catch(() => {});
  }
  function pollRemote() {
    if (document.hidden) return;
    fetch("/api/player").then((r) => r.json()).then((st) => { RS = st && st.tracks && st.tracks.length ? st : null; paint(); }).catch(() => {});
  }
  const remoteTime = () => (!RS ? 0 : RS.playing ? Math.min(RS.duration || 1e9, RS.time + (Date.now() / 1000 - (RS.at || Date.now() / 1000))) : RS.time);
  // commands arriving in the main window (pushed by the desktop app, or polled in browser mode)
  window.inkwellCmd = (c) => {
    try {
      const byId = (ids) => (ids || []).map((id) => (typeof S !== "undefined" ? S.items.find((x) => x.id === id) : null)).filter(Boolean);
      switch (c.action) {
        case "toggle": return toggle();
        case "pause": return pause();
        case "volume": setVol(c.value); if (q("#plVol")) q("#plVol").value = volPos; return save(true);
        case "next": return next();
        case "prev": return prev();
        case "stop": return stop();
        case "shuffle": return toggleShuffle();
        case "jump": return jump(c.n);
        case "remove": return removeAt(c.n);
        case "clear": P.order = P.order.slice(0, P.pos + 1); return changed();
        case "seek": if (audio && audio.duration) audio.currentTime = c.frac * audio.duration; return save(true);
        case "playAudiobook": return playAudiobook(c.id, { ch: c.ch, t: c.t });
        case "rate": return setRate(c.value);
        case "playList": return playList(byId(c.ids), c.start || 0, c.shuffle ? { shuffle: true } : {});
        case "playNext": return playNext(byId(c.ids));
        case "queue": return addToQueue(byId(c.ids));
      }
    } catch (e) { console.error(e); }
  };
  function startCmdPolling() {
    setInterval(() => fetch("/api/player/cmds").then((r) => r.json()).then((list) => (list || []).forEach(window.inkwellCmd)).catch(() => {}), 1000);
  }

  /* --- public actions --- */
  function playList(list, start = 0, opts = {}) {
    if (!list.length) return;
    if (remote) return sendCmd({ action: "playList", ids: list.map((t) => t.id), start, shuffle: !!opts.shuffle });
    const sh = opts.shuffle !== undefined ? opts.shuffle : P.shuffle;
    setList(list, opts.shuffle && opts.randomStart !== false && !opts.keepStart ? Math.floor(Math.random() * list.length) : start, sh);
    load(true);
  }
  function playNext(list) {
    if (remote) return sendCmd({ action: "playNext", ids: list.map((t) => t.id) });
    if (!P.tracks.length) return playList(list, 0, { shuffle: false });
    const add = list.map(tag);
    const base = P.tracks.length;
    P.tracks.push(...add);
    P.order.splice(P.pos + 1, 0, ...add.map((_, i) => base + i));
    changed();
  }
  function addToQueue(list) {
    if (remote) return sendCmd({ action: "queue", ids: list.map((t) => t.id) });
    if (!P.tracks.length) return playList(list, 0, { shuffle: false });
    const base = P.tracks.length;
    P.tracks.push(...list.map(tag));
    P.order.push(...list.map((_, i) => base + i));
    changed();
  }
  function toggleShuffle(on = !P.shuffle) {
    if (remote) return sendCmd({ action: "shuffle" });
    if (cur() && cur().ab) return;  // audiobook chapters always play in order
    P.shuffle = on;
    remember();
    if (P.tracks.length) {
      const now = P.order[P.pos];
      const rest = P.order.slice(P.pos + 1);
      if (on) { P.order = [...P.order.slice(0, P.pos + 1), ...shuffled(rest)]; }
      else {
        const done = new Set(P.order.slice(0, P.pos + 1));
        const restNatural = P.tracks.map((_, i) => i).filter((i) => i > now && !done.has(i) && rest.includes(i));
        const restEarlier = rest.filter((i) => !restNatural.includes(i));
        P.order = [...P.order.slice(0, P.pos + 1), ...restNatural, ...restEarlier];
      }
    }
    changed();
  }
  function jump(n) {
    if (remote) return sendCmd({ action: "jump", n }); if (n >= 0 && n < P.order.length) { P.pos = n; load(true); } }
  function removeAt(n) {
    if (remote) return sendCmd({ action: "remove", n });
    if (n <= P.pos || n >= P.order.length) return;
    P.order.splice(n, 1);
    changed();
  }
  function next() {
    if (remote) return sendCmd({ action: "next" }); if (P.pos < P.order.length - 1) { P.pos++; load(true); } else if (audio) { audio.pause(); audio.currentTime = 0; } }
  function prev() {
    if (remote) return sendCmd({ action: "prev" }); if (!audio) return; if (audio.currentTime > 3 || P.pos === 0) audio.currentTime = 0; else { P.pos--; load(true); } }
  function toggle() {
    if (remote) {   // show the change straight away; the real state follows a moment later
      if (RS) { RS.time = remoteTime(); RS.at = Date.now() / 1000; RS.playing = !RS.playing; paint(); }
      return sendCmd({ action: "toggle" });
    }
    if (!audio || !cur()) return; audio.paused ? audio.play().catch(() => {}) : audio.pause(); }
  function stop() {
    if (remote) return sendCmd({ action: "stop" }); if (audio) { audio.pause(); audio.removeAttribute("src"); audio.load(); } P.tracks = []; P.order = []; P.pos = 0; changed(); save(true); }

  function remember() { try { localStorage.setItem("inkwell-shuffle", P.shuffle ? "1" : "0"); } catch (e) {} }

  function load(autoplay, at = 0) {
    const t = cur();
    if (!t || !audio) return changed();
    audio.src = t.src || `/api/items/${t.id}/file`;
    if (at) audio.addEventListener("loadedmetadata", () => { audio.currentTime = at; }, { once: true });
    applyRate();
    if (autoplay) audio.play().catch(() => {});
    if (!t.ab) fetch(`/api/items/${t.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ opened: true }) }).catch(() => {});
    changed();
  }

  /* --- audiobooks: chapters of a book, played in order (never shuffled), position remembered on the book --- */
  async function playAudiobook(id, opts = {}) {
    if (remote) return sendCmd({ action: "playAudiobook", id, ch: opts.ch, t: opts.t });
    const [m, it] = await Promise.all([fetch(`/api/items/${id}/audiobook`).then((r) => r.json()), fetch(`/api/items/${id}`).then((r) => r.json())]);
    if (!m || !m.chapters) return;
    const tracks = m.chapters.map((c, i) => ({ id: `ab:${id}:${i}`, ab: id, ch: i, src: `/api/items/${id}/audio/${i}`, title: c.title,
      album: it.title, authors: it.authors || [], has_cover: it.has_cover, cover_v: it.cover_v, duration: c.duration }));
    let ch = opts.ch, t = opts.t;
    if (ch == null && it.audio_pos && !it.audio_pos.done) { ch = it.audio_pos.ch; t = it.audio_pos.t; }
    ch = Math.max(0, Math.min(tracks.length - 1, ch || 0));
    P.tracks = tracks.map(tag);
    P.order = P.tracks.map((_, i) => i);
    P.pos = ch;
    load(true, Math.max(0, (t || 0) - 1.5));
  }
  let lastAbSave = 0;
  function saveAbPos(done) {
    const t = cur();
    if (!t || !t.ab || !audio) return;
    lastAbSave = Date.now();
    fetch(`/api/items/${t.ab}/audio-pos`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ch: t.ch, t: audio.currentTime, done: !!done }) }).catch(() => {});
  }
  function nowPlaying() {
    const V = view();
    const t = V.tracks[V.order[V.pos]];
    return { track: t || null, time: remote ? remoteTime() : audio ? audio.currentTime : 0, playing: remote ? !!(RS && RS.playing) : !!(audio && !audio.paused) };
  }

  /* --- state for the other window --- */
  function state() {
    return { tracks: P.tracks, order: P.order, pos: P.pos, shuffle: P.shuffle, time: audio ? audio.currentTime : 0, at: Date.now() / 1000,
      duration: audio && isFinite(audio.duration) ? audio.duration : 0, playing: !!(audio && !audio.paused && cur()), volume: volPos, rate: abRate() };
  }
  function restore(st, autoplay) {
    if (!st || !st.tracks || !st.tracks.length) return;
    P.tracks = st.tracks; P.order = st.order; P.pos = st.pos || 0; P.shuffle = !!st.shuffle;
    P.uid = Math.max(0, ...P.tracks.map((t) => t._u || 0));
    if (st.volume != null) setVol(st.volume);
    load(autoplay === undefined ? st.playing : autoplay, st.time || 0);
  }
  function save(now) {
    clearTimeout(saveT);
    const go = () => { lastSaved = Date.now(); fetch("/api/player", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(state()) }).catch(() => {}); };
    if (now) go(); else saveT = setTimeout(go, 800);
  }

  function changed() { save(); paint(); onChange(state()); }

  /* --- UI (any of these elements may be missing) --- */
  const view = () => (remote ? RS || { tracks: [], order: [], pos: 0, shuffle: false } : P);
  const viewCur = () => { const V = view(); return V.tracks[V.order[V.pos]]; };
  function paint() {
    const V = view();
    const t = viewCur();
    if (remote) {
      if (q("#plPlay")) q("#plPlay").textContent = RS && RS.playing ? "❚❚" : "▶";
      const vol = q("#plVol");
      if (vol && RS && RS.volume != null && document.activeElement !== vol && Date.now() - (window._volT || 0) > 4000) vol.value = RS.volume;
      onChange(RS || {});
      tickRemote();
    }
    const bar = q("#player");
    if (bar) { bar.hidden = !t; document.body.classList.toggle("has-player", !!t); }
    if (q("#plTitle")) q("#plTitle").textContent = t ? t.title : "";
    const rs = q("#plRate");
    if (rs) { rs.hidden = !(t && t.ab); const r = remote ? (RS && RS.rate) || 1 : abRate(); if (document.activeElement !== rs) rs.value = String(r); }
    if (q("#plArtist")) q("#plArtist").textContent = t ? [(t.authors || [])[0], t.album].filter(Boolean).join(" · ") : "";
    if (q("#plCover")) q("#plCover").innerHTML = t && t.has_cover ? `<img alt="" src="/api/items/${t.id}/cover?v=${t.cover_v || 0}">` : "";
    if (q("#plShuf")) { q("#plShuf").classList.toggle("on", V.shuffle); q("#plShuf").setAttribute("aria-pressed", V.shuffle ? "true" : "false"); q("#plShuf").title = V.shuffle ? "Shuffle is on" : "Shuffle is off"; }
    if (q("#plQCount")) { const n = V.order.length - V.pos - 1; q("#plQCount").textContent = n > 0 ? n : ""; }
    paintQueue();
  }
  function paintQueue() {
    const box = q("#plQueueList");
    if (!box || q("#plQueuePanel")?.hidden) return;
    const V = view();
    const t = viewCur();
    const up = V.order.slice(V.pos + 1);
    box.innerHTML = (t ? `<li class="q-now"><span class="q-lbl">Now playing</span><b>${escH(t.title)}</b><span>${escH([(t.authors || [])[0], t.album].filter(Boolean).join(" · "))}</span></li>` : "") +
      (up.length ? `<li class="q-lbl">Up next${V.shuffle ? " (shuffled)" : ""}</li>` + up.map((i, k) => { const x = V.tracks[i]; return `<li class="q-row"><button class="q-go" data-q-jump="${V.pos + 1 + k}"><b>${escH(x.title)}</b><span>${escH([(x.authors || [])[0], x.album].filter(Boolean).join(" · "))}</span></button><button class="icon-btn sm" data-q-del="${V.pos + 1 + k}" title="Remove from queue">✕</button></li>`; }).join("")
        : `<li class="q-empty">Nothing queued after this track.</li>`);
  }

  function tickRemote() {
    if (!remote) return;
    const d = RS ? RS.duration : 0, tm = remoteTime();
    if (q("#plFill")) q("#plFill").style.width = (d ? Math.min(100, (tm / d) * 100) : 0) + "%";
    if (q("#plTime")) q("#plTime").textContent = RS ? `${fmt(tm)} / ${fmt(d)}` : "";
    const sk = q("#plSeek");
    if (sk && document.activeElement !== sk) { sk.max = d || 0; sk.value = tm; }
  }
  function seek(frac) {
    if (remote) return sendCmd({ action: "seek", frac });
    if (audio && audio.duration) audio.currentTime = frac * audio.duration;
  }
  /* audiobook speed (music always plays at normal speed) */
  const RATES = [1, 1.25, 1.5, 1.75, 2, 2.5, 3, 3.5, 4, 4.5, 5];
  function abRate() { try { const r = parseFloat(localStorage.getItem("inkwell-ab-rate")); return RATES.includes(r) ? r : 1; } catch (e) { return 1; } }
  function applyRate() {
    if (!audio) return;
    const t = cur();
    const r = t && t.ab ? abRate() : 1;
    audio.defaultPlaybackRate = r;   // survives the next chapter loading
    audio.playbackRate = r;
    audio.preservesPitch = true;
  }
  function setRate(v) {
    v = Number(v);
    if (!RATES.includes(v)) return;
    if (remote) { if (RS) RS.rate = v; paint(); return sendCmd({ action: "rate", value: v }); }
    try { localStorage.setItem("inkwell-ab-rate", v); } catch (e) {}
    applyRate(); paint(); save(true);
  }
  function pause() { if (remote) return sendCmd({ action: "pause" }); if (audio && !audio.paused) audio.pause(); }
  function setVolume(v) {
    if (remote) { if (RS) RS.volume = v; return sendCmd({ action: "volume", value: v }); }
    setVol(v); save(true);
  }

  function bind(opts = {}) {
    onChange = opts.onChange || onChange;
    if (opts.remote) {
      remote = true;
      const on = (id, ev, fn) => { const el = q(id); if (el) el.addEventListener(ev, fn); };
      on("#plPlay", "click", toggle);
      on("#plNext", "click", next);
      on("#plPrev", "click", prev);
      on("#plShuf", "click", () => toggleShuffle());
      on("#plClose", "click", stop);
      on("#plQueue", "click", () => { const p = q("#plQueuePanel"); p.hidden = !p.hidden; paintQueue(); });
      on("#plQueueClose", "click", () => { q("#plQueuePanel").hidden = true; });
      on("#plQueueClear", "click", () => sendCmd({ action: "clear" }));
      on("#plRate", "change", (e) => setRate(e.target.value));
      let volT = null;
      on("#plSeek", "change", (e) => { const mx = Number(e.target.max); if (mx) seek(Number(e.target.value) / mx); e.target.blur(); });
      on("#plVol", "input", (e) => { window._volT = Date.now(); clearTimeout(volT); const v = Number(e.target.value); volT = setTimeout(() => setVolume(v), 120); });
      on("#plQueueList", "click", (e) => {
        const j = e.target.closest("[data-q-jump]"), d = e.target.closest("[data-q-del]");
        if (j) jump(Number(j.dataset.qJump)); else if (d) removeAt(Number(d.dataset.qDel));
      });
      // until the main window reports its state, show the saved volume rather than the slider's default (full)
      try { const v = parseFloat(localStorage.getItem("inkwell-volpos")); if (v >= 0 && v <= 1 && q("#plVol")) q("#plVol").value = v; } catch (e) {}
      pollRemote();
      pollT = setInterval(pollRemote, 1500);
      tickT = setInterval(tickRemote, 500);
      document.addEventListener("visibilitychange", () => { if (!document.hidden) pollRemote(); });
      return;
    }
    audio = q("#audio");
    const on = (id, ev, fn) => { const el = q(id); if (el) el.addEventListener(ev, fn); };
    on("#plPlay", "click", toggle);
    on("#plNext", "click", next);
    on("#plPrev", "click", prev);
    on("#plShuf", "click", () => toggleShuffle());
    on("#plClose", "click", stop);
    on("#plQueue", "click", () => { const p = q("#plQueuePanel"); p.hidden = !p.hidden; paintQueue(); });
    on("#plQueueClose", "click", () => { q("#plQueuePanel").hidden = true; });
    on("#plQueueClear", "click", () => { P.order = P.order.slice(0, P.pos + 1); changed(); });
    on("#plRate", "change", (e) => setRate(e.target.value));
    on("#plQueueList", "click", (e) => {
      const j = e.target.closest("[data-q-jump]"), d = e.target.closest("[data-q-del]");
      if (j) jump(Number(j.dataset.qJump)); else if (d) removeAt(Number(d.dataset.qDel));
    });
    on("#plSeek", "input", (e) => { audio.currentTime = Number(e.target.value); });
    audio.addEventListener("seeked", () => save(true));
    on("#plVol", "input", (e) => setVol(e.target.value));
    on("#plVol", "change", () => save(true));
    try { let v = parseFloat(localStorage.getItem("inkwell-volpos")); if (!(v >= 0 && v <= 1)) { const old = parseFloat(localStorage.getItem("inkwell-volume")); v = old > 0 && old <= 1 ? Math.max(0, 1 + (20 * Math.log10(old)) / 36) : 1; } setVol(v); if (q("#plVol")) q("#plVol").value = v; } catch (e) {}
    audio.addEventListener("play", () => { if (q("#plPlay")) q("#plPlay").textContent = "❚❚"; save(); });
    audio.addEventListener("pause", () => { if (q("#plPlay")) q("#plPlay").textContent = "▶"; save(); });
    audio.addEventListener("ended", () => { if (cur() && cur().ab && P.pos >= P.order.length - 1) saveAbPos(true); next(); });
    audio.addEventListener("timeupdate", () => {
      if (q("#plSeek")) { q("#plSeek").max = audio.duration || 0; q("#plSeek").value = audio.currentTime; }
      if (q("#plTime")) q("#plTime").textContent = `${fmt(audio.currentTime)} / ${fmt(audio.duration)}`;
      if (q("#plFill")) q("#plFill").style.width = (audio.duration ? (audio.currentTime / audio.duration) * 100 : 0) + "%";
      if (Date.now() - lastSaved > 5000) save(true);
      if (cur() && cur().ab && Date.now() - lastAbSave > 5000) saveAbPos();
    });
    audio.addEventListener("pause", () => saveAbPos());
    // pick up where the other window left off (paused) if nothing is loaded yet
    fetch("/api/player").then((r) => r.json()).then((st) => { if (!P.tracks.length && st && st.tracks && st.tracks.length) restore(st, false); }).catch(() => {});
    paint();
  }

  return { bind, startCmdPolling, seek, pause, setVolume, setRate, playAudiobook, nowPlaying, get remote() { return remote; }, playList, playNext, addToQueue, toggleShuffle, toggle, next, prev, stop, state, restore, fmt, get shuffle() { return P.shuffle; }, current: cur };
})();
