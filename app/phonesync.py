"""Phone sync: lets the Babel's Library Android app keep the same library, positions and progress as this computer,
and fetch files from it over Wi-Fi, or from anywhere when "Reach from anywhere" is on.

A second, small web server on port 8766 answers only /sync/... requests, each needing a paired phone's token (the
library's own server stays on this computer only). Phones pair once with a 6-digit code shown in Settings.

  GET  /sync/hello                 who is this (no token)
  POST /sync/pair {code, name, device}  -> {token, pc, topic}
  GET  /sync/pull?since=<server time>   items, annotations, journal and collections changed since then, deletions, sends
  POST /sync/push {ops:[{id, field, value, ts}], now}   the phone's own changes; per field, the newer change wins
  GET  /sync/file/<id>, /sync/cover/<id>   the file (resumable) and its cover
  POST /sync/sent {ids}            files the phone has finished fetching ("Send to phone" queue)

Phones find this computer on Wi-Fi by a UDP broadcast on port 8767. Away from home, the app reaches it through a
Cloudflare quick tunnel (no account needed); its changing address is posted to a private ntfy.sh topic the phone
learned when it paired.
"""
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer

import store

PORT = int(os.environ.get("BABEL_SYNC_PORT", "8766"))
DISCOVERY_PORT = 8767
VERSION = 1
PHONE_FIELDS = ("id", "kind", "title", "authors", "year", "publisher", "journal", "volume", "issue", "pages", "doi", "isbn", "url",
                "genre", "subject", "fiction", "topic", "tags", "summary", "series", "series_index", "season", "episode",
                "album", "album_artist", "track", "disc", "duration", "file_type", "format", "direction", "physical",
                "progress", "last_location", "favorite", "wanted", "watched", "watched_at", "opened_at", "added_at",
                "has_file", "has_cover", "cover_v", "collections", "ann_count", "audio_pos", "updated_at", "expires_at", "audio_status", "source", "private_to")
BIN = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "BabelsLibrary", "bin")

_codes = {}          # pairing code -> expiry
_lock = threading.Lock()
_tunnel = {"url": "", "proc": None, "error": "", "posted": 0.0}
_server = None


# ---------------------------------------------------------------- devices
def _settings():
    return store.get_settings()


def devices():
    return list(_settings().get("phone_devices") or [])


def _save_devices(devs):
    store.set_settings({"phone_devices": devs})


def _hash(tok):
    return hashlib.sha256(tok.encode()).hexdigest()


def device_for(token):
    if not token:
        return None
    h = _hash(token)
    return next((d for d in devices() if hmac.compare_digest(d.get("token_hash", ""), h)), None)


def new_code():
    code = f"{secrets.randbelow(1000000):06d}"
    with _lock:
        now = time.time()
        for c in [c for c, t in _codes.items() if t < now]:
            _codes.pop(c, None)
        _codes[code] = now + 600
    threading.Thread(target=_post_pair_address, args=(code,), daemon=True).start()
    return code


def pair_topic(code):
    """Where an iPhone finds this computer from the pairing code alone (the iPhone app lives on the web, so it can't
    look around the Wi-Fi; it reaches the computer through the away-from-home address instead). The topic only says
    where to knock: pairing still needs the code itself, which is good for ten minutes."""
    return "babel-pair-" + hashlib.sha256(("babel-pair:" + str(code)).encode()).hexdigest()[:24]


def _post_pair_address(code):
    for _ in range(30):                  # (the away-from-home address may still be starting)
        if _tunnel["url"]:
            break
        time.sleep(2)
    if not _tunnel["url"]:
        return
    try:
        urllib.request.urlopen(urllib.request.Request("https://ntfy.sh/" + pair_topic(code), data=_tunnel["url"].encode(),
                                                      headers={"User-Agent": "BabelsLibrary", "Cache": "yes"}), timeout=20).read()
    except Exception as e:
        print("[inkwell] couldn't post the pairing address:", e)


