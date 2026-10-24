"""DOI / ISBN / URL metadata lookup. The only part of Babel's Library that uses the internet,
and it fails quietly when offline."""
import html
import json
import re
import urllib.error
import urllib.parse
import urllib.request

from extract import DOI_RE, clean_doi, clean_isbn

UA = "BabelsLibrary/1.3 (personal book library app; babels-library-app@users.noreply.github.com)"
UA_ALT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
_ua_for = {}
_fails, _down = {}, {}   # a site that refuses every connection is left alone for a while


def check_down(host):
    if _down.get(host, 0) > _time.time():
        raise urllib.error.URLError(f"{host} is refusing connections; trying again later")   # host -> the user agent it accepts (some sites drop connections from unfamiliar ones)


import threading as _th
import time as _time

_last_call = {}
_call_lock = _th.Lock()
_cache = {}


GAPS = {"upload.wikimedia": 0.6, "google": 1.2, "query.wikidata": 1.5, "wikidata": 0.8, "openlibrary": 0.5, "api.nytimes.com": 12.5, "wikimedia.org": 0.3}


def _gap(host):
    return next((g for k, g in GAPS.items() if k in host), 0.3)


def reserve(host, gap=None):
    """Book this request's turn with a site; returns how long to wait for it. Each request takes the next free
    slot one gap after the previous one (queued requests must not add up their waits)."""
    with _call_lock:
        now = _time.time()
        slot = max(now, _last_call.get(host, 0) + (_gap(host) if gap is None else gap))
        _last_call[host] = slot
    return slot - now


def _get(url, timeout=10, accept="application/json"):
    """HTTP GET with a polite per-site pace; when a site says "too many requests", wait as long as it asks and retry."""
    host = urllib.parse.urlparse(url).netloc
    if url in _cache:
        return _cache[url]
    check_down(host)
    for attempt in range(3):
        wait = reserve(host)
        if wait > 0:
            _time.sleep(wait)
        req = urllib.request.Request(url, headers={"User-Agent": _ua_for.get(host, UA), "Accept": accept})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = r.read()
            if len(_cache) > 300:
                _cache.clear()
            _cache[url] = data
            _fails.pop(host, None)
            return data
        except urllib.error.HTTPError as e:
            if e.code in (429, 503) and attempt < 2:
                try:
                    pause = min(20, max(3, int(e.headers.get("Retry-After") or 0)))
                except (TypeError, ValueError):
                    pause = 6
                with _call_lock:
                    _last_call[host] = _time.time() + pause   # everyone waits for this site, not just this request
                continue
            raise
        except (urllib.error.URLError, ConnectionError, TimeoutError) as e:
            # a dropped connection: try once more as an ordinary browser, and remember what worked
            _fails[host] = _fails.get(host, 0) + 1
            if _fails[host] >= 4:
                _down[host] = _time.time() + 1800
                print(f"[inkwell] {host} keeps refusing connections; leaving it alone for 30 minutes")
                raise
            if attempt < 2 and "timed out" not in str(e):
                print(f"[inkwell] {host} dropped the connection ({e}); retrying")
                _ua_for[host] = UA_ALT if _ua_for.get(host, UA) == UA else UA
                _time.sleep(1)
                continue
            raise


def crossref(doi):
    doi = clean_doi(doi)
    data = json.loads(_get("https://api.crossref.org/works/" + urllib.parse.quote(doi, safe="/")))["message"]
    authors = []
    for a in data.get("author", []):
        if a.get("family"):
            authors.append(f"{a.get('given', '')} {a['family']}".strip())
        elif a.get("name"):
            authors.append(a["name"])
    year = ""
    for k in ("published-print", "published-online", "issued", "created"):
        dp = (data.get(k) or {}).get("date-parts")
        if dp and dp[0] and dp[0][0]:
            year = str(dp[0][0])
            break
    typ = data.get("type", "")
    kind = "book" if typ in ("book", "monograph", "edited-book", "reference-book") else "article"
    abstract = re.sub(r"<[^>]+>", " ", data.get("abstract") or "")
    return {
        "kind": kind,
        "title": html.unescape((data.get("title") or [""])[0]),
        "authors": authors,
        "year": year,
        "journal": html.unescape((data.get("container-title") or [""])[0]) if kind == "article" else "",
        "volume": data.get("volume", ""),
        "issue": data.get("issue", ""),
        "pages": data.get("page", ""),
        "publisher": data.get("publisher", ""),
        "doi": doi,
        "isbn": clean_isbn((data.get("ISBN") or [""])[0]),
        "subjects": data.get("subject", []),
        "description": re.sub(r"\s+", " ", abstract).strip(),
    }


