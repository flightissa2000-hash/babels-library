"""Music, TV and Movies: metadata from embedded tags (mutagen) and file / folder names."""
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor_py"))

import taxonomy as T  # noqa: E402

AUDIO_EXT = (".mp3", ".flac", ".m4a", ".aac", ".ogg", ".oga", ".opus", ".wav", ".wma", ".aiff", ".aif", ".alac")
VIDEO_EXT = (".mp4", ".m4v", ".mkv", ".webm", ".avi", ".mov", ".wmv", ".mpg", ".mpeg", ".ts")
MEDIA_EXT = AUDIO_EXT + VIDEO_EXT
CONTENT_TYPES = {".mp3": "audio/mpeg", ".flac": "audio/flac", ".m4a": "audio/mp4", ".aac": "audio/aac", ".ogg": "audio/ogg",
                 ".oga": "audio/ogg", ".opus": "audio/ogg", ".wav": "audio/wav", ".aiff": "audio/aiff", ".aif": "audio/aiff",
                 ".mp4": "video/mp4", ".m4v": "video/mp4", ".mkv": "video/x-matroska", ".webm": "video/webm",
                 ".avi": "video/x-msvideo", ".mov": "video/quicktime", ".wmv": "video/x-ms-wmv", ".mpg": "video/mpeg",
                 ".mpeg": "video/mpeg", ".ts": "video/mp2t"}

RELEASE_JUNK = re.compile(
    r"[\s.\-_\[(]+(?:480p|576p|720p|1080p|2160p|4k|uhd|hdr10?|dv|x264|x265|h\.?264|h\.?265|hevc|avc|bluray|blu-ray|brrip|bdrip|"
    r"webrip|web-?dl|web|hdtv|dvdrip|dvd|hdrip|aac\d?|ac3|dts|ddp?\d?\.?\d?|atmos|10bit|8bit|proper|repack|extended|unrated|"
    r"remastered|imax|yify|yts|rarbg|amzn|nf|hulu|dsnp|hmax|criterion|multi|subs?|dual|complete)\b.*$", re.I)


def is_media(ext):
    return ext.lower() in MEDIA_EXT


def kind_for(path, tags=None):
    ext = os.path.splitext(path)[1].lower()
    if ext in AUDIO_EXT:
        return "music"
    if tags and tags.get("tv"):
        return "tv"
    return "tv" if parse_tv(path) else "movie"


def _clean(s):
    s = re.sub(r"\[[^\]]*\]", " ", s)  # [Group] / [Eng Sub] tags first, or 'Sub' inside one cuts off the real title
    s = re.sub(r"[._]+", " ", s)
    s = RELEASE_JUNK.sub("", s)
    return re.sub(r"\s+", " ", s).strip(" -")


def series_key(name):
    """Comparable form of a show name: 'Psycho-Pass', 'Psycho Pass (2012)' and 'psycho.pass' all match."""
    n = re.sub(r"\((?:19|20)\d\d\)|\b(?:19|20)\d\d\b", " ", (name or "").lower())
    return re.sub(r"[^a-z0-9]+", "", n)