# ---------------------------------------------------------------- notifications for the iPhone app (Web Push)
def push_news(items):
    """New events on the Local desk: a notification on each iPhone that asked for them."""
    devs = [d for d in devices() if d.get("push")]
    if not devs or not items:
        return
    import webpush
    one = items[0]
    msg = {"kind": "news", "title": "New event: " + one["title"] if len(items) == 1 else f"{len(items)} new events in the News",
           "body": (one.get("source") or "") if len(items) == 1 else "; ".join(i["title"] for i in items[:3]),
           "items": [{k: i.get(k) for k in ("title", "link", "source", "date")} for i in items[:8]]}
    for d in devs:
        try:
            code = webpush.send(d["push"], msg)
            if code in (404, 410):                 # the iPhone unsubscribed (or the app was removed)
                _touch(d, push=None)
        except Exception as e:
            print(f"[inkwell] couldn't notify {d.get('name')}: {e}")


def _take_code(code):
    with _lock:
        t = _codes.pop(str(code or "").strip(), None)
    return bool(t and t > time.time())


def topic():
    s = _settings()
    if not s.get("phone_topic"):
        store.set_settings({"phone_topic": "babel-" + secrets.token_hex(12)})
        s = _settings()
    return s["phone_topic"]


def pc_name():
    return socket.gethostname() or "This computer"


def remove_device(dev_id):
    _save_devices([d for d in devices() if d.get("id") != dev_id])


def _touch(dev, **extra):
    devs = devices()
    for d in devs:
        if d.get("id") == dev.get("id"):
            d["last_seen"] = time.time()
            d.update(extra)
    _save_devices(devs)


# ---------------------------------------------------------------- "Send to phone"
def queue_send(item_id, dev_id=None):
    """Mark a file to be fetched by the phone(s) next time they sync."""
    devs = devices()
    for d in devs:
        if dev_id in (None, d.get("id")):
            q = list(d.get("queue") or [])
            if int(item_id) not in q:
                q.append(int(item_id))
            d["queue"] = q
    _save_devices(devs)
    return len([d for d in devs if dev_id in (None, d.get("id"))])


def _sent(dev, ids):
    devs = devices()
    for d in devs:
        if d.get("id") == dev.get("id"):
            d["queue"] = [i for i in (d.get("queue") or []) if i not in set(int(x) for x in ids)]
    _save_devices(devs)


# ---------------------------------------------------------------- what a phone gets
def _file_size(item_id):
    raw = store.get_item(item_id, raw=True)
    try:
        return os.path.getsize(store.resolve_file(raw["file_path"])) if raw and raw.get("file_path") else 0
    except OSError:
        return 0


def pull(since):
    """Everything changed since `since`, as the phone's profile sees it (its own places, notes and journal)."""
    import journal
    now = time.time()
    pid = store.viewer()
    mine = store.progress_changed_since(pid, since) if pid != store.OWNER else set()
    items = [it for it in store.list_items() if (it.get("updated_at") or 0) > since or it["id"] in mine]
    clocks = store.item_clocks({it["id"] for it in items})
    out = []
    for it in items:
        d = {k: it.get(k) for k in PHONE_FIELDS}
        d["file_size"] = _file_size(it["id"]) if it.get("has_file") else 0
        d["clock"] = clocks.get(it["id"], {})
        out.append(d)
    anns = [a for a in store.list_annotations() if (a.get("updated_at") or 0) > since]
    try:
        log = journal.list_log()
        logs = {r["id"] for r in log}
        entries = [dict(r) for r in journal._q("SELECT id, log_id, body, created_at, updated_at FROM journal WHERE COALESCE(updated_at, created_at, 0) > ?", (since,))
                   if r["log_id"] in logs]
    except Exception:
        log, entries = [], []
    deleted = store.tombstones_since(since)
    with store._lock:       # hidden by another profile since: gone from this phone
        hid = store._db.execute("SELECT id FROM items WHERE private_to IS NOT NULL AND private_to<>? AND updated_at>?", (pid, since)).fetchall()
    deleted += [{"kind": "item", "ref_id": r[0], "ts": now} for r in hid]
    return {"now": now, "full": since <= 0, "items": out, "annotations": anns, "deleted": deleted,
            "collections": store.list_collections(), "log": [dict(r) for r in log], "journal": entries,
            "profiles": store.list_profiles(), "profile": pid,
            "bulletin": (store.get_settings().get("bulletin") or {}).get(str(pid)) or {}, "bookmarks": _bookmarks()}


