"""Audio/subtitle tracks for videos.

- Reads the track list of Matroska (.mkv/.webm) files with a small EBML parser.
- Extracts embedded *text* subtitles (SRT, ASS/SSA, WebVTT) to WebVTT, cached on disk.
- Finds sidecar subtitle files next to the video (Movie.srt, Movie.en.srt, Subs/…) and converts them to WebVTT.
"""
import json
import os
import re
import struct

LANG_NAMES = {"eng": "English", "en": "English", "jpn": "Japanese", "ja": "Japanese", "spa": "Spanish", "es": "Spanish",
              "fre": "French", "fra": "French", "fr": "French", "ger": "German", "deu": "German", "de": "German",
              "ita": "Italian", "it": "Italian", "por": "Portuguese", "pt": "Portuguese", "rus": "Russian", "ru": "Russian",
              "chi": "Chinese", "zho": "Chinese", "zh": "Chinese", "kor": "Korean", "ko": "Korean", "ara": "Arabic", "ar": "Arabic",
              "hin": "Hindi", "hi": "Hindi", "pol": "Polish", "pl": "Polish", "dut": "Dutch", "nld": "Dutch", "nl": "Dutch",
              "swe": "Swedish", "sv": "Swedish", "tur": "Turkish", "tr": "Turkish", "und": "Unknown language"}
SUB_EXT = (".srt", ".vtt", ".ass", ".ssa")

# Matroska element IDs
SEGMENT, CLUSTER, TRACKS, TRACKENTRY, INFO = 0x18538067, 0x1F43B675, 0x1654AE6B, 0xAE, 0x1549A966
TIMECODESCALE, TRACKNUMBER, TRACKTYPE, CODECID, LANGUAGE, LANGBCP47, NAME = 0x2AD7B1, 0xD7, 0x83, 0x86, 0x22B59C, 0x22B59D, 0x536E
CODECPRIVATE, FLAGDEFAULT, FLAGFORCED = 0x63A2, 0x88, 0x55AA
TIMECODE, SIMPLEBLOCK, BLOCKGROUP, BLOCK, BLOCKDURATION = 0xE7, 0xA3, 0xA0, 0xA1, 0x9B
LEVEL1 = {0x114D9B74, INFO, TRACKS, CLUSTER, 0x1C53BB6B, 0x1941A469, 0x1043A770, 0x1254C367, 0xEC}


def lang_name(code, name=""):
    base = LANG_NAMES.get((code or "").lower().split("-")[0], code or "")
    return f"{base} — {name}" if name and name.lower() not in base.lower() else (base or name or "Track")


class _R:
    def __init__(self, f):
        self.f = f

    def vint(self, keep_marker=False):
        b = self.f.read(1)
        if not b:
            raise EOFError
        first = b[0]
        mask, length = 0x80, 1
        while length <= 8 and not (first & mask):
            mask >>= 1
            length += 1
        if length > 8:
            raise ValueError("bad vint")
        val = first if keep_marker else first & (mask - 1)
        rest = self.f.read(length - 1)
        all_ones = (first & (mask - 1)) == mask - 1 and all(x == 0xFF for x in rest)
        for x in rest:
            val = (val << 8) | x
        return val, length, (all_ones and not keep_marker)

    def element(self):
        eid, _, _ = self.vint(True)
        size, _, unknown = self.vint()
        return eid, (None if unknown else size)


def _uint(b):
    return int.from_bytes(b, "big") if b else 0


