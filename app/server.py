"""Babel's Library — a local, offline-first personal library.

Run:  python3 app/server.py      then open http://localhost:8765
"""
import hashlib
import html
import json
import mimetypes
import os
import re
import shutil
import sqlite3
import sys
import threading
import time
import traceback
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except Exception:
        pass
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("text/html", ".html")
mimetypes.add_type("application/wasm", ".wasm")
sys.path.insert(0, HERE)

import ai  # noqa: E402
import cite  # noqa: E402
import comics  # noqa: E402
import files  # noqa: E402
import importers  # noqa: E402
import devices  # noqa: E402
import series  # noqa: E402
import journal  # noqa: E402
import discover  # noqa: E402
import media_catalog  # noqa: E402
import extract  # noqa: E402
import lookup  # noqa: E402
import media  # noqa: E402
import store  # noqa: E402
import subs  # noqa: E402
import audiobook  # noqa: E402
import taxonomy  # noqa: E402

STATIC = os.path.join(HERE, "static")
PORT = int(os.environ.get("INKWELL_PORT", "8765"))
SUPPORTED = files.SUPPORTED
activity = []  # recent events for the UI
DESKTOP = None  # set by desktop.py when running as a desktop app
_activity_lock = threading.Lock()


def log(msg, kind="info", item_id=None):
    print(f"[inkwell] {msg}")
    with _activity_lock:
        activity.append({"t": time.time(), "msg": msg, "kind": kind, "item_id": item_id})
        del activity[:-50]


def sha256_file(path):
    """Content fingerprint. Large media files use size + head + tail so scans stay fast."""
    h = hashlib.sha256()
    size = os.path.getsize(path)
    if media.is_media(os.path.splitext(path)[1]) and size > 64 * 1024 * 1024:
        with open(path, "rb") as f:
            h.update(str(size).encode())
            h.update(f.read(4 << 20))
            f.seek(-(4 << 20), 2)
            h.update(f.read())
        return "q" + h.hexdigest()[1:]
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def safe_name(name):
    base = re.sub(r"[^\w.\- ]+", "_", os.path.basename(name)).strip() or "file"
    return base[-120:]


# ---------------- import pipeline ----------------
def import_file(src_path, filename=None, origin="upload", move=False, meta=None, attach_to=None, quiet=False):
    """Bring a file into the library: de-duplicate, copy/move into the library folder, then sort it."""
    filename = filename or os.path.basename(src_path)
    ext = os.path.splitext(filename)[1].lower()
    if ext not in SUPPORTED:
        raise ValueError("Babel's Library can add PDF, EPUB, CBZ and CBR files.")
    sha = sha256_file(src_path)
    existing = store.find_by_sha(sha)
    if existing:
        if move and origin in ("folder scan", "inbox folder") and not files.inside(src_path, files.library_root()):
            try:
                os.remove(src_path)  # it's a duplicate of something already filed
            except OSError:
                pass
        return existing, False
    meta = dict(meta or {})
    picture = None
    if media.is_media(ext):
        mm = media.metadata(src_path, filename)
        picture = mm.pop("picture", None)
        for k, v in mm.items():
            if v not in (None, "", []) and not meta.get(k):
                meta[k] = v
    kind = meta.get("kind") or files.kind_for_ext(ext)
    if kind == "tv" and meta.get("series"):
        meta["series"] = canonical_series(meta["series"])
    side = subs.sidecars(src_path) if kind in ("tv", "movie") else []
    dest = files.place_new(src_path, filename, kind, move=move, genre=meta.get("genre"), meta=meta)
    if side and os.path.abspath(dest) != os.path.abspath(src_path):
        src_base = os.path.splitext(os.path.basename(src_path))[0]
        dest_base = os.path.splitext(os.path.basename(dest))[0]
        for sc in side:
            fn = os.path.basename(sc["path"])
            new = dest_base + fn[len(src_base):] if fn.lower().startswith(src_base.lower()) else f"{dest_base}.{os.path.splitext(fn)[0]}{os.path.splitext(fn)[1]}"
            try:
                (files.safe_move if move else files.safe_copy)(sc["path"], os.path.join(os.path.dirname(dest), new))
            except OSError as e:
                print("[inkwell] subtitle file not copied:", e)
    fields = {"file_path": dest, "file_type": ext[1:], "sha256": sha, "status": "analyzing", "orig_name": filename}
    if attach_to:
        store.update_item(attach_to, fields)
        item_id = attach_to
        threading.Thread(target=analyze_item, args=(item_id, False), kwargs={"merge_tags": True}, daemon=True).start()
    else:
        title_guess = os.path.splitext(filename)[0].replace("_", " ")
        data = {"kind": kind, "title": title_guess, "source": origin, **fields}
        data.update({k: v for k, v in meta.items() if k in store.ITEM_FIELDS and k not in fields})
        item_id = store.create_item(data)
        if picture:
            with open(os.path.join(store.COVERS_DIR, f"{item_id}.jpg"), "wb") as f:
                f.write(picture)
            store.update_item(item_id, {"cover_path": f"{item_id}.jpg"})
        if not quiet:
            log(f"Added “{data['title']}” ({origin})", "import", item_id)
        threading.Thread(target=analyze_item, args=(item_id, not meta.get("title")),
                         kwargs={"merge_tags": bool(meta.get("tags")), "keep_fields": tuple(k for k in ("summary", "genre") if meta.get(k))},
                         daemon=True).start()
    return item_id, True


def canonical_series(name):
    """Reuse the spelling of a show that's already in the library ('Psycho Pass' -> 'Psycho-Pass')."""
    key = media.series_key(name)
    if not key:
        return name
    for it in store.list_items():
        if it.get("series") and it["kind"] in ("tv", "movie", "book", "graphic") and media.series_key(it["series"]) == key:
            return it["series"]
    return name


def create_entry(d):
    """An item with no file yet (typed in, looked up, or imported without an attachment)."""
    d = dict(d)
    d.setdefault("kind", "book")
    d["status"] = "analyzing"
    iid = store.create_item({k: v for k, v in d.items() if k in store.ITEM_FIELDS})
    keep = [k for k in ("genre", "fiction") if d.get(k) not in (None, "")]
    threading.Thread(target=analyze_item, args=(iid, False, keep), kwargs={"merge_tags": bool(d.get("tags"))}, daemon=True).start()
    return iid


def download_open_access(item_id, quiet=False):
    """Find a free, legal copy (arXiv / OpenAlex open-access / direct PDF link) and file it in the library folder."""
    it = store.get_item(item_id)
    if not it or it.get("has_file"):
        return False
    cands = lookup.find_open_access(it.get("doi"), it.get("url"))
    if not cands:
        if not quiet:
            log(f"No free copy found for “{it['title']}”", "info", item_id)
        return False
    tmp = os.path.join(store.DATA_DIR, f".dl-{time.time_ns()}.pdf")
    try:
        used = lookup.download_pdf(cands, tmp)
        if not used:
            if not quiet:
                log(f"No free copy found for “{it['title']}”", "info", item_id)
            return False
        name = files.clean_filename(f"{it['title'][:120]}.pdf")
        import_file(tmp, name, origin="download", move=True, attach_to=item_id)
        log(f"Downloaded a free copy of “{it['title']}”", "import", item_id)
        return True
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def merge_meta(item, found, overwrite=False):
    upd = {}
    for k in ("kind", "title", "authors", "year", "journal", "volume", "issue", "pages", "publisher", "place", "doi", "isbn", "url"):
        v = found.get(k)
        if v and (overwrite or not item.get(k) or (k == "title" and item.get("_title_is_guess"))):
            upd[k] = v
    if upd.get("doi"):
        upd["doi"] = extract.clean_doi(upd["doi"])
    return upd


LOCKABLE = ("title", "authors", "year", "kind", "topic", "subject", "genre", "fiction", "series", "series_index",
            "tags", "summary", "publisher", "journal", "volume", "issue", "pages", "doi", "isbn", "url", "place",
            "album", "album_artist", "track", "disc", "season", "episode", "direction", "format")


def _web_details(kind, item, meta):
    """Synopsis + bookstore categories for books and comics (online, optional, fails quietly)."""
    if kind not in ("book", "graphic"):
        return
    try:
        if item.get("isbn"):
            g = lookup.google_books(isbn=item["isbn"])
        else:
            g = lookup.google_books(title=item.get("title"), author=(item.get("authors") or [None])[0])
        meta["description"] = meta.get("description") or g.get("description", "")
        meta["categories"] = (meta.get("categories") or []) + g.get("categories", [])
        if g.get("series_index") and not item.get("series_index"):
            meta["series_index"] = g["series_index"]
    except Exception as e:
        print("[inkwell] google books skipped:", e)
    if item.get("isbn") and (not meta.get("description") or not meta.get("categories")):
        try:
            o = lookup.openlibrary_description(item["isbn"])
            meta["description"] = meta.get("description") or o["description"]
            meta["categories"] = (meta.get("categories") or []) + o["categories"]
        except Exception as e:
            print("[inkwell] openlibrary skipped:", e)


def analyze_item(item_id, refresh_meta=True, keep_fields=(), merge_tags=False, comicinfo=None):
    _analyze_item(item_id, refresh_meta, keep_fields, merge_tags, comicinfo)
    try:
        merge_copies(item_id)          # (now that its title and ISBN are known)
    except Exception as e:
        print("[inkwell] copies not merged:", e)


def _last_name(it):
    a = ((it.get("authors") or [""])[0] or "").replace(",", " ").split()
    return a[-1].lower() if a else ""


def merge_copies(item_id):
    """A file for a book (or comic) you already have on the shelf as a physical copy, or on your wishlist: the file
    joins that entry (its journal, notes, collections and place stay together) instead of making a second one.
    Returns the id the file ended up under."""
    it = store.get_item(item_id)
    if not it or not it.get("has_file") or it["kind"] not in ("book", "graphic"):
        return item_id
    key = journal.norm(it.get("title") or "")
    for o in store.list_items():
        if o["id"] == item_id or o.get("has_file") or o["kind"] != it["kind"] or not (o.get("physical") or o.get("wanted")):
            continue
        same_isbn = bool(it.get("isbn")) and str(o.get("isbn") or "").replace("-", "") == str(it["isbn"]).replace("-", "")
        same_title = len(key) > 3 and journal.norm(o.get("title") or "") == key and (not _last_name(o) or not _last_name(it) or _last_name(o) == _last_name(it))
        if it.get("kind") == "graphic" and (o.get("series_index") or it.get("series_index")) and o.get("series_index") != it.get("series_index"):
            continue                    # (a different volume of the same series)
        if not (same_isbn or same_title):
            continue
        raw = store.get_item(item_id, raw=True)
        fields = {k: raw.get(k) for k in ("file_path", "file_type", "sha256", "orig_name") if raw.get(k) is not None}
        for k in ("summary", "isbn", "publisher", "year", "genre", "series", "series_index", "format", "direction", "subject", "fiction"):
            if o.get(k) in (None, "", []) and it.get(k) not in (None, "", []):
                fields[k] = it[k]
        if o.get("wanted"):
            fields["wanted"] = 0        # (the wishlist entry: you have it now)
        old_raw = store.get_item(o["id"], raw=True)
        if not old_raw.get("cover_path") and raw.get("cover_path"):
            src = os.path.join(store.COVERS_DIR, raw["cover_path"])
            if os.path.exists(src):
                dst_name = f"{o['id']}{os.path.splitext(raw['cover_path'])[1] or '.jpg'}"
                shutil.copy2(src, os.path.join(store.COVERS_DIR, dst_name))
                fields["cover_path"] = dst_name
        store.update_item(o["id"], fields)
        store.update_item(item_id, {"file_path": None, "sha256": None})     # (so removing the extra entry can't touch the file)
        store.delete_item(item_id, delete_file=False)
        log(f"“{o['title']}”: the new file joined the copy already on your shelf", "import", o["id"])
        return o["id"]
    return item_id


def merge_all_copies():
    """Once: physical copies (and wishlist entries) that a file of the same book was added beside, before files
    found their copy by themselves. The library is backed up first."""
    if store.get_settings().get("copies_merged"):
        return
    pairs = 0
    try:
        bk = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "BabelsLibraryBackups")
        os.makedirs(bk, exist_ok=True)
        shutil.copy2(store.DB_PATH, os.path.join(bk, time.strftime("library-before-copy-merge-%Y%m%d-%H%M%S.db")))
        for it in store.list_items():
            if it.get("has_file") and it["kind"] in ("book", "graphic") and merge_copies(it["id"]) != it["id"]:
                pairs += 1
        store.set_settings({"copies_merged": 1})
        if pairs:
            print(f"[inkwell] merged {pairs} file(s) into the physical copies already on the shelf")
    except Exception as e:
        print("[inkwell] merging copies skipped:", e)


