"""Discover: find books online (needs an internet connection) and keep a wishlist.

Search            Open Library's catalogue (titles, authors, ISBNs)
Next in a series  the books of each series you own, from Wikidata ("part of the series" + "series ordinal"),
                  minus the ones already on your shelves
More by authors   other works by the authors you read most, from Open Library
Wishlist          wanted books live on the shelf as ordinary entries with wanted=1 (no file); when the real book
                  is added later it takes the wanted entry's place (see claim_wanted)
"""
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse

import journal
import lookup
import series as series_mod
import store

OL = "https://openlibrary.org"
CACHE_FILE = os.path.join(store.DATA_DIR, "discover_cache.json")
COVER_DIR = os.path.join(store.DATA_DIR, "discover_covers")
_cache = {}
_cache_lock = threading.Lock()
_save_timer = None


def _load_cache():
    try:
        with open(CACHE_FILE, encoding="utf-8") as f:
            _cache.update({k: tuple(v) for k, v in json.load(f).items()})
    except (OSError, ValueError):
        pass


def _save_cache():
    global _save_timer
    _save_timer = None
    try:
        with _cache_lock:
            now = time.time()
            data = {k: list(v) for k, v in _cache.items() if now - v[0] < 30 * 86400}
        tmp = CACHE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp, CACHE_FILE)
    except OSError as e:
        print("[inkwell] discover cache not saved:", e)


def _cached(key, ttl, fn):
    """Results are kept on disk too, so the catalogue opens instantly next time and the sites aren't asked twice."""
    global _save_timer
    key = json.dumps(key) if not isinstance(key, str) else key
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    val = fn()
    # nothing came back (a site timed out, say): keep the list we had, or ask again next time rather than for a day
    empty = val in ([], {}) or (isinstance(val, dict) and val.get("items") == [])
    if empty and hit and hit[1] not in ([], {}):
        return hit[1]
    with _cache_lock:
        _cache[key] = (0 if empty else time.time(), val)
    if _save_timer is None:
        _save_timer = threading.Timer(3, _save_cache)
        _save_timer.daemon = True
        _save_timer.start()
    return val


def forget(key):
    with _cache_lock:
        _cache.pop(json.dumps(key), None)


def peek(key):
    """A cached value without fetching (None when unknown)."""
    hit = _cache.get(json.dumps(key))
    return hit[1] if hit else None


_load_cache()


# ---------------------------------------------------------------- covers (fetched by the app, kept on disk)
def _isbn10(isbn):
    d = re.sub(r"[^0-9Xx]", "", isbn or "")
    if len(d) == 10:
        return d.upper()
    if len(d) == 13 and d.startswith("978"):
        core = d[3:12]
        c = (11 - sum((10 - k) * int(x) for k, x in enumerate(core)) % 11) % 11
        return core + ("X" if c == 10 else str(c))
    return ""


THUMB_W = 330   # Wikimedia only serves thumbnails at its standard widths (…250, 330, 500…); others get "429"


def _std_thumb(url):
    """Older cached links ask for 400px thumbnails: move them onto a standard width."""
    if "upload.wikimedia.org" in url and "/thumb/" in url:
        return re.sub(r"/(\d+)px-([^/?]+)(\?|$)", lambda m: f"/{THUMB_W}px-{m.group(2)}{m.group(3)}", url)
    return url


def _fetch_img(url):
    # paced per site like every other request; a "too many requests" answer is waited out, not taken as "no cover"
    data = lookup._get(_std_thumb(url), timeout=15, accept="image/*")
    # Open Library answers "no cover" with a tiny blank image; Amazon with a 1x1 gif
    if len(data) < 1500:
        raise LookupError("no cover")
    return data


def _hc_cover_candidate(title, author, isbn):
    if not hardcover_on():
        return ""
    try:
        return hc_cover_url(hardcover_match(title, author, isbn))
    except Exception as e:
        print("[inkwell] hardcover cover skipped:", e)
        return ""


def _cover_candidates(url="", isbn="", title="", author="", hc_first=False):
    tried = set()
    if hc_first and (title or isbn):
        h = _hc_cover_candidate(title, author, isbn)
        if h:
            tried.add(h)
            yield h
    if url:
        yield url
    if title:
        try:      # Wikipedia's article picture is usually the first-edition cover
            w = wiki_cover_url(title, author)
            if w and w != url:
                yield w
        except Exception as e:
            print("[inkwell] wikipedia cover skipped:", e)
    if not hc_first and title:
        h = _hc_cover_candidate(title, author, isbn)   # Hardcover has covers for books without a Wikipedia article
        if h and h not in tried and h != url:
            yield h
    isbn = re.sub(r"[^0-9Xx]", "", isbn or "")
    if not isbn and title:
        try:      # find the book's ISBN / cover number on Open Library
            hits = _mark([dict(x) for x in _cached(("s", f"{title} {author}".strip().lower()), 7 * 86400, lambda: _ol_search(f"{title} {author}".strip(), 5))])
            hit = next((h for h in hits if journal.norm(h["title"]) == journal.norm(title)), hits[0] if hits else None)
            if hit:
                if hit.get("cover") and hit["cover"] != url:
                    yield hit["cover"]
                isbn = hit.get("isbn") or ""
        except Exception as e:
            if "refusing connections" not in str(e):   # a site known to be down was already reported once
                print("[inkwell] cover search skipped:", e)
    if isbn:
        yield f"https://covers.openlibrary.org/b/isbn/{isbn}-M.jpg?default=false"
        yield f"https://books.google.com/books/content?vid=ISBN{isbn}&printsec=frontcover&img=1&zoom=1"
        i10 = _isbn10(isbn)
        if i10:
            yield f"https://images-na.ssl-images-amazon.com/images/P/{i10}.01.MZZZZZZZ.jpg"


_cover_pool = None
_cover_jobs = {}


class CoverBusy(LookupError):
    """No cover this time, but only because a site was busy or out of reach: worth asking again."""


def cover_quick(url="", isbn="", title="", author="", wait=4):
    """For the catalogue page: a cover if it can be had within a few seconds. Slow ones keep downloading in the
    background (at most three at a time) and are there the next time the page asks."""
    import concurrent.futures
    global _cover_pool
    if _cover_pool is None:
        _cover_pool = concurrent.futures.ThreadPoolExecutor(max_workers=6, thread_name_prefix="cover")
    key = (url, isbn, title, author)
    fut = _cover_jobs.get(key)
    if fut is None or (fut.done() and fut.exception() is not None and (isinstance(fut.exception(), CoverBusy) or not isinstance(fut.exception(), LookupError))):
        fut = _cover_pool.submit(cover, url, isbn, title, author)
        _cover_jobs[key] = fut
        if len(_cover_jobs) > 2000:
            for k in [k for k, f in _cover_jobs.items() if f.done()][:1000]:
                _cover_jobs.pop(k, None)
    try:
        return fut.result(timeout=wait)
    except concurrent.futures.TimeoutError:
        raise LookupError("still fetching")


def cover(url="", isbn="", title="", author="", hc_first=False):
    """A cover image for the catalogue, fetched by the app (several sources in turn) and kept on disk.
    hc_first: for books on your shelves, Hardcover's cover (the edition people know) is tried before anything else."""
    import hashlib
    if url and not url.startswith("https://"):
        raise ValueError("Not a cover address.")
    key = url or isbn or f"{journal.norm(title)}|{journal.norm(author)}"
    if not key.strip("|"):
        raise LookupError("no cover")
    if hc_first:
        key += "|hc"   # its own saved copy: the catalogue may have kept a different picture for the same book
    os.makedirs(COVER_DIR, exist_ok=True)
    path = os.path.join(COVER_DIR, hashlib.sha1(key.encode()).hexdigest())
    if os.path.exists(path + ".jpg"):
        with open(path + ".jpg", "rb") as f:
            return f.read()
    if os.path.exists(path + ".nocover2") and time.time() - os.path.getmtime(path + ".nocover2") < 3 * 86400:
        raise LookupError("no cover")
    errors = []
    for u in _cover_candidates(url, isbn, title, author, hc_first):
        try:
            data = _fetch_img(u)
            with open(path + ".jpg", "wb") as f:
                f.write(data)
            return data
        except Exception as e:
            errors.append(e)
    # only a definite "nothing there" from every source counts; busy or unreachable sites get asked again next time
    definite = lambda e: isinstance(e, LookupError) or (isinstance(e, urllib.error.HTTPError) and e.code in (403, 404, 410))
    if all(definite(e) for e in errors):
        open(path + ".nocover2", "w").close()          # really has no cover: don't ask again for a few days
        raise LookupError("no cover")
    raise CoverBusy("cover sites busy")


def _json(url, accept="application/json"):
    return json.loads(lookup._get(url, timeout=15, accept=accept))


