"""Game details (year, genre, players, developer, publisher) from libretro's game database.

The database ships one .rdb file per system. Relic uses RetroArch's copy when you have it, otherwise
downloads that system's file from the libretro-database project, and keeps a small index of it.
"""

from __future__ import annotations

import json
import re
import struct
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

from reliclog import log
from version import VERSION

RAW = "https://raw.githubusercontent.com/libretro/libretro-database/master/rdb/"
TAGS = re.compile(r"\s*[\(\[][^\)\]]*[\)\]]")
KEEP = {"releaseyear": "year", "genre": "genre", "users": "players", "developer": "developer",
        "publisher": "publisher", "franchise": "franchise", "esrb_rating": "esrb"}
MAX_AGE = 30 * 86400


def key(name: str) -> str:
    t = TAGS.sub("", name)
    t = re.sub(r"^(.*?), (the|a|an)\b", r"\2 \1", t, flags=re.I)
    return re.sub(r"[^a-z0-9]+", "", t.lower())


# ------------------------------------------------------------------ the .rdb format (msgpack records)
class _Reader:
    def __init__(self, data: bytes):
        self.d, self.i = data, 0

    def _take(self, n):
        b = self.d[self.i:self.i + n]
        self.i += n
        return b

    def read(self):
        t = self.d[self.i]
        self.i += 1
        if t <= 0x7f:
            return t
        if 0x80 <= t <= 0x8f:
            return self._map(t & 0x0f)
        if 0x90 <= t <= 0x9f:
            return [self.read() for _ in range(t & 0x0f)]
        if 0xa0 <= t <= 0xbf:
            return self._take(t & 0x1f).decode("utf-8", "replace")
        if t == 0xc0:
            return None
        if t in (0xc2, 0xc3):
            return t == 0xc3
        if t in (0xc4, 0xc5, 0xc6):
            n = struct.unpack(">" + "BHI"[t - 0xc4], self._take([1, 2, 4][t - 0xc4]))[0]
            return self._take(n)
        if t in (0xcc, 0xcd, 0xce, 0xcf):
            sz = [1, 2, 4, 8][t - 0xcc]
            return int.from_bytes(self._take(sz), "big")
        if t in (0xd0, 0xd1, 0xd2, 0xd3):
            sz = [1, 2, 4, 8][t - 0xd0]
            return int.from_bytes(self._take(sz), "big", signed=True)
        if t in (0xd9, 0xda, 0xdb):
            n = int.from_bytes(self._take([1, 2, 4][t - 0xd9]), "big")
            return self._take(n).decode("utf-8", "replace")
        if t in (0xdc, 0xdd):
            n = int.from_bytes(self._take(2 if t == 0xdc else 4), "big")
            return [self.read() for _ in range(n)]
        if t in (0xde, 0xdf):
            return self._map(int.from_bytes(self._take(2 if t == 0xde else 4), "big"))
        if t >= 0xe0:
            return t - 0x100
        raise ValueError(f"unknown type {t:#x}")

    def _map(self, n):
        out = {}
        for _ in range(n):
            k = self.read()
            out[k] = self.read()
        return out