def _bookmarks():
    try:
        import browser
        return browser.bookmarks()       # (this profile's)
    except Exception:
        return None


def push_journal(jops, skew):
    """The phone's journal changes: status/score/finish date of a log row, and review entries added, edited or
    removed. New things carry the phone's own id ("cid"), so a retry after a dropped connection can't add them twice.
    Returns {cid: new id} so the phone can swap its temporary ids for the real ones."""
    import journal
    made = {}
    fresh = set()       # rows made in this same sync: the phone's later changes to them always apply

    def by_cid(table, cid):
        r = journal._q(f"SELECT id FROM {table} WHERE source=?", ("phone:" + cid,), one=True)
        return r["id"] if r else None

    def log_id_of(op):
        if op.get("log_id") and journal._q("SELECT 1 FROM media_log WHERE id=?", (int(op["log_id"]),), one=True):
            return int(op["log_id"])
        if op.get("log_cid"):
            lid = made.get(op["log_cid"]) or by_cid("media_log", op["log_cid"])
            if lid:
                return lid
        if op.get("item_id"):
            it = store.get_item(int(op["item_id"]))
            if it:
                had = journal.log_for_item(it)
                lid = journal.ensure_log_for_item(it)
                if not had:
                    fresh.add(lid)
                return lid
        return None

    for op in jops or []:
        kind = op.get("op")
        ts = float(op.get("ts") or time.time()) + skew
        try:
            if kind == "log_new":
                lid = by_cid("media_log", op["cid"])
                if not lid:
                    lid = journal.create_log({**op.get("fields", {}), "source": "phone:" + op["cid"]})
                    fresh.add(lid)
                made[op["cid"]] = lid
            elif kind == "log":
                lid = log_id_of(op)
                if not lid:
                    continue
                row = journal._q("SELECT updated_at FROM media_log WHERE id=?", (lid,), one=True)
                if lid in fresh or ts > (row["updated_at"] or 0):          # the newer change wins
                    journal.update_log(lid, op.get("fields") or {})
                if op.get("log_cid"):
                    made[op["log_cid"]] = lid
            elif kind == "entry_add":
                if by_cid("journal", op["cid"]):
                    made[op["cid"]] = by_cid("journal", op["cid"])
                    continue
                lid = log_id_of(op)
                if lid:
                    made[op["cid"]] = journal.add_entry(lid, op.get("body"), created_at=float(op.get("created_at") or ts) + skew, source="phone:" + op["cid"])
            elif kind == "entry_edit":
                row = journal._q("SELECT updated_at FROM journal WHERE id=?", (int(op["id"]),), one=True)
                if row and ts > (row["updated_at"] or 0):
                    journal.update_entry(int(op["id"]), op.get("body"))
            elif kind == "entry_del":
                if journal._q("SELECT 1 FROM journal WHERE id=?", (int(op["id"]),), one=True):
                    journal.delete_entry(int(op["id"]))
        except (KeyError, ValueError, TypeError) as e:
            print("[inkwell] phone journal change skipped:", kind, e)
    return made


def push_anns(aops):
    """Highlights, notes, pins and bookmarks made in the phone's reader (in the order they were made; ones made
    offline carry the phone's own id, "c:...", until they're saved here). Returns {phone id: id here}."""
    made = {}
    for op in aops or []:
        try:
            kind = op.get("op")
            if kind == "add":
                it = store.get_item(int(op["item_id"]))
                if not it:
                    continue
                a = store.create_annotation(it["id"], {k: op.get(k) for k in ("title", "note", "quote", "color", "locator") if op.get(k) is not None})
                made[str(op.get("cid"))] = a["id"]
                continue
            aid = op.get("id")
            if isinstance(aid, str) and aid.startswith("c:"):
                aid = made.get(aid[2:])
            if not aid:
                continue
            if kind == "edit":
                store.update_annotation(int(aid), {k: v for k, v in (op.get("fields") or {}).items() if k in ("title", "note", "quote", "color", "locator")})
            elif kind == "del":
                store.delete_annotation(int(aid))
        except Exception as e:
            print("[inkwell] a note from the phone was skipped:", e)
    return made


