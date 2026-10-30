"""Reading / watching log and review journals.

media_log: one row per thing you've finished (or are reviewing) - a book, film or show - in the library or not,
           with your score, the date you finished it, and a link to read about it.
journal:   dated entries for one log row; together they make that book's review, written over time.

Obsidian import: tables with Title / Link / Thoughts / Date columns become log rows; [[Thoughts]] notes become
the first journal entry of the matching row (notes no table points at get a row of their own).
"""
import datetime
import os
import re
import time
import urllib.parse

import store

SCHEMA = """
CREATE TABLE IF NOT EXISTS media_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT, item_id INTEGER, title TEXT NOT NULL, kind TEXT DEFAULT 'book',
  link TEXT, score REAL, finished TEXT, source TEXT, created_at REAL, updated_at REAL
);
CREATE TABLE IF NOT EXISTS journal (
  id INTEGER PRIMARY KEY AUTOINCREMENT, log_id INTEGER NOT NULL REFERENCES media_log(id) ON DELETE CASCADE,
  body TEXT NOT NULL DEFAULT '', created_at REAL, updated_at REAL, source TEXT
);
CREATE INDEX IF NOT EXISTS journal_log ON journal(log_id);
"""
KINDS = ("book", "movie", "show", "game", "other", "writing")      # (writing: the writing notebook's pages)
STATUSES = ("finished", "reading", "hold", "dropped", "")
with store._lock:
    store._db.executescript(SCHEMA)
    if "status" not in {r[1] for r in store._db.execute("PRAGMA table_info(media_log)")}:
        store._db.execute("ALTER TABLE media_log ADD COLUMN status TEXT")
        store._db.execute("UPDATE media_log SET status='finished' WHERE finished IS NOT NULL AND finished<>''")
    if "profile_id" not in {r[1] for r in store._db.execute("PRAGMA table_info(media_log)")}:
        store._db.execute("ALTER TABLE media_log ADD COLUMN profile_id INTEGER DEFAULT 1")     # whose journal it is
    store._db.commit()


def _mine():
    """Each profile keeps its own journal (the app itself, with no profile, sees all of them)."""
    pid = store.profile()
    return ("", ()) if pid is None else (" AND profile_id=?", (pid,))


def _q(sql, args=(), one=False, commit=False):
    with store._lock:
        cur = store._db.execute(sql, args)
        if commit:
            store._db.commit()
            return cur.lastrowid
        rows = cur.fetchall()
    rows = [dict(r) for r in rows]
    return (rows[0] if rows else None) if one else rows


# ---------------------------------------------------------------- log
def list_log():
    w, a = _mine()
    return _q(f"""SELECT l.*, (SELECT COUNT(*) FROM journal j WHERE j.log_id=l.id) AS entries,
                 (SELECT MAX(created_at) FROM journal j WHERE j.log_id=l.id) AS last_entry
                 FROM media_log l WHERE 1=1{w} ORDER BY COALESCE(l.finished, '') DESC, l.id DESC""", a)


def get_log(log_id):
    r = _q("SELECT * FROM media_log WHERE id=?", (log_id,), one=True)
    if r:
        r["journal"] = list_entries(log_id)
    return r


def _clean(d):
    out = {}
    for k in ("item_id", "title", "kind", "link", "score", "finished", "source", "status"):
        if k in d:
            v = d[k]
            if k == "status" and v not in STATUSES:
                v = ""
            if k == "kind" and v not in KINDS:
                v = "other"
            if k == "score":
                try:
                    v = None if v in (None, "") else max(0.0, min(10.0, float(v)))
                except (TypeError, ValueError):
                    v = None
            if k in ("title", "link", "finished") and isinstance(v, str):
                v = v.strip() or None
            out[k] = v
    return out


def create_log(d):
    d = _clean(d)
    if d.get("finished") and not d.get("status"):
        d["status"] = "finished"
    if not d.get("title"):
        raise ValueError("Give it a title.")
    now = time.time()
    d.setdefault("kind", "book")
    cols = list(d) + ["created_at", "updated_at", "profile_id"]
    return _q(f"INSERT INTO media_log ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
              tuple(d.values()) + (now, now, store.viewer()), commit=True)


