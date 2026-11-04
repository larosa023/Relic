"""Your game library: RetroArch's playlists plus any ROM folders you point Relic at."""

from __future__ import annotations

import hashlib
import os
import re
import threading
import time
from pathlib import Path

import systems
from systems import System
from reliclog import log

TAGS = re.compile(r"\s*[\(\[][^\)\]]*[\)\]]")
REGION = re.compile(r"\((USA|Europe|Japan|World|USA, Europe|Japan, USA|Korea|Brazil|Australia|France|Germany|Spain|Italy|En,[^)]*)\)", re.I)
DISC = re.compile(r"\((Disc|Disk|CD)\s*(\d+)[^)]*\)", re.I)
SKIP_DIRS = {"bios", "system", "saves", "states", "screenshots", "thumbnails", "media", "images", "manuals"}


def game_id(path: str) -> str:
    return hashlib.sha1(os.path.normcase(path).encode("utf-8", "surrogatepass")).hexdigest()[:12]


def clean_title(label: str) -> str:
    """"Legend of Zelda, The - A Link to the Past (USA) [!]" -> "The Legend of Zelda - A Link to the Past"."""
    t = TAGS.sub("", label).strip() or label
    t = re.sub(r"^(.*?), (The|A|An)( - .*)?$", lambda m: f"{m[2]} {m[1]}{m[3] or ''}", t)
    return t.replace("_", " ").strip()


def _ad_hoc_system(name: str) -> System:
    sid = "pl-" + re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    maker = name.split(" - ")[0] if " - " in name else ""
    short = name.split(" - ", 1)[-1]
    return System(sid, short, name, maker, 0, [], [])