def _analyze_item(item_id, refresh_meta=True, keep_fields=(), merge_tags=False, comicinfo=None):
    try:
        raw = store.get_item(item_id, raw=True)
        if not raw:
            return
        item = store.get_item(item_id)
        settings = store.get_settings()
        locked = set(item.get("locked") or []) | set(keep_fields or ())
        path = store.resolve_file(raw.get("file_path"))
        if path and not os.path.exists(path):
            path = None
        kind = item.get("kind") or "article"
        if kind in files.MEDIA_KINDS:
            return analyze_media(item_id, item, locked, settings)

        meta = {"subjects": [], "categories": [], "description": "", "tag_hints": []}
        text, upd, title_is_guess, comic = "", {}, True, None

        if path and raw["file_type"] == "pdf":
            info = extract.pdf_info(path)
            text = info["text"]
            meta["keywords"] = info.get("keywords", "")
            if refresh_meta:
                if info["title"]:
                    upd["title"] = info["title"]
                    title_is_guess = False
                for k in ("authors", "year", "doi", "journal", "volume", "issue", "pages"):
                    if info.get(k) and not item.get(k):
                        upd[k] = info[k]
                isbn_m = re.search(r"ISBN[\s:-]*((?:97[89][\s-]?)?[\d\s-]{9,15}[\dX])", text[:30000], re.I)
                if isbn_m and extract.clean_isbn(isbn_m.group(1)) and not item.get("isbn"):
                    upd["isbn"] = extract.clean_isbn(isbn_m.group(1))
            # long documents without a DOI/journal, or with a table of contents of lessons/chapters, are books
            if "kind" not in locked and not (item.get("doi") or info.get("doi") or item.get("journal")):
                toc = re.search(r"\bcontents\b", text[:15000], re.I) and len(re.findall(r"\b(chapter|lesson|part)\s+\d", text[:20000], re.I)) >= 3
                if info["pages_total"] > 120 or (info["pages_total"] > 40 and toc):
                    upd["kind"] = "book"
        elif path and raw["file_type"] == "epub":
            info = extract.epub_info(path)
            text = info["text"]
            meta.update({"subjects": info["subjects"], "categories": list(info["subjects"]), "description": info["description"]})
            if refresh_meta:
                for k in ("title", "authors", "year", "isbn", "publisher"):
                    if info.get(k):
                        upd[k] = info[k]
                title_is_guess = not info.get("title")
            if info.get("series") and not item.get("series"):
                upd["series"] = info["series"]
                if info.get("series_index") is not None:
                    upd["series_index"] = info["series_index"]
            if info.get("cover_bytes") and not raw.get("cover_path"):
                cname = f"{item_id}{info['cover_ext'] or '.jpg'}"
                with open(os.path.join(store.COVERS_DIR, cname), "wb") as f:
                    f.write(info["cover_bytes"])
                upd["cover_path"] = cname
        elif path and raw["file_type"] in ("cbz", "cbr", "cb7", "cbt"):
            ci = comicinfo if comicinfo is not None else comics.read_zip_info(path)["comicinfo"]
            comic = comics.metadata(raw.get("orig_name") or os.path.basename(path), ci)
            upd["kind"] = "graphic"
            if refresh_meta or comicinfo is not None or re.search(r"Vol\. (19|20)\d\d$", item.get("title") or ""):
                for k in ("title", "authors", "year", "publisher", "url"):
                    if comic.get(k):
                        upd[k] = comic[k]
                upd["series"] = comic["series"] or None
                upd["series_index"] = comic["series_index"]
                title_is_guess = False
            if comic["rtl"] and not raw.get("direction"):
                upd["direction"] = "rtl"
            upd["format"] = "manga" if comic["manga"] else "comic"
            meta.update({"description": comic["summary"], "categories": comic["genres"], "tag_hints": comic["tags"]})
        else:
            meta["description"] = item.get("summary") or ""

        merged = {**item, **upd, "_title_is_guess": title_is_guess}
        kind = merged.get("kind") or kind

        # series from the title, e.g. "The Way of Kings: The Stormlight Archive"
        if kind == "book" and not merged.get("series"):
            t, ser, idx = extract.series_from_title(merged.get("title"))
            if ser:
                upd["title"], upd["series"] = t, ser[0].upper() + ser[1:]
                if idx is not None:
                    upd["series_index"] = idx
                merged.update(upd)

        # online catalogue details (silently skipped when offline)
        if settings.get("auto_lookup"):
            if refresh_meta and not comic and (merged.get("doi") or merged.get("isbn")):
                try:
                    found = lookup.crossref(merged["doi"]) if merged.get("doi") else lookup.openlibrary(merged["isbn"])
                    if path and raw["file_type"] == "pdf" and found.get("kind") == "book" and merged.get("kind") == "article":
                        found["kind"] = "book"
                    upd.update(merge_meta(merged, found, overwrite=bool(merged.get("doi"))))
                    meta["categories"] = meta["categories"] + found.get("subjects", [])
                    if found.get("description"):
                        meta["description"] = meta.get("description") or found["description"]
                    if found.get("cover_url") and not raw.get("cover_path") and not upd.get("cover_path"):
                        try:
                            data = lookup.download(found["cover_url"])
                            with open(os.path.join(store.COVERS_DIR, f"{item_id}.jpg"), "wb") as f:
                                f.write(data)
                            upd["cover_path"] = f"{item_id}.jpg"
                        except Exception:
                            pass
                except Exception as e:
                    print("[inkwell] lookup skipped:", e)
                merged = {**merged, **upd}
                kind = merged.get("kind") or kind
            # a book with no file (a physical copy, or wished for): use its Wikipedia cover
            if kind in ("book", "graphic") and not path and not raw.get("cover_path") and not upd.get("cover_path"):
                try:
                    data = discover.cover("", merged.get("isbn") or "", merged.get("title") or "", (merged.get("authors") or [""])[0])
                    with open(os.path.join(store.COVERS_DIR, f"{item_id}.jpg"), "wb") as f:
                        f.write(data)
                    upd["cover_path"] = f"{item_id}.jpg"
                except Exception as e:
                    print("[inkwell] cover for a book without a file skipped:", e)
            if kind in ("book", "graphic") and (not meta.get("description") or not meta.get("categories")):
                _web_details(kind, merged, meta)
                if meta.get("series_index") and not merged.get("series_index"):
                    upd["series_index"] = meta["series_index"]

        if kind in ("book", "graphic") and not merged.get("authors") and "authors" not in locked and settings.get("auto_lookup"):
            name = merged.get("series") if kind == "graphic" and merged.get("series") else merged.get("title")
            try:
                found_people = lookup.find_creators(name, merged.get("publisher"), merged.get("year"))
            except Exception as e:
                found_people = []
                print("[inkwell] creator lookup skipped:", e)
            if found_people:
                upd["authors"] = found_people
                merged["authors"] = found_people
        if kind == "article" and not meta.get("description") and item.get("summary") and item.get("source") in ("zotero", "calibre"):
            meta["description"] = item["summary"]
        if kind in ("book", "graphic") and not meta.get("description") and ai.looks_like_synopsis(item.get("summary")):
            meta["description"] = item["summary"]  # keep a real synopsis found earlier (online or typed in)
        if kind == "article" and not meta.get("description") and item.get("summary") and "abstract" in (item.get("summary") or "")[:12].lower():
            meta["description"] = re.sub(r"^\s*abstract[\s.:—–-]*", "", item["summary"], flags=re.I)

        meta.update({"title": merged.get("title", ""), "authors": merged.get("authors", []), "year": merged.get("year", ""),
                     "series": merged.get("series")})
        res = ai.analyze(kind, meta, text, settings)
        llm_title = res.pop("_title", None)
        llm_authors = res.pop("_authors", None)
        if title_is_guess and llm_title and "title" not in upd:
            upd["title"] = llm_title
        if llm_authors and not merged.get("authors"):
            upd["authors"] = llm_authors
        if res.get("series") and not merged.get("series") and kind != "article":
            upd["series"] = res["series"]
        for k in ("topic", "subject", "genre", "fiction", "tags", "summary", "ai_source"):
            if k in res:
                upd[k] = res[k]
        if kind == "article":
            upd["genre"] = None
        if merge_tags and item.get("tags"):
            upd["tags"] = list(dict.fromkeys(item["tags"] + (upd.get("tags") or [])))[:8]
        for k in locked:
            upd.pop(k, None)
        upd["status"] = "ready"
        store.update_item(item_id, upd)
        if kind in ("book", "graphic"):
            series_check(item_id)
            try:
                got = discover.claim_wanted(item_id)
                if got:
                    log(f"From your wishlist: “{got}” is now on your shelves", "import", item_id)
            except Exception as e:
                print("[inkwell] wishlist check skipped:", e)
        try:
            it2 = store.get_item(item_id)
            if it2 and not (it2.get("wanted") and not it2.get("has_file")) and journal.link_orphans(it2):
                log(f"Linked your journal pages to “{it2.get('title')}”", "import", item_id)
        except Exception as e:
            print("[inkwell] journal link skipped:", e)
        files.refile(item_id)
        log(f"Sorted “{upd.get('title') or merged.get('title')}” into {upd.get('subject') or merged.get('subject')}", "sorted", item_id)
        if settings.get("auto_lookup") and (kind == "graphic" or (kind == "book" and VOL_RX.search(raw.get("orig_name") or ""))):
            threading.Thread(target=_auto_graphic, args=(item_id,), daemon=True).start()
    except Exception:
        traceback.print_exc()
        store.update_item(item_id, {"status": "ready"})


_series_t = None


def series_check(item_id):
    """Find this book's series (and number), then line up spellings across the library a moment later."""
    global _series_t
    try:
        it = store.get_item(item_id)
        if it:
            series.resolve(it, online=True)
    except Exception as e:
        print("[inkwell] series check skipped:", e)
    if _series_t:
        _series_t.cancel()
    _series_t = threading.Timer(2.0, lambda: series.tidy())
    _series_t.daemon = True
    _series_t.start()


def attach_poster(item_id, item, force=False):
    """Give a film, or every episode of a show, its official poster as the cover (online only)."""
    raw = store.get_item(item_id, raw=True) or {}
    if (raw.get("cover_path") or "").startswith("poster_") and not force:
        return None
    kind = item["kind"]
    if kind == "tv":
        key = media.series_key(item.get("series")) or f"i{item_id}"
        fname = f"poster_tv_{key}.jpg"
        siblings = [x for x in store.list_items() if x["kind"] == "tv" and media.series_key(x.get("series")) == media.series_key(item.get("series"))]
    else:
        fname = f"poster_m{item_id}.jpg"
        siblings = [item]
    dest = os.path.join(store.COVERS_DIR, fname)
    found = None
    if not os.path.exists(dest) or force:
        if not store.get_settings().get("auto_lookup"):
            return None
        found = lookup.find_poster(kind, item.get("series") if kind == "tv" else item.get("title"), item.get("year"))
        if not found:
            return None
        data = lookup.download(found["url"])
        if len(data) < 2000:
            return None
        with open(dest, "wb") as f:
            f.write(data)
    for x in siblings:
        old = (store.get_item(x["id"], raw=True) or {}).get("cover_path")
        if old and old != fname and not old.startswith("poster_"):
            try:
                os.remove(os.path.join(store.COVERS_DIR, old))
            except OSError:
                pass
        store.update_item(x["id"], {"cover_path": fname})
    return found or {}


def analyze_media(item_id, item, locked, settings):
    kind = item["kind"]
    upd = {"topic": "Music" if kind == "music" else "Film & Television"}
    upd["subject"] = taxonomy.SUBJECT_OF[upd["topic"]]
    upd["fiction"] = None if kind == "music" else (0 if (item.get("genre") or "").lower() == "documentary" else 1)
    tags = []
    if item.get("genre"):
        tags.append(item["genre"])
    if kind != "music" and settings.get("auto_lookup") and not item.get("summary"):
        try:
            name = item.get("series") if kind == "tv" else item.get("title")
            tries = [f"{name} (TV series)", name] if kind == "tv" else \
                    ([f"{name} ({item['year']} film)"] if item.get("year") else []) + [f"{name} (film)", name]
            for t in tries:
                w = lookup.wikipedia_summary(t)
                if w:
                    upd["summary"] = w
                    break
        except Exception as e:
            print("[inkwell] wikipedia skipped:", e)
    if kind in ("tv", "movie"):
        try:
            p = attach_poster(item_id, item)
            if p and p.get("summary") and not item.get("summary") and not upd.get("summary") and "summary" not in locked:
                upd["summary"] = p["summary"][:1200]
        except Exception as e:
            print("[inkwell] poster skipped:", e)
    models = ai.ollama_available(settings.get("ollama_url", ""))
    if models and kind != "music":
        try:
            what = f"the TV series {item.get('series')}" if kind == "tv" else f"the film {item.get('title')} ({item.get('year') or 'unknown year'})"
            body = json.dumps({"model": settings.get("ollama_model") or models[0], "format": "json", "stream": False,
                               "prompt": f"For {what}, reply ONLY with JSON: {{\"genre\": one of {taxonomy.SCREEN_GENRES}, \"tags\": 3-5 broad theme tags, \"series\": franchise name or \"\", \"synopsis\": 2-3 sentence synopsis}}. If you do not know it, use empty values."}).encode()
            req = urllib.request.Request(settings["ollama_url"].rstrip("/") + "/api/generate", data=body, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=120) as r:
                d = json.loads(json.loads(r.read()).get("response") or "{}")
            if d.get("genre") in taxonomy.SCREEN_GENRES and not item.get("genre"):
                upd["genre"] = d["genre"]
            tags += [t for t in (d.get("tags") or []) if isinstance(t, str)]
            if kind == "movie" and d.get("series") and not item.get("series"):
                upd["series"] = d["series"][:100]
            if d.get("synopsis") and not upd.get("summary") and not item.get("summary"):
                upd["summary"] = d["synopsis"][:900]
            upd["ai_source"] = "ollama"
        except Exception as e:
            print("[inkwell] ollama media skipped:", e)
    upd["tags"] = ai.clean_tags(tags + (item.get("tags") or []), [item.get("series"), item.get("album")])[:6]
    upd.setdefault("ai_source", "builtin")
    for k in locked:
        upd.pop(k, None)
    upd["status"] = "ready"
    store.update_item(item_id, upd)


# ---------------- watched folder ----------------
class Watcher(threading.Thread):
    daemon = True

    def __init__(self):
        super().__init__()
        self.seen = {}
        self.last_scan = None
        self.error = None

    def run(self):
        while True:
            s = store.get_settings()
            if s.get("watch_enabled") and s.get("watch_folder"):
                try:
                    self.scan(os.path.expanduser(s["watch_folder"]))
                    self.error = None
                except Exception as e:
                    self.error = str(e)
            time.sleep(max(3, int(s.get("watch_interval") or 10)))

    def scan(self, folder):
        os.makedirs(folder, exist_ok=True)
        self.last_scan = time.time()
        for root, dirs, files in os.walk(folder):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for fn in files:
                if fn.startswith(".") or os.path.splitext(fn)[1].lower() not in SUPPORTED:
                    continue
                p = os.path.join(root, fn)
                try:
                    st = os.stat(p)
                except OSError:
                    continue
                key = (st.st_size, st.st_mtime)
                if self.seen.get(p) == key:
                    continue
                # wait until the file has stopped changing (still copying)
                if time.time() - st.st_mtime < 2:
                    continue
                self.seen[p] = key
                try:
                    import_file(p, fn, origin="inbox folder", move=bool(store.get_settings().get("inbox_move")))
                except Exception as e:
                    log(f"Couldn't import {fn}: {e}", "error")


watcher = Watcher()


# ---------------- export ----------------
def annotations_markdown(item_ids=None):
    items = {i["id"]: i for i in store.list_items()}
    anns = store.list_annotations()
    by_item = {}
    for a in anns:
        if item_ids and a["item_id"] not in item_ids:
            continue
        by_item.setdefault(a["item_id"], []).append(a)
    out = ["# Babel's Library — Annotations", f"_Exported {time.strftime('%Y-%m-%d %H:%M')}_", ""]
    for iid, lst in by_item.items():
        it = items.get(iid)
        if not it:
            continue
        out.append(f"## {it['title']}")
        c = cite.all_citations(it)["APA (7th ed.)"]["text"]
        out.append(f"*{c}*")
        if it.get("tags"):
            out.append("Tags: " + ", ".join(f"`{t}`" for t in it["tags"]))
        out.append("")
        for a in lst:
            loc = a["locator"] or {}
            where = f"p. {loc['page']}" if loc.get("page") else (loc.get("label") or "")
            kind_label = {"pin": "Pin", "note": "Note"}.get(loc.get("type"), "Highlight")
            head = a["title"].strip() or kind_label
            out.append(f"### {head}" + (f"  ·  {where}" if where else ""))
            if a["quote"]:
                out.append("> " + a["quote"].replace("\n", "\n> "))
            if a["note"]:
                out.append("")
                out.append(a["note"])
            out.append("")
    return "\n".join(out)


# ---------------- HTTP ----------------
ROUTES = []


def _db_broken(e):
    msg = str(e).lower()
    return any(s in msg for s in ("disk i/o error", "unable to open", "readonly", "malformed", "not a database"))