def read_tracks(path):
    """[{number, type: 'video'|'audio'|'subtitles', codec, lang, name, default, forced}] for an MKV/WebM file."""
    tracks, scale = [], 1000000
    with open(path, "rb") as f:
        r = _R(f)
        eid, size = r.element()
        f.seek(size, 1)  # EBML header
        eid, seg_size = r.element()
        if eid != SEGMENT:
            return [], scale
        seg_start = f.tell()
        seg_end = seg_start + seg_size if seg_size else os.path.getsize(path)
        while f.tell() < seg_end:
            try:
                eid, size = r.element()
            except (EOFError, ValueError):
                break
            if eid == INFO:
                end = f.tell() + size
                while f.tell() < end:
                    cid, csize = r.element()
                    data = f.read(csize)
                    if cid == TIMECODESCALE:
                        scale = _uint(data)
            elif eid == TRACKS:
                end = f.tell() + size
                while f.tell() < end:
                    cid, csize = r.element()
                    if cid != TRACKENTRY:
                        f.seek(csize, 1)
                        continue
                    tend = f.tell() + csize
                    t = {"lang": "eng", "name": "", "default": True, "forced": False}
                    while f.tell() < tend:
                        tid, tsize = r.element()
                        data = f.read(tsize)
                        if tid == TRACKNUMBER:
                            t["number"] = _uint(data)
                        elif tid == TRACKTYPE:
                            t["type"] = {1: "video", 2: "audio", 0x11: "subtitles"}.get(_uint(data), "other")
                        elif tid == CODECID:
                            t["codec"] = data.decode("ascii", "ignore")
                        elif tid == LANGUAGE:
                            t["lang"] = data.decode("ascii", "ignore").strip("\x00")
                        elif tid == LANGBCP47:
                            t["lang"] = data.decode("ascii", "ignore").strip("\x00")
                        elif tid == NAME:
                            t["name"] = data.decode("utf-8", "ignore").strip("\x00")
                        elif tid == FLAGDEFAULT:
                            t["default"] = bool(_uint(data))
                        elif tid == FLAGFORCED:
                            t["forced"] = bool(_uint(data))
                        elif tid == CODECPRIVATE:
                            t["private"] = data.decode("utf-8", "ignore")
                    tracks.append(t)
                break  # Tracks comes before the clusters; no need to read further
            elif size is None:
                break
            else:
                f.seek(size, 1)
    return tracks, scale


def _ts(sec):
    sec = max(0.0, sec)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h):02d}:{int(m):02d}:{s:06.3f}"


ASS_TAGS = re.compile(r"\{[^}]*\}")


def _ass_text(t):
    t = ASS_TAGS.sub("", t).replace("\\N", "\n").replace("\\n", "\n").replace("\\h", " ")
    return t.strip()


def extract_mkv_subs(path, out_dir, key):
    """Write every embedded text subtitle track to <out_dir>/<key>_<track>.vtt. Returns {track_number: path}."""
    tracks, scale = read_tracks(path)
    subs = {t["number"]: t for t in tracks if t.get("type") == "subtitles" and re.match(r"S_TEXT/(UTF8|ASS|SSA|WEBVTT)|S_(ASS|SSA)", t.get("codec", ""))}
    if not subs:
        return {}
    cues = {n: [] for n in subs}
    with open(path, "rb") as f:
        r = _R(f)
        eid, size = r.element()
        f.seek(size, 1)
        eid, seg_size = r.element()
        seg_end = f.tell() + seg_size if seg_size else os.path.getsize(path)

        def block(data_len, cluster_tc, duration=None):
            start = f.tell()
            num, ln, _ = r.vint()
            if num not in subs:
                f.seek(start + data_len)
                return
            rel = struct.unpack(">h", f.read(2))[0]
            f.read(1)
            payload = f.read(data_len - ln - 3).decode("utf-8", "ignore")
            st = (cluster_tc + rel) * scale / 1e9
            dur = duration * scale / 1e9 if duration else None
            cues[num].append([st, dur, payload])

        while f.tell() < seg_end:
            try:
                eid, size = r.element()
            except (EOFError, ValueError):
                break
            if eid != CLUSTER:
                if size is None:
                    continue
                f.seek(size, 1)
                continue
            cend = f.tell() + size if size is not None else seg_end
            cluster_tc = 0
            while f.tell() < cend:
                pos = f.tell()
                try:
                    cid, csize = r.element()
                except (EOFError, ValueError):
                    break
                if size is None and cid in LEVEL1 | {CLUSTER}:
                    f.seek(pos)
                    break
                if cid == TIMECODE:
                    cluster_tc = _uint(f.read(csize))
                elif cid == SIMPLEBLOCK:
                    block(csize, cluster_tc)
                elif cid == BLOCKGROUP:
                    gend = f.tell() + csize
                    bpos, blen, dur = None, None, None
                    while f.tell() < gend:
                        gid, gsize = r.element()
                        if gid == BLOCK:
                            bpos, blen = f.tell(), gsize
                            f.seek(gsize, 1)
                        elif gid == BLOCKDURATION:
                            dur = _uint(f.read(gsize))
                        else:
                            f.seek(gsize, 1)
                    if bpos is not None:
                        f.seek(bpos)
                        block(blen, cluster_tc, dur)
                    f.seek(gend)
                else:
                    f.seek(csize, 1)
    out = {}
    for num, lst in cues.items():
        lst.sort(key=lambda c: c[0])
        is_ass = "ASS" in subs[num].get("codec", "") or "SSA" in subs[num].get("codec", "")
        lines = ["WEBVTT", ""]
        for i, (st, dur, text) in enumerate(lst):
            if dur is None:
                dur = min(6.0, (lst[i + 1][0] - st) if i + 1 < len(lst) else 4.0)
            if is_ass:
                parts = text.split(",", 8)
                text = _ass_text(parts[8] if len(parts) == 9 else text)
            text = text.strip()
            if not text:
                continue
            lines += [f"{_ts(st)} --> {_ts(st + dur)}", text.replace("-->", "→"), ""]
        p = os.path.join(out_dir, f"{key}_{num}.vtt")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines))
        out[num] = p
    return out


