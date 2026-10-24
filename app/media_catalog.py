"""The Big Book Catalogue's other departments: manga (AniList), comics, movies and TV (Wikipedia).

Every list item has the same shape as a book in the catalogue (title, authors, year, cover, blurb, link, wiki), plus
"cat" so the page knows what it is. Lists are cached like the book lists (shown at once, refreshed in the background).
"""
import datetime
import json
import re
import time
import urllib.parse

import discover
import journal
import lookup

CATS = ("book", "manga", "comic", "movie", "tv", "animation")
YEAR = datetime.date.today().year


# ---------------------------------------------------------------- manga: AniList
_AL_LIST = """query ($page: Int, $sort: [MediaSort], $genres: [String], $tags: [String], $from: FuzzyDateInt, $to: FuzzyDateInt, $search: String) {
  Page(page: $page, perPage: 40) { media(type: MANGA, isAdult: false, sort: $sort, genre_in: $genres, tag_in: $tags,
      startDate_greater: $from, startDate_lesser: $to, search: $search, format_in: [MANGA, ONE_SHOT]) {
    id title { romaji english } startDate { year } averageScore popularity genres description(asHtml: false)
    coverImage { extraLarge large } siteUrl countryOfOrigin
    staff(perPage: 4, sort: RELEVANCE) { edges { role node { name { full } } } } } } }"""
_AL_ONE = """query ($id: Int) { Media(id: $id, type: MANGA) {
    id title { romaji english } description(asHtml: false) averageScore popularity genres siteUrl volumes status
    tags { name rank isAdult isMediaSpoiler } externalLinks { site url type language isDisabled }
    reviews(sort: RATING_DESC, perPage: 4) { nodes { summary body(asHtml: false) score user { name } } } } }"""

MANGA_AISLES = [("trending", "Trending this month", {"sort": ["TRENDING_DESC"]}),
                ("new", "New this year", {"sort": ["POPULARITY_DESC"], "new": True}),
                ("popular", "All-time favourites", {"sort": ["POPULARITY_DESC"]}),
                ("romance", "Romance", {"genres": ["Romance"]}), ("comedy", "Comedy", {"genres": ["Comedy"]}),
                ("fantasy", "Fantasy", {"genres": ["Fantasy"]}), ("action", "Action", {"genres": ["Action"]}),
                ("horror", "Horror", {"genres": ["Horror"]}), ("scifi", "Science fiction", {"genres": ["Sci-Fi"]}),
                ("mystery", "Mystery", {"genres": ["Mystery"]}), ("drama", "Drama", {"genres": ["Drama"]}),
                ("slice", "Slice of life", {"genres": ["Slice of Life"]}), ("psych", "Psychological", {"genres": ["Psychological"]}),
                ("sports", "Sports", {"genres": ["Sports"]}), ("yuri", "Yuri", {"tags": ["Yuri"]}),
                ("bl", "Boys' Love", {"tags": ["Boys' Love"]}), ("seinen", "Seinen", {"tags": ["Seinen"]}),
                ("josei", "Josei", {"tags": ["Josei"]})]


def _al_item(m):
    t = m.get("title") or {}
    who = [((e.get("node") or {}).get("name") or {}).get("full") for e in ((m.get("staff") or {}).get("edges") or [])
           if re.match(r"(story|art|original)", (e.get("role") or "").lower()) and "(" not in (e.get("role") or "")]
    desc = re.sub(r"\(Source:[^)]*\)|<[^>]+>", "", m.get("description") or "").strip()
    score = m.get("averageScore")
    return {"cat": "manga", "title": t.get("english") or t.get("romaji") or "", "authors": [w for w in who if w][:2],
            "year": (m.get("startDate") or {}).get("year"), "cover": (m.get("coverImage") or {}).get("extraLarge") or (m.get("coverImage") or {}).get("large") or "",
            "blurb": desc, "link": m.get("siteUrl") or "", "al": m.get("id"), "genres": m.get("genres") or [],
            "country": m.get("countryOfOrigin") or "", "rating": round(score / 20, 1) if score else None,
            "readers": m.get("popularity")}


def _al_list(page=1, sort=None, genres=None, tags=None, yfrom=None, yto=None, search=None, new=False):
    v = {"page": page, "sort": sort or ["POPULARITY_DESC"]}
    if genres:
        v["genres"] = genres
    if tags:
        v["tags"] = tags
    if new:
        yfrom = yfrom or YEAR
    if yfrom:
        v["from"] = int(yfrom) * 10000           # FuzzyDateInt: YYYYMMDD
    if yto:
        v["to"] = (int(yto) + 1) * 10000
    if search:
        v["search"] = search
        v["sort"] = ["SEARCH_MATCH"]
    d = lookup._al_post(_AL_LIST, v)
    return [_al_item(m) for m in ((d.get("data") or {}).get("Page") or {}).get("media") or []]