def route(method, pattern):
    def deco(fn):
        ROUTES.append((method, re.compile("^" + pattern + "$"), fn))
        return fn
    return deco


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"  # keep connections open: covers and pages load much faster
    server_version = "Inkwell/1.0"

    def log_message(self, fmt, *args):
        pass

    def handle(self):
        try:
            super().handle()
        except ConnectionError:
            pass  # the window reloaded or closed while a request was open: nothing to report

    def _send(self, code, body=b"", ctype="application/json", headers=None):
        if body is None or isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        if "Cache-Control" not in (headers or {}):
            self.send_header("Cache-Control", "no-store")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def json_body(self):
        self._body_read = True
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}") if n else {}

    def raw_body(self):
        self._body_read = True
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n)

    def _dispatch(self, method):
        self._body_read = False
        try:
            self._route(method)
        finally:
            # with keep-alive, any request body a handler ignored must be read off the connection
            n = int(self.headers.get("Content-Length") or 0)
            if n and not self._body_read:
                try:
                    self.rfile.read(n)
                except OSError:
                    self.close_connection = True

    def _route(self, method):
        parsed = urllib.parse.urlparse(self.path)
        self.query = dict(urllib.parse.parse_qsl(parsed.query))
        path = parsed.path
        # only accept requests from this computer's browser
        host = (self.headers.get("Host") or "").split(":")[0]
        if host not in ("localhost", "127.0.0.1", "[::1]"):
            return self._send(403, {"error": "forbidden"})
        store.use_profile(store.desktop_profile())      # (this computer's chosen profile)
        try:
            for m, rx, fn in ROUTES:
                if m == method:
                    mt = rx.match(path)
                    if mt:
                        return fn(self, *mt.groups())
            if method in ("GET", "HEAD"):
                return self.static(path)
            self._send(404, {"error": "not found"})
        except (ValueError, LookupError) as e:
            self._send(400, {"error": str(e)})
        except ConnectionError as e:
            try:
                self._send(502, {"error": f"A site dropped the connection ({e})."})
            except OSError:
                self.close_connection = True  # it was the window that went away mid-answer: nothing to report
        except Exception as e:
            if isinstance(e, (OSError, sqlite3.Error)) and not store.drive_ok():
                return self._send(503, {"error": "The drive with your library isn't connected.", "drive_missing": True})
            if isinstance(e, sqlite3.Error) and _db_broken(e):
                store.reopen()  # the drive dropped out and came back: the next request gets a working database
            traceback.print_exc()
            self._send(500, {"error": str(e)})

    def do_GET(self):
        self._dispatch("GET")

    def do_HEAD(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_PATCH(self):
        self._dispatch("PATCH")

    def do_DELETE(self):
        self._dispatch("DELETE")

    def static(self, path):
        if path == "/":
            path = "/index.html"
        full = os.path.normpath(os.path.join(STATIC, path.lstrip("/")))
        if not full.startswith(STATIC) or not os.path.isfile(full):
            return self._send(404, "not found", "text/plain")
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        if full.endswith(".woff2"):
            ctype = "font/woff2"
        with open(full, "rb") as f:
            body = f.read()
        rel = path.lstrip("/")
        cache = "public, max-age=86400" if rel.startswith(("vendor/", "fonts/")) or rel.endswith((".woff2", ".png", ".ico")) else "no-cache"
        self._send(200, body, ctype, headers={"Cache-Control": cache})

    def send_file(self, full, ctype, download_name=None, cache=None):
        """Stream a file (supports Range requests, so audio/video can seek without loading it all)."""
        size = os.path.getsize(full)
        start, end, code = 0, size - 1, 200
        rng = self.headers.get("Range")
        if rng and rng.startswith("bytes="):
            a, _, b = rng[6:].split(",")[0].partition("-")
            if a:
                start = int(a)
                end = min(int(b), size - 1) if b else size - 1
            elif b:
                start = max(0, size - int(b))
            code = 206
        if start > end or start >= size:
            self.send_response(416)
            self.send_header("Content-Range", f"bytes */{size}")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Cache-Control", cache or "no-store")
        if code == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        if download_name:
            self.send_header("Content-Disposition", f'inline; filename="{download_name}"')
        self.end_headers()
        if self.command == "HEAD":
            return
        remaining = end - start + 1
        try:
            with open(full, "rb") as f:
                f.seek(start)
                while remaining > 0:
                    chunk = f.read(min(1 << 20, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass


# ---- items
@route("GET", r"/api/items")
def r_items(h):
    h._send(200, store.list_items())


@route("GET", r"/api/items/(\d+)")
def r_item(h, iid):
    it = store.get_item(int(iid))
    if not it:
        return h._send(404, {"error": "not found"})
    it["citations"] = cite.all_citations(it)
    h._send(200, it)


@route("POST", r"/api/items")
def r_create(h):
    d = h.json_body()
    d.setdefault("kind", "book")
    d.setdefault("physical", 1)
    iid = create_entry(d)
    if d.get("_download"):
        threading.Thread(target=download_open_access, args=(iid,), daemon=True).start()
    if d.get("_cover_url"):
        try:
            data = lookup.download(d["_cover_url"])
            with open(os.path.join(store.COVERS_DIR, f"{iid}.jpg"), "wb") as f:
                f.write(data)
            store.update_item(iid, {"cover_path": f"{iid}.jpg"})
        except Exception:
            pass
    if d.get("summary") is None and d.get("_description"):
        store.update_item(iid, {"summary": d["_description"][:600]})
    log(f"Added “{d.get('title')}”", "import", iid)
    h._send(200, store.get_item(iid))


@route("POST", r"/api/upload")
def r_upload(h):
    name = urllib.parse.unquote(h.headers.get("X-Filename") or "upload.pdf")
    tmp = os.path.join(store.DATA_DIR, f".upload-{time.time_ns()}{os.path.splitext(name)[1]}")
    with open(tmp, "wb") as f:
        remaining = int(h.headers.get("Content-Length") or 0)
        while remaining > 0:
            chunk = h.rfile.read(min(remaining, 1 << 20))
            if not chunk:
                break
            f.write(chunk)
            remaining -= len(chunk)
    try:
        iid, new = import_file(tmp, name, move=True)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    h._send(200, {"id": iid, "new": new, "item": store.get_item(iid)})


@route("PATCH", r"/api/items/(\d+)")
def r_update(h, iid):
    d = h.json_body()
    d.pop("file_path", None)
    d.pop("cover_path", None)
    d.pop("private_to", None)
    if "private" in d:          # "only me": hidden from every other profile (always the profile asking)
        d["private_to"] = store.viewer() if d.pop("private") else None
    if "opened" in d:
        d["opened_at"] = time.time()
    if "watched" in d:
        d["watched"] = 1 if d["watched"] else 0
        d["watched_at"] = time.time() if d["watched"] else None
        if d["watched"]:
            d.setdefault("progress", 1.0)   # marked as watched: it's finished, 100%
        if not d["watched"]:
            d.setdefault("progress", 0)
            d.setdefault("last_location", "0")
    elif isinstance(d.get("progress"), (int, float)) and d["progress"] >= 0.92:
        cur = store.get_item(int(iid)) or {}
        if cur.get("kind") in ("tv", "movie") and not cur.get("watched"):
            d["watched"], d["watched_at"] = 1, time.time()
    if d.get("doi"):
        d["doi"] = extract.clean_doi(d["doi"])
    if "series" in d:
        d["series"] = (d["series"] or "").strip() or None
        if d["series"]:
            d["series"] = canonical_series(d["series"])
    edited = [k for k in d if k in LOCKABLE]
    if edited and not d.pop("_no_lock", False):
        cur = store.get_item(int(iid)) or {}
        old = cur.get("locked") or []
        d["locked"] = with_hc_owned(sorted({k for k in old if not k.startswith(HC_MARK)} | set(edited)), hc_owned(old) - set(edited))
    d.pop("_no_lock", None)
    store.update_item(int(iid), d)
    if "kind" in d or "genre" in d:
        files.refile(int(iid))
    it = store.get_item(int(iid))
    it["citations"] = cite.all_citations(it)
    h._send(200, it)


# ---- profiles: everyone who uses the library, each with their own places, notes, journal and Bulletin
@route("GET", r"/api/profiles")
def r_profiles(h):
    h._send(200, {"profiles": store.list_profiles(), "current": store.viewer()})


@route("POST", r"/api/profiles")
def r_profile_new(h):
    d = h.json_body()
    h._send(200, store.create_profile(d.get("name"), d.get("face") or ""))


@route("PATCH", r"/api/profiles/(\d+)")
def r_profile_edit(h, pid):
    h._send(200, store.update_profile(int(pid), h.json_body()))


@route("DELETE", r"/api/profiles/(\d+)")
def r_profile_delete(h, pid):
    pid = int(pid)
    if pid != store.desktop_profile():
        store.need_pin(pid, h.json_body().get("pin"))       # (one with a PIN goes only with its PIN)
    journal.delete_profile(pid)
    import browser
    browser.delete_profile(pid)          # (its bookmarks)
    store.delete_profile(pid)
    allb = dict(store.get_settings().get("bulletin") or {})
    if allb.pop(str(pid), None) is not None:          # (its Bulletin goes with it)
        store.set_settings({"bulletin": allb})
    if store.desktop_profile() == pid:
        store.set_settings({"desktop_profile": store.OWNER})
    h._send(200, {"profiles": store.list_profiles(), "current": store.desktop_profile()})


@route("POST", r"/api/profiles/current")
def r_profile_use(h):
    """Who's using this computer now."""
    d = h.json_body()
    pid = int(d.get("id") or store.OWNER)
    if not store.get_profile(pid):
        raise ValueError("No such profile.")
    if pid != store.desktop_profile():
        store.need_pin(pid, d.get("pin"))
    store.set_settings({"desktop_profile": pid})
    h._send(200, {"current": pid})


@route("POST", r"/api/profiles/unlock")
def r_profile_unlock(h):
    """The app opened on a profile with a PIN: is this it?"""
    store.need_pin(store.desktop_profile(), h.json_body().get("pin"))
    h._send(200, {"ok": True})


@route("POST", r"/api/profiles/pin")
def r_profile_pin(h):
    """A PIN or password for the profile in use (set, changed, or taken off with an empty one)."""
    d = h.json_body()
    h._send(200, store.set_pin(store.desktop_profile(), d.get("pin"), d.get("old")))


# ---- the Bulletin's challenge of the week: kept per profile, so it's the same on the computer and every phone
@route("GET", r"/api/bulletin")
def r_bulletin_get(h):
    h._send(200, (store.get_settings().get("bulletin") or {}).get(str(store.viewer())) or {})


@route("POST", r"/api/bulletin")
def r_bulletin_set(h):
    allb = dict(store.get_settings().get("bulletin") or {})
    allb[str(store.viewer())] = {k: v for k, v in h.json_body().items() if k in ("week", "id", "type", "draw", "since")}
    store.set_settings({"bulletin": allb})
    h._send(200, {"ok": True})


@route("DELETE", r"/api/items/(\d+)")
def r_delete(h, iid):
    if h.query.get("delete_file") == "1":
        audiobook.delete(int(iid))
    store.delete_item(int(iid), delete_file=h.query.get("delete_file") == "1")
    h._send(200, {"ok": True})


@route("POST", r"/api/items/(\d+)/reanalyze")
def r_reanalyze(h, iid):
    store.update_item(int(iid), {"status": "analyzing"})
    threading.Thread(target=analyze_item, args=(int(iid), False), daemon=True).start()
    h._send(200, {"ok": True})


@route("POST", r"/api/items/(\d+)/fill")
def r_fill(h, iid):
    q = h.json_body().get("query", "")
    found = lookup.lookup(q)
    it = store.get_item(int(iid))
    upd = merge_meta(it, found, overwrite=True)
    store.update_item(int(iid), upd)
    it = store.get_item(int(iid))
    it["citations"] = cite.all_citations(it)
    h._send(200, it)


@route("GET", r"/api/items/(\d+)/file")
def r_file(h, iid):
    raw = store.get_item(int(iid), raw=True)
    if not raw or not raw.get("file_path"):
        return h._send(404, {"error": "no file"})
    full = store.resolve_file(raw["file_path"])
    if not os.path.exists(full):
        return h._send(404, {"error": "The file has been moved or deleted: " + full})
    ctype = {"pdf": "application/pdf", "epub": "application/epub+zip", "cbz": "application/vnd.comicbook+zip",
             "cbr": "application/vnd.comicbook-rar"}.get(raw["file_type"]) or media.CONTENT_TYPES.get("." + raw["file_type"], "application/octet-stream")
    h.send_file(full, ctype, urllib.parse.quote(os.path.basename(full)))


@route("GET", r"/api/items/(\d+)/cover")
def r_cover(h, iid):
    raw = store.get_item(int(iid), raw=True)
    if not raw or not raw.get("cover_path"):
        return h._send(404, {"error": "no cover"})
    full = os.path.join(store.COVERS_DIR, raw["cover_path"])
    if not os.path.exists(full):
        return h._send(404, {"error": "no cover"})
    # cover URLs carry ?v=<version>, so the browser can keep them instead of re-downloading on every redraw
    h.send_file(full, mimetypes.guess_type(full)[0] or "image/jpeg",
                cache="private, max-age=31536000, immutable" if h.query.get("v") else "no-cache")


@route("POST", r"/api/items/(\d+)/cover")
def r_cover_set(h, iid):
    data = h.raw_body()
    ext = ".png" if data[:4] == b"\x89PNG" else ".jpg"
    name = f"{iid}{ext}"
    with open(os.path.join(store.COVERS_DIR, name), "wb") as f:
        f.write(data)
    store.update_item(int(iid), {"cover_path": name})
    h._send(200, {"ok": True})


@route("POST", r"/api/items/(\d+)/pullcover")
def r_pullcover(h, iid):
    """A cover from the web for a book that has none: Hardcover first, then Wikipedia and the other catalogues."""
    it = store.get_item(int(iid))
    if not it:
        return h._send(404, {"error": "not found"})
    try:
        discover.pull_cover(it)
    except LookupError:
        raise ValueError("No cover found online for this book. Check its title and author" +
                         ("" if discover.hardcover_on() else ", or add a Hardcover token in Settings → Book catalogue") + ".")
    h._send(200, {"ok": True})


@route("POST", r"/api/covers/fill")
def r_covers_fill(h):
    """Every book without a cover (that the app can't draw one for itself) gets one from the web, in the background."""
    n = sum(1 for it in store.list_items() if discover.needs_cover(it))
    def run():
        got = discover.covers_for_shelf()
        log(f"Found covers for {len(got)} of {n} books that had none" + (f": {', '.join(got[:5])}" if got else ""), "import")
    threading.Thread(target=run, daemon=True).start()
    h._send(200, {"ok": True, "books": n})


HC_FIELDS = ("title", "authors", "year", "summary", "genre", "fiction", "series", "series_index", "isbn")
# Fields filled from Hardcover are locked like your own edits (a re-sort leaves them alone), and also listed in one
# "hc=..." entry of the lock list, so pulling from Hardcover again may update them. Editing one yourself unlists it.
HC_MARK = "hc="


def hc_owned(locked):
    return {f for x in locked or [] if x.startswith(HC_MARK) for f in x[len(HC_MARK):].split(",") if f}


def with_hc_owned(plain, owned):
    return list(plain) + ([HC_MARK + ",".join(sorted(owned))] if owned else [])


def fill_from_online(iid, it, found, fields, skip, tags, their_words):
    """Write details found online (Hardcover for books, Wikipedia for films) onto an item. Replaces what the app found by
    itself, keeps what you typed in yourself, and protects what it fills from later re-sorts.
    tags: the source's extra genres to add as tags; their_words: every word that source uses, so its earlier tags are
    replaced rather than piling up. Returns (updated fields, fields of yours it kept)."""
    upd, kept, same = {}, [], []
    locked = it.get("locked") or []
    from_web = hc_owned(locked)
    mine = {k for k in locked if not k.startswith(HC_MARK)} - from_web   # fields you typed in yourself
    for k in fields:
        v = found.get(k)
        if v in (None, "", []) or k in skip:
            continue
        if k in mine:
            if it.get(k) not in (None, "", []) and it.get(k) != v:
                kept.append(k)
            continue
        if k == "series":
            v = canonical_series(v)
        if it.get(k) != v:
            upd[k] = v
        else:
            same.append(k)
    if tags and "tags" not in mine:
        theirs = {g.lower() for g in list(their_words) + list(tags)}
        base = [t for t in it.get("tags") or [] if t.lower() not in theirs]
        new = list(dict.fromkeys(base + list(tags)))[:8]
        if new != (it.get("tags") or []):
            upd["tags"] = new
        else:
            same.append("tags")
    if upd or set(same) - from_web:
        got = (set(upd) | set(same)) & set(LOCKABLE)
        upd["locked"] = with_hc_owned(sorted({k for k in locked if not k.startswith(HC_MARK)} | got), from_web | got)
        store.update_item(iid, upd)
        if {"genre", "series", "kind", "format"} & set(upd):
            files.refile(iid)
        if "series" in upd and it.get("kind") in ("book", "graphic"):
            threading.Thread(target=series_check, args=(iid,), daemon=True).start()
    return {k: v for k, v in upd.items() if k != "locked"}, kept


# ---- manga and comics: series, authors, genres, format and reading direction from AniList (manga) / Hardcover (comics)
VOL_RX = re.compile(r"(?:\bv(?:ol(?:ume)?)?|\bbook|\bpart)[\s._:-]*0*(\d{1,3})(?!\d)", re.I)
MANGA_FIELDS = ("kind", "format", "direction", "series", "series_index", "title", "authors", "genre", "fiction", "summary")
COMIC_FIELDS = ("kind", "format", "direction", "series", "series_index", "authors", "genre", "fiction", "summary", "year")


def volume_of(it):
    for s in (it.get("orig_name") or "", it.get("title") or ""):
        m = VOL_RX.search(re.sub(r"\(\d{4}\)", " ", os.path.splitext(s)[0]))
        if m:
            return float(m.group(1))
    m = re.search(r"[.,]\s*(\d{1,3})\s*$", it.get("title") or "")       # "Goodnight Punpun. 4"
    return float(m.group(1)) if m else it.get("series_index")


EDITION_RX = re.compile(r"\s*[-–:]?\s*(?:the complete\b.*|(?:master|deluxe|omnibus|perfect|collector'?s|complete|definitive|"
                        r"special|anniversary)\s+edition\b.*)$", re.I)


def series_query(it):
    """The series name to look up: the series if there is one, else the title (or file name) without volume numbers,
    'MANGA:' labels, '-- author' tails, release-group tags and edition wording ('Master Edition')."""
    base = it.get("series") or ""
    if not base:
        base = re.sub(r"^\s*manga\s*[:-]\s*", "", it.get("title") or "", flags=re.I)
        name = os.path.splitext(it.get("orig_name") or "")[0]
        fn = VOL_RX.split(re.split(r"\s+--\s+", name)[0])[0] if name else ""
        fn = re.sub(r"\s*\([^)]*\)|\s*\[[^\]]*\]", " ", fn).strip(" -_.,")
        # PDFs and EPUBs often carry a wrong built-in title ("MANGA: …", one volume's title on another); the file
        # name ("Goodnight Punpun v03", "BLAME! Academy and So On") is the better clue for them
        if len(fn) >= 3 and (VOL_RX.search(name) or it.get("kind") != "graphic"):
            base = fn
    base = re.split(r"\s+--\s+", base)[0]
    base = re.sub(r"\s*\((?:[^)]*)\)|\s*\[[^\]]*\]", " ", base)
    base = re.sub(r"[,:]?\s*\b(?:vol(?:ume)?\.?|v)\s*[\d.]*\s*$|,?\s*vol\.?\s*none\s*$", "", base, flags=re.I)
    base = EDITION_RX.sub("", base)
    return re.sub(r"\s+", " ", base).strip(" -_.,:")


WESTERN_RX = re.compile(r"\(graphic novel\)|-DCP\)|\(webrip\)|Son of Ultron|\((?:marvel|dc|image|oni|dark horse|idw|boom|rebellion|"
                        r"europe comics|humanoids|titan)\b", re.I)
CJK_RX = re.compile(r"[぀-ヿ一-鿿가-힯]")


def _looks_like_comic_file(path, ftype):
    """A PDF or EPUB that's mostly pictures (a scanned or digital comic) rather than a book's text."""
    try:
        if ftype == "pdf":
            info = extract.pdf_info(path, max_pages=12)
            return info["pages_total"] >= 16 and len(info["text"].strip()) < 250 * min(12, info["pages_total"])
        if ftype == "epub":
            import zipfile
            with zipfile.ZipFile(path) as z:
                pics = sum(1 for n in z.namelist() if re.search(r"\.(jpe?g|png|webp|gif)$", n, re.I))
            text = re.sub(r"\bkcc-\d+-kcc\b", "", extract.epub_info(path, max_chars=20000)["text"]).strip()   # Kindle Comic Converter page labels
            return len(text) < 4000 or (pics >= 30 and len(text) / pics < 60)
    except Exception:
        pass
    return False


def graphic_candidates():
    """Comics and manga on the shelves, plus PDFs/EPUBs filed as books that are really volumes of a comic."""
    out, books = [], []
    for it in store.list_items():
        if it.get("kind") == "graphic":
            out.append(it)
        elif it.get("kind") == "book" and it.get("has_file") and it.get("file_type") in ("pdf", "epub"):
            books.append(it)
    picked = [b for b in books if VOL_RX.search(b.get("orig_name") or "") or re.match(r"^\s*manga\s*[:-]", b.get("title") or "", re.I)]
    # a stray volume carrying the same built-in title as the others ("BLAME! Academy and So On" titled "BLAME! Master Edition")
    titles = {b.get("title") for b in picked}
    picked += [b for b in books if b not in picked and b.get("title") in titles]
    return out + picked


def fix_graphic_series(items, log_each=False):
    """Look up one series (a list of its volumes) and set them all straight. Returns (source, changed count)."""
    q = series_query(items[0])
    western = any(WESTERN_RX.search(x.get("orig_name") or "") for x in items)   # a western comic release: not on AniList
    authors = list(dict.fromkeys(a for x in items for a in x.get("authors") or []))
    hit = lookup.manga_match(q, authors) if q and not western else None
    changed = 0
    if hit:
        # AniList's English title, else the English name you already use (rather than the Japanese one)
        series_name = hit["english"] or (q if lookup._norm(q) in lookup._al_names(hit) else hit["romaji"])
        series_name = canonical_series(series_name)
        for it in items:
            if it.get("kind") != "graphic":
                raw = store.get_item(it["id"], raw=True) or {}
                path = store.resolve_file(raw.get("file_path"))
                if not (path and os.path.exists(path) and _looks_like_comic_file(path, it.get("file_type"))):
                    continue                    # a real book that shares the name: leave it alone
            n = volume_of(it)
            found = {"kind": "graphic", "format": "manga", "direction": "rtl" if hit["country"] == "JP" else "ltr",
                     "series": series_name, "series_index": n, "title": f"{series_name}, Vol. {n:g}" if n else series_name,
                     "authors": hit["authors"], "genre": hit["genre"], "fiction": 1, "summary": hit["summary"]}
            skip = {"summary"} if len((it.get("summary") or "").strip()) > 120 and it.get("kind") == "graphic" else set()
            tags = [g for g in hit["genres"] + hit["tags"] if g not in ("Slice of Life",)][:6]
            upd, _ = fill_from_online(it["id"], it, found, MANGA_FIELDS, skip, tags, hit["genres"] + hit["tags"])
            changed += bool(upd)
        return "AniList", changed
    if discover.hardcover_on() and all(it.get("kind") == "graphic" for it in items):
        for it in items:
            try:
                d = discover.hardcover_details(q if it.get("series") else (it.get("title") or q), (it.get("authors") or [""])[0])
            except Exception as e:
                print("[inkwell] hardcover comic lookup skipped:", e)
                d = None
            if not d or not any(re.search(r"comic|graphic novel|manga|superhero", g, re.I) for g in d.get("genres") or []):
                continue    # Hardcover found a novel of the same name ("Outline"), not this comic
            # a Japanese manga Hardcover files under comics (by an author with a Japanese name, or tagged manga)
            jp = (not western and any(CJK_RX.search(a) and not re.search(r"[가-힯]", a) for a in authors)) \
                or any(re.search(r"\bmanga\b", g, re.I) for g in d.get("genres") or [])
            d.update({"kind": "graphic", "format": "manga" if jp else "comic", "direction": "rtl" if jp else "ltr"})
            if it.get("series"):
                d.pop("series", None)
                d.pop("series_index", None)  # the volume numbering from the files is more reliable than Hardcover's
            skip = {"summary"} if len((it.get("summary") or "").strip()) > 120 else set()
            upd, _ = fill_from_online(it["id"], it, d, COMIC_FIELDS, skip, [g for g in d.get("genres") or [] if g != d.get("genre")][:4], d.get("genres") or [])
            changed += bool(upd)
        if changed:
            return "Hardcover", changed
    # not found anywhere: a volume by a Japanese / Korean author is still a manga, read right to left (Korean: left to right)
    if not western and authors and any(CJK_RX.search(a) for a in authors):
        korean = any(re.search(r"[가-힯]", a) for a in authors)
        for it in items:
            if it.get("kind") == "graphic":
                upd, _ = fill_from_online(it["id"], it, {"format": "manga", "direction": "ltr" if korean else "rtl"},
                                          ("format", "direction"), set(), [], [])
                changed += bool(upd)
        return ("its author's name" if changed else None), changed
    return None, 0


def _auto_graphic(item_id):
    """A comic or manga volume was just added: look up its series (a manga's format, reading direction, authors, genre)."""
    try:
        it = store.get_item(item_id)
        if it:
            src, n = fix_graphic_series([it])
            if src and n:
                it2 = store.get_item(item_id)
                log(f"Matched “{it2.get('title')}” on {src}", "sorted", item_id)
    except Exception as e:
        print("[inkwell] comic lookup skipped:", e)


def _series_groups(items):
    groups = {}
    for it in items:
        groups.setdefault(media.series_key(series_query(it)) or f"i{it['id']}", []).append(it)
    return list(groups.values())


def fix_all_graphic():
    """Go through every comic and manga (and comic volumes filed as books), one series at a time."""
    groups = _series_groups(graphic_candidates())
    importers.JOB["total"] = len(groups)
    fixed, unknown = 0, []
    for g in groups:
        importers.JOB["current"] = series_query(g[0])
        try:
            src, n = fix_graphic_series(g)
            fixed += n
            if not src:
                unknown.append(series_query(g[0]))
        except Exception as e:
            print("[inkwell] comic lookup failed for", series_query(g[0]), e)
            importers.JOB["errors"] += 1
        importers.JOB["done"] += 1
        importers.JOB["added"] = fixed
    importers.JOB["message"] = (f"Manga & comics: updated {fixed} volumes in {len(groups)} series"
                                + (f". Not found: {', '.join(unknown[:6])}{'…' if len(unknown) > 6 else ''}" if unknown else ""))


@route("POST", r"/api/graphic/fix-all")
def r_graphic_fix_all(h):
    importers.start_job("Looking up manga & comics", fix_all_graphic)
    h._send(200, {"ok": True})


@route("POST", r"/api/items/(\d+)/graphic")
def r_item_graphic(h, iid):
    """Look up this volume's series (AniList for manga, Hardcover for comics) and fix every volume of it you have."""
    it = store.get_item(int(iid))
    if not it:
        return h._send(404, {"error": "not found"})
    key = media.series_key(series_query(it))
    group = [x for x in graphic_candidates() if media.series_key(series_query(x)) == key] or [it]
    if it["id"] not in [x["id"] for x in group]:
        group.insert(0, it)
    try:
        src, n = fix_graphic_series(group)
    except Exception as e:
        raise ValueError(f"Couldn't reach AniList or Hardcover ({e}).")
    if not src:
        raise ValueError(f"No manga or comic called “{series_query(it)}” was found. Correct the series name and try again.")
    log(f"Looked up “{series_query(it)}” on {src}: {n} of {len(group)} volumes updated", "import", int(iid))
    h._send(200, {"source": src, "changed": n, "volumes": len(group)})


@route("GET", r"/api/films/search")
def r_film_search(h):
    try:
        h._send(200, lookup.film_search(h.query.get("q", "")))
    except Exception as e:
        raise ValueError(f"Couldn't reach Wikipedia ({e}).")


FILM_FIELDS = ("title", "year", "authors", "genre", "fiction", "summary", "series")


@route("POST", r"/api/items/(\d+)/film")
def r_item_film(h, iid):
    """Fill a film's details from the Wikipedia article you picked: title, year, directors, genre, series, synopsis
    and its poster."""
    iid = int(iid)
    it = store.get_item(iid)
    if not it:
        return h._send(404, {"error": "not found"})
    wiki = (h.json_body().get("wiki") or "").strip()
    if not wiki:
        raise ValueError("Pick a film first.")
    try:
        d = lookup.film_details(wiki)
    except LookupError:
        raise
    except Exception as e:
        raise ValueError(f"Couldn't reach Wikipedia ({e}).")
    d["authors"] = d.get("directors") or []
    d["fiction"] = 0 if d.get("genre") == "Documentary" else 1
    upd, kept = fill_from_online(iid, it, d, FILM_FIELDS, set(), d.get("tags") or [],
                                 taxonomy.SCREEN_GENRES + d.get("genres", []) + ["Kaiju"])
    changed = list(upd)
    if d.get("poster"):
        # the poster of the film you picked replaces any the app guessed by itself
        try:
            data = lookup.download(d["poster"])
            if len(data) > 2000:
                name = f"poster_m{iid}.jpg"
                with open(os.path.join(store.COVERS_DIR, name), "wb") as f:
                    f.write(data)
                store.update_item(iid, {"cover_path": name})
                changed.append("poster")
        except Exception as e:
            print("[inkwell] film poster skipped:", e)
    log(f"Filled “{d.get('title')}” from Wikipedia" + (f" ({', '.join(changed)})" if changed else " (nothing new)"), "import", iid)
    h._send(200, {"changed": changed, "kept": kept, "url": d.get("url")})


@route("POST", r"/api/items/(\d+)/hardcover")
def r_item_hardcover(h, iid):
    """Fill a book's details from Hardcover: synopsis, authors, genre, series, year, ISBN (and a cover if it has none).
    It replaces what the app found by itself, keeps anything you typed in yourself, and the fields it sets are kept
    on later re-sorts."""
    iid = int(iid)
    it = store.get_item(iid)
    if not it:
        return h._send(404, {"error": "not found"})
    if not discover.hardcover_on():
        raise ValueError("Add your Hardcover token in Settings → Book catalogue first.")
    try:
        d = discover.hardcover_details(it.get("title") or "", (it.get("authors") or [""])[0], it.get("isbn") or "")
    except (ValueError, LookupError):
        raise
    except Exception as e:
        raise ValueError(f"Couldn't reach Hardcover ({e}).")
    if not d:
        raise ValueError(f"Hardcover has no book called “{it.get('title')}”" + (f" by {it['authors'][0]}" if it.get("authors") else "") +
                         ". If the title is off, correct it and try again.")
    skip = {"title"} if d.get("matched_by") != "isbn" else set()   # matched by title already: keep your spelling of it
    if it.get("isbn"):
        skip.add("isbn")   # your copy's own ISBN beats one picked from Hardcover's list of editions
    tags = [g for g in d.get("genres") or [] if g != d.get("genre")][:4]
    upd, kept = fill_from_online(iid, it, d, HC_FIELDS, skip, tags, d.get("genres") or [])
    cover = False
    if not it.get("has_cover") and d.get("cover"):
        try:
            data = discover._fetch_img(d["cover"])
            with open(os.path.join(store.COVERS_DIR, f"{iid}-c.jpg"), "wb") as f:
                f.write(data)
            store.update_item(iid, {"cover_path": f"{iid}-c.jpg"})
            cover = True
        except Exception as e:
            print("[inkwell] hardcover cover skipped:", e)
    changed = [k for k in upd if k not in ("locked",)] + (["cover"] if cover else [])
    log(f"Filled “{d.get('title') or it.get('title')}” from Hardcover" + (f" ({', '.join(changed)})" if changed else " (nothing new)"), "import", iid)
    h._send(200, {"changed": changed, "kept": kept, "url": d.get("url"), "genres": d.get("genres")})


# ---- annotations
# ---- discover (online) & wishlist
def _online(fn, *a):
    import urllib.error
    try:
        return fn(*a)
    except (ValueError, LookupError):
        raise
    except urllib.error.HTTPError as e:
        print("[inkwell] discover:", e)
        if e.code in (429, 503):
            raise ValueError("The catalogue is busy right now (too many requests). Try again in a minute.") from e
        raise ValueError(f"The catalogue answered with an error ({e.code}). Try again later.") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        print("[inkwell] discover:", e)
        if "timed out" in str(e).lower():
            raise ValueError("The catalogue took too long to answer. Try again.") from e
        raise ValueError("Couldn't reach the book catalogues. Discover needs an internet connection.") from e
    except Exception as e:
        traceback.print_exc()
        raise ValueError(f"Something went wrong looking that up ({type(e).__name__}).") from e


def _cat_years(h):
    """The catalogue department (book, manga, comic, movie, tv) and the span of years asked for, if any."""
    cat = h.query.get("cat", "book")
    cat = cat if cat in media_catalog.CATS else "book"
    yrs = []
    for k in ("from", "to"):
        v = (h.query.get(k) or "").strip()
        yrs.append(int(v) if re.fullmatch(r"\d{4}", v) else None)
    if yrs[0] and yrs[1] and yrs[0] > yrs[1]:
        yrs = [yrs[1], yrs[0]]
    return cat, yrs[0], yrs[1]


@route("GET", r"/api/discover/search")
def r_disc_search(h):
    cat, yf, yt = _cat_years(h)
    if cat == "book":
        return h._send(200, _online(discover.search, h.query.get("q", ""), 30, yf, yt))
    h._send(200, _online(media_catalog.search, cat, h.query.get("q", ""), yf, yt))


@route("GET", r"/api/discover/series")
def r_disc_series(h):
    h._send(200, discover.serve_series())


@route("GET", r"/api/discover/authors")
def r_disc_authors(h):
    h._send(200, discover.serve_authors())


@route("GET", r"/api/news/science")
def r_news_science(h):
    import news
    if h.query.get("fresh"):
        news.forget_feeds()
    h._send(200, news.science())


@route("GET", r"/api/news/article")
def r_news_article(h):
    """A story as text, for reading inside the Gazette."""
    import news
    url = h.query.get("url", "")
    if not re.match(r"^https?://", url):
        raise ValueError("Not a web address.")
    h._send(200, _online(news.article, url))


@route("GET", r"/api/news/local")
def r_news_local(h):
    import news
    if h.query.get("fresh"):
        news.forget_feeds()
    h._send(200, news.local())


@route("POST", r"/api/news/place")
def r_news_place(h):
    import news
    h._send(200, news.set_place(h.json_body()))


@route("GET", r"/api/news/alerts")
def r_news_alerts(h):
    """New events found on the Local desk since a time (for the News badge and the phone's notifications)."""
    import news
    if h.query.get("check"):
        news.check_events()
    h._send(200, {"items": news.alerts_since(h.query.get("since") or 0), "on": bool(store.get_settings().get("news_alerts")), "now": time.time()})


@route("POST", r"/api/news/alerts")
def r_news_alerts_set(h):
    """Switch the event watcher on or off (the phone's Settings toggle)."""
    store.set_settings({"news_alerts": bool(h.json_body().get("on"))})
    h._send(200, {"on": bool(store.get_settings().get("news_alerts")), "now": time.time()})


# ---- web pages saved for 30 days: the app asks before each one is due (delete it, or keep it 30 more days)
DAY = 86400


REMOVED_DIR = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "BabelsLibraryBackups", "Removed articles")


def _put_away(path):
    """A removed page's file is never erased: it goes to the Recycle Bin, or, on a drive that has none (a USB stick:
    Windows would delete it outright), into the "Removed articles" folder. Returns where it went."""
    import ctypes
    import shutil
    drive = os.path.splitdrive(os.path.abspath(path))[0] + "\\"
    if os.name == "nt" and ctypes.windll.kernel32.GetDriveTypeW(drive) == 3:      # a fixed disk: it has a Recycle Bin
        _to_recycle_bin(path)
        return "the Recycle Bin"
    os.makedirs(REMOVED_DIR, exist_ok=True)
    base, ext = os.path.splitext(os.path.basename(path))
    dest, n = os.path.join(REMOVED_DIR, base + ext), 2
    while os.path.exists(dest):
        dest, n = os.path.join(REMOVED_DIR, f"{base} ({n}){ext}"), n + 1
    shutil.move(path, dest)
    return "the Removed articles folder"


def _to_recycle_bin(path):
    """Into the Recycle Bin (so it can still be restored), not erased."""
    if os.name != "nt":
        raise OSError("The Recycle Bin needs Windows")
    import ctypes
    from ctypes import wintypes

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [("hwnd", wintypes.HWND), ("wFunc", ctypes.c_uint), ("pFrom", wintypes.LPCWSTR), ("pTo", wintypes.LPCWSTR),
                    ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", wintypes.BOOL), ("hNameMappings", ctypes.c_void_p),
                    ("lpszProgressTitle", wintypes.LPCWSTR)]
    op = SHFILEOPSTRUCTW(None, 3, os.path.abspath(path) + "\0", None, 0x0040 | 0x0010 | 0x0004 | 0x0400, False, None, None)  # delete; undo; no confirm, no UI, no errors
    if ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op)) != 0:
        raise OSError("Couldn't move it to the Recycle Bin")


