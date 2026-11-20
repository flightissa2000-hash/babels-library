"""Space photos for the Galaxy theme's sleep screen.

ESA's own picks: the Top 100 images from Hubble (esahubble.org) and the Top 100 from Webb (esawebb.org), both
CC BY 4.0. From those ~200, 100 are chosen at random and kept on this computer (not on the library's drive), in
%LOCALAPPDATA%\\BabelsLibrary\\spacephotos. A fresh 100 are drawn every 30 days. The sleep screen shows them in a
random order, each with its title and credit."""
import html
import json
import os
import random
import re
import threading
import time
import urllib.request

DIR = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "BabelsLibrary", "spacephotos")
LIST = os.path.join(DIR, "list.json")
SOURCES = [
    ("https://esahubble.org/images/archive/top100/", "ESA/Hubble & NASA", "cdn.esahubble.org"),
    ("https://esawebb.org/images/archive/top100/", "ESA/Webb, NASA & CSA", "cdn.esawebb.org"),
]
HOW_MANY, REDRAW_DAYS = 100, 30
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) BabelsLibrary/1.0"}
_lock = threading.Lock()
_busy = False
# a top-100 slide: <img ... src="https://cdn.esahubble.org/archives/images/wallpaper2/heic2017a.jpg" ... alt="Title"/>
SLIDE = re.compile(r'<img[^>]+?(?:data-lazy|src)="(https://cdn\.esa(?:hubble|webb)\.org/archives/images/wallpaper2/([A-Za-z0-9_-]+)\.jpg)"[^>]*alt="([^"]*)"')


def _get(url, timeout=40):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return r.read()


def _candidates():
    out, seen = [], set()
    for page, credit, _ in SOURCES:
        try:
            s = _get(page).decode("utf-8", "replace")
        except Exception as e:
            print("[spacephotos] couldn't read", page, e)
            continue
        for url, pid, alt in SLIDE.findall(s):
            if pid in seen:
                continue
            seen.add(pid)
            out.append({"id": pid, "url": url, "title": html.unescape(alt).strip(), "credit": credit})
    return out


def _load():
    try:
        with open(LIST, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _save(d):
    os.makedirs(DIR, exist_ok=True)
    tmp = LIST + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False)
    os.replace(tmp, LIST)


def _file(pid):
    return os.path.join(DIR, re.sub(r"[^A-Za-z0-9_-]", "_", pid) + ".jpg")


def _work():
    """Draw the 100 (when there are none, or they're 30 days old), then fetch any that aren't here yet, gently."""
    global _busy
    try:
        d = _load()
        if not d or not d.get("photos") or time.time() - d.get("drawn", 0) > REDRAW_DAYS * 86400:
            pool = _candidates()
            if pool:
                pick = random.sample(pool, min(HOW_MANY, len(pool)))
                keep = {p["id"] for p in pick}
                d = {"drawn": time.time(), "photos": pick}
                _save(d)
                # the last draw's photos that weren't picked again: off this computer
                for name in os.listdir(DIR):
                    if name.endswith(".jpg") and name[:-4] not in keep:
                        try:
                            os.remove(os.path.join(DIR, name))
                        except OSError:
                            pass
        if not d:
            return
        for p in d["photos"]:
            f = _file(p["id"])
            if os.path.isfile(f):
                continue
            try:
                data = _get(p["url"], 90)
                if data[:2] == b"\xff\xd8":            # (a JPEG, not an error page)
                    with open(f + ".part", "wb") as o:
                        o.write(data)
                    os.replace(f + ".part", f)
            except Exception as e:
                print("[spacephotos]", p["id"], e)
            time.sleep(0.4)
    finally:
        _busy = False


def ensure():
    """Start drawing/fetching in the background (once at a time)."""
    global _busy
    with _lock:
        if _busy:
            return
        _busy = True
    threading.Thread(target=_work, daemon=True, name="spacephotos").start()


def listing():
    """The photos that are on this computer now: [{id, title, credit}] (and starts fetching the rest)."""
    d = _load() or {}
    photos = d.get("photos") or []
    have = [{"id": p["id"], "title": p["title"], "credit": p["credit"]} for p in photos if os.path.isfile(_file(p["id"]))]
    if len(have) < len(photos) or not photos or time.time() - d.get("drawn", 0) > REDRAW_DAYS * 86400:
        ensure()
    return {"photos": have, "drawn": len(photos)}


def path(pid):
    f = _file(pid)
    return f if os.path.isfile(f) else None
