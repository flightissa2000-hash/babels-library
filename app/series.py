"""Working out which books belong to a series, and their order.

Sources, best first:
  1. the book file's own metadata (EPUB calibre:series / belongs-to-collection, ComicInfo) - read during import
  2. the title or original file name: "Herbert, Frank - Dune 01 - Dune", "Brandon Sanderson - -Mistborn 01- - The Final
     Empire", "Neuromancer -- Gibson, William -- Sprawl 1", "Bookshops & Bonedust (Legends & Lattes)",
     "Dungeon Crawler Carl Book 2: ...", "The Alloy of Law: A Mistborn Novel"
  3. Wikidata ("part of the series" + "series ordinal"), when looking things up online is on
  4. other books by the same author: "Heretics of Dune" joins Frank Herbert's Dune series
Spellings are then made the same across the library ("Dune Chronicles" and "Dune" become one series).
"""
import json
import os
import re
import threading
import urllib.parse

import store

SERIES_TAIL = r"(?:series|trilogy|chronicles?|saga|cycle|novels?|books|universe|sequence|quartet|quintet|duology|tetralogy|septology)"
SERIES_HINT = r"\b(?:series|trilogy|chronicles|saga|cycle|archive|diaries|files|sequence|quartet|quintet|duology|tetralogy|legacy)\b"
NOT_SERIES = r"edition|novel\b|version|memoir|vol\b|volume|translated|unabridged|abridged|anniversary|illustrated|reprint|annotated|press|publish|isbn|archive’s|anna"
WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
         "eleven": 11, "twelve": 12, "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6}


def key(name):
    """'The Dune Chronicles', 'Dune' and 'Dune series' all give 'dune'."""
    n = (name or "").lower().strip()
    n = re.sub(r"^the\s+", "", n)
    n = re.sub(r"\b" + SERIES_TAIL + r"\b", " ", n)
    n = re.sub(r"\bof\s*$", "", n.strip())
    return re.sub(r"[^a-z0-9]+", "", n)


def author_key(name):
    toks = re.findall(r"[a-z]{2,}", (name or "").lower())
    return " ".join(sorted(toks))


def _surnames(authors):
    out = set()
    for a in authors or []:
        a = a.strip()
        if "," in a:
            out.add(a.split(",")[0].strip().lower())
        elif a:
            out.add(a.split()[-1].lower())
    return {s for s in out if len(s) > 1}


def _idx(s):
    if s is None:
        return None
    s = str(s).strip().lower()
    if s in WORDS:
        return float(WORDS[s])
    try:
        v = float(s)
        return v if 0 < v < 500 else None
    except ValueError:
        return None


def _clean_series(s):
    s = re.sub(r"\s+", " ", (s or "").strip(" -_.,:;#"))
    return s[0].upper() + s[1:] if s else ""


def _looks_author(seg, authors):
    low = seg.lower()
    return any(sn in low for sn in _surnames(authors)) or bool(re.match(r"^[A-Z][\w'.-]+,\s*[A-Z]", seg))