def update_log(log_id, d):
    d = _clean(d)
    if d.get("finished") and "status" not in d:
        d["status"] = "finished"
    if "title" in d and not d["title"]:
        d.pop("title")
    if not d:
        return
    d["updated_at"] = time.time()
    _q(f"UPDATE media_log SET {','.join(k + '=?' for k in d)} WHERE id=?", tuple(d.values()) + (log_id,), commit=True)


def delete_log(log_id):
    for r in _q("SELECT id FROM journal WHERE log_id=?", (log_id,)):
        store.tombstone("journal", r["id"])
    _q("DELETE FROM journal WHERE log_id=?", (log_id,), commit=True)
    _q("DELETE FROM media_log WHERE id=?", (log_id,), commit=True)
    store.tombstone("log", log_id)      # so phones drop it too


def log_kind_for(item):
    return {"movie": "movie", "tv": "show"}.get(item.get("kind"), "book")


def log_for_item(item):
    """The log row for a library item (for a TV episode: the row for its show)."""
    w, a = _mine()
    r = _q(f"SELECT * FROM media_log WHERE item_id=?{w} ORDER BY id LIMIT 1", (item["id"],) + a, one=True)
    if r or item.get("kind") != "tv" or not item.get("series"):
        return r
    k = norm(item["series"])
    for row in _q(f"SELECT * FROM media_log WHERE kind='show'{w}", a):
        if norm(row["title"]) == k:
            return row
    return None


def ensure_log_for_item(item):
    r = log_for_item(item)
    if r:
        return r["id"]
    title = item.get("series") if item.get("kind") == "tv" and item.get("series") else item.get("title") or "Untitled"
    return create_log({"item_id": item["id"], "title": title, "kind": log_kind_for(item)})


# ---------------------------------------------------------------- journal entries
def list_entries(log_id):
    return _q("SELECT * FROM journal WHERE log_id=? ORDER BY created_at, id", (log_id,))


def add_entry(log_id, body, created_at=None, source=None):
    body = (body or "").strip()
    if not body:
        raise ValueError("The entry is empty.")
    now = time.time()
    eid = _q("INSERT INTO journal (log_id, body, created_at, updated_at, source) VALUES (?,?,?,?,?)",
             (log_id, body, created_at or now, now, source), commit=True)
    _q("UPDATE media_log SET updated_at=? WHERE id=?", (now, log_id), commit=True)
    return eid


def update_entry(eid, body):
    body = (body or "").strip()
    if not body:
        return delete_entry(eid)
    _q("UPDATE journal SET body=?, updated_at=? WHERE id=?", (body, time.time(), eid), commit=True)


def delete_entry(eid):
    _q("DELETE FROM journal WHERE id=?", (eid,), commit=True)
    store.tombstone("journal", eid)


def delete_profile(pid):
    """A profile is removed: its journal goes with it."""
    for r in _q("SELECT id FROM media_log WHERE profile_id=?", (pid,)):
        delete_log(r["id"])


def detach_item(item_id):
    """A library item was deleted: keep its log and review, just unlink them."""
    _q("UPDATE media_log SET item_id=NULL WHERE item_id=?", (item_id,), commit=True)


# ---------------------------------------------------------------- matching titles to the library
def norm(t):
    t = (t or "").lower().replace("&", " and ")
    t = re.sub(r"\((?:\d{4} )?(?:film|novel|tv series|book|movie)\)", " ", t)
    t = re.sub(r"[^a-z0-9]+", " ", t).strip()
    t = re.sub(r"^(the|a|an) ", "", t)
    return t


def _variants(title):
    """(full form, other forms): 'Mistborn: The Final Empire' -> 'mistborn the final empire', {'final empire', ...}.
    One-word pieces ('mistborn') are left out: they name a series, not a book."""
    t = (title or "").strip()
    if not t:
        return "", set()
    parts = set()
    for sep in (":", " - ", " – ", " — ", "-"):
        if sep in t:
            a, b = t.split(sep, 1)
            parts.add(norm(a)); parts.add(norm(b))
    for pat in (r"^(.*?)\s+(?:book|part|vol\.?|volume)\s+\w+$", r"^(.*?)\s+(?:19|20)\d\d$", r"^(.*?)\s+s\d+(?:\s*-\s*s?\d+)?$"):
        m = re.match(pat, t, re.I)
        if m:
            parts.add(norm(m.group(1)))
    full = norm(t)
    return full, {p for p in parts if len(p.split()) >= 2 and p != full}


