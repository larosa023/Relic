"""What Relic adds on top of RetroArch when it starts a game, and a few helpers around it.

  * a per-launch override config: Select + Start quits back to Relic, auto save/load (Resume),
    RetroAchievements sign-in. Your own retroarch.cfg is never changed.
  * the CRT look (a RetroArch shader), on retro systems or everything
  * Resume detection: RetroArch's automatic save for a game
  * Select + Start for standalone emulators too (watched with XInput while one runs)
  * RetroAchievements sign-in (Relic keeps only the token, never your password)
  * BIOS import: recognises BIOS files by name and content and copies each where its core looks
"""

from __future__ import annotations

import ctypes
import json
import os
import shutil
import sys
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

from reliclog import log
from version import VERSION

IS_WIN = sys.platform == "win32"

# 2D-era home consoles and arcade: where a CRT look is how the games were meant to be seen.
RETRO_CRT = {"nes", "fds", "snes", "sms", "genesis", "segacd", "32x", "sg1000", "pce", "pcecd", "sgx", "pcfx",
             "atari2600", "atari5200", "atari7800", "atari800", "coleco", "intv", "odyssey2", "channelf",
             "neocd", "arcade", "msx", "c64", "amiga", "zx", "cpc", "psx", "saturn", "n64", "3do", "cdi", "naomi"}
# Lightest to heaviest; the first one that exists is used.
CRT_SHADERS = ["shaders_slang/crt/crt-easymode.slangp", "shaders_slang/crt/crt-lottes.slangp",
               "shaders_slang/crt/crt-geom.slangp", "shaders_glsl/crt/crt-easymode.glslp"]


def _q(v) -> str:
    return '"' + str(v).replace('"', "") + '"'


def write_override(path: Path, cfg, resume: bool) -> Path:
    """Relic's settings for this launch, appended on top of your RetroArch settings."""
    lines = {
        # Select + Start closes the game (no "press again to quit" prompt) and you're back in Relic.
        "input_quit_gamepad_combo": "4" if cfg["quit_combo"] else "0",
        "quit_press_twice": "false",
        "savestate_auto_save": "true" if cfg["resume"] else "false",
        "savestate_auto_load": "true" if (cfg["resume"] and resume) else "false",
        "input_autodetect_enable": "true",
    }
    ra = cfg["retroachievements"] or {}
    if ra.get("user") and ra.get("token"):
        lines.update({"cheevos_enable": "true", "cheevos_username": ra["user"], "cheevos_token": ra["token"],
                      "cheevos_password": "", "cheevos_hardcore_mode_enable": "true" if ra.get("hardcore") else "false"})
    path.write_text("".join(f"{k} = {_q(v)}\n" for k, v in lines.items()), encoding="utf-8")
    return path


def crt_shader(ra, cfg, system: str) -> str:
    mode = cfg["crt"] or "off"
    if mode == "off" or (mode == "retro" and system not in RETRO_CRT):
        return ""
    base = ra.shaders_dir
    if not base:
        return ""
    for rel in CRT_SHADERS:
        p = base / rel
        if p.is_file():
            return str(p)
    # Unpacked one folder deeper than expected? Look once.
    for rel in CRT_SHADERS:
        hit = next(base.glob("*/" + rel), None) or next(base.glob("*/*/" + rel.split("/", 1)[1]), None)
        if hit:
            return str(hit)
    return ""


# ------------------------------------------------------------------ resume
class States:
    """Which games have an automatic save (RetroArch's <game>.state.auto), found with one quick walk."""

    def __init__(self, ra):
        self.ra = ra
        self._at = 0.0
        self._stems: set[str] = set()

    def stems(self) -> set[str]:
        if time.time() - self._at < 10:
            return self._stems
        out = set()
        d = self.ra.states_dir
        if d and d.is_dir():
            for root, _dirs, files in os.walk(d):
                for f in files:
                    if f.endswith(".state.auto"):
                        out.add(f[: -len(".state.auto")].lower())
        self._stems, self._at = out, time.time()
        return out

    def forget(self):
        self._at = 0.0

    def has(self, game_path: str) -> bool:
        name = game_path.replace("\\", "/").rsplit("/", 1)[-1].rsplit("#", 1)[-1]
        return name.rsplit(".", 1)[0].lower() in self.stems()


