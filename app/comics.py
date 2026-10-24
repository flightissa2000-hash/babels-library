"""Graphic novels & manga: ComicInfo.xml metadata, filename parsing, manga detection."""
import os
import re
import zipfile
import xml.etree.ElementTree as ET

IMG_EXT = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".avif")
MANGA_PUBLISHERS = ("viz", "kodansha", "shueisha", "yen press", "seven seas", "vertical", "tokyopop", "square enix",
                    "shogakukan", "kadokawa", "j-novel", "denpa", "udon", "one peace", "ghost ship", "airship",
                    "dark horse manga", "shonen jump", "shōnen jump", "hakusensha", "akita shoten")
MANGA_WORDS = re.compile(r"\b(manga|manhwa|manhua|shonen|shōnen|shojo|shōjo|seinen|josei|isekai|tankobon|tankōbon|webtoon|raw)\b", re.I)


def natural_key(s):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


def parse_comicinfo(xml_text):
    try:
        root = ET.fromstring(xml_text.encode("utf-8") if isinstance(xml_text, str) else xml_text)
    except Exception:
        return {}
    get = lambda t: (root.findtext(t) or "").strip()
    d = {k: get(k) for k in ("Title", "Series", "Number", "Volume", "Year", "Writer", "Penciller", "Artist", "Inker",
                             "CoverArtist", "Colorist", "Letterer", "Editor", "Translator",
                             "Publisher", "Genre", "Tags", "Summary", "Manga", "LanguageISO", "Characters", "Teams",
                             "Web", "AgeRating", "Count")}
    return {k: v for k, v in d.items() if v}


def parse_metroninfo(xml_text):
    """MetronInfo.xml credits: <Credits><Credit><Creator>Name</Creator><Roles><Role>Writer</Role>…"""
    try:
        root = ET.fromstring(xml_text.encode("utf-8") if isinstance(xml_text, str) else xml_text)
    except Exception:
        return {}
    out = {}
    for cr in root.iter("Credit"):
        name = (cr.findtext("Creator") or "").strip()
        roles = [(r.text or "").strip().lower() for r in cr.iter("Role")]
        for role, key in (("writer", "Writer"), ("script", "Writer"), ("story", "Writer"), ("artist", "Artist"),
                          ("penciller", "Penciller"), ("illustrator", "Artist")):
            if name and any(role in r for r in roles):
                out[key] = ", ".join(x for x in [out.get(key), name] if x)
    return out


def read_zip_info(path):
    """For CBZ: page count and ComicInfo.xml (CBR is read in the app with libarchive)."""
    out = {"pages": 0, "comicinfo": {}}
    try:
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            out["pages"] = sum(1 for n in names if n.lower().endswith(IMG_EXT) and not n.startswith("__MACOSX"))
            ci = next((n for n in names if os.path.basename(n).lower() == "comicinfo.xml"), None)
            if ci:
                out["comicinfo"] = parse_comicinfo(z.read(ci).decode("utf-8", "ignore"))
            mi = next((n for n in names if os.path.basename(n).lower() == "metroninfo.xml"), None)
            if mi:
                for k, v in parse_metroninfo(z.read(mi).decode("utf-8", "ignore")).items():
                    out["comicinfo"].setdefault(k, v)
    except (zipfile.BadZipFile, OSError):
        pass
    return out


def parse_filename(name):
    """'Berserk v01 (2003) (Digital) [Group].cbz' -> series, volume, year."""
    base = os.path.splitext(os.path.basename(name))[0]
    year = re.search(r"\((19|20)\d\d\)", base)
    clean = re.sub(r"[\[\(][^\]\)]*[\]\)]", " ", base).replace("_", " ")
    vol = re.search(r"\b(?:v|vol\.?|volume|tome|#)\s*0*(\d+)", clean, re.I) or re.search(r"\s0*(\d{1,3})\s*$", clean)
    series = clean[:vol.start()].strip(" -") if vol else clean.strip(" -")
    return {"series": re.sub(r"\s+", " ", series), "volume": vol.group(1) if vol else "",
            "year": year.group(0).strip("()") if year else ""}