def openlibrary(isbn):
    isbn = clean_isbn(isbn)
    raw = json.loads(_get(f"https://openlibrary.org/api/books?bibkeys=ISBN:{isbn}&format=json&jscmd=data"))
    d = raw.get(f"ISBN:{isbn}")
    if not d:
        raise LookupError("ISBN not found on OpenLibrary")
    year = re.search(r"\d{4}", d.get("publish_date", "") or "")
    subjects = [s.get("name") for s in d.get("subjects", [])[:10] if s.get("name")]
    return {
        "kind": "book",
        "title": d.get("title", "") + (": " + d["subtitle"] if d.get("subtitle") else ""),
        "authors": [a.get("name") for a in d.get("authors", []) if a.get("name")],
        "year": year.group(0) if year else "",
        "publisher": ", ".join(p.get("name") for p in d.get("publishers", [])[:1] if p.get("name")),
        "place": ", ".join(p.get("name") for p in d.get("publish_places", [])[:1] if p.get("name")),
        "isbn": isbn,
        "subjects": subjects,
        "cover_url": (d.get("cover") or {}).get("large") or (d.get("cover") or {}).get("medium"),
        "url": d.get("url", ""),
        "description": "",
    }


def from_url(url):
    page = _get(url, accept="text/html").decode("utf-8", "ignore")
    m = DOI_RE.search(page[:200000])
    metas = re.findall(r'<meta\s+[^>]*(?:name|property)=["\']([^"\']+)["\'][^>]*content=["\']([^"\']*)["\']', page, re.I)
    md = {}
    for k, v in metas:
        md.setdefault(k.lower(), []).append(html.unescape(v))
    doi = (md.get("citation_doi") or md.get("dc.identifier") or [""])[0]
    if doi and DOI_RE.search(doi):
        try:
            r = crossref(DOI_RE.search(doi).group(1))
            r["url"] = url
            return r
        except Exception:
            pass
    title = (md.get("citation_title") or md.get("og:title") or [""])[0]
    if not title:
        t = re.search(r"<title>(.*?)</title>", page, re.I | re.S)
        title = html.unescape(t.group(1).strip()) if t else url
    year = re.search(r"\d{4}", (md.get("citation_publication_date") or md.get("citation_date") or md.get("article:published_time") or [""])[0])
    return {
        "kind": "article",
        "title": title,
        "authors": md.get("citation_author") or md.get("author") or [],
        "year": year.group(0) if year else "",
        "journal": (md.get("citation_journal_title") or md.get("og:site_name") or [""])[0],
        "volume": (md.get("citation_volume") or [""])[0],
        "issue": (md.get("citation_issue") or [""])[0],
        "pages": "-".join(x for x in [(md.get("citation_firstpage") or [""])[0], (md.get("citation_lastpage") or [""])[0]] if x),
        "doi": clean_doi(m.group(1)) if (m and not doi) else clean_doi(doi),
        "url": url,
        "description": (md.get("description") or md.get("og:description") or [""])[0],
        "subjects": [],
    }


def lookup(query):
    q = (query or "").strip()
    if re.match(r"^https?://(dx\.)?doi\.org/", q, re.I) or q.lower().startswith("doi:") or re.match(r"^10\.\d{4,9}/", q):
        return crossref(q)
    if clean_isbn(q) and re.fullmatch(r"(isbn[:\s]*)?[\d\-\sXx]{10,17}", q, re.I):
        return openlibrary(clean_isbn(q))
    if re.match(r"^https?://", q):
        return from_url(q)
    raise ValueError("Paste a DOI (10.xxxx/…), an ISBN, or a URL.")


def download(url, timeout=15):
    return _get(url, timeout=timeout, accept="*/*")


