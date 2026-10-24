"""Bulk imports: scan a folder, Zotero, Calibre, and open-access downloads.
Every file is copied (or moved) into the main library folder."""
import html
import json
import os
import re
import shutil
import sqlite3
import tempfile
import threading
import time
import traceback

import files
import lookup
import store

JOB = {"running": False, "label": "", "total": 0, "done": 0, "added": 0, "skipped": 0, "errors": 0, "current": "", "finished_at": None}
_job_lock = threading.Lock()


def _srv():
    import server  # late import (server imports us)
    return server


def start_job(label, target, *args):
    with _job_lock:
        if JOB["running"]:
            raise ValueError("Another import is still running. Wait for it to finish.")
        JOB.update(running=True, label=label, total=0, done=0, added=0, skipped=0, errors=0, current="", finished_at=None, message="")

    def run():
        try:
            target(*args)
        except Exception as e:
            traceback.print_exc()
            _srv().log(f"{label} stopped: {e}", "error")
        finally:
            JOB.update(running=False, current="", finished_at=time.time())
            _srv().log(JOB.get("message") or (f"{label} finished: {JOB['added']} added, {JOB['skipped']} already in your library"
                       + (f", {JOB['errors']} couldn't be read" if JOB["errors"] else "")), "import")

    threading.Thread(target=run, daemon=True).start()


# ---------------------------------------------------------------- scan a folder
def list_supported(folder):
    out = []
    lib = files.library_root()
    for root, dirs, fnames in os.walk(folder):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("__MACOSX", "$RECYCLE.BIN", "System Volume Information")
                   and not (d == "Audiobooks" and os.path.normcase(os.path.abspath(root)) == os.path.normcase(lib))
                   and not d.endswith(".building")]
        for fn in fnames:
            if not fn.startswith(".") and os.path.splitext(fn)[1].lower() in files.SUPPORTED:
                out.append(os.path.join(root, fn))
    return out


def scan_preview(folder):
    folder = os.path.expanduser(folder)
    if not os.path.isdir(folder):
        raise ValueError("That folder doesn't exist.")
    paths = list_supported(folder)
    counts = {}
    for p in paths:
        k = files.kind_for_ext(os.path.splitext(p)[1])
        counts[k] = counts.get(k, 0) + 1
    known = {store.resolve_file(fp) for _, fp, _, _ in store.all_file_paths()}
    maybe_new = sum(1 for p in paths if os.path.abspath(p) not in known)
    return {"folder": folder, "total": len(paths), "by_kind": counts, "maybe_new": maybe_new,
            "inside_library": files.inside(folder, files.library_root())}


def scan_folder(folder, move=False):
    paths = list_supported(os.path.expanduser(folder))
    JOB["total"] = len(paths)
    for p in paths:
        JOB["current"] = os.path.basename(p)
        try:
            _, new = _srv().import_file(p, os.path.basename(p), origin="folder scan", move=move, quiet=True)
            JOB["added" if new else "skipped"] += 1
        except Exception as e:
            JOB["errors"] += 1
            print("[inkwell] scan error", p, e)
        JOB["done"] += 1


# ---------------------------------------------------------------- Zotero
ZOTERO_ARTICLE_TYPES = {"journalArticle", "conferencePaper", "preprint", "report", "magazineArticle", "newspaperArticle",
                        "thesis", "manuscript", "webpage", "blogPost", "encyclopediaArticle", "dictionaryEntry", "document"}
ZCOLORS = {"#ffd400": "yellow", "#f19837": "yellow", "#aaaaaa": "yellow", "#5fb236": "green",
           "#2ea8e5": "blue", "#a28ae5": "blue", "#ff6666": "pink", "#e56eee": "pink"}


