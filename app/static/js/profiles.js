/* Profiles: everyone who uses the library. The face in the top bar says who's using this computer; each profile keeps
   its own place in every book and film, its own notes and journal, and can hide things from the other profiles.
   A phone logs in as a profile too (in its Settings), and sees the same. */
const Profiles = (() => {
  const FACES = ["🦉", "🦊", "🐢", "🐙", "🦄", "🐝", "🐸", "🦖", "🐧", "🌵", "🍄", "🚀"];
  let list = [], cur = 1;
  const me = () => list.find((p) => p.id === cur) || list[0] || { id: 1, name: "Me", face: "🦉" };

  async function load() {
    try { const r = await api.get("/api/profiles"); list = r.profiles; cur = r.current; } catch (e) {}
    paint();
    if (me().locked && !unlocked(cur)) lockScreen();
  }

  /* a PIN (or password): the profile is asked for it when someone switches to it, and when the app opens on it */
  const unlocked = (id) => { try { return sessionStorage.getItem("babel-unlocked") === String(id); } catch (e) { return false; } };
  const remember = (id) => { try { sessionStorage.setItem("babel-unlocked", String(id)); } catch (e) {} };
  // fields: [[name, label], …] → {name: value} or null
  function askPin(title, text, fields = [["pin", "PIN"]], ok = "OK", cls = "prof-pin") {
    return new Promise((done) => {
      const w = document.createElement("div");
      w.className = "keep-ask " + cls;
      w.innerHTML = `<form class="ka-card" role="dialog"><h3>${esc(title)}</h3>${text ? `<p>${text}</p>` : ""}
        ${fields.map(([n, l]) => `<label class="pin-field"><span>${esc(l)}</span><input type="password" name="${n}" autocomplete="off" maxlength="64"></label>`).join("")}
        <div class="ka-row"><button class="btn primary">${esc(ok)}</button>${cls === "prof-lock" ? "" : `<button type="button" class="btn" data-x>Cancel</button>`}</div></form>`;
      const end = (v) => { w.remove(); removeEventListener("keydown", key, true); done(v); };
      const key = (e) => { if (e.key === "Escape" && cls !== "prof-lock") { e.stopPropagation(); end(null); } };
      w.querySelector("form").onsubmit = (e) => { e.preventDefault(); end(Object.fromEntries(fields.map(([n]) => [n, w.querySelector(`[name=${n}]`).value]))); };
      w.onclick = (e) => { if (e.target.closest("[data-x]") || (e.target === w && cls !== "prof-lock")) end(null); };
      addEventListener("keydown", key, true);
      document.body.append(w);
      w.querySelector("input").focus();
    });
  }
  // the app opened on a profile with a PIN: its PIN, or another profile
  async function lockScreen() {
    const others = list.filter((p) => p.id !== cur);
    for (;;) {
      const a = await askPin(`${me().face} ${me().name}'s library`, `This profile has a PIN.${others.length ? ` Not ${esc(me().name)}? ${others.map((p) => `<button type="button" class="btn sm" data-lock-use="${p.id}">${esc(p.face)} ${esc(p.name)}</button>`).join(" ")}` : ""}`, [["pin", "PIN"]], "Open", "prof-lock");
      try { await api.send("POST", "/api/profiles/unlock", { pin: a.pin }); remember(cur); return; } catch (err) { toast(err.message, "error"); }
    }
  }
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-lock-use]");
    if (!b) return;
    e.preventDefault(); e.stopPropagation();
    b.closest(".prof-lock").remove();
    use(Number(b.dataset.lockUse)).then((went) => went || lockScreen(), (err) => { toast(err.message, "error"); lockScreen(); });
  }, true);
  async function pinSettings() {
    const p = me();
    const a = await askPin(p.locked ? `${p.name}'s PIN` : `A PIN for ${p.name}`,
      p.locked ? "Type the new one, or leave it empty to take the PIN off." : "Whoever switches to this profile (here or on a phone) will need it, and so will this app when it opens on it. Numbers or a password, 4 or more characters.",
      p.locked ? [["old", "Current PIN"], ["pin", "New PIN (empty: none)"], ["again", "New PIN again"]] : [["pin", "PIN"], ["again", "Again"]], "Save");
    if (!a) return;
    if (a.pin !== a.again) return toast("The two PINs don't match", "error");
    try {
      Object.assign(p, await api.send("POST", "/api/profiles/pin", { pin: a.pin, old: a.old }));
      if (p.locked) remember(p.id);
      toast(p.locked ? "PIN saved" : "PIN taken off"); open();
    } catch (err) { toast(err.message, "error"); }
  }
  function paint() {
    const b = $("#profBtn");
    if (!b) return;
    b.textContent = me().face;
    b.title = `${me().name}'s library (switch profile)`;
  }
  function close() { const m = $("#profMenu"); if (m) m.remove(); }
  function open() {
    close();
    const m = document.createElement("div");
    m.id = "profMenu";
    m.className = "prof-menu";
    m.innerHTML = `<h4>Who's using Babel's Library?</h4>
      ${list.map((p) => `<div class="prof-row ${p.id === cur ? "on" : ""}">
        <button class="prof-face" data-pface="${p.id}" title="Change the picture">${esc(p.face || "🙂")}</button>
        <span class="prof-who"><input data-pname="${p.id}" value="${esc(p.name)}" maxlength="40" aria-label="Name">${(p.devices || []).length ? `<small title="Phones and web apps using this profile">📱 ${esc(p.devices.join(", "))}</small>` : ""}</span>
        ${p.locked ? `<span title="Has a PIN">🔒</span>` : ""}
        ${p.id === cur ? `<span class="badge">In use</span>` : `<button class="btn sm" data-puse="${p.id}">Use</button>`}
        ${p.id !== 1 ? `<button class="btn sm danger" data-pdel="${p.id}" title="Remove this profile">✕</button>` : ""}</div>`).join("")}
      <button class="btn sm prof-pinbtn" data-ppin>🔑 ${me().locked ? `Change or remove ${esc(me().name)}'s PIN` : `Give ${esc(me().name)} a PIN`}</button>
      <form class="row" id="profNewForm"><input id="profNew" maxlength="40" placeholder="A name" autocomplete="off" style="flex:1"><button class="btn sm">＋ Add</button></form>
      <p class="hint">Each profile has its own place in every book and film, its own notes and journal, and the Bulletin's challenge. In an item's details, <b>🔒 Only me</b> hides it from the other profiles.</p>`;
    document.body.append(m);
    const r = $("#profBtn").getBoundingClientRect();
    m.style.top = r.bottom + 6 + "px";
    m.style.right = Math.max(8, innerWidth - r.right) + "px";
  }
  async function use(id) {
    const p = list.find((x) => x.id === id);
    let pin;
    if (p && p.locked) {
      const a = await askPin(`${p.face} ${p.name}'s PIN`, "");
      if (!a) return;
      pin = a.pin;
    }
    await api.send("POST", "/api/profiles/current", { id, pin });
    remember(id);
    location.reload();
    return true;          // everything (places, notes, journal, hidden things) is now this profile's
  }
  document.addEventListener("click", async (e) => {
    const t = e.target;
    if (t.closest("#profBtn")) return $("#profMenu") ? close() : open();
    const m = $("#profMenu");
    if (!m) return;
    if (!m.contains(t)) return close();
    try {
      const u = t.closest("[data-puse]"); if (u) { close(); return await use(Number(u.dataset.puse)); }
      if (t.closest("[data-ppin]")) { close(); return pinSettings(); }
      const f = t.closest("[data-pface]");
      if (f) {
        const p = list.find((x) => x.id === Number(f.dataset.pface));
        p.face = FACES[(FACES.indexOf(p.face) + 1) % FACES.length];
        await api.send("PATCH", `/api/profiles/${p.id}`, { face: p.face });
        f.textContent = p.face; paint(); return;
      }
      const d = t.closest("[data-pdel]");
      if (d) {
        const p = list.find((x) => x.id === Number(d.dataset.pdel));
        if (!confirm(`Remove ${p.name}'s profile? Their places, notes and journal go with it. What they hid becomes ${list[0].name}'s. (The library's files aren't touched.)`)) return;
        let pin;
        if (p.locked) { const a = await askPin(`${p.name}'s PIN`, "Removing a profile with a PIN needs its PIN."); if (!a) return; pin = a.pin; }
        const r = await api.send("DELETE", `/api/profiles/${p.id}`, { pin });
        list = r.profiles;
        if (r.current !== cur) return location.reload();
        open(); paint();
      }
    } catch (err) { toast(err.message, "error"); }
  });
  document.addEventListener("change", async (e) => {
    const n = e.target.closest("[data-pname]");
    if (!n) return;
    const p = list.find((x) => x.id === Number(n.dataset.pname));
    if (!p || !n.value.trim()) return;
    try { Object.assign(p, await api.send("PATCH", `/api/profiles/${p.id}`, { name: n.value.trim() })); paint(); } catch (err) { toast(err.message, "error"); }
  });
  document.addEventListener("submit", async (e) => {
    if (e.target.id !== "profNewForm") return;
    e.preventDefault();
    const name = $("#profNew").value.trim();
    if (!name) return toast("Type a name first");
    try {
      const p = await api.send("POST", "/api/profiles", { name, face: FACES[list.length % FACES.length] });
      list.push(p); open();
      toast(`Added ${p.face} ${p.name}. Press Use to switch.`);
    } catch (err) { toast(err.message, "error"); }
  });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") close(); });

  /* the item drawer: "Only me" (hide it from the other profiles) */
  function drawerToggle(it) {
    return `<label class="watched-box ${it.private_to ? "on" : ""}" title="${list.length < 2 ? "Hide this from profiles you add later (there's only one profile now)" : "Hide this from the other profiles (on this computer and their phones)"}"><input type="checkbox" id="dPrivate" ${it.private_to ? "checked" : ""}><span>🔒 Only me</span></label>`;
  }
  // one volume of a series (or episode of a show): just this one, or the whole series?
  async function withSeries(it, on) {
    if (!inSeries(it)) return [it];
    const k = seriesKey(it.series);
    const rest = S.items.filter((x) => x.id !== it.id && inSeries(x) && seriesKey(x.series) === k && !!x.private_to !== on);
    if (!rest.length) return [it];
    const whole = it.kind === "tv" ? "the whole show" : "the whole series";
    const a = await askKeep(on ? `Hide ${whole}?` : `Show ${whole} again?`,
      `“${it.series}” has ${rest.length} more ${rest.length > 1 ? "items" : "item"} in the library.`,
      [[`Just this one`, "one"], [`${whole[0].toUpperCase()}${whole.slice(1)} (${rest.length + 1})`, "all", "primary"]]);
    return a == null ? null : a === "all" ? [it, ...rest] : [it];
  }
  document.addEventListener("change", async (e) => {
    if (e.target.id !== "dPrivate" || !S.openId) return;
    const on = e.target.checked, it = S.items.find((x) => x.id === S.openId);
    try {
      const these = it ? await withSeries(it, on) : [{ id: S.openId }];
      if (!these) { e.target.checked = !on; return; }
      await Promise.all(these.map((x) => api.send("PATCH", `/api/items/${x.id}`, { private: on })));
      e.target.closest(".watched-box").classList.toggle("on", on);
      const n = these.length;
      toast(on ? `${n > 1 ? n + " items h" : "H"}idden from the other profiles` : `${n > 1 ? n + " items" : "It"} can be seen by everyone again`);
      S._forceRender = true; loadItems();
    } catch (err) { toast(err.message, "error"); }
  });

  load();
  return { load, drawerToggle, me: () => me(), current: () => cur };
})();
