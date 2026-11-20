"""The corkboard: a free board to pin things on (post-it notes, snippets and links from web pages, quotes from the
reader, pictures, things from the library) and tie them together with string. Each profile has its own board, kept
as it's worked on, and boards can be saved under a name, opened again later, and cleared.

Files, per profile: <data>/corkboard/<profile>/current.json, saved/<id>.json; pictures in <data>/corkboard/media.
A board: {"name", "items": [card...], "strings": [{"id", "a", "b", "color"}], "view": {"x", "y", "z"}}
A card: {"id", "type": note|snippet|link|media|image, "x", "y", "w", "r" (tilt), ...its own fields, "added_at"}
"""
import hashlib
import json
import os
import re
import secrets
import threading
import time

import store

_lock = threading.RLock()
TYPES = ("note", "snippet", "link", "media", "image")
COLORS = ("yellow", "pink", "blue", "green", "orange", "purple")


def _root():
    d = os.path.join(store.DATA_DIR, "corkboard", str(store.viewer()))
    os.makedirs(os.path.join(d, "saved"), exist_ok=True)
    return d


def media_dir():
    d = os.path.join(store.DATA_DIR, "corkboard", "media")
    os.makedirs(d, exist_ok=True)
    return d


def _read(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _write(path, data):
    tmp = path + ".part"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _empty():
    return {"name": "", "items": [], "strings": [], "view": {"x": 0, "y": 0, "z": 1}, "saved_id": None, "updated_at": time.time()}


def _clean_card(c):
    if not isinstance(c, dict) or c.get("type") not in TYPES:
        return None
    out = {"id": str(c.get("id") or secrets.token_hex(6))[:40], "type": c["type"]}
    for k in ("x", "y", "w", "h", "r"):
        try:
            out[k] = round(float(c.get(k) or 0), 1)
        except (TypeError, ValueError):
            out[k] = 0.0
    for k in ("text", "title", "url", "image", "source", "color", "kind", "author", "locator"):
        if c.get(k) not in (None, ""):
            out[k] = str(c[k])[:20000 if k == "text" else 2000]
    if c.get("item_id") not in (None, ""):
        try:
            out["item_id"] = int(c["item_id"])
        except (TypeError, ValueError):
            pass
    out["added_at"] = float(c.get("added_at") or time.time())
    return out


def _clean(board):
    b = _empty()
    if isinstance(board, dict):
        b["name"] = str(board.get("name") or "")[:120]
        b["saved_id"] = board.get("saved_id") or None
        b["items"] = [c for c in (_clean_card(x) for x in board.get("items") or []) if c][:2000]
        ids = {c["id"] for c in b["items"]}
        b["strings"] = [{"id": str(s.get("id") or secrets.token_hex(6))[:40], "a": str(s.get("a")), "b": str(s.get("b")),
                         "color": str(s.get("color") or "red")[:20]}
                        for s in board.get("strings") or [] if isinstance(s, dict) and str(s.get("a")) in ids and str(s.get("b")) in ids][:4000]
        v = board.get("view") or {}
        try:
            b["view"] = {"x": float(v.get("x") or 0), "y": float(v.get("y") or 0), "z": min(3.0, max(0.15, float(v.get("z") or 1)))}
        except (TypeError, ValueError):
            pass
    return b


# ---------------------------------------------------------------- the board on screen
def current():
    with _lock:
        return _clean(_read(os.path.join(_root(), "current.json"), _empty()))


def save_current(board, loaded_at=None):
    """The page's whole board. Cards pinned from elsewhere (the browser, the reader) after the page last loaded the
    board are kept, so they can't be lost to a save that hadn't seen them yet."""
    with _lock:
        b = _clean(board)
        if loaded_at:
            mine = {c["id"] for c in b["items"]}
            for c in current()["items"]:
                if c["id"] not in mine and c.get("added_at", 0) > float(loaded_at):
                    b["items"].append(c)
        b["updated_at"] = time.time()
        _write(os.path.join(_root(), "current.json"), b)
        return b


def _free_spot(b):
    """Somewhere near the middle of what's on screen that isn't already covered."""
    v = b["view"]
    cx, cy = (-v["x"] + 520) / v["z"], (-v["y"] + 300) / v["z"]
    n = len(b["items"])
    import math
    for i in range(160):
        a, rad = i * 2.39996, 108 * math.sqrt(i)
        x, y = cx + math.cos(a) * rad - 130, cy + math.sin(a) * rad * 0.75 - 110
        if all(abs(x - c["x"]) > 285 or abs(y - c["y"]) > 250 for c in b["items"]):
            return x, y
    return cx + (n % 7) * 40, cy + (n % 5) * 40


def add(card):
    """Pin a card from anywhere (it lands near the middle of the board, slightly tilted)."""
    with _lock:
        b = current()
        c = _clean_card({**card, "id": secrets.token_hex(6), "added_at": time.time()})
        if not c:
            raise ValueError("That can't be pinned.")
        if not card.get("x") and not card.get("y"):
            c["x"], c["y"] = _free_spot(b)
        if not c.get("r"):
            c["r"] = round((int(hashlib.md5(c["id"].encode()).hexdigest()[:4], 16) % 9) - 4, 1)
        if c["type"] == "note" and not c.get("color"):
            c["color"] = "yellow"
        b["items"].append(c)
        b["updated_at"] = time.time()
        _write(os.path.join(_root(), "current.json"), b)
        return c


def clear():
    with _lock:
        b = _empty()
        _write(os.path.join(_root(), "current.json"), b)
        return b


# ---------------------------------------------------------------- saved boards
def saved():
    d = os.path.join(_root(), "saved")
    out = []
    for f in os.listdir(d):
        if f.endswith(".json"):
            s = _read(os.path.join(d, f), None)
            if s:
                out.append({"id": f[:-5], "name": s.get("name") or "Untitled board", "saved_at": s.get("saved_at") or 0,
                            "cards": len(s.get("items") or []), "strings": len(s.get("strings") or [])})
    return sorted(out, key=lambda s: -s["saved_at"])


def save_as(name, board=None, overwrite=True):
    """Keep the board (the one on screen, or the one given) under a name. The same name saves over that board."""
    name = re.sub(r"\s+", " ", str(name or "")).strip()[:120]
    if not name:
        raise ValueError("Give the board a name.")
    with _lock:
        b = _clean(board) if board else current()
        existing = next((s for s in saved() if s["name"].lower() == name.lower()), None) if overwrite else None
        sid = existing["id"] if existing else secrets.token_hex(5)
        b["name"], b["saved_id"], b["saved_at"] = name, sid, time.time()
        _write(os.path.join(_root(), "saved", sid + ".json"), b)
        cur = current()
        cur["name"], cur["saved_id"] = name, sid
        _write(os.path.join(_root(), "current.json"), {**b, "saved_at": None})
        return {"id": sid, "name": name}


def open_saved(sid):
    sid = re.sub(r"[^0-9a-f]", "", str(sid))
    with _lock:
        s = _read(os.path.join(_root(), "saved", sid + ".json"), None)
        if not s:
            raise LookupError("That board isn't there any more.")
        b = _clean(s)
        b["saved_id"] = sid
        _write(os.path.join(_root(), "current.json"), b)
        return b


def delete_saved(sid):
    sid = re.sub(r"[^0-9a-f]", "", str(sid))
    p = os.path.join(_root(), "saved", sid + ".json")
    if os.path.exists(p):
        os.remove(p)


# ---------------------------------------------------------------- pictures pasted or dropped on the board
def save_media(data, ext=".png"):
    if len(data) > 25 * 1024 * 1024:
        raise ValueError("That picture is too big (25 MB at most).")
    ext = ext if ext in (".png", ".jpg", ".jpeg", ".gif", ".webp") else ".png"
    name = hashlib.sha1(data).hexdigest()[:20] + ext
    path = os.path.join(media_dir(), name)
    if not os.path.exists(path):
        with open(path, "wb") as f:
            f.write(data)
    return "/api/corkboard/media/" + name
