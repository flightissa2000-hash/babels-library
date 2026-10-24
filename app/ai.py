"""Offline analysis: subject class, topic, genre, fiction/non-fiction, broad tags, synopsis/abstract.

1. If Ollama (https://ollama.com) is running locally, a local LLM reads the text.
2. Otherwise the built-in offline analyser is used (lexicons, catalogue categories, dictionary-checked phrases).
Nothing is sent over the internet by this module.
"""
import bisect
import gzip
import json
import math
import os
import re
import urllib.request
from collections import Counter

import taxonomy as T

HERE = os.path.dirname(os.path.abspath(__file__))
_DICT = None


def dictionary():
    global _DICT
    if _DICT is None:
        try:
            with gzip.open(os.path.join(HERE, "data", "words.txt.gz"), "rt") as f:
                words = f.read().split()
        except OSError:
            words = []
        _DICT = (set(words), sorted(words), sorted(w[::-1] for w in words))
    return _DICT


def _is_fragment(w):
    """True for text-extraction debris like 'tudent' (student) or 'languag' (language)."""
    words, fwd, rev = dictionary()
    i = bisect.bisect_left(fwd, w)
    if i < len(fwd) and fwd[i].startswith(w) and fwd[i] != w:
        return True
    r = w[::-1]
    j = bisect.bisect_left(rev, r)
    return j < len(rev) and rev[j].startswith(r) and rev[j] != r


def good_word(w, counts):
    words = dictionary()[0]
    if not words:
        return True
    w = w.lower().strip("-'")
    if w in words or (w.endswith("s") and w[:-1] in words):
        return True
    # technical terms not in the dictionary: long, frequent, and not a broken piece of a real word
    return len(w) >= 6 and counts.get(w, 0) >= 3 and not _is_fragment(w)


STOP = set("""a about above after again against all also am an and any are as at be because been before being below between both
but by can cannot could did do does doing down during each few for from further had has have having he her here hers herself him
himself his how i if in into is it its itself let me more most my myself no nor not of off on once only or other ought our ours
ourselves out over own same she should so some such than that the their theirs them themselves then there these they this those
through to too under until up very was we were what when where which while who whom why with would you your yours yourself
yourselves et al fig figure table tables figures section paper study studies result results using used use based however also may
one two three four five new first second third within among across via thus therefore although whether either neither per eg ie
data analysis approach method methods show shows shown found find journal vol pp doi http https www org com abstract
introduction conclusion conclusions discussion references keywords copyright license author authors university department
said like just will well much many even still back get got go went see seen make made way time year years thing things
examines examine considers consider measured measure suggest suggests present presents presented discuss discusses including
include includes explores explore propose proposes need needs understand outperforms chapter chapters book books page pages prior
large small high low different important significant various several case cases example examples part parts number numbers
eq eqs equation note notes problem problems exercise exercises solution solutions value values given take taken
relevant general specific following total main simple recent current possible certain particular previous typical
common overall further additional various respective corresponding key major minor good better best great""".split())
VERBISH = re.compile(r"(ed|ing|ly)$")


def _words(text):
    return re.findall(r"[a-zà-ÿ][a-zà-ÿ\-']{1,}", (text or "").lower())


def _density(counts, total, triggers):
    hits = sum(counts.get(t, 0) for t in triggers.split())
    return hits, hits * 10000 / max(total, 1)


def key_phrases(text, counts, n=3, exclude=()):
    """Two- or three-word phrases that recur, made only of real words."""
    text = text[:80000]
    excl = {w.lower() for w in exclude}
    phrases = []
    for s in re.split(r"[\.\!\?\;\:\(\)\[\]\n,\"“”]", text.lower()):
        cur = []
        for w in re.findall(r"[a-z][a-z\-]{2,}", s):
            if w in STOP or w in excl or len(w) > 25 or not good_word(w, counts):
                if len(cur) >= 2:
                    phrases.append(tuple(cur))
                cur = []
            else:
                cur.append(w)
        if len(cur) >= 2:
            phrases.append(tuple(cur))
    cleaned = []
    for p in phrases:
        p = list(p)
        while p and VERBISH.search(p[0]):
            p.pop(0)
        while p and VERBISH.search(p[-1]):
            p.pop()
        if 2 <= len(p) <= 3:
            cleaned.append(tuple(p))
    pc = Counter(cleaned)
    out = []
    for p, c in pc.most_common(40):
        if c < 4:
            break
        label = " ".join(p)
        if T.BANNED_TAG_WORDS.search(label) or any(label in o.lower() or o.lower() in label for o in out):
            continue
        out.append(label[0].upper() + label[1:])
        if len(out) >= n:
            break
    return out