# ---------------- open-access copies ----------------
def find_open_access(doi=None, url=None):
    """Return a list of candidate free PDF URLs (arXiv, OpenAlex, or a direct PDF link)."""
    cands = []
    if url and re.search(r"\.pdf($|\?)", url, re.I):
        cands.append(url)
    arx = None
    if doi:
        m = re.search(r"10\.48550/arxiv\.(.+)$", doi, re.I)
        arx = m.group(1) if m else None
    if url and not arx:
        m = re.search(r"arxiv\.org/(?:abs|pdf)/([\w.\-/]+?)(?:v\d+)?(?:\.pdf)?$", url, re.I)
        arx = m.group(1) if m else None
    if arx:
        cands.append(f"https://arxiv.org/pdf/{arx}")
    if doi:
        try:
            w = json.loads(_get("https://api.openalex.org/works/https://doi.org/" + urllib.parse.quote(clean_doi(doi), safe="/")))
            for loc in [w.get("best_oa_location") or {}] + (w.get("locations") or []):
                if loc and loc.get("pdf_url"):
                    cands.append(loc["pdf_url"])
            oa = (w.get("open_access") or {}).get("oa_url")
            if oa:
                cands.append(oa)
        except Exception as e:
            print("[inkwell] OpenAlex lookup failed:", e)
    if url and url not in cands:
        cands.append(url)
    seen, out = set(), []
    for c in cands:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


