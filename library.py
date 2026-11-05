"""Your game library: RetroArch's playlists plus any ROM folders you point Relic at."""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from pathlib import Path

import standalone
import systems
from systems import System
from reliclog import log

TAGS = re.compile(r"\s*[\(\[][^\)\]]*[\)\]]")
REGION = re.compile(r"\((USA|Europe|Japan|World|USA, Europe|Japan, USA|Korea|Brazil|Australia|France|Germany|Spain|Italy|En,[^)]*)\)", re.I)
DISC = re.compile(r"\((Disc|Disk|CD)\s*(\d+)[^)]*\)", re.I)
CACHE_FORMAT = 2
SKIP_DIRS = {"bios", "system", "saves", "states", "screenshots", "thumbnails", "media", "images", "manuals"}


NINTENDO_DISC_EXT = {"iso", "rvz", "gcz", "wia", "ciso", "gcm", "wbfs"}


def _sniff_nintendo_disc(p: Path) -> str | None:
    """"gamecube" or "wii" if this disc image is one (by its header), else None. Reads 128 bytes."""
    try:
        with open(p, "rb") as f:
            h = f.read(0x60)
    except OSError:
        return None
    if len(h) < 0x20:
        return None
    if h[:4] in (b"RVZ\x01", b"WIA\x01"):  # Dolphin's formats: disc type 1 = GameCube, 2 = Wii
        t = int.from_bytes(h[0x48:0x4C], "big")
        return {1: "gamecube", 2: "wii"}.get(t)
    if h[:4] == b"\x01\xc0\x0b\xb1":  # GCZ: sub type 0 = GameCube, 1 = Wii
        t = int.from_bytes(h[4:8], "little")
        return {0: "gamecube", 1: "wii"}.get(t)
    if h[:4] == b"WBFS":
        return "wii"
    if h[:4] == b"CISO":
        try:
            with open(p, "rb") as f:
                f.seek(0x8000)
                h = f.read(0x20)
        except OSError:
            return None
    # A plain disc image: the magic words in the disc header.
    if len(h) >= 0x20:
        if h[0x18:0x1C] == b"\x5d\x1c\x9e\xa3":
            return "wii"
        if h[0x1C:0x20] == b"\xc2\x33\x9f\x3d":
            return "gamecube"
    return None


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
    """Builds the library and keeps it on disk, so Relic opens instantly and rescans quietly behind."""

    def __init__(self, ra, config, cache_path: Path | None = None):
        self.ra = ra
        self.config = config
        self.cache_path = cache_path
        self._lock = threading.Lock()        # guards the swap of results
        self._build_lock = threading.Lock()  # one scan at a time
        self._games: list[dict] | None = None
        self._by_id: dict[str, dict] = {}
        self._systems: dict[str, System] = dict(systems.BY_ID)
        self._cores: dict[str, dict] = {}
        self._sig = ""
        self.rev = 0                         # goes up whenever the library changes
        self._changed = threading.Condition()
        self.scanned_at = 0.0
        self.after_scan: list = []  # run after every scan (game details, BIOS checks)
        self.on_refresh: list = []

    # ------------------------------------------------------------- loading
    def start(self) -> None:
        """Show last time's library straight away, then check for changes in the background."""
        if self._load_cache():
            threading.Thread(target=self.refresh, daemon=True).start()
        else:
            threading.Thread(target=self.games, daemon=True).start()

    def _load_cache(self) -> bool:
        if not self.cache_path:
            return False
        try:
            data = json.loads(self.cache_path.read_text(encoding="utf-8"))
            if data.get("format") != CACHE_FORMAT:
                return False
            for sid, name, db, maker in data.get("adhoc", []):
                self._systems.setdefault(sid, System(sid, name, db, maker, 0, [], []))
            self._swap(data["games"], data.get("cores", {}))
            log.info("library: %d games from cache", len(data["games"]))
            return True
        except (OSError, ValueError, KeyError, TypeError):
            return False

    def _save_cache(self) -> None:
        if not self.cache_path:
            return
        adhoc = [[s.id, s.name, s.db, s.maker] for s in self._systems.values() if s.id.startswith("pl-")]
        data = {"format": CACHE_FORMAT, "games": self._games, "cores": self._cores, "adhoc": adhoc}
        try:
            tmp = self.cache_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
            os.replace(tmp, self.cache_path)
        except OSError:
            log.exception("couldn't save the library cache")

    def _swap(self, games: list[dict], cores: dict) -> bool:
        sig = hashlib.sha1(json.dumps([games, sorted(cores)], sort_keys=True).encode()).hexdigest()
        with self._lock:
            changed = sig != self._sig
            self._games, self._cores, self._sig = games, cores, sig
            self._by_id = {g["id"]: g for g in games}
        if changed:
            with self._changed:
                self.rev += 1
                self._changed.notify_all()
        return changed

    def refresh(self) -> bool:
        """Rescan now. True if anything changed."""
        with self._build_lock:
            t = time.time()
            cores = self.ra.cores() if self.ra.found or self.ra.cfg_path else {}
            games = self._build(cores)
            changed = self._swap(games, cores)
            self.scanned_at = time.time()
            log.info("library: %d games, %d cores in %.2fs%s", len(games), len(cores), time.time() - t,
                     "" if changed else " (no change)")
            if changed or not (self.cache_path and self.cache_path.exists()):
                self._save_cache()
            for fn in list(self.after_scan):
                try:
                    fn()
                except Exception:
                    log.exception("after-scan step failed")
            return changed


    def bump(self) -> None:
        """Something about the games changed outside a scan (game details arrived): tell the page."""
        with self._changed:
            self.rev += 1
            self._changed.notify_all()
        for fn in list(self.on_refresh):
            try:
                fn()
            except Exception:
                log.exception("library listener failed")

    def wait(self, rev: int, timeout: float = 25) -> int:
        """Block until the library is newer than `rev` (or the timeout). Returns the current rev."""
        with self._changed:
            self._changed.wait_for(lambda: self.rev != rev, timeout)
            return self.rev

    # ------------------------------------------------------------- public
    def games(self, refresh: bool = False) -> list[dict]:
        if refresh or self._games is None:
            if refresh or not self._build_lock.locked():
                self.refresh()
            else:
                with self._build_lock:  # a scan is already running: wait for it
                    pass
        return self._games or []

    def system(self, sid: str) -> System | None:
        return self._systems.get(sid)

    def cores(self) -> dict[str, dict]:
        self.games()
        return self._cores

    def get(self, gid: str) -> dict | None:
        self.games()
        return self._by_id.get(gid)

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
            d["standalone"] = standalone.EMULATORS[sid]["name"] if sid in standalone.EMULATORS else ""
            out.append(d)
        out.sort(key=lambda d: (order.index(d["id"]) if d["id"] in order else 999, d["name"]))
        return out

    def cores_for(self, s: System, cores: dict | None = None) -> list[dict]:
        """Installed cores that can run this system, best first."""
        cores = self._cores if cores is None else cores
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
        if s and s.cores:
            # A console Relic knows, with none of its cores installed: never borrow another console's
            # (the PS2 core opens .iso files too). Setup offers the right one instead.
            return ""
        ext = game["path"].rsplit(".", 1)[-1].lower()
        for c in cores.values():
            if ext in c["exts"] and (not c["databases"] or (s and s.db in c["databases"])):
                return c["path"]
        return ""

    # ------------------------------------------------------------- building
    def _build(self, cores: dict) -> list[dict]:
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
        try:
            added = int(os.stat(path.rsplit("#", 1)[0] if "#" in path and not os.path.exists(path) else path).st_mtime)
        except OSError:
            added = 0
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
            "added": added,
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
            cur = here or s
            if cur and cur.id in ("ps3", "ps4") and self._folder_game(seen, Path(dirpath), filenames, dirnames, cur):
                dirnames[:] = []  # a game folder: don't look inside it for more games
                continue
            self._scan_files(seen, Path(dirpath), filenames, cur)

    def _folder_game(self, seen, d: Path, filenames, dirnames, s: System) -> bool:
        """PS4 games are folders with eboot.bin and sce_sys; PS3 games have PS3_GAME/USRDIR/EBOOT.BIN."""
        lower = {f.lower(): f for f in filenames}
        if s.id == "ps4" and "eboot.bin" in lower:
            title = standalone.sfo_title(d / "sce_sys" / "param.sfo") or d.name
            self._add(seen, str(d / lower["eboot.bin"]), title, s, "scan")
            return True
        if s.id == "ps3":
            sub = {x.lower(): x for x in dirnames}
            if "ps3_game" in sub:
                base = d / sub["ps3_game"]
                title = standalone.sfo_title(base / "PARAM.SFO") or d.name
                self._add(seen, str(base / "USRDIR" / "EBOOT.BIN"), title, s, "scan")
                return True
            if "eboot.bin" in lower and d.name.lower() == "usrdir":
                title = standalone.sfo_title(d.parent / "PARAM.SFO") or d.parent.name
                self._add(seen, str(d / lower["eboot.bin"]), title, s, "scan")
                return True
        return False

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
            disc = _sniff_nintendo_disc(dirpath / f) if ext in NINTENDO_DISC_EXT else None
            if disc:
                sys_ = systems.BY_ID[disc]  # the disc says what it is, whatever folder it's in
            elif s is None:
                sys_ = systems.BY_EXT.get(ext)  # a mixed folder: only file types that say their system
                if not sys_:
                    continue
            elif ext in s.exts:
                sys_ = s
            elif ext in systems.SHARED_EXT:
                if ext == "bin" and s.exts:
                    continue  # loose disc tracks; the .cue is the game
                sys_ = s
            elif ext in systems.BY_EXT:
                sys_ = systems.BY_EXT[ext]  # a file type that says its system (.gbc in a Game Boy folder)
            else:
                continue
            if has_m3u and DISC.search(f) and not fl.endswith(".m3u"):
                continue  # one entry per multi-disc game
            label = Path(f).stem
            # "default.xex" or "code/game.rpx": the game's name is the folder it's in.
            if label.lower() in ("default", "eboot", "main") or dirpath.name.lower() == "code":
                label = (dirpath.parent if dirpath.name.lower() == "code" else dirpath).name
            self._add(seen, str(dirpath / f), label, sys_, "scan")