def _owned_index(watch=False):
    """norm(title) -> 'owned' | 'wanted': books, comics and manga; or (watch) films and shows."""
    return _memo_get("owned-watch" if watch else "owned", lambda: _owned_index_raw(("movie", "tv") if watch else ("book", "graphic")))


def _owned_index_raw(kinds=("book", "graphic")):
    out = {}
    for it in store.list_items():
        if it.get("kind") not in kinds:
            continue
        # a manga or show is in the catalogue by its series name ("Goodnight Punpun"), not a volume or episode
        names = {it.get("series")} if it.get("kind") in ("graphic", "tv") and it.get("series") else set()
        if it.get("kind") != "tv":
            names |= {it.get("title"), re.sub(r"\s*[:(].*$", "", it.get("title") or "")}
        for t in names:
            k = journal.norm(t)
            if k:
                out[k] = "wanted" if it.get("wanted") and not it.get("has_file") else out.get(k) or "owned"
    return out


_memo = {}


def _memo_get(name, fn, ttl=15):
    hit = _memo.get(name)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    v = fn()
    _memo[name] = (time.time(), v)
    return v


def ignored():
    return {x.get("k") for x in store.get_settings().get("discover_ignored") or []}


def ignore(title, undo=False):
    lst = [x for x in store.get_settings().get("discover_ignored") or [] if x.get("k") != journal.norm(title)]
    if not undo:
        lst.append({"k": journal.norm(title), "title": title})
    store.set_settings({"discover_ignored": lst})
    return lst


def _mark(results):
    read, watch, ign = _owned_index(), _owned_index(True), ignored()
    for r in results:
        have = watch if r.get("cat") in ("movie", "tv", "animation") else read
        k = journal.norm(r.get("title"))
        k2 = journal.norm(re.sub(r"\s*[:(].*$", "", r.get("title") or ""))
        r["have"] = have.get(k) or have.get(k2) or ("ignored" if k in ign else "")
    return results


def _ol_doc(d):
    cid = d.get("cover_i") or d.get("cover_id")
    cover = f"https://covers.openlibrary.org/b/id/{cid}-M.jpg" if cid else ""
    if not d.get("author_name") and d.get("authors"):
        d["author_name"] = [a.get("name", "") for a in d["authors"] if isinstance(a, dict)]
    isbn = next((i for i in (d.get("isbn") or []) if len(i) == 13), (d.get("isbn") or [""])[0])
    return {"title": d.get("title", ""), "authors": (d.get("author_name") or [])[:3], "year": d.get("first_publish_year"),
            "cover": cover, "isbn": isbn, "link": OL + d["key"] if d.get("key") else "", "olid": d.get("key", ""),
            "subjects": (d.get("subject") or [])[:6]}


def _ol_search(q, limit):
    url = f"{OL}/search.json?" + urllib.parse.urlencode({"q": q, "limit": limit, "fields": "key,title,author_name,first_publish_year,cover_i,isbn,subject"})
    return [_ol_doc(d) for d in _json(url).get("docs") or [] if d.get("title")]


def search(q, limit=30, yfrom=None, yto=None):
    """Open Library's catalogue; when it can't be reached, Wikipedia's book articles. Optionally only books from a
    span of years."""
    q = (q or "").strip()
    if not q:
        return []
    if yfrom or yto:
        return [r for r in search(q, 50) if in_years(r, yfrom, yto)]
    def go():
        try:
            return _ol_search(q, limit)
        except (urllib.error.URLError, ConnectionError, TimeoutError) as e:
            if isinstance(e, urllib.error.HTTPError) and e.code not in (429, 500, 502, 503, 504):
                raise
            print("[inkwell] open library unreachable, searching wikipedia:", e)
            return wp_books(f'{q} hastemplate:"Infobox book"', limit=limit, sort="relevance")
    return [r for r in _mark([dict(x) for x in _cached(("s", q.lower()), 86400, go)]) if r["have"] != "ignored"]


# ---------------------------------------------------------------- Wikipedia: book articles (with their covers)
WP = "https://en.wikipedia.org/w/api.php?"
BOOKISH = re.compile(r"\b(novel|novella|book|memoir|collection|graphic novel|comic|manga|poetry|poems|non-?fiction|biography|autobiography|essays?|anthology|trilogy)\b", re.I)
NEVER_BOOK = re.compile(r"\b(character|franchise|film series|fashion|exhibition|imprint|bookstore|literary award)\b|\((?:character|franchise)\)", re.I)  # "comic book character" mentions "book" too
NOT_BOOK = re.compile(r"\b(film|television|tv series|video game|franchise|character|album|song|band|novelist|writer|author|poet|journalist|publisher|award|magazine|podcast)\b", re.I)


def wp_books(srsearch, limit=40, sort="incoming_links_desc", offset=0):
    params = {"action": "query", "format": "json", "formatversion": "2", "generator": "search", "gsrsearch": srsearch,
              "gsrlimit": min(50, limit), "gsrnamespace": 0, "prop": "pageimages|description|info", "piprop": "thumbnail", "pilicense": "any",
              "pithumbsize": THUMB_W, "inprop": "url"}
    if sort != "relevance":
        params["gsrsort"] = sort
    if offset:
        params["gsroffset"] = offset
    d = _json(WP + urllib.parse.urlencode(params))
    out = []
    for pg in sorted((d.get("query") or {}).get("pages") or [], key=lambda x: x.get("index", 0)):
        desc = (pg.get("description") or "").strip()
        if not BOOKISH.search(desc) or (NOT_BOOK.search(desc) and not re.search(r"\b(novel|book)\b", desc, re.I)) or NEVER_BOOK.search(desc + " " + pg["title"]):
            continue
        if re.match(r"(list|bibliography|works) of\b", pg["title"], re.I):
            continue
        title = re.sub(r"\s*\([^)]*\b(?:novel|book|novella|comics?|memoir|series|collection|stories|poems|manga)\b[^)]*\)$", "", pg["title"])
        m = re.search(r"\bby\s+(.+?)\s*$", desc)
        y = re.search(r"\b(1[5-9]\d\d|20\d\d)\b", desc)
        out.append({"title": title, "authors": [m.group(1)] if m else [], "year": int(y.group(1)) if y else None,
                    "cover": (pg.get("thumbnail") or {}).get("source", ""), "blurb": desc, "wiki": pg["title"],
                    "link": pg.get("fullurl") or "https://en.wikipedia.org/wiki/" + urllib.parse.quote(pg["title"].replace(" ", "_"))})
    return out


def wiki_cover_url(title, author=""):
    """The picture on a book's Wikipedia article (usually its cover), or ""."""
    def go():
        last = (author or "").split(",")[0].split()[-1] if (author or "").strip() else ""
        res = wp_books(f'{title} {last} hastemplate:"Infobox book"'.strip(), limit=6, sort="relevance")
        if not res:
            res = wp_books(f"{title} {last} novel".strip(), limit=6, sort="relevance")
        t = journal.norm(title)
        hit = next((r for r in res if r["cover"] and journal.norm(r["title"]) == t), None) or \
            next((r for r in res if r["cover"] and t and (t in journal.norm(r["title"]) or journal.norm(r["title"]) in t)
                  and (not last or last.lower() in r["blurb"].lower())), None)
        return hit["cover"] if hit else ""
    return _cached(("wcov3", journal.norm(title), journal.norm(author)), 30 * 86400, go)


# ---------------------------------------------------------------- next in your series
def my_series():
    return [dict(g) for g in _memo_get("series", _my_series_raw)]


def _my_series_raw():
    """Series on the shelves (books only), with the numbers you have."""
    groups = {}
    for it in store.list_items():
        if it.get("kind") not in ("book", "graphic") or not it.get("series"):
            continue
        g = groups.setdefault(series_mod.key(it["series"]), {"series": it["series"], "authors": set(), "have": [], "titles": []})
        g["authors"].update(it.get("authors") or [])
        if it.get("series_index") is not None and not (it.get("wanted") and not it.get("has_file")):
            g["have"].append(it["series_index"])
        g["titles"].append(it.get("title") or "")
    out = [{"series": g["series"], "authors": sorted(g["authors"])[:2], "have": sorted(set(g["have"]))} for g in groups.values()]
    return sorted(out, key=lambda g: g["series"].lower())


SPARQL = "https://query.wikidata.org/sparql?format=json&query="


def _series_entity(name, authors):
    hits = _json("https://www.wikidata.org/w/api.php?" + urllib.parse.urlencode(
        {"action": "wbsearchentities", "search": name, "language": "en", "type": "item", "limit": 10, "format": "json"})).get("search") or []
    sn = {a.split(",")[0].split()[-1].lower() for a in authors if a.strip()}
    def score(h):
        d = (h.get("description") or "").lower()
        s = 0
        if re.search(r"series|trilogy|saga|sequence|cycle|novels|books", d):
            s += 3
        if any(x in d for x in sn):
            s += 2
        if re.search(r"film|television|video game|episode|character", d):
            s -= 4
        return s
    hits = sorted([h for h in hits if score(h) >= 3], key=score, reverse=True)
    return hits[0]["id"] if hits else None