_AL_STAFF = """query ($q: String) { Staff(search: $q) { name { full } staffMedia(type: MANGA, perPage: 50, sort: [POPULARITY_DESC]) { nodes {
    id title { romaji english } startDate { year } averageScore popularity genres description(asHtml: false) isAdult format
    coverImage { extraLarge large } siteUrl countryOfOrigin
    staff(perPage: 4, sort: RELEVANCE) { edges { role node { name { full } } } } } } } }"""


def manga_by_author(name):
    """Every manga a mangaka worked on, best known first (from their AniList staff page)."""
    d = lookup._al_post(_AL_STAFF, {"q": name})
    st = (d.get("data") or {}).get("Staff") or {}
    nodes = (st.get("staffMedia") or {}).get("nodes") or []
    out, seen = [], set()
    for m in nodes:
        if m.get("isAdult") or m.get("format") not in ("MANGA", "ONE_SHOT", None) or m.get("id") in seen:
            continue
        seen.add(m.get("id"))
        out.append(_al_item(m))
    return out


# the official places to read a manga online, best first: free chapter sites, then the publishers' own readers
READ_SITES = ["MANGA Plus", "WEBTOON", "Webtoon", "Tapas", "Comikey", "K MANGA", "Azuki", "INKR", "MANGA MILLION",
              "VIZ", "Kodansha", "J-Novel Club", "Yen Press", "Seven Seas", "Tappytoon", "Lezhin", "Pocket Comics", "Manta"]


def read_links(m):
    """English-language official readers from AniList's links (AniList lists no pirate sites)."""
    rank = lambda l: next((i for i, s in enumerate(READ_SITES) if s.lower() in l["site"].lower()), len(READ_SITES))
    out, seen = [], set()
    for l in sorted((l for l in m.get("externalLinks") or [] if l.get("type") == "STREAMING" and not l.get("isDisabled")
                     and (l.get("language") or "English") == "English" and l.get("url")), key=rank):
        if l["site"] not in seen:                 # VIZ often has two links (series page, chapters): keep the first
            seen.add(l["site"])
            out.append({"label": l["site"], "url": l["url"]})
    return out


def manga_info(al_id):
    d = lookup._al_post(_AL_ONE, {"id": int(al_id)})
    m = (d.get("data") or {}).get("Media") or {}
    desc = re.sub(r"\(Source:[^)]*\)|<br\s*/?>", "\n", m.get("description") or "")
    desc = re.sub(r"<[^>]+>", "", desc).strip()
    tags = [t["name"] for t in m.get("tags") or [] if (t.get("rank") or 0) >= 70 and not t.get("isAdult") and not t.get("isMediaSpoiler")]
    reviews = []
    for r in ((m.get("reviews") or {}).get("nodes") or [])[:4]:
        body = re.sub(r"<[^>]+>|~!|!~|__|\*\*|#+\s|\[(.*?)\]\(.*?\)|img\d*\(.*?\)|youtube\(.*?\)", lambda x: x.group(1) or "", r.get("body") or "")
        reviews.append({"by": (r.get("user") or {}).get("name") or "a reader", "rating": round((r.get("score") or 0) / 20, 1) or None,
                        "text": (r.get("summary") or "") + ("\n\n" if r.get("summary") else "") + re.sub(r"\s+\n", "\n", body).strip()[:1500]})
    genre = next((g2 for g1, g2 in lookup._AL_GENRES if g1 in (m.get("genres") or [])), None)
    score = m.get("averageScore")
    return {"intro": desc, "genre": genre, "genres": (m.get("genres") or []) + tags[:3], "rating": round(score / 20, 1) if score else None,
            "ratings": m.get("popularity"), "reviews": reviews, "volumes": m.get("volumes"), "status": m.get("status"),
            "read": read_links(m), "links": [{"label": "AniList", "url": m.get("siteUrl")}] if m.get("siteUrl") else []}


