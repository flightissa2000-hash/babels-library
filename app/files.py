"""The main library folder: where every PDF / EPUB / comic Babel's Library manages lives on disk.

Layout:  <library>/Articles, <library>/Books, <library>/Graphic Novels, <library>/Graphic Novels/Manga
"""
import os
import re
import shutil
import time

import media
import store

READING_EXT = (".pdf", ".epub", ".cbz", ".cbr", ".cb7", ".cbt")
SUPPORTED = READING_EXT + media.MEDIA_EXT
COMIC_EXT = (".cbz", ".cbr", ".cb7", ".cbt")
KIND_DIRS = {"article": "Articles", "book": "Books", "graphic": "Graphic Novels", "music": "Music", "tv": "TV", "movie": "Movies"}
MEDIA_KINDS = ("music", "tv", "movie")


def library_root():
    root = store.lib_root()
    os.makedirs(root, exist_ok=True)
    return root


def kind_for_ext(ext):
    ext = ext.lower()
    if ext in media.AUDIO_EXT:
        return "music"
    if ext in media.VIDEO_EXT:
        return "movie"
    return "graphic" if ext in COMIC_EXT else ("book" if ext == ".epub" else "article")


def folder_for(kind, genre=None, root=None, meta=None, fmt=None):
    root = root or library_root()
    sub = KIND_DIRS.get(kind, "Articles")
    if kind == "graphic" and ((fmt or "") == "manga" or (genre or "").lower() == "manga"):
        sub = os.path.join(sub, "Manga")
    if kind in MEDIA_KINDS and meta is not None:
        sub = media.subfolder(kind, meta)
    d = os.path.join(root, sub)
    os.makedirs(d, exist_ok=True)
    return d


def clean_filename(name):
    base, ext = os.path.splitext(os.path.basename(name))
    base = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", base).strip(" .") or "file"
    return base[:150] + ext.lower()


def unique_path(folder, name):
    name = clean_filename(name)
    base, ext = os.path.splitext(name)
    p, n = os.path.join(folder, name), 2
    while os.path.exists(p):
        p = os.path.join(folder, f"{base} ({n}){ext}")
        n += 1
    return p


def inside(path, root):
    try:
        return os.path.commonpath([os.path.abspath(path), os.path.abspath(root)]) == os.path.abspath(root)
    except ValueError:
        return False


CHUNK = 8 << 20
FLUSH_EVERY = 64 << 20


def _same_block(f, g, off, n=1 << 20):
    f.seek(off)
    g.seek(off)
    return f.read(n) == g.read(n)


