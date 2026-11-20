"""Reading copies: any paper PDF → an EPUB that reflows on a small screen.

The layout is worked out page by page (columns, running heads, captions, equations), so nothing is specific to a journal.
Figures and tables go at the end, each on its own page, linked from where they're mentioned and listed in the contents.
Whatever can't be trusted as text (fractions, odd math fonts) is cut from the page as a picture, and every equation can
be tapped to see it full size. A scan, or a PDF whose text can't be read, becomes trimmed page pictures, column by column.
The PDF itself is only read.
"""
import html
import os
import re
import statistics
import unicodedata
import uuid
import zipfile
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor_py"))
if os.name != "nt":
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor_py", "linux"))
import pymupdf  # noqa: E402

pymupdf.TOOLS.mupdf_display_errors(False)
EQ_SCALE = 1.4          # equations against the text, when a reader can't change it (Babel's readers can)
MATH_FONT = re.compile(r"CMMI|CMSY|CMEX|CMBSY|MSAM|MSBM|EUFM|EURM|LMMath|Math|MTMI|MTSY|MTEX|MT2|Mathematica|Symbol|STIX|Euclid|Asana|TeXGyre.*Math|Cambria.?M|Txsy|Pxsy|rsfs|Universal.?Greek", re.I)
MATH_CHARS = set("=≈≠≤≥±∓×÷∑∏∫∂∇√∞∝∈∉⊂⊃∪∩→←↔⇌⇒⟶")
GREEK = set("αβγδεζηθικλμνξοπρστυφχψωΓΔΘΛΞΠΣΥΦΨΩ")
SYMBOL_PUA = dict(zip(range(0xF061, 0xF07A), "αβχδεφγηιϕκλμνοπθρστυϖωξψ"))
SYMBOL_PUA.update({0xF8E7: "", 0xF8E6: "", 0xF8E5: "", 0xF8EB: "", 0xF8F6: "", 0xF8EF: "", 0xF8FA: "", 0xF0B4: "×", 0xF0B0: "°", 0xF0B1: "±", 0xF0B3: "≥", 0xF0A3: "≤", 0xF0B5: "∝", 0xF0B6: "∂", 0xF0B7: "•", 0xF0B8: "÷", 0xF0B9: "≠", 0xF0BA: "≡", 0xF0BB: "≈",
                   0xF0AE: "→", 0xF0AC: "←", 0xF0AB: "↔", 0xF02D: "−", 0xF02B: "+", 0xF03D: "=", 0xF03C: "<", 0xF03E: ">", 0xF028: "(", 0xF029: ")", 0xF02C: ",", 0xF02E: ".",
                   0xF044: "Δ", 0xF046: "Φ", 0xF047: "Γ", 0xF04C: "Λ", 0xF050: "Π", 0xF051: "Θ", 0xF053: "Σ", 0xF057: "Ω", 0xF058: "Ξ", 0xF059: "Ψ", 0xF0D7: "·", 0xF0A5: "∞", 0xF0CE: "∈", 0xF0D6: "√"})
CAP = re.compile(r"^\s*(Fig(?:ure|s)?\.?|FIG(?:URE)?\.?|Scheme|SCHEME|Chart|CHART|Table|TABLE|Tab\.|Extended Data Fig(?:ure)?\.?|Supplementary (?:Figure|Fig\.?|Table)|Box|Plate)\s*(S?\d+(?:[.\-]\d+)*(?:[A-Za-z](?![a-z]))?|[IVXL]+(?![a-z]))\s*(\(continued\)|\(cont(?:'d|\.)?\)|continued)?\s*(.?)", re.I)
KNOWN = r"abstract|summary|introduction|background|results?(?: and discussions?)?|discussions?|conclusions?(?: and outlook| and perspectives?)?|summary and outlook|outlook|perspectives?|(?:materials and |experimental |computational )?methods?|materials|experimental(?: section| details| procedures?)?|acknowledge?ments?|references(?: and (?:notes|footnotes))?|notes and references|bibliography|works cited|literature cited|supporting information|supplementary (?:information|materials?)|data availability|code availability|author contributions?|competing interests?|conflicts? of interests?|funding|appendix(?: [a-z0-9]+)?"
HEAD_KNOWN = re.compile(rf"^(?:(?:\d+(?:\.\d+)*|[IVXL]+|[A-Z])[.)]?\s+)?(?:{KNOWN})\s*[.:]?$", re.I)
RUN_IN = re.compile(rf"^((?:{KNOWN}))\s*[:.]\s*(?=\S)", re.I)
FURNITURE = re.compile(r"^(check for updates|read online|cite this:.*|metrics (?:&|and) more|article recommendations|supporting information|access|open access|downloaded (?:from|via).*)$", re.I)
REF_HEAD = re.compile(r"references(?: and (?:notes|footnotes))?|bibliography|works cited|literature cited|notes and references", re.I)
ELEMENTS = set("H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co Ni Cu Zn Ga Ge As Se Br Kr Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Te I Xe Cs Ba La Ce Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Hf Ta W Re Os Ir Pt Au Hg Tl Pb Bi Po At Rn Fr Ra Ac Th Pa U Np Pu Am Cm X M".split())
UNIT_TAIL = re.compile(r"(?:^|[^A-Za-z])(?:m|cm|mm|nm|μm|µm|km|Å|s|g|kg|mg|K|L|mL|mol|A|V|W|Hz|eV|N|J|Pa|T)$")


# ---------------- reading a page
def clean(t):
    t = "".join(PRIVATE.get(ord(c)) or SYMBOL_PUA.get(ord(c), c) for c in t)
    t = unicodedata.normalize("NFKC", re.sub("[­​‌‍⁠﻿]", "", t))     # (soft hyphens and zero-width spaces)
    t = "".join(c for c in t if (ord(c) >= 32 or c in "\t\n\r") and not 127 <= ord(c) <= 159 and c not in ("\ufffe", "\uffff"))     # (not allowed in an EPUB's files)
    return re.sub(r"\s+([̀-ͯ])", r"\1", t)


SYMBOL_FONTS = set()


def is_math_font(f):
    return bool(MATH_FONT.search(f)) or f in SYMBOL_FONTS


def drawn_letters(sp):
    """A publisher's own little symbol font (PBB, Optr): its letters are shapes (A is a big bracket), not letters."""
    name = sp["font"].split("+")[-1]
    # (its letters, if the font's name is a short private one; its punctuation, whatever its name: "@" may be drawn "=")
    return sp["font"] in SYMBOL_FONTS and not MATH_FONT.search(name) and (len(name) <= 5 and re.search(r"[A-Za-z]", sp["text"]) or re.search(r"[!-/:-@\[-`{-~]", sp["text"]))


def learn_symbol_fonts(pages):
    spans, wordy = Counter(), Counter()
    for p in pages:
        for r in p["rows"]:
            for sp in r["spans"]:
                t = sp["text"].strip()
                if t:
                    spans[sp["font"]] += 1
                    if re.search(r"[^\W\d_]{3,}", t) or re.fullmatch(r"[\d\s.,;:()\[\]\-–]+", t) and re.search(r"\d{2}", t) or any(0xE000 <= ord(c) <= 0xF8FF or 0xFB00 <= ord(c) <= 0xFB06 for c in t):
                        wordy[sp["font"]] += 1      # (words, or a font of ligatures: text either way)
    SYMBOL_FONTS.clear()
    SYMBOL_FONTS.update(f for f, n in spans.items() if n >= 8 and not wordy[f] and not re.search(r"Times|Roman|Serif|Sans|Arial|Helvet|Caslon|Minion|Garamond|Palat|Book|Text", f, re.I))


def is_math(s):
    return is_math_font(s["font"]) and not re.search(r"[A-Za-z]{4,}", s["text"]) and s["text"].strip() not in ("“", "”", "‘", "’", "\"", "'")


def is_bold(s):
    return bool(s["flags"] & 16) or bool(re.search(r"Bold|Black|Heavy|Semibold|[-,+]B[dX]?\b|CMBX|Demi", s["font"]))


def is_italic(s):
    return bool(s["flags"] & 2) or bool(re.search(r"Ital|Obli|CMTI|CMMI", s["font"]))


LIGATURE_STEMS = """field first figur specific signific efficien coeffici effect differ flow fluor reflect flexib difficult sufficien affect offer profile final find fine film confirm modif defin conflict influen fluid flame identif classif simplif amplif purif fiber fibre filter fill flat flux flash floor shift staff suffer diffus diffract after left soft craft draft often benefit scientif notif verif justif rectif interface fixed fit five fig office offset cliff stiff""".split()
LIGATURES = ["fi", "fl", "ff", "ffi", "ffl", "ft", "fj", "tt", "st", "ct"]
PRIVATE = {}


def learn_ligatures(pages):
    """A font's private characters that make real words as fi, fl, ff...: they're those."""
    votes = {}
    for p in pages:
        for r in p["rows"]:
            for s in r["spans"]:
                if is_math(s) or not any(0xE000 <= ord(c) <= 0xF8FF for c in s["text"]):
                    continue
                for word in re.findall(r"[^\W\d_]*[\ue000-\uf8ff][^\W\d_\ue000-\uf8ff]*", s["text"]):
                    for c in set(re.findall(r"[\ue000-\uf8ff]", word)):
                        for lig in LIGATURES:
                            trial = re.sub(r"[\ue000-\uf8ff]", lig if True else "", word).lower()
                            if any(stem in trial for stem in LIGATURE_STEMS):
                                votes.setdefault(c, {}).setdefault(lig, 0)
                                votes[c][lig] += 1
    for c, v in votes.items():
        best = sorted(v.items(), key=lambda kv: -kv[1])
        if best[0][1] >= 2 and (len(best) == 1 or best[0][1] >= 1.5 * best[1][1]):
            PRIVATE[ord(c)] = best[0][0]


def learn_old_math(pages):
    """ð1Þ is (1) and ¼ is = in a family of old math fonts."""
    n = Counter()
    for p in pages:
        for r in p["rows"]:
            n.update(c for s in r["spans"] for c in s["text"] if c in "ðÞ¼þÀ")
    if n["ð"] >= 2 and n["Þ"] >= 2:
        PRIVATE.update({ord("ð"): "(", ord("Þ"): ")", ord("¼"): "=", ord("þ"): "+", ord("À"): "−", ord("Â"): "·", ord("Ã"): "*", ord("Ä"): "×"})


def learn_shapes(doc, pages):
    """Private characters that are plainly a minus (one thin bar at mid-height) or an equals sign (two): read as
    those rather than drawn as pictures."""
    seen = {}
    for p in pages:
        for r in p["rows"]:
            for sp in r["spans"]:
                for c in sp["chars"]:
                    if 0xE000 <= ord(c["c"]) <= 0xF8FF and ord(c["c"]) not in PRIVATE and (sp["font"], c["c"]) not in seen:
                        seen[(sp["font"], c["c"])] = (p["n"], c, sp["size"])
    k = 12
    for (font, ch), (page, c, size) in seen.items():
        base = c["origin"][1]
        box = pymupdf.Rect(c["bbox"][0], base - size, c["bbox"][2], base + .3 * size) & doc[page].rect
        if box.is_empty or box.width < .5:
            continue
        pm = doc[page].get_pixmap(matrix=pymupdf.Matrix(k, k), clip=box, colorspace=pymupdf.csGRAY, alpha=False)
        buf = bytes(pm.samples)
        rows = [y for y in range(pm.height) if min(buf[y * pm.stride:y * pm.stride + pm.width]) < 128]
        if not rows:
            continue
        cols = [x for x in range(pm.width) if any(buf[y * pm.stride + x] < 128 for y in rows)]
        bands = 1 + sum(1 for a, b in zip(rows, rows[1:]) if b - a > 1)
        h, w = (rows[-1] - rows[0] + 1) / k, (cols[-1] - cols[0] + 1) / k
        mid = base - (box.y0 + (rows[0] + rows[-1]) / 2 / k)
        filled = sum(1 for y in rows for x in range(cols[0], cols[-1] + 1) if buf[y * pm.stride + x] < 128) / max(len(rows) * len(cols), 1)
        if w < .3 * size or not (.1 * size < mid < .45 * size) or filled < .7:
            continue
        if bands == 1 and h < .12 * size:
            PRIVATE[ord(ch)] = "−"
        elif bands == 2 and h < .45 * size:
            PRIVATE[ord(ch)] = "="


def bad_text(t):
    return any(0xE000 <= ord(c) <= 0xF8FF or c == "�" for c in t)


def tight(spans):
    ink = [s for s in spans if s["text"].strip()]
    if not ink:
        return None
    return (min(s["origin"][1] - .72 * s["size"] for s in ink), max(s["origin"][1] + .2 * s["size"] for s in ink))


FONT_CODES = {"Universal-GreekwithMath": {"@": "[", "#": "]"}}


def spaced(s):
    """A span's characters: decorations out (their boxes are huge and join lines up), and a space wherever there's a gap."""
    out = []
    for c in s["chars"]:
        if c["c"] in "■□▪▫●◆◼":
            continue
        fix = next((m for f, m in FONT_CODES.items() if f in s["font"]), None)       # (fonts that store a symbol under another code)
        if fix and c["c"] in fix:
            c = dict(c, c=fix[c["c"]])
        if out and c["c"] != " " and out[-1]["c"] not in " ([{/" and c["origin"][0] - out[-1]["bbox"][2] > .11 * s["size"]:      # (tightly justified lines leave a word gap of barely an eighth of the type size)
            x = out[-1]["bbox"][2]
            out.append({"c": " ", "origin": (x, c["origin"][1]), "bbox": (x, c["bbox"][1], c["bbox"][0], c["bbox"][3])})
        out.append(c)
    return out


def collides(l, r, body):
    """Words over words: not one line. Small math stacked up (a fraction) is the exception."""
    small = lambda q: is_math(q) or q["size"] < body - .5 or q["size"] > body + 1
    for a in l["spans"]:
        for b in r["spans"]:
            if a["text"].strip() and b["text"].strip() and abs(a["origin"][1] - b["origin"][1]) > 1.5 and min(a["bbox"][2], b["bbox"][2]) - max(a["bbox"][0], b["bbox"][0]) > 1 and not (small(a) and small(b)):
                return True
    return False


def read_rows(page, body_guess=10.0):
    flags = pymupdf.TEXTFLAGS_RAWDICT & ~pymupdf.TEXT_PRESERVE_IMAGES
    lines, sideways = [], []
    for b in page_blocks(page, flags):
        for l in b.get("lines", []):
            spans = []
            for s in l["spans"]:
                s["chars"] = spaced(s)
                s["text"] = "".join(c["c"] for c in s["chars"])
                if s["text"]:
                    s["bbox"] = (s["chars"][0]["bbox"][0], s["bbox"][1], s["chars"][-1]["bbox"][2], s["bbox"][3])
                    spans.append(s)
            ink = [s for s in spans if s["text"].strip()]
            if not ink:
                continue
            box = (min(s["bbox"][0] for s in ink), min(s["bbox"][1] for s in ink), max(s["bbox"][2] for s in ink), max(s["bbox"][3] for s in ink))
            (lines if abs(l["dir"][1]) < .05 and l["dir"][0] > 0 else sideways).append({"spans": spans, "box": box, "dir": l["dir"]})
    rows = []
    for l in sorted(lines, key=lambda q: (q["box"][1], q["box"][0])):
        x0, y0, x1, y1 = l["box"]
        t0, t1 = tight(l["spans"]) or (y0, y1)
        for r in reversed(rows[-8:]):
            r0, r1 = tight(r["spans"]) or (r["y0"], r["y1"])
            ov = min(t1, r1) - max(t0, r0)
            if collides(l, r, body_guess):
                continue
            if ov > .35 * min(t1 - t0, r1 - r0) and x0 - r["x1"] < .7 * min(l["spans"][0]["size"], r["spans"][0]["size"], body_guess) and r["x0"] - x1 < .7 * min(l["spans"][0]["size"], r["spans"][0]["size"], body_guess):
                r["spans"] += l["spans"]
                r["x0"], r["y0"], r["x1"], r["y1"] = min(x0, r["x0"]), min(y0, r["y0"]), max(x1, r["x1"]), max(y1, r["y1"])
                break
        else:
            rows.append({"spans": list(l["spans"]), "x0": x0, "y0": y0, "x1": x1, "y1": y1, "page": page.number})
    for r in rows:
        finish_row(r)
    rows[:] = [r for r in rows if r["chars"]]
    for r in [q for q in rows if q["chars"] <= 3 and (q["math"] > .5 or all(unicodedata.combining(c) or c in "√∼~¯ˉ‾ˆ˜·−" for c in q["text"].replace(" ", "")))]:
        size = r["size"]
        near = [q for q in rows if q is not r and q["chars"] > 3 and r["x0"] >= q["x0"] - size and r["x1"] <= q["x1"] + size and r["y1"] >= q["y0"] - .2 * size and r["y0"] <= q["y1"] + .2 * size]
        # (only the line its foot stands in: a big Σ or a limit above or below a line belongs to an equation, not to that line)
        near = [q for q in near if (lambda t: t[0] - .1 * q["size"] <= r["y1"] <= t[1] + .35 * q["size"])(tight(q["spans"]) or (q["y0"], q["y1"]))]
        if near:
            foot = (r["y1"] - .3 * size, r["y1"] + .6 * size)
            q = max(near, key=lambda q: min(foot[1], q["y1"]) - max(foot[0], q["y0"]))
            q["spans"] += r["spans"]
            q["x0"], q["x1"], q["y0"], q["y1"] = min(q["x0"], r["x0"]), max(q["x1"], r["x1"]), min(q["y0"], r["y0"]), max(q["y1"], r["y1"])
            finish_row(q)
            rows.remove(r)
    join_touching(rows)
    for r in [q for q in rows if re.fullmatch(r"[\[(]?\d{1,4}[.)\]]?", q["text"]) or q["text"] in ("•", "▪", "■", "●") or re.fullmatch(r"(?:Fig(?:ure)?\.?|FIG(?:URE)?\.?|Table|TABLE|Scheme|SCHEME)\s*S?\d+(?:[.\-]\d+)*[.:]?", q["text"])]:
        if r["text"].startswith("(") and any(q["x1"] <= r["x0"] and min(q["y1"], r["y1"]) - max(q["y0"], r["y0"]) > 0 for q in rows):
            continue
        beside = [q for q in rows if q is not r and q["x0"] > r["x1"] and q["x0"] - r["x1"] < 3.2 * max(body_guess, r["size"]) and min(q["y1"], r["y1"]) - max(q["y0"], r["y0"]) > .35 * min(q["y1"] - q["y0"], r["y1"] - r["y0"])]
        if beside:
            q = min(beside, key=lambda c: c["x0"])
            q["spans"] = r["spans"] + q["spans"]
            q["x0"], q["y0"], q["y1"] = r["x0"], min(q["y0"], r["y0"]), max(q["y1"], r["y1"])
            finish_row(q)
            rows.remove(r)
    inline_fractions(page, rows)
    return rows, sideways


BAR_GLYPHS = set("_‒–—―−─━")