def is_manga(ci, filename=""):
    if (ci.get("Manga") or "").lower().startswith("yes"):
        return True
    if (ci.get("LanguageISO") or "").lower() in ("ja", "jp", "jpn"):
        return True
    blob = " ".join([ci.get("Publisher", ""), ci.get("Genre", ""), ci.get("Tags", ""), filename]).lower()
    return any(p in blob for p in MANGA_PUBLISHERS) or bool(MANGA_WORDS.search(blob))


def metadata(filename, ci):
    """Metadata for a comic from ComicInfo.xml (if any) and its filename."""
    fn = parse_filename(filename)
    series = ci.get("Series") or fn["series"]
    vol = ci.get("Number") or ""
    if not vol and ci.get("Volume") and not re.fullmatch(r"(19|20)\d\d", ci["Volume"].strip()):
        vol = ci["Volume"]  # ComicVine stores the start *year* in Volume; ignore that
    if not vol and fn["volume"] and not re.fullmatch(r"(19|20)\d\d", fn["volume"]):
        vol = fn["volume"]
    vol = vol.lstrip("0") or vol
    title = ci.get("Title") or ""
    if series and (not title or title.lower() == series.lower()):
        title = series + (f", Vol. {vol}" if vol else "")
    elif series and title and series.lower() not in title.lower():
        title = f"{series}: {title}"
    people = []
    for k in ("Writer", "Penciller", "Artist", "Inker", "CoverArtist"):
        for p in re.split(r"[,;]", ci.get(k, "")):
            p = p.strip()
            if p and p not in people:
                people.append(p)
    manga = is_manga(ci, filename)
    genres = [g.strip() for g in re.split(r"[,;/]", ci.get("Genre", "")) if g.strip()]
    hints = [t.strip() for t in re.split(r"[,;]", ci.get("Tags", "")) if t.strip()]
    try:
        count = int(ci.get("Count") or 0)
    except ValueError:
        count = 0
    in_series = bool(vol) or count > 1
    return {
        "title": title or fn["series"] or os.path.splitext(os.path.basename(filename))[0],
        "authors": people[:6],
        "year": ci.get("Year") or fn["year"],
        "publisher": ci.get("Publisher", ""),
        "series": series if in_series else "",
        "series_index": float(vol) if vol and re.fullmatch(r"\d+(\.\d+)?", vol) else None,
        "summary": re.sub(r"<[^>]+>", " ", ci.get("Summary", ""))[:900].strip(),
        "manga": manga,
        "rtl": (ci.get("Manga") or "").lower() == "yesandrighttoleft" or (manga and (ci.get("Manga") or "").lower() != "yes"),
        "genres": genres,
        "tags": hints[:6],
        "url": ci.get("Web", ""),
    }


# ---------------------------------------------------------------------------------------------------------------
# Serving comic pages from the server: the app asks for one page at a time instead of downloading whole archives
# (comics are often 300 MB – 1 GB, which made them slow to open or get stuck).
#   CBZ / ZIP-based files:  read straight from the archive (random access, instant).
#   CBT (tar):              Python's tarfile.
#   CBR (RAR) / CB7 (7z):   unpacked once into a cache folder by a system tool (Windows 10/11's built-in tar,
#                           bsdtar, 7-Zip or unrar); pages appear as soon as they're unpacked.
# ---------------------------------------------------------------------------------------------------------------
import shutil as _shutil
import subprocess as _sp
import tarfile as _tarfile
import threading as _th
import time as _time

PAGE_EXT = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".avif")
CACHE_LIMIT = 6 * 1024 ** 3  # unpacked RAR/7z comics kept on disk


def _natural_key(s):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


def _is_page(name):
    base = os.path.basename(name)
    return name.lower().endswith(PAGE_EXT) and not name.startswith("__MACOSX") and "/__MACOSX/" not in name and not base.startswith(".")


def archive_format(path):
    with open(path, "rb") as f:
        head = f.read(264)
    if head[:4] == b"PK\x03\x04" or head[:4] == b"PK\x05\x06":
        return "zip"
    if head[:4] == b"Rar!":
        return "rar"
    if head[:6] == b"7z\xbc\xaf\x27\x1c":
        return "7z"
    if head[257:262] == b"ustar":
        return "tar"
    return "unknown"


