"""Turn a book into an audiobook with Piper (a free, offline neural voice).

Output: <library>/Audiobooks/<Author>/<Title>/NN - <Chapter>.mp3 plus audiobook.json, which lists the chapters and,
for every sentence, when it is spoken (so the reader can highlight along with the audio).
Audiobooks are attached to their book: they never appear as music.
"""
import html
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
import urllib.request
import zipfile
import posixpath
from html.parser import HTMLParser

import store

PIPER_DIR = os.path.join(store.DATA_DIR, "piper")
VOICE_DIR = os.path.join(PIPER_DIR, "voices")
HF = "https://huggingface.co/rhasspy/piper-voices/resolve/main/"
VOICES = {
    "en_US-lessac-medium": ("Lessac: American, warm, neutral (recommended)", "en/en_US/lessac/medium/"),
    "en_US-ryan-high": ("Ryan: American, male, high quality", "en/en_US/ryan/high/"),
    "en_US-amy-medium": ("Amy: American, female", "en/en_US/amy/medium/"),
    "en_US-joe-medium": ("Joe: American, male", "en/en_US/joe/medium/"),
    "en_GB-alan-medium": ("Alan: British, male", "en/en_GB/alan/medium/"),
    "en_GB-jenny_dioco-medium": ("Jenny: British, female", "en/en_GB/jenny_dioco/medium/"),
}
# a second source for the default voice, in case Hugging Face is unreachable
FALLBACK = {"en_US-lessac-medium": "https://github.com/rhasspy/piper/releases/download/v0.0.2/voice-en-us-lessac-medium.tar.gz"}

STATE = {"running": False, "item": None, "title": "", "chapter": "", "done": 0, "total": 0, "message": "", "setup": None, "error": ""}
QUEUE = []
_lock = threading.Lock()
_cancel = set()


def _log(msg, kind="import"):
    try:
        import server
        server.log(msg, kind)
    except Exception:
        print("[babel]", msg)


# ------------------------------------------------------------------ set-up
def deps_ok():
    try:
        import piper  # noqa: F401
        import lameenc  # noqa: F401
        return True
    except Exception:
        return False


def voice_path(vid):
    return os.path.join(VOICE_DIR, vid + ".onnx")


def voice_installed(vid):
    return os.path.exists(voice_path(vid)) and os.path.exists(voice_path(vid) + ".json")


def status():
    return {"deps": deps_ok(), "voices": [{"id": k, "label": v[0], "installed": voice_installed(k)} for k, v in VOICES.items()],
            "job": dict(STATE), "queue": [q["item"] for q in QUEUE]}


def _python_exe():
    exe = sys.executable
    if os.name == "nt" and os.path.basename(exe).lower() == "pythonw.exe":
        cand = os.path.join(os.path.dirname(exe), "python.exe")
        if os.path.exists(cand):
            exe = cand
    return exe