def _open_sqlite_copy(db_path):
    """Zotero/Calibre may be running and holding the DB; work on a copy."""
    tmp = os.path.join(tempfile.gettempdir(), f"inkwell-{os.getpid()}-{os.path.basename(db_path)}")
    for cand in (db_path, db_path + ".bak"):
        try:
            shutil.copy2(cand, tmp)
            c = sqlite3.connect(tmp)
            c.row_factory = sqlite3.Row
            c.execute("SELECT 1 FROM sqlite_master").fetchone()
            return c
        except Exception:
            continue
    raise ValueError(f"Couldn't open {db_path}. Close the app that owns it and try again.")


def _table(c, *names):
    have = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')")}
    return next((n for n in names if n in have), None)


def zotero_read(zdir):
    zdir = os.path.expanduser(zdir)
    dbp = os.path.join(zdir, "zotero.sqlite")
    if not os.path.exists(dbp):
        raise ValueError("No Zotero library found there. Pick the folder that contains zotero.sqlite.")
    c = _open_sqlite_copy(dbp)
    types_t = _table(c, "itemTypesCombined", "itemTypes")
    fields_t = _table(c, "fieldsCombined", "fields")
    deleted = {r[0] for r in c.execute("SELECT itemID FROM deletedItems")} if _table(c, "deletedItems") else set()
    rows = c.execute(f"SELECT i.itemID, i.key, t.typeName FROM items i JOIN {types_t} t ON t.itemTypeID=i.itemTypeID").fetchall()
    items = {r["itemID"]: {"id": r["itemID"], "key": r["key"], "type": r["typeName"], "fields": {}, "creators": [],
                           "tags": [], "atts": [], "notes": []} for r in rows if r["itemID"] not in deleted}
    for r in c.execute(f"SELECT d.itemID, f.fieldName, v.value FROM itemData d JOIN {fields_t} f ON f.fieldID=d.fieldID "
                       "JOIN itemDataValues v ON v.valueID=d.valueID"):
        if r["itemID"] in items:
            items[r["itemID"]]["fields"][r["fieldName"]] = r["value"]
    for r in c.execute("SELECT ic.itemID, c.firstName, c.lastName, ic.orderIndex, ct.creatorType FROM itemCreators ic "
                       "JOIN creators c ON c.creatorID=ic.creatorID JOIN creatorTypes ct ON ct.creatorTypeID=ic.creatorTypeID "
                       "ORDER BY ic.itemID, ic.orderIndex"):
        if r["itemID"] in items and r["creatorType"] in ("author", "editor", "bookAuthor", "contributor"):
            nm = f"{r['firstName'] or ''} {r['lastName'] or ''}".strip()
            if nm:
                items[r["itemID"]]["creators"].append(nm)
    for r in c.execute("SELECT it.itemID, t.name FROM itemTags it JOIN tags t ON t.tagID=it.tagID"):
        if r["itemID"] in items:
            items[r["itemID"]]["tags"].append(r["name"])
    for r in c.execute("SELECT itemID, parentItemID, linkMode, contentType, path FROM itemAttachments"):
        a = items.get(r["itemID"])
        if not a:
            continue
        p = r["path"] or ""
        full = None
        if p.startswith("storage:"):
            full = os.path.join(zdir, "storage", a["key"], p[8:])
        elif r["linkMode"] == 2 and p and not p.startswith("attachments:"):
            full = p
        ext = os.path.splitext(full or "")[1].lower()
        if full and ext in files.SUPPORTED and os.path.exists(full):
            att = {"att_id": r["itemID"], "path": full}
            parent = items.get(r["parentItemID"])
            if parent:
                parent["atts"].append(att)
            else:
                a["standalone"] = att
    if _table(c, "itemNotes"):
        for r in c.execute("SELECT parentItemID, note FROM itemNotes WHERE parentItemID IS NOT NULL"):
            if r["parentItemID"] in items:
                txt = html.unescape(re.sub(r"<[^>]+>", "\n", r["note"] or "")).strip()
                txt = re.sub(r"\n{3,}", "\n\n", txt)
                if txt:
                    items[r["parentItemID"]]["notes"].append(txt)
    annots = {}
    if _table(c, "itemAnnotations"):
        for r in c.execute("SELECT parentItemID, type, text, comment, color, position FROM itemAnnotations"):
            annots.setdefault(r["parentItemID"], []).append(dict(r))
    c.close()
    out = []
    for it in items.values():
        if it["type"] in ("attachment", "note", "annotation") and not it.get("standalone"):
            continue
        out.append(it)
    return out, annots


