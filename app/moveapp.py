"""Moving the whole of Babel's Library (program, library data and every library file) to a chosen folder, from Settings.

<folder>/Inkwell and <folder>/Library are built up as checked copies while the app keeps running. The database goes
last, so a copy that has one is complete; if anything fails, nothing has changed and pressing Move again carries on.
Only then does the new copy start and take over. The old copy is never deleted: its moved_to.txt sends a later start
over to the new place, for as long as the new place is there.
"""
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time

import files
import importers
import store

MARK = ".babel-move"                    # in the chosen folder while a move is under way (a resumed move may overwrite)
MOVED_TO = "moved_to.txt"
SKIP = {"__pycache__", "comic_cache", ".shortcuts-babel", "relocate.json", "MOVED.txt", MOVED_TO, "inkwell.log",
        "library.db", "library.db-wal", "library.db-shm", "library.db-journal"}
ROOM = 1 << 30                          # left free on the new drive


def _norm(p):
    return os.path.normcase(os.path.abspath(p))


def _inside(p, root):
    p, root = _norm(p), _norm(root)
    return p == root or p.startswith(root.rstrip(os.sep) + os.sep)


def _places(folder):
    app = os.path.join(folder, os.path.basename(store.ROOT))
    return {"app": app, "data": os.path.join(app, "library_data"), "library": os.path.join(folder, "Library")}


def _clean(folder):
    folder = (folder or "").strip().strip('"')
    if not folder:
        raise ValueError("Choose a folder first.")
    return os.path.abspath(os.path.expanduser(folder))


def _tree(src, dst, skip=(), names=()):
    for dirpath, dirs, fnames in os.walk(src):
        dirs[:] = [d for d in dirs if d not in names and not any(_norm(os.path.join(dirpath, d)) == _norm(s) for s in skip)]
        for n in fnames:
            if n not in names and not n.endswith(".part"):
                p = os.path.join(dirpath, n)
                yield p, os.path.join(dst, os.path.relpath(p, src))


def _all_files(folder):
    """(from, to) for everything that moves, except the database."""
    to, lib = _places(folder), files.library_root()
    data = store.DATA_DIR
    yield from _tree(store.ROOT, to["app"], (data, lib), SKIP)
    yield from _tree(data, to["data"], (lib,), SKIP)
    if os.path.isdir(lib) and _norm(lib) != _norm(to["library"]):
        yield from _tree(lib, to["library"], (store.ROOT, data))


def _fresh(src, dst):
    try:
        a, b = os.stat(src), os.stat(dst)
    except OSError:
        return False
    return a.st_size == b.st_size and abs(a.st_mtime - b.st_mtime) <= 2         # (exFAT keeps times to 2 seconds at worst)


def _has_files(folder):
    return os.path.isdir(folder) and any(fn for _, _, fn in os.walk(folder))


def _check(folder):
    to, lib = _places(folder), files.library_root()
    if _norm(to["app"]) == _norm(store.ROOT):
        raise ValueError("Babel's Library is already in that folder.")
    if _inside(folder, store.ROOT) or (_norm(lib) != _norm(to["library"]) and _inside(folder, lib)):
        raise ValueError("Choose a folder outside Babel's Library and its library folder.")
    if os.path.exists(os.path.join(to["data"], "library.db")):
        raise ValueError(f"There is already a Babel's Library in {to['app']}. Choose another folder.")
    if not os.path.exists(os.path.join(folder, MARK)):
        if _has_files(to["app"]):
            raise ValueError(f"{to['app']} already has files in it. Choose another folder.")
        if _norm(lib) != _norm(to["library"]) and _has_files(to["library"]):
            raise ValueError(f"{to['library']} already has files in it. Choose another folder.")


def _free(folder):
    p = folder
    while not os.path.exists(p):
        up = os.path.dirname(p)
        if up == p:
            raise ValueError(f"{folder} isn't on a drive that's available.")
        p = up
    return shutil.disk_usage(p).free


def plan(folder):
    folder = _clean(folder)
    _check(folder)
    count = size = need = 0
    for src, dst in _all_files(folder):
        n = os.path.getsize(src)
        count, size = count + 1, size + n
        if not _fresh(src, dst):
            need += n
    need += os.path.getsize(store.DB_PATH)
    free = _free(folder)
    return {"folder": folder, "app": _places(folder)["app"], "library": _places(folder)["library"], "files": count, "size": size,
            "need": need, "free": free, "enough": free >= need + ROOM}


def start(folder):
    p = plan(folder)
    if not p["enough"]:
        raise ValueError("There isn't enough free space in that folder's drive.")
    importers.start_job("Moving Babel's Library", _run, p["folder"])
    return p