# ---------------------------------------------------------------- comics, movies, TV: Wikipedia
KINDS = {
    "comic": {"tpl": "Infobox comic book title", "ok": r"comic|graphic novel|webcomic|manhwa", "noun": "comic",
              "strip": r"comics?|graphic novel|webcomic|comic book|comic strip"},
    "movie": {"tpl": "Infobox film", "ok": r"\bfilm\b|\bmovie\b|animated feature", "noun": "film", "strip": r"(?:\d{4} )?(?:[\w\s-]+ )?film"},
    "tv": {"tpl": "Infobox television", "ok": r"television|tv series|sitcom|miniseries|anime series|animated series|streaming series|web series|reality",
           "noun": "television series", "strip": r"(?:\w+ )?(?:tv|television) series|miniseries|(?:\d{4} )?(?:[\w\s-]+ )?tv series"},
}
NOT_IT = re.compile(r"\b(character|franchise|list of|episode|season \d|soundtrack|album|song|video game|novel|actor|actress|director|award|festival)\b", re.I)

AISLES = {
    "comic": [("trending", "Trending this month", None), ("new", "New this year", ('"{y} comic"', "create_timestamp_desc")),
              ("superhero", "Superheroes", ('"superhero" comic', "incoming_links_desc")),
              ("graphic", "Graphic novels", ('"graphic novel"', "incoming_links_desc")),
              ("horror", "Horror", ('"horror comic"', "incoming_links_desc")), ("fantasy", "Fantasy", ('"fantasy comic"', "incoming_links_desc")),
              ("scifi", "Science fiction", ('"science fiction comic"', "incoming_links_desc")), ("crime", "Crime", ('"crime comic"', "incoming_links_desc")),
              ("humour", "Humour", ('"humor comic" OR "comedy comic"', "incoming_links_desc")), ("web", "Webcomics", ('webcomic', "incoming_links_desc")),
              ("european", "European comics", ('"Franco-Belgian" OR "bande dessinÃ©e"', "incoming_links_desc"))],
    "movie": [("trending", "Trending this month", None), ("new", "New this year", ('"{y} film"', "create_timestamp_desc")),
              ("action", "Action", ('"action film"', "incoming_links_desc")), ("comedy", "Comedy", ('"comedy film"', "incoming_links_desc")),
              ("drama", "Drama", ('"drama film"', "incoming_links_desc")), ("horror", "Horror", ('"horror film"', "incoming_links_desc")),
              ("scifi", "Science fiction", ('"science fiction film"', "incoming_links_desc")), ("fantasy", "Fantasy", ('"fantasy film"', "incoming_links_desc")),
              ("animated", "Animated", ('"animated film"', "incoming_links_desc")), ("thriller", "Thriller", ('"thriller film"', "incoming_links_desc")),
              ("romance", "Romance", ('"romance film" OR "romantic comedy"', "incoming_links_desc")), ("doc", "Documentary", ('"documentary film"', "incoming_links_desc")),
              ("war", "War", ('"war film"', "incoming_links_desc")), ("western", "Western", ('"western film"', "incoming_links_desc")),
              ("kaiju", "Monsters & kaiju", ('kaiju OR "monster film"', "incoming_links_desc")), ("musical", "Musicals", ('"musical film"', "incoming_links_desc"))],
    "tv": [("trending", "Trending this month", None), ("new", "New this year", ('"{y}" "television series"', "create_timestamp_desc")),
           ("drama", "Drama", ('"drama television series"', "incoming_links_desc")), ("comedy", "Comedy", ('sitcom OR "comedy television series"', "incoming_links_desc")),
           ("crime", "Crime", ('"crime drama" television', "incoming_links_desc")), ("scifi", "Science fiction", ('"science fiction television series"', "incoming_links_desc")),
           ("fantasy", "Fantasy", ('"fantasy television series"', "incoming_links_desc")), ("anime", "Anime", ('"anime television series"', "incoming_links_desc")),
           ("animated", "Animated", ('"animated television series" OR "animated sitcom"', "incoming_links_desc")),
           ("mini", "Miniseries", ('miniseries', "incoming_links_desc")), ("doc", "Documentary", ('"documentary television series"', "incoming_links_desc")),
           ("reality", "Reality", ('"reality television"', "incoming_links_desc")), ("horror", "Horror", ('"horror television series"', "incoming_links_desc"))],
}


# films: every film sits in a "<year> films" category, and its genre categories ("American science fiction action
# films") name the genre, so both are checked there rather than by phrase search, which matches anywhere in the article
FILM_CATS = {"action": r"action", "comedy": r"comedy", "drama": r"drama", "horror": r"horror", "scifi": r"science fiction",
             "fantasy": r"fantasy", "animated": r"animated|animation", "thriller": r"thriller", "romance": r"romance|romantic",
             "doc": r"documentary", "war": r"war films|war drama", "western": r"western", "musical": r"musical",
             "kaiju": r"kaiju|giant monster|godzilla"}
