/* Babel's Library: Discover (online) and the wishlist.
   A ring-bound sheet on the desk with four tabs: Search, Next in your series, More by your authors, Wishlist. */
const Discover = (() => {
  const D = { tab: "promos", q: "", results: null, series: null, serRes: {}, authors: null, promos: null, subject: "trending", subjects: null, browse: {}, busy: false,
    cat: "book", yfrom: "", yto: "", subjectsBy: {}, subjectBy: {} };
  const TABS = [["promos", "Hot off the press", "#f08a6b"], ["browse", "Browse the stacks", "#8fc7d9"], ["search", "Search", "#9fd18b"],
    ["series", "Complete the set", "#f2b06b"], ["authors", "More by your authors", "#b9a3e8"], ["wish", "My shopping list", "#f2d27a"]];
  // the catalogue's departments: click the word in the masthead ("Big BOOK Catalogue") to go to the next one
  const CATS = [["book", "Book", "books"], ["manga", "Manga", "manga"], ["comic", "Comic", "comics"], ["movie", "Movie", "films"], ["tv", "TV", "shows"], ["animation", "Animation", "animation"]];
  const catWord = () => CATS.find((c) => c[0] === D.cat)[1];
  const catNoun = () => CATS.find((c) => c[0] === D.cat)[2];
  const catTabs = () => D.cat === "book" ? TABS : TABS.filter(([k]) => ["promos", "browse", "search", "wish"].includes(k));
  const catQ = (extra = {}) => new URLSearchParams({ cat: D.cat, ...(D.yfrom ? { from: D.yfrom } : {}), ...(D.yto ? { to: D.yto } : {}), ...extra }).toString();
  function paintDepts() {
    const m = $("#dvModal"); if (!m) return;
    m.querySelector(".dvc-depts").innerHTML = catTabs().map(([k, l, c], n) => `<button data-dv-tab="${k}" style="--tab:${c}"><i>${k === "wish" ? "Yours" : `Dept. ${"ABCDE"[n]}`}</i><b>${l}</b>${k === "wish" ? `<span class="dvc-count" id="dvCount"></span>` : ""}</button>`).join("");
    const w = m.querySelector("[data-dv-cat]");
    const mail = m.querySelector(".dvc-mail"); if (mail) mail.textContent = `Mail-order ${catNoun()} · browse free`;
    if (w) { w.textContent = catWord(); w.title = `Showing ${catNoun()} · click for ${CATS[(CATS.findIndex((c) => c[0] === D.cat) + 1) % CATS.length][2]}`; }
  }
  function nextCat() {
    D.cat = CATS[(CATS.findIndex((c) => c[0] === D.cat) + 1) % CATS.length][0];
    D.results = null; D.subject = D.subjectBy[D.cat] || "trending"; D.subjects = D.subjectsBy[D.cat] || null;
    if (!catTabs().some(([k]) => k === D.tab)) D.tab = "promos";
    const w = $("#dvModal [data-dv-cat]");
    if (w) { w.classList.remove("flip"); void w.offsetWidth; w.classList.add("flip"); }
    paintDepts();
    paint();
  }

  function sheet() {
    let m = $("#dvModal");
    if (!m) {
      m = document.createElement("div"); m.id = "dvModal"; m.className = "jb-pv dv";
      const yr = new Date().getFullYear(), season = ["Winter", "Spring", "Summer", "Fall"][Math.floor(new Date().getMonth() / 3)];
      m.innerHTML = `<div class="jb-scrim" data-dv-close></div>
        <div class="dvc">
          <header class="dvc-mast">
            <div class="dvc-issue"><span>${season} ${yr} edition</span><span class="dvc-mail">Mail-order books · browse free</span><button data-dv-close title="Put the catalogue away (Esc)">✕ Put away</button></div>
            <h1><small>Babel's</small> Big <button class="dvc-cat" data-dv-cat title="Click for the next department">Book</button> <em>Catalogue</em></h1>
            <div class="dvc-strap">★ Wish now, shelve later ★ Every title hand-picked from the world's catalogues ★ Needs the internet ★</div>
          </header>
          <nav class="dvc-depts">${TABS.map(([k, l, c], n) => `<button data-dv-tab="${k}" style="--tab:${c}"><i>${k === "wish" ? "Yours" : `Dept. ${"ABCDE"[n]}`}</i><b>${l}</b>${k === "wish" ? `<span class="dvc-count" id="dvCount"></span>` : ""}</button>`).join("")}</nav>
          <div class="dvc-body" id="dvBody"></div>
        </div>`;
      document.body.append(m);
      bind(m);
      paintDepts();
    }
    return m;
  }
  function open(tab) {
    const m = sheet();
    if (tab) D.tab = tab;
    paint();
    requestAnimationFrame(() => m.classList.add("open"));
  }
  function close() { if (closeInfo()) return true; const m = $("#dvModal"); if (m && m.classList.contains("open")) { m.classList.remove("open"); return true; } return false; }

  const wishItems = () => S.items.filter((i) => i.wanted && !i.has_file);
  const itemNo = (t) => { let h = 7; for (const c of String(t || "")) h = (h * 31 + c.charCodeAt(0)) >>> 0; return `${(h % 9000) + 1000}-${String.fromCharCode(65 + (h % 26))}`; };
  const thisYear = new Date().getFullYear();

  const journal_norm = (t) => String(t || "").toLowerCase().replace(/^(the|a|an)\s+/, "").replace(/[^a-z0-9]+/g, "");
  const infoOf = (r) => ({ title: r.title, authors: r.authors || [], year: r.year, isbn: r.isbn || "", link: r.ol_link || r.link || "", wiki: r.wiki || "",
    cover: r.cover || "", blurb: r.blurb || "", why: r.why || "", series: r.series || "", index: r.index ?? null, have: r.have || "", released: r.released || "",
    cat: r.cat || "book", al: r.al || "", form: r.form || "", country: r.country || "", rating: r.rating || null, readers: r.readers || null, genres: r.genres || [] });

  /* "More info": the book's own page inside the catalogue: synopsis, reception and reviews */
  const stars = (n) => (n ? `<span class="dvi-stars" style="--r:${Math.max(0, Math.min(5, n))}">★★★★★</span> ${(+n).toFixed(1)}` : "");
  const paras = (t) => esc(t || "").split(/\n{2,}|\n/).filter((x) => x.trim()).map((x) => `<p>${x}</p>`).join("");
  async function showInfo(b) {
    const m = sheet();
    let el = $("#dvInfo");
    if (!el) { el = document.createElement("div"); el.id = "dvInfo"; el.className = "dvi"; m.querySelector(".dvc").append(el); }
    const who = (b.authors || []).join(", ");
    el.innerHTML = `<div class="dvi-bar"><button data-dvi-close>← Back to the catalogue</button><span>${esc(b.why || "")}</span></div>
      <div class="dvi-page">
        <aside class="dvi-side">
          <div class="dvp-cov dvi-cov">${coverImg(b, "")}<span>${esc(b.title)}</span></div>
          <div class="dvi-buy">${b.have === "owned" ? `<span class="dvp-tag got">In your library</span>` : b.have === "wanted" ? `<span class="dvp-tag got">✓ On your list</span>` : `<button class="dvp-tag" data-dv-want="${esc(JSON.stringify(b))}">＋ Add to list</button>`}</div>
          <div class="dvi-links" id="dviLinks"></div>
        </aside>
        <article class="dvi-main">
          <div class="dvp-no">${b.series ? esc(b.series) + (b.index != null ? ` · Book ${+b.index}` : "") : "Catalogue entry"}</div>
          <h2>${esc(b.title)}</h2>
          <p class="dvi-by">${esc([who && "by " + who, b.released || b.year].filter(Boolean).join(" · "))}</p>
          <div class="dvi-rating" id="dviRating"></div>
          <div class="dvi-genre" id="dviGenre"></div>
          <div id="dviBody"><p class="dv-none">Fetching the book's details…</p></div>
          <div id="dviSeries"></div>
          <div id="dviReviews"></div>
        </article>
      </div>`;
    el.scrollTop = 0;
    requestAnimationFrame(() => el.classList.add("open"));
    const cat = b.cat || "book";
    const q = new URLSearchParams({ title: b.title, author: (b.authors || [])[0] || "", wiki: b.wiki || "", isbn: b.isbn || "", link: b.link || "", cat, al: b.al || "", form: b.form || "" });
    let introFrom = "";   // "page" (a full write-up) or "blurb" (the list's short description, replaced by a fuller one when it comes)
    let hcFull = "";      // Hardcover's full description, whichever of the two lookups lands first
    const useFull = () => {
      const body = $("#dviBody");
      if (!body || !hcFull || introFrom !== "blurb" || hcFull.length <= (b.blurb || "").length) return;
      const first = body.querySelector(".dvi-sec");
      if (first) first.innerHTML = paras(hcFull);
      else body.innerHTML = `<section class="dvi-sec">${paras(hcFull)}</section>`;
    };
    // the shelf it would go on in your library; Hardcover's genres when it knows the book, else Wikipedia's description
    let genreFrom = "";
    const genre = (g, more, src) => {
      const box = $("#dviGenre");
      if (!box || !g || (genreFrom === "hardcover" && src !== "hardcover")) return;
      genreFrom = src;
      const extra = (more || []).filter((x) => x.toLowerCase() !== g.toLowerCase()).slice(0, 5);
      box.innerHTML = `<span class="dvi-glabel">Genre</span><b>${esc(g)}</b>${extra.length ? `<span class="dvi-gmore">${extra.map(esc).join(" · ")}</span>` : ""}`;
    };
    // manga: the AniList button becomes "Read it", opening the official reader (MANGA Plus, VIZ...) in a window of its own
    const links = (list, read) => {
      const box = $("#dviLinks"); if (!box) return;
      const web = cat === "manga" || cat === "animation";
      const one = (l, label, cls = "dvi-link") => `<button class="${cls}" ${web ? `data-dvi-web="${esc(l.url)}" data-dvi-title="${esc(b.title)}"` : `data-dvi-open="${esc(l.url)}"`}>${label}</button><button class="dvi-ext" data-dvi-ext="${esc(l.url)}" title="Open in your web browser">↗</button>`;
      let html = "";
      if (web && read?.length) {
        html += one(read[0], cat === "animation" ? `<i>▶</i> ${esc(read[0].label)} →` : `<i>📖</i> Read it on ${esc(read[0].label)} →`, "dvi-link dvi-read");
        if (read.length > 1) html += `<div class="dvi-also">Also on ${read.slice(1, 5).map((l) => `<button data-dvi-web="${esc(l.url)}" data-dvi-title="${esc(b.title)}">${esc(l.label)}</button>`).join(" · ")}</div>`;
      } else if (web && read) html += `<p class="dvi-also">No official English reader is listed for this one yet.</p>`;
      html += list.map((l) => one(l, web && !read?.length ? `<i>📖</i> Find where to read on ${esc(l.label)} →` : `${web ? "See it on" : "Read on"} ${esc(l.label)} →`)).join("");
      // the sites you added in Settings → Your search sites, for this department
      const mine = (S.settings?.search_sites || []).filter((x) => x.url && (x.cats || []).includes(cat));
      if (mine.length) html += `<div class="dvi-mine"><span>Your sites</span>${mine.map((x) => {
        const u = x.url.replace(/\{q\}/g, encodeURIComponent(b.title || "")).replace(/\{author\}/g, encodeURIComponent((b.authors || [])[0] || ""));
        return `<button class="dvi-link dvi-own" data-dvi-web="${esc(u)}" data-dvi-title="${esc(b.title)}">🔎 Search ${esc(x.name)} →</button><button class="dvi-ext" data-dvi-ext="${esc(u)}" title="Open in your web browser">↗</button>`;
      }).join("")}</div>`;
      box.innerHTML = html;
    };
    links(b.link ? [{ label: new URL(b.link).hostname.replace("www.", ""), url: b.link }] : []);
    api.get(`/api/discover/info?${q}`).then((r) => {
      if (!el.isConnected || $("#dvInfo h2")?.textContent !== b.title) return;
      const body = $("#dviBody");
      genre(r.genre, r.genres || [], cat === "manga" ? "hardcover" : "wikipedia");
      if (r.rating) $("#dviRating").innerHTML = `${stars(r.rating)} <small>${cat === "manga" ? `from ${r.ratings ? (+r.ratings).toLocaleString() + " " : ""}AniList readers` : ""}</small>`;
      const img = el.querySelector(".dvi-cov img");
      if (r.cover && (!img || !img.naturalWidth)) el.querySelector(".dvi-cov").insertAdjacentHTML("afterbegin", `<img alt="" src="${esc(r.cover)}" onerror="this.remove()">`);
      const intro = r.intro || b.blurb;
      introFrom = r.intro ? "page" : "blurb";
      if (cat === "manga" && r.reviews?.length) $("#dviReviews").innerHTML = `<section class="dvi-sec"><h3>Readers' reviews</h3>${r.reviews.map((x) => `<blockquote class="dvi-rev">${x.rating ? `<span class="dvi-stars sm" style="--r:${x.rating}">★★★★★</span>` : ""}<div class="dvi-fold">${paras(x.text)}</div><cite>${esc(x.by)} on AniList</cite></blockquote>`).join("")}</section>`;
      body.innerHTML = (intro ? `<section class="dvi-sec">${paras(intro)}</section>` : "")
        + (r.synopsis ? `<section class="dvi-sec"><h3>Synopsis</h3><div class="dvi-fold">${paras(r.synopsis)}</div></section>` : "")
        + (r.reception ? `<section class="dvi-sec"><h3>What critics said</h3><div class="dvi-fold">${paras(r.reception)}</div></section>` : "")
        || `<p class="dv-none">No write-up of this book was found. Try the links on the left.</p>`;
      body.querySelectorAll(".dvi-fold").forEach((f) => { if (f.scrollHeight > 320) { f.classList.add("folded"); f.insertAdjacentHTML("afterend", `<button class="dvi-more" data-dvi-more>Read more ▾</button>`); } });
      links(r.links?.length ? r.links : b.link ? [{ label: new URL(b.link).hostname.replace("www.", ""), url: b.link }] : [], r.read);
      useFull();
    }).catch((e) => { const body = $("#dviBody"); if (body) body.innerHTML = b.blurb ? paras(b.blurb) : `<p class="dv-none err">${esc(e.message)}</p>`; });
    // part of a series: every book in it, in order (this one marked; yours and the ones you want too)
    if (cat === "book" || cat === "manga" || cat === "comic")
      api.get(`/api/discover/seriesof?${new URLSearchParams({ title: b.title, author: (b.authors || [])[0] || "", series: b.series || "", index: b.index ?? "" })}`).then((s) => {
        if (!el.isConnected || $("#dvInfo h2")?.textContent !== b.title || !s || !s.books) return;
        const num = (x) => (x == null ? "" : Number.isInteger(+x) ? String(+x) : String(+x));
        const here = (x) => (s.index != null && +x.index === +s.index) || journal_norm(x.title) === journal_norm(b.title);
        if (!b.series) { const no = el.querySelector(".dvp-no"); if (no) no.textContent = s.series + (s.index != null ? ` · Book ${num(s.index)}` : ""); }
        $("#dviSeries").innerHTML = `<section class="dvi-sec dvi-series"><h3><small class="dvi-ser-k">Part of a series</small>${esc(s.series)} <small>${s.books.length} books</small></h3>
          <div class="dvi-ser">${s.books.map((x) => `<button class="dvi-sb ${here(x) ? "here" : ""} ${x.have ? "have-" + x.have : ""}" data-dv-info="${esc(JSON.stringify(infoOf({ ...x, cat, series: s.series })))}" title="${esc(x.title)}">
            <span class="dvi-sbc">${x.cover ? `<img loading="lazy" alt="" src="${esc(x.cover)}" onerror="this.remove()">` : ""}<i>${esc(x.title)}</i></span>
            <b>${x.index != null ? "#" + num(x.index) + " " : ""}${esc(x.title)}</b><small>${[x.year, x.have === "owned" ? "✓ yours" : x.have === "wanted" ? "on your list" : here(x) ? "this one" : ""].filter(Boolean).join(" · ")}</small></button>`).join("")}</div></section>`;
      }).catch(() => {});
    api.get(`/api/discover/reviews?${q}`).then((r) => {
      if (!el.isConnected || $("#dvInfo h2")?.textContent !== b.title) return;
      const hc = r.hardcover, nyt = r.nyt || [];
      if (cat === "manga" || cat === "movie" || cat === "tv") return;
      if (hc?.rating) $("#dviRating").innerHTML = `${stars(hc.rating)} <small>from ${hc.ratings || "?"} Hardcover readers</small>`;
      genre(hc?.genre || (hc?.genres || [])[0], hc?.genres, "hardcover");
      // no Wikipedia write-up: Hardcover's full description, instead of the shortened one the list carried
      hcFull = (hc?.description || "").trim();
      useFull();
      let html = "";
      if (hc?.reviews?.length) html += `<h3>Readers' reviews</h3>` + hc.reviews.map((x) => `<blockquote class="dvi-rev">${x.rating ? `<span class="dvi-stars sm" style="--r:${x.rating}">★★★★★</span>` : ""}${paras(x.text)}<cite>${esc(x.by)} on Hardcover</cite></blockquote>`).join("");
      if (nyt.length) html += `<h3>In The New York Times</h3>` + nyt.map((x) => `<blockquote class="dvi-rev nyt">${paras(x.summary || "A review by " + x.by)}<cite>${esc(x.by)}${x.date ? ", " + esc(x.date) : ""} · <button data-dvi-open="${esc(x.url)}">read the review</button></cite></blockquote>`).join("");
      if (!html && !r.hardcover && !r.nyt && !r.hardcover_error && !r.nyt_error) html = `<p class="dvi-tip">Add a free Hardcover token or NYT key in Settings → Book catalogue to see ratings and reviews here.</p>`;
      $("#dviReviews").innerHTML = html ? `<section class="dvi-sec">${html}</section>` : "";
    }).catch(() => {});
  }
  function closeInfo() { const el = $("#dvInfo"); if (el && el.classList.contains("open")) { el.classList.remove("open"); setTimeout(() => el.remove(), 250); return true; } return false; }

  /* one product on the catalogue page */
  const card = (r) => {
    const fresh = r.year && +r.year >= thisYear - 1;
    const tag = r.have === "owned" ? `<span class="dvp-tag got">In your library</span>`
      : r.have === "wanted" ? `<span class="dvp-tag got">✓ On your list</span>`
      : `<button class="dvp-tag" data-dv-want='${esc(JSON.stringify(r))}'>＋ Add to list</button>`;
    return `<article class="dvp ${r.have ? "have-" + r.have : ""}">${r.have === "owned" ? "" : `<button class="dvp-x" data-dv-ignore="${esc(r.title)}" title="Not for me: don't show this book again">✕</button>`}${r.why ? `<div class="dvp-why ${r.kind_promo || ""}">${esc(r.why)}</div>` : ""}
      <div class="dvp-cov">${coverImg(r)}<span>${esc((r.title || "?").slice(0, 40))}</span>
        ${fresh ? `<i class="dvp-new">New!</i>` : ""}${r.have === "owned" ? `<i class="dvp-stamp">On your shelf</i>` : r.have === "wanted" ? `<i class="dvp-stamp want">Wanted</i>` : ""}</div>
      <div class="dvp-no">No. ${itemNo(r.title)}${r.index != null ? ` · ${r.cat === "manga" || r.cat === "comic" ? "Vol." : "Book"} ${+r.index}` : ""}${r.rating ? ` · ★ ${(+r.rating).toFixed(1)}` : ""}</div>
      <h3>${esc(r.title)}</h3>
      <p>${esc([(r.authors || []).join(", "), r.year].filter(Boolean).join(" · ")) || "&nbsp;"}</p>
      ${r.series ? `<p class="dvp-ser">${esc(r.series)}</p>` : ""}
      <div class="dvp-foot">${tag}<button class="dvp-peek" data-dv-info="${esc(JSON.stringify(infoOf(r)))}">More info →</button></div>
    </article>`;
  };
  // covers come through the app (it tries several sources and keeps them on disk)
  // (always through the app: Wikimedia refuses pictures fetched straight from the page at these sizes, and the
  // app paces its downloads). A cover that's still downloading is asked for again a few times before giving up.
  const coverSrc = (r) => `/api/discover/cover?` + new URLSearchParams({ u: /^https:\/\//.test(r.cover || "") ? r.cover : "", isbn: r.isbn || "", t: r.title || "", a: (r.authors || [])[0] || "" });
  const coverImg = (r, lazy = ' loading="lazy"') => `<img${lazy} alt="" src="${esc(coverSrc(r))}" onerror="dvCoverRetry(this)">`;
  window.dvCoverRetry = (img) => {
    const n = +(img.dataset.tries || 0);
    if (n >= 3) return img.remove();
    img.dataset.tries = n + 1;
    setTimeout(() => { if (img.isConnected) img.src = img.src.replace(/&try=\d+$/, "") + `&try=${n + 1}`; }, 4000 * (n + 1));
  };
  const note = (t, cls = "") => `<p class="dv-none ${cls}">${t}</p>`;

  /* Lists come straight from what's saved; when more is on its way ("pending"), look again shortly and add it. */
  const polls = {};
  const seen = {};    // the last answer for each list, shown instantly when you come back to a tab
  async function live(name, url, render, every = 3500) {
    clearTimeout(polls[name]);
    if (seen[url] && every === 3500 && !render(seen[url])) return;
    let r;
    try { r = await api.get(url); seen[url] = r; } catch (e) { r = seen[url] || { items: [], pending: false, error: e.message }; }
    if (!render(r)) return;               // the tab was left
    if (r.pending) polls[name] = setTimeout(() => live(name, url, render, Math.min(every * 1.3, 10000)), every);
  }
  const still = (r, what) => (r.pending ? `<p class="dv-none dv-more">More ${what} arriving…</p>` : "");
  async function paint() {
    const m = sheet();
    $("#dvInfo")?.remove();
    m.querySelectorAll("[data-dv-tab]").forEach((b) => b.classList.toggle("on", b.dataset.dvTab === D.tab));
    const n = wishItems().length, cnt = $("#dvCount");
    if (cnt) cnt.textContent = n || "";
    const body = $("#dvBody");
    body.scrollTop = 0;
    if (D.tab === "search") {
      const hint = { animation: "an anime, a cartoon, an animated film…", book: "a title, an author, an ISBN…", manga: "a manga, manhwa or manhua…", comic: "a comic or graphic novel…", movie: "a film…", tv: "a TV series…" }[D.cat];
      const where = { animation: "AniList's anime and Wikipedia's animated series and films", book: "the world's book catalogues", manga: "AniList's catalogue of manga, manhwa and manhua", comic: "Wikipedia's comics", movie: "Wikipedia's films", tv: "Wikipedia's TV series" }[D.cat];
      body.innerHTML = `<form class="dvc-order" id="dvSearch"><label><span>Order form · I'm looking for</span><input name="q" value="${esc(D.q)}" placeholder="${hint}" autocomplete="off"></label><button type="submit">Find it ⟶</button></form>
        ${yearBar()}
        <div class="dvc-grid" id="dvRes">${D.results ? (D.results.length ? D.results.map((r) => card(r)).join("") : note(`Nothing in the catalogue by that name${D.yfrom || D.yto ? " in those years" : ""}. Try fewer words.`)) : note(`Search ${where}. Anything you fancy goes on your shopping list, and waits on your shelf with a WANTED stamp until you get it.`, "big")}</div>`;
      setTimeout(() => body.querySelector("input")?.focus(), 50);
      return;
    }
    if (D.tab === "series") {
      body.innerHTML = `<p class="dvc-lead">Complete the set! The books missing from each series on your shelves. Series you already have in full aren't shown.</p><div id="dvSer"></div>`;
      live("series", "/api/discover/series", (r) => {
        const box = $("#dvSer"); if (!box || D.tab !== "series") return false;
        box.innerHTML = r.items.map((g) => `<section class="dvc-sec"><div class="dvc-sech"><b>${esc(g.series)}</b><small>${esc(g.authors.join(", "))}${g.have.length ? ` · you own no. ${g.have.map((x) => +x).join(", ")}` : ""}</small></div><div class="dvc-grid">${g.missing.map((x) => card(x)).join("")}</div></section>`).join("")
          + (r.items.length || r.pending ? "" : note(r.complete ? "You have every book of every series we know about!" : "No series on your shelves yet."))
          + (r.complete && r.items.length ? note(`${r.complete} complete ${r.complete === 1 ? "set" : "sets"} hidden.`) : "") + still(r, "series");
        return true;
      });
      return;
    }
    if (D.tab === "promos") {
      const promoLine = { animation: "New anime and animated series and films, from this year and last", book: "Notable books published in the last six months, starting with sequels and new books from your authors",
        manga: "The manga everyone's reading right now, started this year or last", comic: "Comics and graphic novels from this year and last",
        movie: "Films released this year and last", tv: "Shows that premiered this year and last" }[D.cat];
      body.innerHTML = `<div class="dvc-promo"><b>${["movie", "tv", "animation"].includes(D.cat) ? "Now showing!" : "Hot off the press!"}</b><span>${promoLine}</span></div><div id="dvPromo"></div>`;
      live("promos", `/api/discover/promos?cat=${D.cat}`, (r) => {
        const box = $("#dvPromo"); if (!box || D.tab !== "promos") return false;
        const part = (k, h) => { const l = r.items.filter((x) => x.kind_promo === k); return l.length ? `<h2 class="dvc-h2"><span>${h}</span></h2><div class="dvc-grid">${l.map((x) => card(x)).join("")}</div>` : ""; };
        box.innerHTML = part("sequel", "Sequels just out") + part("author", "New from your authors") + part("nyt", "New York Times bestsellers")
          + part("hardcover", "Readers' favourites this season") + part("new", "Everything new this season")
          + (r.items.length ? "" : r.error ? note(esc(r.error), "err") : r.pending ? "" : note("Nothing new from your authors lately. Check back soon!"))
          + still(r, "new releases");
        return true;
      });
      return;
    }
    if (D.tab === "browse") {
      if (!D.subjects) D.subjects = D.subjectsBy[D.cat] = await api.get(`/api/discover/subjects?cat=${D.cat}`).catch(() => [{ key: "trending", label: "Trending this month" }]);
      if (!D.subjects.some((x) => x.key === D.subject)) D.subject = D.subjects[0].key;
      body.innerHTML = `<p class="dvc-lead">Something completely different. Wander the aisles; ${catNoun()} already on your shelves are left out.</p>
        <div class="dvc-aisles">${D.subjects.map((x, n) => `<button data-dv-subject="${x.key}" class="${x.key === D.subject ? "on" : ""}"><i>Aisle ${n + 1}</i>${esc(x.label)}</button>`).join("")}<button data-dv-subject="surprise"><i>?</i>Surprise me</button></div>
        ${yearBar()}
        <div id="dvBrowse"></div>`;
      loadBrowse();
      return;
    }
    if (D.tab === "authors") {
      body.innerHTML = `<p class="dvc-lead">If you liked them, you'll like these. More from the authors you read most.</p><div id="dvAuth"></div>`;
      live("authors", "/api/discover/authors", (r) => {
        const box = $("#dvAuth"); if (!box || D.tab !== "authors") return false;
        box.innerHTML = r.items.map((a) => `<section class="dvc-sec"><div class="dvc-sech"><b>${esc(a.author)}</b><small>${a.books.length} more ${a.books.length === 1 ? "book" : "books"}</small></div><div class="dvc-grid">${a.books.map((x) => card(x)).join("")}</div></section>`).join("")
          + (r.items.length || r.pending ? "" : note("Nothing more found by your authors yet.")) + still(r, "authors");
        return true;
      });
      return;
    }
    if (D.tab === "who") {
      const what = { book: "books", manga: "manga", comic: "comics" }[D.cat] || "books";
      body.innerHTML = `<div class="dvc-promo"><b>Everything by ${esc(D.who)}</b><span>All the ${what} we could find. The ones on your shelves are stamped; add the rest to your list.</span></div><div class="dvc-grid" id="dvWho">${note("Looking through the catalogues…")}</div>`;
      try {
        const r = await api.get(`/api/discover/byauthor?${new URLSearchParams({ name: D.who, cat: D.cat })}`);
        const box = $("#dvWho"); if (!box || D.tab !== "who") return;
        box.innerHTML = r.items.length ? r.items.map((x) => card(x)).join("") : note(`Nothing more by ${esc(D.who)} in the catalogues we can reach.`);
      } catch (err) { const box = $("#dvWho"); if (box) box.innerHTML = note(esc(err.message), "err"); }
      return;
    }
    if (D.tab === "wish") {
      const w = wishItems();
      const today = new Date().toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
      body.innerHTML = `<div class="dvl"><div class="dvl-pad">
          <div class="dvl-top"><b>Shopping list</b><span>${today}</span></div>
          ${w.length ? `<ol>${w.map((i) => `<li data-dvl="${i.id}">
              <span class="dvl-box" title="Got it / don't want it: scratch it off"><button data-dv-unwant="${i.id}" aria-label="Scratch off ${esc(i.title)}"></button></span>
              ${i.has_cover ? `<img alt="" src="/api/items/${i.id}/cover?v=${i.cover_v || 0}">` : ""}
              <span class="dvl-t"><b>${esc(i.title)}</b><small>${esc([(i.authors || [])[0], i.series ? `${i.series}${i.series_index != null ? " #" + +i.series_index : ""}` : ""].filter(Boolean).join(" — "))}</small></span>
              <span class="dvl-act"><button data-dv-own="${i.id}" title="You have this book on paper: put it on your shelf as a physical copy">I own it</button><button data-dv-show="${i.id}">find on shelf</button>${i.url ? `<button data-dv-preview="${esc(i.url)}">look it up</button>` : ""}</span>
            </li>`).join("")}</ol>
            <div class="dvl-total">${w.length} ${w.length === 1 ? "book" : "books"} to get</div>`
            : `<p class="dvl-empty">Nothing on the list yet!<br><small>Browse the departments and press “＋ Add to list”.</small></p>`}
        </div><div id="dvIgn"></div><p class="dvl-note">Wanted books sit on your shelves with a WANTED stamp. When you add the real book, it takes the wanted one's place and is crossed off here.</p></div>`;
      api.get("/api/discover/ignored").then((lst) => {
        const box = $("#dvIgn"); if (!box || !lst.length) return;
        box.innerHTML = `<details class="dvl-ign"><summary>${lst.length} ${lst.length === 1 ? "book" : "books"} hidden from the catalogue</summary>
          <ul>${lst.map((x) => `<li>${esc(x.title)} <button data-dv-unignore="${esc(x.title)}">show again</button></li>`).join("")}</ul></details>`;
      }).catch(() => {});
    }
  }

  function paintBrowse(r, sub) {
    const box = $("#dvBrowse"); if (!box || D.tab !== "browse" || D.subject !== sub) return false;
    const fresh = sub === "trending" && D.cat !== "manga";
    const bar = r.items.length ? `<div class="dvc-restock"><span>${r.items.length} ${catNoun()} on these shelves${D.yfrom || D.yto ? ` · ${D.yfrom || "…"}–${D.yto || thisYear}` : ""} · restocks itself weekly</span>
      <button data-dv-restock="${esc(sub)}" title="${fresh ? "Fetch this aisle's list again" : `Swap these for ${catNoun()} you haven't been shown yet`}">↻ ${fresh ? "Refresh this aisle" : `Restock with new ${catNoun()}`}</button></div>` : "";
    box.innerHTML = bar + (r.items.length ? `<div class="dvc-grid">${r.items.map((x) => card(x)).join("")}</div>` : r.error ? note(esc(r.error), "err") : r.pending ? note("Stocking this aisle…") : note("Nothing new in this aisle."))
      + (r.items.length ? still(r, "books") : "");
    return true;
  }
  function loadBrowse() {
    const sub = D.subject;
    D.subjectBy[D.cat] = sub;
    live("browse", `/api/discover/browse?${catQ({ subject: sub })}`, (r) => paintBrowse(r, sub));
  }
  // a span of years for Browse and Search ("1990" to "1999"); empty means any year
  function yearBar() {
    const on = D.yfrom || D.yto;
    return `<form class="dvc-years ${on ? "on" : ""}" id="dvYears"><span>${["movie", "tv"].includes(D.cat) ? "Released" : "Published"}</span><label>from <input name="from" inputmode="numeric" maxlength="4" placeholder="any" value="${esc(D.yfrom)}"></label>
      <label>to <input name="to" inputmode="numeric" maxlength="4" placeholder="${thisYear}" value="${esc(D.yto)}"></label><button type="submit">Apply</button>
      ${on ? `<button type="button" data-dv-years-clear>Any year</button>` : ""}
      <span class="dvc-yq">${[["Last 5 years", thisYear - 4, thisYear], ["2010s", 2010, 2019], ["2000s", 2000, 2009], ["1990s", 1990, 1999], ["Classics", "", 1970]].map(([l, a, b]) => `<button type="button" data-dv-years="${a}-${b}">${l}</button>`).join("")}</span></form>`;
  }
  function setYears(a, b) {
    const ok = (v) => (/^\d{4}$/.test(String(v || "").trim()) ? String(v).trim() : "");
    D.yfrom = ok(a); D.yto = ok(b);
    if (D.tab === "search" && D.q) { const f = $("#dvSearch"); if (f) return f.requestSubmit(); }
    paint();
  }
  async function restockAisle(btn) {
    const sub = btn.dataset.dvRestock;
    btn.disabled = true; btn.textContent = "Restocking…";
    try {
      const r = await api.send("POST", `/api/discover/restock?${catQ({ subject: sub })}`);
      paintBrowse(r, sub);
      $("#dvBrowse")?.scrollIntoView({ block: "start", behavior: "smooth" });
    } catch (err) { toast(err.message, "error"); btn.disabled = false; btn.textContent = "↻ Try again"; }
  }

  function bind(m) {
    m.addEventListener("click", async (e) => {
      const t = e.target;
      if (t.closest("[data-dv-close]")) return close();
      const tb = t.closest("[data-dv-tab]");
      if (tb) { D.tab = tb.dataset.dvTab; return paint(); }
      const inf = t.closest("[data-dv-info]");
      if (inf) return showInfo(JSON.parse(inf.dataset.dvInfo));
      const cv = t.closest(".dvp .dvp-cov");
      if (cv) { const btn = cv.closest(".dvp").querySelector("[data-dv-info]"); if (btn) return showInfo(JSON.parse(btn.dataset.dvInfo)); }
      if (t.closest("[data-dvi-close]")) return closeInfo();
      const more = t.closest("[data-dvi-more]");
      if (more) { more.previousElementSibling.classList.remove("folded"); more.remove(); return; }
      const op = t.closest("[data-dvi-open]");
      if (op) {
        const u = op.dataset.dviOpen;
        if (/openlibrary\.org|archive\.org|amazon\./.test(u)) return api.send("POST", "/api/open-url", { url: u }).then(() => toast("Opened in your browser"));
        return Journal.preview(u);
      }
      const wb = t.closest("[data-dvi-web]");
      if (wb && S.desktopMode === "native") { closeInfo(); close(); return Browser.open(wb.dataset.dviWeb); }
      if (wb) return api.send("POST", "/api/desktop/web",{ url: wb.dataset.dviWeb, title: wb.dataset.dviTitle || "" })
        .then((r) => toast(r.where === "browser" ? "Opened in your browser" : "Opening the reading window…")).catch((err) => toast(err.message, "error"));
      const ex = t.closest("[data-dvi-ext]");
      if (ex) return api.send("POST", "/api/open-url", { url: ex.dataset.dviExt }).then(() => toast("Opened in your browser")).catch((err) => toast(err.message, "error"));
      if (t.closest("[data-dv-cat]")) return nextCat();
      const yq = t.closest("[data-dv-years]");
      if (yq) { const [a, b] = yq.dataset.dvYears.split("-"); return setYears(a, b); }
      if (t.closest("[data-dv-years-clear]")) return setYears("", "");
      const rs = t.closest("[data-dv-restock]");
      if (rs) return restockAisle(rs);
      const sj = t.closest("[data-dv-subject]");
      if (sj) {
        let k = sj.dataset.dvSubject;
        if (k === "surprise") { const opts = (D.subjects || []).filter((x) => x.key !== "new" && x.key !== D.subject); k = opts[Math.floor(Math.random() * opts.length)]?.key || "new"; }
        D.subject = k;
        m.querySelectorAll("[data-dv-subject]").forEach((b) => b.classList.toggle("on", b.dataset.dvSubject === k));
        return loadBrowse();
      }
      const pv = t.closest("[data-dv-preview]");
      if (pv) {
        const u = pv.dataset.dvPreview;
        // Open Library asks for a human check that can't be done inside the app: use your browser for it
        if (/openlibrary\.org|archive\.org/.test(u)) return api.send("POST", "/api/open-url", { url: u }).then(() => toast("Opened in your browser")).catch((err) => toast(err.message, "error"));
        return Journal.preview(u);
      }
      const w = t.closest("[data-dv-want]");
      if (w) {
        try {
          await api.send("POST", "/api/wishlist", JSON.parse(w.dataset.dvWant));
          w.outerHTML = `<span class="dvp-tag got">✓ On your list</span>`;
          toast("Added to your shopping list");
          await loadItems();
          const c = $("#dvCount"); if (c) { c.textContent = wishItems().length || ""; c.classList.remove("bump"); void c.offsetWidth; c.classList.add("bump"); }
        } catch (err) { toast(err.message, "error"); }
        return;
      }
      const un = t.closest("[data-dv-unwant]");
      if (un) {
        const li = un.closest("li");
        li?.classList.add("scratched");
        await new Promise((r) => setTimeout(r, 450));
        try { await api.send("DELETE", `/api/items/${un.dataset.dvUnwant}`); toast("Scratched off your list"); } catch (err) { toast(err.message, "error"); }
        await loadItems(); return paint();
      }
      const ig = t.closest("[data-dv-ignore]");
      if (ig) {
        const cardEl = ig.closest(".dvp");
        cardEl?.classList.add("gone");
        try {
          await api.send("POST", "/api/discover/ignore", { title: ig.dataset.dvIgnore });
          toast(`“${ig.dataset.dvIgnore}” won't be shown again`);
          setTimeout(() => cardEl?.remove(), 300);
        } catch (err) { cardEl?.classList.remove("gone"); toast(err.message, "error"); }
        return;
      }
      const un2 = t.closest("[data-dv-unignore]");
      if (un2) { await api.send("POST", "/api/discover/ignore", { title: un2.dataset.dvUnignore, undo: true }); toast("It can show up again"); return paint(); }
      const ow = t.closest("[data-dv-own]");
      if (ow) {
        const li = ow.closest("li");
        try {
          const r = await api.send("POST", `/api/items/${ow.dataset.dvOwn}/own`, {});
          li?.classList.add("scratched");
          toast(`On your shelf as a physical copy${r.linked ? ", with your journal pages" : ""}`);
          await new Promise((res) => setTimeout(res, 450));
          await loadItems(); return paint();
        } catch (err) { toast(err.message, "error"); }
        return;
      }
      const sh = t.closest("[data-dv-show]");
      if (sh) { close(); openDrawer(Number(sh.dataset.dvShow)); }
    });
    m.addEventListener("submit", async (e) => {
      if (e.target.id === "dvYears") { e.preventDefault(); return setYears(e.target.from.value, e.target.to.value); }
      if (e.target.id !== "dvSearch") return;
      e.preventDefault();
      D.q = e.target.q.value.trim();
      if (!D.q) return;
      const box = $("#dvRes");
      box.innerHTML = note("Searching the catalogue…");
      try { D.results = await api.get(`/api/discover/search?${catQ({ q: D.q })}`); paint(); }
      catch (err) { box.innerHTML = note(esc(err.message), "err"); }
    });
  }
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("#jbPreview.open") && close()) e.stopPropagation(); }, true);
  /* "View all releases" on the home page: the catalogue opened on one author */
  function byAuthor(name, cat = "book") {
    D.cat = cat; D.who = name; D.results = null;
    D.subject = D.subjectBy[D.cat] || "trending"; D.subjects = D.subjectsBy[D.cat] || null;
    sheet();
    paintDepts();
    open("who");
  }
  /* a catalogue find shown elsewhere (the Bulletin's Hot Off the Press): the catalogue opens on its page */
  function showFind(r) { open(); showInfo(infoOf(r)); }
  return { open, close, byAuthor, showFind };
})();