def _tool():
    """A program that can unpack RAR / 7z archives, if this computer has one."""
    cands = []
    if os.name == "nt":
        sysroot = os.environ.get("SystemRoot", r"C:\Windows")
        cands.append(("bsdtar", os.path.join(sysroot, "System32", "tar.exe")))  # Windows' tar is bsdtar (libarchive)
        for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
            if base:
                cands.append(("7z", os.path.join(base, "7-Zip", "7z.exe")))
    for name, kind in (("bsdtar", "bsdtar"), ("7z", "7z"), ("7zz", "7z"), ("7za", "7z"), ("unrar", "unrar"), ("unar", "unar")):
        p = _shutil.which(name)
        if p:
            cands.append((kind, p))
    tar = _shutil.which("tar")
    if tar and os.name != "nt":
        try:
            if "bsdtar" in _sp.run([tar, "--version"], capture_output=True, text=True, timeout=5).stdout:
                cands.append(("bsdtar", tar))
        except Exception:
            pass
    for kind, p in cands:
        if p and os.path.exists(p):
            return kind, p
    return None, None


_NOWIN = 0x08000000 if os.name == "nt" else 0


def _extract_cmd(kind, exe, path, dest):
    if kind == "bsdtar":
        return [exe, "-xf", path, "-C", dest]
    if kind == "7z":
        return [exe, "x", "-y", "-bd", f"-o{dest}", path]
    if kind == "unrar":
        return [exe, "x", "-o+", "-idq", path, dest + os.sep]
    return [exe, "-q", "-f", "-o", dest, path]  # unar


