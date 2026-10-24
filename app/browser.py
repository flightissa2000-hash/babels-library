"""The browser window's memory: history and saved passwords.

Kept in its own database on C: (%LOCALAPPDATA%\\BabelsLibrary\\browser.db), not in the library database: it never
goes to phones, library backups or the USB drive. Every password is encrypted with Windows' DPAPI, so only your
Windows account on this computer can read it back (the database file alone is useless to anyone else).
"""
import csv
import io
import json
import os
import re
import sqlite3
import threading
import time
import urllib.parse

DIR = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "BabelsLibrary")
DB = os.path.join(DIR, "browser.db")
_lock = threading.RLock()
_db = None

# searching: DuckDuckGo, or Wikipedia when asked (the W button)
SEARCH = {"duckduckgo": ("DuckDuckGo", "https://duckduckgo.com/?q={q}"), "wikipedia": ("Wikipedia", "https://en.wikipedia.org/w/index.php?search={q}")}


def db():
    global _db
    with _lock:
        if _db is None:
            os.makedirs(DIR, exist_ok=True)
            _db = sqlite3.connect(DB, check_same_thread=False, timeout=30)
            _db.row_factory = sqlite3.Row
            _db.executescript("""
                CREATE TABLE IF NOT EXISTS history (id INTEGER PRIMARY KEY AUTOINCREMENT, url TEXT NOT NULL, title TEXT, visited_at REAL);
                CREATE INDEX IF NOT EXISTS idx_hist_time ON history(visited_at);
                CREATE TABLE IF NOT EXISTS logins (id INTEGER PRIMARY KEY AUTOINCREMENT, site TEXT NOT NULL, url TEXT, username TEXT,
                    secret BLOB, note TEXT DEFAULT '', created_at REAL, updated_at REAL, used_at REAL);
                CREATE INDEX IF NOT EXISTS idx_login_site ON logins(site);
                CREATE TABLE IF NOT EXISTS prefs (key TEXT PRIMARY KEY, value TEXT);
                CREATE TABLE IF NOT EXISTS bookmarks (id INTEGER PRIMARY KEY AUTOINCREMENT, url TEXT NOT NULL UNIQUE, title TEXT, added_at REAL);
            """)
            _db.commit()
        return _db


# ---------------------------------------------------------------- DPAPI (Windows' per-user encryption)
if os.name == "nt":
    import ctypes
    from ctypes import wintypes

    class _Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    _crypt32, _kernel32 = ctypes.windll.crypt32, ctypes.windll.kernel32
    _ENTROPY = b"BabelsLibrary-browser-v1"

    def _call(fn, data):
        buf = ctypes.create_string_buffer(data, len(data))
        inp = _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
        ent_buf = ctypes.create_string_buffer(_ENTROPY, len(_ENTROPY))
        ent = _Blob(len(_ENTROPY), ctypes.cast(ent_buf, ctypes.POINTER(ctypes.c_char)))
        out = _Blob()
        if not fn(ctypes.byref(inp), None, ctypes.byref(ent), None, None, 0x1, ctypes.byref(out)):   # 0x1: no UI
            raise OSError("Windows couldn't encrypt or decrypt the password")
        try:
            return ctypes.string_at(out.pbData, out.cbData)
        finally:
            _kernel32.LocalFree(out.pbData)

    def protect(text):
        return _call(lambda i, d, e, r, p, f, o: _crypt32.CryptProtectData(i, "Babel's Library", e, r, p, f, o), text.encode("utf-8"))

    def unprotect(blob):
        return _call(lambda i, d, e, r, p, f, o: _crypt32.CryptUnprotectData(i, None, e, r, p, f, o), bytes(blob)).decode("utf-8")
else:
    def protect(text):
        raise OSError("Saved passwords need Windows")

    def unprotect(blob):
        raise OSError("Saved passwords need Windows")


# ---------------------------------------------------------------- sites
def site_of(url):
    """example.com for https://login.example.com/path: logins are shared across a site's subdomains."""
    try:
        host = (urllib.parse.urlparse(url if "://" in url else "https://" + url).hostname or "").lower()
    except ValueError:
        return ""
    host = host.removeprefix("www.")
    parts = host.split(".")
    if len(parts) > 2 and len(parts[-1]) == 2 and parts[-2] in ("co", "com", "net", "org", "ac", "or", "ne", "go", "gov", "edu"):
        return ".".join(parts[-3:])
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def pref(key, default=None):
    r = db().execute("SELECT value FROM prefs WHERE key=?", (key,)).fetchone()
    return json.loads(r["value"]) if r else default