def _zotero_meta(it):
    f = it["fields"]
    year = re.search(r"\d{4}", f.get("date", "") or "")
    kind = "book" if it["type"] in ("book", "bookSection") else "article"
    meta = {
        "kind": kind, "title": f.get("title", "").strip(), "authors": it["creators"][:20],
        "year": year.group(0) if year else "", "journal": f.get("publicationTitle") or f.get("proceedingsTitle") or "",
        "volume": f.get("volume", ""), "issue": f.get("issue", ""), "pages": f.get("pages", ""),
        "publisher": f.get("publisher", ""), "place": f.get("place", ""), "doi": f.get("DOI", ""),
        "isbn": lookup.clean_isbn((f.get("ISBN") or "").split(" ")[0]), "url": f.get("url", ""),
        "tags": it["tags"][:12], "source": "zotero",
    }
    if f.get("abstractNote"):
        meta["summary"] = f["abstractNote"][:600]
    return {k: v for k, v in meta.items() if v not in ("", None, [])}


def zotero_preview(zdir):
    items, _ = zotero_read(zdir)
    with_files = sum(1 for i in items if i["atts"] or i.get("standalone"))
    return {"folder": os.path.expanduser(zdir), "total": len(items), "with_files": with_files,
            "without_files": len(items) - with_files}


def _pdf_page_sizes(path):
    try:
        import extract
        r = extract.PdfReader(path)
        return [(float(p.mediabox.width), float(p.mediabox.height), float(p.mediabox.left), float(p.mediabox.bottom)) for p in r.pages]
    except Exception:
        return []


def _import_zotero_annotations(item_id, path, anns, notes):
    for n in notes:
        first = n.splitlines()[0][:80] if n else ""
        store.create_annotation(item_id, {"title": first or "Zotero note", "note": n[len(first):].strip() or n, "color": "yellow",
                                          "locator": {"type": "note", "label": "Zotero note"}})
    if not anns or not path.lower().endswith(".pdf"):
        return
    sizes = _pdf_page_sizes(path)
    for a in anns:
        try:
            pos = json.loads(a["position"] or "{}")
            pi = int(pos.get("pageIndex", 0))
            W, H, X0, Y0 = sizes[pi] if pi < len(sizes) else (612, 792, 0, 0)
            rects = []
            for x1, y1, x2, y2 in pos.get("rects", [])[:40]:
                rects.append({"p": pi + 1, "x": (x1 - X0) / W, "y": (H - (y2 - Y0)) / H, "w": (x2 - x1) / W, "h": (y2 - y1) / H})
            color = ZCOLORS.get((a.get("color") or "").lower(), "yellow")
            t = a.get("type")
            if t in (1, 5, "highlight", "underline") and rects:
                loc = {"page": pi + 1, "rects": rects}
            elif rects:
                loc = {"type": "pin", "page": pi + 1, "x": min(.97, max(.01, rects[0]["x"])), "y": min(.97, max(.01, rects[0]["y"]))}
            else:
                continue
            store.create_annotation(item_id, {"title": "", "quote": a.get("text") or "", "note": a.get("comment") or "",
                                              "color": color, "locator": loc})
        except Exception as e:
            print("[inkwell] annotation skipped:", e)