def push(dev, ops, phone_now, jops=None, aops=None, profile=None):
    """Apply the phone's changes. Its clock may be off from ours: shift its times by the difference. (profile: a
    profile the phone used to keep on its own, now brought here: its places and notes go to that profile.)"""
    if profile and store.get_profile(int(profile)):
        store.use_profile(int(profile))
    skew = time.time() - float(phone_now) if phone_now else 0.0
    made = push_journal(jops, skew) if jops else {}
    made_anns = push_anns(aops) if aops else {}
    applied, older = 0, 0
    for op in ops or []:
        try:
            iid, field, ts = int(op["id"]), op["field"], float(op["ts"]) + skew
        except (KeyError, TypeError, ValueError):
            continue
        it = store.get_item(iid)
        if field not in store.SYNC_FIELDS or not it:
            continue
        # fields never changed since sync arrived: count them as changed when the item was last opened here
        have = store.item_clocks({iid}).get(iid, {}).get(field) or it.get("opened_at") or it.get("added_at") or 0
        if ts <= have:
            older += 1             # this computer changed it more recently: keep ours
            continue
        store.update_item(iid, {field: op.get("value")}, clock=ts)
        applied += 1
    return {"applied": applied, "kept_ours": older, "made": made, "made_anns": made_anns, "now": time.time()}


# ---------------------------------------------------------------- files sent from the phone
INCOMING = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "BabelsLibrary", "incoming")


def _upload_path(uid):
    if not re.match(r"^[A-Za-z0-9_-]{6,64}$", uid or ""):
        raise ValueError("bad upload id")
    os.makedirs(INCOMING, exist_ok=True)
    return os.path.join(INCOMING, uid + ".part")


def upload_size(uid):
    p = _upload_path(uid)
    return os.path.getsize(p) if os.path.exists(p) else 0


def upload_cancel(uid):
    """The phone stopped sending this file: throw away what had arrived."""
    p = _upload_path(uid)
    if os.path.exists(p):
        os.remove(p)
    return {"ok": True}


def clean_incoming(max_age=2 * 86400):
    """Pieces of files whose sending was abandoned (no new piece for two days) are thrown away."""
    try:
        for f in os.listdir(INCOMING):
            p = os.path.join(INCOMING, f)
            if f.endswith(".part") and time.time() - os.path.getmtime(p) > max_age:
                size = os.path.getsize(p)
                os.remove(p)
                print(f"[inkwell] removed an unfinished file a phone stopped sending ({size // 1048576} MB)")
    except OSError:
        pass


def upload_chunk(h, dev, uid, name, offset, total):
    """One piece of a file the phone is sending (8 MB at a time, so a dropped connection resumes where it stopped
    and big files fit through the away-from-home tunnel). When the last piece is in, the file joins the library."""
    import server
    import files
    name = os.path.basename(str(name or "file")).strip() or "file"
    ext = os.path.splitext(name)[1].lower()
    if ext not in files.SUPPORTED:
        raise ValueError(f"Babel's Library can't add {ext or 'that kind of'} files.")
    p = _upload_path(uid)
    have = os.path.getsize(p) if os.path.exists(p) else 0
    n = int(h.headers.get("Content-Length") or 0)
    if offset == 0 and have == 0 and n > 0:
        # the same file sent again after an earlier try stopped part-way: its first piece matches an unfinished
        # file here, so that one is picked up and the phone carries on from where it got to
        first = h.rfile.read(n)
        h._body_read = True
        parts = [os.path.join(INCOMING, f) for f in os.listdir(INCOMING) if f.endswith(".part")]
        same = []
        for q in parts:
            if q != p and n <= os.path.getsize(q) < total:
                with open(q, "rb") as fh:
                    if fh.read(n) == first:
                        same.append(q)
        if same:
            same.sort(key=os.path.getsize, reverse=True)     # the furthest-along try; older shorter ones go
            os.replace(same[0], p)
            for q in same[1:]:
                os.remove(q)
            print(f"[inkwell] carrying on with {name} from {os.path.getsize(p) // 1048576} MB")
            return {"have": os.path.getsize(p), "error": "offset"}
        with open(p, "ab") as fh:
            fh.write(first)
        have = os.path.getsize(p)
        return {"have": have} if have < total else _finish(p, name, dev, have)
    if offset != have:                      # out of step (a retry): tell the phone where to carry on
        h.rfile.read(n) if n else None
        h._body_read = True
        return {"have": have, "error": "offset"}
    with open(p, "ab") as f:
        left = n
        while left > 0:
            chunk = h.rfile.read(min(left, 1 << 20))
            if not chunk:
                break
            f.write(chunk)
            left -= len(chunk)
    h._body_read = True
    have = os.path.getsize(p)
    if have < total:
        return {"have": have}
    return _finish(p, name, dev, have, total)


