// If the drive holding the library (often a USB drive) drops out, say so instead of failing silently, and reload the
// window once it's back. Everything this needs is already loaded: while the drive is gone nothing more can be fetched.
(function () {
  const realFetch = window.fetch.bind(window);
  let watching = false, box = null;

  function show() {
    if (box) return;
    box = document.createElement("div");
    box.setAttribute("role", "alertdialog");
    box.style.cssText = "position:fixed;inset:0;z-index:2147483647;display:flex;align-items:center;justify-content:center;" +
      "background:rgba(20,28,44,.72);font:16px/1.5 Nunito,'Segoe UI',sans-serif;color:#22304a";
    box.innerHTML = '<div style="background:#fff;border:3px solid #22304a;border-radius:18px;padding:22px 26px;max-width:420px;' +
      'box-shadow:0 6px 0 #22304a;text-align:center"><div style="font-size:20px;font-weight:800;margin-bottom:6px">' +
      "Your library drive isn't connected</div><div>Plug it back in. Babel's Library will carry on by itself as soon as " +
      "it's back.</div><div style=\"margin-top:10px;font-size:13px;opacity:.7\">Waiting for the drive…</div></div>";
    document.body.appendChild(box);
  }

  async function ping() {
    const ctl = new AbortController();
    const t = setTimeout(() => ctl.abort(), 4000);
    try {
      const r = await realFetch("/api/ping", { cache: "no-store", signal: ctl.signal });
      return (await r.json()).drive_ok;
    } catch (e) {
      return null; // the app itself isn't answering (closing, or busy): not a drive problem
    } finally {
      clearTimeout(t);
    }
  }

  async function check() {
    if (watching) return;
    watching = true;
    try {
      if ((await ping()) !== false) return;
      show();
      // the drive is gone: wait for it, then start the page afresh (its database and files were cut off mid-way)
      while ((await ping()) !== true) await new Promise((r) => setTimeout(r, 3000));
      location.reload();
    } finally {
      watching = false;
    }
  }

  window.fetch = async function (...args) {
    try {
      const r = await realFetch(...args);
      if (r.status === 503) {
        r.clone().json().then((d) => d && d.drive_missing && check(), () => {});
      }
      return r;
    } catch (e) {
      if (e && e.name !== "AbortError") check();
      throw e;
    }
  };
  window.inkwellDriveCheck = check;
})();
