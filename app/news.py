"""The News: the Babel Gazette, two desks, like the Discover catalogue.

Science desk: research press releases, from universities, labs and agencies (Phys.org, ScienceDaily, Medical Xpress and the
institutions' own newsrooms: MIT, NIH, NASA, ESA, Harvard, Cambridge), as rows by subject.
Local desk: for a place you type in (a county and its state; the city is the county seat unless you name one): things
to go to around town first (exhibits, festivals, markets, gatherings), then County, City, State and Country politics
(ordinances, votes, meetings), found through Google News searches. Stories are read inside the Gazette: article()
pulls the text out of the page. Lists are cached for half an hour, articles for six hours.
"""
import concurrent.futures
import html
import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser

import store

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
TTL = 30 * 60
MEDIA = "{http://search.yahoo.com/mrss/}"
DC = "{http://purl.org/dc/elements/1.1/}"

PX = "https://phys.org/rss-feed/{}-news/"
SD = "https://www.sciencedaily.com/rss/{}.xml"
# press releases first: what universities, labs and agencies announce about their own research (through Phys.org,
# ScienceDaily and the institutions' own newsrooms)
SCIENCE = [
    ("labs", "Straight from the labs", ["https://news.mit.edu/rss/research", "https://www.nih.gov/news-releases/feed.xml", "https://www.nasa.gov/news-release/feed/",
                                        "https://www.esa.int/rssfeed/Our_Activities/Space_Science", "https://news.harvard.edu/gazette/section/science-technology/feed/",
                                        "https://www.cam.ac.uk/news/feed"]),
    ("physics", "Physics", [PX.format("physics"), SD.format("matter_energy")]),
    ("space", "Space", [PX.format("space"), SD.format("space_time")]),
    ("life", "Life & biology", [PX.format("biology"), SD.format("plants_animals")]),
    ("health", "Health & medicine", ["https://medicalxpress.com/rss-feed/", SD.format("health_medicine")]),
    ("earth", "Earth & climate", [PX.format("earth"), SD.format("earth_climate")]),
    ("chem", "Chemistry & materials", [PX.format("chemistry"), PX.format("nanotech")]),
    ("tech", "Technology & computing", [PX.format("technology"), SD.format("computers_math")]),
]
OUTLET = {"phys.org": "Phys.org", "medicalxpress.com": "Medical Xpress", "sciencedaily.com": "ScienceDaily", "mit.edu": "MIT News", "nih.gov": "NIH",
          "nasa.gov": "NASA", "esa.int": "ESA", "harvard.edu": "Harvard Gazette", "cam.ac.uk": "University of Cambridge", "science.org": "Science", "nytimes.com": "The New York Times", "bbc.co.uk": "BBC News", "bbc.com": "BBC News", "theguardian.com": "The Guardian",
          "npr.org": "NPR", "newscientist.com": "New Scientist", "arstechnica.com": "Ars Technica", "quantamagazine.org": "Quanta Magazine",
          "scientificamerican.com": "Scientific American"}

_cache = {}
_lock = threading.Lock()
PAGE_HTML = None      # set by the desktop app: url -> page HTML through its browser engine