def broad_tags(counts, total, short=False, fiction=False):
    scored = []
    for tag, trig in T.TAG_VOCAB.items():
        if (tag in T.FICTION_ONLY_TAGS) != bool(fiction) and tag in T.FICTION_ONLY_TAGS:
            continue
        hits, dens = _density(counts, total, trig)
        need_hits, need_dens = (2, 0) if short else (4, 2.5)
        if hits >= need_hits and dens >= need_dens:
            scored.append((dens, tag))
    scored.sort(reverse=True)
    return [t for _, t in scored[:5]]


def clean_tags(tags, banned=()):
    out, seen = [], set()
    bl = {b.lower() for b in banned if b}
    for t in tags:
        t = re.sub(r"\s+", " ", str(t)).strip(" .,;:-")
        if not t or len(t) > 40 or t.lower() in seen or t.lower() in bl or T.BANNED_TAG_WORDS.search(t):
            continue
        out.append(t[0].upper() + t[1:])
        seen.add(t.lower())
    return out


def pick_topic(counts, total, title_words, fiction):
    if fiction:
        return "Fiction"
    best, best_s = T.GENERAL_TOPIC, 0.0
    for name, (_, _, trig) in T.TOPICS.items():
        if not trig:
            continue
        s = 0.0
        for k in trig.split():
            c = counts.get(k, 0)
            if c:
                s += 1 + math.log(c)
            if k in title_words:
                s += 4
        s /= math.log(total + 50)
        if s > best_s:
            best, best_s = name, s
    return best if best_s > 0.35 else T.GENERAL_TOPIC


FICTION_LEX = {
    "Fantasy": "magic magical spell spells sorcery sorcerer wizard wizards dragon dragons sword swords knight knights kingdom throne prophecy realm elf elves dwarf dwarves quest enchanted storm shard shards highprince stormlight",
    "Science Fiction": "starship spaceship planet planets alien aliens galaxy robot robots android colony orbit laser cyborg spacecraft station europa",
    "Horror": "scream screamed screaming ghost ghosts monster monsters corpse corpses terror nightmare haunted demon demons undead",
    "Mystery & Crime": "detective murder murdered clue clues inspector suspect alibi investigation",
    "Thriller & Suspense": "agent gun mission bomb spy target operative assassin hostage",
    "Romance": "love kiss kissed lover desire romance wedding embrace",
    "Superhero": "superhero superheroes villain villains vigilante",
    "Historical Fiction": "duke carriage colonel parliament victorian",
}


def fiction_genre(counts, total):
    best, best_d = None, 0.0
    for g, trig in FICTION_LEX.items():
        _, d = _density(counts, total, trig)
        if g == "Horror":
            d *= 0.6  # horror words turn up in every genre; ask for more evidence
        if d > best_d:
            best, best_d = g, d
    return best if best_d >= 6 else "Literary Fiction"


def looks_fiction(text, description=""):
    d = (description or "").lower()
    if re.search(r"\b(novel|short stories|a story|fiction|fantasy|thriller|saga|trilogy|epic)\b", d):
        return 1
    sample = (text or "")[:60000]
    if len(sample) < 3000:
        return 0 if d else None
    k = max(len(sample) / 1000, 1)
    quotes = len(re.findall(r"[\"“”]", sample)) / k
    said = len(re.findall(r"\b(said|asked|replied|whispered|shouted)\b", sample, re.I)) / k
    academic = len(re.findall(r"\b(research|study|evidence|analysis|figure|equation|according|data|exercise|lesson)\b", sample, re.I)) / k
    return 1 if (quotes * 0.15 + said * 1.5) > (academic + 0.6) else 0


JUNK_LINE = re.compile(r"doi|journal|©|copyright|received|accepted|published|https?:|www\.|@|universit|department|institute|"
                       r"laborator|school of|college|faculty|keywords|e-?mail|correspond|licen[cs]e|vol\.|issn|isbn", re.I)


def _upper_heavy(x):
    w = x.split()
    return sum(1 for t in w if len(t) > 2 and t.isupper()) / max(len(w), 1) > 0.25