def set_pref(key, value):
    with _lock:
        db().execute("INSERT OR REPLACE INTO prefs (key, value) VALUES (?,?)", (key, json.dumps(value)))
        db().commit()


def to_url(text, wiki=False):
    """What was typed in the address bar: an address, or words to search for (on Wikipedia with wiki=True)."""
    t = (text or "").strip()
    if not t:
        return ""
    if not wiki:
        if re.match(r"^(https?|file)://", t, re.I):
            return t
        if re.match(r"^(localhost|\d{1,3}(\.\d{1,3}){3})(:\d+)?(/.*)?$", t) or (" " not in t and re.match(r"^[\w-]+(\.[\w-]+)+(:\d+)?(/.*)?$", t)):
            return ("http://" if t.startswith(("localhost", "127.")) else "https://") + t
    return SEARCH["wikipedia" if wiki else "duckduckgo"][1].replace("{q}", urllib.parse.quote_plus(t))


# ---------------------------------------------------------------- history
def visit(url, title=""):
    if not url or not re.match(r"^https?://", url) or url.startswith(("http://localhost", "http://127.0.0.1")):
        return
    with _lock:
        last = db().execute("SELECT id, url, visited_at FROM history ORDER BY id DESC LIMIT 1").fetchone()
        if last and last["url"] == url:          # the same page again (reload, title arriving late): update it
            db().execute("UPDATE history SET title=COALESCE(NULLIF(?, ''), title), visited_at=? WHERE id=?", (title, time.time(), last["id"]))
        elif last and site_of(last["url"]) == site_of(url) and time.time() - (last["visited_at"] or 0) < 4:
            # a redirect a moment later on the same site (search pages add their own bits): one visit, not two
            db().execute("UPDATE history SET url=?, title=COALESCE(NULLIF(?, ''), title), visited_at=? WHERE id=?", (url, title, time.time(), last["id"]))
        else:
            db().execute("INSERT INTO history (url, title, visited_at) VALUES (?,?,?)", (url, title, time.time()))
        db().commit()


def history(q="", limit=300, before=None):
    sql, args = "SELECT id, url, title, visited_at FROM history WHERE 1=1", []
    for w in (q or "").lower().split():
        sql += " AND (lower(url) LIKE ? OR lower(title) LIKE ?)"
        args += [f"%{w}%", f"%{w}%"]
    if before:
        sql += " AND visited_at < ?"
        args.append(float(before))
    sql += " ORDER BY visited_at DESC LIMIT ?"
    args.append(int(limit))
    return [dict(r) for r in db().execute(sql, args)]


def top_sites(n=8):
    rows = db().execute("SELECT url, title, COUNT(*) AS n, MAX(visited_at) AS last FROM history WHERE visited_at > ? GROUP BY url ORDER BY n DESC, last DESC LIMIT 200",
                        (time.time() - 60 * 86400,)).fetchall()
    out, seen = [], set()
    for r in rows:
        s = site_of(r["url"])
        if s and s not in seen:
            seen.add(s)
            out.append({"url": r["url"], "title": r["title"] or s, "site": s})
        if len(out) >= n:
            break
    return out


# ---------------------------------------------------------------- bookmarks (☆ on the bar; shown on the start page)
def bookmarks():
    return [dict(r) | {"site": site_of(r["url"])} for r in db().execute("SELECT id, url, title, added_at FROM bookmarks ORDER BY added_at")]


def is_bookmarked(url):
    return bool(url) and db().execute("SELECT 1 FROM bookmarks WHERE url=?", (url,)).fetchone() is not None


def add_bookmark(url, title=""):
    if not url or not re.match(r"^https?://", url):
        return
    with _lock:
        db().execute("INSERT INTO bookmarks (url, title, added_at) VALUES (?,?,?) ON CONFLICT(url) DO UPDATE SET title=COALESCE(NULLIF(excluded.title, ''), title)",
                     (url, (title or "")[:300], time.time()))
        db().commit()


def remove_bookmark(url=None, bid=None):
    with _lock:
        if bid is not None:
            db().execute("DELETE FROM bookmarks WHERE id=?", (int(bid),))
        else:
            db().execute("DELETE FROM bookmarks WHERE url=?", (url,))
        db().commit()


