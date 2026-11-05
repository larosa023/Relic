"""Finding RetroArch and reading what it already knows: its settings, cores and playlists.

Relic never changes RetroArch's own files. It reads retroarch.cfg to find the
cores, info, playlist and thumbnail folders, and launches games with
`retroarch -L <core> "<game>"`.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from reliclog import log

IS_WIN = sys.platform == "win32"
EXE = "retroarch.exe" if IS_WIN else "retroarch"
CORE_SUFFIX = "_libretro.dll" if IS_WIN else ("_libretro.dylib" if sys.platform == "darwin" else "_libretro.so")


def _candidates() -> list[Path]:
    env = os.environ.get
    out = []
    if IS_WIN:
        for base in (env("APPDATA"), env("LOCALAPPDATA")):
            if base:
                out.append(Path(base) / "RetroArch")
        for drive in ("C:", "D:", "E:"):
            out += [Path(drive + "\\RetroArch-Win64"), Path(drive + "\\RetroArch"), Path(drive + "\\Games\\RetroArch")]
        for pf in (env("ProgramFiles(x86)"), env("ProgramFiles")):
            if pf:
                out += [Path(pf) / "Steam" / "steamapps" / "common" / "RetroArch", Path(pf) / "RetroArch"]
        out.append(Path.home() / "scoop" / "apps" / "retroarch" / "current")
        out += _from_registry() + _steam_libraries()
    else:
        out += [Path.home() / ".config" / "retroarch", Path.home() / ".var/app/org.libretro.RetroArch/config/retroarch",
                Path.home() / ".steam/steam/steamapps/common/RetroArch"]
    on_path = shutil.which("retroarch")
    if on_path:
        out.insert(0, Path(on_path).resolve().parent)
    return out


def _from_registry() -> list[Path]:
    """Where the RetroArch installer says it put RetroArch (Apps & features)."""
    out = []
    try:
        import winreg
    except ImportError:
        return out
    key = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in (0, winreg.KEY_WOW64_32KEY):
            try:
                root = winreg.OpenKey(hive, key, 0, winreg.KEY_READ | view)
            except OSError:
                continue
            for i in range(winreg.QueryInfoKey(root)[0]):
                try:
                    sub = winreg.OpenKey(root, winreg.EnumKey(root, i))
                    name = winreg.QueryValueEx(sub, "DisplayName")[0]
                    if "retroarch" not in str(name).lower():
                        continue
                    for v in ("InstallLocation", "DisplayIcon", "UninstallString"):
                        try:
                            val = str(winreg.QueryValueEx(sub, v)[0]).strip('"').split('",')[0]
                        except OSError:
                            continue
                        p = Path(val)
                        out.append(p if p.suffix == "" else p.parent)
                except OSError:
                    continue
    return out


def _steam_libraries() -> list[Path]:
    """RetroArch from Steam, in any of your Steam library folders (other drives too)."""
    out = []
    for pf in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles")):
        vdf = Path(pf or "") / "Steam" / "steamapps" / "libraryfolders.vdf"
        try:
            text = vdf.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in re.finditer(r'"path"\s+"([^"]+)"', text):
            out.append(Path(m[1].replace("\\\\", "\\")) / "steamapps" / "common" / "RetroArch")
    return out


def read_cfg(path: Path) -> dict[str, str]:
    """retroarch.cfg is `key = "value"` lines."""
    cfg = {}
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return cfg
    for line in text.splitlines():
        if "=" not in line or line.lstrip().startswith("#"):
            continue
        k, v = line.split("=", 1)
        cfg[k.strip()] = v.strip().strip('"')
    return cfg


class RetroArch:
    def __init__(self, path: str | None = None):
        self.root: Path | None = None   # folder with retroarch.exe
        self.exe: Path | None = None
        self.cfg_path: Path | None = None
        self.cfg: dict[str, str] = {}
        self.find(path)

    @property
    def found(self) -> bool:
        return bool(self.exe)

    # ------------------------------------------------------------- locating
    def find(self, path: str | None = None) -> None:
        tries = [Path(path)] if path else _candidates()
        exe_dir = cfg_file = None
        for d in tries:
            d = d.parent if d.is_file() else d
            if exe_dir is None and (d / EXE).is_file():
                exe_dir = d
            if cfg_file is None and (d / "retroarch.cfg").is_file():
                cfg_file = d / "retroarch.cfg"
            if exe_dir and cfg_file:
                break
        # The installer keeps the exe in Program Files and the settings in %APPDATA%; a
        # portable copy has both together, which wins when it exists.
        if exe_dir and (exe_dir / "retroarch.cfg").is_file():
            cfg_file = exe_dir / "retroarch.cfg"
        self.root = exe_dir or (cfg_file.parent if cfg_file else None)
        self.exe = exe_dir / EXE if exe_dir else None
        self.cfg_path = cfg_file
        self.cfg = read_cfg(cfg_file) if cfg_file else {}
        log.info("RetroArch: exe=%s cfg=%s", self.exe, self.cfg_path)

    def _dir(self, key: str, default: str) -> Path | None:
        """A folder from retroarch.cfg. ':' means 'next to retroarch.exe', '~' your home."""
        base = self.root or (self.cfg_path.parent if self.cfg_path else None)
        v = self.cfg.get(key, "")
        if not v or v == "default":
            return base / default if base else None
        if v.startswith(":"):
            return (base / v[1:].lstrip("\\/")) if base else None
        return Path(os.path.expanduser(v))

    @property
    def cores_dir(self): return self._dir("libretro_directory", "cores")
    @property
    def info_dir(self): return self._dir("libretro_info_path", "info")
    @property
    def playlist_dir(self): return self._dir("playlist_directory", "playlists")
    @property
    def thumbnails_dir(self): return self._dir("thumbnails_directory", "thumbnails")

    # ------------------------------------------------------------- cores
    def cores(self) -> dict[str, dict]:
        """Installed cores: {"snes9x": {"path", "name", "exts", "systems"}}."""
        out = {}
        d = self.cores_dir
        if not d or not d.is_dir():
            return out
        for f in d.glob("*" + CORE_SUFFIX):
            cid = f.name[: -len(CORE_SUFFIX)]
            info = self._core_info(cid)
            out[cid] = {
                "id": cid,
                "path": str(f),
                "name": _core_name(info.get("display_name", ""), cid),
                "exts": [e for e in info.get("supported_extensions", "").split("|") if e],
                "databases": [x for x in info.get("database", "").split("|") if x],
            }
        return out

    def _core_info(self, cid: str) -> dict[str, str]:
        for d in (self.info_dir, self.cores_dir):
            if d and (d / f"{cid}_libretro.info").is_file():
                return read_cfg(d / f"{cid}_libretro.info")
        return {}

    # ------------------------------------------------------------- playlists
    def playlists(self) -> list[tuple[str, list[dict]]]:
        """Every playlist RetroArch has: [(name, [{"path", "label", "core_path", "db_name"}])]."""
        d = self.playlist_dir
        if not d or not d.is_dir():
            return []
        out = []
        for f in sorted(d.glob("*.lpl")):
            try:
                items = parse_playlist(f)
            except Exception:
                log.exception("couldn't read playlist %s", f.name)
                continue
            out.append((f.stem, items))
        return out

    # ------------------------------------------------------------- launching
    def launch(self, core_path: str, game_path: str, fullscreen: bool = True) -> subprocess.Popen:
        if not self.exe:
            raise RuntimeError("RetroArch wasn't found. Set its folder in Settings.")
        if not Path(core_path).is_file():
            raise RuntimeError(f"The core {Path(core_path).name} isn't installed. Download it in RetroArch's Online Updater.")
        # "Game.zip#Game.sfc" means a file inside an archive.
        if not Path(game_path).exists() and not Path(game_path.rsplit("#", 1)[0]).exists():
            raise RuntimeError("That game's file has moved or been deleted.")
        args = [str(self.exe), "-L", core_path, game_path]
        if fullscreen:
            args.insert(1, "-f")
        if self.cfg_path and self.cfg_path.parent != self.exe.parent:
            args[1:1] = ["--config", str(self.cfg_path)]
        log.info("launching %s", args)
        flags = 0x00000200 if IS_WIN else 0  # CREATE_NEW_PROCESS_GROUP
        return subprocess.Popen(args, cwd=str(self.exe.parent), creationflags=flags)


def _core_name(display: str, cid: str) -> str:
    """"Nintendo - SNES / SFC (Snes9x - Current)" -> "Snes9x - Current"."""
    m = re.search(r"\(([^()]*(?:\([^()]*\))?[^()]*)\)\s*$", display)
    if m:
        return m[1]
    return display or cid.replace("_", " ").title()


def parse_playlist(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8", errors="replace")
    if text.lstrip().startswith("{"):
        data = json.loads(text)
        items = data.get("items") or []
        default_core = data.get("default_core_path") or ""
        return [{
            "path": it.get("path", ""),
            "label": it.get("label", ""),
            "core_path": (it.get("core_path") if it.get("core_path") not in (None, "", "DETECT") else default_core) or "",
            "db_name": (it.get("db_name") or "").removesuffix(".lpl"),
        } for it in items if it.get("path")]
    # The old format: six lines per game.
    lines = text.splitlines()
    out = []
    for i in range(0, len(lines) - 5, 6):
        p, label, core, _cname, _crc, db = lines[i:i + 6]
        out.append({"path": p, "label": label, "core_path": "" if core == "DETECT" else core,
                    "db_name": db.removesuffix(".lpl")})
    return out