# TV and comics: an aisle keeps the titles whose one-line description names its genre
GENRE_WORDS = {
    "tv": {"drama": r"drama", "comedy": r"comed|sitcom", "crime": r"crime|police|detective|procedural", "scifi": r"science fiction|sci-fi",
           "fantasy": r"fantasy", "anime": r"anime", "animated": r"animat|cartoon", "mini": r"miniseries|limited series",
           "doc": r"documentar|docuseries", "reality": r"reality|competition|game show", "horror": r"horror"},
    "comic": {"superhero": r"superhero|marvel|dc comics", "graphic": r"graphic novel", "horror": r"horror", "fantasy": r"fantasy",
              "scifi": r"science fiction|sci-fi", "crime": r"crime|noir|detective", "humour": r"humou?r|comed|comic strip|satir",
              "web": r"webcomic|webtoon", "european": r"franco|belgian|french|italian|spanish|european|bande"},
}


def _year_cats(yfrom=None, yto=None):
    if not (yfrom or yto):
        return ""
    first, last = int(yfrom or 1900), min(int(yto or YEAR), YEAR + 1)
    return ' incategory:"' + "|".join(f"{y} films" for y in range(max(first, last - 60), last + 1)) + '"'


def _film_genre_ok(items, subject):
    """Keep the films that Wikipedia files under the aisle's genre."""
    want = re.compile(FILM_CATS[subject], re.I)
    cats = {}
    titles = [it["wiki"] for it in items]
    for i in range(0, len(titles), 20):
        params = {"action": "query", "format": "json", "formatversion": "2", "prop": "categories", "cllimit": "max",
                  "clshow": "!hidden", "titles": "|".join(titles[i:i + 20])}
        for _ in range(6):
            d = discover._json(discover.WP + urllib.parse.urlencode(params))
            for p in (d.get("query") or {}).get("pages") or []:
                cats.setdefault(p["title"], []).extend(c["title"] for c in p.get("categories") or [])
            if "continue" not in d:
                break
            params.update(d["continue"])
    return [it for it in items if any(want.search(c) and c.endswith("films") for c in cats.get(it["wiki"], []))]


def _wp_item(cat, pg):
    k = KINDS[cat]
    desc = (pg.get("description") or "").strip()
    title = pg.get("title") or ""
    if not re.search(k["ok"], desc, re.I) or NOT_IT.search(desc) and not re.search(k["ok"], desc.split(" by ")[0], re.I):
        return None
    if re.search(r"\bcharacters?\b|\bteam\b|\bpublisher\b|\bimprint\b", desc, re.I) or re.search(r"\((?:character|comics|franchise|android)\)$", title, re.I):
        return None    # "Marvel Comics character", "John Stewart (character)": people in comics, not comics
    if cat == "comic" and re.search(r"\b(?:super)?(?:hero|villain|heroine)\b", desc, re.I) and not re.search(r"series|book|title|novel|strip|magazine|anthology", desc, re.I):
        return None    # "DC Comics superhero" is a person too
    if re.match(r"(list|lists|index|timeline|outline) of\b", title, re.I):
        return None
    shown = re.sub(r"\s*\((?:" + k["strip"] + r")\)$", "", title, flags=re.I)
    by = re.search(r"\b(?:by|directed by|created by)\s+(.+?)\s*$", desc)
    y = re.search(r"\b(1[89]\d\d|20\d\d)\b", desc + " " + title)
    return {"cat": cat, "title": shown, "authors": [by.group(1)] if by else [], "year": int(y.group(1)) if y else None,
            "cover": (pg.get("thumbnail") or {}).get("source", ""), "blurb": desc, "wiki": title,
            "link": pg.get("fullurl") or "https://en.wikipedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_"))}


def _wp_search(cat, q, sort="incoming_links_desc", page=0, limit=40):
    params = {"action": "query", "format": "json", "formatversion": "2", "generator": "search",
              "gsrsearch": f'{q} hastemplate:"{KINDS[cat]["tpl"]}"', "gsrlimit": limit, "gsrnamespace": 0,
              "prop": "pageimages|description|info", "piprop": "thumbnail", "pilicense": "any", "pithumbsize": discover.THUMB_W, "inprop": "url"}
    if sort != "relevance":
        params["gsrsort"] = sort
    if page:
        params["gsroffset"] = page * limit
    d = discover._json(discover.WP + urllib.parse.urlencode(params))
    pages = sorted((d.get("query") or {}).get("pages") or [], key=lambda x: x.get("index", 0))
    return [x for x in (_wp_item(cat, p) for p in pages) if x]