def _series_books(name, authors=()):
    """Every book in a series, in order (Wikidata), with its Wikipedia article when there is one."""
    qid = _series_entity(name, list(authors))
    if not qid:
        return []
    q = f"""SELECT ?item ?itemLabel ?ord ?date ?article WHERE {{
      ?item p:P179 ?st . ?st ps:P179 wd:{qid} . OPTIONAL {{ ?st pq:P1545 ?ord }}
      OPTIONAL {{ ?item wdt:P577 ?date }}
      OPTIONAL {{ ?article schema:about ?item ; schema:isPartOf <https://en.wikipedia.org/> }}
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }} }}"""
    rows = _json(SPARQL + urllib.parse.quote(q), accept="application/sparql-results+json").get("results", {}).get("bindings", [])
    books = {}
    for r in rows:
        title = r.get("itemLabel", {}).get("value", "")
        if not title or re.fullmatch(r"Q\d+", title):
            continue
        o = r.get("ord", {}).get("value")
        try:
            o = float(o) if o is not None else None
        except ValueError:
            o = None
        y = (r.get("date", {}).get("value") or "")[:4]
        k = journal.norm(title)
        if k not in books or (books[k]["index"] is None and o is not None):
            books[k] = {"title": title, "index": o, "year": int(y) if y.isdigit() else None,
                        "link": r.get("article", {}).get("value") or r["item"]["value"], "cover": ""}
    # each book's cover: the picture on its Wikipedia article (one request for up to 50 books)
    arts = {urllib.parse.unquote(b["link"].rsplit("/", 1)[-1]).replace("_", " "): b for b in books.values() if "wikipedia.org/wiki/" in b["link"]}
    if arts:
        try:
            for pg in _wp_pages(list(arts)):
                b = arts.get(pg.get("asked"))
                if b:
                    b["cover"] = (pg.get("thumbnail") or {}).get("source", "")
                    b["wiki"] = pg.get("title", "")
        except Exception as e:
            print("[inkwell] series covers skipped:", e)
    return sorted(books.values(), key=lambda b: (b["index"] is None, b["index"] or 0, b["year"] or 0))


def _missing(g, books):
    have_idx = set(g["have"])
    books = _mark([dict(b) for b in books])
    out = []
    for b in books:
        if b["have"] in ("owned", "ignored") or (b["index"] is not None and b["index"] in have_idx):
            continue
        b["series"], b["authors"] = g["series"], list(g["authors"])[:2]
        out.append(b)
    return out


def series_next(name, authors=()):
    """Books in this series you don't have yet, in order."""
    books = _cached(("series", series_mod.key(name)), 7 * 86400, lambda: _series_books(name, authors))
    g = next((g for g in my_series() if series_mod.key(g["series"]) == series_mod.key(name)), None) or {"series": name, "authors": list(authors), "have": []}
    return _missing(g, books)


# ---------------------------------------------------------------- more by your authors
def top_authors(n=12):
    return _memo_get(("authors", n), lambda: _top_authors_raw(n))


def _top_authors_raw(n=12):
    counts = {}
    for it in store.list_items():
        if it.get("kind") != "book" or not it.get("has_file"):
            continue
        for a in (it.get("authors") or [])[:1]:
            a = a.strip()
            if "," in a:
                last, first = [x.strip() for x in a.split(",", 1)]
                a = f"{first} {last}"
            if len(a) > 3 and not re.search(r"\.com|unknown", a, re.I):
                counts[a] = counts.get(a, 0) + 1
    return [a for a, _ in sorted(counts.items(), key=lambda x: -x[1])[:n]]


def _last(name):
    return re.sub(r"[^a-z]", "", (name or "").split(",")[0].split()[-1].lower()) if (name or "").strip() else ""


def by_author_raw(name, limit=40):
    last = _last(name)
    res = wp_books(f'"{name}" hastemplate:"Infobox book"', limit=limit)
    return [r for r in res if last and last in re.sub(r"[^a-z ]", "", r["blurb"].lower())]


def all_by_author(name, cat="book"):
    """Everything an author has out (for the home page's "View all releases"): books from Wikipedia, manga from the
    author's AniList page, comics from Wikipedia's comics pages. The ones you have are marked "owned"."""
    import media_catalog
    name = (name or "").strip()
    if "," in name:
        last, first = [x.strip() for x in name.split(",", 1)]
        name = f"{first} {last}"
    if not name:
        return {"items": [], "pending": False}

    def fetch():
        if cat == "manga":
            return media_catalog.manga_by_author(name)
        if hardcover_on():                 # the fullest lists (series, every book) when you have a Hardcover token
            try:
                got = hardcover_by_author(name)
                if got:
                    return [dict(r, cat=cat) for r in got]
            except Exception as e:
                print("[inkwell] hardcover author list:", e)
        if cat == "comic":
            last, seen, out = _last(name), set(), []
            for tpl in ("Infobox comic book title", "Infobox graphic novel"):
                for r in wp_books(f'"{name}" hastemplate:"{tpl}"', limit=30):
                    if last and last in re.sub(r"[^a-z ]", "", (r.get("blurb") or "").lower()) and r["title"] not in seen:
                        seen.add(r["title"])
                        out.append(dict(r, cat="comic"))
            return out
        return by_author_raw(name, 50)
    items = [dict(x) for x in _cached(("allby2", cat, name.lower()), 3 * 86400, fetch)]
    items = [r for r in _mark(items) if r.get("have") != "ignored"]
    # a manga or comic series you have some volumes of counts as yours ("Goodnight Punpun" vs "Goodnight Punpun, Vol. 1")
    mine = set()
    for it in store.list_items():
        if it.get("has_file") or it.get("physical"):
            for t in (it.get("series"), re.sub(r",?\s*(vol(ume)?\.?|book|#)\s*\d+.*$", "", it.get("title") or "", flags=re.I)):
                if t:
                    mine.add(journal.norm(t))
    for r in items:
        if cat != "book" and r.get("have") != "owned" and journal.norm(r.get("title") or "") in mine:
            r["have"] = "owned"
    items.sort(key=lambda r: r.get("have") == "owned")      # yours last; otherwise the source's order (most read first)
    return {"items": items, "pending": False}


def by_author(name, limit=40):
    return [r for r in _mark([dict(x) for x in _cached(("a3", name.lower()), 3 * 86400, lambda: by_author_raw(name, limit))]) if r["have"] not in ("owned", "ignored")]


# ---------------------------------------------------------------- the wishlist
def add_wanted(d, srv):
    title = (d.get("title") or "").strip()
    if not title:
        raise ValueError("No title.")
    cat = d.get("cat") or "book"
    have = _owned_index(cat in ("movie", "tv", "animation")).get(journal.norm(title))
    if have == "owned":
        raise ValueError("That's already in your library.")
    if have == "wanted":
        raise ValueError("That's already on your wishlist.")
    kind = {"manga": "graphic", "comic": "graphic", "movie": "movie", "tv": "tv", "animation": "movie" if d.get("form") == "movie" else "tv"}.get(cat, "book")
    data = {"kind": kind, "title": title, "authors": d.get("authors") or [], "year": str(d["year"]) if d.get("year") else None,
            "isbn": d.get("isbn") or None, "url": d.get("link") or d.get("ol_link") or None, "wanted": 1, "source": "wishlist"}
    if cat in ("manga", "comic"):
        data["format"] = cat
        data["direction"] = "rtl" if cat == "manga" and d.get("country", "JP") == "JP" else "ltr"
        data["series"] = d.get("series") or title
    if cat == "tv":
        data["series"] = title
    if d.get("series"):
        data["series"] = d["series"]
        if d.get("index") is not None:
            data["series_index"] = d["index"]
    iid = srv.create_entry(data)
    threading.Thread(target=_fetch_cover, args=(iid, d.get("cover") or "", d.get("isbn") or "", title, (d.get("authors") or [""])[0]), daemon=True).start()
    return iid


def _fetch_cover(iid, url, isbn="", title="", author=""):
    try:
        data = cover(url, isbn, title, author)
        if data and len(data) > 1500:
            name = f"{iid}.jpg"
            with open(os.path.join(store.COVERS_DIR, name), "wb") as f:
                f.write(data)
            store.update_item(iid, {"cover_path": name})
    except Exception as e:
        print("[inkwell] wishlist cover skipped:", e)