def inline_fractions(page, rows):
    """A small fraction set inside a line of text (tan⁻¹(σ_AHE / σ_xx)): its top, its bar and its bottom are stored as
    pieces of different lines. Written as text, a/b, it reads and reflows like the rest of the line."""
    bars = []
    for r in rows:
        for sp in r["spans"]:
            t = sp["text"].strip()
            if t and set(t) <= BAR_GLYPHS and sp["bbox"][2] - sp["bbox"][0] < 90:
                bars.append((sp["bbox"][0], sp["bbox"][2], sp["origin"][1] - .02 * sp["size"], sp, r))
    for d in page.get_drawings():
        b = d["rect"]
        if b.height < 1.3 and 3 < b.width < 90:
            bars.append((b.x0, b.x1, (b.y0 + b.y1) / 2, None, None))
    for x0, x1, y, bar_sp, bar_row in bars:
        # the line the fraction sits in: ordinary-size text just left or right of the bar, its baseline a little below
        host = None
        for r in rows:
            if r is bar_row and len([s for s in r["spans"] if s["text"].strip()]) == 1:
                continue
            big = [s for s in r["spans"] if s["text"].strip() and s["size"] >= r["size"] - .5 and not s.get("frac")]
            if big and len(re.findall(r"[A-Za-z]{3,}", r["text"])) >= 2 and r["chars"] >= 12 and 0 <= r["base"] - y <= .75 * r["size"] and any(s["bbox"][2] <= x0 + 2 and x0 - s["bbox"][2] < 2.5 * r["size"] for s in big):
                host = r
                break
        if host is None:
            continue
        size = host["size"]
        near = [(r, s) for r in rows for s in r["spans"] if s is not bar_sp and s["text"].strip() and not s.get("frac") and s["size"] < size - .8
                and x0 - 1 <= (s["bbox"][0] + s["bbox"][2]) / 2 <= x1 + 1 and abs((s["origin"][1] - .3 * s["size"]) - y) < 1.3 * size]
        top = [(r, s) for r, s in near if s["origin"][1] - .3 * s["size"] < y]
        bot = [(r, s) for r, s in near if s["origin"][1] - .3 * s["size"] >= y]
        if not top or not bot:
            continue
        pieces = []
        for part in (top, bot):
            spans = sorted((s for _, s in part), key=lambda s: s["origin"][0])
            main = max(spans, key=lambda s: (s["size"], len(s["text"].strip())))
            for s in spans:
                if s is main or s["size"] >= main["size"] - .3:
                    s["forced"] = ""
                else:
                    s["forced"] = "sub" if s["origin"][1] - .3 * s["size"] > main["origin"][1] - .3 * main["size"] else "sup"
                s["size"] = size if s["forced"] == "" else size * .7
            for s in spans:                       # (no gaps inside a fraction's top or bottom)
                s["chars"] = [c for c in s["chars"] if not c["c"].isspace() and c["c"] not in "​   "]
                s["text"] = "".join(c["c"] for c in s["chars"])
            spans = [s for s in spans if s["text"]]
            text = "".join(clean(s["text"]) for s in spans).strip()
            group = bool(re.search(r"[+\-−=±×·]", text))
            pieces.append((spans, group))
        # out of the lines they were in
        for r, s in near:
            r["spans"] = [q for q in r["spans"] if q is not s]
        if bar_sp is not None:
            bar_row["spans"] = [q for q in bar_row["spans"] if q is not bar_sp]
        # into the host line, in order: (top) / (bottom)
        new, k = [], 0
        def put(text, like):
            nonlocal k
            k += 1
            c = {"c": text, "origin": (x0 + .001 * k, host["base"]), "bbox": (x0, host["y0"], x0 + .01, host["y1"])}
            new.append(dict(like, text=text, chars=[c], origin=c["origin"], bbox=c["bbox"], size=size, forced="", frac=True, font=like["font"]))
        for n, (spans, group) in enumerate(pieces):
            if n:
                put("/", spans[0])
            if group:
                put("(", spans[0])
            for s in spans:
                k += 1
                shift = host["base"] - s["origin"][1] + (0 if s["forced"] == "" else (1 if s["forced"] == "sub" else -3))
                s["chars"] = [dict(c, origin=(x0 + .001 * k, c["origin"][1] + shift)) for c in s["chars"]]
                s["origin"] = (x0 + .001 * k, host["base"] + (0 if s["forced"] == "" else (2 if s["forced"] == "sub" else -3)))
                s["bbox"] = (x0, host["y0"], x0 + .01, host["y1"])
                s["frac"] = True
                new.append(s)
            if group:
                put(")", spans[-1])
        host["spans"] += new
        host["x1"] = max(host["x1"], x1)
        # the rest of the line, left on its own where the fraction's bottom was: back into the line
        for r in [q for q in rows if q is not host and abs(q["base"] - host["base"]) < 1.5 and x0 - 2 <= min((s["bbox"][0] for s in q["spans"] if s["text"].strip() and not s.get("frac")), default=-1e9) <= x1 + 3 * size]:
            host["spans"] += [s for s in r["spans"] if s not in new]
            host["x1"] = max(host["x1"], r["x1"])
            r["spans"] = []
        for r in rows:
            ink = [q for q in r["spans"] if q["text"].strip()]
            if ink:
                r["x0"], r["x1"] = min(q["bbox"][0] for q in ink), max(q["bbox"][2] for q in ink)
            finish_row(r)
        rows[:] = [r for r in rows if r["chars"]]
        join_touching(rows)


MARKS = {"\u00af": "\u0304", "\u02c9": "\u0304", "\u203e": "\u0305", "\u02dc": "\u0303", "\u02c6": "\u0302", "\u02d9": "\u0307", "\u00a8": "\u0308", "\u2192": None}


def place_marks(r):
    """Accents drawn on their own (the bar over an antiquark, wherever it was stored) go on the letter they're drawn over."""
    def is_mark(c):
        return unicodedata.combining(c) or (c in MARKS and MARKS[c])
    letters = [(sp, c) for sp in r["spans"] for c in sp["chars"] if c["c"].isalnum()]
    moves = []
    for sp in r["spans"]:
        for c in sp["chars"]:
            if not is_mark(c["c"]):
                continue
            cx = (c["bbox"][0] + c["bbox"][2]) / 2
            near = min(letters, key=lambda l: abs((l[1]["bbox"][0] + l[1]["bbox"][2]) / 2 - cx), default=None)
            if near and abs((near[1]["bbox"][0] + near[1]["bbox"][2]) / 2 - cx) <= max(near[1]["bbox"][2] - near[1]["bbox"][0], 3):
                moves.append((sp, c, near))
    for sp, c, (tsp, tc) in moves:
        at = next((i for i, x in enumerate(tsp["chars"]) if x is tc), None)
        if at is None or not any(x is c for x in sp["chars"]):
            continue
        sp["chars"] = [x for x in sp["chars"] if x is not c]
        at = next((i for i, x in enumerate(tsp["chars"]) if x is tc), None)
        if at is None:
            continue
        tsp["chars"].insert(at + 1, {"c": MARKS.get(c["c"]) or c["c"], "origin": tc["origin"], "bbox": tc["bbox"]})
    for sp in r["spans"]:
        sp["text"] = "".join(x["c"] for x in sp["chars"])
    r["spans"] = [sp for sp in r["spans"] if sp["text"]]


VULGAR = {("1", "2"): "½", ("1", "3"): "⅓", ("2", "3"): "⅔", ("1", "4"): "¼", ("3", "4"): "¾", ("1", "5"): "⅕", ("1", "6"): "⅙", ("1", "8"): "⅛", ("3", "8"): "⅜", ("5", "8"): "⅝", ("7", "8"): "⅞"}


def stack_fractions(r):
    """Little numbers stacked in ordinary text (spin ½): one fraction, not a superscript and a subscript."""
    big = max((sp["size"] for sp in r["spans"] if sp["text"].strip()), default=0)
    small = [sp for sp in r["spans"] if re.fullmatch(r"\d{1,3}", sp["text"].strip()) and sp["size"] < big - .8 and not is_math_font(sp["font"])]
    for top in small:
        for bot in small:
            if top is bot or "text" not in top or not top["text"] or not bot["text"]:
                continue
            ov = min(top["bbox"][2], bot["bbox"][2]) - max(top["bbox"][0], bot["bbox"][0])
            if ov > .5 * min(top["bbox"][2] - top["bbox"][0], bot["bbox"][2] - bot["bbox"][0]) and bot["origin"][1] - top["origin"][1] > .3 * big:
                n, d = top["text"].strip(), bot["text"].strip()
                word = VULGAR.get((n, d)) or f"{n}\u2044{d}"
                top["text"] = word
                top["chars"] = [{"c": ch, "origin": (top["origin"][0], r.get("base", bot["origin"][1])), "bbox": (top["bbox"][0], top["bbox"][1], bot["bbox"][2], bot["bbox"][3])} for ch in word]
                line = Counter(round(x["origin"][1], 1) for x in r["spans"] if x["size"] >= big - .5 and x["text"].strip())
                top["size"], top["origin"] = big, (top["origin"][0], line.most_common(1)[0][0] if line else bot["origin"][1])
                top["bbox"] = (min(top["bbox"][0], bot["bbox"][0]), top["bbox"][1], max(top["bbox"][2], bot["bbox"][2]), bot["bbox"][3])
                bot["text"], bot["chars"] = "", []
    r["spans"] = [sp for sp in r["spans"] if sp["text"]]


def finish_row(r):
    place_marks(r)
    stack_fractions(r)
    r["spans"].sort(key=lambda s: s["origin"][0])
    ink = [s for s in r["spans"] if s["text"].strip()]
    if not ink:             # (nothing left but marks that moved onto other letters)
        r.update(text="", size=0, base=r.get("base", r["y1"]), chars=0, math=0, bold=0, soft=False)
        return
    # a blank piece lying over another piece's letters (a stray thin space) would land as a space in the wrong place
    keep = []
    for s in r["spans"]:
        host = None if s["text"].strip() else next((o for o in ink if o["bbox"][0] < s["bbox"][0] - .5 and o["bbox"][2] > s["bbox"][2] + .5 and o["chars"]
                                                    and abs(o["origin"][1] - s["origin"][1]) < .15 * max(o["size"], 1)), None)
        if host is None:
            keep.append(s)
            continue
        # (it goes into that piece where it sits, unless a space is there already)
        cs = host["chars"]
        k = next((i for i, c in enumerate(cs) if c["bbox"][0] >= s["bbox"][2] - 1), None)
        if k and host["text"] == "".join(c["c"] for c in cs) and not cs[k]["c"].isspace() and not cs[k - 1]["c"].isspace():
            host["chars"] = cs[:k] + [{"c": " ", "origin": (s["bbox"][0], host["origin"][1]), "bbox": tuple(s["bbox"])}] + cs[k:]
            host["text"] = "".join(c["c"] for c in host["chars"])
    r["spans"] = keep
    # two pieces of text with a word's gap between them and no space (a list number set apart from its item: "1.Stein")
    for a, b in zip(ink, ink[1:]):
        gap = b["bbox"][0] - a["bbox"][2]
        if (a["text"][-1:].isspace() or b["text"][:1].isspace() or a.get("img") or b.get("img") or abs(a["size"] - b["size"]) > .6
                or abs(a["origin"][1] - b["origin"][1]) > .15 * a["size"] or gap < (.32 if is_math(a) or is_math(b) else .25) * a["size"]
                or a["text"][-1:] in "([{/" or b["text"][:1] in ",.;:)]}/"
                or (a["text"][-1:].islower() and b["text"][:1].islower() and not is_math(a) and not is_math(b))):      # (mid-word: never)
            continue
        a["text"] += " "
        a["chars"] = a["chars"] + [{"c": " ", "origin": (a["bbox"][2], a["origin"][1]), "bbox": (a["bbox"][2], a["bbox"][1], b["bbox"][0], a["bbox"][3])}]
    raw = "".join(s["text"] for s in r["spans"]).rstrip()
    r["text"] = re.sub(r"\s+", " ", clean(raw)).strip() + ("-" if raw.endswith("\u00ad") else "")
    r["soft"] = raw.endswith("\u00ad")
    weights = Counter()
    for s in ink:
        weights[round(s["size"], 1)] += len(s["text"].strip())
    r["size"] = weights.most_common(1)[0][0]
    base = Counter()
    for s in ink:
        if abs(s["size"] - r["size"]) < .6:
            base[round(s["origin"][1], 1)] += len(s["text"].strip())
    r["base"] = base.most_common(1)[0][0] if base else ink[0]["origin"][1]
    n = sum(len(s["text"].strip()) for s in ink) or 1
    r["chars"] = n
    r["math"] = sum(len(s["text"].strip()) for s in ink if is_math(s)) / n
    r["bold"] = sum(len(s["text"].strip()) for s in ink if is_bold(s)) / n


def merge_rows(rows):
    r = {"spans": [s for q in rows for s in q["spans"]], "x0": min(q["x0"] for q in rows), "y0": min(q["y0"] for q in rows), "x1": max(q["x1"] for q in rows), "y1": max(q["y1"] for q in rows), "page": rows[0]["page"]}
    finish_row(r)
    return r


class Ink:
    """Where the dark pixels are on a page, leaving out the text: what's left is what was drawn."""
    TABLE = bytes(1 if v < 150 else 0 for v in range(256))

    def __init__(self, page, rows):
        pm = page.get_pixmap(matrix=pymupdf.Matrix(1, 1), colorspace=pymupdf.csGRAY, alpha=False)
        self.w, self.h, self.s = pm.width, pm.height, pm.stride
        buf = bytearray(pm.samples)
        for r in rows:
            x0, x1 = max(int(r["x0"]) - 1, 0), min(int(r["x1"]) + 2, self.w)
            for y in range(max(int(r["y0"]), 0), min(int(r["y1"]) + 1, self.h)):
                buf[y * self.s + x0:y * self.s + x1] = b"\xff" * (x1 - x0)
        self.buf = bytes(buf).translate(Ink.TABLE)

    def box(self, x0, y0, x1, y1):
        """The ink inside a box: (x0, y0, x1, y1, how many dark pixels), or None."""
        x0, x1, y0, y1 = max(int(x0), 0), min(int(x1) + 1, self.w), max(int(y0), 0), min(int(y1) + 1, self.h)
        if x1 <= x0:
            return None
        bx0, bx1, by0, by1, n = 10 ** 6, -1, None, None, 0
        for y in range(y0, y1):
            row = self.buf[y * self.s + x0:y * self.s + x1]
            k = row.count(1)
            if k:
                n += k
                bx0, bx1 = min(bx0, row.find(1) + x0), max(bx1, row.rfind(1) + x0)
                by0 = y if by0 is None else by0
                by1 = y
        return (bx0, by0, bx1 + 1, by1 + 1, n) if n else None


# ---------------- what's on all the pages
def running_heads(pages):
    """Lines repeating at the tops and bottoms of the pages, and lone page numbers."""
    n = len(pages)
    seen = Counter()
    key = lambda t: re.sub(r"[\d\W]+", "", t.lower())[:48]
    def edge(r, h):
        top, foot = (.18, .82) if OCR else (.1, .865)        # (a scanned page's margins can be wide)
        return (r["y0"] + r["y1"]) / 2 < h * top or (r["y0"] + r["y1"]) / 2 > h * foot
    for p in pages:
        for k in {key(r["text"]) for r in p["rows"] if edge(r, p["h"]) and len(key(r["text"])) > 3}:
            seen[k] += 1
    need = min(max(2, int(n * .2)), 3)
    if OCR:
        # read from a scan, the same head comes out spelt a little differently page to page
        import difflib
        alike = {k: sum(v for o, v in seen.items() if o == k or difflib.SequenceMatcher(None, k, o).ratio() > .82) for k in seen}
        seen = Counter(alike)
    for p in pages:
        keep = []
        for r in p["rows"]:
            if edge(r, p["h"]) and (seen[key(r["text"])] >= need and len(key(r["text"])) > 3 or re.fullmatch(r"[\d\s/ivxlcIVXLC.\-–—|]*(?:page\s*\d+)?(?:of\s*\d+)?", r["text"], re.I)):
                continue
            keep.append(r)
        p["heads"] = [r for r in p["rows"] if not any(r is q for q in keep)]
        # the numbered lines down the margin of a manuscript
        nums = [r for r in keep if re.fullmatch(r"\d{1,4}", r["text"])]
        if len(nums) >= 15:
            xs = Counter(round(r["x1"] / 6) for r in nums)
            col = xs.most_common(1)[0][0]
            keep = [r for r in keep if not (re.fullmatch(r"\d{1,4}", r["text"]) and abs(round(r["x1"] / 6) - col) <= 1)]
        p["rows"] = keep


def word_like(r):
    words = r["text"].split()
    letters = sum(c.isalpha() for c in r["text"])
    return len(words) >= 8 and r["chars"] >= 42 and letters / max(len(r["text"]), 1) > .62


def find_captions(p, body):
    out = []
    rows = sorted(p["rows"], key=lambda r: r["y0"])
    for r in rows:
        m = CAP.match(r["text"])
        if not m:
            continue
        after = m.group(4)
        head = r["spans"][0] if r["spans"] else None
        label_bold = any(is_bold(s) for s in r["spans"][:3])
        small = r["size"] < body - .4
        alone = r["text"].strip() == m.group(0).strip()
        delim = after in (".", ":", "|", "–", "—", "-", "—", "▪", "●", "•", "/")
        if not (delim or alone or label_bold or small or m.group(3)):
            continue
        if not delim and not alone and not (label_bold or small):
            continue
        # "Fig. 3 shows": a sentence, not a caption
        if not delim and not alone and re.match(r"\s*[a-z]", r["text"][m.start(4):]) and not (label_bold or small):
            continue
        # "…examples are shown in / Fig. 5. The …": a sentence carrying on from the line above, not a caption
        prev = [q for q in rows if q is not r and 0 <= r["y0"] - q["y1"] < .8 * max(r["y1"] - r["y0"], 6) and abs(q["x0"] - r["x0"]) < 12
                and abs(q["size"] - r["size"]) < .4 and q["x1"] - q["x0"] > .6 * (r["x1"] - r["x0"])]
        if prev and not label_bold and re.search(r"[A-Za-z,]$", prev[-1]["text"].strip()) and not re.search(r"\b(?:Fig(?:ure)?s?|Tables?)\.?\s*\d", prev[-1]["text"]):
            continue
        label = m.group(1).lower()
        kind = "table" if label.startswith(("tab",)) or "table" in label else "fig"
        out.append({"row": r, "kind": kind, "label": m.group(1).rstrip(". "), "num": re.sub(r"(?<=\d)[A-Za-z]$", "", m.group(2)).upper()})
    return out