def _in_years(it, yfrom, yto):
    y = it.get("year")
    if not (yfrom or yto):
        return True
    if not y:
        return False
    return (not yfrom or int(y) >= int(yfrom)) and (not yto or int(y) <= int(yto))


def _trending_wp(cat):
    titles = discover.top_viewed_titles()
    out, seen = [], set()
    for pg in sorted(discover._wp_pages(titles), key=lambda p: p["index"]):
        it = _wp_item(cat, pg)
        if it and journal.norm(it["title"]) not in seen:
            seen.add(journal.norm(it["title"]))
            out.append(it)
        if len(out) >= 60:
            break
    return out


# ---------------------------------------------------------------- animation: anime (AniList) and western animation (Wikipedia)
_AL_ANIME = """query ($page: Int, $sort: [MediaSort], $genres: [String], $formats: [MediaFormat], $from: FuzzyDateInt, $to: FuzzyDateInt, $search: String) {
  Page(page: $page, perPage: 40) { media(type: ANIME, isAdult: false, sort: $sort, genre_in: $genres, format_in: $formats,
      startDate_greater: $from, startDate_lesser: $to, search: $search) {
    id title { romaji english } startDate { year } averageScore popularity genres description(asHtml: false) format episodes
    coverImage { extraLarge large } siteUrl studios(isMain: true) { nodes { name } } } } }"""
_AL_ANIME_ONE = """query ($id: Int) { Media(id: $id, type: ANIME) {
    id title { romaji english } description(asHtml: false) averageScore popularity genres siteUrl episodes status format
    tags { name rank isAdult isMediaSpoiler } externalLinks { site url type language isDisabled }
    reviews(sort: RATING_DESC, perPage: 4) { nodes { summary body(asHtml: false) score user { name } } } } }"""
ANIME_SERIES, ANIME_FILMS = ["TV", "TV_SHORT", "ONA", "OVA"], ["MOVIE"]


def _al_anime(page=1, sort=None, genres=None, formats=None, yfrom=None, yto=None, search=None, new=False):
    v = {"page": page, "sort": sort or ["POPULARITY_DESC"], "formats": formats or ANIME_SERIES + ANIME_FILMS}
    if genres:
        v["genres"] = genres
    if new:
        yfrom = yfrom or YEAR
    if yfrom:
        v["from"] = int(yfrom) * 10000
    if yto:
        v["to"] = (int(yto) + 1) * 10000
    if search:
        v["search"], v["sort"] = search, ["SEARCH_MATCH"]
    d = lookup._al_post(_AL_ANIME, v)
    out = []
    for m in ((d.get("data") or {}).get("Page") or {}).get("media") or []:
        it = _al_item(m)
        film = m.get("format") == "MOVIE"
        studio = [s["name"] for s in ((m.get("studios") or {}).get("nodes") or []) if s.get("name")][:1]
        it.update(cat="animation", form="movie" if film else "tv", authors=studio, al_type="ANIME",
                  why=("Anime film" if film else f"Anime · {m['episodes']} episodes" if m.get("episodes") else "Anime series"))
        out.append(it)
    return out


def _western(form, q, sort="incoming_links_desc", page=0):
    """Western animation from Wikipedia: animated series (TV) or animated films, anime left out (AniList has those)."""
    out = []
    for it in _wp_search(form, q, sort, page):
        if re.search(r"animat|cartoon|stop-motion|claymation", it["blurb"], re.I) and not re.search(r"\banime\b|japanese", it["blurb"], re.I):
            it.update(cat="animation", form=form, why="Animated film" if form == "movie" else "Animated series")
            out.append(it)
    return out


ANIMATION_AISLES = [("trending", "Trending now"), ("new", "New this year"), ("anime", "Anime series"), ("animefilms", "Anime films"),
                    ("western", "Western animated series"), ("cartoonfilms", "Animated films"), ("action", "Anime: action"),
                    ("comedy", "Anime: comedy"), ("fantasy", "Anime: fantasy"), ("romance", "Anime: romance"), ("scifi", "Anime: sci-fi"),
                    ("slice", "Anime: slice of life"), ("family", "Family animation"), ("adult", "Animation for grown-ups")]
_ANIME_GENRE = {"action": "Action", "comedy": "Comedy", "fantasy": "Fantasy", "romance": "Romance", "scifi": "Sci-Fi", "slice": "Slice of Life"}


def _mix(*lists):
    """Take turns between lists (anime and western, so neither crowds the other out), without repeats."""
    import itertools
    out, seen = [], set()
    for x in (y for group in itertools.zip_longest(*lists) for y in group if y):
        k = journal.norm(x["title"])
        if k not in seen:
            seen.add(k)
            out.append(x)
    return out