def _finish(p, name, dev, have, total=None):
    """The last piece is in: the file joins the library (in the background; it can take a while for a big film)."""
    import server
    if total is not None and have > total:
        os.remove(p)
        raise ValueError("The file arrived bigger than expected; send it again.")

    def bring_in():
        try:
            iid, new = server.import_file(p, name, origin="phone", move=True)
            it = store.get_item(iid) or {}
            print(f"[inkwell] {'Added from' if new else 'Already in the library, sent from'} {dev.get('name', 'phone')}: {it.get('title') or name}")
        except Exception as e:
            print(f"[inkwell] couldn't add {name} from {dev.get('name', 'phone')}: {e}")
        finally:
            if os.path.exists(p):
                os.remove(p)
    threading.Thread(target=bring_in, daemon=True).start()
    return {"have": have, "done": True}


_ab_pack = {"at": 0.0, "data": b""}


def _adblock_pack():
    """The block lists for the phone's browser: {"domains": [...], "hide": script}, gzipped (about 1 MB)."""
    import gzip
    import adblock
    st = adblock.status()
    if not _ab_pack["data"] or _ab_pack["at"] != st["updated"]:
        body = json.dumps({"domains": sorted(adblock._domains), "hide": adblock.hide_css(), "updated": st["updated"]}).encode()
        _ab_pack.update(at=st["updated"], data=gzip.compress(body, 6))
    return _ab_pack["data"]