def claim_wanted(item_id):
    """A real book was added: if it was on the wishlist, the wanted entry gives way to it."""
    it = store.get_item(item_id)
    if not it or not it.get("has_file") or it.get("kind") not in ("book", "graphic"):
        return None
    keys = {journal.norm(it.get("title")), journal.norm(re.sub(r"\s*[:(].*$", "", it.get("title") or ""))}
    for w in store.list_items():
        if w["id"] == item_id or not w.get("wanted") or w.get("has_file"):
            continue
        if journal.norm(w.get("title")) in keys or (it.get("isbn") and it.get("isbn") == w.get("isbn")):
            upd = {k: w[k] for k in ("series", "series_index") if w.get(k) and not it.get(k)}
            if upd:
                store.update_item(item_id, upd)
            for c in w.get("collections") or []:
                store.collection_add(c, [item_id])
            journal._q("UPDATE media_log SET item_id=? WHERE item_id=?", (item_id, w["id"]), commit=True)
            store.delete_item(w["id"])
            return w.get("title")
    return None


# ---------------------------------------------------------------- browse: books unrelated to your library
YEAR = time.localtime().tm_year
SUBJECTS = [("trending", "Trending this month"), ("new", "New this year"), ("fantasy", "Fantasy"), ("scifi", "Science fiction"), ("mystery", "Mystery"),
            ("thriller", "Thrillers"), ("romance", "Romance"), ("historical", "Historical fiction"), ("horror", "Horror"),
            ("graphic", "Graphic novels"), ("biography", "Biography"), ("history", "History"), ("science", "Popular science"),
            ("philosophy", "Philosophy"), ("poetry", "Poetry"), ("humour", "Humour"), ("classics", "Classics")]
AISLE = {  # Wikipedia searches over book articles; (query, sort)
    "new": [(f'hastemplate:"Infobox book" "{YEAR} novel"', "create_timestamp_desc"), (f'hastemplate:"Infobox book" "{YEAR - 1} novel"', "create_timestamp_desc")],
    "fantasy": [('hastemplate:"Infobox book" "fantasy novel"', "incoming_links_desc"), (f'hastemplate:"Infobox book" "fantasy novel" "{YEAR - 1}"', "create_timestamp_desc")],
    "scifi": [('hastemplate:"Infobox book" "science fiction novel"', "incoming_links_desc"), (f'hastemplate:"Infobox book" "science fiction novel" "{YEAR - 1}"', "create_timestamp_desc")],
    "mystery": [('hastemplate:"Infobox book" "mystery novel"', "incoming_links_desc"), ('hastemplate:"Infobox book" "detective novel"', "incoming_links_desc")],
    "thriller": [('hastemplate:"Infobox book" "thriller novel"', "incoming_links_desc")],
    "romance": [('hastemplate:"Infobox book" "romance novel"', "incoming_links_desc")],
    "historical": [('hastemplate:"Infobox book" "historical novel"', "incoming_links_desc")],
    "horror": [('hastemplate:"Infobox book" "horror novel"', "incoming_links_desc")],
    "graphic": [('hastemplate:"Infobox comic book title" "graphic novel"', "incoming_links_desc"), ('hastemplate:"Infobox book" "graphic novel"', "incoming_links_desc")],
    "biography": [('hastemplate:"Infobox book" biography', "incoming_links_desc"), ('hastemplate:"Infobox book" memoir', "incoming_links_desc")],
    "history": [('hastemplate:"Infobox book" "history book"', "incoming_links_desc"), ('hastemplate:"Infobox book" "non-fiction book" history', "incoming_links_desc")],
    "science": [('hastemplate:"Infobox book" "popular science"', "incoming_links_desc")],
    "philosophy": [('hastemplate:"Infobox book" "philosophy" "book by"', "incoming_links_desc")],
    "poetry": [('hastemplate:"Infobox book" "poetry collection"', "incoming_links_desc")],
    "humour": [('hastemplate:"Infobox book" "comic novel"', "incoming_links_desc"), ('hastemplate:"Infobox book" "humorous"', "incoming_links_desc")],
    "classics": [('hastemplate:"Infobox book" novel', "incoming_links_desc")],
}


def _wp_pages(titles):
    """Descriptions and cover pictures for up to 50 Wikipedia articles at a time."""
    out = []
    for i in range(0, len(titles), 50):
        params = {"action": "query", "format": "json", "formatversion": "2", "titles": "|".join(titles[i:i + 50]), "redirects": 1,
                  "prop": "pageimages|description|info", "piprop": "thumbnail", "pilicense": "any", "pithumbsize": THUMB_W, "inprop": "url"}
        d = _json(WP + urllib.parse.urlencode(params))
        order = {t: n for n, t in enumerate(titles)}
        qd = d.get("query") or {}
        back = {}                                   # final title -> the title we asked for
        for m in (qd.get("normalized") or []) + (qd.get("redirects") or []):
            back[m["to"]] = back.get(m["from"], m["from"])
        pages = qd.get("pages") or []
        for pg in pages:
            asked = back.get(pg.get("title"), pg.get("title"))
            pg["asked"] = asked
            pg["index"] = order.get(asked, 10 ** 6)
        out += pages
    return out


def _book_from_page(pg):
    desc = (pg.get("description") or "").strip()
    if not BOOKISH.search(desc) or (NOT_BOOK.search(desc) and not re.search(r"\b(novel|book)\b", desc, re.I)) or NEVER_BOOK.search(desc + " " + pg.get("title", "")):
        return None
    if re.match(r"(list|bibliography|works) of\b", pg.get("title", ""), re.I):
        return None
    title = re.sub(r"\s*\([^)]*\b(?:novel|book|novella|comics?|memoir|series|collection|stories|poems|manga)\b[^)]*\)$", "", pg["title"])
    m = re.search(r"\bby\s+(.+?)\s*$", desc)
    y = re.search(r"\b(1[5-9]\d\d|20\d\d)\b", desc)
    return {"title": title, "authors": [m.group(1)] if m else [], "year": int(y.group(1)) if y else None,
            "cover": (pg.get("thumbnail") or {}).get("source", ""), "blurb": desc, "wiki": pg["title"],
            "link": pg.get("fullurl") or "https://en.wikipedia.org/wiki/" + urllib.parse.quote(pg["title"].replace(" ", "_"))}


def trending_raw():
    """The book articles people read most on Wikipedia over the last 30 days."""
    import datetime
    today = datetime.date.today()
    titles = top_viewed_titles()
    out, seen = [], set()
    for pg in sorted(_wp_pages(titles), key=lambda p: p["index"]):
        b = _book_from_page(pg)
        if b and journal.norm(b["title"]) not in seen:
            seen.add(journal.norm(b["title"]))
            out.append(b)
    # then the newer books the catalogue knows about, ranked by how much their articles were read this month
    cands = [dict(b) for b in (peek(("promos4",)) or []) + (peek(("browse3", "new")) or [])
             if b.get("wiki") and journal.norm(b.get("title")) not in seen]
    ranked = []
    for b in cands[:150]:
        if journal.norm(b["title"]) in seen:
            continue
        seen.add(journal.norm(b["title"]))
        try:
            n = _views_30d(b["wiki"], today)
        except Exception:
            continue
        if n >= 3000:                      # about a hundred readers a day
            ranked.append((n, {k: v for k, v in b.items() if k not in ("why", "kind_promo", "have")}))
    out += [b for _, b in sorted(ranked, key=lambda x: -x[0])]
    return out[:60]


def top_viewed_titles():
    """The 3000 most-read Wikipedia articles of the last 30 days, from the daily top-1000 lists (a whole month's list is
    only published after it ends; today's isn't out yet). Shared by every department's Trending aisle; kept a day."""
    import datetime
    def go():
        views = {}
        today = datetime.date.today()
        for back in range(1, 31):
            d = today - datetime.timedelta(days=back)
            try:
                data = _json(f"https://wikimedia.org/api/rest_v1/metrics/pageviews/top/en.wikipedia/all-access/{d.year}/{d.month:02d}/{d.day:02d}")
            except Exception as e:
                print("[inkwell] trending day skipped:", e)
                continue
            for a in (data.get("items") or [{}])[0].get("articles") or []:
                t = a.get("article", "")
                if ":" in t or t == "Main_Page":
                    continue
                views[t.replace("_", " ")] = views.get(t.replace("_", " "), 0) + a.get("views", 0)
        return [t for t, _ in sorted(views.items(), key=lambda x: -x[1])[:3000]]
    return _cached(("topviews",), 86400, go)


def _views_30d(wtitle, today):
    import datetime
    a, b = today - datetime.timedelta(days=30), today - datetime.timedelta(days=1)
    art = urllib.parse.quote(wtitle.replace(" ", "_"), safe="")
    d = _json(f"https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia/all-access/user/{art}/daily/"
              f"{a:%Y%m%d}/{b:%Y%m%d}")
    return sum(x.get("views", 0) for x in d.get("items") or [])