def animation_browse(subject, page=0, yfrom=None, yto=None, random_pick=False):
    sort = ["SCORE_DESC"] if random_pick else None
    if subject == "trending":
        return _mix(_al_anime(page + 1, ["TRENDING_DESC"], yfrom=yfrom, yto=yto),
                    [x for x in _western("tv", '"animated television series" OR "animated sitcom"', "incoming_links_desc", page) if _in_years(x, yfrom, yto)])
    if subject == "new":
        return _mix(_al_anime(page + 1, ["POPULARITY_DESC"], new=True, yfrom=yfrom, yto=yto),
                    _western("tv", f'"{YEAR}" "animated television series"', "create_timestamp_desc", page),
                    _western("movie", f'"{YEAR} animated film"', "create_timestamp_desc", page))
    if subject == "anime":
        return _al_anime(page + 1, sort, formats=ANIME_SERIES, yfrom=yfrom, yto=yto)
    if subject == "animefilms":
        return _al_anime(page + 1, sort, formats=ANIME_FILMS, yfrom=yfrom, yto=yto)
    if subject in _ANIME_GENRE:
        return _al_anime(page + 1, sort, genres=[_ANIME_GENRE[subject]], yfrom=yfrom, yto=yto)
    s = "random" if random_pick else "incoming_links_desc"
    if subject == "western":
        return [x for x in _western("tv", '"animated television series" OR "animated sitcom" OR "animated series"', s, page) if _in_years(x, yfrom, yto)]
    if subject == "cartoonfilms":
        return [x for x in _western("movie", '"animated film"', s, page) if _in_years(x, yfrom, yto)]
    if subject == "family":
        return _mix(_western("movie", '"animated" "family film"', s, page), _western("tv", '"children\'s animated television series"', s, page))
    if subject == "adult":
        return _western("tv", '"adult animated" OR "adult animation"', s, page)
    return []


def is_animated(title, form):
    """Is a show or film in your library animated? AniList knows the anime; Wikipedia's one-line description
    ("American adult animated sitcom") gives away the rest. Asked once per title, then remembered."""
    def check():
        t = journal.norm(title)
        try:
            for x in _al_anime(search=title):
                if t in {journal.norm(x["title"])} | {journal.norm(s) for s in [x.get("title_romaji") or ""]}:
                    return True
        except Exception:
            pass
        try:
            for x in _wp_search(form, title, "relevance", limit=5):
                if journal.norm(x["title"]) == t:
                    return bool(re.search(r"animat|anime|cartoon|stop-motion", x["blurb"], re.I))
        except Exception:
            pass
        return False
    return discover._cached(("isanim", form, journal.norm(title)), 180 * 86400, check)


_anim_busy = False


def library_animated():
    """The titles of the shows and films in your library that are animated (worked out in the background)."""
    import store
    titles = {}
    for it in store.list_items():
        if it.get("kind") == "tv" and it.get("series"):
            titles[it["series"]] = "tv"
        elif it.get("kind") == "movie" and it.get("title"):
            titles[it["title"]] = "movie"
    known = {t: discover.peek(("isanim", f, journal.norm(t))) for t, f in titles.items()}
    todo = [(t, f) for t, f in titles.items() if known[t] is None]
    global _anim_busy
    if todo and not _anim_busy:
        import threading
        _anim_busy = True

        def run():
            global _anim_busy
            try:
                for t, f in todo:
                    is_animated(t, f)
            finally:
                _anim_busy = False
        threading.Thread(target=run, daemon=True).start()
    return {"titles": [t for t, v in known.items() if v], "pending": bool(todo)}


def animation_info(title, wiki="", al="", form="tv"):
    if al:
        d = lookup._al_post(_AL_ANIME_ONE, {"id": int(al)})
        m = (d.get("data") or {}).get("Media") or {}
        desc = re.sub(r"<[^>]+>", "", re.sub(r"\(Source:[^)]*\)|<br\s*/?>", "\n", m.get("description") or "")).strip()
        score = m.get("averageScore")
        return {"intro": desc, "genres": m.get("genres") or [], "rating": round(score / 20, 1) if score else None, "ratings": m.get("popularity"),
                "read": [{"label": "Watch on " + l["site"], "url": l["url"]} for l in m.get("externalLinks") or [] if l.get("type") == "STREAMING" and not l.get("isDisabled")][:4],
                "links": [{"label": "AniList", "url": m.get("siteUrl")}] if m.get("siteUrl") else []}
    return info(form if form in ("tv", "movie") else "tv", title, wiki)