@route("GET", r"/api/expiring")
def r_expiring(h):
    soon = time.time() + 3 * DAY
    h._send(200, {"items": [{"id": it["id"], "title": it["title"], "url": it.get("url"), "expires_at": it["expires_at"]}
                            for it in store.list_items() if it.get("expires_at") and it["expires_at"] < soon]})


@route("POST", r"/api/items/(\d+)/expire")
def r_item_expire(h, iid):
    """extend: 30 more days · keep: for good · delete: off the shelf, its file put away (never erased)."""
    it = store.get_item(int(iid))
    if not it:
        return h._send(404, {"error": "Not found"})
    act = h.json_body().get("action")
    if act == "extend":
        store.update_item(it["id"], {"expires_at": max(time.time(), it.get("expires_at") or 0) + 30 * DAY})
    elif act == "keep":
        store.update_item(it["id"], {"expires_at": None})
    elif act == "delete":
        p = store.resolve_file(store.get_item(it["id"], raw=True).get("file_path"))
        went = _put_away(p) if p and os.path.exists(p) else ""
        store.delete_item(it["id"], delete_file=False)
        print(f"[inkwell] Removed (30 days were up): {it['title']} -> {went or 'no file'}")
        return h._send(200, {"ok": True, "went": went})
    else:
        raise ValueError("extend, keep or delete")
    h._send(200, {"ok": True})


