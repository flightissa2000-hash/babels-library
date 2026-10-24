/* Custom collections, multi-select, and Checkout (copy files out to any folder). */
window.Coll = (() => {
  let list = [];
  S.coll = null;          // collection id being viewed
  S.selecting = false;
  S.sel = new Set();      // selected item ids

  const byId = (id) => list.find((c) => c.id === id);
  const nameOf = (id) => (byId(id) || {}).name || "";

  async function load() {
    try { list = await api.get("/api/collections"); } catch (e) { list = []; }
    if (S.coll && S.coll !== "wish" && !byId(S.coll)) S.coll = null;
    paintBar();
  }

  /* ---------- collections bar ---------- */
  function paintBar() {
    const bar = $("#collBar");
    if (!bar) return;
    const ak = areaKinds();
    const countIn = (c) => S.items.filter((i) => (i.collections || []).includes(c.id) && ak.includes(i.kind)).length;
    const cur = byId(S.coll);
    const total = S.items.filter((i) => ak.includes(i.kind)).length;
    bar.innerHTML = `<div class="cb-panel">
      <span class="cb-lbl"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 3h12a1 1 0 0 1 1 1v17l-7-4.5L5 21V4a1 1 0 0 1 1-1z"/></svg>Collections</span>
      <div class="cb-chips">
        <button class="cchip all ${!S.coll ? "on" : ""}" data-coll=""><b class="cc-ico">✦</b>Everything<span class="cc-n">${total}</span></button>
        ${(() => { const n = S.items.filter((i) => i.wanted && !i.has_file && ak.includes(i.kind)).length; return n ? `<button class="cchip wish ${S.coll === "wish" ? "on" : ""}" data-coll="wish" style="--cc:#e8a33d"><b class="cc-ico">★</b>Wishlist<span class="cc-n">${n}</span></button>` : ""; })()}
        ${list.map((c) => `<button class="cchip ${S.coll === c.id ? "on" : ""}" data-coll="${c.id}" style="--cc:${c.color || "var(--accent)"}"><i></i>${esc(c.name)}<span class="cc-n">${countIn(c)}</span></button>`).join("")}
        <button class="cchip add" data-coll-new title="Make a new collection"><b class="cc-ico">+</b>New</button>
      </div>
      <span class="cb-side">
        ${cur ? `<span class="cb-tools"><button class="cb-tool" data-coll-play title="Play the music in this collection">▶ Play</button><button class="cb-tool" data-coll-out>Check out…</button><button class="cb-tool" data-coll-rename>Rename</button><button class="cb-tool danger" data-coll-del>Delete</button></span>` : ""}
        <button class="cb-sel ${S.selecting ? "on" : ""}" id="selBtn" title="Pick items to add to a collection or check out">${S.selecting ? "✓ Done" : "☐ Select"}</button>
      </span>
    </div>`;
    const music = cur && S.items.some((i) => i.kind === "music" && (i.collections || []).includes(cur.id));
    const pb = bar.querySelector("[data-coll-play]");
    if (pb) pb.hidden = !music;
  }

  const COLORS = ["#d9534f", "#e8a33d", "#5cb85c", "#3a9ad9", "#8e6bd1", "#d65db1", "#3bb3a6", "#a0805a"];
  async function create(items) {
    const name = await ask("New collection", "Name", "");
    if (!name) return null;
    const r = await api.send("POST", "/api/collections", { name, color: COLORS[list.length % COLORS.length], items: items || [] });
    await load();
    await loadItems();
    toast(`Made the collection “${name}”${items && items.length ? ` with ${items.length} item${items.length === 1 ? "" : "s"}` : ""}`);
    return r.id;
  }

  /* small prompt dialog (window.prompt is blocked in the desktop app) */
  function ask(title, label, value) {
    return new Promise((resolve) => {
      const d = $("#askDialog");
      $("#askTitle").textContent = title;
      $("#askLabel").textContent = label;
      $("#askInput").value = value || "";
      d.returnValue = "";
      d.showModal();
      $("#askInput").select();
      d.onclose = () => resolve(d.returnValue === "ok" ? $("#askInput").value.trim() : null);
    });
  }

  /* ---------- selection ---------- */
  const idsFor = (el) => {
    if (el.dataset.open) return [Number(el.dataset.open)];
    if (el.dataset.album !== undefined) { const a = Media.albums(S.items).find((x) => x.key === el.dataset.album); return a ? a.tracks.map((t) => t.id) : []; }
    if (el.dataset.series !== undefined) {
      const key = (s) => (s || "Unknown series").toLowerCase().replace(/\((?:19|20)\d\d\)|\b(?:19|20)\d\d\b/g, " ").replace(/[^a-z0-9]+/g, "") || "unknown";
      return S.items.filter((i) => i.kind === "tv" && key(i.series) === el.dataset.series).map((i) => i.id);
    }
    return [];
  };
  function setSelecting(on) {
    S.selecting = on;
    if (!on) S.sel.clear();
    document.body.classList.toggle("selecting", on);
    paintBar();
    paintSel();
  }
  function paintSel() {
    $$("#library [data-open],#library [data-album],#library [data-series]").forEach((el) => {
      const ids = idsFor(el);
      el.classList.toggle("picked", S.selecting && ids.length > 0 && ids.every((i) => S.sel.has(i)));
    });
    const bar = $("#selBar");
    bar.hidden = !S.selecting;
    if (!S.selecting) return;
    const n = S.sel.size;
    const withFile = S.items.filter((i) => S.sel.has(i.id) && i.has_file).length;
    $("#selCount").textContent = n ? `${n} selected` : "Click items to select them";
    $("#selAdd").innerHTML = `<option value="">Add to collection…</option>` + list.map((c) => `<option value="${c.id}">${esc(c.name)}</option>`).join("") + `<option value="new">＋ New collection…</option>`;
    $("#selAdd").disabled = !n;
    $("#selOut").disabled = !withFile;
    $("#selRemove").hidden = !S.coll;
    $("#selRemove").disabled = !n;
    $("#selRemove").textContent = S.coll ? `Remove from “${nameOf(S.coll)}”` : "";
  }
  const shownIds = () => {
    const ids = new Set();
    $$("#library [data-open],#library [data-album],#library [data-series]").forEach((el) => idsFor(el).forEach((i) => ids.add(i)));
    return [...ids];
  };

  /* ---------- checkout ---------- */
  async function checkout(ids) {
    const withFile = S.items.filter((i) => ids.includes(i.id) && i.has_file);
    if (!withFile.length) return toast("None of those have a file to copy.", "error");
    const d = $("#coDialog");
    let saved = ""; try { saved = localStorage.getItem("inkwell-checkout-dir") || ""; } catch (e) {}
    $("#coFolder").value ||= saved;
    $("#coSummary").textContent = `${withFile.length} file${withFile.length === 1 ? "" : "s"} will be copied. The originals stay in your library.` +
      (withFile.length < ids.length ? ` (${ids.length - withFile.length} have no file, like books on your shelf, and are skipped.)` : "");
    d.dataset.ids = JSON.stringify(withFile.map((i) => i.id));
    d.showModal();
  }
  async function runCheckout() {
    const d = $("#coDialog");
    const folder = $("#coFolder").value.trim();
    if (!folder) return toast("Choose a folder first.", "error");
    try {
      const r = await api.send("POST", "/api/checkout", { items: JSON.parse(d.dataset.ids || "[]"), folder, keep_folders: $("#coKeep").checked });
      try { localStorage.setItem("inkwell-checkout-dir", folder); } catch (e) {}
      d.close();
      toast(`Copying ${r.count} item${r.count === 1 ? "" : "s"} to ${folder}…`);
      if (S.selecting) setSelecting(false);
    } catch (e) { toast(e.message, "error"); }
  }

  /* ---------- drawer sections ---------- */
  function drawerSection(it) {
    return `<div class="d-sec"><h4>Collections</h4><div class="coll-picks" data-coll-item="${it.id}">
      ${list.map((c) => `<label class="cpick" style="--cc:${c.color || "var(--accent)"}"><input type="checkbox" data-coll-toggle="${c.id}" ${(it.collections || []).includes(c.id) ? "checked" : ""}><span>${esc(c.name)}</span></label>`).join("")}
      <button class="btn sm" data-coll-new-for="${it.id}">＋ New collection</button></div></div>`;
  }
  function albumSection(key) {
    const a = Media.albums(S.items).find((x) => x.key === key);
    if (!a) return "";
    const ids = a.tracks.map((t) => t.id);
    return `<div class="d-sec"><h4>Collections</h4><div class="coll-picks" data-coll-album="${esc(key)}">
      ${list.map((c) => { const n = ids.filter((i) => (S.items.find((x) => x.id === i)?.collections || []).includes(c.id)).length; return `<label class="cpick" style="--cc:${c.color || "var(--accent)"}"><input type="checkbox" data-coll-toggle="${c.id}" ${n === ids.length ? "checked" : ""} ${n && n < ids.length ? 'data-partial="1"' : ""}><span>${esc(c.name)}</span></label>`; }).join("")}
      <button class="btn sm" data-coll-new-album="${esc(key)}">＋ New collection</button>
      <button class="btn sm" data-checkout-ids="${ids.join(",")}">Check out album…</button></div></div>`;
  }

  /* ---------- events ---------- */
  function bind() {
    // while selecting, a click picks an item instead of opening it
    document.addEventListener("click", (e) => {
      if (!S.selecting) return;
      const el = e.target.closest("#library [data-open],#library [data-album],#library [data-series]");
      if (!el || e.target.closest("[data-tag]")) return;
      e.preventDefault(); e.stopImmediatePropagation();
      const ids = idsFor(el);
      const all = ids.every((i) => S.sel.has(i));
      ids.forEach((i) => (all ? S.sel.delete(i) : S.sel.add(i)));
      paintSel();
    }, true);

    document.addEventListener("click", async (e) => {
      const t = e.target;
      const chip = t.closest("[data-coll]");
      if (chip) { S.coll = chip.dataset.coll === "wish" ? "wish" : chip.dataset.coll ? Number(chip.dataset.coll) : null; paintBar(); render(); return; }
      if (t.closest("#selBtn")) return setSelecting(!S.selecting);
      if (t.closest("[data-coll-new]")) { const id = await create(); if (id) { S.coll = id; paintBar(); render(); } return; }
      if (t.closest("[data-coll-rename]")) {
        const c = byId(S.coll); const n = c && await ask("Rename collection", "Name", c.name);
        if (n) { await api.send("PATCH", `/api/collections/${c.id}`, { name: n }); await load(); }
        return;
      }
      if (t.closest("[data-coll-del]")) {
        const c = byId(S.coll); if (!c) return;
        if (!t.closest("[data-coll-del]").dataset.armed) { const b = t.closest("[data-coll-del]"); b.dataset.armed = "1"; b.textContent = "Click again to delete"; setTimeout(() => { b.dataset.armed = ""; b.textContent = "Delete"; }, 3000); return; }
        await api.send("DELETE", `/api/collections/${c.id}`);
        S.coll = null; await load(); await loadItems();
        toast(`Deleted the collection “${c.name}”. Its items are still in your library.`);
        return;
      }
      if (t.closest("[data-coll-play]")) {
        const tracks = Media.albums(S.items.filter((i) => (i.collections || []).includes(S.coll))).flatMap((a) => a.tracks);
        if (tracks.length) Player.playList(tracks, 0);
        return;
      }
      if (t.closest("[data-coll-out]")) return checkout(S.items.filter((i) => (i.collections || []).includes(S.coll)).map((i) => i.id));
      const co = t.closest("[data-checkout-ids]");
      if (co) return checkout(co.dataset.checkoutIds.split(",").map(Number));
      const nf = t.closest("[data-coll-new-for]");
      if (nf) { await create([Number(nf.dataset.collNewFor)]); openDrawer(Number(nf.dataset.collNewFor), true); return; }
      const na = t.closest("[data-coll-new-album]");
      if (na) { const a = Media.albums(S.items).find((x) => x.key === na.dataset.collNewAlbum); if (a) { await create(a.tracks.map((x) => x.id)); Media.openAlbum(a.key); } return; }
      if (t.closest("#selAll")) { shownIds().forEach((i) => S.sel.add(i)); paintSel(); return; }
      if (t.closest("#selNone")) { S.sel.clear(); paintSel(); return; }
      if (t.closest("#selOut")) return checkout([...S.sel]);
      if (t.closest("#selRemove")) {
        await api.send("POST", `/api/collections/${S.coll}/items`, { items: [...S.sel], remove: true });
        toast(`Removed ${S.sel.size} from “${nameOf(S.coll)}”`);
        S.sel.clear(); await load(); await loadItems(); paintSel();
        return;
      }
      if (t.closest("#selDone")) return setSelecting(false);
      if (t.closest("#coGo")) return runCheckout();
    });

    document.addEventListener("change", async (e) => {
      const tg = e.target.closest("[data-coll-toggle]");
      if (tg) {
        const box = tg.closest("[data-coll-item],[data-coll-album]");
        const ids = box.dataset.collItem ? [Number(box.dataset.collItem)] : (Media.albums(S.items).find((x) => x.key === box.dataset.collAlbum)?.tracks || []).map((t) => t.id);
        const cid = Number(tg.dataset.collToggle);
        await api.send("POST", `/api/collections/${cid}/items`, { items: ids, remove: !tg.checked });
        toast(`${tg.checked ? "Added to" : "Removed from"} “${nameOf(cid)}”`);
        await load(); await loadItems();
        return;
      }
      if (e.target.id === "selAdd" && e.target.value) {
        const v = e.target.value; e.target.value = "";
        const ids = [...S.sel];
        if (v === "new") { await create(ids); }
        else { await api.send("POST", `/api/collections/${v}/items`, { items: ids }); toast(`Added ${ids.length} to “${nameOf(Number(v))}”`); await load(); await loadItems(); }
        paintSel();
      }
    });
    document.addEventListener("keydown", (e) => { if (e.key === "Escape" && S.selecting && $("#reader").hidden && !document.querySelector("dialog[open]")) setSelecting(false); });
    $("#coBrowse").onclick = async () => {
      try { const r = await api.send("POST", "/api/pick-folder", {}); if (r.path) $("#coFolder").value = r.path; } catch (err) { toast(err.message, "error"); }
    };
    load();
  }

  return { load, bind, paintBar, paintSel, drawerSection, albumSection, nameOf, get list() { return list; } };
})();
