"""E-readers running Babel (the EEGO A4): the library as an OPDS catalogue, and reading places kept in step through the
KOReader sync protocol. Both live on the phone-sync server (port 8766), so they're reachable on the Wi-Fi.

  /opds/...                         the catalogue: shelves, series, search, books (EPUB; a PDF as its reading copy), covers
  /kosync/users/auth                KOReader sync: is this e-reader paired?
  /kosync/syncs/progress[/<doc>]    KOReader sync: read / write the place in a book

An e-reader is paired like a phone (it's in the same device list, so it can be removed the same way); it signs in with
the user name "babel" and its token as the password: OPDS sends them as Basic auth, KOReader sync as x-auth-user and
x-auth-key (the MD5 of the password, which is how the KOReader protocol works).

Places: the e-reader says where it is as a KOReader XPath (/body/DocFragment[3]/body/div[2]/p[4]/text()[1].17), Babel
keeps an EPUB CFI (epubcfi(/6/6!/4/4/8/1:17)). Both point at a spot in the same file's text, so each is turned into the
other through copyanchor.Book (spine page + offset in that page's text).
"""
import base64
import hashlib
import hmac
import io
import json
import os
import re
import secrets
import threading
import time
import urllib.parse
from xml.sax.saxutils import escape

import store

USER = "babel"
PAGE = 50                   # (the e-reader holds at most 62 entries per feed page)
_lock = threading.Lock()
_books = {}                 # (path, mtime) -> copyanchor.Book, a few kept
HASHES = os.path.join(store.DATA_DIR, "ereader_hashes.json")
THUMBS = os.path.join(store.DATA_DIR, "ereader_covers")


# ---------------------------------------------------------------- pairing
def pair(name="E-reader", profile=None):
    """A new e-reader: its record in the device list, and the password it signs in with (shown once)."""
    import phonesync
    tok = secrets.token_urlsafe(18)
    dev = {"id": "ereader-" + secrets.token_hex(6), "name": str(name)[:60], "kind": "ereader",
           "token_hash": phonesync._hash(tok), "ko_key": hashlib.md5(tok.encode()).hexdigest(),
           "paired_at": time.time(), "last_seen": time.time(), "queue": []}
    if profile:
        dev["profile"] = int(profile)
    phonesync._save_devices(phonesync.devices() + [dev])
    return dev, tok


def _device(h):
    """The paired e-reader making this request, from Basic auth (OPDS) or x-auth-user / x-auth-key (KOReader sync)."""
    import phonesync
    key = (h.headers.get("x-auth-key") or "").strip().lower()
    if key:
        if (h.headers.get("x-auth-user") or "").strip() != USER:
            return None
        return next((d for d in phonesync.devices() if d.get("ko_key") and hmac.compare_digest(d["ko_key"], key)), None)
    auth = h.headers.get("Authorization") or ""
    if auth.startswith("Basic "):
        try:
            user, _, pw = base64.b64decode(auth[6:]).decode("utf-8", "replace").partition(":")
        except Exception:
            return None
        dev = phonesync.device_for(pw) if user == USER else None
        return dev if dev and dev.get("kind") == "ereader" else None
    return None


# ---------------------------------------------------------------- which books an e-reader gets
def _original_id(it):
    src = it.get("source") or ""
    return int(src.split(":", 1)[1]) if src.startswith("reading-copy:") and src.split(":", 1)[1].isdigit() else None


def books():
    """Books an e-reader can open: EPUBs, and each PDF through its reading copy (the PDF itself is left out)."""
    out = []
    for it in store.list_items():
        if it.get("kind") not in ("book", "article", "graphic") or not it.get("has_file") or (it.get("file_type") or "").lower() != "epub":
            continue
        if not store.visible(it):
            continue
        shown, cover = _shown(it)
        shown["_cover"] = cover
        out.append(shown)
    return out


def _journal():
    """status by item id (an EPUB's own row, or for a reading copy its PDF's row)."""
    import journal
    st = {}
    try:
        for r in journal.list_log():
            if r.get("item_id"):
                st[int(r["item_id"])] = r.get("status") or ""
    except Exception:
        pass
    return st