@route("POST", r"/api/news/save")
def r_news_save(h):
    """Keep a story: the page is saved into the library as an article (in the background; it takes a few seconds)."""
    body = h.json_body()
    url, days = str(body.get("url") or ""), body.get("days")
    if not re.match(r"^https?://", url):
        raise ValueError("Only web pages can be saved.")
    if DESKTOP is None or not hasattr(DESKTOP, "save_web"):
        raise ValueError("Saving pages needs the Babel's Library window.")

    def save():
        try:
            DESKTOP.save_web(url, days)
        except Exception as e:
            print(f"[inkwell] couldn't save {url}: {e}")
    threading.Thread(target=save, daemon=True).start()
    h._send(200, {"ok": True})


@route("GET", r"/api/media/animated")
def r_media_animated(h):
    h._send(200, media_catalog.library_animated())


@route("GET", r"/api/discover/byauthor")
def r_disc_byauthor(h):
    cat = h.query.get("cat", "book")
    if cat not in ("book", "manga", "comic"):
        raise ValueError("Unknown kind of book.")
    h._send(200, _online(discover.all_by_author, h.query.get("name", ""), cat))


@route("GET", r"/api/discover/browse")
def r_disc_browse(h):
    cat, yf, yt = _cat_years(h)
    if cat == "book":
        return h._send(200, discover.serve_browse(h.query.get("subject", "new"), yf, yt))
    h._send(200, media_catalog.serve_browse(cat, h.query.get("subject", "trending"), yf, yt))


@route("POST", r"/api/discover/restock")
def r_disc_restock(h):
    cat, yf, yt = _cat_years(h)
    if cat == "book":
        return h._send(200, _online(discover.restock, h.query.get("subject", "new"), yf, yt))
    h._send(200, _online(media_catalog.restock, cat, h.query.get("subject", "trending"), yf, yt))


@route("GET", r"/api/discover/subjects")
def r_disc_subjects(h):
    cat, _, _ = _cat_years(h)
    if cat == "book":
        return h._send(200, [{"key": k, "label": l} for k, l in discover.SUBJECTS])
    h._send(200, media_catalog.subjects(cat))


@route("GET", r"/api/discover/promos")
def r_disc_promos(h):
    cat, _, _ = _cat_years(h)
    h._send(200, discover.serve_promos() if cat == "book" else media_catalog.serve_promos(cat))


@route("GET", r"/api/discover/cover")
def r_disc_cover(h):
    q = h.query
    try:
        data = discover.cover_quick(q.get("u", ""), q.get("isbn", ""), q.get("t", ""), q.get("a", ""))
    except Exception:
        return h._send(404, b"", "text/plain", {"Cache-Control": "no-store"})
    h._send(200, data, "image/jpeg", {"Cache-Control": "max-age=2592000"})


@route("POST", r"/api/items/(\d+)/own")
def r_item_own(h, iid):
    r = discover.mark_owned(int(iid), sys.modules[__name__])
    it = store.get_item(int(iid))
    log(f"“{it.get('title')}” is on your shelf (physical copy)" + (", linked to your journal" if r["linked"] else ""), "import", int(iid))
    h._send(200, r)


@route("GET", r"/api/discover/info")
def r_disc_info(h):
    q = h.query
    cat, _, _ = _cat_years(h)
    if cat == "animation":
        return h._send(200, _online(media_catalog.animation_info, q.get("title", ""), q.get("wiki", ""), q.get("al", ""), q.get("form", "tv")))
    if cat != "book":
        return h._send(200, _online(media_catalog.info, cat, q.get("title", ""), q.get("wiki", ""), q.get("al", "")))
    h._send(200, _online(discover.info, q.get("title", ""), q.get("author", ""), q.get("wiki", ""), q.get("isbn", ""), q.get("link", "")))


@route("GET", r"/api/discover/reviews")
def r_disc_reviews(h):
    q = h.query
    cat, _, _ = _cat_years(h)
    if cat in ("manga", "movie", "tv"):
        return h._send(200, {})          # their ratings and reviews come with "More info" (AniList) or aren't available
    h._send(200, discover.reviews(q.get("title", ""), q.get("author", ""), q.get("isbn", "")))


@route("POST", r"/api/discover/test-keys")
def r_disc_test(h):
    h._send(200, discover.test_keys())


@route("POST", r"/api/discover/ignore")
def r_disc_ignore(h):
    d = h.json_body()
    h._send(200, discover.ignore(d.get("title") or "", bool(d.get("undo"))))


@route("GET", r"/api/discover/ignored")
def r_disc_ignored(h):
    h._send(200, store.get_settings().get("discover_ignored") or [])


@route("POST", r"/api/wishlist")
def r_wishlist_add(h):
    iid = discover.add_wanted(h.json_body(), sys.modules[__name__])
    h._send(200, {"id": iid})


# ---- reading log & review journals
@route("GET", r"/api/log")
def r_log_list(h):
    h._send(200, journal.list_log())


@route("POST", r"/api/log")
def r_log_create(h):
    d = h.json_body()
    lid = journal.create_log(d)
    if d.get("body"):
        journal.add_entry(lid, d["body"])
    h._send(200, journal.get_log(lid))


@route("GET", r"/api/log/(\d+)")
def r_log_get(h, lid):
    r = journal.get_log(int(lid))
    if not r:
        return h._send(404, {"error": "Not found"})
    h._send(200, r)


@route("PATCH", r"/api/log/(\d+)")
def r_log_update(h, lid):
    journal.update_log(int(lid), h.json_body())
    h._send(200, journal.get_log(int(lid)))


@route("DELETE", r"/api/log/(\d+)")
def r_log_delete(h, lid):
    journal.delete_log(int(lid))
    h._send(200, {"ok": True})


@route("POST", r"/api/log/(\d+)/journal")
def r_journal_add(h, lid):
    d = h.json_body()
    journal.add_entry(int(lid), d.get("body"))
    h._send(200, journal.get_log(int(lid)))


@route("PATCH", r"/api/journal/(\d+)")
def r_journal_update(h, eid):
    journal.update_entry(int(eid), h.json_body().get("body"))
    h._send(200, {"ok": True})


@route("DELETE", r"/api/journal/(\d+)")
def r_journal_delete(h, eid):
    journal.delete_entry(int(eid))
    h._send(200, {"ok": True})


# ---- journal photos: screen snips kept as figures beside a journal's details (Fig. 1, Fig. 2...). They live as PNG
#      files in library_data/journal_photos/<log id>/ with an index.json; numbers never shift, so "Fig. 2" in an entry
#      always means the same picture. Removing one moves it to a "removed" folder rather than deleting it.
PHOTO_DIR = os.path.join(store.DATA_DIR, "journal_photos")
_photo_lock = threading.Lock()


def _photos(lid):
    folder = os.path.join(PHOTO_DIR, str(int(lid)))
    try:
        with open(os.path.join(folder, "index.json"), encoding="utf-8") as f:
            return folder, json.load(f)
    except (OSError, ValueError):
        return folder, []


def _save_photos(folder, items):
    os.makedirs(folder, exist_ok=True)
    tmp = os.path.join(folder, "index.json.part")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(items, f)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, os.path.join(folder, "index.json"))


@route("GET", r"/api/log/(\d+)/photos")
def r_photos(h, lid):
    h._send(200, _photos(lid)[1])


@route("POST", r"/api/log/(\d+)/photos")
def r_photo_add(h, lid):
    import base64
    d = h.json_body()
    m = re.match(r"^data:image/(png|jpeg);base64,(.+)$", d.get("data") or "", re.S)
    if not m:
        return h._send(400, {"error": "Not a picture"})
    raw = base64.b64decode(m.group(2))
    if len(raw) > 25 * 1024 * 1024:
        return h._send(400, {"error": "That picture is too big"})
    with _photo_lock:
        folder, items = _photos(lid)
        n = max([p["n"] for p in items] + [0]) + 1
        os.makedirs(folder, exist_ok=True)
        name = f"{n:03d}.{'png' if m.group(1) == 'png' else 'jpg'}"
        with open(os.path.join(folder, name), "wb") as f:
            f.write(raw)
            f.flush()
            os.fsync(f.fileno())
        items.append({"n": n, "file": name, "caption": str(d.get("caption") or "")[:200], "w": d.get("w"), "h": d.get("h"), "at": time.time()})
        _save_photos(folder, items)
    h._send(200, items)


@route("PATCH", r"/api/log/(\d+)/photos/(\d+)")
def r_photo_edit(h, lid, n):
    d = h.json_body()
    with _photo_lock:
        folder, items = _photos(lid)
        for p in items:
            if p["n"] == int(n):
                p["caption"] = str(d.get("caption") or "")[:200]
        _save_photos(folder, items)
    h._send(200, items)


@route("DELETE", r"/api/log/(\d+)/photos/(\d+)")
def r_photo_remove(h, lid, n):
    with _photo_lock:
        folder, items = _photos(lid)
        gone = [p for p in items if p["n"] == int(n)]
        for p in gone:
            src = os.path.join(folder, p["file"])
            if os.path.exists(src):
                os.makedirs(os.path.join(folder, "removed"), exist_ok=True)
                os.replace(src, os.path.join(folder, "removed", f"{int(time.time())}-{p['file']}"))
        _save_photos(folder, [p for p in items if p["n"] != int(n)])
    h._send(200, _photos(lid)[1])


@route("GET", r"/api/log/(\d+)/photos/(\d+)\.img")
def r_photo_file(h, lid, n):
    folder, items = _photos(lid)
    p = next((p for p in items if p["n"] == int(n)), None)
    full = p and os.path.join(folder, p["file"])
    if not full or not os.path.exists(full):
        return h._send(404, {"error": "Not found"})
    h.send_file(full, "image/png" if full.endswith(".png") else "image/jpeg")


@route("POST", r"/api/desktop/snap")
def r_desktop_snap(h):
    """A picture of the library window as it looks right now (for a journal photo; the page picks the area)."""
    if DESKTOP is None or not hasattr(DESKTOP, "snap"):
        return h._send(400, {"error": "Screen snips work in the desktop app."})
    h._send(200, {"data": DESKTOP.snap()})


# ---- the Bulletin's dailies: Wikipedia's picture of the day and featured article, and Wikiquote's quote of the day
#      (fetched once a day; nothing shown when there's no internet)
_potd = {"day": "", "data": None, "tried": 0.0}