def parse_rdb(data: bytes) -> dict:
    """From an .rdb file: details by name key, official names by disc ID, and every game's name.
    {"info": {key: {"year", "genre", ...}}, "serials": {"SLUS20946": "Grand Theft Auto - ..."}, "names": [...]}"""
    if data[:7] != b"RARCHDB":
        raise ValueError("not an rdb file")
    r = _Reader(data)
    r.i = 16
    out: dict[str, dict] = {}
    serials: dict[str, str] = {}
    names: dict[str, None] = {}
    while r.i < len(data):
        try:
            rec = r.read()
        except (IndexError, ValueError, struct.error):
            break
        if not isinstance(rec, dict):
            break
        name = rec.get("name")
        if isinstance(name, bytes):
            name = name.decode("utf-8", "replace")
        if isinstance(name, str) and name:
            names[name] = None
            ser = rec.get("serial")
            if isinstance(ser, bytes):
                ser = ser.decode("ascii", "replace")
            if isinstance(ser, str) and ser:
                # Nintendo discs: "DL-DOL-GZLE-USA" (the naming box art uses) answers to the game ID GZLE
                n4 = re.match(r"(?:DL-DOL|RVL)-([A-Z0-9]{4})-", ser)
                if n4:
                    serials.setdefault("ID4:" + n4[1], name)
                # "SLES-52202-GER" style variants share the base ID; keep the plain one first
                for sv in (ser, ser.split("-")[0] + (ser.split("-")[1] if ser.count("-") >= 1 else "")):
                    k = re.sub(r"[^A-Z0-9]", "", sv.upper())
                    if k and len(k) >= 6:
                        serials.setdefault(k, name)
        info = {}
        for src, dst in KEEP.items():
            v = rec.get(src)
            if v not in (None, "", 0):
                info[dst] = v if not isinstance(v, bytes) else v.decode("utf-8", "replace")
        if not info:
            continue
        for nm in (name, rec.get("description"), (rec.get("rom_name") or "").rsplit(".", 1)[0]):
            if isinstance(nm, str) and nm:
                out.setdefault(key(nm), info)
    return {"info": out, "serials": serials, "names": list(names)}


REGIONS = ("USA", "World", "Europe", "Japan")
ODD = re.compile(r"\((?:[^)]*\b)?(Demo|Beta|Proto|Prototype|Sample|Kiosk|Trade Demo|Preview|Debug|Pre-Production|Taikenban)\b", re.I)
STOP = {"the", "a", "an", "of", "and", "edition", "version", "game"}
TOKEN = re.compile(r"[a-z0-9]+")


LOOSE_PREFIXES = {
    "PlayStation": ("SLUS", "SCUS", "SLES", "SCES", "SLPS", "SCPS", "SLPM", "SCPM"),
    "PlayStation 2": ("SLUS", "SCUS", "SLES", "SCES", "SLPS", "SLPM", "SCPS", "SCAJ", "SLKA"),
    "PlayStation Portable": ("ULUS", "UCUS", "ULES", "UCES", "ULJM", "ULJS", "UCJS", "NPUH", "NPUG"),
}

# Short names people type, and what the database calls them.
ALIASES = {
    "gta": "grand theft auto", "sa": "san andreas", "vc": "vice city", "lcs": "liberty city stories",
    "vcs": "vice city stories", "ff": "final fantasy", "mgs": "metal gear solid", "kh": "kingdom hearts",
    "gt": "gran turismo", "nfs": "need for speed", "mw": "most wanted", "re": "resident evil",
    "sf": "street fighter", "mk": "mortal kombat", "thps": "tony hawk s pro skater", "cod": "call of duty",
    "dbz": "dragon ball z", "tmnt": "teenage mutant ninja turtles", "loz": "legend of zelda",
    "zelda": "zelda", "smb": "super mario bros", "ctr": "crash team racing", "dmc": "devil may cry",
    "sotc": "shadow of the colossus", "rdr": "red dead revolver", "jak": "jak", "ratchet": "ratchet",
    "pes": "pro evolution soccer", "we": "winning eleven", "bf": "battlefront", "sw": "star wars",
    "ac": "armored core", "dq": "dragon quest", "smt": "shin megami tensei", "mvc": "marvel vs capcom",
    "tlou": "last of us", "gow": "god of war", "kotor": "knights of the old republic",
}
ROMAN = {"1": "i", "2": "ii", "3": "iii", "4": "iv", "5": "v", "6": "vi", "7": "vii", "8": "viii", "9": "ix", "10": "x"}
ROMAN.update({v: k for k, v in list(ROMAN.items())})


def _words(name: str) -> list[str]:
    return TOKEN.findall(TAGS.sub("", name).lower())