def _wiki_title(url):
    m = re.search(r"wikipedia\.org/wiki/([^#?]+)", url or "")
    return urllib.parse.unquote(m.group(1)).replace("_", " ") if m else ""


def match_item(names, kind, items):
    """Library item whose title matches any of the names (for films/shows: by title or show name)."""
    wf, wp = set(), set()
    for n in names:
        f, p = _variants(n)
        if f:
            wf.add(f)
        wp |= p
    if not wf:
        return None
    kinds = {"book": ("book", "graphic"), "movie": ("movie",), "show": ("tv",)}.get(kind, ("book", "graphic", "movie", "tv"))
    digits = lambda x: set(re.findall(r"\d+", x))
    best, best_score = None, 0
    for it in items:
        if it.get("kind") not in kinds:
            continue
        hf, hp = _variants(it.get("series") if it.get("kind") == "tv" else it.get("title"))
        if not hf:
            continue
        hfull = {hf}
        if it.get("kind") != "tv" and it.get("series") and it.get("title"):
            hfull.add(norm(f"{it['series']} {it['title']}"))
            if it.get("series_index") is not None:          # "Dungeon Crawler Carl book 1"
                n = f"{float(it['series_index']):g}"
                hfull |= {norm(f"{it['series']} book {n}"), norm(f"{it['series']} {n}"), norm(f"{it['series']} vol {n}")}
        exact = (wf | wp) & (hfull | hp)
        score = max((len(x) + 100 for x in exact), default=0)
        if not score:
            for w in wf:
                for h in hfull:
                    short, long_ = sorted((w, h), key=len)
                    if len(short) >= 10 and len(short) >= 0.6 * len(long_) and short in long_ and digits(w) == digits(h):
                        score = max(score, len(short))
        if score > best_score:
            best, best_score = it, score
    return best


def link_orphans(item):
    """Journal pages written before the book was on the shelf get attached to it when it arrives."""
    if not item:
        return 0
    n = 0
    for r in _q("SELECT id, title, kind FROM media_log WHERE item_id IS NULL OR item_id NOT IN (SELECT id FROM items)"):
        if match_item([r["title"]], r["kind"], [item]):
            _q("UPDATE media_log SET item_id=? WHERE id=?", (item["id"], r["id"]), commit=True)
            n += 1
    return n


# ---------------------------------------------------------------- splitting a note into journal entries
# A note written over several sittings reads as one block. These openings start a new sitting.
SESSION_START = re.compile(r"""^(?:ok(?:ay)?[,.]?\s+(?:update|so|im|i'm)\b|update\b|aight\b|alright\b|
    so+\s+i\s+(?:just\s+)?finished|i\s+just\s+finished|just\s+finished|just\s+recently\s+started|recently\s+started|
    had\s+the\s+final|after\s+thinking|honestly\s+after\s+resting|below\s+is|above\s+is|one\s+chapter\s+in|
    chapter\s+\d+|idk\s+ill\s+give|dropped\b|holy\s+shit\s+that\s+ending|not\s+complete\s+yet|im\s+currently\s+still|
    pg\s+\d+|so\s+far\b|second\s+run)""", re.I | re.X)
DROPPED = re.compile(r"\b(dropp(?:ed|ing)\s+(?:the|this|it\b)|dropped\s+because|didn'?t\s+finish|did\s+not\s+finish|gave\s+up\s+on)", re.I)


def split_sessions(text):
    paras = [p.strip() for p in re.split(r"\n\s*\n", (text or "").strip()) if p.strip()]
    parts = []
    for p in paras:
        if not parts or SESSION_START.match(p):
            parts.append([p])
        else:
            parts[-1].append(p)
    # a sitting of one short line belongs with the next one ("Recently started the book." + first thoughts)
    merged = []
    for chunk in parts:
        if merged and len(" ".join(merged[-1])) < 60:
            merged[-1].extend(chunk)
        else:
            merged.append(chunk)
    return ["\n\n".join(c) for c in merged]