def zotero_import(zdir, download_oa=False, move=True):
    items, annots = zotero_read(zdir)
    JOB["total"] = len(items)
    srv = _srv()
    for it in items:
        meta = _zotero_meta(it) if not it.get("standalone") else {"source": "zotero"}
        JOB["current"] = meta.get("title") or "attachment"
        try:
            att = (it["atts"] or [it.get("standalone")])[0] if (it["atts"] or it.get("standalone")) else None
            dupe = store.find_dupe(meta.get("doi"), meta.get("isbn"), meta.get("title")) if meta.get("title") else None
            if att and dupe and store.get_item(dupe).get("has_file"):
                cur = store.get_item(dupe)
                if meta.get("tags"):
                    store.update_item(dupe, {"tags": list(dict.fromkeys((cur.get("tags") or []) + meta["tags"]))[:8]})
                if not store.list_annotations(dupe):
                    _import_zotero_annotations(dupe, store.resolve_file(store.get_item(dupe, raw=True)["file_path"]),
                                               annots.get(att["att_id"], []), it["notes"])
                JOB["skipped"] += 1
                JOB["done"] += 1
                continue
            if att:
                item_id, new = srv.import_file(att["path"], os.path.basename(att["path"]), origin="Zotero",
                                               meta=meta if len(meta) > 1 else None, quiet=True, move=move)
                att["path"] = store.resolve_file(store.get_item(item_id, raw=True)["file_path"]) or att["path"]
                if new or not store.list_annotations(item_id):
                    _import_zotero_annotations(item_id, att["path"], annots.get(att["att_id"], []), it["notes"])
                if not new and meta.get("tags"):
                    cur = store.get_item(item_id)
                    store.update_item(item_id, {"tags": list(dict.fromkeys((cur.get("tags") or []) + meta["tags"]))[:12]})
            else:
                if store.find_dupe(meta.get("doi"), meta.get("isbn"), meta.get("title")):
                    JOB["skipped"] += 1
                    JOB["done"] += 1
                    continue
                item_id, new = srv.create_entry({**meta, "physical": 0}), True
                for n in it["notes"]:
                    store.create_annotation(item_id, {"title": "Zotero note", "note": n, "locator": {"type": "note"}})
                if download_oa and (meta.get("doi") or meta.get("url")):
                    srv.download_open_access(item_id, quiet=True)
            JOB["added" if new else "skipped"] += 1
        except Exception as e:
            JOB["errors"] += 1
            print("[inkwell] zotero item failed:", e)
        JOB["done"] += 1


# ---------------------------------------------------------------- Calibre
FORMAT_PREF = ["EPUB", "PDF", "CBZ", "CBR", "CB7", "CBT"]


def calibre_read(cdir):
    cdir = os.path.expanduser(cdir)
    dbp = os.path.join(cdir, "metadata.db")
    if not os.path.exists(dbp):
        raise ValueError("No Calibre library found there. Pick the folder that contains metadata.db.")
    c = _open_sqlite_copy(dbp)
    books = {r["id"]: {**dict(r), "authors": [], "tags": [], "formats": {}, "ids": {}} for r in
             c.execute("SELECT id, title, pubdate, path, has_cover FROM books")}
    for r in c.execute("SELECT l.book, a.name FROM books_authors_link l JOIN authors a ON a.id=l.author ORDER BY l.id"):
        if r["book"] in books:
            books[r["book"]]["authors"].append(r["name"].replace("|", ","))
    for r in c.execute("SELECT l.book, t.name FROM books_tags_link l JOIN tags t ON t.id=l.tag"):
        if r["book"] in books:
            books[r["book"]]["tags"].append(r["name"])
    for r in c.execute("SELECT book, format, name FROM data"):
        if r["book"] in books:
            books[r["book"]]["formats"][r["format"].upper()] = r["name"]
    for r in c.execute("SELECT book, type, val FROM identifiers"):
        if r["book"] in books:
            books[r["book"]]["ids"][r["type"].lower()] = r["val"]
    pubs = {r["book"]: r["name"] for r in c.execute("SELECT l.book, p.name FROM books_publishers_link l JOIN publishers p ON p.id=l.publisher")}
    comments = {r["book"]: r["text"] for r in c.execute("SELECT book, text FROM comments")}
    series = {}
    if _table(c, "books_series_link"):
        series = {r["book"]: r["name"] for r in c.execute("SELECT l.book, s.name FROM books_series_link l JOIN series s ON s.id=l.series")}
    c.close()
    for b in books.values():
        b["publisher"] = pubs.get(b["id"], "")
        b["comment"] = html.unescape(re.sub(r"<[^>]+>", " ", comments.get(b["id"]) or "")).strip()
        b["series"] = series.get(b["id"], "")
        fmt = next((f for f in FORMAT_PREF if f in b["formats"]), None)
        b["file"] = os.path.join(cdir, b["path"], f"{b['formats'][fmt]}.{fmt.lower()}") if fmt else None
        if b["file"] and not os.path.exists(b["file"]):
            b["file"] = None
        b["cover"] = os.path.join(cdir, b["path"], "cover.jpg") if b["has_cover"] else None
    return list(books.values())


