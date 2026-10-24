"""Standard library groupings used by Babel's Library.

Subject  = broad class, modelled on the Library of Congress Classification main classes.
Topic    = the discipline inside it (what the work is *about*, never what kind of media it is).
Genre    = bookseller-style genre (BISAC headings for non-fiction, standard fiction genres).
Tags     = a controlled vocabulary of broad themes, plus a few checked key phrases.
"""
import re

# ---- Subject classes (LCC main classes, histories merged) ----
SUBJECTS = [
    "General Works", "Philosophy, Psychology & Religion", "History", "Geography, Anthropology & Recreation",
    "Social Sciences", "Political Science", "Law", "Education", "Music", "Fine Arts", "Language & Literature",
    "Science", "Medicine", "Agriculture", "Technology & Engineering", "Military & Naval Science",
    "Bibliography & Library Science",
]

# ---- Topics: name -> (subject class, BISAC-style non-fiction genre, trigger words) ----
TOPICS = {
    "Physics & Astronomy": ("Science", "Science", "quantum particle particles physics physical electron photon neutrino neutrinos quark quarks lepton leptons boson bosons hadron gauge relativity galaxy star stars planet orbit cosmology telescope gravitational plasma momentum hamiltonian lagrangian symmetry scattering"),
    "Chemistry & Materials": ("Science", "Science", "chemical chemistry reaction molecule molecular synthesis compound catalyst polymer solvent oxidation reduction redox crystal crystals crystalline material materials electrochemical electrode electrodes electrolyte ion ions lithium intercalation spectroscopy diffraction acid alloy anode cathode impedance voltammetry"),
    "Biology & Life Sciences": ("Science", "Science", "cell cells gene genes protein proteins species evolution organism dna rna genome enzyme ecology bacteria tissue mutation habitat plant plants animal animals"),
    "Earth & Environmental Science": ("Science", "Science", "climate environment environmental emissions ocean soil forest ecosystem biodiversity sustainability pollution rainfall geology earthquake sediment warming water"),
    "Mathematics & Statistics": ("Science", "Mathematics", "theorem proof lemma equation equations matrix matrices probability statistical regression variance integral integrals derivative series fourier calculus algebra vector vectors differential eigenvalue tensor"),
    "Computer Science": ("Science", "Computers", "algorithm algorithms software computer computing neural dataset machine programming code compiler database transformer classification benchmark network"),
    "Engineering & Technology": ("Technology & Engineering", "Technology & Engineering", "engineering design device devices circuit sensor power efficiency mechanical structural fabrication manufacturing voltage battery batteries fuel electrolyzer reactor prototype industrial"),
    "Medicine & Health": ("Medicine", "Medical", "patient patients clinical disease treatment therapy hospital symptoms diagnosis medical drug dose mortality cancer infection vaccine nursing"),
    "Psychology": ("Philosophy, Psychology & Religion", "Psychology", "participants cognitive behavior behaviour memory emotion perception attention anxiety depression personality mental psychological motivation"),
    "Philosophy": ("Philosophy, Psychology & Religion", "Philosophy", "philosophy ethics moral metaphysics epistemology consciousness argument virtue truth existence ontology"),
    "Religion": ("Philosophy, Psychology & Religion", "Religion", "god gods religion religious theology church scripture faith prayer spiritual"),
    "Research Methods": ("Social Sciences", "Social Science", "hypothesis hypotheses variable variables validity reliability sample sampling experimental nonexperimental design methodology researchers empirical survey"),
    "Economics & Business": ("Social Sciences", "Business & Economics", "market markets economic economy price prices firm firms trade inflation labor labour wage investment financial finance gdp consumer business management revenue"),
    "Sociology & Anthropology": ("Social Sciences", "Social Science", "social society community culture cultural gender identity inequality ethnographic urban family migration institutions"),
    "Politics & Government": ("Political Science", "Political Science", "government political policy election democracy parliament regulation constitution voters party international"),
    "Law": ("Law", "Law", "law legal court courts statute rights justice legislation contract liability"),
    "Education": ("Education", "Education", "students student teaching teacher classroom school curriculum pedagogy course assessment literacy"),
    "History": ("History", "History", "century war empire historical history ancient medieval colonial revolution dynasty archive"),
    "Geography & Travel": ("Geography, Anthropology & Recreation", "Travel", "travel geography map maps region regions city cities country journey"),
    "Language & Linguistics": ("Language & Literature", "Foreign Language Study", "lesson lessons dialogue dialogues vocabulary grammar pronunciation pinyin chinese mandarin spanish french german japanese korean phrases sentence sentences characters linguistics syntax"),
    "Literary Studies": ("Language & Literature", "Literary Criticism", "novel poetry poem narrative literary author criticism reader writing translation"),
    "Art & Design": ("Fine Arts", "Art", "art artist painting aesthetic museum visual design architecture photography sculpture"),
    "Music": ("Music", "Music", "music musical song songs album composer orchestra melody harmony"),
    "Film & Television": ("Language & Literature", "Performing Arts", "film films cinema television movie director screenplay episode"),
    "Agriculture & Food": ("Agriculture", "Cooking", "agriculture crop crops farm farming food recipe recipes cooking soil harvest"),
    "Military Science": ("Military & Naval Science", "History", "military army navy weapons battle strategy tactics soldiers"),
    "Fiction": ("Language & Literature", None, ""),
}
GENERAL_TOPIC = "General Works"
SUBJECT_OF = {k: v[0] for k, v in TOPICS.items()}
SUBJECT_OF[GENERAL_TOPIC] = "General Works"

