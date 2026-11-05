"""Standalone emulators, for systems RetroArch has no core for (PS4, PS3, Switch, Wii U, Xbox, Xbox 360).

Each one is its own program. Relic finds it (or you point Relic at its .exe in Settings → Other
emulators) and starts it with the game, the same way it starts RetroArch.
"""

from __future__ import annotations

import os
import struct
import subprocess
import sys
from pathlib import Path

from reliclog import log

IS_WIN = sys.platform == "win32"

# system id -> how to find and start its emulator. "{game}" in args is the game's path.
EMULATORS = {
    "ps4": {"name": "shadPS4", "site": "shadps4.net",
            "exe": ["shadPS4.exe", "shadps4.exe", "shadPS4QtLauncher.exe"], "dirs": ["shadPS4", "shadps4"],
            "args": ["-g", "{game}"], "fullscreen": ["--fullscreen", "true"]},
    "ps3": {"name": "RPCS3", "site": "rpcs3.net",
            "exe": ["rpcs3.exe"], "dirs": ["RPCS3", "rpcs3"],
            "args": ["--no-gui", "{game}"], "fullscreen": ["--fullscreen"]},
    "switch": {"name": "Ryujinx", "site": "the Ryujinx project's releases page",
               "exe": ["Ryujinx.exe", "Ryujinx.Ava.exe"], "dirs": ["Ryujinx", "ryujinx", "publish"],
               "args": ["{game}"], "fullscreen": ["--fullscreen"]},
    "wiiu": {"name": "Cemu", "site": "cemu.info",
             "exe": ["Cemu.exe", "cemu.exe"], "dirs": ["Cemu", "cemu"],
             "args": ["-g", "{game}"], "fullscreen": ["-f"]},
    "xbox": {"name": "xemu", "site": "xemu.app",
             "exe": ["xemu.exe"], "dirs": ["xemu"],
             "args": ["-dvd_path", "{game}"], "fullscreen": ["-full-screen"]},
    "xbox360": {"name": "Xenia Canary", "site": "xenia.jp",
                "exe": ["xenia_canary.exe", "xenia.exe"], "dirs": ["xenia", "xenia_canary", "Xenia"],
                "args": ["{game}"], "fullscreen": ["--fullscreen=true"]},
}


def _roots() -> list[Path]:
    """Places people keep emulators: Program Files, AppData, and the usual folders in your home."""
    env = os.environ.get
    home = Path.home()
    out = [Path(p) for p in (env("ProgramFiles"), env("ProgramFiles(x86)"), env("LOCALAPPDATA"), env("APPDATA")) if p]
    out += [Path(env("LOCALAPPDATA") or home) / "Programs"]
    out += [home / d for d in ("Downloads", "Desktop", "Documents", "Emulators", "Games", "OneDrive/Desktop", "OneDrive/Documents")]
    out += [Path(d + "\\" + sub) for d in ("C:", "D:", "E:") for sub in ("Emulators", "Games", "Emulation", "")]
    return [p for p in out if p.is_dir()]


_cache: dict[tuple, tuple[float, Path | None]] = {}


def find(sid: str, chosen: str = "") -> Path | None:
    """The emulator's .exe (remembered for a minute, so Settings and launching stay quick)."""
    import time
    hit = _cache.get((sid, chosen))
    if hit and time.time() - hit[0] < 60 and (hit[1] is None or hit[1].is_file()):
        return hit[1]
    exe = _find(sid, chosen)
    _cache[(sid, chosen)] = (time.time(), exe)
    return exe


def _find(sid: str, chosen: str = "") -> Path | None:
    """The one you chose, or one found in the usual places (two folders deep)."""
    emu = EMULATORS.get(sid)
    if not emu:
        return None
    if chosen:
        p = Path(chosen)
        if p.is_file():
            return p
        for name in emu["exe"]:
            if (p / name).is_file():
                return p / name
    names = {n.lower() for n in emu["exe"]}
    dirs = {d.lower() for d in emu["dirs"]}
    for root in _roots():
        try:
            for a in os.scandir(root):
                if not a.is_dir():
                    continue
                low = a.name.lower()
                # Only look inside folders whose name mentions the emulator (keeps this quick).
                if not any(d in low for d in dirs) and low not in ("emulators", "emulation"):
                    continue
                for f in _exe_in(Path(a.path), names, depth=2):
                    return f
        except OSError:
            continue
    return None


def _exe_in(folder: Path, names: set[str], depth: int):
    try:
        entries = list(os.scandir(folder))
    except OSError:
        return
    for e in entries:
        if e.is_file() and e.name.lower() in names:
            yield Path(e.path)
    if depth > 0:
        for e in entries:
            if e.is_dir() and not e.name.startswith("."):
                yield from _exe_in(Path(e.path), names, depth - 1)


def launch(sid: str, exe: Path, game_path: str, fullscreen: bool) -> subprocess.Popen:
    emu = EMULATORS[sid]
    if not Path(game_path).exists():
        raise RuntimeError("That game's file has moved or been deleted.")
    args = [str(exe)] + (emu["fullscreen"] if fullscreen else []) + [a.replace("{game}", game_path) for a in emu["args"]]
    log.info("launching %s", args)
    flags = 0x00000200 if IS_WIN else 0
    return subprocess.Popen(args, cwd=str(exe.parent), creationflags=flags)


def sfo_title(path: Path) -> str:
    """The game's name from a PS3/PS4 PARAM.SFO file."""
    try:
        data = path.read_bytes()
        if data[:4] != b"\x00PSF":
            return ""
        key_start, data_start, count = struct.unpack_from("<III", data, 8)
        for i in range(count):
            key_off, _fmt, length, _max, data_off = struct.unpack_from("<HHIII", data, 20 + i * 16)
            key = data[key_start + key_off:].split(b"\x00", 1)[0]
            if key == b"TITLE":
                raw = data[data_start + data_off: data_start + data_off + length]
                return raw.split(b"\x00", 1)[0].decode("utf-8", "replace").strip()
    except (OSError, struct.error):
        pass
    return ""