def _quote_of_the_day(when):
    """Wikiquote's quote of the day: {text, by, page}."""
    page = "Wikiquote:Quote_of_the_day/" + time.strftime("%B_", when) + str(when.tm_mday) + time.strftime(",_%Y", when)
    req = urllib.request.Request("https://en.wikiquote.org/w/api.php?" + urllib.parse.urlencode({"action": "parse", "page": page, "prop": "text", "format": "json", "formatversion": 2}),
                                 headers={"User-Agent": "BabelsLibrary/1.0 (personal library app)"})
    t = json.loads(urllib.request.urlopen(req, timeout=15).read())["parse"]["text"]
    t = re.sub(r"<!--.*?-->", "", t, flags=re.S)
    t = re.sub(r"</?(a|span|i|b|em|strong|abbr)(?=[ >])[^>]*>", "", t)          # (inline tags: no gap; the rest end a line)
    text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", t))).strip()
    m = re.search(r"“\s*(.+?)\s*”\s*[—–]\s*(.+?)\s*$", text, re.S)
    if not m:
        return None
    q = m.group(1)
    by = m.group(2).strip()
    return {"text": q[:900], "by": by[:120], "page": "https://en.wikiquote.org/wiki/" + urllib.parse.quote(by.replace(" ", "_"))}


def _article_intro(title):
    """The paragraphs before an article's first heading, as plain text."""
    q = urllib.parse.urlencode({"action": "query", "prop": "extracts", "exintro": 1, "explaintext": 1, "redirects": 1,
                                "format": "json", "formatversion": 2, "titles": title})
    req = urllib.request.Request("https://en.wikipedia.org/w/api.php?" + q, headers={"User-Agent": "BabelsLibrary/1.0 (personal library app)"})
    pages = json.loads(urllib.request.urlopen(req, timeout=15).read()).get("query", {}).get("pages") or []
    text = (pages[0].get("extract") or "") if pages else ""
    out, n = [], 0
    for p in (x.strip() for x in text.split("\n")):
        if not p:
            continue
        if n + len(p) > 6000:
            break
        out.append(p)
        n += len(p)
    return out


@route("GET", r"/api/potd")
def r_potd(h):
    day = time.strftime("%Y/%m/%d")
    if _potd["day"] != day and time.time() - _potd["tried"] > 600:      # (after a failure, try again in ten minutes)
        _potd["tried"] = time.time()
        try:
            req = urllib.request.Request(f"https://api.wikimedia.org/feed/v1/wikipedia/en/featured/{day}",
                                         headers={"User-Agent": "BabelsLibrary/1.0 (personal library app)"})
            feed = json.loads(urllib.request.urlopen(req, timeout=15).read())
            img = feed.get("image") or {}
            thumb = (img.get("thumbnail") or {}).get("source") or ""
            strip = lambda s: re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html.unescape(s or ""))).strip()
            data = {}
            if thumb:
                data.update({"img": thumb, "title": re.sub(r"^File:|\.\w+$", "", img.get("title") or ""),
                    "desc": strip((img.get("description") or {}).get("text"))[:400], "artist": strip((img.get("artist") or {}).get("text"))[:120],
                    "license": (img.get("license") or {}).get("type") or "", "page": img.get("file_page") or ""})
            a = feed.get("tfa") or {}
            if a.get("extract"):
                thumb = (a.get("thumbnail") or {}).get("source") or ""
                data["article"] = {"title": (a.get("titles") or {}).get("normalized") or a.get("title") or "", "about": a.get("description") or "",
                                   "text": a["extract"][:1400], "img": thumb,
                                   "page": ((a.get("content_urls") or {}).get("mobile") or {}).get("page") or ""}
                try:            # the computer has room for the article's whole introduction, not just its first paragraph
                    data["article"]["paras"] = _article_intro(a.get("title") or data["article"]["title"])
                except Exception as e:
                    print("[inkwell] no article introduction:", e)
            try:
                data["quote"] = _quote_of_the_day(time.localtime())
            except Exception as e:
                print("[inkwell] no quote of the day:", e)
            if data:
                _potd.update(day=day, data=data)
        except Exception as e:
            print("[inkwell] no picture of the day:", e)
    h._send(200, _potd["data"] if _potd["day"] == day else {})


@route("GET", r"/api/items/(\d+)/log")
def r_item_log(h, iid):
    it = store.get_item(int(iid))
    if not it:
        return h._send(404, {"error": "Not found"})
    r = journal.log_for_item(it)
    h._send(200, journal.get_log(r["id"]) if r else None)


@route("POST", r"/api/items/(\d+)/log")
def r_item_log_make(h, iid):
    """Start (or update) this item's log row: {finished, score, body}."""
    it = store.get_item(int(iid))
    if not it:
        return h._send(404, {"error": "Not found"})
    d = h.json_body()
    lid = journal.ensure_log_for_item(it)
    upd = {k: d[k] for k in ("finished", "score", "link", "kind", "title", "status") if k in d}
    if upd:
        journal.update_log(lid, upd)
    if d.get("body"):
        journal.add_entry(lid, d["body"])
    h._send(200, journal.get_log(lid))


@route("POST", r"/api/log/import-obsidian")
def r_log_import(h):
    folder = h.json_body().get("folder") or ""
    st = journal.import_obsidian(folder)
    store.set_settings({"obsidian_folder": folder})
    h._send(200, st)


@route("POST", r"/api/open-url")
def r_open_url(h):
    url = h.json_body().get("url") or ""
    if not re.match(r"^https?://", url):
        raise ValueError("Only web links can be opened.")
    webbrowser.open(url)
    h._send(200, {"ok": True})


def _public_host(host):
    import ipaddress
    import socket
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return None   # can't look the name up: probably offline
    try:
        for info in infos:
            ip = ipaddress.ip_address(info[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
                return False
        return True
    except ValueError:
        return False


PREVIEW_PAGE = """<!doctype html><meta charset=utf-8><style>body{font:15px/1.5 system-ui,sans-serif;color:#444;display:grid;place-items:center;height:90vh;margin:0;text-align:center;padding:0 20px}</style><div>%s</div>"""


@route("GET", r"/api/webpreview")
def r_webpreview(h):
    """A web page shown inside Babel's Library: fetched here, with its scripts removed and links kept inside the preview."""
    url = h.query.get("url") or ""
    if not re.match(r"^https?://", url):
        return h._send(400, PREVIEW_PAGE % "That isn't a web link.", "text/html; charset=utf-8")
    # Wikipedia's mobile pages read much better in a narrow panel
    url = re.sub(r"^https?://([a-z\-]+)\.wikipedia\.org/", r"https://\1.m.wikipedia.org/", url)
    host = urllib.parse.urlparse(url).hostname or ""
    ok = _public_host(host)
    if ok is None:
        return h._send(200, PREVIEW_PAGE % "Couldn't reach the site. Previews need an internet connection.", "text/html; charset=utf-8")
    if not ok:
        return h._send(400, PREVIEW_PAGE % "Can't preview that address.", "text/html; charset=utf-8")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36 BabelsLibrary/1.0",
                                                   "Accept": "text/html,application/xhtml+xml", "Accept-Language": "en"})
        with urllib.request.urlopen(req, timeout=12) as r:
            final = r.geturl()
            ctype = r.headers.get("Content-Type", "")
            data = r.read(6 * 1024 * 1024)
    except Exception as e:
        return h._send(200, PREVIEW_PAGE % ("Couldn't load the page. Are you online?<br><small>" + html.escape(str(e))[:200] + "</small>"), "text/html; charset=utf-8")
    if "html" not in ctype:
        return h._send(200, PREVIEW_PAGE % "This link isn't a web page. Open it in your browser instead.", "text/html; charset=utf-8")
    m = re.search(r"charset=([\w-]+)", ctype)
    page = data.decode(m.group(1) if m else "utf-8", errors="replace")
    page = re.sub(r"(?is)<script\b.*?</script>", "", page)
    page = re.sub(r"(?is)<noscript\b[^>]*>(.*?)</noscript>", r"\1", page)   # the no-JavaScript version of the page
    page = re.sub(r"(?is)<meta[^>]+http-equiv=[\"']?(?:refresh|content-security-policy)[^>]*>", "", page)
    page = re.sub(r"(?is)<base\b[^>]*>", "", page)
    # pictures that normally wait for JavaScript to load them (Wikipedia's mobile pages, lazy-loading sites)
    def lazy_span(mm):
        tag = mm.group(0)
        src = re.search(r'data-src="([^"]+)"', tag)
        if not src:
            return tag
        w = re.search(r'data-width="(\d+)"', tag)
        hh = re.search(r'data-height="(\d+)"', tag)
        return f'<img src="{src.group(1)}"' + (f' width="{w.group(1)}"' if w else "") + (f' height="{hh.group(1)}"' if hh else "") + ' style="max-width:100%;height:auto">'
    page = re.sub(r'(?is)<span\b[^>]*class="[^"]*lazy-image-placeholder[^"]*"[^>]*>(?:\s*&nbsp;\s*)?</span>', lazy_span, page)
    page = re.sub(r'(?is)<img\b([^>]*?)\sdata-src="([^"]+)"', lambda mm: f'<img{mm.group(1)} src="{mm.group(2)}"' if " src=" not in mm.group(1) else mm.group(0), page)

    # links must point back here in full: the page's <base> points at the real site
    me = f"http://{(getattr(h, 'headers', None) or {}).get('Host') or f'127.0.0.1:{PORT}'}/api/webpreview?url="

    def link(mm):
        href = html.unescape(mm.group(2))
        if href.startswith(("javascript:", "mailto:", "tel:")):
            return mm.group(0)
        absu = urllib.parse.urljoin(final, href)
        if not absu.startswith("http"):
            return mm.group(0)
        frag = ""
        if "#" in absu:
            absu, frag = absu.split("#", 1)
            frag = "#" + frag
        return f'{mm.group(1)}"{me}{html.escape(urllib.parse.quote(absu, safe=""))}{html.escape(frag)}"'
    page = re.sub(r'(?is)(<a\b[^>]*?\bhref=)["\']([^"\']*)["\']', link, page)
    head = f'<base href="{html.escape(final)}"><style>html{{overflow-x:hidden}}</style>'
    page = re.sub(r"(?is)<head\b[^>]*>", lambda mm: mm.group(0) + head, page, count=1) if re.search(r"(?is)<head\b", page) else head + page
    h._send(200, page, "text/html; charset=utf-8",
            {"Content-Security-Policy": "script-src 'none'; object-src 'none'; frame-ancestors 'self'", "X-Preview-Url": final})


@route("GET", r"/api/items/(\d+)/annotations")
def r_anns(h, iid):
    h._send(200, store.list_annotations(int(iid)))


@route("POST", r"/api/items/(\d+)/annotations")
def r_ann_create(h, iid):
    h._send(200, store.create_annotation(int(iid), h.json_body()))


@route("PATCH", r"/api/annotations/(\d+)")
def r_ann_update(h, aid):
    h._send(200, store.update_annotation(int(aid), h.json_body()))


@route("DELETE", r"/api/annotations/(\d+)")
def r_ann_delete(h, aid):
    store.delete_annotation(int(aid))
    h._send(200, {"ok": True})


@route("GET", r"/api/export/annotations")
def r_export(h):
    ids = [int(x) for x in h.query.get("items", "").split(",") if x.strip().isdigit()] or None
    fmt = h.query.get("format", "md")
    if fmt == "json":
        items = {i["id"]: i for i in store.list_items()}
        data = [{**a, "item_title": items.get(a["item_id"], {}).get("title")} for a in store.list_annotations() if not ids or a["item_id"] in ids]
        return h._send(200, json.dumps(data, indent=2), "application/json",
                       {"Content-Disposition": 'attachment; filename="inkwell-annotations.json"'})
    h._send(200, annotations_markdown(ids), "text/markdown; charset=utf-8",
            {"Content-Disposition": 'attachment; filename="inkwell-annotations.md"'})


@route("GET", r"/api/export/citations")
def r_export_cite(h):
    style = h.query.get("style", "APA (7th ed.)")
    lines = []
    for it in sorted(store.list_items(), key=lambda i: (i.get("authors") or [i.get("title") or ""])[0]):
        c = cite.all_citations(it).get(style)
        if c:
            lines.append(c["text"])
    h._send(200, "\n\n".join(lines), "text/plain; charset=utf-8",
            {"Content-Disposition": 'attachment; filename="inkwell-bibliography.txt"'})


# ---- lookup, settings, status
@route("POST", r"/api/lookup")
def r_lookup(h):
    h._send(200, lookup.lookup(h.json_body().get("query", "")))


@route("GET", r"/api/settings")
def r_settings(h):
    s = store.get_settings()
    s["library_folder"] = files.library_root()
    h._send(200, s)


@route("POST", r"/api/settings")
def r_settings_set(h):
    body = h.json_body()
    body.pop("library_folder", None)  # changed through /api/library/switch
    old = store.get_settings()
    s = store.set_settings(body)
    if any(old.get(k) != s.get(k) for k in ("nyt_key", "hardcover_token")):
        discover.forget(("promos4",))      # new sources for Hot off the press
    if s.get("watch_folder"):
        try:
            os.makedirs(os.path.expanduser(s["watch_folder"]), exist_ok=True)
        except OSError:
            pass
    h._send(200, s)


@route("GET", r"/api/ping")
def r_ping(h):
    """Touches nothing on the data drive, so it answers even while that drive is unplugged."""
    h._send(200, {"ok": True, "drive_ok": store.drive_ok(), "data_dir": store.DATA_DIR})


@route("GET", r"/api/status")
def r_status(h):
    s = store.get_settings()
    since = float(h.query.get("since", 0) or 0)
    with _activity_lock:
        act = [a for a in activity if a["t"] > since]
    h._send(200, {
        "ollama_models": ai.ollama_available(s["ollama_url"]),
        "watch_folder": os.path.expanduser(s["watch_folder"]),
        "watch_enabled": s["watch_enabled"],
        "watch_last_scan": watcher.last_scan,
        "watch_error": watcher.error,
        "analyzing": store.count_status("analyzing"),
        "library_folder": files.library_root(),
        "app_root": store.ROOT,
        "audiobook": {k: audiobook.STATE.get(k) for k in ("running", "item", "title", "chapter", "done", "total", "setup", "error")},
        "job": importers.JOB,
        "activity": act,
        "now": time.time(),
    })


@route("POST", r"/api/open-inbox")
def r_open_inbox(h):
    folder = os.path.expanduser(store.get_settings()["watch_folder"])
    os.makedirs(folder, exist_ok=True)
    try:
        if sys.platform == "darwin":
            os.system(f'open "{folder}"')
        elif os.name == "nt":
            os.startfile(folder)  # type: ignore[attr-defined]
        else:
            os.system(f'xdg-open "{folder}" >/dev/null 2>&1 &')
    except Exception:
        pass
    h._send(200, {"ok": True, "folder": folder})


@route("POST", r"/api/desktop/open-main")
def r_desk_open(h):
    d = h.json_body()
    if DESKTOP is None:
        return h._send(200, {"ok": False, "mode": "browser"})
    threading.Thread(target=DESKTOP.open_main, kwargs={"read_id": d.get("read"), "fullscreen": d.get("fullscreen", True)}, daemon=True).start()
    h._send(200, {"ok": True})


@route("POST", r"/api/desktop/reader")
def r_desk_reader(h):
    """Widget mode: open (or close / full-screen) the separate reader window."""
    d = h.json_body()
    if DESKTOP is None or not hasattr(DESKTOP, "open_reader"):
        return h._send(200, {"ok": False, "mode": "browser"})
    act = d.get("action", "open")
    fn = {"open": lambda: DESKTOP.open_reader(d.get("id")), "close": DESKTOP.close_reader,
          "fullscreen": getattr(DESKTOP, "toggle_reader_fullscreen", lambda: None)}.get(act)
    if fn:
        threading.Thread(target=fn, daemon=True).start()
    h._send(200, {"ok": True})