FICTION_GENRES = ["Fantasy", "Science Fiction", "Horror", "Mystery & Crime", "Thriller & Suspense", "Romance",
                  "Historical Fiction", "Adventure", "Superhero", "Humor", "Literary Fiction", "Young Adult"]
NONFICTION_GENRES = ["Biography & Memoir", "History", "Science", "Mathematics", "Computers", "Technology & Engineering",
                     "Medical", "Psychology", "Philosophy", "Religion", "Social Science", "Business & Economics",
                     "Political Science", "Law", "Education", "Foreign Language Study", "Literary Criticism", "Art",
                     "Music", "Performing Arts", "Travel", "Cooking", "Self-Help", "True Crime", "Poetry", "Reference"]
MUSIC_GENRES = ["Rock", "Pop", "Hip-Hop", "R&B & Soul", "Jazz", "Classical", "Electronic", "Country", "Folk",
                "Metal", "Blues", "Reggae", "Latin", "Soundtrack", "World", "Ambient", "Punk", "Indie"]
SCREEN_GENRES = ["Action", "Adventure", "Animation", "Comedy", "Crime", "Documentary", "Drama", "Family", "Fantasy",
                 "Horror", "Mystery", "Romance", "Science Fiction", "Thriller", "War", "Western", "Musical"]
ALL_GENRES = {"book": FICTION_GENRES + NONFICTION_GENRES, "graphic": FICTION_GENRES + NONFICTION_GENRES,
              "music": MUSIC_GENRES, "movie": SCREEN_GENRES, "tv": SCREEN_GENRES}

# catalogue category text (Google Books, OpenLibrary, EPUB, Calibre, ComicInfo) -> genre
CATEGORY_RULES = [
    (r"\bsuper ?hero", "Superhero"),
    (r"\bfantasy\b|sword and sorcery|\bmagic\b|\bdragons?\b|\bwizards?\b", "Fantasy"),
    (r"science fiction|sci[- ]?fi\b|space opera|cyberpunk|dystopi|\bapocalyptic", "Science Fiction"),
    (r"\bhorror\b|\bghost|\bvampire|\bzombie|\bsupernatural", "Horror"),
    (r"true crime", "True Crime"),
    (r"\bmyster|\bdetective|crime fiction|\bnoir\b|\bcrime\b", "Mystery & Crime"),
    (r"thriller|suspense|espionage|\bspy\b|\bspies\b", "Thriller & Suspense"),
    (r"\bromance|love stories", "Romance"),
    (r"historical fiction|fiction, historical", "Historical Fiction"),
    (r"\bhumou?r|comedy|satire|comic fiction", "Humor"),
    (r"young adult|juvenile fiction|\bteen\b", "Young Adult"),
    (r"\badventure|action and adventure|action & adventure", "Adventure"),
    (r"biograph|memoir|autobiograph", "Biography & Memoir"),
    (r"self[- ]help|personal growth", "Self-Help"),
    (r"cook|recipes|\bfood\b", "Cooking"),
    (r"\bpoetry\b|\bpoems\b", "Poetry"),
    (r"foreign language|language study|textbooks for foreign|chinese language|language and languages", "Foreign Language Study"),
    (r"literary criticism", "Literary Criticism"),
    (r"\btravel\b", "Travel"),
    (r"literary fiction|general fiction|fiction, general|\bclassics?\b", "Literary Fiction"),
    (r"\bmathemat", "Mathematics"),
    (r"computers?\b|programming|computer science", "Computers"),
    (r"\bphysics\b|\bscience\b|\bchemistry\b|\bbiology\b|astronomy", "Science"),
    (r"\bhistory\b", "History"),
    (r"philosophy", "Philosophy"),
    (r"religion|christian|islam|buddhis", "Religion"),
    (r"business|economics", "Business & Economics"),
    (r"psychology", "Psychology"),
    (r"medical|medicine|\bhealth\b", "Medical"),
    (r"political|politics", "Political Science"),
    (r"\blaw\b|legal", "Law"),
    (r"education|teaching", "Education"),
    (r"technology|engineering", "Technology & Engineering"),
    (r"\bart\b|photography|design", "Art"),
    (r"\bmusic\b", "Music"),
]
FICTION_HINT = re.compile(r"\bfiction\b|\bnovels?\b|\bcomics? & graphic novels\b|\bgraphic novels?\b|\bfantasy\b|science fiction|\bhorror\b|\bthriller", re.I)
NONFICTION_HINT = re.compile(r"non-?fiction|textbook|study and teaching|\bhandbooks?\b|manuals?\b|\breference\b", re.I)