def browse_raw(subject, page=0, sort_override=None):
    if subject == "trending":
        return trending_raw()
    out, seen, err = [], set(), None
    for q, sort in AISLE.get(subject, AISLE["new"]):
        try:
            for r in wp_books(q, limit=40, sort=sort_override or sort, offset=page * 40):
                k = journal.norm(r["title"])
                if k not in seen:
                    seen.add(k)
                    out.append(r)
        except Exception as e:
            err = e
    if not out and err:
        raise err
    return out


# ---------------------------------------------------------------- promotions: recent sequels and new books by your authors
def _recent_releases(months=6):
    """Books with a Wikipedia article whose release date (to the month or day) falls in the last few months."""
    import datetime
    since = (datetime.date.today() - datetime.timedelta(days=int(months * 30.5))).isoformat()
    q = f"""SELECT ?item ?itemLabel ?date ?authorLabel ?article ?links WHERE {{
      VALUES ?type {{ wd:Q7725634 wd:Q8261 wd:Q571 wd:Q47461344 wd:Q725377 wd:Q8274 }}
      ?item wdt:P31 ?type ; p:P577 ?ds .
      ?ds psv:P577 [ wikibase:timeValue ?date ; wikibase:timePrecision ?prec ] .
      FILTER(?prec >= 10 && ?date >= "{since}T00:00:00Z"^^xsd:dateTime && ?date <= NOW())
      ?article schema:about ?item ; schema:isPartOf <https://en.wikipedia.org/> .
      ?item wikibase:sitelinks ?links .
      OPTIONAL {{ ?item wdt:P50 ?author }}
      OPTIONAL {{ ?item wdt:P212 ?isbn }}
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
    }} ORDER BY DESC(?links) LIMIT 300"""
    rows = _json(SPARQL + urllib.parse.quote(q), accept="application/sparql-results+json").get("results", {}).get("bindings", [])
    books = {}
    for r in rows:
        art = r.get("article", {}).get("value", "")
        if not art:
            continue
        b = books.setdefault(art, {"wtitle": urllib.parse.unquote(art.rsplit("/", 1)[-1]).replace("_", " "), "authors": [],
                                    "date": r["date"]["value"][:10], "links": int(r.get("links", {}).get("value") or 0)})
        a = r.get("authorLabel", {}).get("value")
        if a and not re.fullmatch(r"Q\d+", a) and a not in b["authors"]:
            b["authors"].append(a)
        b["date"] = min(b["date"], r["date"]["value"][:10])
        if r.get("isbn", {}).get("value"):
            b["isbn"] = re.sub(r"[^0-9Xx]", "", r["isbn"]["value"])
    pages = {p.get("asked"): p for p in _wp_pages([b["wtitle"] for b in books.values()])}
    out = []
    for b in books.values():
        pg = pages.get(b["wtitle"]) or {"title": b["wtitle"]}
        bk = _book_from_page({**pg, "description": pg.get("description") or "book"}) or {}
        if not bk:
            continue
        bk["authors"] = b["authors"] or bk.get("authors") or []
        bk["released"] = b["date"]
        bk["year"] = int(b["date"][:4])
        bk["links"] = b["links"]
        bk["isbn"] = b.get("isbn", "")
        out.append(bk)
    return out


def promos_raw():
    """Hot off the press: notable new books from the last six months. Sequels to your series and books by your
    authors come first, then everything else that's new."""
    mine = {_last(a) for a in top_authors(40)}
    series_titles = {}
    for g in my_series():
        for b in peek(("series", series_mod.key(g["series"]))) or []:
            series_titles[journal.norm(b["title"])] = (g["series"], b.get("index"))
    out = []
    try:
        recent = _recent_releases(6)
    except Exception as e:
        print("[inkwell] hot off the press: wikidata skipped:", e)
        recent = []
    for b in recent:
        k = journal.norm(b["title"])
        if k in series_titles:
            name, idx = series_titles[k]
            b["why"], b["kind_promo"] = f"New in {name}" + (f": book {idx:g}" if idx is not None else ""), "sequel"
        elif any(_last(a) in mine for a in b["authors"]):
            b["why"], b["kind_promo"] = f"New from {b['authors'][0]}", "author"
        else:
            b["why"], b["kind_promo"] = "Out " + time.strftime("%b %Y", time.strptime(b["released"], "%Y-%m-%d")), "new"
        out.append(b)
    seen = {journal.norm(b["title"]) for b in out}
    for src, fn in (("hardcover", hardcover_raw), ("nyt", nyt_raw)):
        try:
            for b in fn():
                k = journal.norm(b["title"])
                if k in series_titles and k not in seen:
                    name, idx = series_titles[k]
                    b["why"], b["kind_promo"] = f"New in {name}" + (f": book {idx:g}" if idx is not None else ""), "sequel"
                elif k not in seen and any(_last(a) in mine for a in b["authors"]):
                    b["why"], b["kind_promo"] = f"New from {b['authors'][0]}", "author"
                if k not in seen:
                    seen.add(k)
                    out.append(b)
        except Exception as e:
            print(f"[inkwell] hot off the press: {src} skipped:", e)
    rank = {"sequel": 0, "author": 1, "nyt": 2, "hardcover": 3, "new": 4}
    return sorted(out, key=lambda b: (rank[b["kind_promo"]], -(b.get("links") or b.get("readers") or 0)))


# ---------------------------------------------------------------- serving: show what's known now, fill in the rest
# Every list is answered at once from what's saved (however old), and refreshed in the background when stale.
# "pending" tells the page to look again in a moment for the new arrivals.
_bg = {}
_errors = {}


def _refresh(key, fn):
    k = json.dumps(key)
    if k in _bg:
        return
    def run():
        try:
            _cached(key, 0, fn)
            _errors.pop(k, None)
        except Exception as e:
            _errors[k] = e
            print("[inkwell] discover:", key[0], e)
        finally:
            _bg.pop(k, None)
    _bg[k] = threading.Thread(target=run, daemon=True)
    _bg[k].start()


def swr(key, ttl, fn):
    k = json.dumps(key)
    hit = _cache.get(k)
    if not hit or time.time() - hit[0] >= ttl:
        _refresh(key, fn)
    return (hit[1] if hit else None), k in _bg, _errors.get(k) if not hit else None


def serve_list(key, ttl, fn, keep_owned=False):
    val, pending, err = swr(key, ttl, fn)
    items = _mark([dict(x) for x in (val or [])])
    if not keep_owned:
        items = [r for r in items if r["have"] not in ("owned", "ignored")]
    return {"items": items, "pending": pending, "error": _err_text(err) if err and not items else ""}


def _err_text(e):
    if isinstance(e, urllib.error.HTTPError) and e.code in (429, 503):
        return "The catalogue is busy right now. It'll try again shortly."
    if isinstance(e, (urllib.error.URLError, ConnectionError, TimeoutError, OSError)):
        return "Couldn't reach the book catalogues right now. It'll keep trying in the background."
    return f"Something went wrong ({type(e).__name__})."


def _browse_key(subject, yfrom=None, yto=None):
    if yfrom or yto:
        return ("browse3y", subject, str(yfrom or ""), str(yto or ""))
    return ("trending2",) if subject == "trending" else ("browse3", subject)


def in_years(r, yfrom=None, yto=None):
    if not (yfrom or yto):
        return True
    y = r.get("year")
    try:
        y = int(str(y)[:4])
    except (TypeError, ValueError):
        return False
    return (not yfrom or y >= int(yfrom)) and (not yto or y <= int(yto))


def browse_years(subject, yfrom=None, yto=None, page=0, sort_override=None):
    """An aisle limited to books from a span of years. Wikipedia can't search by year, so the years asked for are
    added to the search (when it's a short span) and only the books that fit are kept."""
    if subject == "trending":
        return [r for r in trending_raw() if in_years(r, yfrom, yto)]
    span = list(range(int(yfrom or 1500), int(yto or YEAR) + 1))
    extra = (" (" + " OR ".join(f'"{y}"' for y in span) + ")") if len(span) <= 12 else ""
    out, seen = [], set()
    for p in range(page, page + 3):
        for q, sort in AISLE.get(subject, AISLE["new"]):
            try:
                for r in wp_books(q + extra, limit=40, sort=sort_override or sort, offset=p * 40):
                    k = journal.norm(r["title"])
                    if k not in seen and in_years(r, yfrom, yto):
                        seen.add(k)
                        out.append(r)
            except Exception as e:
                print("[inkwell] aisle by years skipped:", e)
        if len(out) >= 30:
            break
    return out