def calibre_preview(cdir):
    books = calibre_read(cdir)
    return {"folder": os.path.expanduser(cdir), "total": len(books), "with_files": sum(1 for b in books if b["file"]),
            "without_files": sum(1 for b in books if not b["file"])}


def calibre_import(cdir, download_oa=False, move=True):
    books = calibre_read(cdir)
    JOB["total"] = len(books)
    srv = _srv()
    for b in books:
        JOB["current"] = b["title"]
        year = re.match(r"(\d{4})", b.get("pubdate") or "")
        meta = {"title": b["title"], "authors": b["authors"], "year": year.group(1) if year and year.group(1) != "0101" else "",
                "publisher": b["publisher"], "isbn": lookup.clean_isbn(b["ids"].get("isbn", "")), "doi": b["ids"].get("doi", ""),
                "tags": b["tags"][:12], "series": b["series"], "source": "calibre"}
        if b["comment"]:
            meta["summary"] = b["comment"][:600]
        meta = {k: v for k, v in meta.items() if v not in ("", None, [])}
        try:
            if b["file"]:
                ext = os.path.splitext(b["file"])[1].lower()
                meta["kind"] = files.kind_for_ext(ext)
                item_id, new = srv.import_file(b["file"], os.path.basename(b["file"]), origin="Calibre", meta=meta, quiet=True, move=move)
            else:
                if store.find_dupe(meta.get("doi"), meta.get("isbn"), meta.get("title")):
                    JOB["skipped"] += 1
                    JOB["done"] += 1
                    continue
                item_id, new = srv.create_entry({**meta, "kind": "book", "physical": 0}), True
            if new and b["cover"] and os.path.exists(b["cover"]):
                shutil.copy2(b["cover"], os.path.join(store.COVERS_DIR, f"{item_id}.jpg"))  # covers are copied, never moved
                store.update_item(item_id, {"cover_path": f"{item_id}.jpg"})
            JOB["added" if new else "skipped"] += 1
        except Exception as e:
            JOB["errors"] += 1
            print("[inkwell] calibre book failed:", e)
        JOB["done"] += 1