# ------------------------------------------------------------------ Select + Start for standalone emulators
class _XState(ctypes.Structure):
    _fields_ = [("packet", ctypes.c_uint32), ("buttons", ctypes.c_uint16), ("lt", ctypes.c_ubyte), ("rt", ctypes.c_ubyte),
                ("lx", ctypes.c_short), ("ly", ctypes.c_short), ("rx", ctypes.c_short), ("ry", ctypes.c_short)]


def _xinput():
    for dll in ("xinput1_4", "xinput1_3", "xinput9_1_0"):
        try:
            return getattr(ctypes.windll, dll).XInputGetState
        except (OSError, AttributeError):
            continue
    return None


def watch_quit_combo(proc, stop: threading.Event) -> None:
    """While a standalone emulator runs: Back + Start held for a moment closes it (politely first)."""
    if not IS_WIN:
        return
    get = _xinput()
    if not get:
        return
    BACK, START = 0x0020, 0x0010
    held_since = 0.0
    st = _XState()
    while proc.poll() is None and not stop.is_set():
        down = any(get(i, ctypes.byref(st)) == 0 and (st.buttons & (BACK | START)) == (BACK | START) for i in range(4))
        if down:
            held_since = held_since or time.time()
            if time.time() - held_since > 0.8:
                log.info("Back + Start: closing the emulator")
                close_process(proc)
                return
        else:
            held_since = 0.0
        time.sleep(0.05)


def close_process(proc) -> None:
    """Ask the program's windows to close (so it can save), then make sure it's gone."""
    if IS_WIN:
        user32 = ctypes.windll.user32
        WM_CLOSE = 0x0010
        pid = proc.pid
        proto = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

        def each(hwnd, _):
            owner = ctypes.c_ulong()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
            if owner.value == pid and user32.IsWindowVisible(hwnd):
                user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
            return True
        user32.EnumWindows(proto(each), 0)
    try:
        proc.wait(timeout=6)
    except Exception:
        proc.terminate()


# ------------------------------------------------------------------ RetroAchievements
RA_API = os.environ.get("RELIC_RA_API", "https://retroachievements.org/dorequest.php")