def _copy(src, dst):
    """A USB drive can drop out for a moment: wait and try again before giving up."""
    last = None
    for attempt in range(7):
        try:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            files.safe_copy(src, dst)
            return
        except OSError as e:
            if os.path.exists(store.ROOT) and not os.path.exists(src):
                return                  # the drive's there and the file isn't: it was removed while moving
            last = e
            time.sleep(10)
    raise last


def _new_database(folder):
    """A consistent copy of the database that finds the library in its new place. Returns files outside the library."""
    to, lib = _places(folder), files.library_root()
    os.makedirs(to["data"], exist_ok=True)
    part = os.path.join(to["data"], "library.db.part")
    if os.path.exists(part):
        os.remove(part)
    a, b = sqlite3.connect(store.DB_PATH, timeout=30), sqlite3.connect(part)
    try:
        a.backup(b)
        b.execute("UPDATE settings SET value=? WHERE key='library_folder'", (json.dumps("@/Library"),))
        outside = []
        for iid, p, title in b.execute("SELECT id, file_path, title FROM items WHERE file_path IS NOT NULL").fetchall():
            if os.path.isabs(p):
                if _inside(p, lib):
                    b.execute("UPDATE items SET file_path=? WHERE id=?", (store.LIB_PREFIX + os.path.relpath(p, lib).replace(os.sep, "/"), iid))
                else:
                    outside.append(title or p)
        b.commit()
        if b.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise OSError("the copy of the database didn't check out")
        for p, in b.execute("SELECT file_path FROM items WHERE file_path LIKE ?", (store.LIB_PREFIX + "%",)).fetchall():
            rel = p[len(store.LIB_PREFIX):]
            old, new = os.path.join(lib, *rel.split("/")), os.path.join(to["library"], *rel.split("/"))
            if os.path.exists(old) and not (os.path.exists(new) and os.path.getsize(new) == os.path.getsize(old)):
                raise OSError(f"{rel} didn't arrive in the new folder")
    except BaseException:
        b.close()
        os.remove(part)
        raise
    finally:
        a.close()
        b.close()
    os.replace(part, os.path.join(to["data"], "library.db"))
    return outside


def _update_startup(old_app, new_app):
    """Start with Windows, if it's on, starts the new copy."""
    launcher = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "BabelsLibrary", "start_babel.pyw")
    try:
        if os.path.exists(launcher):
            with open(launcher, encoding="utf-8") as f:
                text = f.read()
            with open(launcher, "w", encoding="utf-8") as f:
                f.write(text.replace(f"APP = {old_app!r}", f"APP = {new_app!r}"))
    except OSError as e:
        print("[inkwell] Start with Windows not updated:", e)


def _take_over(folder):
    to = _places(folder)
    new_app = os.path.join(to["app"], "app", "desktop.py")
    with open(os.path.join(store.ROOT, MOVED_TO), "w", encoding="utf-8") as f:
        f.write(to["app"])
    with open(os.path.join(store.ROOT, "MOVED.txt"), "w", encoding="utf-8") as f:
        f.write(f"Babel's Library now lives at {to['app']}\nIts library is at {to['library']}\n\n"
                f"This old copy was left as it was and starting it opens the new one. Once you're happy with the new place,\n"
                f"this folder and the old library folder are yours to delete. To go back to this copy, delete {MOVED_TO}.\n")
    _update_startup(os.path.join(os.path.dirname(os.path.abspath(__file__)), "desktop.py"), new_app)
    pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    subprocess.Popen([pyw if os.path.exists(pyw) else sys.executable, new_app], cwd=to["app"])      # it closes this one


def _run(folder):
    job = importers.JOB
    try:
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, MARK), "w", encoding="utf-8") as f:
            f.write("A move of Babel's Library into this folder is under way.\n")
        for _ in range(2):              # the second time round picks up what changed while the first was copying
            todo = [(s, d) for s, d in _all_files(folder) if not _fresh(s, d)]
            job.update(total=job["done"] + len(todo))
            for src, dst in todo:
                job["current"] = os.path.basename(src)
                _copy(src, dst)
                job["done"] += 1
                job["added"] = job["done"]
        job["current"] = "Checking everything arrived"
        outside = _new_database(folder)
        os.remove(os.path.join(folder, MARK))
        job["message"] = (f"Moved Babel's Library to {folder}: starting it from there."
                          + (f" Still in their old places: {len(outside)} files outside the library folder." if outside else ""))
        if outside:
            print("[inkwell] files outside the library folder, not moved:", outside)
        _take_over(folder)
    except Exception as e:
        job["errors"] = 1
        job["message"] = f"The move stopped: {e}. Babel's Library hasn't changed. Choose the same folder to carry on from here."
        print("[inkwell] move stopped:", e)
