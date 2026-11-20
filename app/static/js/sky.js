/* The star chart layout: your library as the real night sky. Each group (a genre, an author, a year... whatever the
   Group menu says) is a region of the sky: its single books are one real constellation and each of its series is a
   neighbouring one, the series' books along the figure's own lines, in order. Search lights up what matches; the
   atlas lists region ▸ constellation ▸ books. The sky turns under the mouse like a planetarium dome (drag to turn it, the
   wheel to zoom, double-click a constellation to fly to it), with the real Milky Way behind it (ESO's all-sky photo,
   mapped onto the sky in a WebGL shader). How bright a star burns is how far you've read it.
   Star data: d3-celestial (Olaf Frohn, BSD-3) from the Hipparcos catalogue. Milky Way: ESO/S. Brunier (CC BY 4.0). */
const Sky = window.Sky = (() => {
  const D2R = Math.PI / 180;
  let DATA = null, loading = null;
  const load = () => DATA ? Promise.resolve(DATA) : (loading ||= fetch("sky/sky.json").then((r) => r.json()).then((d) => (DATA = d)));
  const vec = (ra, dec) => { const a = ra * D2R, d = dec * D2R, c = Math.cos(d); return [c * Math.cos(a), c * Math.sin(a), Math.sin(d)]; };
  const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
  const reduced = () => matchMedia("(prefers-reduced-motion: reduce)").matches;

  // the camera: looking at (ra, dec) from inside the sphere; k = zoom (pixels per stereographic unit)
  let V = null;               // the current view: {root, cv, ctx, gl, W, H, dpr, ra, dec, k, books, cons, hover, ...}

  function basis(ra, dec) {
    const a = ra * D2R, d = dec * D2R;
    const f = vec(ra, dec), e = [-Math.sin(a), Math.cos(a), 0], n = [-Math.sin(d) * Math.cos(a), -Math.sin(d) * Math.sin(a), Math.cos(d)];
    return { f, e, n };
  }
  function project(v, B) {
    const z = dot(v, B.f);
    if (z < -0.2) return null;                                  // (behind you)
    const s = V.k / (1 + z);
    return [V.W / 2 - dot(v, B.e) * 2 * s, V.H / 2 - dot(v, B.n) * 2 * s, z];
  }

  /* ---------------- which book is which star ---------------- */
  function storeKey() { return `inkwell-sky4-${S.area}-${S.groupBy}`; }
  /* Each genre (or whatever the Group menu groups by) is a region of the sky: its books that aren't in a series take
     one constellation, and each of its series takes another right next door, so a genre and its series sit together
     like a country on a map. Every book is placed once only, in the first group it turns up in. */
  function assign(groups) {
    let saved = {};
    try { saved = JSON.parse(localStorage.getItem(storeKey()) || "{}"); } catch (e) {}
    const gMap = saved.g || {}, sMap = saved.s || {};
    const cons = DATA.cons.map((c) => ({ ...c, cap: c.stars.length, v: vec(c.c[0], c.c[1]) }));
    const byId = Object.fromEntries(cons.map((c) => [c.id, c]));
    const taken = new Set(), out = [], regions = [];
    const ang = (a, b) => Math.acos(Math.max(-1, Math.min(1, dot(a.v, b.v))));
    // the units: per group, its loose books and each of its series
    const seen = new Set(), byGroup = [];
    for (const [name, items] of groups) {
      const g = { name, loose: [], series: [] };
      for (const run of seriesRuns(seriesTogether(items))) {
        const fresh = run.filter((it) => !seen.has(it.id));
        fresh.forEach((it) => seen.add(it.id));
        if (fresh.length > 1 && inSeries(fresh[0])) g.series.push({ key: "s:" + seriesKey(fresh[0].series), label: fresh[0].series, group: name, series: true, items: fresh });
        else g.loose.push(...fresh);
      }
      if (g.loose.length || g.series.length) byGroup.push(g);
    }
    // more units than constellations: the smallest series go back in with their group's loose books
    const count = () => byGroup.reduce((t, g) => t + g.series.length + (g.loose.length ? 1 : 0), 0);
    while (count() > cons.length) {
      let sm = null, home = null;
      for (const g of byGroup) for (const u of g.series) if (!sm || u.items.length < sm.items.length) { sm = u; home = g; }
      if (!sm) break;
      home.series = home.series.filter((u) => u !== sm); home.loose.push(...sm.items);
    }
    byGroup.sort((x, y) => (y.loose.length + y.series.reduce((t, u) => t + u.items.length, 0)) - (x.loose.length + x.series.reduce((t, u) => t + u.items.length, 0)));
    const free = () => cons.filter((c) => !taken.has(c.id));
    const seeds = [];
    function place(u, c, part) {
      taken.add(c.id); gMap[part ? `${u.key} (${part + 1})` : u.key] = c.id;
      const here = u.items.slice(0, c.cap);
      const used = new Set(), at = new Map();
      if (!u.series) for (const it of here) { const st = sMap[it.id]; if (st && st.c === c.id && st.i < c.cap && !used.has(st.i)) { used.add(st.i); at.set(it.id, st.i); } }
      let next = 0;
      for (const it of here) { if (at.has(it.id)) continue; while (used.has(next)) next++; used.add(next); at.set(it.id, next); }   // (a series lies along the figure in order)
      for (const it of here) sMap[it.id] = { c: c.id, i: at.get(it.id) };
      const g = { c, group: u.group, label: part ? `${u.label} (${part + 1})` : u.label, series: u.series, items: here.map((it) => ({ it, star: c.stars[at.get(it.id)] })) };
      out.push(g);
      return { g, rest: u.items.slice(c.cap) };
    }
    // a unit next to its region: the stored constellation if it's still free, else the nearest free one that holds it
    function near(u, centre) {
      const need = u.items.length, st = byId[gMap[u.key]];
      if (st && !taken.has(st.id)) return st;
      const f = free().sort((x, y) => ang(x, centre) - ang(y, centre));
      return (u.series ? f.slice(0, 6).find((c) => c.fig >= need) : null) || f.slice(0, 8).find((c) => c.cap >= need) || f.find((c) => c.cap >= need) || f[0];
    }
    for (const grp of byGroup) {
      const units = [...(grp.loose.length ? [{ key: grp.name, label: grp.name, group: grp.name, series: false, items: grp.loose }] : []), ...grp.series.sort((x, y) => y.items.length - x.items.length)];
      const first = units[0], need = first.items.length;
      // the region's heart: where it was before, else a well-known constellation big enough, as far as can be from the other regions
      let seed = byId[gMap[first.key]];
      if (!seed || taken.has(seed.id)) {
        const f = free(), fits = f.filter((c) => c.cap >= (first.series ? need : need * 1.5) && (!first.series || c.fig >= need));
        const pool = (fits.filter((c) => c.rank === 1).length ? fits.filter((c) => c.rank === 1) : fits.length ? fits : f);
        const far = (c) => (seeds.length ? Math.min(...seeds.map((s2) => ang(c, s2))) : c.cap / 200);
        seed = pool.sort((x, y) => far(y) - far(x))[0];
      }
      if (!seed) break;
      seeds.push(seed);
      const region = { name: grp.name, cons: [] };
      for (const u of units) {
        let c = u === first ? seed : near(u, seed), part = 0, rest;
        if (!c) break;
        ({ rest } = place(u, c, part)); region.cons.push(out[out.length - 1]);
        while (rest.length) {                 // (too many for one constellation: the next one along)
          part++;
          const u2 = { ...u, items: rest }, c2 = near(u2, seed);
          if (!c2) break;
          ({ rest } = place(u2, c2, part)); region.cons.push(out[out.length - 1]);
        }
      }
      // the region's name sits at the middle of its constellations
      const m = region.cons.reduce((t, g) => [t[0] + g.c.v[0] * g.items.length, t[1] + g.c.v[1] * g.items.length, t[2] + g.c.v[2] * g.items.length], [0, 0, 0]);
      const l = Math.hypot(...m) || 1;
      region.v = m.map((x) => x / l);
      region.n = region.cons.reduce((t, g) => t + g.items.length, 0);
      regions.push(region);
    }
    try { localStorage.setItem(storeKey(), JSON.stringify({ g: gMap, s: sMap })); } catch (e) {}
    out.regions = regions;
    return out;
  }

  /* ---------------- the Milky Way photo, on the sky (WebGL) ---------------- */
  const VS = "attribute vec2 p;void main(){gl_Position=vec4(p,0.,1.);}";
  const FS = `precision highp float;
    uniform vec2 res; uniform float k; uniform vec3 E,N,F; uniform sampler2D tex; uniform float glow;
    const mat3 G = mat3(-0.0548755604,0.4941094279,-0.8676661490, -0.8734370902,-0.4448296300,-0.1980763734, -0.4838350155,0.7469822445,0.4559837762);
    void main(){
      vec2 s = vec2(gl_FragCoord.x, res.y - gl_FragCoord.y);
      float X = (res.x*0.5 - s.x)/k, Y = (res.y*0.5 - s.y)/k;
      float r2 = X*X + Y*Y, z = (4.0 - r2)/(4.0 + r2);
      vec3 v = normalize(E*(X*(1.0+z)*0.5) + N*(Y*(1.0+z)*0.5) + F*z);
      vec3 g = G * v;
      float l = atan(g.y, g.x), b = asin(clamp(g.z,-1.,1.));
      vec2 uv = vec2(fract(0.5 - l/6.2831853), 0.5 - b/3.14159265);
      vec3 c = texture2D(tex, uv).rgb;
      c = pow(c, vec3(0.92)) * glow;
      gl_FragColor = vec4(c + vec3(0.006,0.008,0.03), 1.0);
    }`;
  function initGL(cv) {
    const gl = cv.getContext("webgl", { antialias: false, alpha: false });
    if (!gl) return null;
    const sh = (t, src) => { const s = gl.createShader(t); gl.shaderSource(s, src); gl.compileShader(s); if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s)); return s; };
    const pr = gl.createProgram();
    gl.attachShader(pr, sh(gl.VERTEX_SHADER, VS)); gl.attachShader(pr, sh(gl.FRAGMENT_SHADER, FS)); gl.linkProgram(pr); gl.useProgram(pr);
    const buf = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
    const loc = gl.getAttribLocation(pr, "p"); gl.enableVertexAttribArray(loc); gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
    const tex = gl.createTexture(); gl.bindTexture(gl.TEXTURE_2D, tex);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGB, 1, 1, 0, gl.RGB, gl.UNSIGNED_BYTE, new Uint8Array([2, 3, 10]));
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.REPEAT); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    const img = new Image();
    img.onload = () => { gl.bindTexture(gl.TEXTURE_2D, tex); gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGB, gl.RGB, gl.UNSIGNED_BYTE, img); if (V && V.gl === gl) { V.photo = true; draw(); } };
    img.src = "sky/milkyway.jpg";
    const u = (n) => gl.getUniformLocation(pr, n);
    return { gl, u: { res: u("res"), k: u("k"), E: u("E"), N: u("N"), F: u("F"), glow: u("glow") } };
  }

  /* ---------------- drawing ---------------- */
  const SPRITES = {};
  function sprite(kind) {
    if (SPRITES[kind]) return SPRITES[kind];
    const col = { done: [255, 205, 110], now: [255, 244, 214], next: [150, 200, 255], hold: [210, 180, 255], new: [205, 215, 255] }[kind] || [230, 235, 255];
    const c = document.createElement("canvas"); c.width = c.height = 64;
    const x = c.getContext("2d"), g = x.createRadialGradient(32, 32, 0, 32, 32, 32);
    g.addColorStop(0, "rgba(255,255,255,1)"); g.addColorStop(0.12, `rgba(${col},0.95)`); g.addColorStop(0.35, `rgba(${col},0.35)`); g.addColorStop(1, `rgba(${col},0)`);
    x.fillStyle = g; x.fillRect(0, 0, 64, 64);
    if (kind === "done" || kind === "now") {          // the brightest get diffraction spikes
      x.globalCompositeOperation = "lighter"; x.strokeStyle = `rgba(${col},0.55)`; x.lineWidth = 1.2;
      x.beginPath(); x.moveTo(32, 2); x.lineTo(32, 62); x.moveTo(2, 32); x.lineTo(62, 32); x.stroke();
    }
    return (SPRITES[kind] = c);
  }
  const bvColor = (bv) => bv < 0 ? "200,215,255" : bv < 0.4 ? "232,238,255" : bv < 0.8 ? "255,250,235" : bv < 1.2 ? "255,228,190" : "255,205,165";
  const kindOf = (it) => { const s = lvStatus(it).k; return s === "reading" ? "now" : s; };

  function draw(t = performance.now()) {
    if (!V || !V.cv.isConnected) return;
    const { ctx, W, H, dpr } = V, B = basis(V.ra, V.dec);
    V.B = B;
    if (V.glp) {
      const { gl, u } = V.glp;
      gl.viewport(0, 0, V.bg.width, V.bg.height);
      gl.uniform2f(u.res, V.bg.width, V.bg.height); gl.uniform1f(u.k, V.k * dpr);
      gl.uniform3fv(u.E, B.e); gl.uniform3fv(u.N, B.n); gl.uniform3fv(u.F, B.f); gl.uniform1f(u.glow, 0.85);
      gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W, H);
    const zoom = V.k / Math.min(W, H);
    // the real sky, faintly: every naked-eye star
    const bg = DATA.bg;
    for (let i = 0; i < bg.length; i += 4) {
      const mag = bg[i + 2];
      if (mag > 4.2 + zoom * 2.4) continue;
      const p = project(vec(bg[i], bg[i + 1]), B);
      if (!p || p[0] < -5 || p[1] < -5 || p[0] > W + 5 || p[1] > H + 5) continue;
      const r = Math.max(0.5, (6.4 - mag) * 0.38 * Math.sqrt(zoom * 1.6));
      ctx.fillStyle = `rgba(${bvColor(bg[i + 3])},${Math.min(0.85, 0.25 + (6.5 - mag) * 0.12)})`;
      ctx.beginPath(); ctx.arc(p[0], p[1], r, 0, 6.283); ctx.fill();
    }
    // the regions' names, large and faint, while you're zoomed out enough to see a region whole
    if (zoom < 1.25) for (const rg of V.regions) {
      const p = project(rg.v, B);
      if (!p || p[2] < 0.1) continue;
      const lit = !V.match || rg.cons.some((g) => g.items.some((b) => V.match.has(b.it.id)));
      ctx.textAlign = "center"; ctx.font = `600 ${Math.round(20 + zoom * 10)}px "Cormorant Garamond", Georgia, serif`;
      ctx.fillStyle = `rgba(255,226,160,${lit ? 0.22 : 0.06})`;
      ctx.fillText(rg.name.toUpperCase().split("").join(" "), p[0], p[1] + 46);
    }
    // the constellations that hold your books: their lines, their names
    V.hit = [];
    for (const g of V.cons) {
      const hot = V.hover && V.hover.g === g, sel = V.sel === g;
      const dim = V.match && !g.items.some((b) => V.match.has(b.it.id));
      ctx.globalAlpha = dim ? 0.25 : 1;
      ctx.strokeStyle = hot || sel ? "rgba(180,205,255,0.85)" : "rgba(150,175,255,0.30)";
      ctx.lineWidth = hot || sel ? 1.6 : 1;
      for (const ls of g.c.lines) {
        ctx.beginPath(); let on = false;
        for (const [ra, dec] of ls) { const p = project(vec(ra, dec), B); if (!p) { on = false; continue; } on ? ctx.lineTo(p[0], p[1]) : ctx.moveTo(p[0], p[1]); on = true; }
        ctx.stroke();
      }
      const c = project(vec(g.c.c[0], g.c.c[1]), B);
      if (c && c[2] > 0.15) {
        ctx.textAlign = "center";
        ctx.font = `600 ${Math.round(11 + zoom * 3)}px ${getComputedStyle(document.body).getPropertyValue("--font-ui") || "sans-serif"}`;
        ctx.fillStyle = hot || sel ? "rgba(225,235,255,0.95)" : "rgba(185,200,255,0.55)";
        ctx.fillText(g.c.name.toUpperCase().split("").join(" "), c[0], c[1] - 10);
        ctx.font = `italic ${Math.round(12 + zoom * 4)}px Georgia, serif`;
        ctx.fillStyle = hot || sel ? "rgba(255,226,160,0.95)" : "rgba(255,226,160,0.6)";
        ctx.fillText(g.label, c[0], c[1] + 8);
      }
      ctx.globalAlpha = 1;
    }
    // your books: bright by how far you've read them
    const tw = reduced() ? 0 : t / 1000, labels = [];
    for (const g of V.cons) for (const b of g.items) {
      const p = project(vec(b.star[0], b.star[1]), B);
      if (!p || p[0] < -20 || p[1] < -20 || p[0] > W + 20 || p[1] > H + 20) continue;
      const k = kindOf(b.it), base = { done: 15, now: 13, next: 11, hold: 10, new: 9.5 }[k] || 9.5;
      const realBoost = Math.max(0, 3.5 - b.star[2]) * 1.6;
      let r = (base + realBoost) * (0.75 + zoom * 0.55);
      if (k === "now") r *= 1 + 0.12 * Math.sin(tw * 2.2 + b.it.id);
      if (V.hover && V.hover.b === b) r *= 1.5;
      const s = sprite(k), hit = V.match && V.match.has(b.it.id);
      if (hit) r *= 1.45;
      ctx.globalAlpha = V.match && !hit ? 0.12 : k === "new" ? 0.9 : 1;
      ctx.drawImage(s, p[0] - r, p[1] - r, r * 2, r * 2);
      ctx.globalAlpha = 1;
      V.hit.push({ x: p[0], y: p[1], r: Math.max(9, r * 0.5), b, g });
      if (V.pulse && V.pulse.id === b.it.id) {           // (the star you went looking for: rings spreading out from it)
        const q = ((t - V.pulse.t0) / 1400) % 1;
        if (t - V.pulse.t0 < 5600) { ctx.strokeStyle = `rgba(255,226,160,${0.9 * (1 - q)})`; ctx.lineWidth = 2; ctx.beginPath(); ctx.arc(p[0], p[1], r * 0.4 + q * 46, 0, 6.283); ctx.stroke(); }
      }
      if (hit && !(V.hover && V.hover.b === b)) labels.unshift([p[0] + r * 0.45 + 3, p[1] + 4, short(b.it.title)]);
      else if (!V.match && (zoom > 1.3 || (V.sel === g && zoom > 1)) && !(V.hover && V.hover.b === b)) labels.push([p[0] + r * 0.45 + 3, p[1] + 4, short(b.it.title)]);
    }
    drawLabels(labels);
  }
  function drawLabels(labels) {          // (titles once you're zoomed in, never on top of each other)
    const { ctx } = V, boxes = [];
    ctx.font = "12px sans-serif"; ctx.textAlign = "left";
    for (const [x, y, t] of labels) {
      const w = ctx.measureText(t).width, bx = [x, y - 11, x + w, y + 3];
      if (boxes.some((o) => bx[0] < o[2] && bx[2] > o[0] && bx[1] < o[3] && bx[3] > o[1])) continue;
      boxes.push(bx);
      ctx.fillStyle = "rgba(0,0,0,0.55)"; ctx.fillText(t, x + 1, y + 1);
      ctx.fillStyle = "rgba(225,232,255,0.85)"; ctx.fillText(t, x, y);
    }
  }
  const short = (t) => { t = t || "Untitled"; return t.length > 28 ? t.slice(0, 26) + "…" : t; };

  let raf = 0;
  function loop(t) {
    raf = 0; if (!V || !V.cv.isConnected) return; draw(t);
    const pulsing = V.pulse && t - V.pulse.t0 < 5600;
    if (pulsing || (!reduced() && V.cons.some((g) => g.items.some((b) => kindOf(b.it) === "now")))) raf = requestAnimationFrame(loop);
  }
  function redraw() { if (!raf) raf = requestAnimationFrame(loop); }

  /* ---------------- moving around ---------------- */
  function fly(ra, dec, k) {
    return new Promise((done) => {
      const s = { ra: V.ra, dec: V.dec, k: V.k }, t0 = performance.now(), dur = reduced() ? 0 : 900;
      const dra = ((ra - s.ra + 540) % 360) - 180;
      const tick = (t) => {
        const q = dur ? Math.min(1, (t - t0) / dur) : 1, e = q < 0.5 ? 2 * q * q : 1 - Math.pow(-2 * q + 2, 2) / 2;
        V.ra = s.ra + dra * e; V.dec = s.dec + (dec - s.dec) * e; if (k) V.k = s.k + (k - s.k) * e;
        draw(); if (q < 1) requestAnimationFrame(tick); else { redraw(); done(); }
      };
      requestAnimationFrame(tick);
    });
  }
  // go to a book: fly to its star, ring it, and open its card beside it
  async function flyToBook(id) {
    const g = V.cons.find((x) => x.items.some((b) => b.it.id === id));
    if (!g) return;
    const b = g.items.find((x) => x.it.id === id);
    V.sel = g;
    await fly(b.star[0], b.star[1], Math.max(V.k, Math.min(V.W, V.H) * 1.9));
    V.pulse = { id, t0: performance.now() }; redraw();
    const p = project(vec(b.star[0], b.star[1]), V.B);
    if (p) { V.hover = { b, g, x: p[0], y: p[1] }; V.pinned = b; showCard(V.hover, p[0], p[1]); }
  }
  function nearest(x, y, slack = 4) {
    let best = null, bd = 1e9;
    for (const h of V.hit) { const d = Math.hypot(h.x - x, h.y - y); if (d < h.r + slack && d < bd) { bd = d; best = h; } }
    return best;
  }
  function consAt(x, y) {
    let best = null, bd = 1e9;
    for (const g of V.cons) { const p = project(vec(g.c.c[0], g.c.c[1]), V.B); if (!p) continue; const d = Math.hypot(p[0] - x, p[1] - y); if (d < bd) { bd = d; best = g; } }
    return bd < Math.min(V.W, V.H) * 0.35 ? best : null;
  }

  /* ---------------- the hover card ---------------- */
  function showCard(h, x, y) {
    const card = V.root.querySelector(".sky-card");
    if (!h) { card.classList.remove("on", "pinned"); V.pinned = null; return; }
    const it = h.b.it, s = lvStatus(it), p = pctOf(it), g = h.g;
    const pos = g.items.indexOf(h.b) + 1, starName = h.b.star[3] || "";
    card.innerHTML = `<div class="sky-c-top"><span class="sky-c-cov">${coverHTML(it)}</span><div><b>${esc(it.title || "Untitled")}</b>
        <small>${esc(authorLine(it))}${it.year ? " · " + esc(it.year) : ""}</small>
        ${inSeries(it) ? `<small class="sky-c-ser">${esc(it.series)}${it.series_index ? " #" + +it.series_index : ""}</small>` : ""}
        <span class="sky-c-st s-${s.k}">${s.w || "Not started"}${p && s.k !== "done" ? " · " + p + "%" : ""}</span>${p ? `<span class="lv-p"><i style="width:${p}%"></i></span>` : ""}</div></div>
      <button class="sky-c-open" data-sky-open="${it.id}">Open ›</button>
      <div class="sky-c-const"><span>✦ In <b>${esc(g.c.name)}</b>${g.c.en && g.c.en !== g.c.name ? ` <em>(${esc(g.c.en)})</em>` : ""}${starName ? ` <em>· the star ${esc(starName)}</em>` : ""}</span><small>${g.series ? `${esc(g.label)} · book ${pos} of ${g.items.length} · ${esc(g.group)}` : `${esc(g.label)} · ${pos} of ${g.items.length} here`}</small></div>`;
    const r = V.root.getBoundingClientRect(), cw = 300;
    card.style.left = Math.min(V.W - cw - 10, Math.max(10, x + 18)) + "px";
    card.style.top = Math.min(V.H - 190, Math.max(10, y - 30)) + "px";
    card.classList.add("on");
    card.classList.toggle("pinned", !!V.pinned);
  }

  /* ---------------- mounting ---------------- */
  async function mount(root, groups) {
    if (raf) cancelAnimationFrame(raf), raf = 0;
    root.innerHTML = `<div class="sky-load">Charting the sky…</div>`;
    await load();
    if (!root.isConnected) return;
    const prev = V && V.area === S.area ? { ra: V.ra, dec: V.dec, k: V.k } : null;
    // drawn again (a sync, a re-render): the atlas, the search and the tapped star's card come back as they were
    const ui = prev && V.root ? { atlas: V.root.classList.contains("atlas-open"), q: V.root.querySelector(".sky-q")?.value || "", pinned: V.pinned && V.pinned.it.id,
      open: [...V.root.querySelectorAll(".sky-atlas details[open] > summary")].map((x) => x.textContent) } : null;
    root.innerHTML = `<canvas class="sky-bg"></canvas><canvas class="sky-fg" tabindex="0" aria-label="Star chart of your library: drag to turn the sky, scroll to zoom"></canvas>
      <div class="sky-card"></div>
      <div class="sky-ui"><button class="sky-b" data-sky="in" title="Zoom in">＋</button><button class="sky-b" data-sky="out" title="Zoom out">－</button><button class="sky-b" data-sky="home" title="Back to the start">⌂</button></div>
      <div class="sky-side">
        <div class="sky-find"><button class="sky-atlas-btn" data-sky="atlas" title="The atlas: every region, constellation and book" aria-label="Atlas">☰</button><input type="search" class="sky-q" placeholder="Find a book, author or series…" aria-label="Find a book on the star chart"><div class="sky-res" hidden></div></div>
        <nav class="sky-atlas" aria-label="Atlas of the sky"></nav>
      </div>
      <p class="sky-credit">Drag to turn the sky · scroll or pinch to zoom · double-click a constellation to fly to it.<br>Milky Way: ESO/S. Brunier (CC BY 4.0) · Stars: Hipparcos via d3-celestial</p>`;
    const cv = root.querySelector(".sky-fg"), bgc = root.querySelector(".sky-bg");
    const cons = assign(groups);
    V = { root, cv, ctx: cv.getContext("2d"), bg: bgc, area: S.area, cons, regions: cons.regions || [], ra: 0, dec: 0, k: 300, hover: null, sel: null, hit: [], match: null, pulse: null };
    try { V.glp = initGL(bgc); } catch (e) { V.glp = null; }
    V.gl = V.glp && V.glp.gl;
    const size = () => {
      const r = root.getBoundingClientRect(), dpr = Math.min(2, devicePixelRatio || 1);
      V.W = r.width; V.H = r.height; V.dpr = dpr;
      for (const c of [cv, bgc]) { c.width = Math.round(r.width * dpr); c.height = Math.round(r.height * dpr); }
      draw();
    };
    new ResizeObserver(() => V && V.root === root && size()).observe(root);
    const home = () => { const g = cons[0]; return g ? { ra: g.c.c[0], dec: g.c.c[1] } : { ra: 0, dec: 0 }; };
    Object.assign(V, prev || { ...home(), k: 0 });
    size();
    if (!prev) V.k = Math.min(V.W, V.H) * 0.9;
    // the atlas: region (genre) ▸ constellation ▸ books, like a table of contents for the sky
    root.querySelector(".sky-atlas").innerHTML = V.regions.map((rg, ri) => `<details class="sky-rg"><summary data-sky-region="${ri}"><b>${esc(rg.name)}</b><small>${rg.n} book${rg.n === 1 ? "" : "s"} · ${rg.cons.length} constellation${rg.cons.length === 1 ? "" : "s"}</small></summary>
      ${rg.cons.map((g) => { const i = cons.indexOf(g); return `<details class="sky-cn"><summary data-sky-go="${i}"><span class="sky-cn-n">✦ ${esc(g.c.name)}</span><em>${g.series ? "📚 " + esc(g.label) : g.label === rg.name ? "single books" : esc(g.label)}</em><small>${g.items.length}</small></summary>
        <ol>${g.items.map((b) => { const k = kindOf(b.it); return `<li><button data-sky-book="${b.it.id}" class="k-${k}"><i></i>${esc(b.it.title || "Untitled")}</button></li>`; }).join("")}</ol></details>`; }).join("")}</details>`).join("");
    // search: what matches lights up, everything else fades; Enter (or a result) flies to it
    const q = root.querySelector(".sky-q"), res = root.querySelector(".sky-res");
    const all = cons.flatMap((g) => g.items.map((b) => ({ b, g })));
    let hits = [];
    q.addEventListener("input", () => {
      const words = q.value.toLowerCase().trim().split(/\s+/).filter(Boolean);
      if (!words.length) { V.match = null; res.hidden = true; return redraw(); }
      hits = all.filter(({ b }) => { const it = b.it, hay = [it.title, (it.authors || []).join(" "), it.series, it.genre, it.year].join(" ").toLowerCase(); return words.every((w) => hay.includes(w)); });
      V.match = new Set(hits.map((h) => h.b.it.id));
      res.innerHTML = hits.length ? hits.slice(0, 8).map(({ b, g }) => `<button data-sky-book="${b.it.id}"><b>${esc(b.it.title || "Untitled")}</b><small>${esc(authorLine(b.it))} · ✦ ${esc(g.c.name)}${g.series ? " · 📚 " + esc(g.label) : ""}</small></button>`).join("") + (hits.length > 8 ? `<p>${hits.length - 8} more lit up on the sky</p>` : "")
        : `<p>No star by that name.</p>`;
      res.hidden = false; draw(); redraw();
    });
    q.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && hits[0]) { e.preventDefault(); res.hidden = true; flyToBook(hits[0].b.it.id); }
      if (e.key === "Escape") { e.stopPropagation(); q.value = ""; q.dispatchEvent(new Event("input")); q.blur(); }
    });
    draw(); redraw();
    if (ui) {
      root.classList.toggle("atlas-open", ui.atlas);
      root.querySelectorAll(".sky-atlas details > summary").forEach((x) => { if (ui.open.includes(x.textContent)) x.parentNode.open = true; });
      if (ui.q) { const qi = root.querySelector(".sky-q"); qi.value = ui.q; setTimeout(() => { qi.dispatchEvent(new Event("input")); root.querySelector(".sky-res").hidden = true; }, 0); }
      if (ui.pinned) setTimeout(() => { draw(); const h = V.hit.find((x) => x.b.it.id === ui.pinned); if (h) { V.hover = h; V.pinned = h.b; showCard(h, h.x, h.y); } }, 0);
    }

    let drag = null, pinch = null;
    const touches = new Map();
    const span = () => { const [a, b] = [...touches.values()]; return Math.hypot(a.x - b.x, a.y - b.y); };
    cv.addEventListener("pointerdown", (e) => {
      touches.set(e.pointerId, { x: e.clientX, y: e.clientY });
      try { cv.setPointerCapture(e.pointerId); } catch (err) {}
      if (touches.size === 2) { pinch = { d: span(), k: V.k }; drag = null; return; }        // (two fingers: zoom)
      drag = { x: e.clientX, y: e.clientY, ra: V.ra, dec: V.dec, moved: false, touch: e.pointerType === "touch" }; cv.classList.add("grab");
    });
    cv.addEventListener("pointermove", (e) => {
      const r = cv.getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top;
      if (touches.has(e.pointerId)) touches.set(e.pointerId, { x: e.clientX, y: e.clientY });
      if (pinch && touches.size === 2) {
        const m = Math.min(V.W, V.H);
        V.k = Math.max(m * 0.28, Math.min(m * 7, pinch.k * span() / (pinch.d || 1)));
        showCard(null); V.hover = null; draw(); return;
      }
      if (drag) {
        const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
        if (Math.abs(dx) + Math.abs(dy) > 3) drag.moved = true;
        const sc = (2 * V.k) / 2;          // (near the middle, a radian is about k pixels)
        V.dec = Math.max(-89, Math.min(89, drag.dec + (dy / sc) / D2R));
        V.ra = (drag.ra + (dx / sc) / D2R / Math.max(0.25, Math.cos(V.dec * D2R)) + 360) % 360;
        showCard(null); V.hover = null; draw(); return;
      }
      if (e.pointerType !== "mouse" || V.pinned) return;          // (fingers don't hover; a pinned card stays put)
      const h = nearest(x, y);
      if ((h && h.b) !== (V.hover && V.hover.b)) { V.hover = h; cv.style.cursor = h ? "pointer" : ""; showCard(h, x, y); draw(); }
    });
    const lift = (e) => {
      touches.delete(e.pointerId);
      if (pinch) { if (touches.size < 2) pinch = null; drag = null; return; }
      const d = drag; drag = null; cv.classList.remove("grab");
      if (!d || d.moved || e.type === "pointercancel") return;
      const r = cv.getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top, h = nearest(x, y, d.touch ? 14 : 4);
      if (!d.touch) { if (h) openDrawer(h.b.it.id); return; }
      // a tap: the first shows the star's card, a second on the same star opens it; a tap on empty sky puts it away
      if (!h) { showCard(null); V.hover = null; return draw(); }
      if (V.pinned === h.b) return openDrawer(h.b.it.id);
      V.hover = h; V.pinned = h.b; showCard(h, x, y); draw();
    };
    cv.addEventListener("pointerup", lift);
    cv.addEventListener("pointercancel", lift);
    cv.addEventListener("pointerleave", (e) => { if (!drag && e.pointerType === "mouse" && !V.pinned) { V.hover = null; showCard(null); draw(); } });
    cv.addEventListener("dblclick", (e) => { const r = cv.getBoundingClientRect(), g = consAt(e.clientX - r.left, e.clientY - r.top); if (g) { V.sel = g; fly(g.c.c[0], g.c.c[1], Math.max(V.k, Math.min(V.W, V.H) * 1.6)); } });
    cv.addEventListener("wheel", (e) => { e.preventDefault(); V.k = Math.max(Math.min(V.W, V.H) * 0.28, Math.min(Math.min(V.W, V.H) * 7, V.k * Math.exp(-e.deltaY * 0.0012))); showCard(null); V.hover = null; draw(); }, { passive: false });
    root.addEventListener("click", (e) => {
      const op = e.target.closest("[data-sky-open]");
      if (op) return openDrawer(+op.dataset.skyOpen);
      const bk = e.target.closest("[data-sky-book]");
      if (bk) { root.querySelector(".sky-res").hidden = true; root.classList.remove("atlas-open"); return flyToBook(+bk.dataset.skyBook); }
      const rgn = e.target.closest("[data-sky-region]");
      if (rgn) { const rg = V.regions[+rgn.dataset.skyRegion]; const ra = Math.atan2(rg.v[1], rg.v[0]) / D2R, dec = Math.asin(rg.v[2]) / D2R; V.sel = null; fly((ra + 360) % 360, dec, Math.min(V.W, V.H) * 1.1); return; }
      const go = e.target.closest("[data-sky-go]");
      if (go) { const g = cons[+go.dataset.skyGo]; V.sel = g; return fly(g.c.c[0], g.c.c[1], Math.max(V.k, Math.min(V.W, V.H) * 1.5)); }
      const b = e.target.closest("[data-sky]");
      if (!b) return;
      const m = Math.min(V.W, V.H);
      if (b.dataset.sky === "in") { V.k = Math.min(m * 7, V.k * 1.35); draw(); }
      if (b.dataset.sky === "out") { V.k = Math.max(m * 0.28, V.k / 1.35); draw(); }
      if (b.dataset.sky === "atlas") { root.classList.toggle("atlas-open"); return; }
      if (b.dataset.sky === "home") { V.sel = null; const h = home(); fly(h.ra, h.dec, m * 0.9); }
    });
  }
  return { mount, get view() { return V; } };
})();