def _status(it, st):
    return st.get(it["id"]) or st.get(_original_id(it) or -1) or ""


# ---------------------------------------------------------------- KOReader document ids
def ko_hash(path):
    """KOReader's partial MD5: 1 KiB at offsets 0, 1 KiB, 4 KiB, 16 KiB ... 1 GiB (as the e-reader computes it)."""
    md5 = hashlib.md5()
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        for i in range(-1, 11):
            off = 0 if i < 0 else 1024 << (2 * i)
            if off >= size:
                continue
            f.seek(off)
            md5.update(f.read(min(1024, size - off)))
    return md5.hexdigest()


def _hash_index():
    """KOReader id -> item id for every book an e-reader can have (kept on disk; a file is hashed again if it changes)."""
    with _lock:
        try:
            cache = json.load(open(HASHES, encoding="utf-8"))
        except (OSError, ValueError):
            cache = {}
        changed = False
        out = {}
        for it in books():
            raw = store.get_item(it["id"], raw=True)
            try:
                path = store.resolve_file(raw["file_path"])
                st = os.stat(path)
            except (OSError, TypeError, KeyError):
                continue
            c = cache.get(str(it["id"]))
            if not c or c.get("size") != st.st_size or abs(c.get("mtime", 0) - st.st_mtime) > 1:
                try:
                    c = {"size": st.st_size, "mtime": st.st_mtime, "ko": ko_hash(path)}
                except OSError:
                    continue
                cache[str(it["id"])] = c
                changed = True
            out[c["ko"]] = it["id"]
        if changed:
            tmp = HASHES + ".part"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(cache, f)
            os.replace(tmp, HASHES)
        return out


def find_doc(doc, meta=None):
    """The item an e-reader's document id stands for; by title and author when the file isn't byte-for-byte ours."""
    iid = _hash_index().get((doc or "").lower())
    if iid:
        return iid
    if meta and meta.get("title"):
        import journal
        t = journal.norm(meta["title"])
        a = journal.norm((meta.get("authors") or "").split(",")[0].split("&")[0])
        for it in books():
            if journal.norm(it.get("title") or "") == t:
                if not a or not it.get("authors") or a.split()[-1:] == journal.norm(it["authors"][0]).split()[-1:]:
                    return it["id"]
    return None


# ---------------------------------------------------------------- places: KOReader XPath <-> EPUB CFI
def _book(item_id):
    import copyanchor
    raw = store.get_item(item_id, raw=True)
    path = store.resolve_file(raw["file_path"])
    key = (path, os.path.getmtime(path))
    with _lock:
        b = _books.get(key)
        if b is None:
            b = copyanchor.Book(path)
            if len(_books) > 4:
                _books.pop(next(iter(_books)))
            _books[key] = b
        return b


def _local(tag):
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def xpath_to_spot(book, xp):
    """(page index, offset in its text) for a KOReader XPath, or None."""
    m = re.match(r"^/body/DocFragment\[(\d+)\](.*)$", (xp or "").strip())
    if not m:
        return None
    pi = int(m.group(1)) - 1
    if not (0 <= pi < len(book.pages)):
        return None
    page = book.pages[pi]
    if page["body"] is None:
        return pi, 0
    segs = [s for s in m.group(2).split("/") if s]
    if segs and re.match(r"^body(\[1\])?$", segs[0]):
        segs = segs[1:]
    el = page["body"]
    start = lambda e: page["at"].get(id(e), 0)
    for s in segs:
        t = re.match(r"^text\(\)(?:\[(\d+)\])?(?:\.(\d+))?$", s)
        if t:
            own = [n for n in page["nodes"] if n[0] is el]
            k = int(t.group(1) or 1) - 1
            if 0 <= k < len(own):
                return pi, own[k][2] + min(int(t.group(2) or 0), len(own[k][3]))
            return pi, start(el)
        e = re.match(r"^([\w:.-]+?)(?:\[(\d+)\])?(?:\.(\d+))?$", s)
        if not e:
            return pi, start(el)
        kids = [c for c in el if _local(c.tag) == e.group(1).split(":")[-1]]
        k = int(e.group(2) or 1) - 1
        if not (0 <= k < len(kids)):
            return pi, start(el)
        el = kids[k]
        if e.group(3):                       # an offset on the element itself
            return pi, start(el) + int(e.group(3))
    return pi, start(el)


