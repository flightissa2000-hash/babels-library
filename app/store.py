"""SQLite storage for Babel's Library."""
import json
import os
import sqlite3
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.environ.get("INKWELL_DATA", os.path.join(ROOT, "library_data"))
FILES_DIR = os.path.join(DATA_DIR, "files")
COVERS_DIR = os.path.join(DATA_DIR, "covers")
DB_PATH = os.path.join(DATA_DIR, "library.db")

import relocate  # noqa: E402  (finishes a move to another drive before the database opens)
_RELOCATED = relocate.copy_data_if_pending(ROOT, DATA_DIR)

for d in (DATA_DIR, FILES_DIR, COVERS_DIR):
    os.makedirs(d, exist_ok=True)

# ---------- portable paths ----------
# The library can live on a drive shared by Windows and Linux. Paths are saved relative so they work on both:
#   library_folder "@/Library"  -> <folder that contains the Babel's Library folder>/Library
#   file_path "lib:Books/x.pdf" -> <library folder>/Books/x.pdf
LIB_PREFIX = "lib:"
BASE_DIR = os.path.dirname(ROOT)
_lib_root_cache = [None]


def expand_root(v):
    v = (v or "").strip()
    if v.startswith("@/"):
        return os.path.normpath(os.path.join(BASE_DIR, *[p for p in v[2:].split("/") if p]))
    return os.path.abspath(os.path.expanduser(v)) if v else v


def compact_root(path):
    """Save the library folder relative to the drive/folder Babel's Library sits in when it's there, so it survives OS changes."""
    full = os.path.abspath(os.path.expanduser(path))
    try:
        rel = os.path.relpath(full, BASE_DIR)
    except ValueError:  # different Windows drive
        return full
    if rel == "." or rel.startswith(".."):
        return full
    return "@/" + rel.replace(os.sep, "/")


def lib_root():
    if _lib_root_cache[0] is None:
        _lib_root_cache[0] = expand_root(get_settings().get("library_folder") or DEFAULT_SETTINGS["library_folder"])
    return _lib_root_cache[0]


def _inside(p, root):
    try:
        return os.path.commonpath([os.path.normcase(os.path.abspath(p)), os.path.normcase(os.path.abspath(root))]) == os.path.normcase(os.path.abspath(root))
    except ValueError:
        return False


def path_to_db(p):
    if p and os.path.isabs(p) and _inside(p, lib_root()):
        return LIB_PREFIX + os.path.relpath(p, lib_root()).replace(os.sep, "/")
    return p


def path_from_db(p, root=None):
    if p and p.startswith(LIB_PREFIX):
        return os.path.join(root or lib_root(), *[x for x in p[len(LIB_PREFIX):].split("/") if x])
    return p