def file_to_vtt(path):
    raw = open(path, "rb").read()
    for enc in ("utf-8-sig", "utf-16", "cp1252", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    ext = os.path.splitext(path)[1].lower()
    if ext == ".vtt":
        return text
    if ext == ".srt":
        text = re.sub(r"(\d\d:\d\d:\d\d),(\d\d\d)", r"\1.\2", text.replace("\r\n", "\n"))
        return "WEBVTT\n\n" + text
    # .ass / .ssa
    lines, fmt = ["WEBVTT", ""], None
    cues = []
    for line in text.splitlines():
        if line.lower().startswith("format:") and fmt is None and "text" in line.lower() and "start" in line.lower():
            fmt = [x.strip().lower() for x in line[7:].split(",")]
        elif line.startswith("Dialogue:") and fmt:
            parts = line[9:].split(",", len(fmt) - 1)
            d = dict(zip(fmt, parts))
            def t(v):
                h, m, s = v.strip().split(":")
                return int(h) * 3600 + int(m) * 60 + float(s)
            try:
                cues.append((t(d["start"]), t(d["end"]), _ass_text(d.get("text", ""))))
            except (KeyError, ValueError):
                pass
    for st, en, tx in sorted(cues):
        if tx:
            lines += [f"{_ts(st)} --> {_ts(en)}", tx, ""]
    return "\n".join(lines)


def sidecars(video_path):
    """Subtitle files that belong to a video: same name (+ .lang), or inside a Subs/Subtitles folder."""
    d = os.path.dirname(video_path)
    base = os.path.splitext(os.path.basename(video_path))[0]
    found = []
    cand_dirs = [d] + [os.path.join(d, x) for x in ("Subs", "subs", "Subtitles", "subtitles", base)]
    for cd in cand_dirs:
        if not os.path.isdir(cd):
            continue
        for fn in sorted(os.listdir(cd)):
            stem, ext = os.path.splitext(fn)
            if ext.lower() not in SUB_EXT:
                continue
            if cd == d and not stem.lower().startswith(base.lower()):
                continue
            if cd != d and os.path.basename(cd).lower() not in (base.lower(),) and not (stem.lower().startswith(base.lower()) or len(os.listdir(cd)) < 40):
                continue
            tag = stem[len(base):].strip(" ._-") if stem.lower().startswith(base.lower()) else stem
            parts = [p for p in re.split(r"[._\s-]+", tag) if p]
            lang = next((p for p in parts if p.lower() in LANG_NAMES), "")
            label = lang_name(lang) if lang else (tag or "Subtitles")
            if any(p.lower() in ("forced",) for p in parts):
                label += " (forced)"
            if any(p.lower() in ("sdh", "cc", "hi") for p in parts):
                label += " (SDH)"
            found.append({"path": os.path.join(cd, fn), "label": label, "lang": (lang or "und")[:3]})
    return found