@route("POST", r"/api/desktop/web")
def r_desk_web(h):
    """A web page that needs a real browser (manga readers): its own app window, or the web browser without one."""
    d = h.json_body()
    url = d.get("url") or ""
    if not re.match(r"^https?://", url):
        raise ValueError("Only web links can be opened.")
    if DESKTOP is None or not hasattr(DESKTOP, "open_web"):
        webbrowser.open(url)
        return h._send(200, {"ok": True, "where": "browser"})
    threading.Thread(target=DESKTOP.open_web, args=(url, str(d.get("title") or "")[:80]), daemon=True).start()
    h._send(200, {"ok": True, "where": "window"})


@route("GET", r"/api/phone")
def r_phone(h):
    import phonesync
    h._send(200, phonesync.status())


@route("POST", r"/api/phone/code")
def r_phone_code(h):
    import phonesync
    h._send(200, {"code": phonesync.new_code(), "expires_in": 600, **phonesync.status()})


@route("POST", r"/api/phone/send/(\d+)")
def r_phone_send(h, iid):
    import phonesync
    it = store.get_item(int(iid))
    if not it or not it.get("has_file"):
        raise ValueError("This item has no file to send.")
    n = phonesync.queue_send(int(iid))
    if not n:
        raise ValueError("No phone is paired yet. Pair one in Settings → Phone.")
    h._send(200, {"ok": True, "phones": n})


@route("DELETE", r"/api/phone/devices/([\w-]+)")
def r_phone_forget(h, dev):
    import phonesync
    phonesync.remove_device(dev)
    h._send(200, phonesync.status())


@route("POST", r"/api/phone/remote")
def r_phone_remote(h):
    import phonesync
    on = bool(h.json_body().get("on"))
    store.set_settings({"phone_remote": on})
    threading.Thread(target=phonesync.start_tunnel if on else phonesync.stop_tunnel, daemon=True).start()
    h._send(200, phonesync.status())


# ---- the browser window: history and saved passwords (browser.py). Every call needs the X-Babel header: pages
# from other sites can't send it (that would need permission this server never gives), so they can't reach these.
def _browser_guard(h):
    if h.headers.get("X-Babel") != "1":
        raise ValueError("forbidden")


@route("GET", r"/api/discover/fresh")
def r_disc_fresh(h):
    """When the catalogue's shelves last got new titles (the Discover button lights up for it)."""
    h._send(200, {"updated_at": discover.shelves_updated_at()})


@route("GET", r"/api/browser/history")
def r_br_hist(h):
    import browser
    _browser_guard(h)
    h._send(200, {"items": browser.history(h.query.get("q", ""), int(h.query.get("limit") or 300), h.query.get("before"))})


@route("DELETE", r"/api/browser/history")
def r_br_hist_del(h):
    import browser
    _browser_guard(h)
    b = h.json_body()
    browser.forget_history(b.get("ids"), b.get("since"))
    h._send(200, {"ok": True})


@route("GET", r"/api/browser/start")
def r_br_start(h):
    import browser
    _browser_guard(h)
    h._send(200, {"top": browser.top_sites(), "bookmarks": browser.bookmarks(), "recent": browser.history(limit=8), "search": browser.pref("search", "duckduckgo"),
                  "engines": {k: v[0] for k, v in browser.SEARCH.items()}, "logins": len(browser.logins())})


@route("GET", r"/api/browser/bookmarks")
def r_br_bm(h):
    import browser
    _browser_guard(h)
    h._send(200, {"items": browser.bookmarks()})


@route("POST", r"/api/browser/bookmarks")
def r_br_bm_add(h):
    import browser
    _browser_guard(h)
    b = h.json_body()
    browser.add_bookmark(str(b.get("url") or ""), str(b.get("title") or ""))
    h._send(200, {"items": browser.bookmarks()})


@route("DELETE", r"/api/browser/bookmarks")
def r_br_bm_del(h):
    import browser
    _browser_guard(h)
    b = h.json_body()
    browser.remove_bookmark(b.get("url"), b.get("id"))
    h._send(200, {"items": browser.bookmarks()})


@route("POST", r"/api/browser/prefs")
def r_br_prefs(h):
    import browser
    _browser_guard(h)
    b = h.json_body()
    if b.get("search") in browser.SEARCH:
        browser.set_pref("search", b["search"])
    h._send(200, {"ok": True})


@route("GET", r"/api/browser/logins")
def r_br_logins(h):
    import browser
    _browser_guard(h)
    h._send(200, {"items": browser.logins(h.query.get("q", ""))})


@route("GET", r"/api/browser/logins/(\d+)/password")
def r_br_reveal(h, lid):
    import browser
    _browser_guard(h)
    h._send(200, {"password": browser.reveal(int(lid))})


@route("POST", r"/api/browser/logins")
def r_br_save(h):
    import browser
    _browser_guard(h)
    b = h.json_body()
    lid = browser.save_login(b.get("url", ""), b.get("username", ""), b.get("password", ""), b.get("note", ""), b.get("id"))
    h._send(200, {"id": lid})


@route("DELETE", r"/api/browser/logins/(\d+)")
def r_br_del(h, lid):
    import browser
    _browser_guard(h)
    browser.delete_login(int(lid))
    h._send(200, {"ok": True})


@route("POST", r"/api/browser/import")
def r_br_import(h):
    import browser
    _browser_guard(h)
    r = browser.import_csv(h.json_body().get("csv", ""))
    log(f"Imported passwords: {r['added']} added, {r['updated']} updated, {r['skipped']} skipped", "import")
    h._send(200, r)


@route("GET", r"/browser-go")
def r_br_go(h):
    """The start page's search box: an address goes there, words to DuckDuckGo (or Wikipedia with w=1)."""
    import browser
    url = browser.to_url(h.query.get("q", ""), wiki=h.query.get("w") == "1") or "/browser.html"
    h.send_response(302)
    h.send_header("Location", url)
    h.send_header("Content-Length", "0")
    h.end_headers()


@route("POST", r"/api/browser/view")
def r_br_view(h):
    """The library page's browser bar: place/hide the website view, go somewhere, back, forward, fill a password..."""
    _browser_guard(h)
    if DESKTOP is None or not hasattr(DESKTOP, "browser_view"):
        return h._send(200, {"ok": False})
    DESKTOP.browser_view(h.json_body())
    h._send(200, {"ok": True})


@route("POST", r"/api/browser/open")
def r_br_open(h):
    import browser
    _browser_guard(h)
    url = browser.to_url(h.json_body().get("url", "")) or f"http://localhost:{PORT}/browser.html"
    if DESKTOP is None or not hasattr(DESKTOP, "open_web"):
        webbrowser.open(url)
        return h._send(200, {"ok": True, "where": "browser"})
    threading.Thread(target=DESKTOP.open_web, args=(url, ""), daemon=True).start()
    h._send(200, {"ok": True, "where": "window"})


@route("GET", r"/api/adblock")
def r_adblock(h):
    import adblock
    h._send(200, adblock.status())


@route("POST", r"/api/desktop/fullscreen")
def r_desk_fs(h):
    if DESKTOP is not None:
        threading.Thread(target=DESKTOP.toggle_fullscreen, daemon=True).start()
    h._send(200, {"ok": DESKTOP is not None})


# ---- start with Windows (like Firefox's option): an entry in your sign-in list (HKCU ... Run). It runs a tiny
# launcher that waits for the library's drive (a USB drive may come up after sign-in) and then opens the app.
RUN_KEY, RUN_NAME = r"Software\Microsoft\Windows\CurrentVersion\Run", "BabelsLibrary"
LAUNCHER = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "BabelsLibrary", "start_babel.pyw")


def _startup_on():
    if os.name != "nt":
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            return bool(winreg.QueryValueEx(k, RUN_NAME)[0])
    except OSError:
        return False


@route("GET", r"/api/desktop/startup")
def r_startup_get(h):
    h._send(200, {"on": _startup_on()})


@route("POST", r"/api/desktop/startup")
def r_startup_set(h):
    if os.name != "nt":
        raise ValueError("Starting with the computer needs Windows")
    import winreg
    on = bool(h.json_body().get("on"))
    if on == _startup_on():
        return h._send(200, {"on": on})
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if on:
            app = os.path.join(os.path.dirname(os.path.abspath(__file__)), "desktop.py")
            pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
            os.makedirs(os.path.dirname(LAUNCHER), exist_ok=True)
            with open(LAUNCHER, "w", encoding="utf-8") as f:
                f.write("\n".join([
                    "# Starts Babel's Library when Windows starts (its drive may take a moment to appear).",
                    "import os, subprocess, sys, time",
                    f"APP = {app!r}",
                    "for _ in range(90):",
                    "    if os.path.exists(APP):",
                    "        subprocess.Popen([sys.executable, APP], cwd=os.path.dirname(APP))",
                    "        break",
                    "    time.sleep(2)", ""]))
            winreg.SetValueEx(k, RUN_NAME, 0, winreg.REG_SZ, f'"{pyw}" "{LAUNCHER}"')
        else:
            try:
                winreg.DeleteValue(k, RUN_NAME)
            except OSError:
                pass
    h._send(200, {"on": _startup_on()})


@route("POST", r"/api/desktop/widget")
def r_desk_widget(h):
    d = h.json_body()
    if DESKTOP is None:
        return h._send(200, {"ok": False})
    threading.Thread(target=DESKTOP.widget_action, args=(d.get("action"), d.get("value")), daemon=True).start()
    h._send(200, {"ok": True})


@route("GET", r"/api/desktop")
def r_desk_info(h):
    h._send(200, {"mode": getattr(DESKTOP, "mode", "browser"), "fullscreen": bool(getattr(DESKTOP, "_fs", False))})



# ---- folders & bulk imports
def pick_folder_dialog(title="Choose a folder"):
    if DESKTOP is not None and hasattr(DESKTOP, "pick_folder"):
        return DESKTOP.pick_folder()
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        p = filedialog.askdirectory(title=title)
        root.destroy()
        return p or None
    except Exception as e:
        raise ValueError("No folder picker is available here. Type the folder path instead.") from e


@route("POST", r"/api/pick-folder")
def r_pick(h):
    h._send(200, {"path": pick_folder_dialog(h.json_body().get("title") or "Choose a folder")})


@route("POST", r"/api/scan/preview")
def r_scan_preview(h):
    folder = h.json_body().get("folder", "")
    if devices.is_device_path(folder):
        return h._send(200, devices.preview(folder))
    h._send(200, importers.scan_preview(folder))


@route("POST", r"/api/devices/browse")
def r_devices_browse(h):
    h._send(200, {"folders": devices.browse(h.json_body().get("path") or "")})


@route("POST", r"/api/scan")
def r_scan(h):
    d = h.json_body()
    folder = os.path.expanduser(d.get("folder", ""))
    if devices.is_device_path(folder):
        importers.start_job("Copying from your device", devices.import_from, folder)
        return h._send(200, {"ok": True})
    if not os.path.isdir(folder):
        raise ValueError("That folder doesn't exist.")
    importers.start_job("Folder scan", importers.scan_folder, folder, d.get("move", True) is not False)
    h._send(200, {"ok": True})


@route("POST", r"/api/import/(zotero|calibre)/preview")
def r_import_preview(h, src):
    d = h.json_body()
    s = store.get_settings()
    folder = d.get("folder") or s[src + "_dir"]
    h._send(200, (importers.zotero_preview if src == "zotero" else importers.calibre_preview)(folder))


@route("POST", r"/api/import/(zotero|calibre)")
def r_import(h, src):
    d = h.json_body()
    folder = d.get("folder") or store.get_settings()[src + "_dir"]
    store.set_settings({src + "_dir": folder})
    fn = importers.zotero_import if src == "zotero" else importers.calibre_import
    importers.start_job("Zotero import" if src == "zotero" else "Calibre import", fn, folder, bool(d.get("download_oa")), d.get("move", True) is not False)
    h._send(200, {"ok": True})


@route("POST", r"/api/items/(\d+)/download")
def r_download(h, iid):
    threading.Thread(target=download_open_access, args=(int(iid),), daemon=True).start()
    h._send(200, {"ok": True})


@route("POST", r"/api/items/(\d+)/comicinfo")
def r_comicinfo(h, iid):
    xml = h.raw_body().decode("utf-8", "ignore")
    ci = comics.parse_comicinfo(xml) if xml.strip() else {}
    threading.Thread(target=analyze_item, args=(int(iid), True), kwargs={"comicinfo": ci}, daemon=True).start()
    h._send(200, {"ok": True})


@route("POST", r"/api/reveal")
def r_reveal(h):
    d = h.json_body()
    target = files.library_root()
    if d.get("id"):
        raw = store.get_item(int(d["id"]), raw=True)
        target = store.resolve_file(raw.get("file_path")) if raw else target
    try:
        if os.name == "nt":
            import subprocess
            if os.path.isfile(target):
                subprocess.Popen(["explorer", "/select,", target])
            else:
                os.startfile(target)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            os.system(f'open -R "{target}"' if os.path.isfile(target) else f'open "{target}"')
        else:
            os.system(f'xdg-open "{os.path.dirname(target) if os.path.isfile(target) else target}" >/dev/null 2>&1 &')
    except Exception:
        pass
    h._send(200, {"ok": True, "path": target})


@route("POST", r"/api/library/rescan")
def r_rescan(h):
    importers.start_job("Refreshing the library", importers.rescan_library)
    h._send(200, {"ok": True})


@route("POST", r"/api/library/switch")
def r_lib_switch(h):
    """Point Babel's Library at a different main folder. mode = 'move' (bring my files) or 'switch' (leave files where they are)."""
    d = h.json_body()
    new = os.path.abspath(os.path.expanduser((d.get("folder") or "").strip()))
    if not d.get("folder"):
        raise ValueError("Choose a folder first.")
    os.makedirs(new, exist_ok=True)
    old = files.library_root()
    store.materialize_paths()
    store.set_settings({"library_folder": new})
    store.compact_paths()
    mode = d.get("mode", "move")
    if mode == "move" and old != new:
        def mv():
            n = files.move_library(old, new, log=lambda m: log(m, "error"))
            store.compact_paths()
            log(f"Moved {n} files into {new}", "import")
            if d.get("scan"):
                importers.start_job("Folder scan", importers.scan_folder, new, False)
        threading.Thread(target=mv, daemon=True).start()
    elif d.get("scan"):
        importers.start_job("Folder scan", importers.scan_folder, new, False)
    log(f"Library folder is now {new}", "import")
    h._send(200, {"ok": True, "folder": new})


@route("POST", r"/api/items/(\d+)/rename-file")
def r_rename_file(h, iid):
    raw = store.get_item(int(iid), raw=True)
    it = store.get_item(int(iid))
    cur = store.resolve_file(raw.get("file_path"))
    if not cur or not os.path.exists(cur):
        raise ValueError("This item has no file to rename.")
    who = ""
    if it.get("authors"):
        a = it["authors"][0]
        who = a.split(",")[0] if "," in a else a.split()[-1]
    name = " - ".join(x for x in [it.get("title") or "Untitled", who] if x) + (f" ({it['year']})" if it.get("year") else "")
    dest = files.unique_path(os.path.dirname(cur), name + os.path.splitext(cur)[1])
    shutil.move(cur, dest)
    store.update_item(int(iid), {"file_path": dest})
    h._send(200, {"ok": True, "path": dest})


SUBS_DIR = os.path.join(store.DATA_DIR, "subs")
os.makedirs(SUBS_DIR, exist_ok=True)
_sub_locks = {}


def _video_path(iid):
    raw = store.get_item(int(iid), raw=True)
    p = store.resolve_file(raw.get("file_path")) if raw else None
    if not p or not os.path.exists(p):
        raise ValueError("The video file can't be found.")
    return p