def safe_copy(src, dest):
    """Copy that can't leave a broken file behind. Writes to <dest>.part in chunks, flushes to the disk as it goes
    (a USB drive that drops out mid-copy otherwise loses Windows' cached writes silently while the copy 'succeeds'),
    checks size and sampled blocks, then renames into place. Raises OSError and removes the .part on any failure."""
    part = dest + ".part"
    size = os.path.getsize(src)
    try:
        with open(src, "rb") as f, open(part, "wb") as g:
            since = 0
            while True:
                buf = f.read(CHUNK)
                if not buf:
                    break
                g.write(buf)
                since += len(buf)
                if since >= FLUSH_EVERY:
                    g.flush()
                    os.fsync(g.fileno())
                    since = 0
                    time.sleep(0.02)  # short breather so slow drives never face one long write burst
            g.flush()
            os.fsync(g.fileno())
        if os.path.getsize(part) != size:
            raise OSError(f"copy of {os.path.basename(src)} came out the wrong size")
        with open(src, "rb") as f, open(part, "rb") as g:
            offs = {0, max(0, size - (1 << 20))} | {(size // 8) * i for i in range(1, 8)}
            if not all(_same_block(f, g, o) for o in sorted(offs)):
                raise OSError(f"copy of {os.path.basename(src)} doesn't match the original")
        shutil.copystat(src, part)
        os.replace(part, dest)
    except BaseException:
        try:
            os.remove(part)
        except OSError:
            pass
        raise
    return dest


def safe_move(src, dest):
    """Rename when possible; across drives copy safely first and only then delete the original."""
    try:
        if os.path.splitdrive(os.path.abspath(src))[0].lower() == os.path.splitdrive(os.path.abspath(dest))[0].lower():
            os.rename(src, dest)
            return dest
    except OSError:
        pass
    if os.path.isdir(src):
        return shutil.move(src, dest, copy_function=safe_copy)
    safe_copy(src, dest)
    os.remove(src)
    return dest


def place_new(src, filename, kind, move=False, genre=None, meta=None, fmt=None):
    """Copy (or move) a file into the library folder. Files already inside it are used where they are."""
    root = library_root()
    if inside(src, root):
        return os.path.abspath(src)
    dest = unique_path(folder_for(kind, genre, root, meta, fmt), filename)
    if move:
        try:
            return safe_move(src, dest)
        except PermissionError:
            pass  # the original is open in another program: copy it instead (the copy itself has been checked)
        if os.path.exists(dest):
            return dest
    return safe_copy(src, dest)


def refile(item_id):
    """After sorting, move a managed file into the right sub-folder (e.g. a PDF that turned out to be a book)."""
    raw = store.get_item(item_id, raw=True)
    if not raw or not raw.get("file_path") or not os.path.isabs(raw["file_path"]):
        return
    cur = raw["file_path"]
    root = library_root()
    if not os.path.exists(cur) or not inside(cur, root):
        return
    if raw["kind"] in MEDIA_KINDS:
        return  # media is filed by artist/album or series/season at import
    managed = [os.path.join(root, d) for d in ("Articles", "Books", "Graphic Novels")]
    if not any(os.path.dirname(cur) == m or os.path.dirname(cur) == os.path.join(m, "Manga") for m in managed):
        return  # the user's own sub-folder: leave it alone
    want = folder_for(raw["kind"], raw.get("genre"), root, fmt=raw.get("format"))
    if os.path.dirname(cur) == want:
        return
    dest = unique_path(want, os.path.basename(cur))
    try:
        safe_move(cur, dest)
        store.update_item(item_id, {"file_path": dest})
    except OSError as e:
        print("[inkwell] couldn't move file:", e)


def migrate_legacy():
    """Older versions kept files hidden in library_data/files; move them into the library folder."""
    for item_id, fp, kind, genre in store.all_file_paths():
        if fp and not os.path.isabs(fp):
            src = os.path.join(store.FILES_DIR, fp)
            if not os.path.exists(src):
                continue
            name = re.sub(r"^[0-9a-f]{12}-", "", fp)
            dest = unique_path(folder_for(kind or "article", genre), name)
            try:
                safe_move(src, dest)
                store.update_item(item_id, {"file_path": dest})
            except OSError as e:
                print("[inkwell] migrate failed:", e)


def move_library(old_root, new_root, log=print):
    """Library folder changed in Settings: carry every file inside the old folder across."""
    old_root, new_root = os.path.abspath(os.path.expanduser(old_root)), os.path.abspath(os.path.expanduser(new_root))
    if old_root == new_root:
        return 0
    os.makedirs(new_root, exist_ok=True)
    moved = 0
    for item_id, fp, kind, genre in store.all_file_paths():
        if fp and os.path.isabs(fp) and inside(fp, old_root) and os.path.exists(fp):
            rel = os.path.relpath(fp, old_root)
            dest = os.path.join(new_root, rel)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            if os.path.exists(dest):
                dest = unique_path(os.path.dirname(dest), os.path.basename(dest))
            try:
                safe_move(fp, dest)
                store.update_item(item_id, {"file_path": dest})
                moved += 1
            except OSError as e:
                log(f"Couldn't move {os.path.basename(fp)}: {e}")
    # generated audiobooks travel with the library
    ab = os.path.join(old_root, "Audiobooks")
    if os.path.isdir(ab):
        try:
            dest = os.path.join(new_root, "Audiobooks")
            if os.path.exists(dest):
                for name in os.listdir(ab):
                    if not os.path.exists(os.path.join(dest, name)):
                        safe_move(os.path.join(ab, name), os.path.join(dest, name))
            else:
                safe_move(ab, dest)
        except OSError as e:
            log(f"Couldn't move the audiobooks: {e}")
    return moved
