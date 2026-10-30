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
        <input data-pname="${p.id}" value="${esc(p.name)}" maxlength="40" aria-label="Name">
        ${p.id === cur ? `<span class="badge">In use</span>` : `<button class="btn sm" data-puse="${p.id}">Use</button>`}
        ${p.id !== 1 ? `<button class="btn sm danger" data-pdel="${p.id}" title="Remove this profile">✕</button>` : ""}</div>`).join("")}
      <form class="row" id="profNewForm"><input id="profNew" maxlength="40" placeholder="A name" autocomplete="off" style="flex:1"><button class="btn sm">＋ Add</button></form>
      <p class="hint">Each profile has its own place in every book and film, its own notes and journal, and the Bulletin's challenge. In an item's details, <b>🔒 Only me</b> hides it from the other profiles.</p>`;
    document.body.append(m);
    const r = $("#profBtn").getBoundingClientRect();
    m.style.top = r.bottom + 6 + "px";
    m.style.right = Math.max(8, innerWidth - r.right) + "px";
  }
  async function use(id) {
    await api.send("POST", "/api/profiles/current", { id });
    location.reload();          // everything (places, notes, journal, hidden things) is now this profile's
  }
  document.addEventListener("click", async (e) => {
    const t = e.target;
    if (t.closest("#profBtn")) return $("#profMenu") ? close() : open();
    const m = $("#profMenu");
    if (!m) return;
    if (!m.contains(t)) return close();
    try {
      const u = t.closest("[data-puse]"); if (u) return use(Number(u.dataset.puse));
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
        const r = await api.send("DELETE", `/api/profiles/${p.id}`);
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
    if (list.length < 2 && !it.private_to) return "";
    return `<label class="watched-box ${it.private_to ? "on" : ""}" title="Hide this from the other profiles (on this computer and their phones)"><input type="checkbox" id="dPrivate" ${it.private_to ? "checked" : ""}><span>🔒 Only me</span></label>`;
  }
  document.addEventListener("change", async (e) => {
    if (e.target.id !== "dPrivate" || !S.openId) return;
    try {
      await api.send("PATCH", `/api/items/${S.openId}`, { private: e.target.checked });
      e.target.closest(".watched-box").classList.toggle("on", e.target.checked);
      toast(e.target.checked ? `Hidden from the other profiles` : "Everyone can see it again");
      S._forceRender = true; loadItems();
    } catch (err) { toast(err.message, "error"); }
  });

  load();
  return { load, drawerToggle, me: () => me(), current: () => cur };
})();