_lock = threading.RLock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL DEFAULT 'article',
  title TEXT, authors TEXT DEFAULT '[]', year TEXT,
  publisher TEXT, journal TEXT, volume TEXT, issue TEXT, pages TEXT,
  doi TEXT, isbn TEXT, url TEXT, place TEXT,
  file_path TEXT, file_type TEXT, physical INTEGER DEFAULT 0,
  topic TEXT, tags TEXT DEFAULT '[]', genre TEXT, subject TEXT, fiction INTEGER,
  summary TEXT, cover_path TEXT, sha256 TEXT,
  status TEXT DEFAULT 'ready', ai_source TEXT,
  progress REAL DEFAULT 0, last_location TEXT, favorite INTEGER DEFAULT 0,
  added_at REAL, opened_at REAL
);
CREATE TABLE IF NOT EXISTS annotations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
  title TEXT DEFAULT '', note TEXT DEFAULT '', quote TEXT DEFAULT '',
  color TEXT DEFAULT 'yellow', locator TEXT DEFAULT '{}',
  created_at REAL, updated_at REAL
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS collections (
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, color TEXT DEFAULT '', created_at REAL
);
CREATE TABLE IF NOT EXISTS collection_items (
  collection_id INTEGER NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
  item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
  added_at REAL, PRIMARY KEY (collection_id, item_id)
);
CREATE INDEX IF NOT EXISTS idx_items_sha ON items(sha256);
CREATE INDEX IF NOT EXISTS idx_ann_item ON annotations(item_id);
-- phone sync: when each of your own fields (position, progress, watched...) last changed, so the newer side wins,
-- and what was deleted, so phones drop it too
CREATE TABLE IF NOT EXISTS item_clock (item_id INTEGER NOT NULL, field TEXT NOT NULL, ts REAL NOT NULL, PRIMARY KEY (item_id, field));
CREATE TABLE IF NOT EXISTS tombstones (kind TEXT NOT NULL, ref_id INTEGER NOT NULL, ts REAL NOT NULL, PRIMARY KEY (kind, ref_id));
"""
# the fields a phone can change too (phonesync.py); everything else about an item is the computer's to say
SYNC_FIELDS = ("progress", "last_location", "opened_at", "favorite", "wanted", "watched", "watched_at", "audio_pos", "direction")

DEFAULT_SETTINGS = {
    "discover_ignored": [],
    "news_county": "", "news_state": "", "news_city": "", "news_country": "United States", "news_seat": "",   # the News' Local desk
    "news_alerts": False,     # tell me about new events on the Local desk (checked in the background)
    "nyt_key": "",
    "hardcover_token": "",
    "watch_folder": os.path.join(os.path.expanduser("~"), "Library-Inbox"),
    "watch_enabled": True,
    "watch_interval": 10,
    "ollama_url": "http://localhost:11434",
    "ollama_model": "llama3.2",
    "auto_lookup": True,
    "theme": "wordtown",
    "widget_autohide": True,  # the widget's title bar stays tucked away until pointed at
    "adblock": True,          # block ads and trackers in the reading window (adblock.py)
    "search_sites": [],
    "phone_devices": [],      # paired phones (phonesync.py): id, name, token hash, last seen, files waiting to send
    "phone_topic": "",        # private ntfy.sh topic where the away-from-home address is posted
    "phone_remote": False,    # reach this library from anywhere through a Cloudflare quick tunnel      # your own search sites for the catalogue: [{"name", "url" with {q}, "cats": [...]}]
    "view": "shelf",
    "group_by": "auto",
    "start_mode": "widget",
    "widget_default_applied": False,
    "series_pass": 0,
    "obsidian_folder": "",
    "journal_fix": 0,
    "widget_locked": False,
    "widget_corner": "top-right",
    "widget_x": None,
    "widget_y": None,
    "widget_w": 340,
    "widget_h": 520,
    "main_fullscreen": False,
    "library_folder": os.path.join(os.path.expanduser("~"), "Documents", "Inkwell Library"),
    "inbox_move": True,
    "zotero_dir": os.path.join(os.path.expanduser("~"), "Zotero"),
    "tts_voice": "en_US-lessac-medium",
    "tts_speed": 1.0,
    "mini_w": 980,
    "mini_h": 760,
    "calibre_dir": os.path.join(os.path.expanduser("~"), "Calibre Library"),
    "analysis_version": 1,
    "reader_mode": {},
    "reader_width": {},
}

JSON_FIELDS = ("authors", "tags", "locked")
ITEM_FIELDS = (
    "kind", "title", "authors", "year", "publisher", "journal", "volume", "issue", "pages",
    "doi", "isbn", "url", "place", "file_path", "file_type", "physical", "topic", "tags",
    "genre", "subject", "fiction", "summary", "cover_path", "sha256", "status", "ai_source",
    "progress", "last_location", "favorite", "added_at", "opened_at",
    "direction", "series", "orig_name", "source", "album", "album_artist", "track", "disc", "season", "episode",
    "duration", "series_index", "locked", "format", "watched", "watched_at",
    "audio_dir", "audio_status", "audio_pos", "wanted",
    "expires_at",          # a web page saved for 30 days: when it's due (the app asks before anything is removed)
)


def conn():
    c = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    return c


def drive_ok():
    """Is the drive holding the data folder there? (It may be a USB drive that has dropped out.)"""
    return os.path.isfile(DB_PATH)


def reopen():
    """After the data drive disappeared and came back, the old database handle is dead: open a fresh one."""
    global _db
    with _lock:
        old, _db = _db, conn()
        try:
            old.close()
        except Exception:
            pass


_db = conn()
with _lock:
    _db.executescript(SCHEMA)
    _cols = {r[1] for r in _db.execute("PRAGMA table_info(items)")}
    for _c, _t in (("direction", "TEXT"), ("series", "TEXT"), ("orig_name", "TEXT"), ("source", "TEXT"),
                   ("album", "TEXT"), ("album_artist", "TEXT"), ("track", "INTEGER"), ("disc", "INTEGER"),
                   ("season", "INTEGER"), ("episode", "INTEGER"), ("duration", "REAL"), ("series_index", "REAL"),
                   ("locked", "TEXT"), ("format", "TEXT"), ("watched", "INTEGER DEFAULT 0"), ("watched_at", "REAL"),
                   ("audio_dir", "TEXT"), ("audio_status", "TEXT"), ("audio_pos", "TEXT"), ("wanted", "INTEGER DEFAULT 0"),
                   ("updated_at", "REAL"), ("expires_at", "REAL")):
        if _c not in _cols:
            _db.execute(f"ALTER TABLE items ADD COLUMN {_c} {_t}")
    _db.execute("UPDATE items SET updated_at=COALESCE(opened_at, added_at, 0) WHERE updated_at IS NULL")
    _db.execute("CREATE INDEX IF NOT EXISTS idx_items_upd ON items(updated_at)")
    _db.commit()


def _row_item(r):
    if r is None:
        return None
    d = dict(r)
    for f in JSON_FIELDS:
        try:
            d[f] = json.loads(d.get(f) or "[]")
        except Exception:
            d[f] = []
    d["collections"] = [int(x) for x in str(d.pop("coll", "") or "").split(",") if x]
    d["has_file"] = bool(d.get("file_path"))
    d["has_audiobook"] = d.get("audio_status") in ("ready", "building", "queued") and bool(d.get("audio_dir")) or d.get("audio_status") == "ready"
    try:
        d["audio_pos"] = json.loads(d["audio_pos"]) if d.get("audio_pos") else None
    except Exception:
        d["audio_pos"] = None
    d.pop("audio_dir", None)
    cp = os.path.join(COVERS_DIR, d["cover_path"]) if d.get("cover_path") else None
    try:
        d["cover_v"] = f'{int(os.path.getmtime(cp)) % 10000000}{len(d["cover_path"])}' if cp else ""
        d["has_cover"] = bool(cp)
    except OSError:
        d["cover_v"], d["has_cover"] = "", False
    d.pop("cover_path", None)
    d["file_location"] = resolve_file(d.pop("file_path", None))
    return d


def _enc(field, value):
    if field in JSON_FIELDS:
        return json.dumps(value or [])
    if field == "file_path":
        return path_to_db(value)
    if field in ("physical", "favorite", "wanted"):
        return 1 if value else 0
    if field == "fiction":
        return None if value is None or value == "" else (1 if value in (True, 1, "1", "true", "fiction") else 0)
    return value


# ---------- items ----------
def count_status(status):
    with _lock:
        return _db.execute("SELECT COUNT(*) FROM items WHERE status=?", (status,)).fetchone()[0]


def list_items():
    with _lock:
        rows = _db.execute("SELECT i.*, (SELECT COUNT(*) FROM annotations a WHERE a.item_id=i.id) AS ann_count, (SELECT group_concat(collection_id) FROM collection_items c WHERE c.item_id=i.id) AS coll FROM items i ORDER BY added_at DESC").fetchall()
    return [_row_item(r) for r in rows]


def get_item(item_id, raw=False):
    with _lock:
        r = _db.execute("SELECT i.*, (SELECT COUNT(*) FROM annotations a WHERE a.item_id=i.id) AS ann_count, (SELECT group_concat(collection_id) FROM collection_items c WHERE c.item_id=i.id) AS coll FROM items i WHERE id=?", (item_id,)).fetchone()
    if raw:
        if not r:
            return None
        d = dict(r)
        d["file_path"] = path_from_db(d.get("file_path"))
        return d
    return _row_item(r)


def find_dupe(doi=None, isbn=None, title=None):
    with _lock:
        if doi:
            r = _db.execute("SELECT id FROM items WHERE lower(doi)=lower(?)", (doi,)).fetchone()
            if r:
                return r["id"]
        if isbn:
            r = _db.execute("SELECT id FROM items WHERE isbn=?", (isbn,)).fetchone()
            if r:
                return r["id"]
        if title and len(title) > 6:
            r = _db.execute("SELECT id FROM items WHERE lower(title)=lower(?)", (title.strip(),)).fetchone()
            if r:
                return r["id"]
    return None


def all_file_paths():
    with _lock:
        return [(r["id"], path_from_db(r["file_path"]), r["kind"], r["genre"]) for r in _db.execute("SELECT id, file_path, kind, genre FROM items WHERE file_path IS NOT NULL")]


def materialize_paths(root=None):
    """Turn library-relative paths into full paths (before the library folder setting changes)."""
    root = root or lib_root()
    with _lock:
        rows = _db.execute("SELECT id, file_path FROM items WHERE file_path LIKE 'lib:%'").fetchall()
        _db.executemany("UPDATE items SET file_path=? WHERE id=?", [(path_from_db(r["file_path"], root), r["id"]) for r in rows])
        _db.commit()


def compact_paths():
    """Store every file inside the library folder relative to it (portable between Windows and Linux)."""
    with _lock:
        rows = _db.execute("SELECT id, file_path FROM items WHERE file_path IS NOT NULL AND file_path NOT LIKE 'lib:%'").fetchall()
        upd = [(path_to_db(r["file_path"]), r["id"]) for r in rows if path_to_db(r["file_path"]) != r["file_path"]]
        _db.executemany("UPDATE items SET file_path=? WHERE id=?", upd)
        _db.commit()
    return len(upd)


def find_by_sha(sha):
    with _lock:
        r = _db.execute("SELECT id FROM items WHERE sha256=?", (sha,)).fetchone()
    return r["id"] if r else None


def create_item(data):
    data = dict(data)
    data.setdefault("added_at", time.time())
    cols = [f for f in ITEM_FIELDS if f in data] + ["updated_at"]
    vals = [_enc(f, data[f]) for f in cols[:-1]] + [time.time()]
    with _lock:
        cur = _db.execute(
            f"INSERT INTO items ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", vals)
        _db.commit()
        return cur.lastrowid


def update_item(item_id, data, clock=None):
    """clock: when the change was made (a phone's edit arriving later); now if not given."""
    cols = [f for f in ITEM_FIELDS if f in data]
    if not cols:
        return
    vals = [_enc(f, data[f]) for f in cols]
    now = time.time()
    with _lock:
        _db.execute(f"UPDATE items SET {','.join(c + '=?' for c in cols)}, updated_at=? WHERE id=?", vals + [now, item_id])
        _db.executemany("INSERT OR REPLACE INTO item_clock (item_id, field, ts) VALUES (?,?,?)",
                        [(item_id, f, clock or now) for f in cols if f in SYNC_FIELDS])
        _db.commit()


def item_clocks(item_ids=None):
    """{item_id: {field: ts}} for the fields phones can change."""
    with _lock:
        rows = _db.execute("SELECT item_id, field, ts FROM item_clock").fetchall()
    out = {}
    for r in rows:
        if item_ids is None or r["item_id"] in item_ids:
            out.setdefault(r["item_id"], {})[r["field"]] = r["ts"]
    return out


def tombstone(kind, ref_id):
    with _lock:
        _db.execute("INSERT OR REPLACE INTO tombstones (kind, ref_id, ts) VALUES (?,?,?)", (kind, int(ref_id), time.time()))
        _db.commit()


def tombstones_since(ts):
    with _lock:
        return [dict(r) for r in _db.execute("SELECT kind, ref_id, ts FROM tombstones WHERE ts>?", (ts,))]


def resolve_file(p):
    """file_path: 'lib:...' (inside the library folder), absolute (elsewhere), or plain relative (very old installs)."""
    if not p:
        return None
    if p.startswith(LIB_PREFIX):
        return path_from_db(p)
    return p if os.path.isabs(p) else os.path.join(FILES_DIR, p)


def delete_item(item_id, delete_file=False):
    raw = get_item(item_id, raw=True)
    if not raw:
        return
    shared = raw.get("cover_path") and _db.execute("SELECT COUNT(*) FROM items WHERE cover_path=? AND id<>?", (raw["cover_path"], item_id)).fetchone()[0]
    targets = [] if shared else [(raw.get("cover_path"), COVERS_DIR)]
    if delete_file or (raw.get("file_path") and not os.path.isabs(raw["file_path"])):
        targets.append((raw.get("file_path"), FILES_DIR))
    for p, base in targets:
        if p:
            try:
                os.remove(p if os.path.isabs(p) else os.path.join(base, p))
            except OSError:
                pass
    with _lock:
        _db.execute("DELETE FROM annotations WHERE item_id=?", (item_id,))
        _db.execute("DELETE FROM collection_items WHERE item_id=?", (item_id,))
        _db.execute("DELETE FROM items WHERE id=?", (item_id,))
        _db.execute("DELETE FROM item_clock WHERE item_id=?", (item_id,))
        _db.execute("INSERT OR REPLACE INTO tombstones (kind, ref_id, ts) VALUES ('item',?,?)", (item_id, time.time()))
        try:
            _db.execute("UPDATE media_log SET item_id=NULL WHERE item_id=?", (item_id,))  # keep reviews of deleted items
        except sqlite3.OperationalError:
            pass
        _db.commit()


# ---------- collections ----------
def list_collections():
    with _lock:
        rows = _db.execute("SELECT c.*, (SELECT COUNT(*) FROM collection_items x WHERE x.collection_id=c.id) AS count FROM collections c ORDER BY lower(name)").fetchall()
    return [dict(r) for r in rows]


def create_collection(name, color=""):
    name = (name or "").strip()[:80]
    if not name:
        raise ValueError("Give the collection a name.")
    with _lock:
        cur = _db.execute("INSERT INTO collections (name, color, created_at) VALUES (?,?,?)", (name, color or "", time.time()))
        _db.commit()
        return cur.lastrowid


def update_collection(cid, data):
    with _lock:
        if data.get("name", "").strip():
            _db.execute("UPDATE collections SET name=? WHERE id=?", (data["name"].strip()[:80], cid))
        if "color" in data:
            _db.execute("UPDATE collections SET color=? WHERE id=?", (data["color"] or "", cid))
        _db.commit()


def delete_collection(cid):
    with _lock:
        _db.execute("DELETE FROM collection_items WHERE collection_id=?", (cid,))
        _db.execute("DELETE FROM collections WHERE id=?", (cid,))
        _db.commit()


def collection_add(cid, item_ids):
    with _lock:
        _db.executemany("INSERT OR IGNORE INTO collection_items (collection_id, item_id, added_at) VALUES (?,?,?)",
                        [(cid, int(i), time.time()) for i in item_ids])
        _db.commit()


def collection_remove(cid, item_ids):
    with _lock:
        _db.executemany("DELETE FROM collection_items WHERE collection_id=? AND item_id=?", [(cid, int(i)) for i in item_ids])
        _db.commit()


# ---------- annotations ----------
def _row_ann(r):
    d = dict(r)
    try:
        d["locator"] = json.loads(d.get("locator") or "{}")
    except Exception:
        d["locator"] = {}
    return d


def list_annotations(item_id=None):
    with _lock:
        if item_id is None:
            rows = _db.execute("SELECT * FROM annotations ORDER BY item_id, created_at").fetchall()
        else:
            rows = _db.execute("SELECT * FROM annotations WHERE item_id=? ORDER BY created_at", (item_id,)).fetchall()
    return [_row_ann(r) for r in rows]


def create_annotation(item_id, data):
    now = time.time()
    with _lock:
        cur = _db.execute(
            "INSERT INTO annotations (item_id,title,note,quote,color,locator,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)",
            (item_id, data.get("title", "") or "", data.get("note", "") or "", data.get("quote", "") or "",
             data.get("color", "yellow"), json.dumps(data.get("locator", {})), now, now))
        _db.commit()
        r = _db.execute("SELECT * FROM annotations WHERE id=?", (cur.lastrowid,)).fetchone()
    return _row_ann(r)


def update_annotation(ann_id, data):
    sets, vals = [], []
    for f in ("title", "note", "quote", "color"):
        if f in data:
            sets.append(f + "=?")
            vals.append(data[f] or "")
    if "locator" in data:
        sets.append("locator=?")
        vals.append(json.dumps(data["locator"]))
    sets.append("updated_at=?")
    vals.append(time.time())
    with _lock:
        _db.execute(f"UPDATE annotations SET {','.join(sets)} WHERE id=?", vals + [ann_id])
        _db.commit()
        r = _db.execute("SELECT * FROM annotations WHERE id=?", (ann_id,)).fetchone()
    return _row_ann(r) if r else None


def delete_annotation(ann_id):
    with _lock:
        _db.execute("DELETE FROM annotations WHERE id=?", (ann_id,))
        _db.execute("INSERT OR REPLACE INTO tombstones (kind, ref_id, ts) VALUES ('annotation',?,?)", (ann_id, time.time()))
        _db.commit()


# ---------- settings ----------
def _foreign_path(p):
    """A path saved on the other operating system (e.g. C:\\... seen on Linux, or /home/... on Windows)."""
    import re as _re
    if not isinstance(p, str) or not p or p.startswith(("~", "@/")):
        return False
    is_win = bool(_re.match(r"^[A-Za-z]:[\\/]", p))
    return is_win != (os.name == "nt")


def get_settings():
    s = dict(DEFAULT_SETTINGS)
    with _lock:
        for r in _db.execute("SELECT key, value FROM settings"):
            try:
                s[r["key"]] = json.loads(r["value"])
            except Exception:
                pass
    # folders picked on Windows don't exist on Linux (and the reverse): fall back to this computer's defaults
    for k in ("watch_folder", "zotero_dir", "calibre_dir"):
        if _foreign_path(s.get(k)):
            s[k] = DEFAULT_SETTINGS.get(k, "")
    if _foreign_path(s.get("library_folder")):
        s["library_folder"] = "@/Library"
    return s


def set_settings(data):
    if data.get("library_folder"):
        data = {**data, "library_folder": compact_root(expand_root(data["library_folder"]))}
        _lib_root_cache[0] = None
    with _lock:
        for k, v in data.items():
            if k in DEFAULT_SETTINGS:
                _db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (k, json.dumps(v)))
        _db.commit()
    return get_settings()