def parse(title, orig_name=None, authors=None):
    """-> (better_title or None, series, index or None). Empty series when nothing was found."""
    t = (title or "").strip()
    authors = authors or []

    # "Herbert, Frank - Dune 01 - Dune" as the title itself
    m = re.match(r"^(.+?)\s+-\s+(.+?)\s+#?(\d{1,3}(?:\.\d)?)\s+-\s+(.+)$", t)
    if m and _looks_author(m.group(1), authors):
        return m.group(4).strip(), _clean_series(m.group(2)), _idx(m.group(3))
    # "Mistborn (Mistborn, #1)", "Title (Series Book 2)", "Title (Series)"
    m = re.match(r"^(.*?\S)\s*\(([^()]+?)\)\s*$", t)
    if m:
        inner = m.group(2).strip()
        mm = re.match(r"^(.+?),?\s*(?:#|book|vol\.?|volume|no\.?)\s*([\d.]+|\w+)$", inner, re.I)
        if mm and _idx(mm.group(2)):
            return m.group(1), _clean_series(mm.group(1)), _idx(mm.group(2))
        if (len(inner.split()) <= 5 and not re.search(NOT_SERIES, inner, re.I) and not re.search(r"\d{4}", inner)
                and not _looks_author(inner, authors) and inner.lower() not in ("a novel", "novel", "the novel")):
            return m.group(1), _clean_series(inner), None
    # "Dungeon Crawler Carl Book 2: Carl's Doomsday Scenario"
    m = re.match(r"^(.+?)\s+(?:book|vol\.?|volume|#|no\.?)\s*(\d{1,3}|\w+)\s*[:\-–—]\s*(.+)$", t, re.I)
    if m and _idx(m.group(2)):
        return m.group(3).strip(), _clean_series(m.group(1)), _idx(m.group(2))
    # "The Alloy of Law: A Mistborn Novel", "Shadows of Self: A Mistborn Novel"
    m = re.match(r"^(.+?)\s*[:\-–—]\s*an?\s+(.+?)\s+(?:novel|novella|book|adventure|mystery|story)$", t, re.I)
    if m and len(m.group(2).split()) <= 4 and not re.search(r"\bof\b", m.group(2), re.I):
        return m.group(1).strip(), _clean_series(m.group(2)), None
    # "The Way of Kings: The Stormlight Archive", "Title: Book Two of the X Trilogy"
    import extract
    t2, ser, idx = extract.series_from_title(t)
    if ser:
        return t2, _clean_series(ser), idx

    # the original file name, split into its " - " / " -- " parts
    base = os.path.splitext(orig_name or "")[0]
    if base:
        segs = [s.strip(" -_") for s in re.split(r"\s+-{1,2}\s+", base)]
        segs = [s for s in segs if s]
        for s in segs[1:]:
            if re.search(r"\b(?:19|20)\d\d\b", s) or re.search(NOT_SERIES, s, re.I) or re.fullmatch(r"[0-9a-f]{20,}", s):
                continue
            mm = re.match(r"^(.*?[A-Za-z].*?)\s*(?:#|book|vol\.?|no\.?)?\s*(\d{1,3}(?:\.\d)?)$", s, re.I)
            if mm and not _looks_author(mm.group(1), authors):
                rest = [x for x in segs if x != s and not _looks_author(x, authors)]
                new_t = rest[-1] if rest and _norm(t) in (_norm(base), "") else None  # the title was just the file name
                return new_t, _clean_series(mm.group(1)), _idx(mm.group(2))
            if re.search(SERIES_HINT, s, re.I) and not _looks_author(s, authors) and _norm(s) != _norm(t):
                return None, _clean_series(s), None
    return None, "", None


def _norm(s):
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


# ---------------------------------------------------------------- Wikidata
WD = "https://www.wikidata.org/w/api.php?format=json&"


def _wd(params):
    import lookup
    return json.loads(lookup._get(WD + urllib.parse.urlencode(params), timeout=12))


def wikidata(title, authors=None):
    """-> (series name, index or None) or None."""
    import lookup
    t = re.sub(r"\s*[:(].*$", "", title or "").strip() or title
    if not t:
        return None
    hits = _wd({"action": "wbsearchentities", "search": t, "language": "en", "type": "item", "limit": 8}).get("search") or []
    sn = _surnames(authors)
    def score(h):
        d = (h.get("description") or "").lower()
        s = 0
        if re.search(r"novel|book|novella|fiction|short story|comic", d):
            s += 2
        if any(x in d for x in sn):
            s += 3
        if lookup._norm(h.get("label")) == lookup._norm(t) or lookup._norm(h.get("label")) == lookup._norm(title):
            s += 2
        if re.search(r"film|television|episode|album|song|video game|character|human|family name|disambiguation", d):
            s -= 6
        return s
    hits = [h for h in hits if score(h) >= 3 and (not sn or any(x in (h.get("description") or "").lower() for x in sn))]
    hits.sort(key=score, reverse=True)
    if not hits:
        return None
    ents = _wd({"action": "wbgetentities", "ids": "|".join(h["id"] for h in hits[:4]), "props": "claims"}).get("entities") or {}
    for h in hits[:4]:
        claims = (ents.get(h["id"]) or {}).get("claims") or {}
        for c in claims.get("P179") or []:
            sid = (((c.get("mainsnak") or {}).get("datavalue") or {}).get("value") or {}).get("id")
            if not sid:
                continue
            ordv = None
            for q in (c.get("qualifiers") or {}).get("P1545") or []:
                ordv = _idx(((q.get("datavalue") or {}).get("value")))
            if ordv is None:
                for c2 in claims.get("P1545") or []:
                    ordv = _idx(((c2.get("mainsnak") or {}).get("datavalue") or {}).get("value"))
            lab = _wd({"action": "wbgetentities", "ids": sid, "props": "labels", "languages": "en"})
            name = ((((lab.get("entities") or {}).get(sid) or {}).get("labels") or {}).get("en") or {}).get("value")
            if name:
                name = re.sub(r"\s*\((?:novel |book )?series\)$", "", name, flags=re.I)
                name = re.sub(r"\s+(?:novel |book )?series$", "", name, flags=re.I)
                return _clean_series(name), ordv
    return None