def locate_figures(p, doc, body, content):
    """Each caption, and the picture or table next to it."""
    caps = find_captions(p, body)
    rows = p["rows"]
    used = set()
    figures = []
    ink = None
    # a caption's own lines first, so they stop the next one's search
    for c in caps:
        r = c["row"]
        extent = [r]
        below = sorted((q for q in rows if (q["y0"] >= r["y1"] - 2 or q.get("base", q["y1"]) > r.get("base", r["y1"]) + .6 * r["size"]) and q is not r and min(q["x1"], r["x1"]) - max(q["x0"], r["x0"]) > .5 * min(q["x1"] - q["x0"], r["x1"] - r["x0"])), key=lambda q: q["y0"])
        lead = max(r["y1"] - r["y0"], 6)
        for q in below:
            if q["y0"] - extent[-1]["y1"] > .9 * lead or any(q is d["row"] for d in caps) or abs(q["size"] - r["size"]) > 1.2:
                break
            if q["x0"] < r["x0"] - 25:
                break
            # a caption across the page ends where the text splits into columns again
            side = [o for o in rows if o is not q and min(o["y1"], q["y1"]) - max(o["y0"], q["y0"]) > .4 * (q["y1"] - q["y0"]) and (o["x0"] > q["x1"] + 4 or o["x1"] < q["x0"] - 4)]
            # (pieces of the same caption line, split at a wide space: same size, same baseline, within the caption)
            pieces = [o for o in side if abs(o["size"] - r["size"]) < .6 and abs(o.get("base", o["y1"]) - q.get("base", q["y1"])) < 1.5
                      and o["x0"] >= r["x0"] - 5 and o["x1"] <= r["x1"] + 5 and not any(o is d["row"] for d in caps)]
            if pieces and len(pieces) == len(side) and min([q["x0"]] + [o["x0"] for o in pieces]) < r["x0"] + 25 and max([q["x1"]] + [o["x1"] for o in pieces]) - min([q["x0"]] + [o["x0"] for o in pieces]) > .75 * (r["x1"] - r["x0"]):
                extent += [q] + [o for o in pieces if o not in extent]
                continue
            if side and q["x1"] - q["x0"] < .75 * (r["x1"] - r["x0"]):
                break
            extent.append(q)
        c["lines"] = extent
        used.update(id(q) for q in extent)
    if caps:
        ink = Ink(doc[p["n"]], rows + p.get("heads", []))
    for c in caps:
        r = c["lines"][0]
        cx0, cx1 = min(q["x0"] for q in c["lines"]), max(q["x1"] for q in c["lines"])
        cy0, cy1 = min(q["y0"] for q in c["lines"]), max(q["y1"] for q in c["lines"])
        wide = cx1 - cx0 > .62 * (content[2] - content[0])
        # the column it belongs to: all the way across unless text runs beside it
        beside = [q for q in rows if id(q) not in used and word_like(q) and q["y1"] > cy0 - 200 and q["y0"] < cy1 + 200 and (q["x1"] < cx0 or q["x0"] > cx1) and q["size"] < body + 1 and q["size"] > .5 * body]
        xa, xb = (content[0], content[2]) if wide or not beside else (cx0 - 6, cx1 + 6)
        if not wide and beside:
            mid = (cx0 + cx1) / 2
            left = [q["x1"] for q in beside if q["x1"] < mid]
            right = [q["x0"] for q in beside if q["x0"] > mid]
            xa, xb = (max(left) + 2 if left else content[0]), (min(right) - 2 if right else content[2])
        def barrier(q):
            if min(q["x1"], xb) - max(q["x0"], xa) < .5 * (q["x1"] - q["x0"]):
                return False
            # (body text stops a figure: a full line, or a column's line under a caption that spans the page)
            if id(q) in used or (word_like(q) and abs(q["size"] - body) < 1 and q["x1"] - q["x0"] > (.55 if c["kind"] == "table" else .3) * (xb - xa)):
                return True
            # (a paragraph's short last line, right under its full lines: still the paragraph)
            above = [o for o in rows if o is not q and 0 <= q["y0"] - o["y1"] < .7 * max(q["y1"] - q["y0"], 6) and abs(o["x0"] - q["x0"]) < 3
                     and abs(o["size"] - q["size"]) < .5 and word_like(o) and abs(o["size"] - body) < 1]
            return bool(above) and abs(q["size"] - body) < 1 and bool(re.search(r"[a-z]{2,}", q["text"])) and q["x1"] - q["x0"] < above[0]["x1"] - above[0]["x0"]
        top =max([q["y1"] for q in rows if q["y1"] <= cy0 + 1 and barrier(q)] or [content[1]])
        bottom = min([q["y0"] for q in rows if q["y0"] >= cy1 - 1 and barrier(q)] or [content[3]])
        def fill(a, b):
            box = ink.box(xa, a, xb, b)
            words = [q for q in rows if q["y0"] >= a - 1 and q["y1"] <= b + 1 and q["x0"] >= xa - 2 and q["x1"] <= xb + 2 and id(q) not in used]
            return box, words
        up, up_w = fill(top, cy0)
        down, down_w = fill(cy1, bottom)
        score_up = (up[4] if up else 0) + 40 * len(up_w)
        score_dn = (down[4] if down else 0) + 40 * len(down_w)
        prefer_down = c["kind"] == "table"
        if prefer_down:
            pick = "down" if score_dn and (score_dn >= score_up * .5 or not up) else "up" if score_up else None
        else:
            pick = "up" if score_up and (score_up >= score_dn * .35 or not down) else "down" if score_dn else None
        box = None
        if pick:
            b, w = (up, up_w) if pick == "up" else (down, down_w)
            xs0 = [q["x0"] for q in w] + ([b[0]] if b else [])
            ys0 = [q["y0"] for q in w] + ([b[1]] if b else [])
            xs1 = [q["x1"] for q in w] + ([b[2]] if b else [])
            ys1 = [q["y1"] for q in w] + ([b[3]] if b else [])
            box = (min(xs0) - 3, min(ys0) - 3, max(xs1) + 3, max(ys1) + 3)
            used.update(id(q) for q in w)
            # a figure wider than its caption's column: follow the drawing out, as long as no text of the page is in the way
            if b and (b[0] <= xa + 2 or b[2] >= xb - 2):
                wide = ink.box(content[0], box[1], content[2], box[3])
                if wide and (wide[0] < box[0] - 2 or wide[2] > box[2] + 2):
                    wb = (min(box[0], wide[0] - 3), box[1], max(box[2], wide[2] + 3), box[3])
                    blocked = [q for q in rows if id(q) not in used and word_like(q) and q["x1"] > wb[0] and q["x0"] < wb[2] and q["y1"] > wb[1] + 2 and q["y0"] < wb[3] - 2]
                    if not blocked:
                        extra = [q for q in rows if id(q) not in used and wb[0] <= (q["x0"] + q["x1"]) / 2 <= wb[2] and wb[1] <= (q["y0"] + q["y1"]) / 2 <= wb[3]]
                        used.update(id(q) for q in extra)
                        box = (min([wb[0]] + [q["x0"] - 3 for q in extra]), wb[1], max([wb[2]] + [q["x1"] + 3 for q in extra]), wb[3])
        if box and pick == "up":
            # labels just above the picture (a panel letter, a panel's title) set higher than the page's text
            for _ in range(2):
                over = [q for q in rows if id(q) not in used and box[1] - 1.6 * body <= q["y1"] <= box[1] + 2 and q["x0"] >= box[0] - 3 and q["x1"] <= box[2] + 3
                        and q["size"] <= body + .5 and len(q["text"]) <= 40 and not word_like(q)]
                if not over:
                    break
                used.update(id(q) for q in over)
                box = (box[0], min(q["y0"] for q in over) - 3, box[2], box[3])
        if box:
            # body text caught inside along one side (a column beside a figure whose caption is at its side): cut away
            caption = {id(q) for d in caps for q in d["lines"]}
            prose_line = lambda q: len(q["text"].split()) >= 4 and q["chars"] >= 20 and sum(ch.isalpha() for ch in q["text"]) > .6 * len(q["text"])
            inside = [q for q in rows if id(q) not in caption and prose_line(q) and abs(q["size"] - body) < 1 and box[0] <= (q["x0"] + q["x1"]) / 2 <= box[2] and box[1] <= (q["y0"] + q["y1"]) / 2 <= box[3]]
            mid = (box[0] + box[2]) / 2
            if len(inside) >= 3 and all(q["x0"] > mid - 5 for q in inside):
                box = (box[0], box[1], min(q["x0"] for q in inside) - 3, box[3])
            elif len(inside) >= 3 and all(q["x1"] < mid + 5 for q in inside):
                box = (max(q["x1"] for q in inside) + 3, box[1], box[2], box[3])
            else:
                inside = []
            # (and that text goes back to the page's flow; so does anything else of the column beside it)
            side = [q for q in rows if inside and (q["x0"] >= box[2] - 1 or q["x1"] <= box[0] + 1) and box[1] - 2 <= (q["y0"] + q["y1"]) / 2 <= box[3] + 2]
            used.difference_update(id(q) for q in inside + side)
        figures.append({"kind": c["kind"], "label": c["label"], "num": c["num"], "page": p["n"], "box": box, "lines": c["lines"]})
    return figures, used


def join_touching(rows):
    """Pieces of one line that now meet (bridged by a symbol or a picture) become one line."""
    def joins(a, b):
        return b is not a and abs(b["base"] - a["base"]) < 1.5 and -1 <= b["x0"] - a["x1"] <= .7 * min(a["size"], b["size"])
    joined = True
    while joined:
        joined = False
        for a in rows:
            b = next((b for b in rows if joins(a, b)), None)
            if b:
                a["spans"] += b["spans"]
                a["x1"], a["y0"], a["y1"] = max(a["x1"], b["x1"]), min(a["y0"], b["y0"]), max(a["y1"], b["y1"])
                finish_row(a)
                rows.remove(b)
                joined = True
                break


def drawn_figures(pg, p, rows, taken, body, band=None):
    """Drawings and pictures with no caption (a diagram, a graph), with the labels written on them: kept as one picture
    where they sit in the text. Returns the rows left and the boxes taken."""
    area = p["w"] * p["h"]
    words = [r for r in rows if word_like(r)]
    shapes = []
    for d in pg.get_drawings():
        r = d["rect"]
        if r.is_empty or r.x1 < 0 or r.y1 < 0 or r.x0 > p["w"] or r.y0 > p["h"]:
            continue
        if band and (r.y1 <= band[0] or r.y0 >= band[1]):            # (the running head's bar or logo)
            continue
        if r.width * r.height > .3 * area:
            continue
        if r.height < 1.5 and r.width > .45 * p["w"]:          # (a rule across the page)
            continue
        if sum(1 for q in words if r.contains(pymupdf.Rect(q["x0"], q["y0"], q["x1"], q["y1"]))) >= 2:
            continue                                              # (a box or shading behind text)
        shapes.append(r)
    maybe = []
    for im in page_images(pg):
        b = pymupdf.Rect(im["bbox"]) & pg.rect
        if b.width * b.height >= .8 * area or min(b.width, b.height) < 12:
            continue
        if b.height >= 3.5 * body and b.width >= 40:
            shapes.append(b)
        else:
            maybe.append(b)                # (small: part of a diagram if it sits by one, else an equation)
    shapes = [b for b in shapes if not any(pymupdf.Rect(t).intersects(b) for t in taken)]
    # neighbours join up into one picture
    groups = []
    for b in sorted(shapes, key=lambda b: (b.y0, b.x0)):
        k = next((k for k, g in enumerate(groups) if (g + (-6, -6, 6, 6)).intersects(b)), None)
        if k is None:
            groups.append(pymupdf.Rect(b))
        else:
            groups[k] = groups[k] | b
    merged = True
    while merged:
        merged = False
        for i, a in enumerate(groups):
            for j in range(i + 1, len(groups)):
                if (a + (-6, -6, 6, 6)).intersects(groups[j]):
                    groups[i] = a | groups.pop(j); merged = True
                    break
            if merged:
                break
    for b in maybe:
        k = next((k for k, g in enumerate(groups) if (g + (-15, -15, 15, 15)).intersects(b)), None)
        if k is not None:
            groups[k] = groups[k] | b
    # small pieces (an arrow, a label's circle) belong to the diagram they sit by
    big = [g for g in groups if g.width >= 30 and g.height >= 18]
    grew = True
    while grew:
        grew = False
        for sm in [g for g in groups if not any(g is b for b in big)]:
            k = next((k for k, b in enumerate(big) if (b + (-22, -22, 22, 22)).intersects(sm)), None)
            if k is not None:
                big[k] = big[k] | sm
                groups = [g for g in groups if g is not sm]
                grew = True
        for i in range(len(big)):           # (and diagrams that now touch are one)
            for j in range(len(big) - 1, i, -1):
                if (big[i] + (-8, -8, 8, 8)).intersects(big[j]):
                    big[i] = big[i] | big.pop(j); grew = True
    boxes = []
    for g in big:
        # the labels on it, and short labels just around it
        for _ in range(2):
            for q in rows:
                qb = pymupdf.Rect(q["x0"], q["y0"], q["x1"], q["y1"])
                if word_like(q) and not (g.contains(qb)):
                    continue
                if (g + (-10, -10, 10, 10)).intersects(qb) and (q["chars"] <= 40 or g.contains(qb)):
                    g = g | qb
        sentences = [q for q in rows if len(re.findall(r"[^\W\d_]{2,}", q["text"])) >= 5 and q["chars"] >= 25]       # (lines of prose, however narrow)
        if sum(1 for q in sentences if g.contains(pymupdf.Rect(q["x0"], q["y0"], q["x1"], q["y1"]))) >= 3:
            continue                                              # (it's a page of text with a frame around it)
        if any(q["size"] > body + 1.5 and q["chars"] >= 3 and g.contains(pymupdf.Point((q["x0"] + q["x1"]) / 2, (q["y0"] + q["y1"]) / 2)) for q in rows):
            continue                                              # (a chapter's title among its decorations: the title is what matters)
        boxes.append(g + (-3, -3, 3, 3))
    if not boxes:
        return rows, []
    left = []
    for q in rows:
        c = ((q["x0"] + q["x1"]) / 2, (q["y0"] + q["y1"]) / 2)
        if any(b.x0 <= c[0] <= b.x1 and b.y0 <= c[1] <= b.y1 for b in boxes):
            continue
        left.append(q)
    for b in boxes:
        sp = picture_span(b, b.y1, body)
        sp["fig"] = True
        r = {"spans": [sp], "x0": b.x0, "y0": b.y0, "x1": b.x1, "y1": b.y1, "page": p["n"]}
        finish_row(r)
        left.append(r)
    return sorted(left, key=lambda r: (r["y0"], r["x0"])), [tuple(b) for b in boxes]


def drawn_bars(pg, rows):
    """Short flat lines drawn just above a letter are its bar (an antiparticle's): a combining overline on the letter.
    A fraction's line, with numbers above and below it, isn't."""
    chars = [(r, sp, c) for r in rows for sp in r["spans"] if not sp.get("img") for c in sp["chars"] if c["c"].isalnum()]
    for d in pg.get_drawings():
        b = d["rect"]
        if not (b.height < 1.6 and 2.5 < b.width < 14):
            continue
        under = [(r, sp, c) for r, sp, c in chars if min(b.x1, c["bbox"][2]) - max(b.x0, c["bbox"][0]) > .55 * min(b.width, c["bbox"][2] - c["bbox"][0])
                 and 0 <= (c["origin"][1] - .72 * sp["size"]) - b.y1 <= .35 * sp["size"]]
        above = [c for r, sp, c in chars if min(b.x1, c["bbox"][2]) - max(b.x0, c["bbox"][0]) > 0 and -1 <= b.y0 - c["origin"][1] <= .45 * sp["size"]]
        # (a root sign's top stroke runs over what's under the root)
        rooted = any(x["c"] == "√" and b.x0 - 6 < x["bbox"][2] <= b.x0 + 3 and x["bbox"][1] - 3 < b.y1 for r in rows for sp in r["spans"] for x in sp["chars"])
        # an antiparticle's bar is about one letter wide; a fraction's or a root's spans more
        fits = len(under) == 1 and .5 <= b.width / max(under[0][2]["bbox"][2] - under[0][2]["bbox"][0], .1) <= 1.8
        if not under or above or rooted or not fits or under[0][2]["c"].isdigit():
            continue
        for r, sp, c in under[:1]:
            at = next((i for i, x in enumerate(sp["chars"]) if x is c), None)
            if at is not None and not (at + 1 < len(sp["chars"]) and sp["chars"][at + 1]["c"] in "\u0304\u0305"):
                sp["chars"].insert(at + 1, {"c": "\u0305", "origin": c["origin"], "bbox": c["bbox"]})
                sp["text"] = "".join(x["c"] for x in sp["chars"])
                finish_row(r)
    # a slash drawn as a line rather than typed (c/ν): put back as "/"
    for d in pg.get_drawings():
        b = d["rect"]
        items = d.get("items") or []
        if not (len(items) == 1 and items[0][0] == "l" and b.width < 6 and b.height > 2):
            continue
        p1, p2 = items[0][1], items[0][2]
        if not ((p1.y > p2.y) == (p1.x < p2.x)):              # (rising to the right, like /)
            continue
        cx = (b.x0 + b.x1) / 2
        for r in rows:
            if r["y0"] - 1 <= (b.y0 + b.y1) / 2 <= r["y1"] + 1 and r["x0"] <= cx <= r["x1"] and .5 * r["size"] < b.height < 1.6 * r["size"]:
                if any(c["c"] == "/" and abs((c["bbox"][0] + c["bbox"][2]) / 2 - cx) < 3 for sp in r["spans"] for c in sp["chars"]):
                    break
                model = next((sp for sp in r["spans"] if sp["text"].strip() and not sp.get("img")), None)
                if model:
                    c = {"c": "/", "origin": (b.x0, r["base"]), "bbox": (b.x0, b.y0, b.x1, b.y1)}
                    r["spans"].append(dict(model, text="/", chars=[c], bbox=c["bbox"], origin=c["origin"], flags=0, font=model["font"]))
                    finish_row(r)
                break
    # a bar over a whole word, set as "spaces" in a font that draws them as a line (n̄eutron for antineutron):
    # blank text with ink above the letters under it
    k = 3
    blanks = [s["bbox"] for b in page_blocks(pg) for l in b.get("lines", []) for s in l["spans"]
              if s["chars"] and not "".join(c["c"] for c in s["chars"]).strip() and s["bbox"][2] - s["bbox"][0] > 4]
    for x0, y0, x1, y1 in blanks:
        for r in rows:
            if not (r["y0"] - 4 <= (y0 + y1) / 2 <= r["y1"] + 4):
                continue
            under = [(t, c) for t in r["spans"] if not t.get("img") for c in t["chars"] if c["c"].isalnum() and x0 - 1 <= (c["bbox"][0] + c["bbox"][2]) / 2 <= x1 + 1]
            if not under:
                continue
            top = min(c["origin"][1] - .72 * t["size"] for t, c in under)
            band = pymupdf.Rect(x0, top - .6 * r["size"], x1, top - .5) & pg.rect
            if band.is_empty or band.height < 1:
                continue
            pm = pg.get_pixmap(matrix=pymupdf.Matrix(k, k), clip=band, colorspace=pymupdf.csGRAY, alpha=False)
            buf = bytes(pm.samples)
            line = any(sum(1 for x in range(pm.width) if buf[y * pm.stride + x] < 140) > .7 * pm.width for y in range(pm.height))
            if not line:
                continue
            for t, c in under:
                at = next((i for i, x in enumerate(t["chars"]) if x is c), None)
                if at is not None and not (at + 1 < len(t["chars"]) and t["chars"][at + 1]["c"] in "̄̅"):
                    t["chars"].insert(at + 1, {"c": "̅", "origin": c["origin"], "bbox": c["bbox"]})
                    t["text"] = "".join(x["c"] for x in t["chars"])
            finish_row(r)


def picture_span(box, base, size):
    return {"text": "\ufffc", "img": True, "font": "picture", "size": size, "flags": 0, "bbox": tuple(box), "origin": (box[0], base),
            "chars": [{"c": "\ufffc", "origin": (box[0], base), "bbox": tuple(box)}]}


def place_pictures(pg, p, rows, taken, body):
    """Small pictures in the page that aren't figures: equations set as images. One inside a line of text goes into
    that line; one on its own becomes a line of its own (and so a displayed equation)."""
    area = p["w"] * p["h"]
    for im in page_images(pg):
        b = pymupdf.Rect(im["bbox"]) & pg.rect
        if b.is_empty or b.width * b.height > .25 * area or b.width < 3 or b.height < 3:
            continue
        c = ((b.x0 + b.x1) / 2, (b.y0 + b.y1) / 2)
        if any(t[0] <= c[0] <= t[2] and t[1] <= c[1] <= t[3] for t in taken):
            continue
        # an empty picture (a placeholder over real text) isn't an equation
        pm = pg.get_pixmap(clip=b, dpi=72, colorspace=pymupdf.csGRAY, alpha=False)
        if bytes(pm.samples).translate(Ink.TABLE).count(1) < max(3, .004 * pm.width * pm.height):
            continue
        # text lying on the picture is a hidden copy of it (for searching): the picture says it
        for r in rows if pg.number not in OCR else []:
            gone = False
            for sp in r["spans"]:
                if sp.get("img"):
                    continue
                kept = [ch for ch in sp["chars"] if not (b.x0 - .5 <= (ch["bbox"][0] + ch["bbox"][2]) / 2 <= b.x1 + .5 and b.y0 - .5 <= (ch["bbox"][1] + ch["bbox"][3]) / 2 <= b.y1 + .5)]
                if len(kept) != len(sp["chars"]):
                    sp["chars"], sp["text"], gone = kept, "".join(ch["c"] for ch in kept), True
            if gone:
                r["spans"] = [sp for sp in r["spans"] if sp["text"]]
                finish_row(r)
        rows = [r for r in rows if r.get("chars")]
        home, best = None, None
        for r in rows:
            t0, t1 = tight(r["spans"]) or (r["y0"], r["y1"])
            ov = min(t1, b.y1) - max(t0, b.y0)
            d = max(r["x0"] - b.x1, b.x0 - r["x1"], 0)            # (the piece of the line it sits beside)
            if ov > .45 * min(t1 - t0, b.height) and d <= 3 * body and b.height < 2.6 * body:
                if best is None or d < best:
                    home, best = r, d
        if home:
            home["spans"].append(picture_span(b, home["base"], home["size"]))
            home["x0"], home["x1"] = min(home["x0"], b.x0), max(home["x1"], b.x1)
            finish_row(home)
        else:
            r = {"spans": [picture_span(b, b.y1, body)], "x0": b.x0, "y0": b.y0, "x1": b.x1, "y1": b.y1, "page": p["n"]}
            finish_row(r)
            rows.append(r)
    join_touching(rows)
    return sorted(rows, key=lambda r: (r["y0"], r["x0"]))


