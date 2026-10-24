"""Pull text, metadata and covers out of PDF and EPUB files (offline)."""
import html
import io
import os
import posixpath
import re
import sys
import zipfile
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor_py"))
from pypdf import PdfReader  # noqa: E402

DOI_RE = re.compile(r"\b(10\.\d{4,9}/[^\s\"<>]+)", re.I)
ISBN_RE = re.compile(r"\b(?:ISBN(?:-1[03])?:?\s*)?((?:97[89][\s-]?)?\d{1,5}[\s-]?\d{1,7}[\s-]?\d{1,7}[\s-]?[\dX])\b", re.I)
YEAR_RE = re.compile(r"\b(1[5-9]\d\d|20\d\d)\b")


def clean_doi(d):
    if not d:
        return ""
    d = d.strip().rstrip(".,;)]}")
    d = re.sub(r"^(https?://(dx\.)?doi\.org/|doi:\s*)", "", d, flags=re.I)
    return d


def clean_isbn(s):
    if not s:
        return ""
    s = re.sub(r"[^0-9Xx]", "", s)
    return s.upper() if len(s) in (10, 13) else ""


def split_authors(s):
    if not s:
        return []
    s = s.strip()
    if ";" in s:
        parts = s.split(";")
    elif " and " in s or "&" in s:
        parts = re.split(r",?\s+(?:and|&)\s+|,\s+(?=[A-Z][a-z]+\s+[A-Z])", s)
    elif s.count(",") >= 2:
        parts = s.split(",")
    else:
        parts = [s]
    return [p.strip() for p in parts if p.strip() and len(p.strip()) < 80]


# ---------------- PDF ----------------
def pdf_info(path, max_pages=14):
    out = {"text": "", "title": "", "authors": [], "year": "", "doi": "", "pages_total": 0, "keywords": ""}
    try:
        reader = PdfReader(path)
    except Exception as e:
        out["error"] = str(e)
        return out
    out["pages_total"] = len(reader.pages)
    meta = {}
    try:
        meta = reader.metadata or {}
    except Exception:
        pass
    def _s(v):
        if v is None:
            return ""
        if isinstance(v, bytes):
            v = v.decode("utf-8", "ignore")
        try:
            return str(v).replace("\x00", "").strip()
        except Exception:
            return ""
    title = _s(meta.get("/Title")) if meta else ""
    if title and not re.match(r"^(untitled|microsoft word|document\d*|.*\.(docx?|pdf|tex|dvi))", title, re.I) and len(title) > 3:
        out["title"] = title
    if meta and _s(meta.get("/Author")):
        out["authors"] = split_authors(_s(meta.get("/Author")))
    if meta and _s(meta.get("/Keywords")):
        out["keywords"] = _s(meta.get("/Keywords"))
    if meta and _s(meta.get("/Subject")):
        out["pdf_subject"] = _s(meta.get("/Subject"))
    cd = _s(meta.get("/CreationDate")) if meta else ""
    m = re.search(r"D:(\d{4})", cd)
    texts = []
    for i, page in enumerate(reader.pages[:max_pages]):
        try:
            texts.append(page.extract_text() or "")
        except Exception:
            texts.append("")
    text = "\n".join(texts)
    out["text"] = text
    first = texts[0] if texts else ""
    dm = DOI_RE.search(first) or DOI_RE.search(text[:20000])
    if dm:
        out["doi"] = clean_doi(dm.group(1))
    ym = YEAR_RE.findall(first[:3000])
    if ym:
        out["year"] = max(ym, key=lambda y: (int(y) <= 2100, ym.count(y)))
    elif m:
        out["year"] = m.group(1)
    if not out["title"]:
        out["title"] = guess_title_from_text(first)
    out.update(guess_journal(first))
    return out


def guess_journal(first):
    """Find a 'Journal Name, 2021, Vol. 58(4), 812-825' style line on page 1."""
    res = {}
    for line in first.splitlines()[:40]:
        if not re.search(r"\b(vol\.?|volume)\s*\d", line, re.I):
            continue
        j = re.match(r"\s*([A-Z][A-Za-z&:\- ]{4,90}?)[,\.]?\s+(?:\(?\d{4}\)?[,;]?\s*)?(?:vol\.?|volume)", line, re.I)
        if j and not re.search(r"doi|http", j.group(1), re.I):
            res["journal"] = j.group(1).strip(" ,.")
        v = re.search(r"(?:vol\.?|volume)\s*(\d+)\s*(?:\((\d+)\)|,?\s*(?:no\.?|issue)\s*(\d+))?", line, re.I)
        if v:
            res["volume"] = v.group(1)
            if v.group(2) or v.group(3):
                res["issue"] = v.group(2) or v.group(3)
        pg = re.search(r"(?:pp\.?\s*)?\b(\d{1,5})\s*[-–]\s*(\d{1,5})\b", line[v.end():] if v else line)
        if pg and int(pg.group(2)) > int(pg.group(1)):
            res["pages"] = f"{pg.group(1)}-{pg.group(2)}"
        break
    return res


def guess_title_from_text(first):
    lines = [l.strip() for l in first.splitlines() if l.strip()]
    skip = re.compile(r"(journal|vol\.|volume|issn|doi|http|www\.|©|copyright|received|accepted|arxiv|preprint|page \d|^\d+$|abstract)", re.I)
    cand = []
    for l in lines[:25]:
        if skip.search(l) or len(l) < 12 or len(l) > 220:
            continue
        cand.append(l)
        if len(cand) >= 1:
            break
    return cand[0] if cand else ""


# ---------------- EPUB ----------------
NS = {
    "c": "urn:oasis:names:tc:opendocument:xmlns:container",
    "opf": "http://www.idpf.org/2007/opf",
    "dc": "http://purl.org/dc/elements/1.1/",
}