# ---------------------------------------------------------------- the web server phones talk to
def _make_handler():
    import server

    class SyncHandler(server.Handler):
        server_version = "BabelSync/1.0"

        def _send(self, code, body=b"", ctype="application/json", headers=None):
            headers = dict(headers or {})
            headers.setdefault("Access-Control-Allow-Origin", "*")
            return super()._send(code, body, ctype, headers)

        def _route(self, method):
            parsed = urllib.parse.urlparse(self.path)
            self.query = dict(urllib.parse.parse_qsl(parsed.query))
            path = parsed.path
            store.use_profile(None)
            try:
                if path == "/sync/hello":
                    return self._send(200, {"app": "babels-library", "name": pc_name(), "version": VERSION})
                if path == "/sync/pair" and method == "POST":
                    b = self.json_body()
                    if not _take_code(b.get("code")):
                        time.sleep(1.5)        # slows down guessing
                        return self._send(403, {"error": "That code is wrong or has expired. Make a new one in Settings → Phone."})
                    tok = secrets.token_urlsafe(32)
                    dev = {"id": str(b.get("device") or secrets.token_hex(8))[:64], "name": str(b.get("name") or "Phone")[:60],
                           "token_hash": _hash(tok), "paired_at": time.time(), "last_seen": time.time(), "queue": []}
                    _save_devices([d for d in devices() if d.get("id") != dev["id"]] + [dev])
                    print(f"[inkwell] Paired a phone: {dev['name']}")
                    return self._send(200, {"token": tok, "pc": pc_name(), "topic": topic(), "now": time.time()})
                tok = (self.headers.get("Authorization") or "").removeprefix("Bearer ").strip() or self.query.get("t", "")
                dev = device_for(tok)
                if not dev:
                    return self._send(401, {"error": "This phone isn't paired with this computer (or was removed)."})
                # each phone is logged in as a profile: it sees that profile's places, notes, journal and hidden things
                pid = int(dev.get("profile") or store.OWNER)
                store.use_profile(pid if store.get_profile(pid) else store.OWNER)
                if path == "/sync/profiles":
                    if method == "POST":
                        b = self.json_body()
                        p = store.create_profile(b.get("name"), b.get("face") or "")
                        return self._send(200, {"profile": p, "profiles": store.list_profiles()})
                    return self._send(200, {"profiles": store.list_profiles(), "current": store.viewer()})
                if path == "/sync/profile" and method == "POST":
                    b = self.json_body()
                    if b.get("edit"):          # rename / new face for a profile
                        store.update_profile(int(b["edit"]), b)
                        return self._send(200, {"profiles": store.list_profiles(), "current": store.viewer()})
                    if "setpin" in b:          # a PIN for the profile this phone is using (empty: none)
                        store.set_pin(store.viewer(), b.get("setpin"), b.get("old"))
                        return self._send(200, {"profiles": store.list_profiles(), "current": store.viewer()})
                    new = int(b.get("id") or store.OWNER)
                    if not store.get_profile(new):
                        raise ValueError("No such profile.")
                    if new != store.viewer():
                        store.need_pin(new, b.get("pin"))
                    _touch(dev, profile=new)
                    return self._send(200, {"current": new})
                if path == "/sync/bulletin":
                    for meth, rx, fn in server.ROUTES:
                        if meth == method and rx.match("/api/bulletin"):
                            return fn(self)
                    return self._send(404, {"error": "not found"})
                if path == "/sync/pull":
                    data = pull(float(self.query.get("since") or 0))
                    data["queue"] = dev.get("queue") or []
                    data["remote"] = _tunnel["url"]
                    data["theme"] = _settings().get("theme") or "wordtown"
                    data["pc"] = pc_name()
                    _touch(dev)
                    return self._send(200, data)
                if path == "/sync/push" and method == "POST":
                    b = self.json_body()
                    return self._send(200, push(dev, b.get("ops"), b.get("now"), b.get("jops"), b.get("aops"), b.get("profile")))
                if path == "/sync/sent" and method == "POST":
                    _sent(dev, self.json_body().get("ids") or [])
                    return self._send(200, {"ok": True})
                if path == "/sync/upload":
                    q = self.query
                    if method == "GET":
                        return self._send(200, {"have": upload_size(q.get("u", ""))})
                    if method == "DELETE":
                        return self._send(200, upload_cancel(q.get("u", "")))
                    return self._send(200, upload_chunk(self, dev, q.get("u", ""), q.get("name", ""), int(q.get("offset") or 0), int(q.get("total") or 0)))
                if path == "/sync/push/key":
                    import webpush
                    return self._send(200, {"key": webpush.public_key()})
                if path == "/sync/push/subscribe" and method == "POST":
                    sub = self.json_body().get("sub")
                    if sub and not (isinstance(sub, dict) and str(sub.get("endpoint", "")).startswith("https://") and (sub.get("keys") or {}).get("p256dh")):
                        raise ValueError("That isn't a push subscription.")
                    _touch(dev, push=sub or None)
                    if sub:
                        store.set_settings({"news_alerts": True})       # (the computer's watcher is what finds the events)
                    return self._send(200, {"ok": True, "on": bool(sub)})
                if path == "/sync/adblock":
                    return self._send(200, _adblock_pack(), "application/gzip")
                if path == "/sync/bookmarks":
                    # the browser's bookmarks are shared: ☆ on the phone or the computer, they show on both start pages
                    import browser
                    if method == "POST":
                        b = self.json_body()
                        if b.get("remove"):
                            browser.remove_bookmark(b.get("url"), b.get("id"))
                        else:
                            browser.add_bookmark(str(b.get("url") or ""), str(b.get("title") or ""))
                    return self._send(200, {"items": browser.bookmarks()})
                if path == "/sync/savearticle" and method == "POST":
                    # the phone's browser: "save this article" (the computer loads and files it; it arrives with the next sync)
                    body = self.json_body()
                    url, days = str(body.get("url") or ""), body.get("days")      # (days: kept for 30 days, if asked)
                    if not re.match(r"^https?://", url):
                        raise ValueError("Only web pages can be saved.")
                    if server.DESKTOP is None or not hasattr(server.DESKTOP, "save_web"):
                        raise ValueError("Saving pages needs the Babel's Library window open on the computer.")

                    def save():
                        try:
                            server.DESKTOP.save_web(url, days)
                        except Exception as e:
                            print(f"[inkwell] couldn't save {url} from {dev.get('name', 'phone')}: {e}")
                    threading.Thread(target=save, daemon=True).start()
                    return self._send(200, {"ok": True})
                # an item's full details on the phone: read them, edit them, and the same buttons as the computer's
                m = re.match(r"^/sync/item/(\d+)(/annotations|/edit|/remove|/reanalyze|/pullcover|/hardcover|/poster|/fill|/expire|/tracks|/audiobook|/subs/[es]\d+\.vtt|/audio/\d+)?$", path)
                if m:
                    sub = m.group(2) or ""
                    # (Android can't send PATCH or a DELETE with a body: edits come as POST /edit, removal as POST /remove)
                    want = {("GET", ""): ("GET", ""), ("GET", "/annotations"): ("GET", "/annotations"), ("POST", "/edit"): ("PATCH", ""),
                            ("POST", "/remove"): ("DELETE", "")}.get((method, sub)) or (("POST", sub) if method == "POST" and sub not in ("", "/annotations") else None)
                    # the reader's subtitles, audiobook and its chapters (read only)
                    if method == "GET" and re.match(r"^/(tracks|audiobook|subs/[es]\d+\.vtt|audio/\d+)$", sub):
                        want = ("GET", sub)
                    if not want:
                        return self._send(405, {"error": "not allowed"})
                    target = f"/api/items/{m.group(1)}{want[1]}"
                    self.query.pop("delete_file", None)                  # from the phone, removing never deletes the file
                    for meth, rx, fn in server.ROUTES:
                        mm = rx.match(target)
                        if meth == want[0] and mm:
                            return fn(self, *mm.groups())
                    return self._send(404, {"error": "not found"})
                m = re.match(r"^/sync/news/(science|local|place|save|article|alerts)$", path)
                if m:
                    for meth, rx, fn in server.ROUTES:
                        if meth == method and rx.match("/api/news/" + m.group(1)):
                            return fn(self)
                    return self._send(404, {"error": "not found"})
                if path == "/sync/potd" and method == "GET":        # the Bulletin's photo of the day
                    for meth, rx, fn in server.ROUTES:
                        if meth == "GET" and rx.match("/api/potd"):
                            return fn(self)
                    return self._send(404, {"error": "not found"})
                # the catalogue (Discover) for the phone: the computer's own routes, passed through
                m = re.match(r"^/sync/cat/(promos|browse|subjects|search|byauthor|cover|info|reviews|series|authors|ignore|wish)$", path)
                if m:
                    target = "/api/wishlist" if m.group(1) == "wish" else "/api/discover/" + m.group(1)
                    for meth, rx, fn in server.ROUTES:
                        if meth == method and rx.match(target):
                            return fn(self)
                    return self._send(404, {"error": "not found"})
                m = re.match(r"^/sync/(file|cover)/(\d+)$", path)
                if m and method == "GET":
                    return (server.r_file if m.group(1) == "file" else server.r_cover)(self, m.group(2))
                return self._send(404, {"error": "not found"})
            except (ValueError, LookupError) as e:
                return self._send(400, {"error": str(e)})
            except OSError:
                self.close_connection = True
            except Exception as e:
                import traceback
                traceback.print_exc()
                return self._send(500, {"error": str(e)})

        def end_headers(self):
            # every answer can be read by the iPhone app (a page on another site), including a file's size and range
            sent = b"".join(getattr(self, "_headers_buffer", [])).lower()
            if b"access-control-allow-origin" not in sent:
                self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Expose-Headers", "Content-Range, Content-Length, Accept-Ranges, X-File-Size")
            super().end_headers()

        def do_OPTIONS(self):
            self.send_response(204)
            self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type, Range")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
            self.send_header("Access-Control-Max-Age", "86400")
            self.send_header("Content-Length", "0")
            self.end_headers()

    return SyncHandler