def restock(subject, yfrom=None, yto=None):
    """Put different books in an aisle: the next 40 or so from its search that you haven't been shown yet (ones you
    own or hid are left out as always). When an aisle runs out, it starts over with a random pick. Trending and New
    this year are fetched afresh instead."""
    subject = subject if subject in AISLE or subject == "trending" else "new"
    key = _browse_key(subject, yfrom, yto)
    raw = (lambda page=0, sort=None: browse_years(subject, yfrom, yto, page, sort)) if (yfrom or yto) else \
          (lambda page=0, sort=None: browse_raw(subject, page, sort))
    if subject == "trending":
        _cached(key, 0, raw)
        return serve_browse(subject, yfrom, yto)
    skey = json.dumps(["aislestate", subject] + ([str(yfrom or ""), str(yto or "")] if (yfrom or yto) else []))
    with _cache_lock:
        st = dict((_cache.get(skey) or (0, {}))[1])
    seen = set(st.get("seen") or []) | {journal.norm(b.get("title")) for b in (peek(key) or [])}
    page, out, wrapped = int(st.get("page") or 0), [], False
    hide = set(_owned_index()) | ignored()
    for _ in range(4):
        page += 1
        batch = raw(page) if not wrapped else raw(0, "random")
        if not batch and not wrapped:
            wrapped, page = True, 0             # past the end of the aisle: start over with a random pick
            continue
        out += [b for b in batch if journal.norm(b["title"]) not in seen and journal.norm(b["title"]) not in hide
                and not any(journal.norm(b["title"]) == journal.norm(x["title"]) for x in out)]
        if len(out) >= 30:
            break
    if not out:
        raise LookupError("No more books found for this aisle right now.")
    with _cache_lock:
        _cache[json.dumps(list(key))] = (time.time(), out)
        _cache[skey] = (time.time(), {"page": page, "seen": list(seen)[-600:]})
    _save_cache()
    return serve_browse(subject, yfrom, yto)


def serve_browse(subject, yfrom=None, yto=None):
    subject = subject if subject in AISLE or subject == "trending" else "new"
    if yfrom or yto:
        return serve_list(_browse_key(subject, yfrom, yto), 3 * 86400, lambda: browse_years(subject, yfrom, yto))
    return serve_list(_browse_key(subject), 3 * 86400 if subject not in ("new", "trending") else 86400, lambda: browse_raw(subject))


def serve_promos():
    return serve_list(("promos4",), 86400, promos_raw)


def _all_series():
    for g in my_series():
        key = ("series", series_mod.key(g["series"]))
        old = peek(key)
        _cached(key, 0 if old and any("cover" not in b for b in old) else 7 * 86400, lambda g=g: _series_books(g["series"], g["authors"]))


def serve_series():
    """Every series you own with the books missing from it; complete series are left out."""
    out, unknown = [], 0
    for g in my_series():
        hit = _cache.get(json.dumps(["series", series_mod.key(g["series"])]))
        if not hit:
            unknown += 1
            continue
        miss = _missing(g, hit[1])
        if miss:
            out.append(dict(g, missing=miss))
    pending = False
    def stale(g):
        hit = _cache.get(json.dumps(["series", series_mod.key(g["series"])])) or (0, [])
        # older saved lists have no covers yet: fetch them again once
        return time.time() - hit[0] > 7 * 86400 or any("cover" not in b for b in hit[1])
    if unknown or any(stale(g) for g in my_series()):
        k = json.dumps(["allseries"])
        if k not in _bg:
            _refresh(("allseries",), lambda: _all_series() or [])
        pending = True
    pending = pending and json.dumps(["allseries"]) in _bg
    return {"items": out, "pending": pending, "complete": len(my_series()) - unknown - len(out)}


def serve_authors():
    out, missing = [], False
    for a in top_authors(12):
        hit = _cache.get(json.dumps(["a3", a.lower()]))
        if hit:
            books = [r for r in _mark([dict(x) for x in hit[1]]) if r["have"] not in ("owned", "ignored")]
            if books:
                out.append({"author": a, "books": books})
        else:
            missing = True
    if missing:
        _refresh(("allauthors",), lambda: [by_author(a) for a in top_authors(12)] and [])
    return {"items": out, "pending": json.dumps(["allauthors"]) in _bg}


# ---------------------------------------------------------------- "new on the shelves" for the catalogue button
SHELVES_KEY = json.dumps(["shelves-updated"])


def mark_shelves_updated():
    with _cache_lock:
        _cache[SHELVES_KEY] = (time.time(), True)
    _save_cache()


def shelves_updated_at():
    return (_cache.get(SHELVES_KEY) or (0, None))[0]


def _shelf_print():
    """A fingerprint of what's on the shelves now (Hot off the press and every aisle's titles)."""
    keys = [("promos4",)] + [_browse_key(k) for k, _ in SUBJECTS]
    out = []
    for k in keys:
        v = (_cache.get(json.dumps(list(k))) or (0, None))[1]
        items = v if isinstance(v, list) else (v or {}).get("items") if isinstance(v, dict) else None
        out.append("|".join(str(r.get("title")) for r in (items or [])[:40] if isinstance(r, dict)))
    return hash("\n".join(out))


# ---------------------------------------------------------------- the background gatherer
def warm():
    """Gather everything the catalogue shows, quietly, so it's ready when it's opened."""
    before = _shelf_print()
    try:
        covers_for_shelf()
    except Exception as e:
        print("[inkwell] shelf covers:", e)
    jobs = [(("allseries",), lambda: _all_series() or [])]
    jobs += [(("promos4",), promos_raw)]
    jobs += [(_browse_key(k), (lambda k=k: browse_raw(k))) for k, _ in SUBJECTS if k != "trending"]
    jobs += [(_browse_key("trending"), trending_raw)]   # last: it ranks the new books gathered above
    for key, fn in jobs:
        try:
            _cached(key, 12 * 3600, fn)
        except Exception as e:
            print("[inkwell] discover gathering:", key[0], e)
    for a in top_authors(12):
        try:
            by_author(a)
        except Exception as e:
            print("[inkwell] discover gathering:", a, e)
    try:                          # once a week every aisle in every department restocks itself
        import media_catalog
        media_catalog.weekly_restock()
    except Exception as e:
        print("[inkwell] weekly restock skipped:", e)
    if before and _shelf_print() != before:
        mark_shelves_updated()    # the shelves have new titles, ready to look at
    # covers last
    seen = set()
    for v in list(_cache.values()):
        for r in v[1] if isinstance(v[1], list) else []:
            if not isinstance(r, dict) or not r.get("title"):
                continue
            k = r.get("cover") or r.get("isbn") or r.get("title")
            if k in seen:
                continue
            seen.add(k)
            try:
                cover(r.get("cover") or "", r.get("isbn") or "", r.get("title") or "", (r.get("authors") or [""])[0])
            except Exception:
                pass


def start_gatherer(first_delay=8, every=12 * 3600):
    def loop():
        time.sleep(first_delay)
        while True:
            try:
                warm()
            except Exception as e:
                print("[inkwell] discover gathering stopped:", e)
            time.sleep(every)
    threading.Thread(target=loop, daemon=True).start()


def needs_cover(it):
    """Books without a cover that the app can't draw one for itself (PDFs and comics get their first page)."""
    return (it.get("kind") in ("book", "graphic") and not it.get("has_cover")
            and (not it.get("has_file") or it.get("file_type") == "epub"))


def pull_cover(it):
    """Fetch a cover for a book on the shelves (Hardcover first, then Wikipedia and the rest) and save it.
    Returns the saved file name; raises LookupError when no source has one."""
    data = cover("", it.get("isbn") or "", it.get("title") or "", (it.get("authors") or [""])[0], hc_first=True)
    name = f"{it['id']}-c.jpg"
    with open(os.path.join(store.COVERS_DIR, name), "wb") as f:
        f.write(data)
    store.update_item(it["id"], {"cover_path": name})
    return name


def covers_for_shelf():
    """Books without a cover (physical copies, wishes, EPUBs without one inside) get one from the web."""
    got = []
    for it in store.list_items():
        if not needs_cover(it):
            continue
        try:
            pull_cover(it)
            got.append(it.get("title"))
        except Exception:
            pass
    return got


# ---------------------------------------------------------------- "I own this": a wished-for book you've got on paper
def mark_owned(item_id, srv):
    it = store.get_item(item_id)
    if not it:
        raise LookupError("Not found.")
    store.update_item(item_id, {"wanted": 0, "physical": 1})
    it = store.get_item(item_id)
    linked = journal.link_orphans(it)
    def finish():
        if not it.get("has_cover"):
            try:
                data = cover("", it.get("isbn") or "", it.get("title") or "", (it.get("authors") or [""])[0])
                with open(os.path.join(store.COVERS_DIR, f"{item_id}.jpg"), "wb") as f:
                    f.write(data)
                store.update_item(item_id, {"cover_path": f"{item_id}.jpg"})
            except Exception as e:
                print("[inkwell] cover for owned book skipped:", e)
        srv.analyze_item(item_id, True, ("series", "series_index"))
    threading.Thread(target=finish, daemon=True).start()
    return {"linked": linked}