def spot_to_xpath(book, pi, off):
    """A KOReader XPath for (page index, offset): the text node holding that spot (skipping blank runs)."""
    page = book.pages[pi]
    head = f"/body/DocFragment[{pi + 1}]/body"
    nodes = page["nodes"]
    if page["body"] is None or not nodes:
        return head
    k = next((i for i, n in enumerate(nodes) if n[2] <= off < n[2] + len(n[3])), len(nodes) - 1)
    while k < len(nodes) - 1 and not nodes[k][3].strip():
        k += 1
    el, _slot, at, text = nodes[k]
    parents = {c: p for p in page["body"].iter() for c in p}
    path = []
    x = el
    while x is not page["body"]:
        p = parents[x]
        same = [c for c in p if _local(c.tag) == _local(x.tag)]
        path.append(f"/{_local(x.tag)}[{same.index(x) + 1}]")
        x = p
    own = [n for n in nodes if n[0] is el]
    t = next(i for i, n in enumerate(own) if n is nodes[k])
    o = max(0, min(off - at, len(text))) if nodes[k][2] <= off else 0
    return head + "".join(reversed(path)) + f"/text()[{t + 1}].{o}"


def cfi_to_xpath(item_id, cfi):
    b = _book(item_id)
    loc = b.locate(cfi)
    return (spot_to_xpath(b, *loc), loc[0]) if loc else (None, None)


def xpath_to_cfi(item_id, xp):
    b = _book(item_id)
    loc = xpath_to_spot(b, xp)
    return b.cfi_at(*loc) if loc else None


# ---------------------------------------------------------------- KOReader sync
def _clock(iid, *fields):
    c = store.item_clocks({iid}).get(iid, {})
    return max([c.get(f) or 0 for f in fields] or [0])


def _seen(dev, iid):
    """This e-reader has Babel's place for the book as of now."""
    import phonesync
    fresh = next((d for d in phonesync.devices() if d.get("id") == dev.get("id")), dev)
    seen = dict(fresh.get("ko_seen") or {})
    seen[str(iid)] = time.time() + 1
    phonesync._touch(dev, ko_seen=seen)
    dev["ko_seen"] = seen


def get_progress(dev, doc):
    iid = find_doc(doc)
    if not iid:
        return 404, {"message": "Unknown document"}
    _seen(dev, iid)
    it = store.get_item(iid)
    pct = float(it.get("progress") or 0)
    cfi = it.get("last_location") or ""
    if not cfi and pct <= 0:
        return 404, {"message": "No progress yet"}
    xp, spine = (None, None)
    if cfi:
        try:
            xp, spine = cfi_to_xpath(iid, cfi)
        except Exception as e:
            print(f"[inkwell] e-reader: couldn't turn {cfi} into a KOReader place: {e}")
    ts = int(_clock(iid, "last_location", "progress") or it.get("opened_at") or it.get("updated_at") or 0)
    out = {"document": doc, "progress": xp or "", "percentage": round(pct, 6), "device": "Babel's Library",
           "device_id": "babel-" + str(store.viewer()), "timestamp": ts}
    if xp and len(xp) <= 120:
        out["position"] = {"pctQ": int(pct * 1_000_000), "spine": spine, "page": 0, "pages": 1, "xpath": xp}
    return 200, out