class _Book:
    def __init__(self, path, cache_dir):
        self.path, self.cache_dir = path, cache_dir
        self.fmt = archive_format(path)
        self.lock = _th.Lock()
        self.zip = None
        self.tar = None
        self.names = []
        self.error = None
        self.done = True
        self.mtime = os.path.getmtime(path)
        self.used = _time.time()
        if self.fmt == "zip":
            self.zip = zipfile.ZipFile(path)
            self.names = sorted([n for n in self.zip.namelist() if _is_page(n)], key=_natural_key)
        elif self.fmt == "tar":
            self.tar = _tarfile.open(path)
            self.members = {m.name: m for m in self.tar.getmembers() if m.isfile()}
            self.names = sorted([n for n in self.members if _is_page(n)], key=_natural_key)
        else:
            self._unpack()

    # ---- RAR / 7z: unpack once into the cache
    def _unpack(self):
        kind, exe = _tool()
        if not kind:
            self.error = "notool"
            return
        stamp = os.path.join(self.cache_dir, ".complete")
        if os.path.exists(stamp):
            self._scan()
            self.done = True
            return
        os.makedirs(self.cache_dir, exist_ok=True)
        self.done = False
        # list first, so the reader knows how many pages there are
        try:
            if kind == "bsdtar":
                out = _sp.run([exe, "-tf", self.path], capture_output=True, text=True, timeout=300, creationflags=_NOWIN).stdout
                names = [l.strip().replace("\\", "/") for l in out.splitlines()]
            elif kind == "7z":
                out = _sp.run([exe, "l", "-slt", "-ba", self.path], capture_output=True, text=True, timeout=300, creationflags=_NOWIN).stdout
                names = [l[7:].strip().replace("\\", "/") for l in out.splitlines() if l.startswith("Path = ")]
            elif kind == "unrar":
                out = _sp.run([exe, "lb", self.path], capture_output=True, text=True, timeout=300, creationflags=_NOWIN).stdout
                names = [l.strip().replace("\\", "/") for l in out.splitlines()]
            else:
                names = []
            self.names = sorted([n for n in names if _is_page(n)], key=_natural_key)
        except Exception as e:
            print("[babel] comic listing failed:", e)
        prune_cache(os.path.dirname(self.cache_dir), keep=self.cache_dir)

        def run():
            try:
                r = _sp.run(_extract_cmd(kind, exe, self.path, self.cache_dir), capture_output=True, timeout=3600, creationflags=_NOWIN)
                if r.returncode != 0 and not any(True for _ in os.scandir(self.cache_dir)):
                    self.error = "unpack"
                    print("[babel] comic unpack failed:", (r.stderr or b"")[:300])
                else:
                    with open(stamp, "w") as f:
                        f.write("ok")
            except Exception as e:
                self.error = "unpack"
                print("[babel] comic unpack failed:", e)
            self._scan()
            self.done = True
        _th.Thread(target=run, daemon=True).start()

    def _scan(self):
        found = []
        for root, _, files in os.walk(self.cache_dir):
            for fn in files:
                rel = os.path.relpath(os.path.join(root, fn), self.cache_dir).replace("\\", "/")
                if _is_page(rel):
                    found.append(rel)
        if found and (not self.names or self.done or len(found) >= len(self.names)):
            self.names = sorted(found, key=_natural_key)

    def info(self):
        return {"count": len(self.names), "ready": self.done, "format": self.fmt, "error": self.error}

    def page(self, i, wait=25):
        self.used = _time.time()
        if i < 0 or i >= len(self.names):
            raise IndexError("no such page")
        name = self.names[i]
        if self.zip is not None:
            with self.lock:
                return self.zip.read(name), name
        if self.tar is not None:
            with self.lock:
                return self.tar.extractfile(self.members[name]).read(), name
        full = os.path.join(self.cache_dir, *name.split("/"))
        t0 = _time.time()
        while True:
            # a page counts as ready once the next one exists (or unpacking has finished)
            nxt = os.path.join(self.cache_dir, *self.names[i + 1].split("/")) if i + 1 < len(self.names) else None
            if os.path.exists(full) and (self.done or (nxt and os.path.exists(nxt))):
                with open(full, "rb") as f:
                    return f.read(), name
            if self.done and not os.path.exists(full):
                raise IndexError("page missing")
            if _time.time() - t0 > wait:
                raise TimeoutError("still unpacking")
            _time.sleep(0.15)

    def read_member(self, want):
        """Any file in the archive (e.g. ComicInfo.xml) by base name, or None."""
        want = want.lower()
        if self.zip is not None:
            n = next((n for n in self.zip.namelist() if os.path.basename(n).lower() == want), None)
            return self.zip.read(n) if n else None
        if self.tar is not None:
            n = next((n for n in self.members if os.path.basename(n).lower() == want), None)
            return self.tar.extractfile(self.members[n]).read() if n else None
        for root, _, files in os.walk(self.cache_dir):
            for fn in files:
                if fn.lower() == want:
                    with open(os.path.join(root, fn), "rb") as f:
                        return f.read()
        return None


_books = {}
_books_lock = _th.Lock()


def book(item_id, path, cache_root):
    with _books_lock:
        b = _books.get(item_id)
        if b and b.path == path and b.mtime == os.path.getmtime(path):
            return b
        b = _Book(path, os.path.join(cache_root, str(item_id)))
        _books[item_id] = b
        # keep only a few archives open
        if len(_books) > 6:
            old = sorted(_books.items(), key=lambda kv: kv[1].used)[0][0]
            ob = _books.pop(old)
            try:
                ob.zip and ob.zip.close()
                ob.tar and ob.tar.close()
            except Exception:
                pass
        return b


def prune_cache(cache_root, keep=None):
    """Delete the least recently used unpacked comics once the cache gets large."""
    try:
        dirs = [os.path.join(cache_root, d) for d in os.listdir(cache_root)]
    except OSError:
        return
    def size(d):
        total = 0
        for root, _, files in os.walk(d):
            for fn in files:
                try:
                    total += os.path.getsize(os.path.join(root, fn))
                except OSError:
                    pass
        return total
    info = sorted(((os.path.getmtime(d), d, size(d)) for d in dirs if os.path.isdir(d) and d != keep))
    total = sum(s for _, _, s in info)
    for _, d, s in info:
        if total <= CACHE_LIMIT:
            break
        _shutil.rmtree(d, ignore_errors=True)
        total -= s