def parse_tv(path):
    base = os.path.splitext(os.path.basename(path))[0]
    base = re.sub(r"^\s*(\[[^\]]*\]\s*)+", "", base)  # leading [Group] tags
    m = re.search(r"^(.*?)[\s._\-]*[Ss](\d{1,2})[\s._\-]*[Ee][Pp]?(\d{1,3})(?:[\s._\-]*[Ee]\d{1,3})?(.*)$", base) or \
        re.search(r"^(.*?)[\s._\-]+(\d{1,2})x(\d{2,3})(.*)$", base) or \
        re.search(r"^(.*?)[\s._]+[Ss](?:eason)?[\s._]?(\d{1,2})[\s._]*-[\s._]*(?:[Ee][Pp]?)?(\d{1,4})(?:v\d)?\b(.*)$", base)
    if not m:
        # anime style: "Show - 03 [1080p]" / "Show Ep 03" (season 1)
        a = re.search(r"^(.*?)\s+-\s+(?:[Ee][Pp]?)?(\d{1,4})(?:v\d)?(?=\s|\[|\(|$)(.*)$", base) or \
            re.search(r"^(.*?)[\s._]+(?:[Ee]p|[Ee]pisode)[\s._]*(\d{1,4})\b(.*)$", base)
        if a and _clean(a.group(1)) and not re.fullmatch(r"(19|20)\d\d", a.group(2)):
            show = re.sub(r"\s*\(?(19|20)\d\d\)?$", "", _clean(a.group(1))).strip()
            ep = int(a.group(2))
            return {"series": show, "season": 1, "episode": ep, "title": _clean(a.group(3)) or f"Episode {ep}"}
    parent = os.path.basename(os.path.dirname(path))
    if not m:
        sm = re.match(r"season[\s._-]*(\d+)", parent, re.I)
        em = re.search(r"(?:^|[\s._-])(?:e|ep|episode)[\s._-]*(\d{1,3})\b", base, re.I) or \
            (re.match(r"^\s*(\d{1,3})\b", base) if sm else None)
        if sm and em:
            show = os.path.basename(os.path.dirname(os.path.dirname(path)))
            return {"series": _clean(show), "season": int(sm.group(1)), "episode": int(em.group(1)),
                    "title": _clean(base[em.end():]) or f"Episode {int(em.group(1))}"}
        return None
    show = _clean(m.group(1)) or _clean(os.path.basename(os.path.dirname(os.path.dirname(path)))) or _clean(parent)
    show = re.sub(r"\s*\(?(19|20)\d\d\)?$", "", show).strip()
    ep_title = _clean(m.group(4))
    return {"series": show, "season": int(m.group(2)), "episode": int(m.group(3)),
            "title": ep_title or f"Episode {int(m.group(3))}"}


def parse_movie(path):
    base = os.path.splitext(os.path.basename(path))[0]
    y = re.search(r"[\s.(\[_-]((?:19|20)\d\d)(?:[\s.)\]_-]|$)", base)
    title = base[:y.start()] if y else base
    title = _clean(title)
    if not title or title.lower() in ("movie", "video", "film"):
        title = _clean(os.path.basename(os.path.dirname(path)))
    return {"title": title, "year": y.group(1) if y else ""}


def _num(v):
    m = re.match(r"\s*(\d+)", str(v or ""))
    return int(m.group(1)) if m else None


def read_tags(path):
    """Embedded tags via mutagen (MP3/ID3, FLAC, MP4/M4A, OGG/Opus, …). Returns a plain dict."""
    out = {}
    try:
        from mutagen import File as MFile
        f = MFile(path, easy=True)
        if f is not None:
            g = lambda k: (f.tags.get(k) or [""])[0] if f.tags and f.tags.get(k) else ""
            if f.tags:
                out = {"title": g("title"), "artist": g("artist"), "albumartist": g("albumartist"), "album": g("album"),
                       "track": _num(g("tracknumber")), "disc": _num(g("discnumber")), "date": g("date"), "genre": g("genre")}
            if getattr(f, "info", None) is not None and getattr(f.info, "length", None):
                out["duration"] = float(f.info.length)
        raw = MFile(path)
        if raw is not None and raw.tags is not None:
            t = raw.tags
            # MP4 video atoms
            if hasattr(t, "get") and path.lower().endswith((".mp4", ".m4v", ".mov")):
                out["tv"] = bool(t.get("tvsh")) or (t.get("stik") or [None])[0] == 10
                for key, name in (("tvsh", "show"), ("©nam", "title"), ("©day", "date"), ("©gen", "genre"), ("ldes", "desc"), ("desc", "short_desc")):
                    if t.get(key):
                        out[name] = str(t[key][0])
                if t.get("tvsn"):
                    out["season"] = int(t["tvsn"][0])
                if t.get("tves"):
                    out["episode"] = int(t["tves"][0])
            out["picture"] = _picture(raw)
    except Exception as e:
        print("[inkwell] tags unreadable:", os.path.basename(path), e)
    return out