def put_progress(dev, b):
    import journal
    import phonesync
    doc = str(b.get("document") or "")
    iid = find_doc(doc, b.get("metadata"))
    if not iid:
        return 404, {"message": "This book isn't in Babel's Library"}
    pct = max(0.0, min(1.0, float(b.get("percentage") or 0)))
    xp = str(b.get("progress") or "") or str((b.get("position") or {}).get("xpath") or "")
    now = time.time()
    # Behind Babel's place, and Babel's place moved since this e-reader last saw it (read further on the phone or the
    # computer meanwhile): it hasn't caught up yet, so keep ours. Behind with nothing new here: went back on purpose.
    it = store.get_item(iid)
    ours = float(it.get("progress") or 0)
    seen = float((dev.get("ko_seen") or {}).get(str(iid)) or 0)
    if pct + 0.0005 < ours and _clock(iid, "last_location", "progress") > seen:
        print(f"[inkwell] e-reader {dev.get('name')}: kept Babel's place in “{it.get('title')}” ({ours:.1%} over {pct:.1%})")
        _seen(dev, iid)
        return 200, {"document": doc, "timestamp": int(now)}
    ops = [{"id": iid, "field": "progress", "value": pct, "ts": now}, {"id": iid, "field": "opened_at", "value": now, "ts": now}]
    cfi = None
    if xp:
        try:
            cfi = xpath_to_cfi(iid, xp)
        except Exception as e:
            print(f"[inkwell] e-reader: couldn't turn {xp} into a CFI: {e}")
    if cfi:
        ops.append({"id": iid, "field": "last_location", "value": cfi, "ts": now})
    phonesync.push(dev, ops, now)
    # the journal: started reading it, or got to the end
    try:
        it = store.get_item(iid)
        jit = store.get_item(_original_id(it) or iid) or it
        if jit.get("kind") != "book":
            raise LookupError("papers don't go in the reading journal")
        lid = journal.ensure_log_for_item(jit)
        row = journal.get_log(lid) or {}
        status = row.get("status") or ""
        if pct >= 0.995 and status != "finished":
            journal.update_log(lid, {"status": "finished", "finished": time.strftime("%Y-%m-%d")})
        elif pct > 0 and status in ("", "next", "hold"):
            journal.update_log(lid, {"status": "reading"})
    except LookupError:
        pass
    except Exception as e:
        print(f"[inkwell] e-reader: journal not updated: {e}")
    _seen(dev, iid)
    return 200, {"document": doc, "timestamp": int(now)}


def mark_finished(dev, iid):
    """The e-reader's "Mark finished": what the computer's own button does (journal status Finished with today's
    date, progress 100%); a reading copy's PDF is marked too. Returns the title shown."""
    import journal
    import phonesync
    it = store.get_item(iid)
    oid = _original_id(it)
    orig = store.get_item(oid) if oid else None
    target = orig or it
    lid = journal.ensure_log_for_item(target)
    journal.update_log(lid, {"status": "finished", "finished": time.strftime("%Y-%m-%d")})
    now = time.time()
    ops = [{"id": x["id"], "field": "progress", "value": 1.0, "ts": now} for x in (it, orig) if x]
    phonesync.push(dev, ops, now)
    _seen(dev, iid)
    print(f"[inkwell] e-reader {dev.get('name')}: marked “{target.get('title')}” finished")
    return re.sub(r"\s*\(reading copy\)\s*$", "", target.get("title") or "", flags=re.I)


# ---------------------------------------------------------------- OPDS
NAV ="application/atom+xml;profile=opds-catalog;kind=navigation"
ACQ = "application/atom+xml;profile=opds-catalog;kind=acquisition"


def _iso(t):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t or 0))


_BAD_XML = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f￾￿\ud800-\udfff]")


def _feed(fid, title, entries, kind, links=""):
    # (text pulled from PDFs can carry control characters XML doesn't allow: the e-reader's parser stops there)
    return _BAD_XML.sub("", '<?xml version="1.0" encoding="utf-8"?>\n'
            '<feed xmlns="http://www.w3.org/2005/Atom" xmlns:opds="http://opds-spec.org/2010/catalog" '
            'xmlns:dc="http://purl.org/dc/terms/">'
            f'<id>urn:babel:{escape(fid)}</id><title>{escape(title)}</title><updated>{_iso(time.time())}</updated>'
            '<author><name>Babel\'s Library</name></author>'
            f'<link rel="start" href="/opds" type="{NAV}"/>'
            '<link rel="search" href="/opds/search?q={searchTerms}" type="application/atom+xml"/>'
            f'{links}{"".join(entries)}</feed>').encode("utf-8", "replace")