def ra_login(user: str, password: str) -> dict:
    """Sign in to RetroAchievements; returns {"user", "token"}. The password isn't kept."""
    data = urllib.parse.urlencode({"r": "login2", "u": user, "p": password}).encode()
    req = urllib.request.Request(RA_API, data=data, headers={"User-Agent": f"Relic/{VERSION}"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            res = json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        try:
            res = json.loads(e.read().decode("utf-8", "replace"))
        except Exception:
            raise RuntimeError("Couldn't reach RetroAchievements. Try again in a bit.")
    except Exception:
        raise RuntimeError("Couldn't reach RetroAchievements. Check your connection and try again.")
    if not res.get("Success") or not res.get("Token"):
        raise RuntimeError(res.get("Error") or "That username and password didn't work.")
    return {"user": res.get("User") or user, "token": res["Token"], "score": res.get("Score", 0)}


# ------------------------------------------------------------------ BIOS import
# BIOS files by name (lowercase) -> folder under RetroArch's system folder.
BIOS_NAMES = {
    # PlayStation
    **{n: "" for n in ("scph5500.bin", "scph5501.bin", "scph5502.bin", "scph1001.bin", "scph7001.bin", "scph7502.bin",
                       "scph101.bin", "scph1000.bin", "scph3500.bin", "scph5000.bin", "ps1_rom.bin", "psxonpsp660.bin")},
    # Sega
    **{n: "" for n in ("bios_cd_u.bin", "bios_cd_e.bin", "bios_cd_j.bin", "bios_md.bin", "bios_ms.bin", "bios_gg.bin",
                       "sega_101.bin", "mpr-17933.bin", "saturn_bios.bin", "mpr-18811-mx.ic1", "mpr-19367-mx.ic1")},
    "dc_boot.bin": "dc", "dc_flash.bin": "dc", "naomi.zip": "dc", "awbios.zip": "dc", "naomi2.zip": "dc",
    # NEC
    **{n: "" for n in ("syscard1.pce", "syscard2.pce", "syscard3.pce", "gexpress.pce", "pcfx.rom")},
    # Nintendo
    **{n: "" for n in ("gba_bios.bin", "gb_bios.bin", "gbc_bios.bin", "sgb_bios.bin", "sgb2_bios.bin",
                       "disksys.rom", "bios7.bin", "bios9.bin", "firmware.bin", "dsi_bios7.bin", "dsi_bios9.bin",
                       "dsi_firmware.bin", "dsi_nand.bin", "bios.min")},
    # 3DO, Neo Geo, Atari, others
    **{n: "" for n in ("panafz1.bin", "panafz10.bin", "panafz10-norsa.bin", "panafz10e-anvil.bin", "goldstar.bin",
                       "sanyotry.bin", "3do_arcade_saot.bin", "neogeo.zip", "lynxboot.img", "5200.rom",
                       "7800 bios (u).rom", "7800 bios (e).rom", "colecovision.rom", "exec.bin", "grom.bin",
                       "atarixl.rom", "ataribas.rom", "atariosa.rom", "atariosb.rom", "tos.img", "kick34005.a500",
                       "kick40063.a600", "kick40068.a1200", "o2rom.bin", "sl31253.bin", "sl31254.bin", "cdi.zip")},
    **{n: "neocd" for n in ("neocd_f.rom", "neocd_sf.rom", "neocd_t.rom", "neocd_st.rom", "neocd_z.rom",
                            "neocd_sz.rom", "front-sp1.bin", "top-sp1.bin", "neocd.bin", "uni-bioscd.rom")},
}


def _ps2_bios(p: Path, size: int) -> bool:
    if not (2 << 20) <= size <= (8 << 20) or p.suffix.lower() not in (".bin", ".rom", ""):
        return False
    try:
        with open(p, "rb") as f:
            head = f.read(1 << 16)
        return b"RESET\x00" in head and b"ROMDIR" in head
    except OSError:
        return False


def _ps1_bios(p: Path, size: int) -> bool:
    if size != 512 * 1024 or p.suffix.lower() not in (".bin", ".rom", ""):
        return False
    try:
        with open(p, "rb") as f:
            data = f.read()
        return b"Sony Computer Entertainment Inc" in data and b"PlayStation" in data
    except OSError:
        return False


def import_bios(src: Path, system_dir: Path) -> list[dict]:
    """Copy every BIOS file found in `src` (and its subfolders) to where its core looks for it."""
    done = []
    if not src.is_dir():
        raise RuntimeError("That folder doesn't exist.")
    for root, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if not d.startswith(".")][:200]
        for f in files:
            p = Path(root) / f
            try:
                size = p.stat().st_size
            except OSError:
                continue
            if size > 64 << 20:
                continue
            name = f.lower()
            if name in BIOS_NAMES:
                dest = system_dir / BIOS_NAMES[name] / f
                kind = "BIOS"
            elif _ps2_bios(p, size):
                dest = system_dir / "pcsx2" / "bios" / f
                kind = "PS2 BIOS"
            elif _ps1_bios(p, size):
                dest = system_dir / f
                kind = "PS1 BIOS"
            else:
                continue
            if dest.resolve() == p.resolve():
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            if not dest.exists() or dest.stat().st_size != size:
                shutil.copy2(p, dest)
            done.append({"file": f, "kind": kind, "to": str(dest.parent)})
    log.info("BIOS import from %s: %d files", src, len(done))
    return done