def _word_hits(word: str, words: list[str], low: str) -> bool:
    """Whether one typed word is in a name: as written, as its usual long form ("gta"), as a
    number written the other way ("2"/"ii"), or as the first letters of words in a row ("gta",
    "mgs")."""
    if len(word) >= 3 and word in low:
        return True
    if word in words:
        return True
    alt = ROMAN.get(word)
    if alt and alt in words:
        return True
    long = ALIASES.get(word)
    if long and f" {long} " in f" {' '.join(words)} ":
        return True
    if 2 <= len(word) <= 6 and word.isalpha():
        firsts = "".join(w[0] for w in words)
        if word in firsts and any(firsts[i:i + len(word)] == word for i in range(len(firsts))):
            return True
    return False


def _tokens(name: str) -> frozenset:
    return frozenset(t for t in TOKEN.findall(TAGS.sub("", name).lower()) if t not in STOP)


def _nums(tokens) -> frozenset:
    return frozenset(t for t in tokens if t.isdigit())


def _by_region(cands: list[str], prefer: str = "") -> str:
    if prefer:
        for c in [c for c in cands if not ODD.search(c)] or cands:
            if f"({prefer}" in c or f", {prefer}" in c:
                return c
    real = [c for c in cands if not ODD.search(c)] or cands  # the retail game before demos and betas
    for r in REGIONS:
        for c in real:
            if f"({r}" in c:
                return c
    return real[0]


