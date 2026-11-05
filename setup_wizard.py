"""Built-in setup: Relic downloads and installs what a game needs, so you just press Play.

  * RetroArch itself (the portable build, into %LOCALAPPDATA%\\Relic\\RetroArch)
  * the RetroArch core for the system (from the libretro buildbot, the same place RetroArch's own
    Online Updater gets them)
  * standalone emulators for newer consoles (the official release on GitHub)

BIOS files are the one thing Relic can't download: they're copyrighted and must come from your own
console. Relic tells you which file a system needs and opens the folder to put it in.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import threading
import time
import urllib.request
import zipfile
from pathlib import Path

import standalone
from reliclog import log
from version import VERSION

BUILDBOT = os.environ.get("RELIC_BUILDBOT", "https://buildbot.libretro.com")
GITHUB_API = os.environ.get("RELIC_GITHUB_API", "https://api.github.com")
PLATFORM = "windows/x86_64"

# Official releases of the standalone emulators: GitHub repo and which download is the Windows build.
STANDALONE_RELEASES = {
    "ps4": ("shadps4-emu/shadPS4", r"win.*(qt|sdl)?.*\.zip$"),
    "ps3": ("RPCS3/rpcs3-binaries-win", r"win64.*\.7z$"),
    "wiiu": ("cemu-project/Cemu", r"windows.*x64.*\.zip$"),
    "xbox": ("xemu-project/xemu", r"win.*x86_64.*release.*\.zip$|win-release\.zip$"),
    "xbox360": ("xenia-canary/xenia-canary-releases", r"windows.*\.zip$|xenia_canary.*\.zip$"),
}

# BIOS files systems can't start without. Any one file from `files` is enough.
BIOS = {
    "ps2": {"dir": "pcsx2/bios", "files": None, "what": "a PS2 BIOS (any region), dumped from your PS2"},
    "segacd": {"dir": "", "files": ["bios_CD_U.bin", "bios_CD_E.bin", "bios_CD_J.bin"], "what": "a Sega CD BIOS (bios_CD_U.bin for US games)"},
    "saturn": {"dir": "", "files": ["sega_101.bin", "mpr-17933.bin", "saturn_bios.bin"], "what": "a Saturn BIOS (sega_101.bin or mpr-17933.bin)"},
    "pcecd": {"dir": "", "files": ["syscard3.pce"], "what": "the TurboGrafx-CD System Card 3 (syscard3.pce)"},
    "3do": {"dir": "", "files": ["panafz1.bin", "panafz10.bin", "panafz10-norsa.bin", "goldstar.bin"], "what": "a 3DO BIOS (panafz10.bin)"},
    "neocd": {"dir": "neocd", "files": ["neocd_f.rom", "neocd_sf.rom", "neocd_t.rom", "front-sp1.bin", "top-sp1.bin"], "what": "a Neo Geo CD BIOS (neocd_f.rom)"},
    "pcfx": {"dir": "", "files": ["pcfx.rom"], "what": "the PC-FX BIOS (pcfx.rom)"},
    "jaguar": None,
}


def install_root() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".local" / "share")
    d = Path(base) / "Relic"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _req(url: str, accept: str = "*/*"):
    return urllib.request.Request(url, headers={"User-Agent": f"Relic/{VERSION}", "Accept": accept})


def _get_text(url: str) -> str:
    with urllib.request.urlopen(_req(url), timeout=20) as r:
        return r.read().decode("utf-8", "replace")


def _safe_extract(archive: Path, dest: Path) -> None:
    """Unpack a .zip or .7z, refusing any path that would land outside `dest`."""
    dest.mkdir(parents=True, exist_ok=True)
    root = dest.resolve()

    def ok(name: str) -> bool:
        target = (dest / name).resolve()
        return target == root or root in target.parents

    if archive.suffix.lower() == ".7z":
        import py7zr
        with py7zr.SevenZipFile(archive, "r") as z:
            names = [n for n in z.getnames() if ok(n)]
            z.extract(path=dest, targets=names)
    else:
        with zipfile.ZipFile(archive) as z:
            for m in z.infolist():
                if ok(m.filename):
                    z.extract(m, dest)


class Setup:
    """One install job at a time; the UI polls snapshot() for progress."""

    def __init__(self, ra, config, library):
        self.ra, self.config, self.library = ra, config, library
        self._lock = threading.Lock()
        self.state = {"busy": False, "phase": "", "progress": None, "error": "", "done": False, "steps": [], "step": 0}

    def snapshot(self) -> dict:
        return dict(self.state)

    # ------------------------------------------------------------- what a game needs
    def needs(self, game: dict, meta: dict) -> dict:
        """What has to be installed (and which BIOS added) before this game can start."""
        sid = game["system"]
        s = self.library.system(sid)
        steps = []
        bios = None
        if sid in standalone.EMULATORS:
            if not standalone.find(sid, (self.config["emulators"] or {}).get(sid, "")):
                emu = standalone.EMULATORS[sid]
                if sid in STANDALONE_RELEASES:
                    steps.append({"kind": "standalone", "id": sid, "label": emu["name"]})
                else:
                    return {"steps": [], "bios": None, "manual": f"{s.name} games run in {emu['name']}. Download it from {emu['site']}, then choose it in Settings → Other emulators."}
            return {"steps": steps, "bios": None, "manual": ""}
        if not self.ra.found:
            steps.append({"kind": "retroarch", "label": "RetroArch"})
        if not self.library.core_path(game, meta) and s and s.cores:
            steps.append({"kind": "core", "id": s.cores[0], "options": list(s.cores), "label": f"{s.name} core"})
        if s:
            bios = self.missing_bios(sid)
        return {"steps": steps, "bios": bios, "manual": ""}

    def missing_bios(self, sid: str) -> dict | None:
        req = BIOS.get(sid)
        if not req:
            return None
        sysdir = self.system_dir()
        if not sysdir:
            return {"folder": "", **req}
        folder = sysdir / req["dir"] if req["dir"] else sysdir
        try:
            if req["files"] is None:
                present = folder.is_dir() and any(f.is_file() and f.suffix.lower() in (".bin", ".rom", ".nvm", "") for f in folder.iterdir())
            else:
                have = {f.name.lower() for f in folder.iterdir()} if folder.is_dir() else set()
                present = any(n.lower() in have for n in req["files"])
        except OSError:
            present = False
        return None if present else {"folder": str(folder), "what": req["what"], "files": req["files"] or []}

    def system_dir(self) -> Path | None:
        return self.ra._dir("system_directory", "system")

    # ------------------------------------------------------------- running a job
    def start(self, steps: list[dict]) -> bool:
        with self._lock:
            if self.state["busy"]:
                return False
            self.state = {"busy": True, "phase": "Starting", "progress": None, "error": "", "done": False,
                          "steps": [s["label"] for s in steps], "step": 0}
        threading.Thread(target=self._run, args=(steps,), daemon=True).start()
        return True

    def _set(self, **kw):
        self.state.update(kw)

    def _run(self, steps):
        try:
            for i, st in enumerate(steps):
                self._set(step=i, progress=None)
                if st["kind"] == "retroarch":
                    self.install_retroarch()
                elif st["kind"] == "core":
                    self.install_core(st.get("options") or [st["id"]])
                elif st["kind"] == "standalone":
                    self.install_standalone(st["id"])
            self.library.refresh()
            self._set(busy=False, done=True, phase="Ready", progress=1.0)
        except Exception as e:
            log.exception("setup failed")
            msg = str(e) if isinstance(e, RuntimeError) else f"Download failed ({type(e).__name__}). Check your internet connection and try again."
            self._set(busy=False, error=msg, phase="")

    def _download(self, url: str, label: str) -> Path:
        self._set(phase=f"Downloading {label}", progress=0.0)
        log.info("setup: downloading %s", url)
        tmp = Path(tempfile.mkdtemp(prefix="relic-"))
        dest = tmp / url.rsplit("/", 1)[-1].split("?")[0]
        with urllib.request.urlopen(_req(url), timeout=30) as r, open(dest, "wb") as f:
            total = int(r.headers.get("Content-Length") or 0)
            got = 0
            while True:
                chunk = r.read(1 << 16)
                if not chunk:
                    break
                f.write(chunk)
                got += len(chunk)
                if total:
                    self._set(progress=min(0.99, got / total))
        return dest

    # ------------------------------------------------------------- RetroArch
    def install_retroarch(self) -> None:
        listing = _get_text(f"{BUILDBOT}/stable/")
        versions = sorted({tuple(int(x) for x in m.split(".")) for m in re.findall(r'href="/?(?:stable/)?(\d+\.\d+\.\d+)/?"', listing)})
        if not versions:
            raise RuntimeError("Couldn't find a RetroArch download. Try again later, or install it from retroarch.com.")
        ver = ".".join(map(str, versions[-1]))
        archive = self._download(f"{BUILDBOT}/stable/{ver}/{PLATFORM}/RetroArch.7z", f"RetroArch {ver}")
        self._set(phase=f"Installing RetroArch {ver}", progress=None)
        dest = install_root() / "RetroArch"
        try:
            _safe_extract(archive, dest)
        finally:
            shutil.rmtree(archive.parent, ignore_errors=True)
        exe = next((p for p in dest.rglob("retroarch.exe")), None) or next((p for p in dest.rglob("retroarch")), None)
        if not exe:
            raise RuntimeError("RetroArch downloaded, but retroarch.exe wasn't in it.")
        folder = exe.parent
        # Portable RetroArch keeps its settings next to the exe; start it pointing at the right folders.
        cfg = folder / "retroarch.cfg"
        if not cfg.exists():
            cfg.write_text('libretro_directory = ":\\cores"\nlibretro_info_path = ":\\info"\n'
                           'system_directory = ":\\system"\nplaylist_directory = ":\\playlists"\n'
                           'thumbnails_directory = ":\\thumbnails"\n', encoding="utf-8")
        for sub in ("cores", "info", "system", "playlists"):
            (folder / sub).mkdir(exist_ok=True)
        self.config.update({"retroarch_path": str(folder)})
        self.ra.find(str(folder))
        try:  # core info files: names and file types for every core
            info = self._download(f"{BUILDBOT}/assets/frontend/info.zip", "core info")
            _safe_extract(info, folder / "info")
            shutil.rmtree(info.parent, ignore_errors=True)
        except Exception:
            log.info("core info download failed; cores still work")
        log.info("setup: RetroArch %s installed at %s", ver, folder)

    # ------------------------------------------------------------- cores
    def install_core(self, options: list[str]) -> str:
        cores = self.ra.cores_dir
        if not cores:
            raise RuntimeError("RetroArch isn't set up yet.")
        cores.mkdir(parents=True, exist_ok=True)
        last = None
        for cid in options:  # the best core first; fall back if the buildbot doesn't have it
            url = f"{BUILDBOT}/nightly/{PLATFORM}/latest/{cid}_libretro.dll.zip"
            try:
                archive = self._download(url, f"the {cid} core")
            except Exception as e:
                last = e
                continue
            self._set(phase=f"Installing the {cid} core", progress=None)
            try:
                _safe_extract(archive, cores)
            finally:
                shutil.rmtree(archive.parent, ignore_errors=True)
            log.info("setup: core %s installed", cid)
            return cid
        raise RuntimeError(f"Couldn't download a core ({last}). Try again, or get one in RetroArch's Online Updater.")

    # ------------------------------------------------------------- standalone emulators
    def install_standalone(self, sid: str) -> None:
        repo, pattern = STANDALONE_RELEASES[sid]
        name = standalone.EMULATORS[sid]["name"]
        self._set(phase=f"Finding the latest {name}")
        data = json.loads(_get_text(f"{GITHUB_API}/repos/{repo}/releases/latest"))
        assets = [a for a in data.get("assets", []) if re.search(pattern, a["name"], re.I)]
        if not assets:
            raise RuntimeError(f"Couldn't find a Windows download of {name}. Get it from {standalone.EMULATORS[sid]['site']}.")
        archive = self._download(assets[0]["browser_download_url"], f"{name} {data.get('tag_name', '')}".strip())
        self._set(phase=f"Installing {name}", progress=None)
        dest = install_root() / "Emulators" / name.replace(" ", "")
        try:
            _safe_extract(archive, dest)
        finally:
            shutil.rmtree(archive.parent, ignore_errors=True)
        names = {n.lower() for n in standalone.EMULATORS[sid]["exe"]}
        exe = next((p for p in dest.rglob("*") if p.name.lower() in names), None)
        if not exe:
            raise RuntimeError(f"{name} downloaded, but its program wasn't in it.")
        self.config.update({"emulators": {**(self.config["emulators"] or {}), sid: str(exe)}})
        standalone._cache.clear()
        log.info("setup: %s installed at %s", name, exe)