def genre_from_categories(cats):
    """Return (genre, is_fiction) from catalogue categories, or (None, None)."""
    text = " | ".join(c for c in cats if c).lower()
    if not text.strip():
        return None, None
    fiction = None
    if FICTION_HINT.search(text):
        fiction = 1
    if NONFICTION_HINT.search(text) and not re.search(r"\bfiction\b", text.replace("non-fiction", "").replace("nonfiction", "")):
        fiction = 0
    votes = {}
    for i, (rx, g) in enumerate(CATEGORY_RULES):
        n = len(re.findall(rx, text))
        if n:
            votes[g] = votes.get(g, 0) + n * (1 + (len(CATEGORY_RULES) - i) / 100)
    if not votes:
        return None, fiction
    if fiction == 1:
        fic_votes = {g: v for g, v in votes.items() if g in FICTION_GENRES}
        if fic_votes:
            votes = fic_votes
    elif fiction == 0:
        nf = {g: v for g, v in votes.items() if g in NONFICTION_GENRES}
        if nf:
            votes = nf
    g = max(votes, key=votes.get)
    if fiction is None:
        fiction = 1 if g in FICTION_GENRES else 0
    return g, fiction


def music_genre(raw):
    t = (raw or "").lower()
    rules = [("hip hop|hip-hop|rap", "Hip-Hop"), ("r&b|soul|funk", "R&B & Soul"), ("metal", "Metal"), ("punk", "Punk"),
             ("rock|grunge|alternative", "Rock"), ("pop", "Pop"), ("jazz|swing|bebop", "Jazz"),
             ("classical|baroque|orchestra|symphon|opera", "Classical"), ("electro|edm|house|techno|trance|dubstep|dance", "Electronic"),
             ("country|bluegrass", "Country"), ("folk|acoustic|singer", "Folk"), ("blues", "Blues"), ("reggae|ska|dub", "Reggae"),
             ("latin|salsa|reggaeton|bossa", "Latin"), ("soundtrack|score|ost", "Soundtrack"), ("ambient|new age", "Ambient"),
             ("indie", "Indie"), ("world", "World")]
    for rx, g in rules:
        if re.search(rx, t):
            return g
    return raw.strip().title() if raw and raw.strip() else None