class Library:
    def __init__(self, ra, config):
        self.ra = ra
        self.config = config
        self._lock = threading.Lock()
        self._games: list[dict] | None = None
        self._systems: dict[str, System] = dict(systems.BY_ID)
        self._cores: dict[str, dict] = {}
        self.scanned_at = 0.0

    # ------------------------------------------------------------- public
    def games(self, refresh: bool = False) -> list[dict]:
        with self._lock:
            if self._games is None or refresh:
                t = time.time()
                self._cores = self.ra.cores() if self.ra.found or self.ra.cfg_path else {}
                self._games = self._build()
                self.scanned_at = time.time()
                log.info("library: %d games, %d cores in %.2fs", len(self._games), len(self._cores), time.time() - t)
            return self._games

    def system(self, sid: str) -> System | None:
        return self._systems.get(sid)

    def cores(self) -> dict[str, dict]:
        self.games()
        return self._cores

    def get(self, gid: str) -> dict | None:
        return next((g for g in self.games() if g["id"] == gid), None)

    def systems_public(self) -> list[dict]:
        counts: dict[str, int] = {}
        for g in self.games():
            counts[g["system"]] = counts.get(g["system"], 0) + 1
        out = []
        order = [s[0] for s in systems.SYSTEMS]
        for sid, n in counts.items():
            s = self._systems[sid]
            d = s.public()
            d["count"] = n
            d["cores"] = self.cores_for(s)
            out.append(d)
        out.sort(key=lambda d: (order.index(d["id"]) if d["id"] in order else 999, d["name"]))
        return out

    def cores_for(self, s: System) -> list[dict]:
        """Installed cores that can run this system, best first."""
        cores = self._cores
        picked = [c for c in s.cores if c in cores]
        for cid, c in sorted(cores.items()):
            if cid not in picked and s.db in c["databases"]:
                picked.append(cid)
        return [{"id": c, "name": cores[c]["name"]} for c in picked]

    def core_path(self, game: dict, meta: dict) -> str:
        """Which core to launch a game with: yours for that game, yours for its system, the playlist's, the best installed."""
        cores = self.cores()
        choice = meta.get("core") or (self.config["system_cores"] or {}).get(game["system"])
        if choice and choice in cores:
            return cores[choice]["path"]
        if game.get("core_path") and Path(game["core_path"]).is_file():
            return game["core_path"]
        if game.get("core_path") and Path(game["core_path"]).name:
            # The playlist was made on another PC: same core, this PC's cores folder.
            name = Path(game["core_path"].replace("\\", "/")).name
            cid = name.rsplit("_libretro", 1)[0]
            if cid in cores:
                return cores[cid]["path"]
        s = self._systems.get(game["system"])
        if s:
            for c in self.cores_for(s):
                return cores[c["id"]]["path"]
        ext = game["path"].rsplit(".", 1)[-1].lower()
        for c in cores.values():
            if ext in c["exts"]:
                return c["path"]
        return ""

    # ------------------------------------------------------------- building
    def _build(self) -> list[dict]:
        seen: dict[str, dict] = {}
        hidden_pl = set(self.config["hidden_playlists"] or [])
        for name, items in self.ra.playlists():
            if name in hidden_pl or name.lower() in ("history", "favorites", "content_history", "content_favorites"):
                continue
            s = systems.from_playlist(name)
            if not s:
                s = self._systems.setdefault(_ad_hoc_system(name).id, _ad_hoc_system(name))
            for it in items:
                # A mixed playlist ("All my games") still says each game's database.
                gs = systems.from_playlist(it["db_name"]) if it["db_name"] and it["db_name"] != name else s
                self._add(seen, it["path"], it["label"], gs or s, "playlist", it["core_path"])
        for folder in self.config["rom_folders"] or []:
            self._scan_root(seen, Path(folder))
        games = list(seen.values())
        games.sort(key=lambda g: (g["system"], g["sort"]))
        return games

    def _add(self, seen, path, label, s: System, source, core_path=""):
        gid = game_id(path)
        if gid in seen:
            return
        stem = Path(path.rsplit("#", 1)[-1]).stem if "#" in path else Path(path).stem
        label = label or stem
        title = clean_title(label)
        region = REGION.search(label)
        seen[gid] = {
            "id": gid,
            "title": title,
            "label": label,  # the full No-Intro/Redump name, which box art is named after
            "sort": re.sub(r"^(the|a|an)\s+", "", title.lower()),
            "system": s.id,
            "path": path,
            "core_path": core_path,
            "region": region[1] if region else "",
            "source": source,
        }

    def _scan_root(self, seen, root: Path):
        if not root.is_dir():
            return
        s = systems.from_folder(root.name)
        if s:
            return self._scan(seen, root, s)
        try:
            subdirs = [d for d in root.iterdir() if d.is_dir()]
        except OSError:
            return
        for d in subdirs:
            if d.name.lower() in SKIP_DIRS or d.name.startswith("."):
                continue
            # A folder named after a system, or a mixed folder sorted by file type.
            self._scan(seen, d, systems.from_folder(d.name))
        loose = [f for f in root.iterdir() if f.is_file()]
        if loose:
            self._scan_files(seen, root, [f.name for f in loose], None)

    def _scan(self, seen, folder: Path, s: System | None):
        for dirpath, dirnames, filenames in os.walk(folder):
            dirnames[:] = [d for d in dirnames if d.lower() not in SKIP_DIRS and not d.startswith(".")]
            # A subfolder named after a system beats the folder above it.
            here = systems.from_folder(Path(dirpath).name) if Path(dirpath) != folder else None
            self._scan_files(seen, Path(dirpath), filenames, here or s)

    def _scan_files(self, seen, dirpath: Path, filenames: list[str], s: System | None):
        lower = {f.lower() for f in filenames}
        listed = set()  # discs that a .m3u, .cue or .gdi already covers
        for f in filenames:
            fl = f.lower()
            if not fl.endswith((".m3u", ".cue", ".gdi")):
                continue
            try:
                for line in (dirpath / f).read_text(encoding="utf-8", errors="replace").splitlines():
                    line = line.strip()
                    if fl.endswith(".m3u") and line and not line.startswith("#"):
                        listed.add(Path(line).name.lower())
                    m = re.search(r'FILE\s+"([^"]+)"', line) or (re.search(r"(\S+\.(?:bin|raw))", line, re.I) if fl.endswith(".gdi") else None)
                    if m:
                        listed.add(Path(m[1]).name.lower())
            except OSError:
                pass
        has_m3u = any(f.endswith(".m3u") for f in lower)
        for f in filenames:
            fl = f.lower()
            if fl in listed:
                continue
            ext = fl.rsplit(".", 1)[-1] if "." in fl else ""
            if s is None:
                sys_ = systems.BY_EXT.get(ext)  # a mixed folder: only file types that say their system
                if not sys_:
                    continue
            elif ext in s.exts:
                sys_ = s
            elif ext in systems.SHARED_EXT:
                if ext == "bin" and s.exts:
                    continue  # loose disc tracks; the .cue is the game
                sys_ = s
            elif s.id in ("gb", "gbc") and ext in ("gb", "gbc"):
                sys_ = systems.BY_EXT[ext]  # Game Boy folders often hold both
            else:
                continue
            if has_m3u and DISC.search(f) and not fl.endswith(".m3u"):
                continue  # one entry per multi-disc game
            self._add(seen, str(dirpath / f), Path(f).stem, sys_, "scan")
