"""APA 7, MLA 9 and Chicago (17th, notes-bibliography) citations."""
import html
import re

PARTICLES = {"van", "von", "de", "der", "den", "da", "di", "du", "la", "le", "del", "dos", "ter", "bin", "al"}


def parse_name(n):
    n = re.sub(r"\s+", " ", (n or "").strip())
    if not n:
        return None
    if "," in n:
        last, first = [p.strip() for p in n.split(",", 1)]
        return {"first": first, "last": last}
    parts = n.split(" ")
    if len(parts) == 1:
        return {"first": "", "last": parts[0], "org": True}
    i = len(parts) - 1
    while i > 1 and parts[i - 1].lower() in PARTICLES:
        i -= 1
    return {"first": " ".join(parts[:i]), "last": " ".join(parts[i:])}


def initials(first):
    out = []
    for p in re.split(r"\s+", first.strip()):
        if not p:
            continue
        out.append("-".join(s[0].upper() + "." for s in p.split("-") if s))
    return " ".join(out)


def _join(items, conj, oxford=True):
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]}{',' if conj == '&' else ''} {conj} {items[1]}"
    return ", ".join(items[:-1]) + ("," if oxford else "") + f" {conj} {items[-1]}"


def sentence_case(t):
    if not t:
        return t
    words = t.split(" ")
    out = []
    for i, w in enumerate(words):
        if i == 0 or (out and out[-1].endswith(":")):
            out.append(w[:1].upper() + w[1:])
        elif w.isupper() and len(w) > 1:
            out.append(w)
        elif re.match(r"^[A-Z][a-z]+[A-Z]", w):
            out.append(w)
        else:
            out.append(w.lower())
    return " ".join(out)


def title_case(t):
    small = {"a", "an", "the", "and", "but", "or", "for", "nor", "on", "at", "to", "by", "of", "in", "as", "vs", "with", "from", "into", "over", "upon", "per", "via", "up"}
    words = (t or "").split(" ")
    return " ".join(w if (w.isupper() and len(w) > 1) else (w.capitalize() if (i == 0 or i == len(words) - 1 or w.lower() not in small) else w.lower())
                    for i, w in enumerate(words))


def _end(s):
    return s if s.endswith((".", "?", "!")) else s + "."


def apa(it):
    names = [n for n in map(parse_name, it.get("authors") or []) if n]
    fmt = [n["last"] if n.get("org") else f"{n['last']}, {initials(n['first'])}" for n in names]
    if len(fmt) > 20:
        fmt = fmt[:19] + ["… " + fmt[-1]]
    auth = _join(fmt, "&") if fmt else ""
    year = f"({it.get('year') or 'n.d.'})."
    title = sentence_case((it.get("title") or "Untitled").strip())
    doi = it.get("doi")
    link = f" https://doi.org/{doi}" if doi else (f" {it['url']}" if it.get("url") else "")
    if it.get("kind") in ("book", "graphic"):
        pub = f" {it['publisher']}." if it.get("publisher") else ""
        lead = f"{auth} {year}" if auth else f"<i>{_end(title)[:-1]}</i>. {year}"
        gn = " [Graphic novel]" if it.get("kind") == "graphic" else ""
        body = f" <i>{_end(title)[:-1]}</i>{gn}." if auth else ""
        return f"{lead}{body}{pub}{link}".strip()
    src = ""
    if it.get("journal"):
        src = f" <i>{title_case(it['journal'])}</i>"
        if it.get("volume"):
            src += f", <i>{it['volume']}</i>"
            if it.get("issue"):
                src += f"({it['issue']})"
        if it.get("pages"):
            src += f", {it['pages'].replace('-', '–')}"
        src += "."
    lead = f"{auth} {year} {_end(title)}" if auth else f"{_end(title)} {year}"
    return f"{lead}{src}{link}".strip()


def _mla_names(names):
    if not names:
        return ""
    first = names[0]
    a = first["last"] if first.get("org") else f"{first['last']}, {first['first']}"
    if len(names) == 2:
        b = names[1]
        a += f", and {b['first']} {b['last']}".replace("  ", " ")
    elif len(names) > 2:
        a += ", et al"
    return _end(a)


def mla(it):
    names = [n for n in map(parse_name, it.get("authors") or []) if n]
    auth = _mla_names(names)
    title = title_case((it.get("title") or "Untitled").strip())
    doi = it.get("doi")
    tail = f" https://doi.org/{doi}." if doi else (f" {it['url']}." if it.get("url") else "")
    if it.get("kind") in ("book", "graphic"):
        parts = [p for p in (it.get("publisher"), it.get("year")) if p]
        return f"{auth} <i>{title}</i>. {', '.join(parts) + '.' if parts else ''}{tail}".strip()
    seg = [f"<i>{title_case(it['journal'])}</i>"] if it.get("journal") else []
    if it.get("volume"):
        seg.append(f"vol. {it['volume']}")
    if it.get("issue"):
        seg.append(f"no. {it['issue']}")
    if it.get("year"):
        seg.append(str(it["year"]))
    if it.get("pages"):
        seg.append(("pp. " if "-" in it["pages"] else "p. ") + it["pages"].replace("-", "–"))
    src = (" " + ", ".join(seg) + ".") if seg else ""
    return f"{auth} “{_end(title)}”{src}{tail}".strip()


def chicago(it):
    names = [n for n in map(parse_name, it.get("authors") or []) if n]
    fmt = []
    for i, n in enumerate(names[:10]):
        if n.get("org"):
            fmt.append(n["last"])
        elif i == 0:
            fmt.append(f"{n['last']}, {n['first']}")
        else:
            fmt.append(f"{n['first']} {n['last']}")
    if len(names) > 10:
        fmt = fmt[:7] + ["et al"]
    if len(fmt) == 2:
        auth = _end(f"{fmt[0]}, and {fmt[1]}")
    else:
        auth = _end(_join(fmt, "and")) if fmt else ""
    title = title_case((it.get("title") or "Untitled").strip())
    doi = it.get("doi")
    tail = f" https://doi.org/{doi}." if doi else (f" {it['url']}." if it.get("url") else "")
    if it.get("kind") in ("book", "graphic"):
        pub = ""
        if it.get("publisher") or it.get("year"):
            place = f"{it['place']}: " if it.get("place") else ""
            pub = " " + place + ", ".join(p for p in (it.get("publisher"), it.get("year")) if p) + "."
        return f"{auth} <i>{title}</i>.{pub}{tail}".strip()
    src = ""
    if it.get("journal"):
        src = f" <i>{title_case(it['journal'])}</i>"
        if it.get("volume"):
            src += f" {it['volume']}"
        if it.get("issue"):
            src += f", no. {it['issue']}"
        if it.get("year"):
            src += f" ({it['year']})"
        if it.get("pages"):
            src += f": {it['pages'].replace('-', '–')}"
        src += "."
    elif it.get("year"):
        src = f" {it['year']}."
    return f"{auth} “{_end(title)}”{src}{tail}".strip()


def all_citations(it):
    out = {}
    for label, fn in (("APA (7th ed.)", apa), ("MLA (9th ed.)", mla), ("Chicago (17th ed.)", chicago)):
        h = re.sub(r"\s+", " ", fn(it))
        out[label] = {"html": h, "text": html.unescape(re.sub(r"</?i>", "", h))}
    return out