# ---------------------------------------------------------------- the department's lists
def subjects(cat):
    if cat == "manga":
        return [{"key": k, "label": l} for k, l, _ in MANGA_AISLES]
    if cat == "animation":
        return [{"key": k, "label": l} for k, l in ANIMATION_AISLES]
    return [{"key": k, "label": l} for k, l, _ in AISLES[cat]]


def browse_raw(cat, subject, page=0, yfrom=None, yto=None, random_pick=False):
    if cat == "animation":
        return animation_browse(subject, page, yfrom, yto, random_pick)
    if cat == "manga":
        conf = next((c for k, _, c in MANGA_AISLES if k == subject), MANGA_AISLES[0][2])
        c = dict(conf)
        if random_pick:
            c["sort"] = ["SCORE_DESC"]          # past the end of an aisle: a different ordering
        return _al_list(page=page + 1, yfrom=yfrom, yto=yto, **c)
    conf = next((c for k, _, c in AISLES[cat] if k == subject), None)
    if conf is None:
        items = _trending_wp(cat)
        if cat == "comic" and len(items) < 20:
            # comics rarely make Wikipedia's most-read lists: add the best-known graphic novels and superhero comics
            items += browse_raw(cat, "graphic", 0, yfrom, yto) + browse_raw(cat, "superhero", 0, yfrom, yto)
        seen, out = set(), []
        for x in items:
            if journal.norm(x["title"]) not in seen and _in_years(x, yfrom, yto):
                seen.add(journal.norm(x["title"]))
                out.append(x)
        return out
    if subject == "new" and not random_pick:
        return [x for x in new_releases(cat) if _in_years(x, yfrom, yto)][page * 40:(page + 1) * 40]
    q, sort = conf
    q = q.replace("{y}", str(yto or YEAR))
    films = cat == "movie" and subject in FILM_CATS
    if films:
        q += _year_cats(yfrom, yto)                 # the year categories make the years exact
    want = GENRE_WORDS.get(cat, {}).get(subject)
    # otherwise Wikipedia can't search by year: go a few pages deep and keep the ones from those years
    deep = 6 if (yfrom or yto) and not films else 2 if want or films else 1
    out, seen = [], set()
    for p in range(page * deep, (page + 1) * deep):
        batch = _wp_search(cat, q, "random" if random_pick else sort, p)
        if not batch:
            break
        if films:
            batch = _film_genre_ok(batch, subject)
        for it in batch:
            k = journal.norm(it["title"])
            if k in seen or not _in_years(it, yfrom, yto) or (want and not re.search(want, it["blurb"], re.I)):
                continue
            seen.add(k)
            out.append(it)
        if len(out) >= 30:
            break
    return out


def new_releases(cat):
    """This year's and last year's films / shows / comics, the most-read ones first (from the month's most-read
    Wikipedia articles), then the newest articles about them."""
    def go():
        out, seen = [], set()
        for it in _trending_wp(cat) + [x for y in (YEAR, YEAR - 1)
                                        for x in _wp_search(cat, next(c for k, _, c in AISLES[cat] if k == "new")[0].replace("{y}", str(y)), "create_timestamp_desc")]:
            k = journal.norm(it["title"])
            if k not in seen and (it.get("year") or 0) >= YEAR - 1:
                seen.add(k)
                out.append(it)
        return out
    return discover._cached(_key(cat, "newrel"), 86400, go)


def search_raw(cat, q, yfrom=None, yto=None):
    if cat == "animation":
        return _mix(_al_anime(search=q, yfrom=yfrom, yto=yto), _western("tv", q, "relevance"), _western("movie", q, "relevance"))
    if cat == "manga":
        return _al_list(search=q, yfrom=yfrom, yto=yto)
    return [x for x in _wp_search(cat, q, "relevance") if _in_years(x, yfrom, yto)]


def promos_raw(cat):
    """New releases: this year's (and last year's) most-read, newest first."""
    if cat == "animation":
        items = animation_browse("new")[:48]
        for it in items:
            it["kind_promo"] = "new"
        return items
    if cat == "manga":
        items = _al_list(sort=["TRENDING_DESC"], yfrom=YEAR - 1)
        for it in items:
            it["why"], it["kind_promo"] = f"Out {it['year']}" if it.get("year") else "New", "new"
        return items
    out = [dict(x) for x in new_releases(cat)[:48]]
    for it in out:
        it["why"], it["kind_promo"] = f"Out {it['year']}" if it.get("year") else "New", "new"
    return out


def _key(cat, *parts):
    return (f"{cat}cat4",) + tuple(str(p or "") for p in parts)