def _download(url, dest):
    tmp = dest + ".part"
    req = urllib.request.Request(url, headers={"User-Agent": "BabelsLibrary/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        got = 0
        while True:
            b = r.read(1 << 16)
            if not b:
                break
            f.write(b)
            got += len(b)
            if total:
                STATE["setup"] = f"Downloading voice… {got * 100 // total}%"
    os.replace(tmp, dest)


def setup(vid):
    """Install Piper + the MP3 encoder (pip, one time) and download a voice."""
    vid = vid if vid in VOICES else "en_US-lessac-medium"
    try:
        if not deps_ok():
            STATE["setup"] = "Installing the voice engine (one time, needs internet)…"
            flags = 0x08000000 if os.name == "nt" else 0
            base = [_python_exe(), "-m", "pip", "install", "--user", "--disable-pip-version-check", "piper-tts", "lameenc"]
            r = subprocess.run(base, capture_output=True, text=True, creationflags=flags)
            if r.returncode != 0 and "externally-managed" in (r.stderr + r.stdout):
                r = subprocess.run(base + ["--break-system-packages"], capture_output=True, text=True, creationflags=flags)
            if r.returncode != 0:
                raise RuntimeError("Couldn't install the voice engine: " + (r.stderr or r.stdout).strip().splitlines()[-1][:300])
            import importlib
            import site
            importlib.invalidate_caches()
            try:
                site.addsitedir(site.getusersitepackages())
            except Exception:
                pass
            if not deps_ok():
                raise RuntimeError("The voice engine installed, but Babel's Library needs a restart to use it.")
        if not voice_installed(vid):
            os.makedirs(VOICE_DIR, exist_ok=True)
            STATE["setup"] = "Downloading voice…"
            try:
                path = HF + VOICES[vid][1] + vid
                _download(path + ".onnx.json", voice_path(vid) + ".json")
                _download(path + ".onnx", voice_path(vid))
            except Exception as e:
                if vid not in FALLBACK:
                    raise
                print("[babel] voice download from Hugging Face failed, trying GitHub:", e)
                import tarfile
                tgz = os.path.join(PIPER_DIR, "voice.tgz")
                _download(FALLBACK[vid], tgz)
                with tarfile.open(tgz) as t:
                    for m in t.getmembers():
                        if m.name.endswith(".onnx"):
                            with t.extractfile(m) as src, open(voice_path(vid), "wb") as dst:
                                shutil.copyfileobj(src, dst)
                        elif m.name.endswith(".onnx.json"):
                            with t.extractfile(m) as src, open(voice_path(vid) + ".json", "wb") as dst:
                                shutil.copyfileobj(src, dst)
                os.remove(tgz)
        STATE["setup"] = None
        STATE["error"] = ""
        return True
    except Exception as e:
        traceback.print_exc()
        STATE["setup"] = None
        STATE["error"] = str(e)
        _log(f"Audiobook set-up failed: {e}", "error")
        return False


# ------------------------------------------------------------------ text
BLOCK = {"p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "blockquote", "section", "article", "td", "th", "dd", "dt", "pre", "figcaption"}
SKIP = {"script", "style", "head", "title", "nav", "svg", "math", "rt", "rp"}


class _Text(HTMLParser):
    """Paragraph texts of an XHTML document, whitespace-collapsed exactly like the browser's text content."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks, self.cur, self.skip, self.heading = [], [], 0, None
        self._in_h = False

    def handle_starttag(self, tag, attrs):
        if tag in SKIP:
            self.skip += 1
        elif tag in BLOCK or tag == "br":
            self.flush()
        if tag in ("h1", "h2", "h3"):
            self._in_h = True
        # footnote markers read badly ("word12"): skip superscripts
        if tag == "sup":
            self.skip += 1

    def handle_endtag(self, tag):
        if tag in SKIP or tag == "sup":
            self.skip = max(0, self.skip - 1)
        elif tag in BLOCK:
            if tag in ("h1", "h2", "h3") and self.cur and not self.heading:
                self.heading = re.sub(r"\s+", " ", "".join(self.cur)).strip()
            self.flush()
        if tag in ("h1", "h2", "h3"):
            self._in_h = False

    def handle_data(self, d):
        if not self.skip:
            self.cur.append(d)

    def flush(self):
        t = re.sub(r"\s+", " ", "".join(self.cur)).strip()
        if t:
            self.blocks.append(t)
        self.cur = []


ABBR = re.compile(r"\b(?:Mr|Mrs|Ms|Dr|Prof|Sr|Jr|St|vs|etc|e\.g|i\.e|Fig|Figs|Eq|No|Vol|pp|cf|approx|Gen|Col|Capt|Lt|Sgt|Mt|Inc|Ltd|Co)\.$", re.I)


def sentences(text):
    """Split a paragraph into sentences (keeping the exact characters, so they can be found on the page)."""
    out, start = [], 0
    for m in re.finditer(r'[.!?…]+["”’»)\]]*\s+(?=["“‘«(\[]?[A-Z0-9])', text):
        piece = text[start:m.end()].strip()
        if ABBR.search(text[start:m.start() + 1]) or len(piece) < 2:
            continue
        out.append(piece)
        start = m.end()
    tail = text[start:].strip()
    if tail:
        out.append(tail)
    # very long sentences: break at ; or , so the voice keeps a natural pace
    res = []
    for s in out:
        while len(s) > 420:
            cut = max(s.rfind("; ", 0, 380), s.rfind(", ", 0, 380))
            if cut < 120:
                break
            res.append(s[:cut + 1])
            s = s[cut + 2:]
        res.append(s)
    return [s for s in res if re.search(r"\w", s)]


def _epub_toc(z, opf_dir, opf):
    titles = {}
    nav = re.search(r'<item[^>]+properties="[^"]*\bnav\b[^"]*"[^>]*>', opf)
    try:
        if nav:
            href = re.search(r'href="([^"]+)"', nav.group(0)).group(1)
            doc = z.read(posixpath.normpath(posixpath.join(opf_dir, href))).decode("utf-8", "ignore")
            base = posixpath.dirname(href)
            for m in re.finditer(r'<a[^>]+href="([^"#]+)(?:#[^"]*)?"[^>]*>(.*?)</a>', doc, re.S):
                key = posixpath.normpath(posixpath.join(base, m.group(1)))
                t = html.unescape(re.sub(r"<[^>]+>|\s+", " ", m.group(2))).strip()
                if t and key not in titles:
                    titles[key] = re.sub(r"\s+", " ", t)
        else:
            ncx = re.search(r'<item[^>]+media-type="application/x-dtbncx\+xml"[^>]*>', opf)
            if ncx:
                href = re.search(r'href="([^"]+)"', ncx.group(0)).group(1)
                doc = z.read(posixpath.normpath(posixpath.join(opf_dir, href))).decode("utf-8", "ignore")
                base = posixpath.dirname(href)
                for m in re.finditer(r"<navPoint.*?<text>(.*?)</text>.*?<content[^>]+src=\"([^\"#]+)", doc, re.S):
                    key = posixpath.normpath(posixpath.join(base, m.group(2)))
                    if key not in titles:
                        titles[key] = html.unescape(re.sub(r"\s+", " ", m.group(1))).strip()
    except Exception:
        pass
    return titles


def epub_chapters(path):
    z = zipfile.ZipFile(path)
    cont = z.read("META-INF/container.xml").decode("utf-8", "ignore")
    opf_path = re.search(r'full-path="([^"]+)"', cont).group(1)
    opf = z.read(opf_path).decode("utf-8", "ignore")
    opf_dir = posixpath.dirname(opf_path)
    manifest = {}
    for m in re.finditer(r"<item\b[^>]*>", opf):
        tag = m.group(0)
        i = re.search(r'\bid="([^"]+)"', tag)
        h = re.search(r'\bhref="([^"]+)"', tag)
        if i and h:
            manifest[i.group(1)] = urllib.request.url2pathname(h.group(1)).replace("\\", "/") if "%" in h.group(1) else h.group(1)
    titles = _epub_toc(z, opf_dir, opf)
    chapters = []
    for m in re.finditer(r"<itemref\b[^>]*>", opf):
        tag = m.group(0)
        if 'linear="no"' in tag:
            continue
        idref = re.search(r'idref="([^"]+)"', tag)
        href = manifest.get(idref.group(1)) if idref else None
        if not href:
            continue
        full = posixpath.normpath(posixpath.join(opf_dir, href))
        try:
            doc = z.read(full).decode("utf-8", "ignore")
        except KeyError:
            continue
        p = _Text()
        p.feed(doc)
        p.flush()
        sents = [s for b in p.blocks for s in sentences(b)]
        if not sents:
            continue
        title = titles.get(posixpath.normpath(href)) or titles.get(full) or p.heading or ""
        text_len = sum(len(s) for s in sents)
        entry = [{"text": s, "href": href} for s in sents]
        # fold tiny untitled sections (title pages, copyright notes) into the next chapter
        if chapters and not title and chapters[-1].get("_small"):
            chapters[-1]["sentences"] += entry
            chapters[-1]["_small"] = text_len < 600
            continue
        chapters.append({"title": title, "href": href, "sentences": entry, "_small": text_len < 600 and not title})
    for i, c in enumerate(chapters):
        c.pop("_small", None)
        c["title"] = c["title"] or f"Part {i + 1}"
    return chapters


def _clean_pdf_pages(texts):
    lines_per_page = [[l.strip() for l in (t or "").splitlines()] for t in texts]
    # running headers/footers: short lines that repeat on many pages
    from collections import Counter
    edge = Counter()
    for ls in lines_per_page:
        cand = [l for l in (ls[:2] + ls[-2:]) if l and len(l) < 80]
        for l in set(re.sub(r"\d+", "#", l) for l in cand):
            edge[l] += 1
    repeated = {k for k, v in edge.items() if v >= max(3, len(texts) * 0.3)}
    pages = []
    for ls in lines_per_page:
        keep = [l for l in ls if l and not re.fullmatch(r"[\divxlcIVXLC\-–— .]{1,8}", l) and re.sub(r"\d+", "#", l) not in repeated]
        t = "\n".join(keep)
        t = re.sub(r"(\w)-\n(\w)", r"\1\2", t)          # re-join hyphenated words
        t = re.sub(r"\s*\n\s*", " ", t)
        pages.append(re.sub(r"\s+", " ", t).strip())
    return pages


def pdf_chapters(path):
    import extract  # noqa: F401  (adds the bundled pypdf to the path)
    from pypdf import PdfReader
    r = PdfReader(path)
    texts = []
    for pg in r.pages:
        try:
            texts.append(pg.extract_text() or "")
        except Exception:
            texts.append("")
    pages = _clean_pdf_pages(texts)
    marks = []
    try:
        def walk(items):
            for o in items:
                if isinstance(o, list):
                    walk(o)
                else:
                    try:
                        marks.append((r.get_destination_page_number(o), str(o.title).strip()))
                    except Exception:
                        pass
        walk(r.outline)
    except Exception:
        pass
    marks = sorted({(p, t) for p, t in marks if t}, key=lambda x: x[0])
    if len(marks) < 2:
        step = 15
        marks = [(i, f"Pages {i + 1}–{min(len(pages), i + step)}") for i in range(0, len(pages), step)]
    chapters = []
    for k, (start, title) in enumerate(marks):
        end = marks[k + 1][0] if k + 1 < len(marks) else len(pages)
        if end <= start and k + 1 < len(marks):
            continue
        sents = []
        for pi in range(start, max(start + 1, end)):
            if pi < len(pages):
                sents += [{"text": s, "page": pi + 1} for s in sentences(pages[pi])]
        if sents:
            chapters.append({"title": title, "page": start + 1, "sentences": sents})
    if marks and marks[0][0] > 0:  # text before the first bookmark
        pre = [{"text": s, "page": pi + 1} for pi in range(0, marks[0][0]) for s in sentences(pages[pi])]
        if sum(len(s["text"]) for s in pre) > 400:
            chapters.insert(0, {"title": "Opening", "page": 1, "sentences": pre})
    return chapters


def chapters_for(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".epub":
        return epub_chapters(path)
    if ext == ".pdf":
        return pdf_chapters(path)
    raise ValueError("Audiobooks can be made from EPUB and PDF books.")


def speakable(s):
    """What the voice should say (the text shown on the page stays unchanged)."""
    s = re.sub(r"\[\d+(?:[,–-]\d+)*\]", "", s)           # citation markers [12]
    s = re.sub(r"https?://\S+", "link", s)
    s = s.replace("&", " and ").replace("—", ", ").replace("–", " to ")
    return s


# ------------------------------------------------------------------ building
def _safe(s, default):
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", (s or "").strip()).strip(" .")
    return s[:80] or default


def folder_for(item):
    import files
    who = (item.get("authors") or ["Unknown author"])[0]
    return os.path.join(files.library_root(), "Audiobooks", _safe(who, "Unknown author"), _safe(item.get("title"), f"Book {item['id']}"))


def manifest_path(item):
    d = audio_dir(item)
    return os.path.join(d, "audiobook.json") if d else None


def audio_dir(item):
    raw = (store.get_item(item["id"], raw=True) or {}).get("audio_dir")
    return store.path_from_db(raw) if raw else None


def load_manifest(item):
    p = manifest_path(item)
    if not p or not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


# An unfinished audiobook keeps its finished chapters in "<folder>.building" with progress.json, so it can carry on
# where it stopped (Stop, a crash, closing the app) instead of starting again.
_thread = None


def _work_dir(item):
    return folder_for(item) + ".building"


def _progress_path(item):
    return os.path.join(_work_dir(item), "progress.json")


def load_progress(item):
    try:
        with open(_progress_path(item), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _save_progress(item, prog):
    tmp = _progress_path(item) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(prog, f, ensure_ascii=False)
    os.replace(tmp, _progress_path(item))


def resume_info(item):
    p = load_progress(item)
    if not p or not p.get("total_chapters"):
        return None
    done = len(p.get("chapters") or [])
    return {"voice": p.get("voice"), "speed": p.get("speed"), "chapters_done": done, "chapters": p["total_chapters"],
            "pct": round(100 * (p.get("sentences_done") or 0) / max(1, p.get("total_sentences") or 1))}


def _idle_status(item):
    """What an item's audiobook status should be when nothing is being made for it."""
    if not item:
        return None
    if resume_info(item):
        return "partial"
    return "ready" if load_manifest(item) else None


def reset_stale():
    """At start-up: a book left 'building' or 'queued' by a previous run is really paused."""
    try:
        for it in store.list_items():
            if it.get("audio_status") in ("building", "queued"):
                store.update_item(it["id"], {"audio_status": _idle_status(it)})
    except Exception:
        traceback.print_exc()


def queue(item_id, voice, speed, fresh=False):
    global _thread
    with _lock:
        _cancel.discard(item_id)
        if any(q["item"] == item_id for q in QUEUE) or (STATE.get("running") and STATE.get("item") == item_id):
            return
        if fresh:
            it = store.get_item(item_id)
            if it:
                shutil.rmtree(_work_dir(it), ignore_errors=True)
        QUEUE.append({"item": item_id, "voice": voice, "speed": speed})
        store.update_item(item_id, {"audio_status": "queued"})
        if _thread is None or not _thread.is_alive():
            STATE.update(running=True, error="")
            _thread = threading.Thread(target=_worker, daemon=True)
            _thread.start()


def cancel(item_id):
    with _lock:
        QUEUE[:] = [q for q in QUEUE if q["item"] != item_id]
        building = STATE.get("running") and STATE.get("item") == item_id and _thread is not None and _thread.is_alive()
        if building:
            _cancel.add(item_id)          # the worker stops after the current sentence
    if not building:
        store.update_item(item_id, {"audio_status": _idle_status(store.get_item(item_id))})


def discard(item_id):
    """Throw away an unfinished audiobook."""
    cancel(item_id)
    it = store.get_item(item_id)
    if it:
        shutil.rmtree(_work_dir(it), ignore_errors=True)
        try:   # don't leave an empty author folder behind
            os.rmdir(os.path.dirname(_work_dir(it)))
        except OSError:
            pass
        store.update_item(item_id, {"audio_status": _idle_status(it)})


def _worker():
    try:
        while True:
            with _lock:
                if not QUEUE:
                    STATE.update(running=False, item=None, title="", chapter="", done=0, total=0)
                    return
                job = QUEUE.pop(0)
            try:
                build(job["item"], job["voice"], job["speed"])
            except Exception as e:
                traceback.print_exc()
                STATE["error"] = str(e)
                it = store.get_item(job["item"])
                store.update_item(job["item"], {"audio_status": "partial" if it and resume_info(it) else "error"})
                _log(f"Couldn't make the audiobook: {e}", "error")
            finally:
                _cancel.discard(job["item"])
    finally:
        STATE.update(running=False, item=None)


def build(item_id, voice_id, speed=1.0):
    item = store.get_item(item_id)
    raw = store.get_item(item_id, raw=True)
    path = store.resolve_file(raw.get("file_path"))
    if not path or not os.path.exists(path):
        raise ValueError("The book's file can't be found.")
    STATE.update(item=item_id, title=item.get("title") or "", chapter="Reading the book…", done=0, total=0, message="", error="")
    store.update_item(item_id, {"audio_status": "building"})
    if not deps_ok() or not voice_installed(voice_id):
        STATE["chapter"] = "Setting up the voice…"
        if not setup(voice_id):
            raise RuntimeError(STATE.get("error") or "Voice set-up failed")
    from piper import PiperVoice
    try:
        from piper import SynthesisConfig
    except ImportError:
        SynthesisConfig = None
    import lameenc
    chapters = chapters_for(path)
    if not chapters:
        raise ValueError("No readable text was found in this book (it may be scanned images).")
    total_sents = sum(len(c["sentences"]) for c in chapters)
    STATE["total"] = total_sents
    voice = PiperVoice.load(voice_path(voice_id))
    cfg = SynthesisConfig(length_scale=1.0 / max(0.5, min(2.0, float(speed or 1.0)))) if SynthesisConfig else None

    final_dir = folder_for(item)
    work = final_dir + ".building"
    prog = load_progress(item)
    if not (prog and prog.get("voice") == voice_id and float(prog.get("speed") or 1) == float(speed or 1)
            and prog.get("total_chapters") == len(chapters) and prog.get("total_sentences") == total_sents):
        shutil.rmtree(work, ignore_errors=True)        # different voice/speed or a changed book: start again
        prog = None
    os.makedirs(work, exist_ok=True)
    prog = prog or {"voice": voice_id, "speed": speed, "total_chapters": len(chapters), "total_sentences": total_sents, "chapters": [], "sentences_done": 0}
    out_chapters = list(prog["chapters"])
    STATE["done"] = sum(len(c["sentences"]) for c in chapters[:len(out_chapters)])
    if out_chapters:
        _log(f"Carrying on with the audiobook of “{item.get('title')}” from chapter {len(out_chapters) + 1}.")
    _save_progress(item, prog)
    gap = None
    for ci, ch in enumerate(chapters):
        if ci < len(out_chapters):
            continue
        if item_id in _cancel:
            break
        STATE["chapter"] = f"Chapter {ci + 1} of {len(chapters)}: {ch['title']}"
        enc = None
        rate = None
        t = 0.0
        timing = []
        fname = f"{ci + 1:02d} - {_safe(ch['title'], 'Chapter')}.mp3"
        with open(os.path.join(work, fname), "wb") as f:
            for si, s in enumerate(ch["sentences"]):
                if item_id in _cancel:
                    break
                pcm = b""
                try:
                    try:
                        gen = voice.synthesize(speakable(s["text"]), syn_config=cfg) if cfg is not None else voice.synthesize(speakable(s["text"]))
                        for c in gen:
                            rate = rate or c.sample_rate
                            pcm += c.audio_int16_bytes
                    except TypeError:  # older piper-tts
                        rate = rate or voice.config.sample_rate
                        for b in voice.synthesize_stream_raw(speakable(s["text"])):
                            pcm += b
                except Exception as e:      # one odd sentence mustn't stop the whole book
                    print("[babel] skipped a sentence the voice couldn't read:", e)
                    pcm = b""
                    rate = rate or getattr(getattr(voice, "config", None), "sample_rate", 22050)
                if enc is None:
                    enc = lameenc.Encoder()
                    enc.set_bit_rate(64)
                    enc.set_in_sample_rate(rate)
                    enc.set_channels(1)
                    enc.set_quality(2)
                    gap = b"\x00\x00" * int(rate * 0.28)
                dur = len(pcm) / 2 / rate
                timing.append({**s, "t0": round(t, 3), "t1": round(t + dur, 3)})
                t += dur + 0.28
                f.write(enc.encode(pcm + gap))
                STATE["done"] += 1
            if enc is not None:
                f.write(enc.flush())
        if item_id in _cancel:
            break                                   # this chapter is incomplete: it's made again on resume
        out_chapters.append({"title": ch["title"], "file": fname, "duration": round(t, 2),
                             "href": ch.get("href"), "page": ch.get("page"), "sentences": timing})
        prog["chapters"] = out_chapters
        prog["sentences_done"] = STATE["done"]
        _save_progress(item, prog)
    if item_id in _cancel:
        _cancel.discard(item_id)
        store.update_item(item_id, {"audio_status": _idle_status(item)})
        _log(f"Paused the audiobook of “{item.get('title')}” after {len(out_chapters)} of {len(chapters)} chapters. It carries on from there next time.")
        return
    manifest = {"item": item_id, "title": item.get("title"), "authors": item.get("authors") or [], "voice": voice_id,
                "speed": speed, "created": time.time(), "kind": os.path.splitext(path)[1].lower().lstrip("."),
                "chapters": out_chapters}
    with open(os.path.join(work, "audiobook.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False)
    try:
        os.remove(os.path.join(work, "progress.json"))
    except OSError:
        pass
    old = audio_dir(item)
    if old and os.path.isdir(old) and os.path.abspath(old) != os.path.abspath(final_dir):
        shutil.rmtree(old, ignore_errors=True)
    shutil.rmtree(final_dir, ignore_errors=True)
    os.replace(work, final_dir)
    hours = sum(c["duration"] for c in out_chapters) / 3600
    store.update_item(item_id, {"audio_dir": store.path_to_db(final_dir), "audio_status": "ready", "audio_pos": json.dumps({"ch": 0, "t": 0})})
    _log(f"Audiobook ready: “{item.get('title')}” ({len(out_chapters)} chapters, {hours:.1f} h)")


def delete(item_id):
    item = store.get_item(item_id)
    if item:
        shutil.rmtree(_work_dir(item), ignore_errors=True)
    d = audio_dir(item) if item else None
    if d and os.path.isdir(d):
        shutil.rmtree(d, ignore_errors=True)
        parent = os.path.dirname(d)
        try:
            if not os.listdir(parent):
                os.rmdir(parent)
        except OSError:
            pass
    store.update_item(item_id, {"audio_dir": None, "audio_status": None, "audio_pos": None})