@route("GET", r"/api/items/(\d+)/tracks")
def r_tracks(h, iid):
    p = _video_path(iid)
    audio, subtitles = [], []
    if p.lower().endswith((".mkv", ".webm", ".mka")):
        try:
            tracks, _ = subs.read_tracks(p)
        except Exception as e:
            tracks = []
            print("[inkwell] mkv tracks unreadable:", e)
        for t in [t for t in tracks if t.get("type") == "audio"]:
            audio.append({"number": t["number"], "lang": t.get("lang"), "label": subs.lang_name(t.get("lang"), t.get("name")), "default": t.get("default")})
        for t in [t for t in tracks if t.get("type") == "subtitles"]:
            text = bool(re.match(r"S_TEXT/(UTF8|ASS|SSA|WEBVTT)|S_(ASS|SSA)", t.get("codec", "")))
            subtitles.append({"id": f"e{t['number']}", "lang": t.get("lang"), "label": subs.lang_name(t.get("lang"), t.get("name")) + (" (forced)" if t.get("forced") else ""),
                              "default": t.get("default"), "supported": text, "source": "embedded"})
    for i, sc in enumerate(subs.sidecars(p)):
        subtitles.append({"id": f"s{i}", "lang": sc["lang"], "label": sc["label"] + " (file)", "default": False, "supported": True, "source": "file"})
    h._send(200, {"audio": audio, "subtitles": subtitles})


@route("GET", r"/api/items/(\d+)/subs/([es]\d+)\.vtt")
def r_sub(h, iid, sid):
    p = _video_path(iid)
    if sid[0] == "s":
        sc = subs.sidecars(p)[int(sid[1:])]
        return h._send(200, subs.file_to_vtt(sc["path"]), "text/vtt; charset=utf-8")
    num = int(sid[1:])
    cache = os.path.join(SUBS_DIR, f"{iid}_{num}.vtt")
    if not os.path.exists(cache) or os.path.getmtime(cache) < os.path.getmtime(p):
        lock = _sub_locks.setdefault(iid, threading.Lock())
        with lock:
            if not os.path.exists(cache) or os.path.getmtime(cache) < os.path.getmtime(p):
                subs.extract_mkv_subs(p, SUBS_DIR, str(iid))
    if not os.path.exists(cache):
        raise ValueError("That subtitle track couldn't be read.")
    with open(cache, encoding="utf-8") as f:
        h._send(200, f.read(), "text/vtt; charset=utf-8")


@route("GET", r"/api/collections")
def r_colls(h):
    h._send(200, store.list_collections())


@route("POST", r"/api/collections")
def r_coll_new(h):
    d = h.json_body()
    cid = store.create_collection(d.get("name"), d.get("color"))
    if d.get("items"):
        store.collection_add(cid, d["items"])
    h._send(200, {"id": cid})


@route("PATCH", r"/api/collections/(\d+)")
def r_coll_edit(h, cid):
    store.update_collection(int(cid), h.json_body())
    h._send(200, {"ok": True})


@route("DELETE", r"/api/collections/(\d+)")
def r_coll_del(h, cid):
    store.delete_collection(int(cid))
    h._send(200, {"ok": True})


@route("POST", r"/api/collections/(\d+)/items")
def r_coll_items(h, cid):
    d = h.json_body()
    ids = [int(i) for i in d.get("items") or []]
    if d.get("remove"):
        store.collection_remove(int(cid), ids)
    else:
        store.collection_add(int(cid), ids)
    h._send(200, {"ok": True})


@route("POST", r"/api/checkout")
def r_checkout(h):
    d = h.json_body()
    ids = [int(i) for i in d.get("items") or []]
    folder = os.path.expanduser((d.get("folder") or "").strip())
    if not ids:
        raise ValueError("Pick at least one item to check out.")
    if not folder or not os.path.isabs(folder):
        raise ValueError("Choose a folder to copy the files into.")
    if os.path.abspath(folder) == os.path.abspath(files.library_root()):
        raise ValueError("Pick a folder outside your library folder.")
    importers.start_job("Checkout", importers.checkout, ids, folder, bool(d.get("keep_folders")))
    h._send(200, {"ok": True, "count": len(ids)})


@route("POST", r"/api/items/(\d+)/poster")
def r_poster(h, iid):
    it = store.get_item(int(iid))
    if not it or it["kind"] not in ("tv", "movie"):
        raise ValueError("Posters are for TV and movies.")
    found = attach_poster(int(iid), it, force=True)
    if found is None:
        raise ValueError("No poster found online for this title. Check the title (or series name) and that you're online.")
    h._send(200, {"ok": True})


# ---- comics: one page at a time
COMIC_CACHE = os.path.join(store.DATA_DIR, "comic_cache")


def _comic_book(iid):
    raw = store.get_item(int(iid), raw=True)
    path = store.resolve_file(raw.get("file_path")) if raw else None
    if not path or not os.path.exists(path):
        raise ValueError("The comic's file can't be found.")
    return comics.book(int(iid), path, COMIC_CACHE)


@route("GET", r"/api/items/(\d+)/comic")
def r_comic_info(h, iid):
    h._send(200, _comic_book(iid).info())


@route("GET", r"/api/items/(\d+)/comic/(\d+)")
def r_comic_page(h, iid, n):
    b = _comic_book(iid)
    try:
        data, name = b.page(int(n))
    except TimeoutError:
        return h._send(503, {"error": "still unpacking"}, headers={"Retry-After": "1"})
    except IndexError:
        return h._send(404, {"error": "no such page"})
    ctype = mimetypes.guess_type(name)[0] or "image/jpeg"
    h._send(200, data, ctype, headers={"Cache-Control": "private, max-age=86400"})


@route("GET", r"/api/items/(\d+)/comic-info")
def r_comic_xml(h, iid):
    data = _comic_book(iid).read_member("comicinfo.xml")
    h._send(200, (data or b"").decode("utf-8", "ignore"), "text/xml; charset=utf-8")


# ---- audiobooks
@route("GET", r"/api/tts")
def r_tts(h):
    h._send(200, audiobook.status())


@route("POST", r"/api/tts/setup")
def r_tts_setup(h):
    d = h.json_body()
    threading.Thread(target=audiobook.setup, args=(d.get("voice") or "en_US-lessac-medium",), daemon=True).start()
    h._send(200, {"ok": True})


@route("POST", r"/api/items/(\d+)/audiobook")
def r_ab_make(h, iid):
    d = h.json_body()
    it = store.get_item(int(iid))
    if not it or it.get("file_type") not in ("epub", "pdf"):
        raise ValueError("Audiobooks can be made from EPUB and PDF books.")
    s = store.get_settings()
    voice = d.get("voice") or s.get("tts_voice") or "en_US-lessac-medium"
    speed = float(d.get("speed") or s.get("tts_speed") or 1.0)
    store.set_settings({"tts_voice": voice, "tts_speed": speed})
    audiobook.queue(int(iid), voice, speed, fresh=bool(d.get("fresh")))
    h._send(200, {"ok": True})


@route("GET", r"/api/items/(\d+)/audiobook/progress")
def r_ab_progress(h, iid):
    it = store.get_item(int(iid))
    h._send(200, audiobook.resume_info(it) if it else None)


@route("POST", r"/api/items/(\d+)/audiobook/discard")
def r_ab_discard(h, iid):
    audiobook.discard(int(iid))
    h._send(200, {"ok": True})


@route("DELETE", r"/api/items/(\d+)/audiobook")
def r_ab_delete(h, iid):
    audiobook.cancel(int(iid))
    audiobook.delete(int(iid))
    h._send(200, {"ok": True})


@route("POST", r"/api/items/(\d+)/audiobook/cancel")
def r_ab_cancel(h, iid):
    audiobook.cancel(int(iid))
    h._send(200, {"ok": True})


@route("GET", r"/api/items/(\d+)/audiobook")
def r_ab_manifest(h, iid):
    it = store.get_item(int(iid))
    m = audiobook.load_manifest(it) if it else None
    if not m:
        return h._send(404, {"error": "no audiobook"})
    h._send(200, m)


@route("GET", r"/api/items/(\d+)/audio/(\d+)")
def r_ab_audio(h, iid, n):
    it = store.get_item(int(iid))
    m = audiobook.load_manifest(it) if it else None
    if not m or int(n) >= len(m["chapters"]):
        return h._send(404, {"error": "no such chapter"})
    path = os.path.join(audiobook.audio_dir(it), m["chapters"][int(n)]["file"])
    h.send_file(path, "audio/mpeg")


@route("POST", r"/api/items/(\d+)/audio-pos")
def r_ab_pos(h, iid):
    d = h.json_body()
    store.update_item(int(iid), {"audio_pos": json.dumps({"ch": int(d.get("ch") or 0), "t": float(d.get("t") or 0), "done": bool(d.get("done"))}),
                                 "opened_at": time.time()})
    h._send(200, {"ok": True})


PLAYER_STATE = {}


@route("GET", r"/api/player")
def r_player_get(h):
    h._send(200, PLAYER_STATE)


PLAYER_CMDS = []


@route("POST", r"/api/player/cmd")
def r_player_cmd(h):
    """Widget -> main window remote control."""
    cmd = h.json_body()
    d = DESKTOP
    if d is not None and hasattr(d, "player_cmd") and getattr(d, "main", None) is not None:
        threading.Thread(target=d.player_cmd, args=(cmd,), daemon=True).start()
    else:
        PLAYER_CMDS.append(cmd)
        del PLAYER_CMDS[:-20]
    h._send(200, {"ok": True})


@route("GET", r"/api/player/cmds")
def r_player_cmds(h):
    out = PLAYER_CMDS[:]
    PLAYER_CMDS.clear()
    h._send(200, out)


@route("POST", r"/api/player")
def r_player_set(h):
    d = h.json_body()
    PLAYER_STATE.clear()
    if isinstance(d, dict) and d.get("tracks"):
        PLAYER_STATE.update(d)
    h._send(200, {"ok": True})


@route("GET", r"/api/genres")
def r_genres(h):
    h._send(200, {"genres": taxonomy.ALL_GENRES, "subjects": taxonomy.SUBJECTS, "topics": list(taxonomy.TOPICS) + [taxonomy.GENERAL_TOPIC]})


ANALYSIS_VERSION = 4


def reparse_video(it):
    """Re-read a video's show/season/episode from its file name (fixes anime-style names like 'Show S1 - 03')."""
    raw = store.get_item(it["id"], raw=True)
    path = store.resolve_file(raw.get("file_path"))
    if not path or not os.path.exists(path):
        return
    locked = set(it.get("locked") or [])
    mm = media.metadata(path, raw.get("orig_name") or os.path.basename(path))
    mm.pop("picture", None)
    upd = {}
    for k in ("kind", "series", "season", "episode", "title", "year"):
        if mm.get(k) not in (None, "") and k not in locked:
            upd[k] = mm[k]
    if upd.get("kind") == "tv" and upd.get("series"):
        upd["series"] = canonical_series(upd["series"])
    if upd:
        store.update_item(it["id"], upd)


def reclassify_library():
    """Re-sort with the current rules (keeps anything you edited yourself)."""
    s = store.get_settings()
    ver = int(s.get("analysis_version") or 1)
    if ver >= ANALYSIS_VERSION:
        return
    store.set_settings({"analysis_version": ANALYSIS_VERSION})
    items = store.list_items()
    if ver < 2:
        log(f"Re-sorting {len(items)} items with the new subject, genre and tag rules…", "import")
    for it in items:
        try:
            if it["kind"] in ("tv", "movie"):
                if ver < 3:
                    reparse_video(it)
                it = store.get_item(it["id"])
                if not (store.get_item(it["id"], raw=True).get("cover_path") or "").startswith("poster_"):
                    analyze_item(it["id"])
            elif ver < 2 or (it["kind"] in ("graphic", "book") and not it.get("authors")):
                analyze_item(it["id"], refresh_meta=not it.get("ai_source"))
        except Exception:
            traceback.print_exc()


def start_background():
    """Start the library server + inbox watcher on background threads (used by desktop.py)."""
    try:
        files.migrate_legacy()
    except Exception as e:
        print("[inkwell] migration skipped:", e)
    for it in store.list_items():
        if it["status"] == "analyzing":
            threading.Thread(target=analyze_item, args=(it["id"], True), daemon=True).start()
    watcher.start()
    try:
        import relocate
        if os.path.exists(os.path.join(store.ROOT, "relocate.json")):
            relocate.finish(log)
        else:
            n = store.compact_paths()
            if n:
                print(f"[inkwell] stored {n} file paths in portable form")
    except Exception:
        traceback.print_exc()
    # one pass over the existing books to find series (again whenever the way series are found improves)
    threading.Thread(target=audiobook.reset_stale, daemon=True).start()
    discover.start_gatherer()        # the catalogue's contents are gathered in the background
    threading.Thread(target=lambda: (time.sleep(45), merge_all_copies()), daemon=True).start()   # (once)
    try:
        import news
        news.start_watching()        # and the Local desk's events, when you've asked to hear about new ones
    except Exception as e:
        print("[inkwell] event watching skipped:", e)
    def _link_journal():             # journal pages written before their book was on the shelf
        try:
            for it in store.list_items():
                if not (it.get("wanted") and not it.get("has_file")):
                    journal.link_orphans(it)
        except Exception as e:
            print("[inkwell] journal linking skipped:", e)
    threading.Thread(target=_link_journal, daemon=True).start()
    threading.Thread(target=discover.covers_for_shelf, daemon=True).start()   # audiobooks interrupted last time are paused, not stuck
    if store.get_settings().get("series_pass") != 2:
        def _series_pass():
            series.backfill(online=True, log=log)
            store.set_settings({"series_pass": 2})
        threading.Thread(target=_series_pass, daemon=True).start()
    # re-run the Obsidian import once with the newer importer: it also reads the "finished" tables next to the
    # notes folder, so films and shows get their type, score and date (and nothing is duplicated)
    if store.get_settings().get("journal_fix") == 1:
        # imported notes become one entry per sitting, and "dropped" notes get marked as dropped
        try:
            n = journal.split_imported()
            if n:
                log(f"Journal: split {n} imported reviews into separate entries", "import")
        except Exception as e:
            print("[inkwell] journal split skipped:", e)
        store.set_settings({"journal_fix": 2})
    if not store.get_settings().get("journal_fix"):
        def _journal_fix():
            folder = store.get_settings().get("obsidian_folder")
            try:
                if folder and os.path.isdir(folder):
                    st = journal.import_obsidian(folder)
                    log(f"Journal updated from Obsidian: {st.get('logged', 0)} added, {st.get('moved', 0)} reviews moved to their film or show", "import")
            except Exception as e:
                print("[inkwell] journal re-import skipped:", e)
            store.set_settings({"journal_fix": 2})
        threading.Thread(target=_journal_fix, daemon=True).start()
    # Babel's Library now starts as the desktop widget (once; you can still change it in Settings)
    if not store.get_settings().get("widget_default_applied"):
        store.set_settings({"start_mode": "widget", "widget_default_applied": True})
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    # "localhost" often resolves to IPv6 first; answering there too avoids a slow fallback on every connection
    try:
        import socket

        class V6Server(ThreadingHTTPServer):
            address_family = socket.AF_INET6
        srv6 = V6Server(("::1", PORT), Handler)
        srv6.daemon_threads = True
        threading.Thread(target=srv6.serve_forever, daemon=True).start()
    except OSError:
        pass
    threading.Thread(target=reclassify_library, daemon=True).start()
    import phonesync
    phonesync.start()       # the Android app's sync server (port 8766, paired phones only)
    return srv


def main():
    """Browser mode: python3 app/server.py"""
    srv = start_background()
    url = f"http://localhost:{PORT}"
    print(f"\n  Babel's Library is open at {url}\n  Library data: {store.DATA_DIR}\n  Inbox folder: {os.path.expanduser(store.get_settings()['watch_folder'])}\n  Press Ctrl+C to stop.\n")
    if "--no-browser" not in sys.argv:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        srv.shutdown()
        print("Goodbye.")


if __name__ == "__main__":
    main()
