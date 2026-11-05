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


def parse_rdb(data: bytes) -> dict[str, dict]:
    """{name key: {"year", "genre", "players", ...}} from an .rdb file."""
    if data[:7] != b"RARCHDB":
        raise ValueError("not an rdb file")
    r = _Reader(data)
    r.i = 16
    out: dict[str, dict] = {}
    while r.i < len(data):
        try:
            rec = r.read()
        except (IndexError, ValueError, struct.error):
            break
        if not isinstance(rec, dict):
            break
        info = {}
        for src, dst in KEEP.items():
            v = rec.get(src)
            if v not in (None, "", 0):
                info[dst] = v if not isinstance(v, bytes) else v.decode("utf-8", "replace")
        if not info:
            continue
        for nm in (rec.get("name"), rec.get("description"), (rec.get("rom_name") or "").rsplit(".", 1)[0]):
            if isinstance(nm, str) and nm:
                out.setdefault(key(nm), info)
    return out


# ------------------------------------------------------------------ lookup
class Metadata:
    def __init__(self, data_dir: Path, ra, on_change=None):
        self.dir = data_dir / "meta"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.ra = ra
        self.on_change = on_change or (lambda: None)
        self._idx: dict[str, dict[str, dict]] = {}
        self._busy = False
        self._lock = threading.Lock()

    def get(self, db: str, label: str) -> dict:
        idx = self._idx.get(db)
        if idx is None:
            idx = self._load_cached(db)
        return idx.get(key(label), {}) if idx else {}

    def _path(self, db: str) -> Path:
        return self.dir / (re.sub(r"[^\w.-]+", "_", db) + ".json")

    def _load_cached(self, db: str) -> dict | None:
        p = self._path(db)
        try:
            idx = json.loads(p.read_text(encoding="utf-8"))
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
                    changed = True
                    log.info("game details: %s (%d entries)", db, len(idx))
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