def serve_browse(cat, subject, yfrom=None, yto=None):
    key = _key(cat, "browse", subject, yfrom, yto)
    return discover.serve_list(key, 3 * 86400, lambda: browse_raw(cat, subject, 0, yfrom, yto), keep_owned=False)


def serve_promos(cat):
    return discover.serve_list(_key(cat, "promos"), 86400, lambda: promos_raw(cat))


def search(cat, q, yfrom=None, yto=None):
    q = (q or "").strip()
    if not q:
        return []
    items = discover._cached(_key(cat, "s", q.lower(), yfrom, yto), 86400, lambda: search_raw(cat, q, yfrom, yto))
    return [r for r in discover._mark([dict(x) for x in items]) if r["have"] != "ignored"]


def restock(cat, subject, yfrom=None, yto=None):
    """Different titles in an aisle: the next page of it you haven't been shown, then a different ordering."""
    key = _key(cat, "browse", subject, yfrom, yto)
    skey = json.dumps(list(_key(cat, "aislestate", subject, yfrom, yto)))
    if subject == "trending" and cat not in ("manga", "animation"):
        discover._cached(key, 0, lambda: browse_raw(cat, subject, 0, yfrom, yto))
        return serve_browse(cat, subject, yfrom, yto)
    st = dict((discover._cache.get(skey) or (0, {}))[1])
    seen = set(st.get("seen") or []) | {journal.norm(b.get("title")) for b in (discover.peek(key) or [])}
    page, out, wrapped = int(st.get("page") or 0), [], False
    hide = set(discover._owned_index()) | discover.ignored()
    for _ in range(4):
        page += 1
        batch = browse_raw(cat, subject, page if not wrapped else 0, yfrom, yto, random_pick=wrapped)
        if not batch and not wrapped:
            wrapped, page = True, 0
            continue
        out += [b for b in batch if journal.norm(b["title"]) not in seen | hide and not any(journal.norm(b["title"]) == journal.norm(x["title"]) for x in out)]
        if len(out) >= 24:
            break
    if not out:
        raise LookupError("No more titles found for this aisle right now.")
    with discover._cache_lock:
        discover._cache[json.dumps(list(key))] = (time.time(), out)
        discover._cache[skey] = (time.time(), {"page": page, "seen": list(seen)[-600:]})
    discover._save_cache()
    return serve_browse(cat, subject, yfrom, yto)


def info(cat, title, wiki="", al=""):
    """More info for a manga (AniList), comic, film or show (Wikipedia: plot or premise, and what critics said)."""
    def go():
        if cat == "manga" and al:
            return manga_info(al)
        out = {"title": title, "links": []}
        w = wiki
        if not w:
            hits = _wp_search(cat, title, "relevance", limit=6)
            hit = next((h for h in hits if journal.norm(h["title"]) == journal.norm(title)), hits[0] if hits else None)
            w = hit["wiki"] if hit else ""
        if w:
            sec = discover._wp_sections(w)
            out.update(intro=discover._clip(sec["intro"], 1600), synopsis=discover._clip(sec["synopsis"], 3000),
                       reception=discover._clip(sec["reception"], 2400), cover=sec["cover"])
            out["links"].append({"label": "Wikipedia", "url": sec["url"]})
            words = [sec.get("description") or "", re.split(r"(?<=\.)\s", sec["intro"] or "", 1)[0]]
            if cat in ("movie", "tv"):
                g = lookup.screen_genres(words)
                out["genre"] = g[0] if g else None
            else:
                import taxonomy
                out["genre"] = taxonomy.genre_from_categories(words)[0]
        return out
    return discover._cached(_key(cat, "info", journal.norm(title), al or wiki), 7 * 86400, go)


def weekly_restock():
    """Once a week every aisle in every department gets new titles by itself (books included)."""
    k = json.dumps(["weekly-restock"])
    last = (discover._cache.get(k) or (0, None))[0]
    if time.time() - last < 7 * 86400:
        return False
    with discover._cache_lock:
        discover._cache[k] = (time.time(), True)
    for key, _ in discover.SUBJECTS:
        try:
            discover.restock(key)
        except Exception as e:
            print("[inkwell] weekly restock skipped:", "book", key, e)
    for cat in ("manga", "comic", "movie", "tv", "animation"):
        for s in subjects(cat):
            try:
                restock(cat, s["key"])
            except Exception as e:
                print("[inkwell] weekly restock skipped:", cat, s["key"], e)
    print("[inkwell] the catalogue restocked itself for the week")
    discover.mark_shelves_updated()
    return True