# ---------------------------------------------------------------- Checkout (copy out)
def checkout(item_ids, folder, keep_folders=False):
    """Copy the files of the chosen items into another folder (originals stay in the library)."""
    import files
    import media
    import subs
    root = files.library_root()
    os.makedirs(folder, exist_ok=True)
    jobs = []
    for iid in item_ids:
        raw = store.get_item(int(iid), raw=True)
        p = store.resolve_file(raw.get("file_path")) if raw else None
        if p and os.path.exists(p):
            jobs.append((raw, p))
    JOB["total"] = len(jobs)
    total_bytes = 0
    for raw, p in jobs:
        JOB["current"] = os.path.basename(p)
        try:
            dest_dir = folder
            if keep_folders and files.inside(p, root):
                dest_dir = os.path.join(folder, os.path.relpath(os.path.dirname(p), root))
                os.makedirs(dest_dir, exist_ok=True)
            dest = files.unique_path(dest_dir, os.path.basename(p))
            files.safe_copy(p, dest)
            total_bytes += os.path.getsize(dest)
            if os.path.splitext(p)[1].lower() in media.VIDEO_EXT:
                src_base = os.path.splitext(os.path.basename(p))[0]
                dest_base = os.path.splitext(os.path.basename(dest))[0]
                for sc in subs.sidecars(p):
                    fn = os.path.basename(sc["path"])
                    if fn.lower().startswith(src_base.lower()):
                        try:
                            shutil.copy2(sc["path"], os.path.join(dest_dir, dest_base + fn[len(src_base):]))
                        except OSError:
                            pass
            JOB["added"] += 1
        except Exception as e:
            JOB["errors"] += 1
            print("[inkwell] checkout error", p, e)
        JOB["done"] += 1
    mb = total_bytes / 1048576
    JOB["message"] = (f"Checked out {JOB['added']} file{'s' if JOB['added'] != 1 else ''} ({mb:,.0f} MB) to {folder}"
                      + (f"; {JOB['errors']} couldn't be copied" if JOB["errors"] else "")
                      + (f"; {len(item_ids) - len(jobs)} had no file" if len(item_ids) > len(jobs) else ""))


# ---------------------------------------------------------------- Refresh (recheck the library folder)
def rescan_library():
    """Remove items whose files are gone, relink files that moved inside the library folder, add new files."""
    srv = _srv()
    root = files.library_root()
    if not os.path.isdir(root):
        raise ValueError("The library folder isn't reachable. Is the drive connected?")
    on_disk = list_supported(root)
    items = [(i, p) for i, p, _, _ in store.all_file_paths()]
    missing = {i: p for i, p in items if p and not os.path.exists(p)}
    if on_disk == [] and len(items) > 5 and len(missing) == len(items):
        raise ValueError("No files were found in the library folder, so nothing was removed. Is the drive connected?")
    known = {os.path.normcase(os.path.abspath(p)) for _, p in items if p}
    new_files = [p for p in on_disk if os.path.normcase(os.path.abspath(p)) not in known]
    JOB["total"] = len(new_files) + len(missing)
    relinked = added = removed = 0
    # files that are new on disk but match a missing item: the same file, moved or renamed
    by_sha = {}
    for iid in missing:
        raw = store.get_item(iid, raw=True)
        if raw and raw.get("sha256"):
            by_sha[raw["sha256"]] = iid
    for p in new_files:
        JOB["current"] = os.path.basename(p)
        try:
            sha = srv.sha256_file(p)
            iid = by_sha.pop(sha, None)
            if iid is not None:
                store.update_item(iid, {"file_path": p})
                missing.pop(iid, None)
                relinked += 1
            else:
                _, new = srv.import_file(p, os.path.basename(p), origin="folder scan", move=False, quiet=True)
                added += 1 if new else 0
                JOB["skipped"] += 0 if new else 1
        except Exception as e:
            JOB["errors"] += 1
            print("[babel] rescan error", p, e)
        JOB["done"] += 1
    for iid, p in missing.items():
        JOB["current"] = os.path.basename(p)
        try:
            store.delete_item(iid, delete_file=False)
            removed += 1
        except Exception as e:
            JOB["errors"] += 1
            print("[babel] rescan remove error", p, e)
        JOB["done"] += 1
    JOB["added"] = added
    import series
    series.backfill(online=True)
    JOB["message"] = (f"Library refreshed: {added} new, {removed} missing removed"
                      + (f", {relinked} moved files found again" if relinked else "")
                      + (f", {JOB['errors']} problems" if JOB["errors"] else ""))