def split_imported():
    """Imported notes were one entry each; split them into one entry per sitting. Returns how many were split."""
    _q("UPDATE media_log SET status='finished' WHERE (status IS NULL OR status='') AND source LIKE 'obsidian:%inish%'", commit=True)
    n = 0
    for e in _q("SELECT * FROM journal WHERE source LIKE 'obsidian:%' AND source NOT LIKE '%#%'"):
        parts = split_sessions(e["body"])
        if DROPPED.search(e["body"]):
            row = _q("SELECT status FROM media_log WHERE id=?", (e["log_id"],), one=True)
            if row and row.get("status") != "dropped":
                _q("UPDATE media_log SET status='dropped' WHERE id=?", (e["log_id"],), commit=True)
        if len(parts) < 2:
            continue
        for i, body in enumerate(parts):
            _q("INSERT INTO journal (log_id, body, created_at, updated_at, source) VALUES (?,?,?,?,?)",
               (e["log_id"], body, e["created_at"] - (len(parts) - 1 - i) * 60, time.time(), f"{e['source']}#{i + 1}"), commit=True)
        _q("DELETE FROM journal WHERE id=?", (e["id"],), commit=True)
        n += 1
    return n


# ---------------------------------------------------------------- Obsidian import
def _parse_date(s):
    s = (s or "").strip()
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d", "%d %B %Y", "%B %d, %Y"):
        try:
            return datetime.datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            pass
    return None


def _cells(line):
    s = line.strip()
    if not s.startswith("|"):
        return None
    s = s.strip("|")
    # don't split on pipes inside [[a|b]] links
    parts, depth, cur = [], 0, ""
    for ch in s:
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth = max(0, depth - 1)
        if ch == "|" and depth == 0:
            parts.append(cur.strip()); cur = ""
        else:
            cur += ch
    parts.append(cur.strip())
    return parts


def _kind_from_name(name):
    n = name.lower()
    if re.search(r"movie|film", n):
        return "movie"
    if re.search(r"show|series|tv|anime", n):
        return "show"
    if re.search(r"game", n):
        return "game"
    return "book"


def parse_tables(path):
    """Rows of every Title/... table in a Markdown file."""
    rows, header = [], None
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            c = _cells(line)
            if c is None:
                header = None
                continue
            low = [x.lower() for x in c]
            if any(x == "title" for x in low):
                header = low
                continue
            if header is None or all(re.fullmatch(r":?-*:?", x) for x in c):
                continue
            rec = dict(zip(header, c))
            title = rec.get("title", "").strip()
            if not title:
                continue
            link_cell = rec.get("link", "")
            m = re.search(r"\[([^\]]*)\]\(([^)]*)\)", link_cell)
            link_text, link = (m.group(1), m.group(2)) if m else ("", link_cell if link_cell.startswith("http") else "")
            link = re.sub(r"(https?://\S+?)(?=https?://)", "", link).strip()  # a link pasted twice
            thoughts = re.findall(r"\[\[([^\]|#]+)", rec.get("thoughts", "") or rec.get("review", "") or rec.get("notes", ""))
            score = None
            for k in ("my score", "score", "rating"):
                if k in rec:
                    sm = re.search(r"\d+(?:\.\d+)?", rec[k] or "")
                    score = float(sm.group(0)) if sm else None
            date = None
            for k in ("date finished", "date", "finished"):
                if rec.get(k):
                    date = _parse_date(rec[k])
            rows.append({"title": title, "link": link or None, "link_text": link_text, "thoughts": thoughts[0].strip() if thoughts else None,
                         "score": score, "finished": date})
    return rows