# ---------------------------------------------------------------- New York Times bestsellers (free API key in Settings)
NYT = "https://api.nytimes.com/svc/books/v3/"
SMALL = {"a", "an", "the", "and", "but", "or", "for", "nor", "on", "at", "to", "from", "by", "of", "in", "with", "as"}


def _nice_title(t):
    """NYT titles come in capitals: 'THE WIND AND TRUTH' -> 'The Wind and Truth'."""
    if not t or t != t.upper():
        return t or ""
    words = t.lower().split()
    out = []
    for i, w in enumerate(words):
        out.append(w if (i and w in SMALL) else re.sub(r"^([^a-z]*)([a-z])", lambda m: m.group(1) + m.group(2).upper(), w))
    return " ".join(out)


_rejected_keys = set()


def _nyt_key(testing=False):
    """The NYT key, unless the NYT has already turned it down (then it's left alone until a new key is saved)."""
    key = (store.get_settings().get("nyt_key") or "").strip()
    return key if key and (testing or key not in _rejected_keys) else ""


def _nyt_json(url, key):
    try:
        return _json(url)
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            _rejected_keys.add(key)
        raise


def nyt_raw(testing=False):
    key = _nyt_key(testing)
    if not key:
        return []
    d = _nyt_json(NYT + "lists/overview.json?" + urllib.parse.urlencode({"api-key": key}), key)
    out, seen = [], set()
    for lst in (d.get("results") or {}).get("lists") or []:
        name = lst.get("display_name") or lst.get("list_name") or ""
        if re.search(r"children|picture|middle grade|series", name, re.I):
            continue
        for b in lst.get("books") or []:
            title = _nice_title(b.get("title"))
            k = journal.norm(title)
            if not k or k in seen:
                continue
            seen.add(k)
            weeks = b.get("weeks_on_list") or 0
            out.append({"title": title, "authors": [b.get("author") or ""] if b.get("author") else [], "year": YEAR,
                        "cover": b.get("book_image") or "", "isbn": b.get("primary_isbn13") or "", "blurb": b.get("description") or "",
                        "link": b.get("amazon_product_url") or "", "kind_promo": "nyt",
                        "why": f"#{b.get('rank')} {name}" + (" · new this week" if weeks <= 1 else f" · {weeks} weeks")})
    return out


def nyt_reviews(isbn="", title=""):
    key = _nyt_key()
    if not key or not (isbn or title):
        return []
    q = {"api-key": key, **({"isbn": isbn} if isbn else {"title": title})}
    d = _nyt_json(NYT + "reviews.json?" + urllib.parse.urlencode(q), key)
    return [{"summary": r.get("summary") or "", "by": r.get("byline") or "", "url": r.get("url") or "", "date": r.get("publication_dt") or ""}
            for r in d.get("results") or []][:3]


# ---------------------------------------------------------------- Hardcover (free personal token in Settings)
HC = "https://api.hardcover.app/v1/graphql"


def _hc(query, variables=None):
    import urllib.request
    tok = (store.get_settings().get("hardcover_token") or "").strip()
    if not tok:
        raise LookupError("no hardcover token")
    if not tok.lower().startswith("bearer "):
        tok = "Bearer " + tok
    wait = lookup.reserve("api.hardcover.app", 1.1)   # Hardcover allows about one request a second
    if wait > 0:
        time.sleep(wait)
    body = json.dumps({"query": query, "variables": variables or {}}).encode()
    req = urllib.request.Request(HC, data=body, headers={"Content-Type": "application/json", "authorization": tok,
                                                         "User-Agent": lookup.UA})
    with urllib.request.urlopen(req, timeout=20) as r:
        d = json.loads(r.read())
    if d.get("errors"):
        raise ValueError("Hardcover: " + "; ".join(e.get("message", "") for e in d["errors"])[:200])
    return d.get("data") or {}


HC_RECENT = """query Recent($since: date!, $until: date!) {
  books(where: {release_date: {_gte: $since, _lte: $until}, users_count: {_gte: 20}}, order_by: {users_count: desc}, limit: 60) {
    id title slug release_date rating ratings_count users_count description
    image { url }
    contributions(limit: 2) { author { name } }
    book_series(limit: 1) { position series { name } }
  }
}"""


HC_AUTHOR = """query ByAuthor($name: String!) {
  authors(where: {name: {_eq: $name}}, order_by: {books_count: desc}, limit: 1) {
    contributions(where: {contributable_type: {_eq: "Book"}}, order_by: {book: {users_count: desc}}, limit: 80) {
      book { title slug release_date rating users_count compilation description
        image { url } book_series(limit: 1) { position series { name } } } } } }"""


def hardcover_by_author(name):
    """An author's books on Hardcover, most read first: no box sets, no duplicate editions, nothing nobody has read."""
    d = _hc(HC_AUTHOR, {"name": name})
    out, seen = [], set()
    for c in ((d.get("authors") or [{}])[0] or {}).get("contributions") or []:
        b = c.get("book") or {}
        k = journal.norm(re.sub(r"[:(].*$", "", b.get("title") or ""))
        if not k or b.get("compilation") or (b.get("users_count") or 0) < 3 or k in seen:
            continue
        seen.add(k)
        ser = (b.get("book_series") or [{}])[0] if b.get("book_series") else {}
        rel = b.get("release_date") or ""
        out.append({"cat": "book", "title": b.get("title") or "", "authors": [name], "year": int(rel[:4]) if rel[:4].isdigit() and rel[:4] > "1000" else None,
                    "cover": (b.get("image") or {}).get("url") or "", "blurb": (b.get("description") or "").strip(),
                    "link": f"https://hardcover.app/books/{b.get('slug')}" if b.get("slug") else "",
                    "series": (ser.get("series") or {}).get("name"), "index": ser.get("position"),
                    "rating": b.get("rating"), "readers": b.get("users_count")})
    return out


def hardcover_raw(months=6):
    import datetime
    if not (store.get_settings().get("hardcover_token") or "").strip():
        return []
    today = datetime.date.today()
    since = today - datetime.timedelta(days=int(months * 30.5))
    d = _hc(HC_RECENT, {"since": since.isoformat(), "until": today.isoformat()})
    out = []
    for b in d.get("books") or []:
        ser = (b.get("book_series") or [{}])[0] if b.get("book_series") else {}
        rel = b.get("release_date") or ""
        out.append({"title": b.get("title") or "", "authors": [c["author"]["name"] for c in b.get("contributions") or [] if c.get("author")],
                    "year": int(rel[:4]) if rel[:4].isdigit() else None, "released": rel, "cover": (b.get("image") or {}).get("url") or "",
                    "blurb": (b.get("description") or "").strip(), "link": f"https://hardcover.app/books/{b.get('slug')}" if b.get("slug") else "",
                    "series": (ser.get("series") or {}).get("name"), "index": ser.get("position"),
                    "rating": b.get("rating"), "ratings": b.get("ratings_count"), "readers": b.get("users_count"), "kind_promo": "hardcover",
                    "why": f"★ {b['rating']:.1f} · {b.get('users_count')} readers" if b.get("rating") else f"{b.get('users_count')} readers"})
    return out


HC_FIND = """query Find($q: String!) { search(query: $q, query_type: "Book", per_page: 5) { results } }"""
HC_REVIEWS = """query Reviews($id: Int!) {
  user_books(where: {book_id: {_eq: $id}, has_review: {_eq: true}}, order_by: {likes_count: desc_nulls_last}, limit: 5) {
    rating review_raw user { username }
  }
}"""


def hardcover_on():
    return bool((store.get_settings().get("hardcover_token") or "").strip())


def _hc_hits(q):
    d = _hc(HC_FIND, {"q": q})
    return [h["document"] for h in ((d.get("search") or {}).get("results") or {}).get("hits") or [] if h.get("document")]


def hardcover_match(title, author="", isbn="", loose=False):
    """The Hardcover book for a title (and author / ISBN). An ISBN that Hardcover knows decides it; otherwise the title
    must match, and among several with that title the one by this author, then the most read, wins.
    loose: fall back to the top search hit (fine for showing a rating, not for changing your library)."""
    isbn = re.sub(r"[^0-9Xx]", "", isbn or "").upper()
    def go():
        if isbn:
            doc = next((x for x in _hc_hits(isbn) if isbn in [i.upper() for i in x.get("isbns") or []]), None)
            if doc:
                return doc
        if not title:
            return None
        hits = _hc_hits(f"{title} {author}".strip()) or (_hc_hits(title) if author else [])
        short = lambda t: journal.norm(re.sub(r"\s*[:(].*$", "", t or ""))
        same = [x for x in hits if journal.norm(x.get("title")) == journal.norm(title) or short(x.get("title")) == short(title)]
        last = _last(author)
        mine = [x for x in same if last and any(_last(a) == last for a in x.get("author_names") or [])]
        pick = sorted(mine or same, key=lambda x: -(x.get("users_count") or 0))
        return pick[0] if pick else (hits[0] if loose and hits else None)
    return _cached(("hcm", journal.norm(title), _last(author), isbn, loose), 7 * 86400, go)