def _get(url, timeout=15, data=None, headers=None):
    req = urllib.request.Request(url, data=data, headers={"User-Agent": UA, "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                                                          "Accept-Language": "en-US,en;q=0.9", **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _text(s, n=320):
    s = html.unescape(re.sub(r"<[^>]+>", " ", s or ""))
    s = re.sub(r"\s+", " ", s).strip()
    return s if len(s) <= n else s[:n].rsplit(" ", 1)[0] + "…"


def _when(s):
    try:
        return parsedate_to_datetime(s).timestamp()
    except Exception:
        try:
            return time.mktime(time.strptime((s or "")[:19], "%Y-%m-%dT%H:%M:%S"))
        except Exception:
            return 0


def _outlet(link):
    host = (urllib.parse.urlparse(link).hostname or "").removeprefix("www.")
    return next((v for k, v in OUTLET.items() if host == k or host.endswith("." + k)), host)


def _cached(key, ttl, fn):
    with _lock:
        hit = _cache.get(key)
        if hit and time.time() - hit[0] < ttl:
            return hit[1]
    val = fn()
    with _lock:
        _cache[key] = (time.time(), val)
    return val


def feed(url):
    """One RSS feed as a list of stories (cached)."""
    def fetch():
        root = ET.fromstring(_get(url))
        out = []
        for it in root.iter("item"):
            title = _text(it.findtext("title"), 300)
            link = (it.findtext("link") or "").strip()
            if not title or not link:
                continue
            src_el = it.find("source")
            source = (src_el.text or "").strip() if src_el is not None else ""
            if source and title.endswith(" - " + source):          # Google News adds " - Publisher" to headlines
                title = title[: -len(source) - 3]
            img = ""
            for tag in (MEDIA + "content", MEDIA + "thumbnail", "enclosure"):
                for el in it.findall(tag):
                    if el.get("url") and (tag != "enclosure" or (el.get("type") or "image").startswith("image")):
                        img = el.get("url")
                if img:
                    break
            if not img:
                m = re.search(r'<img[^>]+src="([^"]+)"', (it.findtext("description") or "") + (it.findtext("{http://purl.org/rss/1.0/modules/content/}encoded") or ""))
                img = m.group(1) if m else ""
            img = img.replace("/csz/news/tmb/", "/csz/news/800a/")       # phys.org lists 100px thumbnails; this is the full picture
            desc = "" if "news.google.com" in url else _text(it.findtext("description"))
            out.append({"title": title, "link": link, "source": source or _outlet(link), "by": _text(it.findtext(DC + "creator"), 80),
                        "date": _when(it.findtext("pubDate") or it.findtext(DC + "date")), "summary": desc, "image": img})
        return out
    return _cached(("feed", url), TTL, fetch)


def _many(urls, limit=40, mix=False):
    """Several feeds as one list, newest first; mix=True takes turns between them (so one busy newsroom can't fill it)."""
    stories, seen = [], set()
    with concurrent.futures.ThreadPoolExecutor(5) as ex:
        lists = list(ex.map(lambda u: _safe(feed, u), urls))
    if mix:
        lists = [sorted(l, key=lambda s: -s["date"]) for l in lists]
        order = [s for group in __import__("itertools").zip_longest(*lists) for s in group if s]
    else:
        order = sorted((s for l in lists for s in l), key=lambda s: -s["date"])
    for s in order:
        k = re.sub(r"\W+", "", s["title"].lower())[:80]
        if k not in seen:
            seen.add(k)
            stories.append(s)
    return stories[:limit]


def _safe(fn, *a):
    try:
        return fn(*a)
    except Exception as e:
        print("[inkwell] news feed:", e)
        return []


def forget_feeds():
    """↻ on a desk: the feeds are fetched again rather than taken from the half-hour cache."""
    with _lock:
        for k in [k for k in _cache if k[0] == "feed"]:
            del _cache[k]


def science():
    with concurrent.futures.ThreadPoolExecutor(4) as ex:
        rows = list(ex.map(lambda s: {"key": s[0], "label": s[1], "items": _many(s[2], 24, mix=s[0] == "labs")}, SCIENCE))
    return {"sections": rows}


# ---------------------------------------------------------------- the local desk
def place():
    s = store.get_settings()
    return {"county": s.get("news_county") or "", "state": s.get("news_state") or "", "city": s.get("news_city") or "",
            "country": s.get("news_country") or "United States", "seat": s.get("news_seat") or ""}


def set_place(d):
    county = re.sub(r"\s+", " ", str(d.get("county") or "")).strip()[:80]
    state = re.sub(r"\s+", " ", str(d.get("state") or "")).strip()[:60]
    if not county:
        raise ValueError("Type the name of your county.")
    if not re.search(r"county|parish|borough", county, re.I):
        county += " County"
    seat = "" if str(d.get("city") or "").strip() else county_seat(county, state)
    store.set_settings({"news_county": county, "news_state": state, "news_city": str(d.get("city") or "").strip()[:60],
                        "news_country": str(d.get("country") or "United States").strip()[:60] or "United States", "news_seat": seat})
    return place()


def county_seat(county, state):
    """The county seat from Wikidata (P36), so the City section has somewhere to look without you typing it."""
    try:
        q = f"{county}, {state}" if state else county
        d = json.loads(_get("https://www.wikidata.org/w/api.php?" + urllib.parse.urlencode(
            {"action": "wbsearchentities", "search": q, "language": "en", "format": "json", "limit": 1})))
        if not d.get("search"):
            return ""
        qid = d["search"][0]["id"]
        e = json.loads(_get(f"https://www.wikidata.org/wiki/Special:EntityData/{qid}.json"))["entities"][qid]
        seat = (e.get("claims", {}).get("P36") or [{}])[0].get("mainsnak", {}).get("datavalue", {}).get("value", {}).get("id")
        if not seat:
            return ""
        s = json.loads(_get(f"https://www.wikidata.org/wiki/Special:EntityData/{seat}.json"))["entities"][seat]
        return re.sub(r",.*$", "", s.get("labels", {}).get("en", {}).get("value", ""))
    except Exception as e:
        print("[inkwell] county seat lookup:", e)
        return ""


def _gnews(q, days=None):
    if days:
        q += f" when:{days}d"
    return "https://news.google.com/rss/search?" + urllib.parse.urlencode({"q": q, "hl": "en-US", "gl": "US", "ceid": "US:en"})


# what each story is about, for the little labels on the local desk
KINDS = [("vote", r"\bvot(e|es|ed|ing)\b|approv|passes|passed|rejects?|ballot|referendum"), ("ordinance", r"ordinance|bylaw|zoning|code amendment|regulation|\bban\b"),
         ("meeting", r"meeting|hearing|session|town hall|forum|agenda|workshop"), ("election", r"election|candidate|primary|runoff|campaign"),
         ("budget", r"budget|tax|bond|funding|millage|spending")]
# things you can go to (an event row is only these), and what to leave out of it
EVENT = (r"exhibit|exhibition|museum|gallery|festival|\bfest\b|\bfair\b(?! to)|farmers.? market|market day|art walk|open house|workshop|meetup|gathering|celebrat|"
         r"parade|concert series|free concert|block party|cleanup|volunteer|lecture|book (talk|signing)|reading series|screening|film series|"
         r"things to do|this weekend|weekend guide|events? (this|calendar|guide)|halloween|holiday (market|lights)|trunk.or.treat|5k|run/walk|library program|story ?time|class(es)? at")
NOT_EVENT = r"\b(tour (dates|of north america)|world series|nfl|nba|mlb|nhl|arrest|shooting|crash|lawsuit|dies|killed|obituary|stock|earnings|opinion|open letter|fair to|photos:|recap|editorial)\b|^photos"
EVENT_HOSTS = ("patch.com", "eventbrite", "allevents", "visit")


def _kind(title):
    t = title.lower()
    return next((k for k, rx in KINDS if re.search(rx, t)), "")


def _events(city, county, state):
    """Gatherings, exhibits, festivals and markets near you: several searches, kept only when they're something to attend."""
    where = f'("{city}" OR "{county}")' if city else f'"{county}"'
    st = f' "{state}"' if state else ""
    qs = [_gnews(f'{where}{st} (exhibit OR exhibition OR museum OR gallery) opens', 30),
          _gnews(f'{where}{st} (festival OR "farmers market" OR "art walk" OR "block party" OR parade OR fair)', 21),
          _gnews(f'{where}{st} ("things to do" OR "this weekend" OR "events this week")', 10),
          _gnews(f'{where}{st} (workshop OR lecture OR "open house" OR volunteer OR "library" OR meetup)', 21)]
    out = []
    for s in _many(qs, 80):
        t = s["title"].lower()
        if re.search(NOT_EVENT, t):
            continue
        if re.search(EVENT, t):
            s["kind"] = "event"
            out.append(s)
    return out[:24]


def local():
    p = place()
    if not p["county"]:
        return {"place": p, "sections": []}
    county, state, country = p["county"], p["state"], p["country"]
    city = p["city"] or p["seat"]
    st = f' "{state}"' if state else ""
    civic = "(ordinance OR vote OR council OR commissioners OR meeting OR hearing OR budget OR election OR approves)"
    plan = [("county", county, lambda: _many([_gnews(f'"{county}"{st} {civic}', 30), _gnews(f'"{county}" (commissioners OR "commissioners court" OR "board of supervisors")', 30)], 24))]
    if city:
        plan.append(("city", city, lambda: _many([_gnews(f'"{city}"{st} ("city council" OR mayor OR ordinance OR "city hall" OR vote OR meeting)', 30)], 24)))
    if state:
        plan.append(("state", state, lambda: _many([_gnews(f'("{state} Legislature" OR "{state} governor" OR "{state} Senate" OR "{state} House" OR "{state} lawmakers" OR "state lawmakers" OR "{state} attorney general") -firm -litigator -lawyers', 7)], 24)))
    if country:
        nat = '(Congress OR Senate OR "White House" OR "Supreme Court" OR "House votes")' if country.lower() in ("united states", "usa", "us", "u.s.") else f'"{country}" (parliament OR government OR minister OR vote)'
        plan.append(("country", country, lambda: _many([_gnews(nat, 3)], 24)))
    with concurrent.futures.ThreadPoolExecutor(5) as ex:
        ev = ex.submit(_events, city, county, state)
        got = list(ex.map(lambda pl: pl[2](), plan))
    out, shown = [{"key": "events", "label": f"Things to do around {city or county}", "items": ev.result()}], set()
    shown.update(s["link"] for s in out[0]["items"])
    for (key, label, _), items in zip(plan, got):
        items = [s for s in items if s["link"] not in shown]       # a story only once, in the closest section
        shown.update(s["link"] for s in items)
        for s in items:
            s["kind"] = _kind(s["title"])
        out.append({"key": key, "label": label, "items": items})
    return {"place": p, "sections": out}


# ---------------------------------------------------------------- new events, watched for in the background
# With "Tell me about new events" on (Settings), the Local desk's events are checked every few hours, like the
# catalogue restocks itself. Events not seen before are kept in news_alerts.json, for the News button's badge and
# the phone's notifications. The first check only learns what's already there (no flood of "new" events).
ALERTS = None
CHECK_EVERY = 3 * 3600


def _alerts_file():
    import os
    return os.path.join(store.DATA_DIR, "news_alerts.json")


def _alerts_load():
    try:
        with open(_alerts_file(), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"seen": [], "items": [], "checked": 0}


def _alerts_save(d):
    import os
    tmp = _alerts_file() + ".part"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f)
    os.replace(tmp, _alerts_file())


def check_events():
    """One look at the events: returns the new ones (and remembers them)."""
    p = place()
    if not p["county"]:
        return []
    city = p["city"] or p["seat"]
    with _lock:
        for k in [k for k in _cache if k[0] == "feed"]:
            del _cache[k]
    found = _events(city, p["county"], p["state"])
    d = _alerts_load()
    seen, first = set(d["seen"]), not d["seen"] and not d["checked"]
    new = [s for s in found if s["link"] not in seen]
    d["seen"] = (d["seen"] + [s["link"] for s in new])[-600:]
    d["checked"] = time.time()
    if not first:
        now = time.time()
        def where(link):            # the story's own address (what gets shared), not Google News's go-between
            try:
                return real_url(link)
            except Exception:
                return link
        d["items"] = (d["items"] + [{"title": s["title"], "link": where(s["link"]), "source": s.get("source", ""), "date": s.get("date", 0), "at": now} for s in new[:20]])[-60:]
    _alerts_save(d)
    return [] if first else new


def alerts_since(ts=0):
    return [a for a in _alerts_load()["items"] if a["at"] > float(ts or 0)]


def start_watching():
    def loop():
        time.sleep(90)                       # (let the app finish starting)
        while True:
            try:
                if store.get_settings().get("news_alerts") and time.time() - _alerts_load().get("checked", 0) > CHECK_EVERY - 60:
                    n = check_events()
                    if n:
                        print(f"[inkwell] {len(n)} new event(s) on the Local desk")
                        import phonesync
                        phonesync.push_news(alerts_since(time.time() - 120))    # (the iPhones that asked; Android phones look for themselves)
            except Exception as e:
                print("[inkwell] event check skipped:", e)
            time.sleep(15 * 60)
    threading.Thread(target=loop, daemon=True).start()


# ---------------------------------------------------------------- reading a story inside the Gazette
def real_url(link):
    """Google News hands out its own links (news.google.com/rss/articles/...): ask it where they really go."""
    if "news.google.com" not in link:
        return link

    def resolve():
        gid = urllib.parse.urlparse(link).path.rstrip("/").split("/")[-1]
        page = _get(f"https://news.google.com/rss/articles/{gid}").decode("utf-8", "replace")
        sg, ts = re.search(r'data-n-a-sg="([^"]+)"', page), re.search(r'data-n-a-ts="([^"]+)"', page)
        if not sg or not ts:
            return link
        inner = ["garturlreq", [["X", "X", ["X", "X"], None, None, 1, 1, "US:en", None, 1, None, None, None, None, None, 0, 1], "X", "X", 1, [1, 1, 1], 1, 1, None, 0, 0, None, 0],
                 gid, int(ts.group(1)), sg.group(1)]
        body = urllib.parse.urlencode({"f.req": json.dumps([[["Fbv4je", json.dumps(inner), None, "generic"]]])}).encode()
        res = _get("https://news.google.com/_/DotsSplashUi/data/batchexecute", data=body,
                   headers={"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"}).decode("utf-8", "replace")
        return json.loads(json.loads(res.split("\n\n", 1)[1])[0][2])[1]
    try:
        return _cached(("real", link), 7 * 86400, resolve)
    except Exception as e:
        print("[inkwell] couldn't follow a Google News link:", e)
        return link


SKIP = {"script", "style", "noscript", "nav", "header", "footer", "aside", "form", "button", "svg", "figcaption", "iframe", "select", "template"}
BLOCKS = {"p", "h2", "h3", "blockquote", "li"}
JUNK = re.compile(r"^(advertisement|subscribe|sign up|related|read more|share this|follow us|copyright|©|image|photo:|credit:)|newsletter|cookie|all rights reserved", re.I)


class _Body(HTMLParser):
    """The story's paragraphs: every paragraph adds its length to the boxes around it, and the box with the most
    text is the article (menus, comments and footers lose)."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack, self.skip, self.cur, self.paras, self.score, self.meta, self.n = [], 0, None, [], {}, {}, 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "meta":
            k = (a.get("property") or a.get("name") or "").lower()
            if k in ("og:title", "og:image", "og:site_name", "author", "article:published_time", "og:description", "twitter:image"):
                self.meta.setdefault(k, a.get("content") or "")
            return
        if tag in ("br", "img", "hr", "input", "link", "source", "wbr"):
            return
        cls = (a.get("class") or "") + " " + (a.get("id") or "")
        hidden = tag in SKIP or re.search(r"\b(comment|related|newsletter|promo|share|social|advert|sidebar|footer|nav|subscribe|recirc|most-popular)", cls, re.I)
        self.n += 1
        self.stack.append((tag, self.n, bool(hidden)))
        if hidden:
            self.skip += 1
        if tag in BLOCKS and not self.skip and self.cur is None:
            self.cur = [tag, [], [n for _, n, _ in self.stack[:-1]]]

    def handle_endtag(self, tag):
        while self.stack:
            t, n, hidden = self.stack.pop()
            if hidden:
                self.skip -= 1
            if self.cur is not None and t == self.cur[0] and len(self.stack) == len(self.cur[2]):
                text = re.sub(r"\s+", " ", "".join(self.cur[1])).strip()
                if text and not JUNK.search(text[:60]) and (len(text) > 50 or t in ("h2", "h3")):
                    self.paras.append((t, text, self.cur[2]))
                    w = len(text) if t == "p" else len(text) // 3
                    for i, anc in enumerate(reversed(self.cur[2][-4:])):
                        self.score[anc] = self.score.get(anc, 0) + w / (1 + i)
                self.cur = None
            if t == tag:
                break

    def handle_data(self, data):
        if self.cur is not None and not self.skip:
            self.cur[1].append(data)


def article(link):
    """A story for reading in the Gazette: title, byline, picture and paragraphs (some sites only let a few through)."""
    url = real_url(link)

    def read():
        try:
            raw = _get(url, timeout=20).decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            # some sites (Phys.org) turn away plain downloads: open it in the app's own browser engine instead
            if e.code not in (401, 403, 429) or PAGE_HTML is None:
                raise
            raw = PAGE_HTML(url)
            if not raw:
                raise
        p = _Body()
        p.feed(raw)
        best = max(p.score, key=p.score.get) if p.score else None
        blocks = [{"t": t, "x": x} for t, x, anc in p.paras if best is None or best in anc]
        # sites that put the whole text in their structured data: use it when the page itself gives little
        if sum(len(b["x"]) for b in blocks) < 600:
            for m in re.finditer(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', raw, re.S | re.I):
                try:
                    data = json.loads(m.group(1))
                except Exception:
                    continue
                for d in data if isinstance(data, list) else data.get("@graph", [data]) if isinstance(data, dict) else []:
                    body = isinstance(d, dict) and d.get("articleBody")
                    if body and len(body) > 600:
                        blocks = [{"t": "p", "x": x.strip()} for x in re.split(r"\n{1,}", html.unescape(body)) if x.strip()]
                        break
        title = html.unescape(p.meta.get("og:title") or "")
        title = re.sub(r"\s+[|–—-]\s+[^|–—-]{2,40}$", "", title) if re.search(r"\s[|]\s|\s[–—-]\s(?=[^|–—-]{2,40}$)", title) and _outlet(url).split()[-1].lower() in title.lower()[-45:] else title
        seen, clean = set(), []
        for b in blocks:                                        # repeated pull-quotes and the headline itself, once
            k = b["x"][:80]
            if k not in seen and b["x"] != title:
                seen.add(k)
                clean.append(b)
        return {"url": url, "title": title, "site": p.meta.get("og:site_name") or _outlet(url), "by": p.meta.get("author") or "",
                "date": p.meta.get("article:published_time") or "", "image": p.meta.get("og:image") or p.meta.get("twitter:image") or "",
                "dek": html.unescape(p.meta.get("og:description") or ""), "blocks": clean[:120]}
    return _cached(("art", url), 6 * 3600, read)