# ---- Broad tags: tag -> trigger words (a tag is used when its triggers are frequent in the text) ----
TAG_VOCAB = {
    # sciences
    "Particle physics": "quark quarks lepton leptons boson bosons hadron hadrons gluon gluons higgs neutrino neutrinos",
    "Quantum mechanics": "quantum schrödinger schrodinger wavefunction wavefunctions hamiltonian eigenstate eigenstates",
    "Relativity": "relativity lorentz spacetime minkowski",
    "Electromagnetism": "electromagnetic maxwell magnetic electric",
    "Thermodynamics": "thermodynamic thermodynamics entropy enthalpy",
    "Astronomy": "galaxy galaxies telescope stellar cosmology cosmological",
    "Electrochemistry": "electrochemical electrochemistry electrode electrodes voltammetry faradaic redox potentiostat",
    "Impedance spectroscopy": "impedance nyquist",
    "Batteries & energy storage": "battery batteries cathode cathodes anode anodes capacity cycling",
    "Fuel cells & electrolysis": "fuel electrolyzer electrolyzers electrolysis hydrogen",
    "Lithium": "lithium",
    "Resource recovery": "recovery extraction brine brines",
    "Crystallography": "crystallography crystallographic diffraction",
    "Crystals": "crystal crystals crystalline",
    "Materials science": "materials",
    "Catalysis": "catalyst catalysts catalytic catalysis",
    "Spectroscopy": "spectroscopy spectroscopic spectra spectrum",
    "Differential equations": "differential ode pde",
    "Linear algebra": "matrix matrices eigenvalue eigenvalues eigenvector vectors",
    "Calculus": "integral integrals derivative derivatives integration",
    "Fourier analysis": "fourier",
    "Complex analysis": "complex analytic residue residues contour",
    "Probability & statistics": "probability probabilities statistics statistical distribution distributions",
    "Machine learning": "neural dataset datasets transformer backpropagation classifier",
    "Programming": "programming code compiler software",
    "Algorithms": "algorithm algorithms complexity",
    "Genetics": "gene genes genome genetic dna",
    "Ecology": "ecology ecosystem ecosystems biodiversity species",
    "Climate change": "climate warming emissions carbon",
    "Neuroscience": "brain neural neurons cortex",
    "Public health": "health disease epidemiology mortality",
    "Research methods": "hypothesis hypotheses validity variable variables sampling methodology",
    "Experimental design": "experimental experiment experiments control randomized random assignment",
    # language & culture
    "Language learning": "lesson lessons dialogue dialogues vocabulary grammar pronunciation exercises",
    "Chinese language": "chinese mandarin pinyin",
    "Japanese language": "japanese hiragana katakana kanji",
    "Spanish language": "spanish español",
    "French language": "french français",
    # fiction themes (only used for fiction)
    "__FICTION__": "",
    "Magic": "magic magical spell spells sorcery sorcerer wizard wizards enchanted",
    "War": "war battle battles army armies soldiers warfare",
    "Political intrigue": "throne court politics betrayal assassination highprince highlords",
    "Royalty": "king kings queen prince princess kingdom kingdoms",
    "Knights & warriors": "knight knights warrior warriors sword swords blade",
    "Dragons": "dragon dragons",
    "Gods & mythology": "god gods goddess divine mythology",
    "Space travel": "spaceship starship spacecraft orbit planet planets",
    "Robots & AI": "robot robots android androids cyborg",
    "Time travel": "time-travel timeline",
    "Survival": "survive survival survivor survivors",
    "Monsters": "monster monsters creature creatures beast beasts",
    "Ghosts & the supernatural": "ghost ghosts haunted spirit spirits",
    "Murder": "murder murdered killer homicide",
    "Detectives": "detective detectives inspector",
    "Family": "mother father sister brother daughter son family",
    "Friendship": "friend friends friendship",
    "Love": "love lover lovers kiss",
    "Coming of age": "school teenager adolescence growing",
    "Revenge": "revenge vengeance",
    "Post-apocalyptic": "apocalypse wasteland ruins",
    "Superheroes": "superhero superheroes hero heroes villain villains",
    "Crime": "crime criminal criminals gang",
    "Exploration": "expedition explorer explorers voyage",
    "Slavery": "slave slaves slavery",
}

BANNED_TAG_WORDS = re.compile(
    r"\b(graphic novels?|comics?|manga|digital|webrip|ebook|e-book|edition|volume|vol|book|books|novel|fiction|nonfiction|"
    r"publish\w*|press|online|library|journal|copyright|licen[cs]e|creative commons|university|college|department|"
    r"acknowledg\w*|thanks?|editor|manager|reprint|isbn|doi|chapter|appendix|index|contents|preface|introduction|"
    r"wiley|elsevier|springer|cambridge|oxford|acs|rsc|ieee|share|article|articles|downloaded|terms|conditions)\b", re.I)


FICTION_ONLY_TAGS = set()
_seen = False
for _k in list(TAG_VOCAB):
    if _k == "__FICTION__":
        _seen = True
        del TAG_VOCAB[_k]
        continue
    if _seen:
        FICTION_ONLY_TAGS.add(_k)