def hc_genres(doc):
    """Hardcover's genre list, tidied: its tags are user-made, so drop shelf names and stray JSON fragments."""
    out, seen = [], set()
    for g in (doc or {}).get("genres") or []:
        g = re.sub(r'[\[\]"]+', "", g or "").strip()
        if not g or ";" in g or re.fullmatch(r"[a-z]+(?:-[a-z]+)+", g) or g.lower() in seen or len(g) > 40:
            continue
        seen.add(g.lower())
        out.append(g if g != g.lower() else g.title())
    return out


def hc_genre(genres):
    """(genre, fiction) on your shelves from Hardcover's genres. Readers list them most-used first, so the first one
    that names a shelf wins (Dungeon Crawler Carl: Fantasy, not the Science Fiction its later tags add up to)."""
    import taxonomy
    _, fiction = taxonomy.genre_from_categories(genres)
    for g in genres:
        hit, _f = taxonomy.genre_from_categories([g])
        if hit and (fiction is None or (hit in taxonomy.FICTION_GENRES) == bool(fiction)):
            return hit, fiction
    return taxonomy.genre_from_categories(genres)


def hc_cover_url(doc):
    img = (doc or {}).get("image")
    return (img.get("url") if isinstance(img, dict) else "") or ""


def hardcover_details(title, author="", isbn=""):
    """What Babel's Library can take from Hardcover for a book in your library."""
    import taxonomy
    doc = hardcover_match(title, author, isbn)
    if not doc:
        return None
    authors = [c["author"]["name"] for c in doc.get("contributions") or []
               if (c.get("contribution") or "Author") == "Author" and (c.get("author") or {}).get("name")] or (doc.get("author_names") or [])[:1]
    genres = hc_genres(doc)
    genre, fiction = hc_genre(genres)
    ser = (doc.get("featured_series") or {})
    by_isbn = bool(isbn) and isbn in [i.upper() for i in doc.get("isbns") or []]
    return {"title": doc.get("title") or "", "authors": authors, "year": str(doc.get("release_year") or "") or None,
            "summary": re.sub(r"\s+\n", "\n", (doc.get("description") or "").strip()), "genres": genres, "genre": genre, "fiction": fiction,
            "series": ((ser.get("series") or {}).get("name") or None) if ser.get("featured") else None,
            "series_index": ser.get("position") if ser.get("featured") else None,
            # Hardcover lists every edition's ISBN (translations too), so none of them is "this copy's" unless it matched
            "isbn": isbn if by_isbn else None,
            "cover": hc_cover_url(doc), "url": f"https://hardcover.app/books/{doc.get('slug')}" if doc.get("slug") else "",
            "matched_by": "isbn" if isbn and isbn in [i.upper() for i in doc.get("isbns") or []] else "title"}


def hardcover_book(title, author=""):
    doc = hardcover_match(title, author, loose=True)
    if not doc:
        return None
    genres = hc_genres(doc)
    out = {"rating": doc.get("rating"), "ratings": doc.get("ratings_count"), "description": doc.get("description") or "",
           "url": f"https://hardcover.app/books/{doc.get('slug')}" if doc.get("slug") else "", "reviews": [],
           "genres": genres[:6], "genre": hc_genre(genres)[0],
           "cover": hc_cover_url(doc)}
    try:
        r = _hc(HC_REVIEWS, {"id": int(doc.get("id"))})
        out["reviews"] = [{"by": (u.get("user") or {}).get("username") or "a reader", "rating": u.get("rating"),
                           "text": re.sub(r"\s+", " ", u.get("review_raw") or "")[:900]} for u in r.get("user_books") or [] if u.get("review_raw")]
    except Exception as e:
        print("[inkwell] hardcover reviews skipped:", e)
    return out


def test_keys():
    forget(("promos4",))
    res = {}
    if (store.get_settings().get("nyt_key") or "").strip():
        try:
            _rejected_keys.clear()
            res["nyt"] = f"Working: {len(nyt_raw(testing=True))} bestsellers"
        except Exception as e:
            res["nyt"] = f"Not working: {e}"
    if (store.get_settings().get("hardcover_token") or "").strip():
        try:
            res["hardcover"] = f"Working: {len(hardcover_raw())} recent releases"
        except Exception as e:
            res["hardcover"] = f"Not working: {e}"
    return res


# ---------------------------------------------------------------- "More info": a book's page inside the catalogue
def _wp_sections(wtitle):
    params = {"action": "query", "format": "json", "formatversion": "2", "prop": "extracts|pageimages|info|description", "explaintext": 1,
              "exsectionformat": "wiki", "titles": wtitle, "redirects": 1, "piprop": "thumbnail", "pilicense": "any", "pithumbsize": 500, "inprop": "url"}
    pg = ((_json(WP + urllib.parse.urlencode(params)).get("query") or {}).get("pages") or [{}])[0]
    text = pg.get("extract") or ""
    parts = re.split(r"\n(=+)\s*(.+?)\s*=+\n", "\n" + text)
    intro = parts[0].strip()
    secs = {}
    for i in range(1, len(parts) - 2, 3):
        name = parts[i + 1].strip().lower()
        if len(parts[i]) == 2:                      # top-level sections only
            secs[name] = parts[i + 2].strip()
        elif secs:                                  # fold subsections into their parent
            last = list(secs)[-1]
            secs[last] += "\n\n" + parts[i + 2].strip()
    pick = lambda *names: next((secs[n] for n in secs if any(n.startswith(x) for x in names) and secs[n]), "")
    return {"intro": intro, "synopsis": pick("plot", "synopsis", "summary", "premise", "story", "narrative", "content", "contents", "overview"),
            "reception": pick("reception", "critical reception", "reviews", "critical response", "response"),
            "cover": (pg.get("thumbnail") or {}).get("source", ""), "url": pg.get("fullurl") or "", "title": pg.get("title") or wtitle,
            "description": pg.get("description") or ""}


def _clip(t, n):
    t = (t or "").strip()
    if len(t) <= n:
        return t
    cut = t.rfind(". ", 0, n)
    return t[:cut + 1 if cut > n * 0.5 else n] + " …"


def info(title, author="", wiki="", isbn="", link=""):
    """Synopsis, reception and reviews for a book, from Wikipedia, plus Hardcover and the NYT when keys are set."""
    def go():
        out = {"title": title, "author": author, "links": []}
        w = wiki or (re.sub(r"^https?://en\.wikipedia\.org/wiki/", "", link) if "wikipedia.org/wiki/" in (link or "") else "")
        w = urllib.parse.unquote(w).replace("_", " ")
        if not w:
            try:
                last = _last(author)
                t = journal.norm(title)
                hit = None
                for tpl in ("Infobox book", "Infobox book series"):   # a series (Dungeon Crawler Carl) has its own infobox
                    res = wp_books(f'{title} {last} hastemplate:"{tpl}"'.strip(), limit=6, sort="relevance")
                    hit = next((r for r in res if journal.norm(r["title"]) == t), None)
                    if hit:
                        break
                w = hit["wiki"] if hit else ""
            except Exception as e:
                print("[inkwell] info: wikipedia search skipped:", e)
        if w:
            try:
                sec = _wp_sections(w)
                out.update(intro=_clip(sec["intro"], 1400), synopsis=_clip(sec["synopsis"], 2600), reception=_clip(sec["reception"], 2200),
                           cover=sec["cover"])
                out["links"].append({"label": "Wikipedia", "url": sec["url"]})
                # the shelf it would go on, from Wikipedia's one-line description ("2018 psychological thriller novel")
                import taxonomy
                first = re.split(r"(?<=\.)\s", sec["intro"] or "", 1)[0]
                out["genre"] = taxonomy.genre_from_categories([sec.get("description") or "", first])[0]
            except Exception as e:
                print("[inkwell] info: wikipedia skipped:", e)
        if link and not any(l["url"] == link for l in out["links"]):
            out["links"].append({"label": urllib.parse.urlparse(link).netloc.replace("www.", ""), "url": link})
        return out
    return _cached(("info3", journal.norm(title), journal.norm(author)), 7 * 86400, go)


def reviews(title, author="", isbn=""):
    """Ratings and reviews from Hardcover and the New York Times (each only when its key is set)."""
    def go():
        out = {}
        if hardcover_on():
            try:
                out["hardcover"] = hardcover_book(title, author)
            except Exception as e:
                out["hardcover_error"] = str(e)
        if _nyt_key():
            try:
                out["nyt"] = nyt_reviews(isbn, "" if isbn else title)
            except Exception as e:
                out["nyt_error"] = str(e)
        return out
    return _cached(("reviews2", journal.norm(title), journal.norm(author)), 3 * 86400, go)