def _prose(s):
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"^(a ?b ?s ?t ?r ?a ?c ?t)[\s.:—–-]*", "", s, flags=re.I)
    s = re.sub(r"(\w)- (\w)", r"\1\2", s)  # re-join words hyphenated across lines
    sents = [x for x in re.split(r"(?<=[.!?])\s+(?=[A-Z•])", s) if len(x) > 50 and not JUNK_LINE.search(x)
             and not x.lstrip().startswith(("•", "-", "–", "·")) and not _upper_heavy(x)]
    return " ".join(sents[:4])[:1200]


def find_abstract(text):
    t = re.sub(r"[ \t]+", " ", (text or "")[:25000])
    for m in re.finditer(r"(?<![a-z] )\b(a ?b ?s ?t ?r ?a ?c ?t)\b[\s\.:—–-]*", t, re.I):
        before = t[max(0, m.start() - 12):m.start()].lower()
        if "graphical" in before or "g r a p h i c a l" in before:
            continue
        rest = t[m.end():]
        end = re.search(r"\n\s*(keywords?|key words|1\.?\s+introduction|introduction|©|received)\b", rest, re.I)
        body = _prose(rest[:end.start()] if end else rest[:2500])
        if len(body) > 120:
            return body
    # no labelled abstract: the first real paragraph of prose
    return _prose(t[:8000])


def find_blurb(text):
    """Back-cover style description printed in a book's front matter ('This book…', 'This textbook…')."""
    t = re.sub(r"\s+", " ", (text or "")[:20000])
    m = re.search(r"(?:^|[.!?]\s)((?:This|The) (?:new |second |third |revised )?(?:edition of this )?(?:book|textbook|text|volume|guide|edition)\b[^.]{20,}\.(?:\s[A-Z][^.]{20,}\.){0,3})", t)
    return _prose(m.group(1)) if m else ""


def looks_like_synopsis(s):
    s = (s or "").strip()
    if len(s) < 80 or re.search(r"PUBLISHER|EDITOR|MANAGER|©|ISBN|Contents\b", s):
        return False
    words = s.split()
    caps = sum(1 for w in words if len(w) > 2 and w.isupper())
    return caps / max(len(words), 1) < 0.15 and s.count(".") >= 1


def builtin_analyze(kind, meta, text):
    title = meta.get("title", "") or ""
    synopsis = meta.get("description", "") or ""
    cats = list(meta.get("categories") or []) + list(meta.get("subjects") or [])
    blob = "\n".join([title, synopsis, meta.get("keywords", "") or "", text or ""])
    words = _words(blob)
    counts = Counter(words)
    total = len(words)
    title_words = set(_words(title))

    cat_genre, cat_fiction = T.genre_from_categories(cats)
    if kind == "article":
        fiction = 0
    elif kind == "graphic":
        fiction = cat_fiction if cat_fiction is not None else 1
    else:
        fiction = cat_fiction if cat_fiction is not None else looks_fiction(text, synopsis)
        fiction = 0 if fiction is None else fiction

    topic = pick_topic(counts, total, title_words, fiction == 1)
    res = {"topic": topic, "subject": T.SUBJECT_OF.get(topic, "General Works"), "fiction": fiction}

    if kind != "article":
        if cat_genre and (fiction == 1) == (cat_genre in T.FICTION_GENRES):
            res["genre"] = cat_genre
        elif fiction == 1:
            res["genre"] = fiction_genre(counts, total) if total > 300 else (cat_genre or None)
        else:
            res["genre"] = cat_genre or (T.TOPICS.get(topic, (None, None))[1]) or "Reference"

    name_parts = [w for a in meta.get("authors", []) for w in re.findall(r"[A-Za-z]+", a)]
    short = total < 800
    tags = broad_tags(counts, total, short=short, fiction=fiction == 1)[:4]
    tags += [c for c in meta.get("tag_hints", []) if c][:2]
    if meta.get("keywords"):
        tags += [k.strip() for k in re.split(r"[;,]", meta["keywords"]) if 2 < len(k.strip()) < 30][:2]
    if not short and fiction != 1 and len(tags) < 4:
        tags += key_phrases(text or blob, counts, n=1, exclude=name_parts)
    banned = [meta.get("series"), title, res.get("genre"), "Graphic novel", "Comics", "Manga"]
    res["tags"] = clean_tags(tags, banned)[:6]

    # synopsis for books (never a machine summary of the pages); abstract for articles
    if kind == "article":
        res["summary"] = synopsis or find_abstract(text)
    else:
        res["summary"] = synopsis or (find_blurb(text) if fiction != 1 else "")
    return res


# ---------------- Ollama (local LLM) ----------------
_ollama_cache = {}