def forget_history(ids=None, since=None):
    with _lock:
        if ids:
            db().executemany("DELETE FROM history WHERE id=?", [(int(i),) for i in ids])
        elif since is not None:
            db().execute("DELETE FROM history WHERE visited_at >= ?", (float(since),))
        db().commit()


# ---------------------------------------------------------------- saved passwords
def logins(q="", site=None, reveal=False):
    sql, args = "SELECT * FROM logins WHERE 1=1", []
    if site:
        sql += " AND site=?"
        args.append(site)
    for w in (q or "").lower().split():
        sql += " AND (lower(site) LIKE ? OR lower(username) LIKE ? OR lower(url) LIKE ?)"
        args += [f"%{w}%"] * 3
    sql += " ORDER BY site, username"
    out = []
    for r in db().execute(sql, args):
        d = {k: r[k] for k in ("id", "site", "url", "username", "note", "created_at", "updated_at", "used_at")}
        if reveal:
            d["password"] = unprotect(r["secret"])
        out.append(d)
    return out


def reveal(login_id):
    r = db().execute("SELECT secret FROM logins WHERE id=?", (int(login_id),)).fetchone()
    if not r:
        raise LookupError("No such login.")
    return unprotect(r["secret"])


def save_login(url, username, password, note="", login_id=None):
    site = site_of(url)
    if not site:
        raise ValueError("That doesn't look like a website address.")
    if not password:
        raise ValueError("There's no password to save.")
    now = time.time()
    with _lock:
        if login_id:
            db().execute("UPDATE logins SET site=?, url=?, username=?, secret=?, note=?, updated_at=? WHERE id=?",
                         (site, url, username or "", protect(password), note or "", now, int(login_id)))
        else:
            same = db().execute("SELECT id FROM logins WHERE site=? AND username=?", (site, username or "")).fetchone()
            if same:
                db().execute("UPDATE logins SET url=?, secret=?, updated_at=? WHERE id=?", (url, protect(password), now, same["id"]))
                login_id = same["id"]
            else:
                login_id = db().execute("INSERT INTO logins (site, url, username, secret, note, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
                                        (site, url, username or "", protect(password), note or "", now, now)).lastrowid
        db().commit()
    return login_id


def known(site, username, password):
    """Is exactly this login saved already (so there's nothing to offer to save)?"""
    for r in db().execute("SELECT secret FROM logins WHERE site=? AND username=?", (site, username or "")):
        try:
            if unprotect(r["secret"]) == password:
                return True
        except OSError:
            pass
    return False


def used(login_id):
    with _lock:
        db().execute("UPDATE logins SET used_at=? WHERE id=?", (time.time(), int(login_id)))
        db().commit()


def delete_login(login_id):
    with _lock:
        db().execute("DELETE FROM logins WHERE id=?", (int(login_id),))
        db().commit()


def import_csv(text):
    """Passwords exported from Chrome, Edge, Brave, Opera, Firefox, Bitwarden, 1Password, LastPass, Proton Pass and
    most others: a CSV file whose header names the address, username and password columns."""
    text = text.lstrip("﻿")
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        raise ValueError("The file is empty.")
    head = [h.strip().lower() for h in rows[0]]

    def col(*names):
        for n in names:
            if n in head:
                return head.index(n)
        return None
    c_url = col("url", "login_uri", "website", "web site", "origin", "login url", "uri", "hostname")
    c_user = col("username", "login_username", "user name", "login", "email", "user")
    c_pass = col("password", "login_password", "pass")
    c_name = col("name", "title")
    c_note = col("note", "notes", "extra")
    if c_url is None or c_pass is None:
        raise ValueError("This doesn't look like a password export: it needs columns for the website address and the password.")
    added = updated = skipped = 0
    for r in rows[1:]:
        get = lambda c: (r[c].strip() if c is not None and c < len(r) else "")
        url, user, pw = get(c_url), get(c_user), get(c_pass)
        if not url and c_name is not None:
            url = get(c_name)
        if not url or not pw or not site_of(url):
            skipped += 1
            continue
        if known(site_of(url), user, pw):
            skipped += 1
            continue
        existed = db().execute("SELECT 1 FROM logins WHERE site=? AND username=?", (site_of(url), user)).fetchone()
        save_login(url if "://" in url else "https://" + url, user, pw, get(c_note))
        if existed:
            updated += 1
        else:
            added += 1
    return {"added": added, "updated": updated, "skipped": skipped}