def import_obsidian(folder):
    folder = os.path.expanduser((folder or "").strip().strip('"'))
    if not os.path.isdir(folder):
        raise ValueError("That folder doesn't exist.")
    notes, tables = {}, []

    def walk(top):
        for root, dirs, names in os.walk(top):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for n in names:
                if not n.lower().endswith(".md"):
                    continue
                p = os.path.join(root, n)
                rows = parse_tables(p)
                if rows:
                    tables.append((n, rows))
                else:
                    notes.setdefault(os.path.splitext(n)[0].lower(), p)
    walk(folder)
    # picked the notes folder itself? the "finished" tables are usually right next to it
    parent = os.path.dirname(os.path.abspath(folder))
    if not tables and parent and parent != folder:
        for d in os.listdir(parent):
            sub = os.path.join(parent, d)
            if os.path.isdir(sub) and not d.startswith(".") and os.path.abspath(sub) != os.path.abspath(folder):
                walk(sub)
    items = store.list_items()
    existing = {(r["kind"], norm(r["title"])): r for r in _q("SELECT * FROM media_log")}
    stats = {"logged": 0, "updated": 0, "reviews": 0, "linked": 0}
    used_notes = set()

    def upsert(title, kind, link=None, score=None, finished=None, names=(), source=None):
        key = (kind, norm(title))
        it = match_item([title, *names], kind, items)
        row = existing.get(key)
        data = {"title": title, "kind": kind, "link": link, "score": score, "finished": finished, "source": source}
        if source and re.search(r"finish", source, re.I):
            data["status"] = "finished"   # it's in one of your "finished" lists
        if it:
            data["item_id"] = it["id"]
        if row:
            # fill gaps only; what was changed in Babel's Library stays
            upd = {k: v for k, v in data.items() if v not in (None, "") and not row.get(k)}
            if upd:
                update_log(row["id"], upd)
                stats["updated"] += 1
            lid = row["id"]
        else:
            lid = create_log(data)
            existing[key] = {"id": lid, **data}
            stats["logged"] += 1
        if it:
            stats["linked"] += 1
        return lid

    def add_note(lid, note_path, finished):
        src = "obsidian:" + os.path.basename(note_path)
        with open(note_path, encoding="utf-8", errors="replace") as f:
            body = f.read().strip()
        if not body:
            return
        # dated the day you finished it when the table says so, else when the note was last edited
        when = datetime.datetime.fromisoformat(finished + "T12:00:00").timestamp() if finished else os.path.getmtime(note_path)
        olds = _q("SELECT id, log_id FROM journal WHERE source=? OR source LIKE ?", (src, src + "#%"))
        for prev in {o["log_id"] for o in olds if o["log_id"] != lid}:
            # the note had been imported on its own earlier (e.g. as a book); fold that row into this one
            _q("UPDATE journal SET log_id=? WHERE log_id=?", (lid, prev), commit=True)
            p = _q("SELECT * FROM media_log WHERE id=?", (prev,), one=True)
            if p:
                cur = _q("SELECT * FROM media_log WHERE id=?", (lid,), one=True) or {}
                fill = {k: p[k] for k in ("item_id", "link", "score", "finished", "status") if p.get(k) and not cur.get(k)}
                if fill:
                    update_log(lid, fill)
                _q("DELETE FROM media_log WHERE id=?", (prev,), commit=True)
                for k_, v_ in list(existing.items()):
                    if v_.get("id") == prev:
                        existing.pop(k_)
                stats["moved"] = stats.get("moved", 0) + 1
        _q("DELETE FROM journal WHERE source=? OR source LIKE ?", (src, src + "#%"), commit=True)
        parts = split_sessions(body)
        for i, part in enumerate(parts):
            add_entry(lid, part, created_at=when - (len(parts) - 1 - i) * 60, source=f"{src}#{i + 1}" if len(parts) > 1 else src)
        if not olds:
            stats["reviews"] += 1
        if DROPPED.search(body):
            _q("UPDATE media_log SET status='dropped' WHERE id=?", (lid,), commit=True)

    for fname, rows in tables:
        kind = _kind_from_name(fname)
        for r in rows:
            if re.fullmatch(r"-+", str(r.get("score") or "")):
                r["score"] = None
            lid = upsert(r["title"], kind, r["link"], r["score"], r["finished"],
                         names=[r["link_text"], _wiki_title(r["link"]), r["thoughts"] or ""], source="obsidian:" + fname)
            if r["thoughts"] and r["thoughts"].lower() in notes:
                used_notes.add(r["thoughts"].lower())
                add_note(lid, notes[r["thoughts"].lower()], r["finished"])
    # notes no table points at: their own row (books unless they match a film or show in the library)
    for k, p in notes.items():
        if k in used_notes:
            continue
        title = os.path.splitext(os.path.basename(p))[0]
        src0 = "obsidian:" + os.path.basename(p)
        done = _q("SELECT log_id FROM journal WHERE source=? OR source LIKE ?", (src0, src0 + "#%"), one=True)
        if done:   # already imported: keep it where it is (you may have changed its type since)
            add_note(done["log_id"], p, None)
            continue
        it = match_item([title], "any", items)
        kind = log_kind_for(it) if it else "book"
        lid = upsert(title, kind, source="obsidian:" + os.path.basename(p))
        add_note(lid, p, None)
    return stats