def loose_pictures(p, doc, used, figures, body):
    """Pictures with no caption of their own. Logos and rules are too small to count."""
    pg = doc[p["n"]]
    if pg.number in OCR:
        return []           # (a page read from its picture: what the reading left is in its own pieces already)
    for im in page_images(pg):
        b = im["bbox"]
        if (b[2] - b[0]) * (b[3] - b[1]) > .8 * p["w"] * p["h"]:
            return []       # a scanned page, with text laid over it
    ink = Ink(pg, p["rows"] + p.get("heads", []))
    taken = [f["box"] for f in figures if f["box"]]
    out = []
    y, start, last, x0, x1 = 0, None, None, 10 ** 6, -1
    def flush():
        if start is not None and last - start >= 60 and x1 - x0 >= 120:
            box = (x0 - 3, start - 3, x1 + 3, last + 3)
            if not any(min(box[3], t[3]) - max(box[1], t[1]) > .3 * (box[3] - box[1]) and min(box[2], t[2]) - max(box[0], t[0]) > .3 * (box[2] - box[0]) for t in taken):
                b = ink.box(*box)
                if b and b[4] > .02 * (box[2] - box[0]) * (box[3] - box[1]):
                    out.append(box)
    for y in range(int(p["h"] * .07), int(p["h"] * .95)):
        row = ink.buf[y * ink.s:y * ink.s + ink.w]
        if row.count(1) >= 6:
            if start is None:
                start, x0, x1 = y, 10 ** 6, -1
            last = y
            x0, x1 = min(x0, row.find(1)), max(x1, row.rfind(1))
        elif start is not None and y - last > 14:
            flush()
            start = None
    flush()
    return out


# ---------------- reading order: columns, however many
def order_rows(rows, content, body):
    if not rows:
        return []
    width = content[2] - content[0]
    narrow = [r for r in rows if r["x1"] - r["x0"] < .56 * width and r["chars"] > 24]
    # (read from a scan, some of them must sit side by side: short last lines of entries in one column don't make columns)
    columns = len(narrow) >= 4 and (not OCR or sum(1 for a in narrow for b in narrow if a["x1"] < b["x0"]) >= 2)

    def gutter(rs):
        if len(rs) < 6:
            return None
        spans = sorted((r["x0"], r["x1"]) for r in rs)
        best, end = None, spans[0][1]
        for a, b in spans[1:]:
            if a - end >= max(6.5, .6 * body):
                left = [r for r in rs if r["x1"] <= a - .1]
                right = [r for r in rs if r["x0"] >= end - .1]
                if len(left) >= 3 and len(right) >= 3 and sum(r["chars"] for r in left) > 80 and sum(r["chars"] for r in right) > 80:
                    gain = min(sum(r["chars"] for r in left), sum(r["chars"] for r in right))
                    if best is None or gain > best[0]:
                        best = (gain, (a + end) / 2)
            end = max(end, b)
        return best[1] if best else None

    def walk(rs, depth=0):
        if depth > 8:
            return [sorted(rs, key=lambda r: (r["y0"], r["x0"]))]
        g = gutter(rs)
        if g is not None:
            return walk([r for r in rs if (r["x0"] + r["x1"]) / 2 < g], depth + 1) + walk([r for r in rs if (r["x0"] + r["x1"]) / 2 >= g], depth + 1)
        if columns and len(rs) >= 12:
            # no gap all the way down: something across the top or bottom (a table running on, a wide figure's labels)
            # crosses it. Cut that off where the rest has clean columns.
            ys = sorted({round(r["y1"], 1) for r in rs})
            for y in ys:                                  # (from the top: the shortest band cut off)
                below = [r for r in rs if r["y0"] >= y - .5]
                if len(below) < .55 * len(rs):
                    break
                if gutter(below) is not None:
                    above = [r for r in rs if r["y0"] < y - .5]
                    return walk(above, depth + 1) + walk(below, depth + 1)
            for y in sorted({round(r["y0"], 1) for r in rs}, reverse=True):
                above = [r for r in rs if r["y1"] <= y + .5]
                if len(above) < .55 * len(rs):
                    break
                if gutter(above) is not None:
                    return walk(above, depth + 1) + walk([r for r in rs if r["y1"] > y + .5], depth + 1)
        rs = sorted(rs, key=lambda r: (r["y0"], r["x0"]))
        if not columns:
            return [rs]
        bands, cur = [], [rs[0]]
        for r in rs[1:]:
            wide_now = r["x1"] - r["x0"] > .62 * width
            wide_last = cur[-1]["x1"] - cur[-1]["x0"] > .62 * width
            if wide_now != wide_last or r["y0"] - max(q["y1"] for q in cur) > 1.8 * body:
                bands.append(cur); cur = [r]
            else:
                cur.append(r)
        bands.append(cur)
        if len(bands) == 1:
            return [rs]
        out = []
        for b in bands:
            out += walk(b, depth + 1) if gutter(b) is not None else [b]
        return out

    leaves = []
    for rs in walk(rows):
        if leaves and abs(leaves[-1][-1]["x0"] - rs[0]["x0"]) < 12 and abs(max(q["x1"] for q in leaves[-1]) - max(q["x1"] for q in rs)) < .2 * width and rs[0]["y0"] > leaves[-1][-1]["y0"] and rs[0]["y0"] - leaves[-1][-1]["y1"] < 2.2 * body:
            leaves[-1] += rs
        else:
            leaves.append(rs)
    return leaves