# ---------------------------------------------------------------- applying it
_lock = threading.Lock()


def _set(item_id, item, upd):
    locked = set(item.get("locked") or [])
    upd = {k: v for k, v in upd.items() if k not in locked and v not in (None, "")}
    if upd:
        store.update_item(item_id, upd)
        item.update(upd)


def resolve(item, online=True):
    """Fill in series / number for one book (dict from store.list_items). Doesn't overwrite what's already known."""
    if item.get("kind") not in ("book", "graphic") or "series" in (item.get("locked") or []):
        return
    upd = {}
    if item.get("series") and re.search(r" -- |[0-9a-f]{20,}|anna.s archive|z-library", item["series"], re.I):
        store.update_item(item["id"], {"series": None, "series_index": None})   # junk from a file name
        item["series"], item["series_index"] = None, None
    new_t, ser, idx = parse(item.get("title"), item.get("orig_name"), item.get("authors"))
    if ser and idx is None and item.get("orig_name"):
        _, ser2, idx2 = parse("", item.get("orig_name"), item.get("authors"))   # the number is often only in the file name
        if ser2 and key(ser2) == key(ser):
            idx = idx2
    if ser and (not item.get("series") or key(ser) == key(item["series"])):
        if not item.get("series"):
            upd["series"] = ser
        if new_t and len(new_t) > 1 and new_t != item.get("title"):
            upd["title"] = new_t
        if idx is not None and item.get("series_index") is None:
            upd["series_index"] = idx
    _set(item["id"], item, upd)
    if online and item.get("kind") == "book" and (not item.get("series") or item.get("series_index") is None) \
            and store.get_settings().get("auto_lookup") and not item.get("_wd_tried"):
        try:
            r = wikidata(item.get("title"), item.get("authors"))
        except Exception as e:
            print("[inkwell] wikidata series lookup skipped:", e)
            r = None
        if r:
            ser, idx = r
            if not item.get("series"):
                _set(item["id"], item, {"series": ser, "series_index": idx})
            elif idx is not None and item.get("series_index") is None and (key(ser) == key(item["series"]) or key(item["series"]) in key(ser)):
                _set(item["id"], item, {"series_index": idx})


def tidy(items=None):
    """Same-author inference and one spelling per series, across the whole library."""
    with _lock:
        items = items if items is not None else store.list_items()
        books = [i for i in items if i.get("kind") in ("book", "graphic")]
        # 1. books by an author whose title names one of that author's series: "Heretics of Dune"
        by_author = {}
        for b in books:
            if b.get("series"):
                for a in b.get("authors") or []:
                    by_author.setdefault(author_key(a), set()).add(b["series"])
        for b in books:
            if b.get("series") or "series" in (b.get("locked") or []):
                continue
            for a in b.get("authors") or []:
                for ser in by_author.get(author_key(a), ()):
                    k = key(ser)
                    words = _norm(b.get("title")).split()
                    if k and len(k) >= 3 and any(re.sub(r"[^a-z0-9]", "", w) == k for w in words) or \
                            (k and len(k) >= 6 and k in re.sub(r"[^a-z0-9]", "", _norm(b.get("title")))):
                        _set(b["id"], b, {"series": ser})
                        break
                if b.get("series"):
                    break
        # 2. one spelling per series: the most used, then the shortest
        groups = {}
        for b in books:
            if b.get("series"):
                groups.setdefault(key(b["series"]), []).append(b)
        for k, members in groups.items():
            if not k:
                continue
            counts = {}
            for b in members:
                counts[b["series"]] = counts.get(b["series"], 0) + 1
            best = sorted(counts, key=lambda s: (-counts[s], len(s), s))[0]
            for b in members:
                if b["series"] != best and "series" not in (b.get("locked") or []):
                    _set(b["id"], b, {"series": best})


def backfill(online=True, log=None):
    """Go through every book once (run in the background)."""
    items = store.list_items()
    for it in items:
        if it.get("kind") in ("book", "graphic"):
            try:
                resolve(it, online=online)
            except Exception as e:
                print("[inkwell] series:", it.get("title"), e)
    tidy()
    n = sum(1 for i in store.list_items() if i.get("series") and i.get("kind") in ("book", "graphic"))
    if log:
        log(f"Series checked: {n} books are in a series.", "import")