def _nav(eid, title, href, about="", count=None):
    n = f' thr:count="{count}" xmlns:thr="http://purl.org/syndication/thread/1.0"' if count is not None else ""
    return (f'<entry><title>{escape(title)}</title><id>urn:babel:{escape(eid)}</id><updated>{_iso(time.time())}</updated>'
            f'<content type="text">{escape(about)}</content>'
            f'<link rel="subsection" href="{escape(href)}" type="{ACQ}"{n}/></entry>')


def _safe(name):
    s = re.sub(r"[^\w\- .,'()]+", "", name or "book").strip()[:60] or "book"
    return urllib.parse.quote(s)


def _shown(it):
    """What an e-reader shows for a book: a reading copy goes by its PDF's title, authors and series (being a copy is
    an internal thing), and its cover when it has none of its own."""
    oid = _original_id(it)
    o = store.get_item(oid) if oid else None
    if not o:
        return it, it["id"] if it.get("has_cover") else None
    shown = dict(it)
    for k in ("title", "authors", "series", "series_index", "summary"):
        if o.get(k):
            shown[k] = o[k]
    shown["title"] = re.sub(r"\s*\(reading copy\)\s*$", "", shown.get("title") or "", flags=re.I)
    return shown, it["id"] if it.get("has_cover") else (oid if o.get("has_cover") else None)


def _book_entry(it, st):
    cover_id = it.get("_cover")
    authors = it.get("authors") or []
    title = it.get("title") or "Untitled"
    if it.get("series"):
        idx = it.get("series_index")
        sub = f"{it['series']} #{idx:g}" if isinstance(idx, (int, float)) and idx else it["series"]
    else:
        sub = ""
    status = _status(it, st)
    words = {"reading": "Reading", "next": "Up next", "finished": "Finished", "hold": "On hold", "dropped": "Dropped"}.get(status, "")
    pct = float(it.get("progress") or 0)
    about = " · ".join(x for x in (sub, words, f"{pct:.0%} read" if 0 < pct < 1 else "", (it.get("summary") or "")[:400]) if x)
    out = [f'<entry><title>{escape(title)}</title><id>urn:babel:item:{it["id"]}</id><updated>{_iso(it.get("updated_at"))}</updated>']
    out += [f"<author><name>{escape(a)}</name></author>" for a in authors[:3]]
    if it.get("series"):
        out.append(f'<category term="{escape(it["series"])}" label="{escape(sub)}"/>')
    out.append(f'<summary type="text">{escape(about)}</summary>')
    if cover_id:
        out.append(f'<link rel="http://opds-spec.org/image" href="/opds/cover/{cover_id}.jpg" type="image/jpeg"/>')
        out.append(f'<link rel="http://opds-spec.org/image/thumbnail" href="/opds/cover/{cover_id}.jpg?thumb=1" type="image/jpeg"/>')
    name = _safe(f"{title} - {authors[0]}" if authors else title)
    out.append(f'<link rel="http://opds-spec.org/acquisition" href="/opds/book/{it["id"]}/{name}.epub" type="application/epub+zip"/>')
    out.append("</entry>")
    return "".join(out)