# ---------------- a line → HTML
class Maker:
    """Holds the document, the pictures cut from it, and how the text flows."""

    def __init__(self, doc):
        self.long = doc.page_count > 150
        self.doc, self.images, self.zooms, self.tail, self.nrefs, self.body = doc, {}, [], "", 0, 10.0
        self.words = set()
        self.page_rows = {}
        self.turns = {}             # page → how far to turn its pictures (a page printed sideways)
        self.raster = False         # a scan: its pieces are pictures, not drawings
        self.keep_hyphens = bool(re.search(r"word|office", (doc.metadata.get("producer", "") + doc.metadata.get("creator", "")), re.I))

    def blanks(self, page, rect, keep):
        """Letters of other lines inside a box: they're whited out of its picture."""
        out = []
        if keep is None:
            return out
        for r in self.page_rows.get(page, []):
            for sp in r["spans"]:
                if id(sp) in keep or not sp["text"].strip() or sp.get("img"):
                    continue
                for c in sp["chars"]:
                    b = pymupdf.Rect(c["bbox"])
                    top = c["origin"][1] - .78 * sp["size"]      # (the letter itself, not the font's tall box)
                    b = pymupdf.Rect(b.x0, max(b.y0, top), b.x1, min(b.y1, c["origin"][1] + .25 * sp["size"]))
                    if b.intersects(rect):
                        out.append(b)
        return out

    def vector(self, page, box, keep=None, stem="v"):
        """A piece of the page as SVG: sharp at any size (e-ink especially), and small. A PNG if the SVG comes out big."""
        rect = pymupdf.Rect(box) & self.doc[page].rect
        if rect.is_empty or rect.width < 1 or rect.height < 1 or self.raster:
            return self.crop(page, box, dpi=400, keep=keep)
        out = pymupdf.open()
        pg = out.new_page(width=rect.width, height=rect.height)
        pg.show_pdf_page(pg.rect, self.doc, page, clip=rect)
        for b in self.blanks(page, rect, keep):
            pg.draw_rect(b - (rect.x0, rect.y0, rect.x0, rect.y0), color=None, fill=(1, 1, 1), overlay=True)
        svg = pg.get_svg_image(text_as_path=True)
        if len(svg) > 220_000:
            return self.crop(page, box, dpi=400, keep=keep)
        name = f"{stem}{len(self.images) + 1}.svg"
        self.images[name] = svg.encode("utf-8")
        return name, rect.width, rect.height

    def trim(self, page, box, keep):
        """The box shrunk to the ink inside it (other lines' letters left out), with a hair of margin: no blank bands
        around an equation."""
        rect = pymupdf.Rect(box) & self.doc[page].rect
        if rect.is_empty or rect.width < 2 or rect.height < 2:
            return box
        k = 3
        pm = self.doc[page].get_pixmap(matrix=pymupdf.Matrix(k, k), clip=rect, alpha=False, colorspace=pymupdf.csGRAY)
        for b in self.blanks(page, rect, keep):
            ir = pymupdf.IRect(pm.x + int((b.x0 - rect.x0) * k), pm.y + int((b.y0 - rect.y0) * k), pm.x + int((b.x1 - rect.x0) * k) + 1, pm.y + int((b.y1 - rect.y0) * k) + 1) & pm.irect
            if not ir.is_empty:
                pm.set_rect(ir, (255,) * pm.n)
        buf = bytes(pm.samples).translate(Ink.TABLE)
        rows = [y for y in range(pm.height) if buf[y * pm.stride:y * pm.stride + pm.width].count(1)]
        if not rows:
            return box
        cols = [x for x in range(pm.width) if any(buf[y * pm.stride + x] for y in range(rows[0], rows[-1] + 1))]
        m = .6
        return (max(rect.x0, rect.x0 + cols[0] / k - m), max(rect.y0, rect.y0 + rows[0] / k - m),
                min(rect.x1, rect.x0 + (cols[-1] + 1) / k + m), min(rect.y1, rect.y0 + (rows[-1] + 1) / k + m))

    def lines_of(self, page, box, keep):
        """A displayed equation of several lines, split where a clear gap runs across it (not inside a fraction)."""
        rect = pymupdf.Rect(box) & self.doc[page].rect
        if rect.height < 2.4 * self.body:
            return [rect]
        k = 2
        pm = self.doc[page].get_pixmap(matrix=pymupdf.Matrix(k, k), clip=rect, alpha=False, colorspace=pymupdf.csGRAY)
        for b in self.blanks(page, rect, keep):
            ir = pymupdf.IRect(pm.x + int((b.x0 - rect.x0) * k), pm.y + int((b.y0 - rect.y0) * k), pm.x + int((b.x1 - rect.x0) * k) + 1, pm.y + int((b.y1 - rect.y0) * k) + 1) & pm.irect
            if not ir.is_empty:
                pm.set_rect(ir, (255,) * pm.n)
        buf = bytes(pm.samples).translate(Ink.TABLE)
        inked = [buf[y * pm.stride:y * pm.stride + pm.width].count(1) > 0 for y in range(pm.height)]
        need = max(3, .3 * self.body) * k
        cuts, run, start = [], 0, 0
        for y, ink in enumerate(inked):
            if ink:
                if run >= need and y - start > .55 * self.body * k:
                    cuts.append(y - run // 2)
                    start = y
                run = 0
            else:
                run += 1
        if not cuts:
            return [rect]
        ys = [rect.y0] + [rect.y0 + c / k for c in cuts] + [rect.y1]
        parts = [pymupdf.Rect(rect.x0, a, rect.x1, b) for a, b in zip(ys, ys[1:]) if b - a > .55 * self.body]
        # each line of a several-line equation is a statement of its own (it has an = or carries one on with + or −);
        # the top and bottom of a fraction aren't, and stay together
        def says(part):
            text = "".join(c["c"] for r in self.page_rows.get(page, []) for sp in r["spans"] if keep is None or id(sp) in keep
                           for c in sp["chars"] if part.contains(pymupdf.Point((c["bbox"][0] + c["bbox"][2]) / 2, c["origin"][1] - .3 * sp["size"])))
            return bool(re.search(r"[=≈≤≥<>≡∝→⇒≃∼]", text) or re.match(r"\s*[+\-−±]", text))
        if len(parts) < 2 or not all(says(q) for q in parts):
            return [rect]
        return parts

    def crop(self, page, box, dpi=300, gray=True, turn=0, stem="m", keep=None):
        rect = pymupdf.Rect(box) & self.doc[page].rect
        if rect.is_empty or rect.width < 1 or rect.height < 1:      # (a sliver: at least a point each way)
            c = pymupdf.Rect(box).tl if not pymupdf.Rect(box).is_infinite else pymupdf.Point(0, 0)
            rect = pymupdf.Rect(c.x - 1, c.y - 1, c.x + 2, c.y + 2) & self.doc[page].rect
            if rect.is_empty:
                rect = pymupdf.Rect(0, 0, 2, 2)
        blank = self.blanks(page, rect, keep)
        limit = 2000 / max(rect.width * dpi / 72, rect.height * dpi / 72, 1)
        dpi = dpi * min(limit, 1)
        m = pymupdf.Matrix(dpi / 72, dpi / 72).prerotate(turn)
        pm = self.doc[page].get_pixmap(matrix=m, clip=rect, alpha=False, colorspace=pymupdf.csGRAY if gray else pymupdf.csRGB)
        k = dpi / 72
        for b in blank:
            ir = pymupdf.IRect(pm.x + int((b.x0 - rect.x0) * k), pm.y + int((b.y0 - rect.y0) * k), pm.x + int((b.x1 - rect.x0) * k) + 1, pm.y + int((b.y1 - rect.y0) * k) + 1) & pm.irect      # (a cropped picture keeps the page's coordinates)
            if not ir.is_empty:
                pm.set_rect(ir, (255,) * pm.n)
        if self.raster and pm.width * pm.height > 0 and pm.n in (1, 3) and pm.stride == pm.width * pm.n:
            # a scan's paper is grey or yellowed: lifted to white, the ink kept dark (each colour by its own paper)
            raw, n = bytes(pm.samples), pm.n
            chans = []
            for ch in range(n):
                hist = sorted(raw[ch::max(n, len(raw) // 4000 // n * n)])
                paper = .8 * max(hist[int(.85 * (len(hist) - 1))], 120)      # (and the print showing through from the back)
                ink = .45 * paper
                chans.append(bytes(0 if v <= ink else min(255, int((v - ink) * 255 / (paper - ink))) for v in range(256)))
            if n == 1:
                raw = raw.translate(chans[0])
            else:
                out = bytearray(raw)
                for ch in range(3):
                    out[ch::3] = raw[ch::3].translate(chans[ch])
                raw = bytes(out)
            pm = pymupdf.Pixmap(pymupdf.csGRAY if n == 1 else pymupdf.csRGB, pm.width, pm.height, raw, 0)
        data, ext = pm.tobytes("png"), "png"
        if len(data) > 700_000:
            jpg = pm.tobytes("jpeg", jpg_quality=85)
            if len(jpg) < len(data) * .6:
                data, ext = jpg, "jpg"
        name = f"{stem}{len(self.images) + 1}.{ext}"
        self.images[name] = data
        return name, pm.width, pm.height

    def glyph(self, page, box, base=None, size=None):
        """One symbol as a picture: cropped to the letter's own height (a font's box is far taller), sitting on the line."""
        if base is not None and size:
            box = (box[0], max(box[1], base - .85 * size), box[2], min(box[3], base + .25 * size))
        name, _, _ = self.vector(page, box)
        h = (box[3] - box[1]) / self.body
        drop = ((box[3] - base) / self.body) if base is not None else .2
        return f'<img class="gl" alt="" src="images/{name}" style="height:{h:.2f}em;vertical-align:-{max(drop, 0):.2f}em"/>'

    def formula(self, page, box, inline=True, number=None, keep=None, raster=False):
        """A picture of an equation (vector, so sharp at any size), tap for full size; its size follows the equation
        size. A displayed equation of several lines is one picture per line, so each fits a narrow screen."""
        box = self.trim(page, (box[0] - .8, box[1] - .8, box[2] + .8, box[3] + .8), keep)
        pts_w = (box[2] - box[0]) / self.body
        draw = (lambda pg, b, kp: self.crop(pg, b, dpi=300, keep=kp)) if raster else self.vector      # (a picture already: as it is)
        if inline:
            name, w, h = draw(page, box, keep)
            img = f'<img class="im" alt="formula" src="images/{name}" style="height:{(box[3] - box[1]) / self.body:.2f}em"/>'
        else:
            parts = self.lines_of(page, box, keep) if not raster else [pymupdf.Rect(box)]
            imgs = []
            for part in parts:
                name, w, h = draw(page, part, keep)
                imgs.append(f'<img alt="equation" src="images/{name}" style="width:{pts_w:.2f}em"/>')
            img = "<br/>".join(imgs)
            if len(parts) > 1 and not self.long:
                name, w, h = self.vector(page, box, keep)        # (the whole equation, for its full-size page)
        if self.long:           # (thousands of extra pages would weigh a book down: Babel's readers zoom any picture when tapped)
            return img
        zid = len(self.zooms) + 1
        self.zooms.append({"id": zid, "image": name, "w": w, "h": h, "number": number})
        return f'<a class="zl" id="z{zid}" href="eq{zid}.xhtml">{img}</a>'


def esc(t):
    return html.escape(t, quote=False)


def is_formula(tail):
    m = re.search(r"[A-Za-z0-9]+$", tail)
    return bool(m and re.fullmatch(r"(?:[A-Z][a-z]?\d*)+", m.group()) and all(e in ELEMENTS for e in re.findall(r"[A-Z][a-z]?", m.group())))


def good_citation(run, nrefs):
    nums = [int(x) for x in re.findall(r"\d+", run)]
    return bool(nums) and all(1 <= n <= nrefs for n in nums) and nums == sorted(nums) and len(set(nums)) == len(nums) and not re.search(r"(?:^|\D)0", run)


def flat_scripts(core, tail, nrefs):
    """Small type set on the line: only the words around it tell a subscript from a citation."""
    if not core:
        return []
    tailing = re.fullmatch(r"(\d+(?:[,–-]\d+)*)([,*†‡§]+)", core)
    if tailing:
        parts = flat_scripts(tailing.group(1), tail, nrefs)
        return parts + [(tailing.group(2), "sup" if not parts or parts[-1][1] != "sub" else "")]
    if re.fullmatch(r"[A-Z]{2,}.*|[A-Z][a-z]+", core):      # small capitals
        return [(core, "")]
    if not re.fullmatch(r"\d+(?:[,–-]\d+)*", core):
        if tail[-1:].isspace() or not tail:
            return [(core, "")]
        return [(core, "sup" if core[0] in "−-+o*†‡§" or core[-1] in "+−" else "sub")]
    if tail.endswith("L1"):
        return [(core, "sub")]
    if re.search(r"[\d)−\-+×^]\s*$", tail) or UNIT_TAIL.search(tail):
        return [(core, "sup")]
    if is_formula(tail):
        if re.search(r"[,–-]", core):
            if good_citation(core, nrefs):
                return [(core, "cite")]
            return [(core[0], "sub"), (core[1:], "cite" if good_citation(core[1:], nrefs) else "sup")]
        return [(core[0], "sub"), (core[1:], "cite" if good_citation(core[1:], nrefs) else "sup")] if len(core) >= 3 else [(core, "sub")]
    if re.search(r"(?:^|[^A-Za-z])[A-Z]$|[α-ω]$", tail):
        return [(core, "sub")]
    return [(core, "cite" if good_citation(core, nrefs) else "sup")]


REFS = set()


def cite_html(core):
    return re.sub(r"\d+", lambda m: f'<a class="cit" href="references.xhtml#r{int(m.group())}">{m.group()}</a>' if int(m.group()) in REFS else m.group(), core)


def script_of(s, r, body):
    if s.get("forced") is not None:
        return s["forced"]
    if s["text"].strip() in ("√", "∼", "~") or all(unicodedata.combining(c) for c in s["text"].strip()):
        return ""
    rise = r["base"] - s["origin"][1]
    small = s["size"] < r["size"] - .8
    unit = max(s["size"], body) * .14
    if not small and (not is_math(s) and len(s["text"].strip()) > 2 or s["text"].strip() in ("−", "-", "+", "=", "×", "·", "±", "→", "←")):
        return ""
    if rise > unit:
        return "sup"
    if rise < -unit:
        return "sub"
    return "flat" if small else ""


def stacked(spans):
    """Math written above other math (fractions, limits): it can't go in a line of text. A superscript over a
    subscript can (ρ with xy below and THE above)."""
    big = max((s["size"] for s in spans if s["text"].strip()), default=0)
    for a in spans:
        for b in spans:
            ov = min(a["bbox"][2], b["bbox"][2]) - max(a["bbox"][0], b["bbox"][0])
            if a is not b and ov > 1.5 and b["origin"][1] - a["origin"][1] > .62 * max(a["size"], b["size"]):
                if a["size"] < big - .8 and b["size"] < big - .8:
                    continue
                return True
    return False


def row_html(mk, r, cite=False):
    """One line as inline HTML. Math that's plain letters stays text; anything else in it becomes a picture."""
    out, run = [], []
    tail_box = mk
    # a fraction written in ordinary letters (λ = c/ν set one over the other): its pieces are math, so it's kept as drawn
    short = [s for s in r["spans"] if 0 < len(s["text"].strip()) <= 4 and not s.get("img")]
    for a in short:
        for b in short:
            if a is not b and min(a["bbox"][2], b["bbox"][2]) - max(a["bbox"][0], b["bbox"][0]) > .4 * min(a["bbox"][2] - a["bbox"][0], b["bbox"][2] - b["bbox"][0]) \
                    and b["origin"][1] - a["origin"][1] > .45 * max(a["size"], b["size"]) and not re.fullmatch(r"\d+", a["text"].strip() + b["text"].strip())                     and not (a["size"] < max(r["size"], mk.body) - .8 and b["size"] < max(r["size"], mk.body) - .8):      # (a superscript over a subscript isn't a fraction)
                a["stack"] = b["stack"] = True

    def end_run():
        nonlocal run
        if not run:
            return
        ink = [s for s in run if s["text"].strip()]
        # (a space the PDF put at the edge of the maths, inside its first or last piece, stays outside it)
        lead_sp, trail_sp, at = clean(run[0]["text"])[:1].isspace(), clean(run[-1]["text"])[-1:].isspace(), len(out)
        if ink:
            text = clean("".join(s["text"] for s in ink))
            hard = any(drawn_letters(sp) for sp in ink) or any(sp.get("stack") for sp in ink) or stacked(ink) or any(bad_text(clean(s["text"])) for s in ink) or re.search(r"[∑∏∫]", text) or ("√" in text and any(s["size"] > r["size"] + 1 or s["bbox"][3] - s["bbox"][1] > 1.6 * r["size"] for s in ink if "√" in s["text"])) or any(s["size"] > max(r["size"], mk.body) + 2 for s in ink) or any(re.search("CMEX|MTEX|Extension", s["font"], re.I) for s in ink)
            if hard and all(drawn_letters(s) for s in ink) and len(text.strip()) <= 2:
                box = (min(s["bbox"][0] for s in ink), min(s["bbox"][1] for s in ink), max(s["bbox"][2] for s in ink), max(s["bbox"][3] for s in ink))
                out.append(mk.glyph(r["page"], box, max(sp["origin"][1] for sp in ink), max(sp["size"] for sp in ink)))          # (one symbol, at the size of the text around it)
            elif hard:
                box = (min(s["bbox"][0] for s in ink), min(s["bbox"][1] for s in ink), max(s["bbox"][2] for s in ink), max(s["bbox"][3] for s in ink))
                out.append(mk.formula(r["page"], box, keep={id(s) for s in r["spans"] if s in ink or (is_math(s) and box[0] - 1 <= s["bbox"][0] and s["bbox"][2] <= box[2] + 1)}))
            else:
                h, last = [], None
                for s in run:
                    t = clean(s["text"])
                    core = t.strip()
                    if not core:
                        h.append(" ")
                        last = None
                        continue
                    piece = esc(core)
                    if core.isalpha() or (is_italic(s) and any(c.isalpha() for c in core)):
                        piece = f"<i>{piece}</i>"
                    sc = script_of(s, r, mk.body)
                    if sc == "sup":
                        piece = f"<sup>{piece}</sup>"
                    elif sc == "sub":
                        piece = f"<sub>{piece}</sub>"
                    elif sc == "flat":
                        piece = f"<sup>{piece}</sup>" if core[:1].isdigit() and h else f"<sub>{piece}</sub>"
                    # a superscript and a subscript printed one above the other (ρ with xy below and THE above): stacked
                    if last and piece[:5] in ("<sup>", "<sub>") and last[1][:5] in ("<sup>", "<sub>") and piece[:5] != last[1][:5]                             and min(s["bbox"][2], last[0]["bbox"][2]) - max(s["bbox"][0], last[0]["bbox"][0]) > .3 * min(s["bbox"][2] - s["bbox"][0], last[0]["bbox"][2] - last[0]["bbox"][0]):
                        up, down = (piece, last[1]) if piece[:5] == "<sup>" else (last[1], piece)
                        h[-1] = f'<span class="ss">{up}{down}</span>'
                        last = None
                        continue
                    h.append(piece)
                    last = (s, piece)
                inner = "".join(h)
                out.append((" " if inner[:1] == " " and out and not out[-1].endswith(" ") else "") + '<span class="m">' + inner.strip() + "</span>" + (" " if inner[-1:] == " " else ""))
            if lead_sp and at and not out[at - 1].endswith(" ") and not out[at].startswith(" "):
                out.insert(at, " ")
            if trail_sp and not out[-1].endswith(" "):
                out.append(" ")
            mk.tail += text
        run = []

    prev_math = False
    last_x = None
    for s in r["spans"]:
        t = s["text"]
        if s.get("img"):
            end_run()
            if last_x is not None and s["bbox"][0] - last_x > .11 * r["size"] and out and not out[-1].endswith(" "):
                out.append(" ")
            out.append(mk.formula(r["page"], s["bbox"], raster=True))
            mk.tail += "x"
            last_x = s["bbox"][2]
            continue
        if t.strip():
            if last_x is not None and s["origin"][0] - last_x > .11 * s["size"] and not t[:1].isspace() and not mk.tail.endswith((" ", "(", "[", "{", "/")) and t.strip()[:1] not in ",.;:)]}" and script_of(s, r, mk.body) == "":
                if run and not is_math(s):
                    end_run()
                if run:
                    run.append({**s, "text": " ", "chars": []})
                else:
                    out.append(" ")
                    mk.tail += " "
            last_x = s["bbox"][2]
        if not t.strip():
            if run:
                run.append(s)
            else:
                out.append(" ")
                mk.tail += " "
            continue
        math = is_math(s) or s.get("stack") or (s["size"] < r["size"] - .8 and prev_math and not t.strip()[:1].isdigit()) or (prev_math and len(t.strip()) <= 2 and script_of(s, r, mk.body) in ("sup", "sub"))
        if math and is_math(s) and len(run) == 0 and clean(t).strip() in ("(", ")", ",", ".", ";", ":", "–", "-", "%", "−", "+", "="):
            math = False
        if math:
            run.append(s)
            prev_math = True
            continue
        end_run()
        if prev_math and t[:1].isspace() and out and not out[-1].endswith(" "):
            out.append(" ")
        prev_math = False
        t = clean(t)
        lead, trail = " " if t[:1].isspace() else "", " " if t[-1:].isspace() else ""
        core = t.strip()
        if bad_text(core):
            out.append(lead)
            word = ""
            for c in s["chars"]:
                ch = clean(c["c"])
                if bad_text(ch):
                    if word:
                        out.append(esc(word)); word = ""
                    if "".join(out).strip():      # (a mark before a heading or list means nothing)
                        out.append(mk.glyph(r["page"], c["bbox"], c["origin"][1], s["size"]))
                else:
                    word += ch
            out.append(esc(word) + trail)
            mk.tail += lead + "x" + trail
            continue
        def dress(x):
            x = esc(x)
            if is_italic(s) and any(c.isalpha() for c in x):
                x = f"<i>{x}</i>"
            if is_bold(s):
                x = f"<b>{x}</b>"
            return x
        sc = script_of(s, r, mk.body)
        if sc == "flat":
            out.append(lead)
            for text, kind in flat_scripts(core, mk.tail, mk.nrefs):
                if kind == "cite" and cite:
                    out.append(f"<sup>{cite_html(text)}</sup>")
                elif kind in ("sup", "cite"):
                    out.append(f"<sup>{esc(text)}</sup>")
                elif kind == "sub":
                    out.append(f"<sub>{esc(text)}</sub>")
                else:
                    out.append(dress(text))
                mk.tail += text
            out.append(trail)
            mk.tail += trail
            continue
        if sc == "sup":
            real = re.fullmatch(r"\d+(?:\s*[,–-]\s*\d+)*,?", core)
            if cite and real and good_citation(core, mk.nrefs) and not re.search(r"[\d)−\-+×^]\s*$", mk.tail) and not UNIT_TAIL.search(mk.tail):
                out.append(f"{lead}<sup>{cite_html(core)}</sup>{trail}")
            else:
                out.append(f"{lead}<sup>{dress(core)}</sup>{trail}")
        elif sc == "sub":
            out.append(f"{lead}<sub>{dress(core)}</sub>{trail}")
        else:
            out.append(lead + dress(core) + trail)
        mk.tail += lead + core + trail
        mk.tail = mk.tail[-40:]
    end_run()
    return "".join(out)


# ---------------- pages → blocks of text
def is_display(r, x0, x1, body):
    """An equation on its own line."""
    ink = [sp for sp in r["spans"] if sp["text"].strip()]
    if ink and all(sp.get("img") or re.fullmatch(r"[\s.,;:()\d]*", sp["text"]) for sp in ink) and any(sp.get("img") for sp in ink):
        return True
    width = max(x1 - x0, 1)
    text = r["text"]
    words = [w for w in re.findall(r"[A-Za-z]{4,}", text)]
    numbered = re.search(r"(?:\(\s*\d+[a-z]?\s*\)|\[\s*\d+[a-z]?\s*\]|Eq\.?\s*\d+)\s*$", text)
    if re.fullmatch(r"\(\s*\d+[a-z]?\s*\)", text) and r["x1"] > x1 - 12 and r["x0"] > x0 + .5 * width:
        return True
    mathy = r["math"] > .25 or any(c in MATH_CHARS for c in text)
    if r.get("eqgroup") and len(words) <= (6 if numbered else 4) and not prose(r):
        return True
    if not mathy or len(words) > (6 if numbered else 3) or (r["size"] > body + 1.5 and any(len(w) >= 5 for w in words)):
        return False
    left, right = r["x0"] - x0, x1 - r["x1"]
    centered = left > .05 * width and (right > .05 * width or numbered)
    if text.endswith(".") and not numbered and len(words) > 1:
        return False
    return centered and r["x1"] - r["x0"] < .97 * width + 1 if not numbered else True


def is_heading(r, body, gap_ok):
    t = re.sub(r"^[\W_]+(?=\w)", "", r["text"]) if not re.match(r"^[\[(]", r["text"]) else r["text"]
    if not t or len(t) > 130 or len(t.split()) > 18 or t[-1] in ",;" or t[0].islower() or r["math"] > .3:
        return None
    if HEAD_KNOWN.match(t):
        return "known"
    if not gap_ok:
        return None
    letters = [c for c in t if c.isalpha()]
    if len(letters) < 3 or sum(c.isdigit() for c in t) > .25 * len(t) and not re.match(r"^\d+(?:\.\d+)*\.?\s+[A-Z]", t):
        return None
    upper = sum(c.isupper() for c in letters) / len(letters)
    numbered = re.match(r"^(?:\d+(?:\.\d+)*\.?|[IVXL]+\.|[A-Z]\.)\s+\S", t)
    if t.endswith(".") and not numbered and len(t.split()) > 6:
        return None
    if r["size"] > body + .7 and r["chars"] >= 3:
        return "big"
    if r["bold"] > .85 and (numbered or len(t.split()) <= 14):
        return "bold"
    if upper > .85 and len(t.split()) >= 1 and len(letters) >= 5:
        return "caps"
    if numbered and r["size"] >= body and re.match(r"^\d+(?:\.\d+)*\.?\s+[A-Z]", t) and len(t.split()) <= 9 and not t.endswith((".", ":")) and re.match(r"^\d+(?:\.\d+)+", t):
        return "num"
    return None


def level_of(text, style, size, body, big_sizes):
    m = re.match(r"^(\d+(?:\.\d+)*)", text)
    if m:
        return min(m.group(1).count(".") + 1, 3)
    if re.match(r"^[IVXL]+\.\s", text):
        return 1
    if re.match(r"^[A-Z]\.\s", text):
        return 2
    if style == "known":
        return 1
    if big_sizes and size >= big_sizes[0] - .2:
        return 1
    return 2


def find_tables(leaf, x0, x1, body):
    """Stretches of lines cut into several cells: {index of first line: index after the last}."""
    cells = []
    for i, r in enumerate(leaf):
        same = any(q is not r and min(q["y1"], r["y1"]) - max(q["y0"], r["y0"]) > .5 * min(q["y1"] - q["y0"], r["y1"] - r["y0"]) for q in leaf[max(0, i - 8):i + 9])
        cells.append(same and r["chars"] < 60 and not is_display(r, x0, x1, body)      # (an equation and its number aren't cells,
                     and len(re.findall(r"[^\W\d_]{2,}", r["text"])) < 5)                # nor is a line of prose beside another)
    # (a table's lines hold numbers: the spread-out words of justified lines aren't cells)
    if sum(1 for r, c in zip(leaf, cells) if c and re.search(r"\d", r["text"])) < .3 * max(sum(cells), 1):
        cells = [False] * len(leaf)
    out, i = {}, 0
    while i < len(leaf):
        if cells[i]:
            j = i
            while j + 1 < len(leaf) and (cells[j + 1] or (j + 2 < len(leaf) and cells[j + 2])) and leaf[j + 1]["y0"] - leaf[j]["y1"] < 2.2 * body:
                j += 1
            if j - i >= 5:
                out[i] = j + 1
                i = j + 1
                continue
        i += 1
    return out


def prose(r):
    return len(re.findall(r"[A-Za-z]{3,}", r["text"])) >= 4 and r["math"] < .3


def mathish(r, body):
    """Set in math type, or math symbols with hardly any words: not a page number, a heading or a line of a list."""
    words = len(re.findall(r"[A-Za-z]{3,}", r["text"]))
    if any(sp.get("img") for sp in r["spans"]) and words <= 2:
        return True
    return words <= 2 and (r["math"] > .25 or any(c in MATH_CHARS or c in "∫∑∏√∂" for c in r["text"]) or (r["chars"] <= 4 and r["math"] > 0))


def split_lead(r, x0, x1, body):
    """A word or two at the margin, then a wide gap, then something set in the middle (an equation): apart."""
    ink = sorted((sp for sp in r["spans"] if sp["text"].strip()), key=lambda sp: sp["bbox"][0])
    for k in range(1, min(len(ink), 6)):
        gap = ink[k]["bbox"][0] - ink[k - 1]["bbox"][2]
        lead = "".join(sp["text"] for sp in ink[:k]).strip()
        if gap > 2.5 * body and ink[k - 1]["bbox"][2] < x0 + .3 * (x1 - x0) and len(lead.split()) <= 2 and len(lead) <= 14:
            a = {"spans": ink[:k], "x0": ink[0]["bbox"][0], "x1": ink[k - 1]["bbox"][2], "y0": r["y0"], "y1": r["y1"], "page": r["page"]}
            b = {"spans": ink[k:], "x0": ink[k]["bbox"][0], "x1": r["x1"], "y0": r["y0"], "y1": r["y1"], "page": r["page"]}
            finish_row(a); finish_row(b)
            if mathish(b, body) or b.get("eqgroup") or r.get("eqgroup"):
                b["eqgroup"] = r.get("eqgroup")
                return [a, b]
            return [r]
    return [r]


def gather_equations(leaf, body):
    """A displayed equation is often several lines of type (a tall integral sign, limits, a fraction's top and bottom,
    its number off to the right): everything in its band that isn't a sentence becomes one line."""
    out, used = [], set()
    for i, r in enumerate(leaf):
        if id(r) in used:
            continue
        if not mathish(r, body) or prose(r):
            out.append(r)
            continue
        group = [r]
        y0, y1 = tight(r["spans"]) or (r["y0"], r["y1"])
        x0, x1 = r["x0"], r["x1"]
        grew = True
        while grew:
            grew = False
            for q in leaf:
                if id(q) in used or any(q is g for g in group) or prose(q) or y1 - y0 > 8 * body:
                    continue
                if q["x0"] > x1 + 3 * body or q["x1"] < x0 - 3 * body:      # (side by side, not across a column gap)
                    continue
                q0, q1 = tight(q["spans"]) or (q["y0"], q["y1"])
                overlap = min(y1, q1) - max(y0, q0)
                close = q0 < y1 + .35 * body and q1 > y0 - .35 * body
                if overlap > .2 * body or (close and (mathish(q, body) or q["chars"] <= 6)):
                    group.append(q); y0, y1 = min(y0, q0), max(y1, q1); x0, x1 = min(x0, q["x0"]), max(x1, q["x1"]); grew = True
        if len(group) > 1:
            used.update(id(g) for g in group)
            m = merge_rows(sorted(group, key=lambda g: (g["y0"], g["x0"])))
            m["eqgroup"] = True
            out.append(m)
        else:
            out.append(r)
    keep = [r for r in out if id(r) not in used or len(r["spans"]) and r not in leaf]
    return sorted(keep, key=lambda r: (r["y0"], r["x0"]))


def build_blocks(mk, pages):
    """Paragraphs, headings and equations in reading order, across columns and pages."""
    blocks, cur = [], None
    body = mk.body

    def flush():
        nonlocal cur
        if cur:
            blocks.append(cur)
        cur = None

    def row_item(r):
        return {"rows": [r]}

    # a scanned book set with hanging indents throughout (a dictionary, a cookbook): counted over the whole book,
    # as a page of one-line entries alone doesn't show it
    hanging, inset, outset = False, 0, 0
    if OCR:
        for p in pages:
            for leaf in p["leaves"]:
                if len(leaf) >= 6:
                    left = sorted(r["x0"] for r in leaf)[len(leaf) // 10]
                    inset += sum(1 for r in leaf if left + .55 * body < r["x0"] < left + 3 * body)
                    outset += sum(1 for r in leaf if r["x0"] <= left + 2)
        hanging = inset > 1.1 * outset > 20
    for p in pages:
        for leaf in p["leaves"]:
            if not leaf:
                continue
            leaf = gather_equations(leaf, body)
            xs = sorted(r["x0"] for r in leaf)
            lx0, lx1 = (xs[len(xs) // 10] if xs else 0), max((r["x1"] for r in leaf), default=0)
            leaf = [q for r in leaf for q in (split_lead(r, lx0, lx1, body) if mathish(r, body) or r.get("eqgroup") or any(c in MATH_CHARS for c in r["text"]) else [r])]
            xs0 = Counter(round(r["x0"]) for r in leaf)
            x0 = min(r["x0"] for r in leaf) if len(leaf) < 3 else min(a for a, n in xs0.items() if n >= max(2, .1 * len(leaf))) if any(n >= max(2, .1 * len(leaf)) for n in xs0.values()) else min(r["x0"] for r in leaf)
            # entries set with a hanging indent (a dictionary, a cookbook): the first line juts out, the rest are in
            hang = hanging
            x1 = max(r["x1"] for r in leaf)
            gaps = [b["base"] - a["base"] for a, b in zip(leaf, leaf[1:]) if 0 < b["base"] - a["base"] < 3 * body]      # (baselines: a tall symbol doesn't move a line)
            lead = statistics.median(gaps) if gaps else body * 1.25
            i = 0
            prev = None
            tables = find_tables(leaf, x0, x1, body)
            while i < len(leaf):
                r = leaf[i]
                gap = r["base"] - prev["base"] if prev else None
                if i in tables:
                    part = leaf[i:tables[i]]
                    flush()
                    blocks.append({"type": "eq", "rows": part, "box": (min(q["x0"] for q in part), min(q["y0"] for q in part), max(q["x1"] for q in part), max(q["y1"] for q in part)), "page": r["page"], "number": None, "text": " ".join(q["text"] for q in part)})
                    prev = part[-1]
                    i = tables[i]
                    continue
                if any(sp.get("fig") for sp in r["spans"]):
                    flush()
                    blocks.append({"type": "pic", "rows": [r], "box": (r["x0"], r["y0"], r["x1"], r["y1"]), "page": r["page"], "text": ""})
                    prev = r
                    i += 1
                    continue
                # an equation: its lines together (a fraction's parts can be separate lines)
                if is_display(r, x0, x1, body):
                    j, parts = i + 1, [r]
                    while j < len(leaf) and (leaf[j]["y0"] - parts[-1]["y1"] < .5 * body) and len(re.findall(r"[A-Za-z]{3,}", leaf[j]["text"])) < 4 and (is_display(leaf[j], x0, x1, body) or (leaf[j]["size"] < body - .5 and leaf[j]["x1"] - leaf[j]["x0"] < .6 * (x1 - x0))):
                        parts.append(leaf[j]); j += 1
                    whole = merge_rows(parts) if len(parts) > 1 else r
                    num = re.search(r"\(\s*(\d+(?:\.\d+)*[a-z]?)\s*\)\s*$|Eq\.?\s*(\d+(?:\.\d+)*[a-z]?)\s*$", whole["text"])
                    # the equation's number, set off to the right, stays text: the picture is just the equation
                    ink = [sp for sp in whole["spans"] if sp["text"].strip()]
                    label = [sp for sp in ink if re.fullmatch(r"\(?\s*(?:Eq\.?\s*)?\d+(?:\.\d+)*[a-z]?\s*\)?[.,]?", sp["text"].strip()) and sp["bbox"][0] > (whole["x0"] + whole["x1"]) / 2]
                    body_spans = [sp for sp in ink if not any(sp is l for l in label)] if label else ink
                    if label and body_spans and max(sp["bbox"][2] for sp in body_spans) < min(sp["bbox"][0] for sp in label) - 6:
                        whole = dict(whole, x1=max(sp["bbox"][2] for sp in body_spans), x0=min(sp["bbox"][0] for sp in body_spans))
                        eqn = " ".join(sp["text"].strip() for sp in label)
                    else:
                        eqn = None
                    flush()
                    blocks.append({"type": "eq", "rows": parts, "box": (whole["x0"], whole["y0"], whole["x1"], whole["y1"]), "page": whole["page"], "number": (num.group(1) or num.group(2)) if num else None, "label": eqn, "text": whole["text"]})
                    prev = parts[-1]
                    i = j
                    continue
                gap_ok = prev is None or gap is None or gap > lead * 1.12 or r["size"] > body + .7
                style = is_heading(r, body, gap_ok)
                if style and style != "known":
                    run = 0
                    for q in leaf[i:i + 12]:
                        if abs(q["size"] - r["size"]) < .3 and abs(q["bold"] - r["bold"]) < .2:
                            run += len(q["text"].split())
                        else:
                            break
                    nxt = leaf[i + 1] if i + 1 < len(leaf) else None
                    if run > 26 or (nxt and nxt["text"][:1].islower() and r["x1"] > x1 - .1 * (x1 - x0) and not is_heading(nxt, body, True)):
                        style = None
                if style:
                    # a heading's next line, in the same type
                    parts = [r]
                    j = i + 1
                    while j < len(leaf) and leaf[j]["y0"] - parts[-1]["y1"] < .8 * body and abs(leaf[j]["size"] - r["size"]) < .3 and abs(leaf[j]["bold"] - r["bold"]) < .2 and is_heading(leaf[j], body, True) and style != "known":
                        parts.append(leaf[j]); j += 1
                    if sum(len(q["text"].split()) for q in parts) <= 24:
                        flush()
                        blocks.append({"type": "h", "rows": parts, "style": style, "size": r["size"], "page": r["page"], "text": re.sub(r"\s+", " ", re.sub(r"^[^\w(\[]+", "", " ".join(q["text"] for q in parts)).replace("￼", " ")).strip().rstrip(" :")})
                        prev = parts[-1]
                        i = j
                        continue
                m = RUN_IN.match(r["text"])
                if m and r["spans"] and (is_bold(next(s for s in r["spans"] if s["text"].strip())) or r["text"][:len(m.group(1))].isupper()):
                    flush()
                    blocks.append({"type": "h", "rows": [], "style": "known", "size": r["size"], "page": r["page"], "text": m.group(1).strip()})
                    r = dict(r)
                    r["strip"] = m.end()
                    cur = {"type": "p", "rows": [r], "page": r["page"], "size": r["size"]}
                    prev = r
                    i += 1
                    continue
                fresh = cur is None
                if not fresh and prev is not None:
                    last = cur["rows"][-1]
                    short = last["x1"] < x1 - .14 * (x1 - x0) and re.search(r"[.?!:)\]]\W*$|\d$", last["text"])
                    indent = (r["x0"] <= x0 + 2 and last["x0"] > x0 + .55 * body) if hang else (r["x0"] > x0 + .55 * body and last["x0"] <= x0 + 2)
                    if gap > lead * 1.4 or short or indent or abs(r["size"] - cur["size"]) > 1.1:
                        fresh = True
                elif not fresh:     # the first line of a column or page: does the paragraph carry on?
                    last = cur["rows"][-1]
                    if re.search(r"[.?!:]\W*$", last["text"]) and (r["x0"] > x0 + .55 * body or r["text"][:1].isupper()) or abs(r["size"] - cur["size"]) > 1.1                             or OCR and not hang and r["x0"] > x0 + .55 * body and last["x1"] < x1 - .14 * (x1 - x0):      # (a scan: its full stop may be in a picture)
                        fresh = True
                if fresh:
                    flush()
                    cur = {"type": "p", "rows": [], "page": r["page"], "size": r["size"]}
                cur["rows"].append(r)
                prev = r
                i += 1
    flush()
    return blocks


def join_rows(mk, rows, cite):
    """Lines into a paragraph, taking back the hyphens that only ended a line."""
    out = ""
    plain = ""
    mk.tail = ""
    for r in rows:
        h = row_html(mk, r, cite)
        if "strip" in r:
            h = re.sub(r"^\s*(?:<[bi]>)*\s*[^<:.]*[:.]\s*(?:</[bi]>)*\s*", "", h, count=1)
        t = r["text"]
        if plain.endswith(("-", "‐")) and re.match(r"[a-z]", t):
            a = re.search(r"([A-Za-z]+)[-‐]$", plain)
            b = re.match(r"[a-z]+", t)
            joined = (a.group(1) + b.group()).lower() if a and b else ""
            whole = (a.group(1) + "-" + b.group()).lower() if a and b else ""
            if rows[rows.index(r) - 1].get("soft"):
                out = out.rstrip()
            elif not mk.keep_hyphens and (joined in mk.words or whole not in mk.words):
                out = re.sub(r"[-‐]((?:</[a-z]+>)*)\s*$", r"\1", out)
            else:
                out = out.rstrip()
            out += h.lstrip()
        else:
            out = out.rstrip() + " " + h.lstrip() if out else h
        plain = t
    return out


def balance(h):
    """Tags closed in the order they were opened, strays dropped (pieces of a line can be cut away after markup)."""
    out, stack = [], []
    for part in re.split(r"(<[^>]+>)", h):
        m = re.fullmatch(r"<(/?)(b|i|sup|sub|span|a)\b[^>]*>", part)
        if not m or part.endswith("/>"):
            out.append(part)
        elif not m.group(1):
            stack.append(m.group(2))
            out.append(part)
        elif m.group(2) in stack:
            while stack[-1] != m.group(2):
                out.append(f"</{stack.pop()}>")
            stack.pop()
            out.append(part)
    return "".join(out) + "".join(f"</{t}>" for t in reversed(stack))


def tidy(h):
    h = re.sub(r"</(i|b)>(\s*)<\1>", r"\2", h)
    h = re.sub(r"\s+", " ", h)
    h = re.sub(r"\s+([̀-ͯ])", r"\1", h)
    h = re.sub(r"\s+([,.;:)\]])(?![^<]*>)", r"\1", h)
    # "…))approaching": a word run straight onto a closing bracket (the PDF's space lost)
    h = re.sub(r"(\)(?:</span>)?)(?=[a-z]{4,}\b)(?![^<]*>)", r"\1 ", h)
    # a bar over letters (an antiparticle): one overline across them, which every reader draws cleanly
    h = re.sub(r"((?:[^\W_]̅)+)", lambda m: '<span class="ov">' + m.group(1).replace("̅", "") + "</span>", h)
    return balance(h.strip())


# ---------------- references
def split_references(mk, rows):
    """{number: rows}, or a plain list when the references aren't numbered."""
    numbered = {}
    pat = re.compile(r"^\s*(?:\[(\d{1,4})\]|\((\d{1,4})\)|(\d{1,4})[.)]\s*(?=[^\W\d_(])|(\d{1,4})\s+(?=[A-Z]))")
    next_n, cur = 1, None
    hits = sum(1 for r in rows if (m := pat.match(r["text"])) and m.group(m.lastindex))
    if rows and hits >= max(3, .1 * len(rows)):
        for r in rows:
            m = pat.match(r["text"])
            n = int(m.group(m.lastindex)) if m else None
            if n is not None and (n == next_n or (cur is None and n < 8) or (next_n < n <= next_n + 25 and r["x0"] <= rows_left(rows, r) + 2)):
                cur = n
                numbered[n] = [r]
                next_n = n + 1
            elif cur is not None:
                numbered[cur].append(r)
        if len(numbered) >= 3:
            return numbered, []
    # no numbers: a new item where a line starts further left than the one before, or after a sentence's end and a gap
    items, cur = [], []
    x_mode = Counter(round(r["x0"]) for r in rows).most_common(1)[0][0] if rows else 0
    for r in rows:
        starts = not cur or (abs(r["x0"] - x_mode) > 200) or (r["x0"] < cur[-1]["x0"] - 4) or (re.search(r"[.)]$", cur[-1]["text"]) and r["y0"] - cur[-1]["y1"] > 1.5)
        if starts and cur:
            items.append(cur); cur = []
        cur.append(r)
    if cur:
        items.append(cur)
    return {}, items


def rows_left(rows, r):
    return min(q["x0"] for q in rows if abs(q["x0"] - r["x0"]) < 40 and q["page"] == r["page"])


def plain_of(h):
    return re.sub(r"<[^>]+>", "", h)


# ---------------- mentions become links
LABEL = r"(Figs?\.?|Figures?|FIGS?\.?|FIGURES?|Tables?|TABLES?|Tabs?\.|Schemes?|SCHEMES?|Charts?|Extended Data Figs?\.?)"
NUM = r"(S?\d+(?:\.\d+)*[A-Za-z]?|[IVX]+)"


def key_of(kind_word, num):
    w = kind_word.lower()
    kind = "table" if w.startswith("tab") else "scheme" if w.startswith("sch") else "chart" if w.startswith("cha") else "fig"
    return kind, re.sub(r"(?<=\d)[a-z]$", "", num).upper()


def link_mentions(h, known, seen, file, eqs):
    def one(kind, raw, text):
        key = (kind, re.sub(r"(?<=\d)[a-zA-Z]$", "", raw).upper())
        f = known.get(key)
        if not f:
            return text
        lst = seen.setdefault(key, [])
        aid = f"m{f}-{len(lst) + 1}"
        lst.append((file, aid))
        return f'<a class="figlink" id="{aid}" href="{f}.xhtml">{text}</a>'

    pat = re.compile(rf"(?<![\w/]){LABEL}((?:</?[bi]>)*\s*(?:</?[bi]>)*){NUM}(?![\w])((?:(?:</?[bi]>)*(?:\s*,\s*|\s+and\s+|\s*[–-]\s*|\s*&\s*)(?:</?[bi]>)*{NUM}(?![\w]))*)")
    out, pos = [], 0
    for m in pat.finditer(h):
        # inside a tag's attributes? leave it
        if h.rfind("<", 0, m.start()) > h.rfind(">", 0, m.start()):
            continue
        kind = key_of(m.group(1), m.group(3))[0]
        out.append(h[pos:m.start()])
        first = m.group(1) + m.group(2) + m.group(3)
        if "<" in m.group(2):
            out.append(m.group(1) + m.group(2) + one(kind, m.group(3), m.group(3)))
        else:
            out.append(one(kind, m.group(3), first))
        rest = m.group(4) or ""
        if rest:
            rest = re.sub(NUM + r"(?![\w])", lambda q: one(kind, q.group(1), q.group(1)), rest)
            out.append(rest)
        pos = m.end()
    out.append(h[pos:])
    h = "".join(out)
    # equations by number
    def eq_link(m):
        if h.rfind("<", 0, m.start()) > h.rfind(">", 0, m.start()):
            return m.group(0)
        z = eqs.get(m.group(2))
        return f'<a class="figlink" href="eq{z}.xhtml">{m.group(0)}</a>' if z else m.group(0)
    return re.sub(r"\b(Eqs?\.?|Equations?|eqs?\.?)\s*\(?(\d+[a-z]?)\)?", eq_link, h)


def link_brackets(h, nrefs):
    def rep(m):
        if not good_or_list(m.group(1), nrefs):
            return m.group(0)
        return "[" + cite_html(m.group(1)) + "]"
    return re.sub(r"\[(\d{1,4}(?:\s*[,–-]\s*\d{1,4})*)\](?![^<]*>)", rep, h)


def good_or_list(run, nrefs):
    nums = [int(x) for x in re.findall(r"\d+", run)]
    return nums and all(1 <= n <= nrefs for n in nums)


# ---------------- writing the EPUB
def css(eq):
    return f""":root{{--eq:{eq}}}
body{{margin:0 3%;line-height:1.45;font-family:serif;overflow-wrap:break-word}}
h1{{font-size:1.45em;line-height:1.2;margin:.4em 0}}h2{{font-size:1.25em;line-height:1.25;margin:1.3em 0 .5em}}h3{{font-size:1.08em;margin:1.1em 0 .4em}}h4{{font-size:1em;margin:1em 0 .3em}}
p{{margin:0 0 .75em;text-align:left;-webkit-hyphens:auto;hyphens:auto;widows:2;orphans:2}}
.m,.cap,.refs,a,h1,h2,h3,h4{{-webkit-hyphens:manual;hyphens:manual}}
.authors{{font-size:.9em}}.addr{{font-size:.78em;margin:0 0 .25em}}.note{{font-size:.8em;margin:0 0 .5em}}
sup,sub{{font-size:.68em;line-height:0}}.ss{{display:inline-flex;flex-direction:column;vertical-align:-.45em;font-size:.68em;line-height:1.05;margin-left:.03em}}.ss sup,.ss sub{{font-size:1em;line-height:1.05;vertical-align:0}}.ov{{text-decoration:overline}}
a{{color:inherit}}a.figlink{{font-weight:bold;text-decoration:underline}}a.cit{{text-decoration:underline}}a.zl{{text-decoration:none}}
.m{{font-size:{eq * .88:.2f}em;font-size:calc(var(--eq)*.88em)}}.m sub,.m sup{{font-size:.82em}}
img.gl{{vertical-align:middle}}
img.im{{font-size:{eq:.2f}em;font-size:calc(var(--eq)*1em);vertical-align:middle;max-width:100%}}
.eq{{text-align:center;margin:.7em 0 1em;overflow:hidden;line-height:1.2}}.eqn{{font-size:.85em;white-space:nowrap;padding-left:.6em}}.eq img{{font-size:{eq:.2f}em;font-size:calc(var(--eq)*1em);max-width:100%;height:auto}}
.zoom{{text-align:center;margin:12% 0 1em}}.zoom img{{width:100%;height:auto}}
.figure{{text-align:center;margin:0}}.figure.inflow{{margin:.8em 0}}.figure.inflow img{{max-height:60vh;width:auto;max-width:100%}}.figure img{{width:100%;max-height:80vh;object-fit:contain}}
.side{{text-align:center;margin:0}}.side img{{max-width:100%;max-height:96vh;object-fit:contain}}
.cap{{font-size:.92em;text-align:left;margin:.6em 0}}
.back{{margin-top:1em;line-height:2.4}}.back a{{display:inline-block;min-width:2.2em;text-align:center;border:1px solid;margin:0 .25em .25em 0;padding:0 .3em;text-decoration:none}}
.refs{{padding-left:0;list-style:none}}.refs li{{margin:0 0 .6em;padding-left:2em;text-indent:-2em}}
.scan{{margin:0 0 .4em;text-align:center}}.scan img{{width:100%;height:auto}}
"""


def page_xhtml(title, body):
    return f'<?xml version="1.0" encoding="utf-8"?>\n<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="en" lang="en"><head><title>{esc(title)}</title><link rel="stylesheet" href="style.css" type="text/css"/></head><body class="babel-paper">{body}</body></html>'


def write_epub(out, title, author, files, images, order, extra, toc, eq):
    uid = str(uuid.uuid4())

    def nav_list(items):
        return "<ol>" + "".join(f'<li><a href="{esc(h)}">{esc(t)}</a>' + (nav_list(s) if s else "") + "</li>" for t, h, s in items) + "</ol>"

    count = [0]
    def points(items):
        s = ""
        for t, h, sub in items:
            count[0] += 1
            s += f'<navPoint id="n{count[0]}" playOrder="{count[0]}"><navLabel><text>{esc(t)}</text></navLabel><content src="{esc(h)}"/>{points(sub)}</navPoint>'
        return s

    nav = page_xhtml("Contents", f'<nav epub:type="toc" id="toc"><h2>Contents</h2>{nav_list(toc)}</nav>')
    ncx = f'<?xml version="1.0" encoding="utf-8"?>\n<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1"><head><meta name="dtb:uid" content="{uid}"/></head><docTitle><text>{esc(title)}</text></docTitle><navMap>{points(toc)}</navMap></ncx>'
    manifest = ['<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>', '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>', '<item id="css" href="style.css" media-type="text/css"/>']
    ids = {}
    for i, k in enumerate(order + extra):
        ids[k] = f"f{i}"
        manifest.append(f'<item id="f{i}" href="{k}" media-type="application/xhtml+xml"/>')
    for i, k in enumerate(images):
        manifest.append(f'<item id="i{i}" href="images/{k}" media-type="image/{"jpeg" if k.endswith("jpg") else "svg+xml" if k.endswith("svg") else "png"}"/>')
    spine = "".join(f'<itemref idref="{ids[k]}"/>' for k in order) + "".join(f'<itemref idref="{ids[k]}" linear="no"/>' for k in extra)
    who = f"<dc:creator>{esc(author)}</dc:creator>" if author else ""
    opf = f'<?xml version="1.0" encoding="utf-8"?>\n<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="id"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="id">urn:uuid:{uid}</dc:identifier><dc:title>{esc(title)}</dc:title>{who}<dc:language>en</dc:language><meta property="dcterms:modified">2026-01-01T00:00:00Z</meta><meta name="babel-converter" content="{VERSION}"/></metadata><manifest>{"".join(manifest)}</manifest><spine toc="ncx">{spine}</spine></package>'
    part = out + ".part"
    with zipfile.ZipFile(part, "w") as z:
        z.writestr("mimetype", "application/epub+zip", zipfile.ZIP_STORED)
        z.writestr("META-INF/container.xml", '<?xml version="1.0"?><container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>', zipfile.ZIP_DEFLATED)
        z.writestr("OEBPS/content.opf", opf, zipfile.ZIP_DEFLATED)
        z.writestr("OEBPS/nav.xhtml", nav, zipfile.ZIP_DEFLATED)
        z.writestr("OEBPS/toc.ncx", ncx, zipfile.ZIP_DEFLATED)
        z.writestr("OEBPS/style.css", css(eq), zipfile.ZIP_DEFLATED)
        for k, v in files.items():
            z.writestr("OEBPS/" + k, v, zipfile.ZIP_DEFLATED)
        for k, v in images.items():
            z.writestr("OEBPS/images/" + k, v, zipfile.ZIP_DEFLATED if k.endswith(".svg") else zipfile.ZIP_STORED)      # (SVG is text: it packs small)
    os.replace(part, out)


# ---------------- a scan (or text whose letters can't be read): Tesseract reads the page, then it's handled like any
# other PDF. Words it isn't sure of, and everything else inked on the page, stay as pictures of the page itself.
OCR = {}            # page number → {"blocks": text read as MuPDF would give it, "images": ink the reading left out}
OCR_DPI = 300
NARROW, WIDE = set("il.,:;'!|`ftjrI()[]"), set("mwMW")


def tesseract():
    import shutil
    for p in (os.environ.get("TESSERACT"), shutil.which("tesseract"), r"C:\Program Files\Tesseract-OCR\tesseract.exe",
              r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe", os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe")):
        if p and os.path.isfile(p):
            return p
    return None


def page_blocks(pg, flags=None):
    if pg.number in OCR:
        import copy
        return copy.deepcopy(OCR[pg.number]["blocks"])
    return pg.get_text("rawdict", flags=flags)["blocks"] if flags is not None else pg.get_text("rawdict")["blocks"]


def page_images(pg):
    return OCR[pg.number]["images"] if pg.number in OCR else pg.get_image_info()


def ocr_sizes(words):
    """Type sizes the words' heights point to (a word's box runs from its tallest letter to its lowest)."""
    def est(t, h):
        up = any(c.isupper() or c.isdigit() or c in "bdfhklt'\"()[]{}/|!?" for c in t)
        down = any(c in "gjpqy,;()[]{}|" for c in t)
        return h / (.98 if up and down else .72 if up else .7 if down else .48)
    sure = [w for w in words if w["keep"]]
    return [est(w["text"], w["y1"] - w["y0"]) for w in sure if len(w["text"]) > 1 and any(c.isalpha() for c in w["text"])] or [est(w["text"], w["y1"] - w["y0"]) for w in sure]


def ocr_line(words, size):
    """A line Tesseract read, as one MuPDF line: a span for each run of words it was sure of."""
    sure = [w for w in words if w["keep"]]
    if not sure:
        return None
    flat = [w["y1"] for w in sure if not any(c in "gjpqy,;()[]{}|Q@$/" for c in w["text"])]
    base = statistics.median(flat) if flat else statistics.median(w["y1"] for w in sure) - .21 * size
    top, bot = base - .78 * size, base + .2 * size          # (the letters' own height: lines set close don't overlap)
    spans, cur = [], None
    for w in words:
        if not w["keep"]:
            cur = None
            continue
        weights = [.55 if c in NARROW else 1.4 if c in WIDE else 1.0 for c in w["text"]]
        unit = (w["x1"] - w["x0"]) / sum(weights)
        if cur is None:
            cur = {"size": size, "flags": 0, "font": "OCR", "color": 0, "alpha": 255, "ascender": .9, "descender": -.25, "chars": []}
            spans.append(cur)
        elif cur["chars"]:
            x = cur["chars"][-1]["bbox"][2]
            cur["chars"].append({"c": " ", "origin": (x, base), "bbox": (x, top, w["x0"], bot)})
        x = w["x0"]
        for c, k in zip(w["text"], weights):
            cur["chars"].append({"c": c, "origin": (x, base), "bbox": (x, top, x + k * unit, bot)})
            x += k * unit
    for s in spans:
        s["origin"] = s["chars"][0]["origin"]
        s["bbox"] = (s["chars"][0]["bbox"][0], top, s["chars"][-1]["bbox"][2], bot)
    box = (spans[0]["bbox"][0], top, spans[-1]["bbox"][2], bot)
    return {"type": 0, "bbox": box, "lines": [{"spans": spans, "dir": (1.0, 0.0), "wmode": 0, "bbox": box}]}


def ocr_tsv(tsv, scale):
    """Tesseract's words, grouped into its lines; ones it wasn't sure of are marked to stay as pictures."""
    lines = {}
    for row in tsv.splitlines()[1:]:
        f = row.split("\t")
        if len(f) < 12 or f[0] != "5" or not f[11].strip():
            continue
        x, y, w, h, conf = int(f[6]), int(f[7]), int(f[8]), int(f[9]), float(f[10])
        lines.setdefault((f[2], f[3], f[4]), []).append({"x0": x * scale, "y0": y * scale, "x1": (x + w) * scale, "y1": (y + h) * scale,
                                                         "conf": conf, "text": clean(f[11].replace("￼", "").strip())})
    out = []
    for words in lines.values():
        words.sort(key=lambda w: w["x0"])
        for w in words:
            t = w["text"]
            w["keep"] = bool(t) and w["conf"] >= 70 or (w["conf"] >= 45 and re.fullmatch(r"[A-Za-z][a-z]+[.,;:]?|[A-Z]+[.,;:]?|\d+[.,;:]?", t) is not None)
            if len(t) >= 3 and w["y1"] - w["y0"] > 1.5 * (w["x1"] - w["x0"]) or re.search(r"[a-z]{3}[A-Z]{2}", t):
                w["keep"] = False           # (words running up the page, read as if across: nonsense)
            if len(re.sub(r"[\W_]", "", t)) == 1 and w["conf"] < 90:
                w["keep"] = False           # (a lone italic letter of an equation, x read as 2: the picture says it right)
        # a line it mostly couldn't read (an equation, a formula) stays a picture as a whole
        chars = sum(len(w["text"]) for w in words)
        sure = sum(len(w["text"]) for w in words if w["keep"])
        mathy = sum(1 for w in words if re.search(r"[=+^_{}<>\\~|]|\b[a-zA-Z]\b", w["text"]))
        if sure < .6 * chars or (mathy >= 2 and mathy >= .4 * len(words) and statistics.mean(w["conf"] for w in words) < 85):
            for w in words:
                w["keep"] = False
        out.append(words)
    # one size for a paragraph's lines (each line's guess wobbles), unless a line is plainly bigger or smaller
    paras = {}
    for (b, p, _), words in zip(lines, out):
        paras.setdefault((b, p), []).append(words)
    for group in paras.values():
        each = [statistics.median(e) if e else None for e in (ocr_sizes(w) for w in group)]
        known = [e for e in each if e]
        mid = statistics.median(known) if known else 10
        for words, e in zip(group, each):
            size = e if e and abs(e - mid) > .22 * mid else mid
            for w in words:
                w["size"] = max(4.0, round(size * 2) / 2)
    return out


def ink_left(pg, lines):
    """Ink on the page that the reading didn't take: equations, figures, words it couldn't read. Grouped into boxes."""
    k = 3
    pm = pg.get_pixmap(matrix=pymupdf.Matrix(k, k), colorspace=pymupdf.csGRAY, alpha=False)
    W, H, S = pm.width, pm.height, pm.stride
    buf = bytearray(pm.samples)
    for words in lines:
        for w in words:
            if w["keep"]:
                x0, x1 = max(int(w["x0"] * k) - 4, 0), min(int(w["x1"] * k) + 5, W)
                for y in range(max(int(w["y0"] * k) - 4, 0), min(int(w["y1"] * k) + 5, H)):
                    buf[y * S + x0:y * S + x1] = b"\xff" * (x1 - x0)
    # ink is what's clearly darker than this page's paper (a scan's shadows and the print showing through aren't)
    hist = sorted(pm.samples[::max(1, len(pm.samples) // 5000)])
    cut = min(165, int(.7 * hist[int(.85 * (len(hist) - 1))]))
    bits = bytes(buf).translate(bytes(1 if v < cut else 0 for v in range(256)))
    c = 6                                     # (cells of 2 points)
    gw, gh = (W + c - 1) // c, (H + c - 1) // c
    # ink inside a line of words read belongs to that line: it doesn't join ink of the lines above and below
    bands = []
    for i, words in enumerate(lines):
        if any(w["keep"] for w in words):
            bands.append((min(w["y0"] for w in words), max(w["y1"] for w in words), min(w["x0"] for w in words) - 8, max(w["x1"] for w in words) + 8, i))
    cells = {}
    for gy in range(gh):
        rows = [bits[y * S:y * S + W] for y in range(gy * c, min(gy * c + c, H))]
        if not any(1 in r for r in rows):
            continue
        yc = (gy + .5) * c / k
        here = [b for b in bands if b[0] <= yc <= b[1]]
        for gx in range(gw):
            if sum(r[gx * c:gx * c + c].count(1) for r in rows) >= 7:
                xc = (gx + .5) * c / k
                cells[(gx, gy)] = next((b[4] for b in here if b[2] <= xc <= b[3]), None)
    boxes, seen = [], set()
    pw, ph = pg.rect.width, pg.rect.height
    for start in cells:
        if start in seen:
            continue
        seen.add(start)
        todo, group = [start], []
        while todo:
            gx, gy = todo.pop()
            group.append((gx, gy))
            for dy in range(-2, 3):
                for dx in range(-3, 4):
                    q = (gx + dx, gy + dy)
                    if q in cells and q not in seen and cells[q] == cells[(gx, gy)]:
                        seen.add(q)
                        todo.append(q)
        xs, ys = [g[0] for g in group], [g[1] for g in group]
        b = (min(xs) * c / k, min(ys) * c / k, (max(xs) + 1) * c / k, (max(ys) + 1) * c / k)
        bw, bh = b[2] - b[0], b[3] - b[1]
        if len(group) < 3 or bw < 3 or bh < 3:
            continue                                                     # (specks)
        edge = b[0] < .04 * pw or b[2] > .96 * pw or b[1] < .03 * ph or b[3] > .97 * ph
        if edge and (bw < .04 * pw or bh < .04 * ph or bw * bh > .5 * pw * ph):
            continue                                                     # (the shadow along a scanned page's edge)
        if b[0] < .015 * pw or b[2] > .985 * pw or b[1] < .01 * ph or b[3] > .99 * ph:
            continue                                                     # (touching the scan's border: its shadow, not print)
        if (b[3] < .08 * ph or b[1] > .93 * ph) and bh < 20:
            continue                                                     # (bits of the running head or the foot)
        if bw * bh > .85 * pw * ph or (edge and bh > 4 * bw):
            continue                                                     # (or the facing page's edge, in the gutter)
        boxes.append({"bbox": b})
    return boxes


def ocr_doc(doc, progress=None):
    """Read every page with Tesseract (several at once). False if there's no Tesseract or it read next to nothing."""
    exe = tesseract()
    if not exe:
        return False
    import subprocess, tempfile, shutil
    from concurrent.futures import ThreadPoolExecutor
    tmp = tempfile.mkdtemp(prefix="babel-ocr-")
    env = dict(os.environ, OMP_THREAD_LIMIT="1")
    tess = os.path.join(os.path.dirname(exe), "tessdata")
    if os.path.isdir(tess):
        env.setdefault("TESSDATA_PREFIX", tess)
    hide = 0x08000000 if os.name == "nt" else 0

    def read(n):
        f = os.path.join(tmp, f"{n}.png")
        try:
            r = subprocess.run([exe, f, "stdout", "--dpi", str(OCR_DPI), "--psm", "3", "tsv"], capture_output=True, env=env,
                               creationflags=hide, timeout=600)
            return r.stdout.decode("utf-8", "replace")
        except Exception:
            return ""
        finally:
            try:
                os.remove(f)
            except OSError:
                pass
    words, workers = 0, max(1, min(6, (os.cpu_count() or 2) - 1))
    try:
        with ThreadPoolExecutor(workers) as pool:
            jobs = {}

            def take(n):
                nonlocal words
                if progress:
                    progress(n + 1, doc.page_count)
                lines = ocr_tsv(jobs.pop(n).result(), 72 / OCR_DPI)
                OCR[n] = {"blocks": [b for b in (ocr_line(w, w[0]["size"]) for w in lines if w) if b], "images": ink_left(doc[n], lines)}
                words += sum(1 for w in lines for x in w if x["keep"])
            for pg in doc:
                pm = pg.get_pixmap(dpi=OCR_DPI, colorspace=pymupdf.csGRAY, alpha=False)
                pm.save(os.path.join(tmp, f"{pg.number}.png"))
                jobs[pg.number] = pool.submit(read, pg.number)
                if len(jobs) >= 2 * workers:            # (a few pages ahead, not the whole book on disk)
                    take(min(jobs))
            while jobs:
                take(min(jobs))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if words / doc.page_count < 40:
        OCR.clear()
        return False
    return True


# ---------------- a scan, or text that can't be read: pictures of the page, column by column
def picture_copy(doc, out, title, author, eq, progress):
    mk = Maker(doc)
    files, order = {}, []
    toc = [(t.strip() or f"Page {p}", f"p{p}.xhtml", []) for lvl, t, p, *_ in doc.get_toc() if lvl <= 2 and 1 <= p <= doc.page_count]
    for pg in doc:
        n = pg.number + 1
        if progress:
            progress(n, doc.page_count)
        pm = pg.get_pixmap(matrix=pymupdf.Matrix(1, 1), colorspace=pymupdf.csGRAY, alpha=False)
        buf = bytes(pm.samples).translate(Ink.TABLE)
        s, w, h = pm.stride, pm.width, pm.height
        rows = [y for y in range(h) if buf[y * s:y * s + w].count(1) > 1]
        if not rows:
            continue
        y0, y1 = rows[0], rows[-1]
        cols = [0] * w
        for x in range(w):
            cols[x] = sum(buf[y * s + x] for y in range(y0, y1 + 1, 2))
        inked = [x for x in range(w) if cols[x]]
        x0, x1 = inked[0], inked[-1]
        # a white gutter down the middle third means two columns
        mid_a, mid_b = x0 + (x1 - x0) // 3, x0 + 2 * (x1 - x0) // 3
        best, run = None, 0
        for x in range(mid_a, mid_b):
            run = run + 1 if cols[x] <= 1 else 0
            if run >= 6:
                best = x - run // 2
        boxes = [(x0, y0, best, y1), (best, y0, x1, y1)] if best else [(x0, y0, x1, y1)]
        parts = []
        for b in boxes:
            name, _, _ = mk.crop(pg.number, (b[0] - 3, b[1] - 3, b[2] + 3, b[3] + 3), dpi=200, stem=f"p{n}-")
            parts.append(f'<div class="scan"><img alt="Page {n}" src="images/{name}"/></div>')
        files[f"p{n}.xhtml"] = page_xhtml(f"Page {n}", "".join(parts))
        order.append(f"p{n}.xhtml")
    if not toc:
        toc = [(f"Page {i}", f"p{i}.xhtml", []) for i in range(1, doc.page_count + 1, max(1, doc.page_count // 25)) if f"p{i}.xhtml" in files]
    if not order:
        raise ValueError("This PDF has no pages to read.")
    write_epub(out, title, author, files, mk.images, order, [], toc, eq)
    return {"mode": "pictures", "pages": doc.page_count, "figures": 0, "tables": 0, "equations": 0, "references": 0}


# ---------------- the whole thing
# Raised whenever the converter's output gets better: the app remakes copies made by an older one (their notes and
# reading places are moved to the same words in the new copy).
VERSION = 4
# what each version changed enough to remake for: a copy older than ALL is remade; one older than PICTURES only if
# it's page pictures (4: scans are read with Tesseract)
REMAKE_ALL, REMAKE_PICTURES = 3, 4


def made_by(path):
    """The converter version a reading copy was made with (0: before versions were written into them)."""
    import zipfile
    try:
        with zipfile.ZipFile(path) as z:
            m = re.search(r'<meta name="babel-converter" content="(\d+)"', z.read("OEBPS/content.opf").decode("utf-8", "replace"))
        return int(m.group(1)) if m else 0
    except Exception:
        return 0


def outdated(path):
    """Should this reading copy be made again with the converter installed now?"""
    v = made_by(path)
    if v < REMAKE_ALL:
        return True
    if v < REMAKE_PICTURES:
        import zipfile
        try:
            with zipfile.ZipFile(path) as z:
                first = next((n for n in z.namelist() if re.fullmatch(r"OEBPS/p\d+\.xhtml", n)), None)
                return bool(first) and 'class="scan"' in z.read(first).decode("utf-8", "replace")
        except Exception:
            return False
    return False


def convert(src, out, title=None, author=None, eq=EQ_SCALE, progress=None):
    doc = pymupdf.open(src)
    if doc.needs_pass:
        raise ValueError("This PDF is locked with a password.")
    if doc.page_count == 0:
        raise ValueError("This PDF has no pages to read.")
    PRIVATE.clear()
    OCR.clear()
    title = clean(title or doc.metadata.get("title") or os.path.splitext(os.path.basename(src))[0]).strip()
    author = clean(author or doc.metadata.get("author") or "").strip()

    def first_read():
        pages, sizes, total, bad = [], Counter(), 0, 0
        for pg in doc:
            rows, sideways = read_rows(pg)
            for r in rows:
                for s in r["spans"]:
                    n = len(s["text"].strip())
                    sizes[round(s["size"], 1)] += n
                    total += n
                    bad += sum(1 for c in clean(s["text"]) if 0xE000 <= ord(c) <= 0xF8FF or c == "�")
            pages.append({"n": pg.number, "rows": rows, "sideways": sideways, "w": pg.rect.width, "h": pg.rect.height})
        return pages, sizes, total, bad
    # first read: is there text to work with?
    pages, sizes, total, bad = first_read()
    words_per_page = sum(len(r["text"].split()) for p in pages for r in p["rows"]) / doc.page_count
    scanned = sum(1 for pg in doc if any((i["bbox"][2] - i["bbox"][0]) * (i["bbox"][3] - i["bbox"][1]) > .8 * pg.rect.width * pg.rect.height for i in pg.get_image_info())) / doc.page_count
    sample = " ".join(r["text"] for p in pages for r in p["rows"] if r["chars"] > 40)
    vowels = sum(c in "aeiouAEIOU" for c in sample)
    letters = sum(c.isalpha() for c in sample)
    nonsense = len(sample) > 500 and (letters < .68 * sum(not c.isspace() for c in sample) or vowels < .24 * letters)
    ocr = False
    if words_per_page < 40 or scanned > .6 or nonsense or (total and bad / total > .05):
        # a scan, or letters that can't be read: Tesseract reads the pages, else they stay page pictures
        if not ocr_doc(doc, progress):
            return picture_copy(doc, out, title, author, eq, progress)
        ocr = True
        pages, sizes, total, bad = first_read()
    body = sizes.most_common(1)[0][0]
    # with the text size known, read again so the pieces of a line join properly
    learn_ligatures(pages)
    learn_old_math(pages)
    learn_symbol_fonts(pages)
    learn_shapes(doc, pages)
    for p in pages:
        p["rows"], p["sideways"] = read_rows(doc[p["n"]], body)
    running_heads(pages)
    mk = Maker(doc)
    mk.raster = ocr and scanned > .6
    mk.body = body
    for p in pages:
        mk.page_rows[p["n"]] = p["rows"] + p.get("heads", [])
        for r in p["rows"]:
            mk.words.update(w.lower() for w in re.findall(r"[A-Za-z]+(?:-[A-Za-z]+)*", r["text"]))
    # text box of the paper, for what counts as "all the way across"
    longs = sorted((r["x0"], r["x1"]) for p in pages for r in p["rows"] if r["chars"] > 30)
    content_x = (min(a for a, _ in longs), max(b for _, b in longs)) if longs else (0, pages[0]["w"])
    # figures and tables
    figures = []
    loose = []
    for i, p in enumerate(pages):
        if progress:
            progress(i + 1, doc.page_count)
        # (figures stop short of the page's running head and foot, and the bars drawn with them)
        heads = p.get("heads", [])
        top = max([q["y1"] + 4 for q in heads if q["y1"] < p["h"] * .15] + [q["y1"] + 3 for q in p["rows"] if q["y1"] < p["h"] * .075] + [p["h"] * .03])
        foot = min([q["y0"] - 4 for q in heads if q["y0"] > p["h"] * .85] + [p["h"] * .97])
        content = (content_x[0], top, content_x[1], foot)
        own = sorted((r["x0"], r["x1"]) for r in p["rows"] if r["chars"] > 30)
        if OCR and len(own) >= 3:            # (a scanned page sits a little differently on each sheet)
            content = (min(a for a, _ in own), top, max(b for _, b in own), foot)
        p["cx"] = (content[0], content[2])
        turned = sum(len(" ".join(sp["text"] for sp in q["spans"])) for q in p["sideways"])
        if turned > 2 * sum(q["chars"] for q in p["rows"]) and turned > 200:
            mk.turns[p["n"]] = 90 if p["sideways"][0]["dir"][1] < 0 else 270
        figs, used = locate_figures(p, doc, body, content)
        # a whole page turned sideways: a table or figure, its caption running up the page
        side_caps = [" ".join(s["text"] for s in q["spans"]) for q in p["sideways"]]
        side_text = clean(" ".join(side_caps))
        m = CAP.match(side_text) if side_text else None
        if m and not figs and len(p["rows"]) < 6:
            figs.append({"kind": "table" if m.group(1).lower().startswith("tab") else "fig", "label": m.group(1).rstrip(". "), "num": m.group(2).upper(), "page": p["n"], "box": (0, 0, p["w"], p["h"]), "lines": [], "caption_text": side_text[:600], "turn": 90 if p["sideways"][0]["dir"][1] < 0 else 270})
        for f in figs:
            if f["box"]:
                b = f["box"]
                for r in p["rows"]:
                    cx, cy = (r["x0"] + r["x1"]) / 2, (r["y0"] + r["y1"]) / 2
                    if b[0] <= cx <= b[2] and b[1] <= cy <= b[3]:
                        used.add(id(r))
        for box in loose_pictures(p, doc, used, figs, body):
            loose.append({"page": p["n"], "box": box})
            for r in p["rows"]:
                if box[0] <= (r["x0"] + r["x1"]) / 2 <= box[2] and box[1] <= (r["y0"] + r["y1"]) / 2 <= box[3] and not word_like(r):
                    used.add(id(r))
        figures += figs
        keep = [r for r in p["rows"] if id(r) not in used]
        keep, drawn = drawn_figures(doc[p["n"]], p, keep, [f["box"] for f in figs if f["box"]], body, (content[1], content[3]))
        drawn_bars(doc[p["n"]], keep)
        loose[:] = [l for l in loose if l["page"] != p["n"] or not any(pymupdf.Rect(l["box"]).intersects(pymupdf.Rect(b)) for b in drawn)]
        keep = place_pictures(doc[p["n"]], p, keep, [f["box"] for f in figs if f["box"]] + [l["box"] for l in loose if l["page"] == p["n"]] + drawn, body)
        # small print at the foot of the page leaves the flow
        keep = [r for r in keep if not FURNITURE.match(r["text"])]
        leaves, notes = [], []
        # an equation's pieces join before the columns are worked out: a root sign's or fraction's gaps look like a column gap
        keep = gather_equations(sorted(keep, key=lambda r: (r["y0"], r["x0"])), body)
        cx = p.get("cx", content_x)
        for leaf in order_rows(keep, (cx[0], 0, cx[1], p["h"]), body):
            big = sum(1 for r in leaf if r["size"] >= body - .9)
            k = len(leaf)
            if big >= 3 or (leaf[0]["y0"] > p["h"] * .8 and len(leaf) <= 6):
                while k and leaf[k - 1]["size"] < body - .9 and leaf[k - 1]["math"] < .2 and leaf[k - 1]["y0"] > p["h"] * .55 and not is_display(leaf[k - 1], leaf[0]["x0"], max(q["x1"] for q in leaf), body):
                    k -= 1
                tail = leaf[k:]
                if any(REF_HEAD.fullmatch(re.sub(r"^[\W\d]+|[.:\s]+$", "", q["text"])) for q in leaf):
                    k = len(leaf)
                elif tail and (tail[-1]["y1"] - tail[0]["y0"] > .25 * p["h"] or any(re.match(r"^\s*(?:\[\d+\]|\(\d+\)|\d+[.)])\s*[A-Z]", q["text"]) for q in tail) and len(tail) > 4):
                    k = len(leaf)
            notes += leaf[k:]
            if leaf[:k]:
                leaves.append(leaf[:k])
        p["notes"], p["leaves"] = notes, leaves
    for f in figures:
        if not f["box"]:
            near = sorted((l for l in loose if abs(l["page"] - f["page"]) <= 1), key=lambda l: abs(l["page"] - f["page"]))
            if near:
                f["box"], f["page"] = near[0]["box"], near[0]["page"]
                loose.remove(near[0])
    # how many references there are decides which numbers are citations
    blocks = build_blocks(mk, pages)
    return assemble(mk, doc, pages, blocks, figures, loose, out, title, author, eq)


def assemble(mk, doc, pages, blocks, figures, loose, out, title, author, eq):
    body = mk.body
    # -- references: everything between their heading and the next heading
    ref_rows, kept = [], []
    in_refs, seen_refs = False, False

    def refs_follow(k):
        """Do the lines after this heading look like references? (A table's row named "References" is not one.)"""
        nxt = [r["text"] for b in blocks[k + 1:k + 6] for r in (b.get("rows") or [])][:10]
        return sum(1 for t in nxt if re.search(r"\b(?:1[89]|20)\d\d\b|\bet al\b|^\s*(?:\[\d+\]|\d+\.\s)|[A-Z]\.\s?[A-Z]\.|\bdoi\b", t)) >= min(2, len(nxt))
    for k, b in enumerate(blocks):
        if b["type"] == "h":
            if REF_HEAD.fullmatch(re.sub(r"^[\dIVX.\s]+|[.:\s]+$", "", b["text"])) and refs_follow(k):
                in_refs, seen_refs = True, True
                continue
            if in_refs and (b["style"] == "known" or b["size"] > body + .7):
                in_refs = False
            elif in_refs:
                ref_rows += b["rows"]
                continue
        if in_refs:
            ref_rows += b.get("rows") or []
            continue
        kept.append(b)
    if not seen_refs:
        # no heading: a numbered list running to the end of the paper
        nth = lambda n: re.compile(rf"^\s*(?:\[{n}\]|\({n}\)|{n}[.)]?\s|{n}[.)](?=[^\W\d_]))")
        found = None
        for i in range(int(len(kept) * .3), len(kept)):
            rs = kept[i].get("rows") or []
            for j, r in enumerate(rs):
                if nth(1).match(r["text"]) and re.search(r"\d{4}|\bet al\b|[A-Z]\.", r["text"] + " " + (rs[j + 1]["text"] if j + 1 < len(rs) else "")):
                    after = [q for b in kept[i:i + 40] for q in (b.get("rows") or [])]
                    after = after[after.index(r):][:40]
                    # (and it reads like references: years, "et al." — not a list of numbered exercises)
                    cited = sum(1 for q in after if re.search(r"\b(?:1[6-9]|20)\d\d\b|\bet al\b", q["text"]))
                    if any(nth(2).match(q["text"]) for q in after) and any(nth(3).match(q["text"]) for q in after) and cited >= min(4, len(after) // 4):
                        found = (i, j)
                        break
            if found:
                break
        if found:
            i, j = found
            head = kept[i]
            before = dict(head, rows=head["rows"][:j]) if j else None
            ref_rows = list(head["rows"][j:])
            cut = i + 1
            for q in kept[i + 1:]:
                if q["type"] == "h" and (q["style"] == "known" and not re.match(r"\d", q["text"]) or q["size"] > body + .7):
                    break
                ref_rows += q.get("rows") or []
                cut += 1
            kept = kept[:i] + ([before] if before else []) + kept[cut:]
    numbered, plain_refs = split_references(mk, ref_rows)
    mk.nrefs = max(numbered) if numbered else 0
    REFS.clear()
    REFS.update(numbered)

    # -- title, then who wrote it, then the abstract
    first_page = [b for b in kept if b["type"] in ("p", "h") and b.get("page", 0) <= 1]
    def bsize(b):
        return b.get("size", 0)
    head_title = None
    candidates = [b for b in kept[:40] if b["type"] in ("p", "h") and b.get("page", 0) == 0 and len(block_text(b)) > 3 and len(block_text(b).split()) <= 45]
    if candidates:
        words = lambda t: set(re.findall(r"[a-z0-9]{3,}", t.lower()))
        known = words(title)
        match = lambda b: len(words(block_text(b)) & known) / max(len(words(block_text(b))), 1)
        named = [b for b in candidates if len(known) >= 2 and match(b) > .6 and len(words(block_text(b)) & known) >= min(2, len(known))]
        top = max(bsize(b) for b in candidates)
        if named:
            head_title = max(named, key=bsize)
        elif top > body + 1.5 and len(known) < 3:      # (a real title on file beats whatever's in the biggest type)
            head_title = next(b for b in candidates if bsize(b) >= top - .2)
    front_html, flow = [], kept
    if head_title is not None:
        i = kept.index(head_title)
        pre = kept[:i]
        rows = list(head_title["rows"])
        k = i + 1
        while k < len(kept) and kept[k]["type"] in ("p", "h") and kept[k].get("page", 0) == 0 and abs(bsize(kept[k]) - bsize(head_title)) < .3 and len(rows) < 6 and bsize(head_title) > body + .5:
            rows += kept[k]["rows"]
            k += 1
        flow = kept[k:]
        title_html = tidy(join_rows(mk, rows, False))
        title = plain_of(title_html).strip() or title
    else:
        pre, title_html = [], esc(title)
    moved_notes = []
    for b in pre:
        if b["type"] in ("p", "h") and block_rows(b):
            moved_notes.append(tidy(join_rows(mk, block_rows(b), False)))
    # short lines after the title are authors and addresses
    k = 0
    has_abs = False
    while k < len(flow):
        b = flow[k]
        if b["type"] == "h":
            has_abs = bool(re.match(r"abstract|summary", b["text"], re.I))
            if b["style"] == "known" or b.get("page", 0) > 0:
                break
            if b["rows"]:
                front_html.append(f'<p class="addr">{tidy(join_rows(mk, b["rows"], False))}</p>')
            k += 1
            continue
        if b["type"] != "p" or b.get("page", 0) > 1 or len(block_text(b).split()) > 55:
            break
        front_html.append(f'<p class="addr">{tidy(join_rows(mk, b["rows"], False))}</p>')
        k += 1
    flow = flow[k:]
    abstract_added = False
    if not has_abs and flow and flow[0]["type"] == "p" and flow[0].get("page", 0) <= 1 and len(block_text(flow[0]).split()) > 55:
        flow = [{"type": "h", "rows": [], "style": "known", "size": body, "page": 0, "text": "Abstract"}] + flow
        abstract_added = True

    # -- numbers for what's at the end: figures, tables, schemes
    known, cards = {}, []
    index = Counter()
    for f in figures:
        word = f["label"].lower()
        kind = "table" if word.startswith("tab") or "table" in word else "scheme" if word.startswith("sch") else "chart" if word.startswith("cha") else "box" if word.startswith("box") else "plate" if word.startswith("plate") else "fig"
        f["key"] = (kind, f["num"])
        index[f["key"]] += 1
        f["file"] = f"{ {'table': 'table', 'scheme': 'scheme', 'chart': 'chart', 'box': 'box', 'plate': 'plate'}.get(kind, 'fig')}{re.sub(r'[^A-Za-z0-9]', '_', f['num'])}" + ("" if index[f["key"]] == 1 else f"-{index[f['key']]}")
        known.setdefault(f["key"], f["file"])

    # -- the text, into files split at the main headings
    big_sizes = sorted({round(b["size"], 1) for b in flow if b["type"] == "h" and b["style"] == "big"}, reverse=True)
    eq_numbers = {}
    for b in flow:
        if b["type"] == "eq":
            spans = [sp for q in b.get("rows") or [] for sp in q["spans"] if sp["text"].strip()]
            b["html"] = mk.formula(b["page"], b["box"], inline=False, number=b["number"], keep={id(sp) for sp in spans}, raster=bool(spans) and all(sp.get("img") or not re.search(r"[^\s.,;:()\d]", sp["text"]) for sp in spans))
            if b["number"]:
                eq_numbers.setdefault(b["number"], len(mk.zooms))
    files, order, toc, seen = {}, [], [], {}
    sections, cur = [], {"title": None, "file": "text", "parts": [], "level": 1}
    sections.append(cur)
    used_files = {"references", "front"}
    size_so_far = 0
    for b in flow:
        if b["type"] == "h":
            level = level_of(b["text"], b["style"], b["size"], body, big_sizes)
            if b["text"].lower().startswith(("abstract", "summary")) and not sections[-1]["parts"] and len(sections) == 1:
                level = 1
            b["level"] = level
            if level == 1:
                name = re.sub(r"[^a-z0-9]+", "-", plain_of(b["text"]).lower()).strip("-")[:32] or "part"
                base, j = name, 2
                while name in used_files:
                    name, j = f"{base}-{j}", j + 1
                used_files.add(name)
                cur = {"title": b["text"], "file": name, "parts": [], "level": 1}
                sections.append(cur)
                size_so_far = 0
                continue
            cur.setdefault("subs", [])
        elif b["type"] == "p":
            size_so_far += sum(r["chars"] for r in b["rows"])
            if size_so_far > 40_000:        # long stretches with no headings: lighter files for the e-reader
                name = f"{cur['file']}-more{len(cur.get('more', [])) + 2}"
                cur.setdefault("more", []).append(name)
                nxt = {"title": None, "file": name, "parts": [], "level": 1, "cont": True}
                sections.append(nxt)
                cur = nxt
                size_so_far = 0
        cur["parts"].append(b)

    done_words = 0
    for sec in sections:
        if not sec["parts"] and not sec["title"]:
            continue
        name = sec["file"] + ".xhtml"
        html_parts = []
        if sec["title"]:
            html_parts.append(f'<h2>{esc(sec["title"])}</h2>')
        subs = []
        for n, b in enumerate(sec["parts"]):
            if b["type"] == "p":
                h = tidy(join_rows(mk, b["rows"], True))
                h = link_brackets(h, mk.nrefs)
                h = link_mentions(h, known, seen, name, eq_numbers)
                done_words += len(plain_of(h).split())
                html_parts.append(f"<p>{h}</p>")
            elif b["type"] == "eq":
                html_parts.append(f'<div class="eq">{b["html"]}' + (f'<span class="eqn"> {esc(b["label"])}</span>' if b.get("label") else "") + '</div>')
            elif b["type"] == "pic":
                img, w, h = mk.crop(b["page"], b["box"], dpi=220, gray=False, turn=mk.turns.get(b["page"], 0), stem="f")
                html_parts.append(f'<div class="figure inflow"><img alt="Picture" src="images/{img}"/></div>')
            else:
                tag = "h3" if b["level"] == 2 else "h4"
                aid = f"s{n}"
                html_parts.append(f'<{tag} id="{aid}">{esc(b["text"])}</{tag}>')
                if b["level"] == 2:
                    subs.append((b["text"], f"{name}#{aid}", []))
        if sec.get("cont") or not sec["title"]:
            pass
        files[name] = page_xhtml(sec["title"] or title, "".join(html_parts))
        order.append(name)
        if sec["title"]:
            toc.append((sec["title"], name, subs))
        elif not sec.get("cont"):
            toc.append(("Main text", name, subs))

    # -- the first page
    head = f"<h1>{title_html}</h1>" + "".join(front_html)
    files["front.xhtml"] = page_xhtml(title, head)
    order.insert(0, "front.xhtml")
    toc.insert(0, ("Title and authors", "front.xhtml", []))

    # -- references
    if numbered or plain_refs:
        items = []
        if numbered:
            for n in sorted(numbered):
                h = tidy(join_rows(mk, numbered[n], False))
                h = re.sub(r"^\s*(?:<[bi]>)*\s*(?:\[\d+\]|\(\d+\)|\d+[.)]?)\s*(?:</[bi]>)*\s*", "", h)
                h = re.sub(r'^\s*(?:(?:<a class="zl"[^>]*>)?<img class="(?:gl|im)"[^>]*/>(?:</a>)?\s*)+', "", h)       # (a number drawn in a symbol font: ours is already there)
                items.append(f'<li id="r{n}">{n}. {balance(h)}</li>')
        else:
            for it in plain_refs:
                items.append(f"<li>{tidy(join_rows(mk, it, False))}</li>")
        done_words += sum(len(plain_of(i).split()) for i in items)
        files["references.xhtml"] = page_xhtml("References", f'<h2>References</h2><ol class="refs">{"".join(items)}</ol>')
        order.append("references.xhtml")
        toc.append(("References", "references.xhtml", []))
    elif mk.nrefs == 0:
        files_refs = None

    # -- notes from the pages
    notes = moved_notes[:]
    for p in pages:
        for r in p.get("notes", []):
            mk.tail = ""
            notes.append(tidy(row_html(mk, r, False)))
    joined = []
    for n in notes:
        if joined and not re.search(r"[.?!:)]\W*$", plain_of(joined[-1])):
            joined[-1] += " " + n
        else:
            joined.append(n)
    if joined:
        files["page-notes.xhtml"] = page_xhtml("Notes from the pages", "<h2>Notes from the pages</h2>" + "".join(f'<p class="note">{n}</p>' for n in joined))
        order.append("page-notes.xhtml")
        toc.append(("Notes from the pages", "page-notes.xhtml", []))

    done_words += sum(len(plain_of(n).split()) for n in joined)

    # -- figures and tables
    extra = []
    fig_toc, table_toc, other_toc = [], [], []
    plural = {"fig": "Figure", "table": "Table", "scheme": "Scheme", "chart": "Chart", "box": "Box", "plate": "Plate"}
    for f in figures:
        kind, num = f["key"]
        word = plural[kind]
        name = f["file"] + ".xhtml"
        if f.get("lines"):
            mk.tail = ""
            cap = tidy(join_rows(mk, f["lines"], False))
            done_words += len(plain_of(cap).split())
        else:
            cap = esc(f.get("caption_text", f"{word} {num}"))
        short = plain_of(cap)
        m = re.match(r"\s*\S+\.?\s*\S+\s*[.:|–—-]*\s*(.{0,70})", short)
        label = f"{word} {num}" + (f": {cut_label(m.group(1))}" if m and m.group(1).strip() else "")
        back = seen.get(f["key"], []) if known.get(f["key"]) == f["file"] else []
        links = "".join(f'<a href="{fl}#{aid}">{i + 1}</a>' for i, (fl, aid) in enumerate(back))
        nav = f'<div class="back">Back to where it\'s mentioned: {links}</div>' if back else ""
        pic, side = "", ""
        if f["box"]:
            img, w, h = mk.crop(f["page"], f["box"], dpi=240, gray=False, turn=f.get("turn", mk.turns.get(f["page"], 0)), stem="f")
            pic = f'<div class="figure"><img alt="{word} {num}" src="images/{img}"/></div>'
            if w > h * 1.15 and not mk.long:
                turned, _, _ = mk.crop(f["page"], f["box"], dpi=240, gray=False, turn=(f.get("turn", 0) + 90) % 360, stem="s")
                files[f["file"] + "-side.xhtml"] = page_xhtml(f"{label} (sideways)", f'<div class="side"><a href="{name}"><img alt="{word} {num}, turned sideways" src="images/{turned}"/></a></div>')
                extra.append(f["file"] + "-side.xhtml")
                side = f'<div class="back"><a href="{f["file"]}-side.xhtml">Fill the screen (sideways)</a></div>'
        files[name] = page_xhtml(label, f'{pic}{side}<p class="cap">{cap}</p>{nav}')
        order.append(name)
        (table_toc if kind == "table" else fig_toc).append((label, name, []))
    # pictures with no caption
    for i, l in enumerate(loose, 1):
        img, w, h = mk.crop(l["page"], l["box"], dpi=240, gray=False, stem="f")
        name = f"pic{i}.xhtml"
        files[name] = page_xhtml(f"Picture {i}", f'<div class="figure"><img alt="Picture from page {l["page"] + 1}" src="images/{img}"/></div><p class="cap">From page {l["page"] + 1}.</p>')
        order.append(name)
        other_toc.append((f"Picture from page {l['page'] + 1}", name, []))
    if fig_toc:
        toc.append(("Figures", fig_toc[0][1], fig_toc))
    if table_toc:
        toc.append(("Tables", table_toc[0][1], table_toc))
    if other_toc:
        toc.append(("Other pictures", other_toc[0][1], other_toc))

    # -- each equation, large
    for z in mk.zooms:
        name = f"eq{z['id']}.xhtml"
        ref = next((fn for fn, content in files.items() if f'id="z{z["id"]}"' in content), None)
        back = f'<div class="back"><a href="{ref}#z{z["id"]}">Back to the text</a></div>' if ref else ""
        files[name] = page_xhtml("Equation", f'<div class="zoom"><img alt="equation, full size" src="images/{z["image"]}"/></div>{back}')
        extra.append(name)

    write_epub(out, title, author, files, mk.images, order, extra, toc, eq)
    in_figures = sum(len(r["text"].split()) for f in figures if f["box"] for r in pages[f["page"]]["rows"] if f["box"][0] <= (r["x0"] + r["x1"]) / 2 <= f["box"][2] and f["box"][1] <= (r["y0"] + r["y1"]) / 2 <= f["box"][3])
    in_equations = sum(len(b["text"].split()) for b in flow if b["type"] == "eq")
    pdf_words = sum(len(r["text"].split()) for p in pages for r in p["rows"]) - in_figures - in_equations
    return {"mode": "text", "ocr": mk.raster or bool(OCR), "pages": doc.page_count, "figures": len([f for f in figures if f["key"][0] != "table"]), "tables": len([f for f in figures if f["key"][0] == "table"]),
            "no_picture": [f["file"] for f in figures if not f["box"]], "loose": len(loose), "equations": len(mk.zooms), "references": len(numbered) or len(plain_refs), "numbered_refs": len(numbered),
            "words": done_words, "pdf_words": pdf_words, "headings": [t for t, _, _ in toc], "mentions": sum(len(v) for v in seen.values()), "abstract_added": abstract_added, "body": body}


def block_rows(b):
    return b.get("rows") or []


def block_text(b):
    return b.get("text") or " ".join(r["text"] for r in block_rows(b))


def cut_label(t):
    t = t.strip()
    m = re.match(r"(.{12,}?[.;:])\s", t + " ")
    t = m.group(1).rstrip(".;:") if m else t
    return t if len(t) <= 62 else t[:60].rsplit(" ", 1)[0] + "…"