def _picture(raw):
    try:
        if hasattr(raw, "pictures") and raw.pictures:  # FLAC
            return raw.pictures[0].data
        t = raw.tags
        if hasattr(t, "getall"):  # ID3
            pics = t.getall("APIC")
            if pics:
                return pics[0].data
        if hasattr(t, "get") and t.get("covr"):  # MP4
            return bytes(t["covr"][0])
        if hasattr(t, "get") and t.get("metadata_block_picture"):  # Ogg
            import base64
            from mutagen.flac import Picture
            return Picture(base64.b64decode(t["metadata_block_picture"][0])).data
    except Exception:
        pass
    return None


def folder_cover(path):
    d = os.path.dirname(path)
    for n in ("cover.jpg", "folder.jpg", "front.jpg", "cover.png", "folder.png", "album.jpg", "poster.jpg"):
        p = os.path.join(d, n)
        if os.path.exists(p):
            with open(p, "rb") as f:
                return f.read()
    return None


def metadata(path, filename=None):
    """Everything Babel's Library needs for a media file: kind, title, artist/album or series/season/episode, genre, cover."""
    filename = filename or os.path.basename(path)
    tags = read_tags(path)
    kind = kind_for(path if filename == os.path.basename(path) else os.path.join(os.path.dirname(path), filename), tags)
    meta = {"kind": kind, "duration": tags.get("duration"), "picture": tags.get("picture") or folder_cover(path)}
    if kind == "music":
        base = os.path.splitext(filename)[0]
        m = re.match(r"^\s*(\d{1,3})[\s.\-_]+(.*)$", base)
        parent = os.path.basename(os.path.dirname(path))
        artist = tags.get("artist") or ""
        if not artist and " - " in base:
            artist = base.split(" - ")[0].strip()
        meta.update({
            "title": tags.get("title") or (m.group(2) if m else base).strip(),
            "authors": [a.strip() for a in re.split(r";|/|\s+feat\.?\s+", artist) if a.strip()] or ["Unknown artist"],
            "album_artist": tags.get("albumartist") or artist or "Unknown artist",
            "album": tags.get("album") or (parent if parent and parent.lower() not in ("music", "downloads", "inbox", "media", "audio", "songs", "desktop", "documents", "new folder", "library-inbox", "my music") else "Singles"),
            "track": tags.get("track") or (int(m.group(1)) if m else None),
            "disc": tags.get("disc"),
            "year": (re.search(r"\d{4}", tags.get("date") or "") or [""])[0] if tags.get("date") else "",
            "genre": T.music_genre(tags.get("genre")),
        })
    elif kind == "tv":
        p = parse_tv(os.path.join(os.path.dirname(path), filename)) or {}
        meta.update({
            "series": tags.get("show") or p.get("series") or "Unknown series",
            "season": tags.get("season") or p.get("season") or 1,
            "episode": tags.get("episode") or p.get("episode"),
            "title": tags.get("title") or p.get("title") or os.path.splitext(filename)[0],
            "year": (re.search(r"\d{4}", tags.get("date") or "") or [""])[0] if tags.get("date") else "",
            "genre": tags.get("genre") or None,
            "summary": tags.get("desc") or tags.get("short_desc") or "",
        })
    else:
        p = parse_movie(os.path.join(os.path.dirname(path), filename))
        tag_title = tags.get("title") or ""
        if p["title"] and series_key(p["title"]) and series_key(p["title"]) in series_key(tag_title):
            tag_title = ""  # the tag is just the file's title plus noise ('GODZILLA RAIDS AGAIN FULL COLOR')
        meta.update({
            "title": tag_title or p["title"],
            "year": p["year"] or ((re.search(r"\d{4}", tags.get("date") or "") or [""])[0] if tags.get("date") else ""),
            "genre": tags.get("genre") or None,
            "summary": tags.get("desc") or tags.get("short_desc") or "",
        })
    return meta


def safe_part(s, default):
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", (s or "").strip()).strip(" .")
    return s[:80] or default


def subfolder(kind, meta):
    if kind == "music":
        return os.path.join("Music", safe_part(meta.get("album_artist") or (meta.get("authors") or [""])[0], "Unknown artist"),
                            safe_part(meta.get("album"), "Singles"))
    if kind == "tv":
        return os.path.join("TV", safe_part(meta.get("series"), "Unknown series"), f"Season {int(meta.get('season') or 1):02d}")
    return "Movies"