def _paged(path, query, items, fid, title, st, sort=None):
    page = max(0, int(query.get("page") or 0))
    chunk = items[page * PAGE:(page + 1) * PAGE]
    links = ""
    entries = [_book_entry(it, st) for it in chunk]
    if sort and page == 0 and len(items) > 5:
        # first row of a shelf: how it is ordered, and the way to change that
        q = {"shelf": fid, **({"have": query["have"]} if query.get("have") else {})}
        entries.insert(0, _nav(f"{fid}:sort", f"Order: {SORTS[sort]}", "/opds/sort?" + urllib.parse.urlencode(q),
                               "Tap to change the order"))
    if (page + 1) * PAGE < len(items):
        q = dict(query, page=str(page + 1))
        nxt = path + "?" + urllib.parse.urlencode(q)
        links = f'<link rel="next" href="{escape(nxt)}" type="{ACQ}"/>'
        # a row at the end of the list too: easier to find than the page buttons
        pages = -(-len(items) // PAGE)
        entries.append(_nav(f"{fid}:more:{page + 1}", f"More {title.lower()} (page {page + 2} of {pages})", nxt,
                            f"{len(items) - (page + 1) * PAGE} more"))
    return _feed(f"{fid}:{page}", title, entries, ACQ, links)


def _name_key(s):
    """A title as it is filed: lower case, without a leading The / A / An."""
    return re.sub(r"^(the|an|a)\s+", "", (s or "").strip().lower())


def _sort_title(it):
    return (_name_key(it.get("series") or it.get("title")), float(it.get("series_index") or 0), _name_key(it.get("title")))


# the orders a shelf can be shown in (the e-reader remembers the one picked for each shelf)
SORTS = {"smart": "reading first", "title": "title, A to Z", "author": "author, A to Z", "new": "newest first"}
SHELVES = {"books": "Books", "papers": "Papers", "next": "Up next", "downloaded": "Downloaded"}


def _ordered(items, sort, st):
    if sort == "author":
        def last_name(it):
            a = ((it.get("authors") or [""])[0] or "").strip()
            # "Surname, Given" is filed as it stands; "Given Surname" by its last word; no author goes last
            return (not a, (a.split(",")[0] if "," in a else a.split()[-1] if a else "").lower(), a.lower())
        return sorted(items, key=lambda it: last_name(it) + _sort_title(it))
    if sort == "new":
        return sorted(items, key=lambda it: -(it.get("added_at") or 0))
    if sort == "smart":
        # what you're in the middle of (latest opened first), then Up next, then unread, on hold, and finished last
        def rank(it):
            s, pct = _status(it, st), float(it.get("progress") or 0)
            if s in ("finished", "dropped") or pct >= 1:
                return 4
            if s == "hold":
                return 3
            if s == "reading" or pct > 0:
                return 0
            return 1 if s == "next" else 2
        return sorted(items, key=lambda it: (rank(it), -(it.get("opened_at") or 0) if rank(it) == 0 else 0) + _sort_title(it))
    return sorted(items, key=_sort_title)


def _shelf_sort(dev, shelf, query):
    """The order for this shelf: the one just picked (kept for next time), else the one kept, else reading first."""
    kept = dict(dev.get("sort") or {})
    picked = query.get("sort")
    if picked in SORTS and kept.get(shelf) != picked:
        kept[shelf] = picked
        dev["sort"] = kept
        import phonesync
        phonesync._touch(dev, sort=kept)
    sort = picked if picked in SORTS else kept.get(shelf)
    return sort if sort in SORTS else "smart"


def opds(dev, path, query):
    bs = books()
    st = _journal()
    if path == "/opds/sort":
        shelf = query.get("shelf") if query.get("shelf") in SHELVES else "books"
        now = _shelf_sort(dev, shelf, {})
        have = {"have": query["have"]} if query.get("have") else {}
        entries = [_nav(f"sort:{shelf}:{k}", label[0].upper() + label[1:] + (" (now)" if k == now else ""),
                        f"/opds/{shelf}?" + urllib.parse.urlencode({"sort": k, **have}))
                   for k, label in SORTS.items()]
        return _feed(f"sort:{shelf}", f"Order of {SHELVES[shelf]}", entries, NAV)
    if path in ("/opds", "/opds/"):
        # what the user asked for on the e-reader: Books, Papers, Up next, Downloaded
        books_ = [it for it in bs if it.get("kind") in ("book", "graphic")]
        papers = [it for it in bs if it.get("kind") == "article"]
        nxt = [it for it in bs if _status(it, st) == "next"]
        entries = [_nav("books", "Books", "/opds/books", "Every book", len(books_)),
                   _nav("papers", "Papers", "/opds/papers", "Every paper", len(papers)),
                   _nav("next", "Up next", "/opds/next", "Marked Up next in your journal", len(nxt)),
                   _nav("downloaded", "Downloaded", "/opds/downloaded", "Books on this e-reader")]
        return _feed("root", "Babel's Library", entries, NAV)
    if path == "/opds/books":
        sort = _shelf_sort(dev, "books", query)
        return _paged(path, query, _ordered([it for it in bs if it.get("kind") in ("book", "graphic")], sort, st), "books", "Books", st, sort)
    if path == "/opds/papers":
        sort = _shelf_sort(dev, "papers", query)
        return _paged(path, query, _ordered([it for it in bs if it.get("kind") == "article"], sort, st), "papers", "Papers", st, sort)
    if path == "/opds/downloaded":
        have = [int(x) for x in re.findall(r"\d+", query.get("have") or "")]
        items = [it for it in bs if it["id"] in set(have)]
        sort = _shelf_sort(dev, "downloaded", query)
        return _paged(path, query, _ordered(items, sort, st), "downloaded", "Downloaded", st, sort)
    if path == "/opds/old-root":
        reading = [it for it in bs if _status(it, st) == "reading" or 0 < float(it.get("progress") or 0) < 1]
        nxt = [it for it in bs if _status(it, st) == "next"]
        sent = [it for it in bs if it["id"] in set(dev.get("queue") or [])]
        series = {it["series"] for it in bs if it.get("series")}
        entries = [_nav("reading", "Continue reading", "/opds/reading", "Books you're in the middle of", len(reading)),
                   _nav("next", "Up next", "/opds/next", "Marked Up next in your journal", len(nxt))]
        if sent:
            entries.append(_nav("sent", "Sent from the computer", "/opds/sent", "Books you sent to this e-reader", len(sent)))
        entries += [_nav("recent", "Recently added", "/opds/recent", "Newest books in the library"),
                    _nav("series", "Series", "/opds/series", "Every series, in order", len(series)),
                    _nav("all", "All books", "/opds/all", "The whole library, A to Z", len(bs))]
        return _feed("root", "Babel's Library", entries, NAV)
    if path == "/opds/reading":
        items = sorted([it for it in bs if _status(it, st) == "reading" or 0 < float(it.get("progress") or 0) < 1],
                       key=lambda it: -(it.get("opened_at") or 0))
        return _paged(path, query, items, "reading", "Continue reading", st)
    if path == "/opds/next":
        sort = _shelf_sort(dev, "next", query)
        return _paged(path, query, _ordered([it for it in bs if _status(it, st) == "next"], sort, st), "next", "Up next", st, sort)
    if path == "/opds/sent":
        q = list(dev.get("queue") or [])
        return _paged(path, query, sorted([it for it in bs if it["id"] in q], key=lambda it: q.index(it["id"])), "sent", "Sent from the computer", st)
    if path == "/opds/recent":
        return _paged(path, query, sorted(bs, key=lambda it: -(it.get("added_at") or 0))[:100], "recent", "Recently added", st)
    if path == "/opds/all":
        return _paged(path, query, sorted(bs, key=lambda it: (it.get("title") or "").lower()), "all", "All books", st)
    if path == "/opds/series":
        names = sorted({it["series"] for it in bs if it.get("series")}, key=str.lower)
        entries = [_nav("series:" + n, n, "/opds/series/" + urllib.parse.quote(n), "",
                        sum(1 for it in bs if it.get("series") == n)) for n in names]
        return _feed("series", "Series", entries, NAV)
    if path.startswith("/opds/series/"):
        name = urllib.parse.unquote(path[len("/opds/series/"):])
        items = sorted([it for it in bs if it.get("series") == name], key=lambda it: float(it.get("series_index") or 0))
        return _paged(path, query, items, "series:" + name, name, st)
    if path == "/opds/search":
        import journal
        words = journal.norm(query.get("q") or "").split()
        hay = lambda it: journal.norm(" ".join([it.get("title") or "", " ".join(it.get("authors") or []), it.get("series") or ""]))
        items = [it for it in bs if words and all(w in hay(it) for w in words)]
        return _paged(path, query, sorted(items, key=_sort_title), "search", f"Search: {query.get('q') or ''}", st)
    return None


def _thumb(item_id, small):
    """The cover as a baseline grey JPEG the e-reader can decode (no progressive JPEG, no WebP), kept on disk."""
    raw = store.get_item(item_id, raw=True)
    if not raw or not raw.get("cover_path"):
        return None
    src = os.path.join(store.COVERS_DIR, raw["cover_path"])
    if not os.path.exists(src):
        return None
    os.makedirs(THUMBS, exist_ok=True)
    out = os.path.join(THUMBS, f"{item_id}-{'s' if small else 'l'}-{int(os.path.getmtime(src))}.jpg")
    if os.path.exists(out):
        return out
    try:
        from PIL import Image
        im = Image.open(src)
        im = im.convert("L")
        im.thumbnail((180, 270) if small else (480, 720))
        tmp = out + ".part"
        im.save(tmp, "JPEG", quality=85, progressive=False, optimize=True)
        os.replace(tmp, out)
        return out
    except Exception as e:
        print(f"[inkwell] e-reader cover for {item_id}: {e}")
        return src if src.lower().endswith((".jpg", ".jpeg")) else None


# ---------------------------------------------------------------- requests
def handle(h, method, path):
    """Called by the phone-sync server for /opds... and /kosync... paths."""
    import server
    dev = _device(h)
    if path.startswith("/kosync"):
        sub = path[len("/kosync"):]
        if sub == "/users/create" and method == "POST":
            return h._send(402, {"message": "Pair this e-reader from Babel's Library on the computer."})
        if not dev:
            return h._send(401, {"message": "Unauthorized"})
        store.use_profile(int(dev.get("profile") or store.OWNER))
        if sub == "/users/auth":
            phonesync_touch(dev)
            return h._send(200, {"authorized": "OK"})
        m = re.match(r"^/syncs/progress/([0-9a-fA-F]{32})$", sub)
        if m and method == "GET":
            code, body = get_progress(dev, m.group(1).lower())
            return h._send(code, body)
        if sub == "/syncs/progress" and method == "PUT":
            code, body = put_progress(dev, h.json_body())
            return h._send(code, body)
        return h._send(404, {"message": "Not found"})
    # OPDS
    if not dev:
        h.send_response(401)
        h.send_header("WWW-Authenticate", 'Basic realm="Babel\'s Library"')
        h.send_header("Content-Length", "0")
        h.end_headers()
        return
    store.use_profile(int(dev.get("profile") or store.OWNER))
    m = re.match(r"^/opds/book/(\d+)/[^/]*$", path)
    if m and method == "GET":
        iid = int(m.group(1))
        if iid not in {it["id"] for it in books()}:
            return h._send(404, {"error": "not found"})
        if iid in set(dev.get("queue") or []):
            import phonesync
            phonesync._sent(dev, [iid])
        return server.r_file(h, iid)
    m = re.match(r"^/opds/finish/(\d+)$", path)
    if m and method == "GET":
        iid = int(m.group(1))
        if iid not in {it["id"] for it in books()}:
            return h._send(404, {"error": "not found"})
        title = mark_finished(dev, iid)
        entry = _nav(f"finished:{iid}", f"Marked finished: {title}", "/opds", "Saved to Babel's Library")
        return h._send(200, _feed(f"finished:{iid}", "Finished", [entry], NAV), NAV)
    m = re.match(r"^/opds/cover/(\d+)\.jpg$", path)
    if m and method == "GET":
        if int(m.group(1)) not in {it.get("_cover") for it in books()}:
            return h._send(404, {"error": "no cover"})
        p = _thumb(int(m.group(1)), bool(h.query.get("thumb")))
        if not p:
            return h._send(404, {"error": "no cover"})
        return h.send_file(p, "image/jpeg")
    body = opds(dev, path, h.query) if method == "GET" else None
    if body is None:
        return h._send(404, {"error": "not found"})
    phonesync_touch(dev)
    kind = NAV if path in ("/opds", "/opds/", "/opds/series", "/opds/sort") else ACQ
    return h._send(200, body, kind)


def phonesync_touch(dev):
    import phonesync
    phonesync._touch(dev)