# ------------------------------------------------------------------ lookup
class Metadata:
    def __init__(self, data_dir: Path, ra, on_change=None):
        self.dir = data_dir / "meta"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.ra = ra
        self.on_change = on_change or (lambda: None)
        self._idx: dict[str, dict] = {}
        self._fuzzy: dict[str, dict] = {}
        self._official: dict = {}
        self._toks: dict[str, list] = {}
        self._busy = False
        self._lock = threading.Lock()

    def _db(self, db: str) -> dict | None:
        idx = self._idx.get(db)
        return idx if idx is not None else self._load_cached(db)

    def get(self, db: str, label: str) -> dict:
        idx = self._db(db)
        return idx["info"].get(key(label), {}) if idx else {}

    def name_for_serial(self, db: str, serial: str) -> str:
        """The official name for a disc ID ("SLUS20946" -> "Grand Theft Auto - San Andreas (USA, Canada) (v3.00)")."""
        idx = self._db(db)
        if not idx or not serial:
            return ""
        if len(serial) == 6 and serial.isalnum():  # a GameCube/Wii game ID: the standard name first
            hit = idx["serials"].get("ID4:" + serial[:4])
            if hit:
                return hit
        if serial.startswith("~"):  # just the number: try the usual prefixes, North America first
            for pre in LOOSE_PREFIXES.get(db.split(" - ")[-1], ()):
                hit = idx["serials"].get(pre + serial[1:])
                if hit:
                    return hit
            return ""
        return idx["serials"].get(serial, "")

    def variants(self, db: str, name: str, limit: int = 6) -> list[str]:
        """Other releases of the same game (another version or region), best first: box art is
        sometimes filed under one of those."""
        self.best_name(db, name)  # builds the name index
        cands = [n for n in (self._fuzzy.get(db) or {}).get(key(name), []) if n != name]
        region = re.search(r"\((USA|Europe|Japan|World)", name)
        cands.sort(key=lambda n: (bool(ODD.search(n)), not (region and region[1] in n), "(USA" not in n, len(n)))
        return cands[:limit]

    def names(self, db: str) -> list[str]:
        idx = self._db(db)
        return idx["names"] if idx else []

    def best_name(self, db: str, title: str) -> str:
        """The official name that best matches a title: same words (ignoring tags and "The"), your region
        first; else the closest by words, as long as the numbers agree (Tekken 4 is never Tekken 5)."""
        names = self.names(db)
        if not names:
            return ""
        idx = self._fuzzy.get(db)
        if idx is None:
            idx = {}
            for n in names:
                idx.setdefault(key(n), []).append(n)
            self._fuzzy[db] = idx
            self._toks[db] = [(_tokens(n), n) for n in names]
        region = re.search(r"\((USA|Europe|Japan|World)", title)
        exact = idx.get(key(title))
        if exact:
            return _by_region(exact, region[1] if region else "")
        want = _tokens(title)
        if len(want) < 2:
            return ""
        nums = _nums(want)
        best, score = [], 0.0
        for toks, n in self._toks[db]:
            if _nums(toks) != nums:
                continue
            inter = len(want & toks)
            if not inter:
                continue
            sc = inter / len(want | toks)
            if sc > score + 1e-9:
                best, score = [n], sc
            elif abs(sc - score) < 1e-9:
                best.append(n)
        return _by_region(best, region[1] if region else "") if score >= 0.8 else ""

    def official(self, db: str, g: dict) -> str:
        """A game's official name: by its disc ID when it has one, else the closest name. Remembered."""
        k = (db, g["label"], g.get("serial", ""))
        if k in self._official:
            return self._official[k]
        name = self.name_for_serial(db, g.get("serial", "")) or self.best_name(db, g["label"])
        if name or self._db(db) is not None:  # don't remember a miss before the database is here
            self._official[k] = name
        return name

    def search(self, db: str, query: str, limit: int = 30) -> list[str]:
        """Names matching what you typed (for choosing box art by hand). Every word must match;
        if nothing does, the names matching the most words are shown instead."""
        q = [w for w in TOKEN.findall(query.lower()) if w not in STOP]
        if not q:
            return []
        scored = []
        for n in self.names(db):
            words = _words(n)
            if not words:
                continue
            low = " ".join(words)
            hits = sum(_word_hits(w, words, low) for w in q)
            if hits:
                scored.append((hits, n))
        if not scored:
            return []
        best = max(h for h, _ in scored)
        if best < len(q) and best < max(1, len(q) // 2):
            return []
        out = [n for h, n in scored if h == best]
        out.sort(key=lambda n: (bool(ODD.search(n)), "(USA" not in n, len(n)))
        return out[:limit]

    def _path(self, db: str) -> Path:
        return self.dir / (re.sub(r"[^\w.-]+", "_", db) + ".v2.json")

    def _load_cached(self, db: str) -> dict | None:
        p = self._path(db)
        try:
            idx = json.loads(p.read_text(encoding="utf-8"))
            if "info" not in idx:
                return None
            self._idx[db] = idx
            return idx
        except (OSError, ValueError):
            return None

    def fetch_async(self, dbs: list[str], allow_download: bool) -> None:
        """Make sure each system's index exists (in the background), then tell the library."""
        with self._lock:
            if self._busy:
                return
            self._busy = True

        def run():
            changed = False
            try:
                for db in dbs:
                    p = self._path(db)
                    fresh = p.exists() and time.time() - p.stat().st_mtime < MAX_AGE
                    if fresh and db in self._idx:
                        continue
                    if fresh and self._load_cached(db) is not None:
                        changed = True
                        continue
                    data = self._local(db) or (self._download(db) if allow_download else None)
                    if not data:
                        continue
                    try:
                        idx = parse_rdb(data)
                    except Exception:
                        log.exception("couldn't read the game database for %s", db)
                        continue
                    p.write_text(json.dumps(idx, separators=(",", ":")), encoding="utf-8")
                    self._idx[db] = idx
                    self._fuzzy.pop(db, None)
                    self._official = {k: v for k, v in self._official.items() if k[0] != db}
                    changed = True
                    log.info("game details: %s (%d games, %d disc IDs)", db, len(idx["names"]), len(idx["serials"]))
            finally:
                self._busy = False
            if changed:
                self.on_change()
        threading.Thread(target=run, daemon=True).start()

    def _local(self, db: str) -> bytes | None:
        d = self.ra.database_dir
        p = d / f"{db}.rdb" if d else None
        try:
            return p.read_bytes() if p and p.is_file() else None
        except OSError:
            return None

    def _download(self, db: str) -> bytes | None:
        url = RAW + urllib.parse.quote(db + ".rdb")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": f"Relic/{VERSION}"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read()
        except Exception as e:
            if "404" not in str(e):
                log.info("game details for %s: %s", db, e)
            return None