def ollama_available(url, timeout=1.5, max_age=60):
    """Installed Ollama models (cached for a minute: on Windows a refused localhost connection can take seconds)."""
    import time as _t
    hit = _ollama_cache.get(url)
    if hit and _t.time() - hit[0] < max_age:
        return hit[1]
    res = _ollama_probe(url, timeout)
    _ollama_cache[url] = (_t.time(), res)
    return res


def _ollama_probe(url, timeout):
    if not url:
        return None
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/api/tags", timeout=timeout) as r:
            data = json.loads(r.read())
        return [m.get("name") for m in data.get("models", [])]
    except Exception:
        return None


def ollama_analyze(url, model, kind, meta, text):
    topics = ", ".join(T.TOPICS)
    genres = ", ".join(T.FICTION_GENRES + T.NONFICTION_GENRES)
    excerpt = (text or "")[:7000]
    what = {"article": "a research article", "book": "a book", "graphic": "a graphic novel or comic"}.get(kind, kind)
    prompt = f"""You are a librarian cataloguing {what}. Reply ONLY with JSON:
{{"fiction": true or false,
 "topic": one of [{topics}] (what the work is about; use "Fiction" for any novel or story),
 "genre": one of [{genres}] {"(use null for research articles)" if kind == "article" else ""},
 "tags": 3-6 BROAD subject tags (1-3 common words each, e.g. "Electrochemistry", "Epic fantasy", "Language learning"); no names, no publishers, no media types,
 "series": the series name if this work belongs to one (else ""),
 "synopsis": {"the paper's abstract in 2-4 sentences" if kind == "article" else "a back-cover style synopsis of the plot or contents in 2-4 sentences (do not summarise front matter)"},
 "title": the work's real title if you can tell (else ""),
 "authors": list of author names if you can tell (else [])}}

Metadata: {json.dumps({k: meta.get(k) for k in ("title", "authors", "year", "categories", "keywords", "series") if meta.get(k)})}
Excerpt:
{excerpt}"""
    body = json.dumps({"model": model, "prompt": prompt, "format": "json", "stream": False,
                       "options": {"temperature": 0.2, "num_ctx": 8192}}).encode()
    req = urllib.request.Request(url.rstrip("/") + "/api/generate", data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=240) as r:
        resp = json.loads(r.read())
    data = json.loads(resp.get("response") or "{}")
    res = {}
    if isinstance(data.get("fiction"), bool):
        res["fiction"] = 1 if data["fiction"] else 0
    if data.get("topic") in T.TOPICS:
        res["topic"] = data["topic"]
        res["subject"] = T.SUBJECT_OF[data["topic"]]
    if kind != "article" and data.get("genre") in (T.FICTION_GENRES + T.NONFICTION_GENRES):
        res["genre"] = data["genre"]
    tags = data.get("tags") or []
    if isinstance(tags, str):
        tags = re.split(r"[;,]", tags)
    res["tags"] = clean_tags(tags, [meta.get("series"), meta.get("title")])[:6]
    if isinstance(data.get("series"), str) and data["series"].strip():
        res["series"] = data["series"].strip()[:120]
    if isinstance(data.get("synopsis"), str) and len(data["synopsis"].strip()) > 40:
        res["_synopsis"] = data["synopsis"].strip()[:900]
    if isinstance(data.get("title"), str) and 3 < len(data["title"]) < 250:
        res["_title"] = data["title"].strip()
    if isinstance(data.get("authors"), list):
        res["_authors"] = [str(a).strip() for a in data["authors"] if str(a).strip()][:12]
    return res


def analyze(kind, meta, text, settings):
    base = builtin_analyze(kind, meta, text)
    source = "builtin"
    models = ollama_available(settings.get("ollama_url", ""))
    if models:
        model = settings.get("ollama_model") or models[0]
        if not any(m == model or m.split(":")[0] == model for m in models):
            model = models[0]
        try:
            llm = ollama_analyze(settings["ollama_url"], model, kind, meta, text)
            syn = llm.pop("_synopsis", None)
            for k, v in llm.items():
                if v not in (None, "", []):
                    base[k] = v
            if syn and not base.get("summary"):
                base["summary"] = syn  # only when no publisher synopsis / abstract exists
            if base.get("fiction") == 1:
                base["topic"], base["subject"] = "Fiction", T.SUBJECT_OF["Fiction"]
            source = "ollama:" + model
        except Exception as e:
            print("[ai] ollama failed, using built-in analyser:", e)
    base["ai_source"] = source
    return base