def download_pdf(candidates, dest_path, max_bytes=300 * 1024 * 1024):
    """Try each URL until one returns a real PDF. Returns the URL used, or None."""
    for u in candidates:
        try:
            req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0 (InkwellLibrary)", "Accept": "application/pdf,*/*"})
            with urllib.request.urlopen(req, timeout=30) as r:
                head = r.read(5)
                if head != b"%PDF-":
                    continue
                with open(dest_path, "wb") as f:
                    f.write(head)
                    total = 5
                    while True:
                        chunk = r.read(1 << 16)
                        if not chunk:
                            break
                        total += len(chunk)
                        if total > max_bytes:
                            raise ValueError("file too large")
                        f.write(chunk)
            return u
        except Exception as e:
            print("[inkwell] download failed:", u, e)
    return None


# ---------------- book catalogue details: synopsis + categories ----------------
def google_books(isbn=None, title=None, author=None):
    """Publisher synopsis and bookstore categories (e.g. 'Fiction / Fantasy / Epic'). No API key needed."""
    if isbn:
        q = "isbn:" + clean_isbn(isbn)
    elif title:
        q = f'intitle:"{title}"' + (f' inauthor:"{author}"' if author else "")
    else:
        raise ValueError("need isbn or title")
    data = json.loads(_get("https://www.googleapis.com/books/v1/volumes?maxResults=3&q=" + urllib.parse.quote(q)))
    items = data.get("items") or []
    if not items:
        raise LookupError("not found on Google Books")
    v = items[0].get("volumeInfo", {})
    desc = re.sub(r"<[^>]+>", " ", v.get("description") or "")
    year = re.search(r"\d{4}", v.get("publishedDate") or "")
    series = ((v.get("seriesInfo") or {}).get("volumeSeries") or [{}])[0] if v.get("seriesInfo") else {}
    return {"description": html.unescape(re.sub(r"\s+", " ", desc)).strip(), "categories": v.get("categories") or [],
            "publisher": v.get("publisher", ""), "year": year.group(0) if year else "",
            "series_index": series.get("orderNumber")}


def openlibrary_description(isbn):
    d = json.loads(_get(f"https://openlibrary.org/isbn/{clean_isbn(isbn)}.json"))
    works = d.get("works") or []
    desc, subjects = "", []
    if works:
        w = json.loads(_get("https://openlibrary.org" + works[0]["key"] + ".json"))
        desc = w.get("description") or ""
        if isinstance(desc, dict):
            desc = desc.get("value", "")
        subjects = w.get("subjects", [])[:15]
    return {"description": re.sub(r"\s+", " ", desc).strip(), "categories": subjects}


def wikipedia_summary(title, must=r"film|television|tv series|miniseries|animated|sitcom|drama|series"):
    """Synopsis-style intro from Wikipedia for a film or TV series (online only)."""
    url = "https://en.wikipedia.org/api/rest_v1/page/summary/" + urllib.parse.quote((title or "").replace(" ", "_"))
    d = json.loads(_get(url))
    if d.get("type") == "disambiguation":
        return None
    if must and not re.search(must, (d.get("description") or "") + " " + (d.get("extract") or "")[:200], re.I):
        return None
    return (d.get("extract") or "").strip() or None



def _norm(t):
    return re.sub(r"[^a-z0-9]+", " ", (t or "").lower()).strip()


def _title_ok(found, want):
    f, w = _norm(found), _norm(want)
    if f == w:
        return True
    return len(w) >= 14 and (f.startswith(w[:40]) or w.startswith(f) and len(f) >= 14)


def find_creators(title, publisher=None, year=None):
    """Authors for a book or graphic novel that has none in its file: OpenLibrary search, then Google Books."""
    t = re.sub(r",?\s*vol\.?\s*\d+$", "", title or "", flags=re.I).strip()
    if not t:
        return []
    try:
        q = "https://openlibrary.org/search.json?limit=5&fields=title,author_name,publisher,first_publish_year&title=" + urllib.parse.quote(t)
        for d in json.loads(_get(q)).get("docs", []):
            if _title_ok(d.get("title"), t) and d.get("author_name"):
                fy = d.get("first_publish_year")
                if year and fy and len(_norm(t)) < 14 and abs(int(str(year)[:4]) - int(fy)) > 2:
                    continue
                if not publisher or any(_norm(publisher) in _norm(p) for p in d.get("publisher", [])) or len(d["author_name"]) < 4:
                    return d["author_name"][:4]
    except Exception as e:
        print("[inkwell] openlibrary search skipped:", e)
    try:
        q = f'intitle:"{t}"' + (f' inpublisher:"{publisher}"' if publisher else "")
        data = json.loads(_get("https://www.googleapis.com/books/v1/volumes?maxResults=5&q=" + urllib.parse.quote(q)))
        for it in data.get("items") or []:
            v = it.get("volumeInfo", {})
            if _title_ok(v.get("title"), t) and v.get("authors"):
                return v["authors"][:4]
    except Exception as e:
        print("[inkwell] google books search skipped:", e)
    return []


def _strip_html(t):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html_unescape(t or ""))).strip()


def html_unescape(t):
    import html
    return html.unescape(t)


_WP_API = "https://en.wikipedia.org/w/api.php?"
_WD_API = "https://www.wikidata.org/w/api.php?"
# Wikidata film genres -> the app's screen genres. Checked in this order: the more particular kinds win, so a kaiju
# film that's also tagged drama and romance lands on Science Fiction.
_SCREEN_RULES = [
    ("Animation", r"animat|anime|cartoon"), ("Documentary", r"documentar"), ("Science Fiction", r"science fiction|sci-fi|kaiju|tokusatsu|space|cyberpunk|dystopi"),
    ("Horror", r"horror|monster|slasher|zombie|vampire"), ("Fantasy", r"fantasy|sword and sorcery"), ("Western", r"western"), ("War", r"\bwar\b"),
    ("Musical", r"musical"), ("Thriller", r"thriller|suspense"), ("Crime", r"crime|gangster|heist|noir"), ("Mystery", r"myster|detective"),
    ("Comedy", r"comedy|comedic|satir|parody"), ("Romance", r"romance|romantic"), ("Action", r"action|martial arts"),
    ("Adventure", r"adventure"), ("Family", r"family|children"), ("Drama", r"drama")]


def screen_genres(labels):
    """Wikidata / Wikipedia genre words -> the app's screen genres, most particular first."""
    text = " | ".join(labels).lower()
    return [g for g, rx in _SCREEN_RULES if re.search(rx, text)]


def _film_title(wtitle):
    return re.sub(r"\s*\((?:\d{4} )?(?:[\w\s-]+ )?(?:film|movie)\)$", "", wtitle or "").strip()


def film_search(query, limit=8):
    """Films on Wikipedia matching a name (typed in by you, or the file's title): title, year, one-line description, poster."""
    query = (query or "").strip()
    if not query:
        return []
    d = json.loads(_get(_WP_API + urllib.parse.urlencode({
        "action": "query", "format": "json", "formatversion": 2, "generator": "search", "gsrsearch": f'{query} hastemplate:"Infobox film"',
        "gsrlimit": limit, "prop": "pageimages|description", "piprop": "thumbnail", "pithumbsize": 240, "pilicense": "any"})))
    out = []
    for p in sorted((d.get("query") or {}).get("pages") or [], key=lambda x: x.get("index", 0)):
        desc = p.get("description") or ""
        y = re.search(r"\b(18|19|20)\d\d\b", desc + " " + p["title"])
        out.append({"wiki": p["title"], "title": _film_title(p["title"]), "year": y.group(0) if y else "", "description": desc,
                    "thumb": (p.get("thumbnail") or {}).get("source", "")})
    return out


def film_details(wtitle):
    """Everything to fill in for one film: title, year, directors, genre, series, runtime, synopsis (its Plot), poster."""
    d = json.loads(_get(_WP_API + urllib.parse.urlencode({
        "action": "query", "format": "json", "formatversion": 2, "titles": wtitle, "redirects": 1,
        "prop": "pageimages|description|pageprops|extracts|info", "piprop": "original", "pilicense": "any", "ppprop": "wikibase_item",
        "explaintext": 1, "exsectionformat": "wiki", "inprop": "url"})))
    pg = ((d.get("query") or {}).get("pages") or [{}])[0]
    if pg.get("missing"):
        raise LookupError("That film isn't on Wikipedia.")
    text = pg.get("extract") or ""
    parts = re.split(r"\n(=+)\s*(.+?)\s*=+\n", "\n" + text)
    intro, secs = parts[0].strip(), {}
    for i in range(1, len(parts) - 2, 3):
        if len(parts[i]) == 2:
            secs[parts[i + 1].strip().lower()] = parts[i + 2].strip()
    plot = next((v for k, v in secs.items() if k.startswith(("plot", "synopsis", "story", "premise")) and v), "")
    out = {"wiki": pg.get("title") or wtitle, "title": _film_title(pg.get("title") or wtitle), "url": pg.get("fullurl") or "",
           "description": pg.get("description") or "", "poster": (pg.get("original") or {}).get("source", ""),
           "summary": _clip_text(plot or intro, 1800), "directors": [], "year": "", "genres": [], "series": None, "minutes": None}
    qid = (pg.get("pageprops") or {}).get("wikibase_item")
    if qid:
        try:
            claims = json.loads(_get(_WD_API + urllib.parse.urlencode({"action": "wbgetentities", "format": "json", "props": "claims", "ids": qid})))["entities"][qid]["claims"]
            ids = lambda p: [c["mainsnak"]["datavalue"]["value"]["id"] for c in claims.get(p, []) if c["mainsnak"].get("datavalue")]
            want = {"directors": ids("P57"), "genres": ids("P136"), "series": ids("P179") or ids("P8345")}
            every = list(dict.fromkeys(sum(want.values(), [])))
            labels = {}
            for i in range(0, len(every), 50):
                ents = json.loads(_get(_WD_API + urllib.parse.urlencode({"action": "wbgetentities", "format": "json", "props": "labels",
                                                                          "languages": "en", "ids": "|".join(every[i:i + 50])})))["entities"]
                labels.update({k: (v.get("labels") or {}).get("en", {}).get("value") for k, v in ents.items()})
            name = lambda x: labels.get(x)
            out["directors"] = [n for n in map(name, want["directors"]) if n][:4]
            out["genres"] = [n for n in map(name, want["genres"]) if n]
            ser = [n for n in map(name, want["series"]) if n]
            out["series"] = re.sub(r"\s+(film series|franchise|media franchise)$", "", ser[0], flags=re.I) if ser else None
            dates = sorted(c["mainsnak"]["datavalue"]["value"]["time"] for c in claims.get("P577", []) if c["mainsnak"].get("datavalue"))
            out["year"] = dates[0][1:5] if dates else ""
            mins = [c["mainsnak"]["datavalue"]["value"]["amount"] for c in claims.get("P2047", []) if c["mainsnak"].get("datavalue")]
            out["minutes"] = int(float(mins[0])) if mins else None
        except Exception as e:
            print("[inkwell] wikidata film details skipped:", e)
    if not out["year"]:
        y = re.search(r"\b(18|19|20)\d\d\b", out["description"])
        out["year"] = y.group(0) if y else ""
    sg = screen_genres(out["genres"] + [out["description"]])
    out["genre"] = sg[0] if sg else None
    out["tags"] = [g for g in sg[1:4]] + (["Kaiju"] if re.search(r"kaiju", " ".join(out["genres"]) + out["description"], re.I) else [])
    return out


def _clip_text(t, n):
    t = (t or "").strip()
    if len(t) <= n:
        return t
    cut = t.rfind(". ", 0, n)
    return t[:cut + 1 if cut > n * 0.5 else n] + " …"


ANILIST = "https://graphql.anilist.co"
_AL_QUERY = """query ($q: String) { Page(perPage: 6) { media(search: $q, type: MANGA, sort: SEARCH_MATCH) {
  id format countryOfOrigin volumes startDate { year } genres isAdult
  tags { name rank isMediaSpoiler isAdult category }
  title { romaji english native } synonyms description(asHtml: false) coverImage { extraLarge }
  staff(perPage: 8, sort: RELEVANCE) { edges { role node { name { full } } } } siteUrl } } }"""
# AniList's genres (alphabetical) -> a shelf genre, most telling first
_AL_GENRES = [("Sci-Fi", "Science Fiction"), ("Mecha", "Science Fiction"), ("Horror", "Horror"), ("Mystery", "Mystery & Crime"),
              ("Thriller", "Thriller & Suspense"), ("Romance", "Romance"), ("Fantasy", "Fantasy"), ("Supernatural", "Fantasy"),
              ("Mahou Shoujo", "Fantasy"), ("Adventure", "Adventure"), ("Action", "Adventure"), ("Comedy", "Humor"),
              ("Psychological", "Literary Fiction"), ("Drama", "Literary Fiction"), ("Slice of Life", "Literary Fiction"),
              ("Sports", "Literary Fiction"), ("Music", "Literary Fiction")]
_AL_TAG_OK = {"Theme-Romance", "Demographic", "Theme-Other", "Setting-Universe", "Theme-Drama", "Theme-Comedy", "Theme-Fantasy",
              "Theme-Sci-Fi", "Theme-Game", "Theme-Action", "Setting-Time", "Setting-Scene"}


def _al_post(query, variables):
    host = "graphql.anilist.co"
    for attempt in range(3):
        wait = reserve(host, 0.8)                     # AniList allows about 90 requests a minute
        if wait > 0:
            _time.sleep(wait)
        req = urllib.request.Request(ANILIST, data=json.dumps({"query": query, "variables": variables}).encode(),
                                     headers={"Content-Type": "application/json", "Accept": "application/json", "User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < 2:
                _time.sleep(min(30, int(e.headers.get("Retry-After") or 10)))
                continue
            raise


def manga_search(query):
    """Manga, manhwa and manhua on AniList matching a series name. Each hit: names, authors, genres, country, synopsis."""
    query = (query or "").strip()
    if not query:
        return []
    key = ("al", query.lower())
    if key in _cache:
        return _cache[key]
    d = _al_post(_AL_QUERY, {"q": query})
    out = []
    for m in ((d.get("data") or {}).get("Page") or {}).get("media") or []:
        t = m.get("title") or {}
        creators = []
        for e in ((m.get("staff") or {}).get("edges") or []):
            role = (e.get("role") or "").lower()
            if re.match(r"(story|art|original (story|creator)|original character design)\b", role) and "(" not in role:
                n = ((e.get("node") or {}).get("name") or {}).get("full")
                if n and n not in creators:
                    creators.append(n)
        genres = m.get("genres") or []
        shelf = next((g2 for g1, g2 in _AL_GENRES if g1 in genres), None)
        tags = [x["name"] for x in m.get("tags") or [] if (x.get("rank") or 0) >= 70 and not x.get("isMediaSpoiler")
                and not x.get("isAdult") and x.get("category") in _AL_TAG_OK]
        desc = re.sub(r"\(Source:[^)]*\)|<[^>]+>", "", m.get("description") or "")
        desc = re.sub(r"\n{3,}", "\n\n", html.unescape(desc)).strip()
        out.append({"id": m.get("id"), "english": t.get("english") or "", "romaji": t.get("romaji") or "", "native": t.get("native") or "",
                    "synonyms": m.get("synonyms") or [], "format": m.get("format"), "country": m.get("countryOfOrigin") or "",
                    "volumes": m.get("volumes"), "year": (m.get("startDate") or {}).get("year"), "genres": genres, "genre": shelf,
                    "tags": tags[:4], "authors": creators[:3], "summary": desc[:2500], "cover": (m.get("coverImage") or {}).get("extraLarge") or "",
                    "url": m.get("siteUrl") or "", "adult": bool(m.get("isAdult"))})
    _cache[key] = out
    return out


def _al_names(hit):
    return [_norm(x) for x in [hit["english"], hit["romaji"], *hit["synonyms"]] if x]


def _name_tokens(names):
    return {w for n in names or [] for w in re.findall(r"[a-z]{3,}", _norm(re.sub(r"\[[^\]]*\]", lambda m: " " + m.group(0)[1:-1] + " ", n)))}


def manga_match(query, authors=None):
    """The one AniList series that a name means: an exact name match (English, romaji or another known title),
    or failing that one whose name starts the same way. None when unsure.
    A match only on a series' alternative titles must also share an author with the ones you have (if any):
    'Beyond the Clouds' by Nicke is not Shinkai's film manga that's also known by that name."""
    q = _norm(query)
    if not q:
        return None
    hits = manga_search(query)
    mine = _name_tokens(authors)
    def ok(h, main_only):
        main = [_norm(x) for x in (h["english"], h["romaji"]) if x]
        if q in main or not mine:
            return True
        return bool(mine & _name_tokens(h["authors"]))
    exact = [h for h in hits if q in _al_names(h) and ok(h, True)]
    if exact:
        return exact[0]
    close = [h for h in hits if any(n.startswith(q) or (q.startswith(n) and len(n) >= 8) for n in _al_names(h)) and ok(h, False)]
    return close[0] if len(close) == 1 or (close and len(q) >= 12) else None


def find_poster(kind, name, year=None):
    """Official poster (and a synopsis) for a show or film. Returns {"url", "summary", "genres"} or None.
    TV: TVmaze. Films: Wikipedia's infobox image, then the iTunes film catalogue. No API keys needed."""
    name = (name or "").strip()
    if not name:
        return None
    if kind == "tv":
        try:
            d = json.loads(_get("https://api.tvmaze.com/singlesearch/shows?q=" + urllib.parse.quote(name)))
            img = (d.get("image") or {}).get("original") or (d.get("image") or {}).get("medium")
            if img and _norm(d.get("name")).replace(" ", "") [:12] == _norm(name).replace(" ", "")[:12]:
                return {"url": img, "summary": _strip_html(d.get("summary")), "genres": d.get("genres") or []}
        except Exception as e:
            print("[inkwell] tvmaze skipped:", e)
        tries = [f"{name} (TV series)", name]
    else:
        tries = ([f"{name} ({year} film)"] if year else []) + [f"{name} (film)", name]
    for t in tries:
        try:
            d = json.loads(_get("https://en.wikipedia.org/api/rest_v1/page/summary/" + urllib.parse.quote(t.replace(" ", "_"))))
            if d.get("type") == "disambiguation":
                continue
            if not re.search(r"film|movie|television|tv series|miniseries|animated|anime|sitcom|series", (d.get("description") or "") + " " + (d.get("extract") or "")[:200], re.I):
                continue
            img = (d.get("originalimage") or {}).get("source") or (d.get("thumbnail") or {}).get("source")
            if img and not img.lower().endswith(".svg"):
                return {"url": img, "summary": (d.get("extract") or "").strip(), "genres": []}
        except Exception:
            continue
    if kind == "movie":
        try:
            d = json.loads(_get("https://itunes.apple.com/search?media=movie&entity=movie&limit=8&term=" + urllib.parse.quote(name)))
            for r in d.get("results") or []:
                if _norm(r.get("trackName")) != _norm(name):
                    continue
                if year and r.get("releaseDate") and abs(int(r["releaseDate"][:4]) - int(str(year)[:4])) > 1:
                    continue
                art = r.get("artworkUrl100") or ""
                if art:
                    return {"url": art.replace("100x100bb", "600x900bb"), "summary": r.get("longDescription") or "",
                            "genres": [r["primaryGenreName"]] if r.get("primaryGenreName") else []}
        except Exception as e:
            print("[inkwell] itunes skipped:", e)
    return None
