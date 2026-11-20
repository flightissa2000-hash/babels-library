"""Notes, highlights, bookmarks and reading places in a reading copy point at spots in its text (EPUB CFIs, as epub.js
writes them). When the copy is made again the text is laid out differently, so those spots are found again by their
words: the text at each old spot is read from the old file, looked for in the new one, and a new CFI is written there."""
import re
import zipfile
import posixpath
import xml.etree.ElementTree as ET

XHTML = "{http://www.w3.org/1999/xhtml}"


class Book:
    """An EPUB's spine as parsed pages, each with its body text flattened (and where each text node sits in it)."""

    def __init__(self, path):
        self.pages = []                                   # [{href, body, nodes:[(el, slot, start, text)], text}]
        with zipfile.ZipFile(path) as z:
            cont = z.read("META-INF/container.xml").decode("utf-8", "replace")
            opf_path = re.search(r'full-path="([^"]+)"', cont).group(1)
            opf = z.read(opf_path).decode("utf-8", "replace")
            base = posixpath.dirname(opf_path)
            items = {m.group(1): m.group(2) for m in re.finditer(r'<item\b[^>]*?\bid="([^"]+)"[^>]*?\bhref="([^"]+)"', opf)}
            items.update({m.group(2): m.group(1) for m in re.finditer(r'<item\b[^>]*?\bhref="([^"]+)"[^>]*?\bid="([^"]+)"', opf)})
            spine = re.search(r"<spine\b.*?</spine>", opf, re.S).group(0)
            for idref in re.findall(r'<itemref\b[^>]*?\bidref="([^"]+)"', spine):
                href = items.get(idref, "")
                page = {"href": href, "body": None, "nodes": [], "text": "", "at": {}}
                try:
                    root = ET.fromstring(z.read(posixpath.join(base, href) if base else href))
                    page["body"] = root.find(XHTML + "body")
                except Exception:
                    pass
                if page["body"] is not None:
                    self._flatten(page)
                self.pages.append(page)

    @staticmethod
    def _flatten(page):
        parts, pos = [], 0

        def walk(el):
            nonlocal pos
            page["at"][id(el)] = pos
            if el.text:
                page["nodes"].append((el, -1, pos, el.text))
                parts.append(el.text)
                pos += len(el.text)
            for i, ch in enumerate(list(el)):
                walk(ch)
                if ch.tail:
                    page["nodes"].append((el, i, pos, ch.tail))
                    parts.append(ch.tail)
                    pos += len(ch.tail)
        walk(page["body"])
        page["text"] = "".join(parts)

    # ---- CFI → (page index, offset in that page's text)
    def locate(self, cfi):
        m = re.match(r"^epubcfi\((.*)\)$", (cfi or "").strip())
        if not m:
            return None
        inner = re.sub(r"\[[^\]]*\]", "", m.group(1))
        if "," in inner:                                  # a range: where it starts
            parent, start = inner.split(",")[:2]
            inner = parent + start
        if "!" not in inner:
            return None
        pkg, rest = inner.split("!", 1)
        steps = [s for s in pkg.split("/") if s]
        if len(steps) < 2:
            return None
        pi = int(steps[1]) // 2 - 1
        if not (0 <= pi < len(self.pages)) or self.pages[pi]["body"] is None:
            return None
        page = self.pages[pi]
        off = 0
        if ":" in rest:
            rest, o = rest.rsplit(":", 1)
            off = int(re.match(r"\d*", o).group(0) or 0)
        steps = [int(s) for s in rest.split("/") if s]
        if not steps or steps[0] != 4:                    # /4 is the body
            return pi, 0
        el = page["body"]
        for k, s in enumerate(steps[1:]):
            kids = list(el)
            if s % 2 == 0:
                if not (0 < s // 2 <= len(kids)):
                    return pi, self._start_of(page, el)
                el = kids[s // 2 - 1]
            else:                                         # a text node: the (s-1)/2-th one among el's own text nodes
                own = [n for n in page["nodes"] if n[0] is el]
                t = (s - 1) // 2
                if t < len(own):
                    return pi, own[t][2] + min(off, len(own[t][3]))
                return pi, self._start_of(page, el)
        return pi, self._start_of(page, el)

    @staticmethod
    def _start_of(page, el):
        return page["at"].get(id(el), 0)

    # ---- (page index, offset) → CFI
    def cfi_at(self, pi, off, end=None):
        page = self.pages[pi]
        head = f"/6/{(pi + 1) * 2}!/4"

        def point(o):
            if not page["nodes"]:
                return ""
            node = next((n for n in page["nodes"] if n[2] <= o < n[2] + len(n[3])), page["nodes"][-1])
            el, slot, start, text = node
            path = []
            x = el
            parents = {c: p for p in page["body"].iter() for c in p}
            while x is not page["body"]:
                p = parents[x]
                path.append((list(p).index(x) + 1) * 2)
                x = p
            own = [n for n in page["nodes"] if n[0] is el]
            t = next(i for i, n in enumerate(own) if n is node)
            return "".join(f"/{s}" for s in reversed(path)) + f"/{t * 2 + 1}:{max(0, min(o - start, len(text)))}"
        if end is None:
            return f"epubcfi({head}{point(off)})"
        return f"epubcfi({head},{point(off)},{point(end)})"


def _norm(s):
    """Lower case, spaces collapsed, with a map from each kept character back to where it was."""
    out, where = [], []
    space = True
    for i, ch in enumerate(s):
        if ch.isspace() or ch in "­​‌‍⁠﻿":
            if not space:
                out.append(" ")
                where.append(i)
            space = True
            continue
        out.append(ch.lower())
        where.append(i)
        space = False
    return "".join(out), where


class Mover:
    def __init__(self, old_path, new_path):
        self.old, self.new = Book(old_path), Book(new_path)
        self.norm = [_norm(p["text"]) for p in self.new.pages]

    def _find(self, want, before, prefer, frac):
        """Where in the new book `want` starts (trying shorter pieces of it, and the text before the spot)."""
        cands = []
        for size in (60, 40, 28, 18, 12):
            w = _norm(want[:size * 2])[0].strip()[:size]
            if len(w) < min(size, 10):
                continue
            for pi, (t, where) in enumerate(self.norm):
                for m in re.finditer(re.escape(w), t):
                    cands.append((pi, where[m.start()], 0))
            if cands:
                break
        if not cands:
            for size in (40, 24, 14):
                b = _norm(before[-size * 2:])[0].strip()[-size:]
                if len(b) < 10:
                    continue
                for pi, (t, where) in enumerate(self.norm):
                    for m in re.finditer(re.escape(b), t):
                        e = m.end() - 1
                        cands.append((pi, where[e] + 1 if e < len(where) else len(self.new.pages[pi]["text"]), 1))
                if cands:
                    break
        if not cands:
            return None
        bn = _norm(before[-30:])[0].strip()

        def score(c):
            pi, at, _ = c
            t = _norm(self.new.pages[pi]["text"][max(0, at - 80):at])[0].strip()
            ctx = sum(1 for a, b in zip(reversed(bn), reversed(t)) if a == b)
            same = self.new.pages[pi]["href"] == prefer
            near = abs(pi / max(len(self.new.pages), 1) - frac)
            return (-ctx, not same, near)
        return min(cands, key=score)[:2]

    def move(self, cfi, quote=""):
        """The CFI's spot in the new book, or None when it can't be found."""
        if not cfi:
            return None
        rng = "," in cfi
        loc = self.old.locate(cfi)
        if loc is None:
            return None
        pi, off = loc
        page = self.old.pages[pi]
        text = page["text"]
        length = None
        if rng:
            m = re.match(r"^epubcfi\((.*)\)$", cfi.strip())
            parent, a, b = re.sub(r"\[[^\]]*\]", "", m.group(1)).split(",")[:3]
            e = self.old.locate(f"epubcfi({parent}{b})")
            if e and e[0] == pi and e[1] > off:
                length = e[1] - off
        want = text[off:off + max(length or 0, 80)] if not quote else quote
        if quote and len(_norm(quote)[0].strip()) < 10:
            want = text[off:off + 80]
        frac = pi / max(len(self.old.pages), 1)
        hit = self._find(want, text[max(0, off - 120):off], page["href"], frac)
        if hit is None and not text[off:].strip():        # the spot is at the end of a page: the next page's start
            hit = self._find(self.old.pages[pi + 1]["text"][:80] if pi + 1 < len(self.old.pages) else "", text[max(0, off - 120):off], page["href"], frac)
        if hit is None:
            same = next((i for i, p in enumerate(self.new.pages) if p["href"] == page["href"]), None)
            if same is None:
                return None
            return self.new.cfi_at(same, 0)
        npi, at = hit
        if length:
            end = min(at + length, len(self.new.pages[npi]["text"]))
            if quote:                                     # the highlight's words, as many of them as were found
                qn = _norm(quote)[0].strip()
                tn, where = _norm(self.new.pages[npi]["text"][at:at + len(quote) * 2 + 20])
                k = len(qn) if tn.startswith(qn) else 0
                if k:
                    end = at + where[k - 1] + 1
            return self.new.cfi_at(npi, at, end)
        return self.new.cfi_at(npi, at)