def _strip_html(s):
    s = re.sub(r"(?is)<(script|style).*?</\1>", " ", s)
    s = re.sub(r"(?s)<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", html.unescape(s))


def epub_info(path, max_chars=60000):
    out = {"text": "", "title": "", "authors": [], "year": "", "isbn": "", "publisher": "",
           "subjects": [], "description": "", "cover_bytes": None, "cover_ext": "", "series": "", "series_index": None}
    try:
        z = zipfile.ZipFile(path)
        container = ET.fromstring(z.read("META-INF/container.xml"))
        opf_path = container.find(".//c:rootfile", NS).attrib["full-path"]
        opf = ET.fromstring(z.read(opf_path))
    except Exception as e:
        out["error"] = str(e)
        return out
    base = posixpath.dirname(opf_path)
    md = opf.find("opf:metadata", NS)

    def all_text(tag):
        return [(e.text or "").strip() for e in md.findall(tag, NS) if (e.text or "").strip()] if md is not None else []

    t = all_text("dc:title")
    out["title"] = t[0] if t else ""
    out["authors"] = all_text("dc:creator")
    pubs = all_text("dc:publisher")
    out["publisher"] = pubs[0] if pubs else ""
    for d in all_text("dc:date"):
        y = YEAR_RE.search(d)
        if y:
            out["year"] = y.group(1)
            break
    for ident in all_text("dc:identifier"):
        isbn = clean_isbn(ident.replace("urn:isbn:", "")) if re.search(r"isbn|^[\d\-X ]{10,17}$", ident, re.I) else ""
        if isbn:
            out["isbn"] = isbn
            break
    out["subjects"] = all_text("dc:subject")
    if md is not None:
        for meta in md.findall("opf:meta", NS):
            nm = meta.attrib.get("name", "")
            if nm == "calibre:series":
                out["series"] = meta.attrib.get("content", "").strip()
            elif nm == "calibre:series_index":
                try:
                    out["series_index"] = float(meta.attrib.get("content"))
                except (TypeError, ValueError):
                    pass
            elif meta.attrib.get("property") == "belongs-to-collection" and (meta.text or "").strip() and not out["series"]:
                out["series"] = meta.text.strip()
            elif meta.attrib.get("property") == "group-position" and out["series_index"] is None:
                try:
                    out["series_index"] = float((meta.text or "").strip())
                except ValueError:
                    pass
    desc = all_text("dc:description")
    out["description"] = _strip_html(desc[0]).strip()[:1500] if desc else ""

    manifest = {}
    cover_href = None
    for it in opf.findall("opf:manifest/opf:item", NS):
        manifest[it.attrib.get("id")] = it.attrib
        if "cover-image" in (it.attrib.get("properties") or ""):
            cover_href = it.attrib.get("href")
    if not cover_href and md is not None:
        for meta in md.findall("opf:meta", NS):
            if meta.attrib.get("name") == "cover":
                ci = manifest.get(meta.attrib.get("content"))
                if ci:
                    cover_href = ci.get("href")
    if not cover_href:
        for it in manifest.values():
            if (it.get("media-type") or "").startswith("image/") and "cover" in (it.get("href", "") + it.get("id", "")).lower():
                cover_href = it.get("href")
                break
    if cover_href:
        try:
            cp = posixpath.normpath(posixpath.join(base, cover_href))
            out["cover_bytes"] = z.read(cp)
            out["cover_ext"] = os.path.splitext(cp)[1].lower() or ".jpg"
        except Exception:
            pass

    texts, total = [], 0
    for ref in opf.findall("opf:spine/opf:itemref", NS):
        it = manifest.get(ref.attrib.get("idref"))
        if not it:
            continue
        try:
            raw = z.read(posixpath.normpath(posixpath.join(base, it["href"]))).decode("utf-8", "ignore")
        except Exception:
            continue
        txt = _strip_html(raw)
        texts.append(txt)
        total += len(txt)
        if total > max_chars:
            break
    out["text"] = " ".join(texts)[:max_chars]
    if not out["isbn"]:
        m = re.search(r"ISBN[\s:-]*((?:97[89][\s-]?)?[\d\s-]{9,15}[\dX])", out["text"][:30000], re.I)
        if m:
            out["isbn"] = clean_isbn(m.group(1))
    return out


SERIES_WORDS = r"(?:archive|saga|series|chronicles?|trilogy|cycle|sequence|quartet|quintet|duology|legacy|books)"


def series_from_title(title):
    """'The Way of Kings: The Stormlight Archive' -> ('The Way of Kings', 'The Stormlight Archive', None)
       'Mistborn (Mistborn, #1)' -> ('Mistborn', 'Mistborn', 1)"""
    t = (title or "").strip()
    m = re.match(r"^(.*?)\s*\(([^()#]+?),?\s*(?:#|book|vol\.?|volume)\s*([\d.]+)\)\s*$", t, re.I)
    if m:
        return m.group(1).strip(), m.group(2).strip(), float(m.group(3))
    m = re.match(r"^(.*?)\s*[:\-–—]\s*(?:book\s+(\w+)\s+of\s+)?(the\s+.+?" + SERIES_WORDS + r")\b\s*(?:,?\s*(?:book|#|vol\.?)\s*([\d.]+))?\s*$", t, re.I)
    if m:
        idx = m.group(4)
        words = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
        if not idx and m.group(2):
            idx = words.get(m.group(2).lower()) or (m.group(2) if m.group(2).isdigit() else None)
        return m.group(1).strip(), m.group(3).strip(), float(idx) if idx else None
    return t, "", None
