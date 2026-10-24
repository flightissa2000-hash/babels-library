/* Comic archives (CBZ, CBR, CB7, CBT): pages come from the server one at a time; libarchive.js in the app is the fallback. */
window.Comic = (() => {
  let libP = null;
  const IMG = /\.(jpe?g|png|webp|gif|bmp|avif)$/i;
  const natural = (a, b) => a.localeCompare(b, undefined, { numeric: true, sensitivity: "base" });

  function lib() {
    if (!libP) {
      libP = import(new URL("vendor/libarchive/libarchive.js", location.href).href).then((m) => {
        m.Archive.init({ workerUrl: new URL("vendor/libarchive/worker-bundle.js", location.href).href });
        return m.Archive;
      });
    }
    return libP;
  }

  /* Fast path: the server hands out one page at a time (no need to download a whole 300 MB – 1 GB archive). */
  async function openServer(itemId) {
    let info = await fetch(`/api/items/${itemId}/comic`).then((r) => r.json());
    if (info.error) throw new Error(info.error);
    for (let k = 0; !info.count && !info.ready && k < 60; k++) {  // listing still in progress
      await new Promise((r) => setTimeout(r, 500));
      info = await fetch(`/api/items/${itemId}/comic`).then((r) => r.json());
      if (info.error) throw new Error(info.error);
    }
    const blobs = new Map();
    const src = (i) => `/api/items/${itemId}/comic/${i}?n=${info.count}`;
    return {
      count: info.count,
      async url(i) {
        if (info.ready) return src(i);
        // still unpacking (RAR / 7z): wait for this page
        if (!blobs.has(i)) blobs.set(i, (async () => {
          for (let k = 0; k < 240; k++) {
            const r = await fetch(src(i));
            if (r.ok) return URL.createObjectURL(await r.blob());
            if (r.status !== 503) throw new Error("Page couldn't be read.");
            await new Promise((res) => setTimeout(res, 500));
          }
          throw new Error("Unpacking is taking too long.");
        })());
        return blobs.get(i);
      },
      async comicInfo() { return fetch(`/api/items/${itemId}/comic-info`).then((r) => r.text()).catch(() => ""); },
      close() { for (const p of blobs.values()) p.then((u) => URL.revokeObjectURL(u)).catch(() => {}); },
    };
  }

  async function open(itemId) {
    try { return await openServer(itemId); }
    catch (e) { console.warn("comic: server pages unavailable, reading the whole file in the app", e); }
    const r = await fetch(`/api/items/${itemId}/file`);
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || "Couldn't load the file.");
    const blob = await r.blob();
    const Archive = await lib();
    const arc = await Archive.open(new File([blob], "comic"));
    const entries = await arc.getFilesArray();
    const full = (e) => (e.path || "") + e.file.name;
    const pages = entries.filter((e) => IMG.test(e.file.name) && !full(e).startsWith("__MACOSX") && !e.file.name.startsWith("."))
      .sort((a, b) => natural(full(a), full(b)));
    const info = entries.find((e) => /^comicinfo\.xml$/i.test(e.file.name));
    const cache = new Map();
    return {
      count: pages.length,
      url(i) {
        if (!cache.has(i)) cache.set(i, pages[i].file.extract().then((f) => URL.createObjectURL(f)));
        return cache.get(i);
      },
      async comicInfo() {
        if (!info) return "";
        return await (await info.file.extract()).text();
      },
      close() {
        for (const p of cache.values()) p.then((u) => URL.revokeObjectURL(u)).catch(() => {});
        try { arc.close && arc.close(); } catch (e) {}
      },
    };
  }

  /* Make a small cover from page 1 and, for CBR files, hand the server any ComicInfo.xml inside. */
  async function makeCover(item) {
    const c = await open(item.id);
    try {
      if (!c.count) return false;
      const img = new Image();
      img.src = await c.url(0);
      await img.decode();
      const w = 420, h = Math.round(img.naturalHeight * (w / img.naturalWidth));
      const cv = document.createElement("canvas");
      cv.width = w; cv.height = h;
      cv.getContext("2d").drawImage(img, 0, 0, w, h);
      const blob = await new Promise((r) => cv.toBlob(r, "image/jpeg", 0.85));
      await fetch(`/api/items/${item.id}/cover`, { method: "POST", body: blob });
      if (item.file_type !== "cbz") {
        const xml = await c.comicInfo();
        if (xml) await fetch(`/api/items/${item.id}/comicinfo`, { method: "POST", body: xml });
      }
      return true;
    } finally {
      c.close();
    }
  }

  /* CBR comics with no creators yet: send the server their ComicInfo.xml once (it also looks the creators up online). */
  async function sendInfo(item) {
    const c = await open(item.id);
    try {
      const xml = (await c.comicInfo()) || "";
      await fetch(`/api/items/${item.id}/comicinfo`, { method: "POST", body: xml });
    } finally { c.close(); }
  }

  return { open, makeCover, sendInfo };
})();