def _discovery():
    """Answer phones looking for Babel's Library on the Wi-Fi."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("0.0.0.0", DISCOVERY_PORT))
    except OSError as e:
        print("[inkwell] phone discovery unavailable:", e)
        return
    while True:
        try:
            data, addr = s.recvfrom(256)
            if data.startswith(b"BABEL?"):
                s.sendto(json.dumps({"app": "babels-library", "name": pc_name(), "port": PORT}).encode(), addr)
        except OSError:
            time.sleep(1)


def start():
    global _server
    if _server:
        return
    try:
        _server = ThreadingHTTPServer(("0.0.0.0", PORT), _make_handler())
    except OSError as e:
        print(f"[inkwell] phone sync couldn't start on port {PORT}: {e}")
        return
    _server.daemon_threads = True
    threading.Thread(target=_server.serve_forever, daemon=True, name="phonesync").start()
    threading.Thread(target=_discovery, daemon=True, name="phonefind").start()
    threading.Thread(target=clean_incoming, daemon=True).start()
    if _settings().get("phone_remote"):
        threading.Thread(target=start_tunnel, daemon=True).start()


def lan_addresses():
    out = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127.") and ip not in out:
                out.append(ip)
    except OSError:
        pass
    try:   # the address used to reach the internet: the one a phone on the same Wi-Fi can use
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        if ip in out:
            out.remove(ip)
        out.insert(0, ip)
    except OSError:
        pass
    return out


# ---------------------------------------------------------------- reach from anywhere (cellular)
CLOUDFLARED_URL = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"


def _cloudflared():
    exe = shutil.which("cloudflared") or os.path.join(BIN, "cloudflared.exe")
    if os.path.exists(exe):
        return exe
    os.makedirs(BIN, exist_ok=True)
    print("[inkwell] Downloading Cloudflare's tunnel program (cloudflared) from github.com/cloudflare …")
    tmp = exe + ".part"
    with urllib.request.urlopen(urllib.request.Request(CLOUDFLARED_URL, headers={"User-Agent": "BabelsLibrary"}), timeout=120) as r, open(tmp, "wb") as f:
        shutil.copyfileobj(r, f)
    os.replace(tmp, exe)
    return exe


def _post_address():
    url = _tunnel["url"]
    if not url:
        return
    try:
        urllib.request.urlopen(urllib.request.Request("https://ntfy.sh/" + topic(), data=url.encode(),
                                                      headers={"User-Agent": "BabelsLibrary", "Cache": "yes"}), timeout=20).read()
        _tunnel["posted"] = time.time()
    except Exception as e:
        print("[inkwell] couldn't post the away-from-home address:", e)


def start_tunnel():
    if _tunnel["proc"] and _tunnel["proc"].poll() is None:
        return
    _tunnel.update(url="", error="")
    try:
        exe = _cloudflared()
        p = subprocess.Popen([exe, "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{PORT}"],
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace",
                             creationflags=0x08000000 if os.name == "nt" else 0)
    except Exception as e:
        _tunnel["error"] = str(e)
        print("[inkwell] away-from-home access couldn't start:", e)
        return
    _tunnel["proc"] = p

    def read():
        for line in p.stdout:
            m = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", line)
            if m and m.group(0) != _tunnel["url"]:
                _tunnel["url"] = m.group(0)
                print("[inkwell] Phones can reach this library from anywhere now")
                _post_address()
        _tunnel["url"] = ""
    threading.Thread(target=read, daemon=True).start()

    def keep_posted():          # ntfy.sh keeps messages for 12 hours: post the address again well before then
        while p.poll() is None:
            time.sleep(600)
            if _tunnel["url"] and time.time() - _tunnel["posted"] > 6 * 3600:
                _post_address()
    threading.Thread(target=keep_posted, daemon=True).start()


def stop_tunnel():
    p = _tunnel.get("proc")
    if p and p.poll() is None:
        p.terminate()
    _tunnel.update(url="", proc=None)


def status():
    return {"port": PORT, "running": bool(_server), "addresses": lan_addresses(), "name": pc_name(),
            "devices": [{k: d.get(k) for k in ("id", "name", "paired_at", "last_seen")} | {"queued": len(d.get("queue") or [])} for d in devices()],
            "remote": bool(_settings().get("phone_remote")), "remote_url": _tunnel["url"], "remote_error": _tunnel["error"]}
