"""Box art, screenshots and title screens.

Looked for in this order, and cached in %APPDATA%\\Relic\\art:
  1. your own picture for that game (set in Relic)
  2. RetroArch's thumbnails folder (anything you've already downloaded there)
  3. the libretro thumbnails server, by the game's exact name
  4. the same server's folder listing, matched loosely (so "Super Mario World.sfc"
     still finds "Super Mario World (USA).png")
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

from reliclog import log
from version import VERSION

KINDS = {"boxart": "Named_Boxarts", "snap": "Named_Snaps", "title": "Named_Titles"}
SERVER = "https://thumbnails.libretro.com"
BAD = re.compile(r'[&*/:`<>?\\|"]')
TAGS = re.compile(r"\s*[\(\[][^\)\]]*[\)\]]")
LISTING = re.compile(r'href="([^"]+\.png)"', re.I)
MISS_DAYS = 3
INDEX_DAYS = 14
PREFERRED_REGIONS = ("USA", "World", "Europe", "Japan")


def thumb_name(label: str) -> str:
    """RetroArch's rule: these characters become underscores in thumbnail file names."""
    return BAD.sub("_", label)


def _key(name: str) -> str:
    t = TAGS.sub("", name)
    t = re.sub(r"^(.*?), (the|a|an)\b", r"\2 \1", t, flags=re.I)
    return re.sub(r"[^a-z0-9]+", "", t.lower())


def _get(url: str, timeout=12) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": f"Relic/{VERSION}"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


class Art:
    def __init__(self, data_dir: Path, ra, config):
        self.dir = data_dir / "art"
        self.custom = data_dir / "customart"
        for d in (self.dir, self.custom, self.dir / "_index"):
            d.mkdir(parents=True, exist_ok=True)
        self.ra = ra
        self.config = config
        self._misses_path = self.dir / "_misses.json"
        try:
            self._misses: dict[str, float] = json.loads(self._misses_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self._misses = {}
        self._lock = threading.Lock()
        self._net = threading.Semaphore(4)
        self._index: dict[str, dict[str, list[str]]] = {}
        self._index_locks: dict[str, threading.Lock] = {}
        self._local_idx: dict[str, dict[str, str]] = {}

    # ------------------------------------------------------------- public
    def find(self, game: dict, db: str, kind: str = "boxart") -> Path | None:
        if kind not in KINDS:
            return None
        custom = self.custom / f"{game['id']}_{kind}"
        for ext in (".png", ".jpg", ".webp"):
            if custom.with_suffix(ext).is_file():
                return custom.with_suffix(ext)
        cached = self.dir / f"{game['id']}_{kind}.png"
        if cached.is_file():
            return cached
        local = self._local(game["label"], db, kind)
        if local:
            return local
        miss_key = f"{game['id']}_{kind}"
        if not self.config["download_art"] or time.time() - self._misses.get(miss_key, 0) < MISS_DAYS * 86400:
            return None
        with self._net:
            if cached.is_file():  # another request got it while this one waited
                return cached
            data = self._download(game["label"], db, kind)
        if data:
            tmp = cached.with_suffix(".tmp")
            tmp.write_bytes(data)
            tmp.replace(cached)
            return cached
        with self._lock:
            self._misses[miss_key] = time.time()
            try:
                self._misses_path.write_text(json.dumps(self._misses), encoding="utf-8")
            except OSError:
                pass
        return None

    def set_custom(self, gid: str, kind: str, data: bytes, ext: str) -> None:
        for old in self.custom.glob(f"{gid}_{kind}.*"):
            old.unlink(missing_ok=True)
        (self.custom / f"{gid}_{kind}{ext}").write_bytes(data)

    def forget_misses(self) -> None:
        self._local_idx = {}
        with self._lock:
            self._misses = {}
            self._misses_path.unlink(missing_ok=True)

    # ------------------------------------------------------------- sources
    def _local(self, label: str, db: str, kind: str) -> Path | None:
        d = self.ra.thumbnails_dir
        if not d:
            return None
        folder = d / db / KINDS[kind]
        p = folder / (thumb_name(label) + ".png")
        if p.is_file():
            return p
        # Loose match against what's on disk; the folder is listed once, not on every request.
        key = str(folder)
        idx = self._local_idx.get(key)
        if idx is None:
            idx = {}
            try:
                for f in os.scandir(folder):
                    if f.name.lower().endswith(".png"):
                        idx.setdefault(_key(f.name[:-4]), f.path)
            except OSError:
                pass
            self._local_idx[key] = idx
        hit = idx.get(_key(label))
        return Path(hit) if hit else None

    def _download(self, label: str, db: str, kind: str) -> bytes | None:
        base = f"{SERVER}/{urllib.parse.quote(db)}/{KINDS[kind]}/"
        names = [thumb_name(label)]
        loose = self._loose(label, db, kind)
        if loose and loose not in names:
            names.append(loose)
        for name in names:
            try:
                data = _get(base + urllib.parse.quote(name) + ".png")
                if data[:8] == b"\x89PNG\r\n\x1a\n":
                    return data
            except Exception as e:
                if "404" not in str(e):
                    log.info("art %s/%s: %s", db, name, e)
        return None

    def _loose(self, label: str, db: str, kind: str) -> str | None:
        """The libretro folder listing, matched by title without tags, preferring your region."""
        idx = self._listing(db, kind)
        cands = idx.get(_key(label)) or []
        if not cands:
            return None
        region = re.search(r"\(([^)]*)\)", label)
        if region:
            same = [c for c in cands if region[1] in c]
            if same:
                return same[0]
        for r in PREFERRED_REGIONS:
            for c in cands:
                if f"({r}" in c:
                    return c
        return cands[0]

    def _listing(self, db: str, kind: str) -> dict[str, list[str]]:
        key = f"{db}|{kind}"
        if key in self._index:
            return self._index[key]
        lock = self._index_locks.setdefault(key, threading.Lock())
        with lock:
            if key in self._index:
                return self._index[key]
            path = self.dir / "_index" / (re.sub(r"[^\w.-]+", "_", key) + ".json")
            names: list[str] = []
            try:
                if time.time() - path.stat().st_mtime < INDEX_DAYS * 86400:
                    names = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                pass
            if not names:
                try:
                    html = _get(f"{SERVER}/{urllib.parse.quote(db)}/{KINDS[kind]}/", timeout=20).decode("utf-8", "replace")
                    names = [urllib.parse.unquote(h)[:-4] for h in LISTING.findall(html)]
                    path.write_text(json.dumps(names), encoding="utf-8")
                except Exception as e:
                    log.info("art listing for %s: %s", db, e)
            idx: dict[str, list[str]] = {}
            for n in names:
                idx.setdefault(_key(n), []).append(n)
            self._index[key] = idx
            return idx
