"""The consoles Relic knows about.

Each system's `db` is the libretro database name. RetroArch uses it for playlist
file names ("Nintendo - Super Nintendo Entertainment System.lpl") and for its
thumbnail folders, so it's how Relic matches playlists and finds box art.

`cores` are RetroArch core names (the file is <core>_libretro.dll), best first.
Relic launches with the first one you have installed, unless you pick another.
"""

from __future__ import annotations

SYSTEMS = [
    # id, short name, db name, maker, year, extensions, cores
    ("nes", "NES", "Nintendo - Nintendo Entertainment System", "Nintendo", 1983,
     ["nes", "unf", "unif", "fds"], ["mesen", "nestopia", "fceumm", "quicknes"]),
    ("snes", "SNES", "Nintendo - Super Nintendo Entertainment System", "Nintendo", 1990,
     ["sfc", "smc", "swc", "fig", "bs"], ["snes9x", "bsnes", "bsnes_hd_beta", "mesen-s"]),
    ("n64", "Nintendo 64", "Nintendo - Nintendo 64", "Nintendo", 1996,
     ["n64", "z64", "v64"], ["mupen64plus_next", "parallel_n64"]),
    ("gb", "Game Boy", "Nintendo - Game Boy", "Nintendo", 1989,
     ["gb"], ["gambatte", "sameboy", "mgba"]),
    ("gbc", "Game Boy Color", "Nintendo - Game Boy Color", "Nintendo", 1998,
     ["gbc"], ["gambatte", "sameboy", "mgba"]),
    ("gba", "Game Boy Advance", "Nintendo - Game Boy Advance", "Nintendo", 2001,
     ["gba"], ["mgba", "vba_next", "gpsp"]),
    ("nds", "Nintendo DS", "Nintendo - Nintendo DS", "Nintendo", 2004,
     ["nds"], ["melonds", "melondsds", "desmume"]),
    ("vb", "Virtual Boy", "Nintendo - Virtual Boy", "Nintendo", 1995,
     ["vb", "vboy"], ["mednafen_vb"]),
    ("sms", "Master System", "Sega - Master System - Mark III", "Sega", 1986,
     ["sms"], ["genesis_plus_gx", "picodrive"]),
    ("genesis", "Genesis", "Sega - Mega Drive - Genesis", "Sega", 1989,
     ["md", "gen", "smd", "bin"], ["genesis_plus_gx", "picodrive", "blastem"]),
    ("segacd", "Sega CD", "Sega - Mega-CD - Sega CD", "Sega", 1992,
     [], ["genesis_plus_gx", "picodrive"]),
    ("32x", "32X", "Sega - 32X", "Sega", 1994,
     ["32x"], ["picodrive"]),
    ("gamegear", "Game Gear", "Sega - Game Gear", "Sega", 1991,
     ["gg"], ["genesis_plus_gx", "gearsystem"]),
    ("saturn", "Saturn", "Sega - Saturn", "Sega", 1995,
     [], ["mednafen_saturn", "yabasanshiro", "kronos"]),
    ("dreamcast", "Dreamcast", "Sega - Dreamcast", "Sega", 1999,
     ["gdi", "cdi"], ["flycast"]),
    ("psx", "PlayStation", "Sony - PlayStation", "Sony", 1995,
     ["pbp"], ["swanstation", "pcsx_rearmed", "mednafen_psx_hw", "mednafen_psx"]),
    ("psp", "PSP", "Sony - PlayStation Portable", "Sony", 2005,
     ["cso"], ["ppsspp"]),
    ("pce", "TurboGrafx-16", "NEC - PC Engine - TurboGrafx 16", "NEC", 1989,
     ["pce"], ["mednafen_pce_fast", "mednafen_pce"]),
    ("atari2600", "Atari 2600", "Atari - 2600", "Atari", 1977,
     ["a26"], ["stella", "stella2014"]),
    ("atari7800", "Atari 7800", "Atari - 7800", "Atari", 1986,
     ["a78"], ["prosystem"]),
    ("lynx", "Lynx", "Atari - Lynx", "Atari", 1989,
     ["lnx"], ["handy", "mednafen_lynx"]),
    ("ngp", "Neo Geo Pocket", "SNK - Neo Geo Pocket Color", "SNK", 1999,
     ["ngp", "ngc"], ["mednafen_ngp"]),
    ("wonderswan", "WonderSwan", "Bandai - WonderSwan Color", "Bandai", 2000,
     ["ws", "wsc"], ["mednafen_wswan"]),
    ("arcade", "Arcade", "FBNeo - Arcade Games", "Arcade", 1980,
     [], ["fbneo", "mame2003_plus", "mame"]),
]

# Disc formats that several systems share: Relic decides by the folder name instead.
SHARED_EXT = {"cue", "chd", "iso", "m3u", "zip", "7z", "bin", "img", "ccd", "mds"}

# Words people use for their ROM folders, mapped to a system id.
FOLDER_ALIASES = {
    "nes": "nes", "famicom": "nes", "fc": "nes", "fds": "nes",
    "snes": "snes", "sfc": "snes", "superfamicom": "snes", "supernintendo": "snes",
    "n64": "n64", "nintendo64": "n64",
    "gb": "gb", "gameboy": "gb",
    "gbc": "gbc", "gameboycolor": "gbc",
    "gba": "gba", "gameboyadvance": "gba",
    "nds": "nds", "ds": "nds", "nintendods": "nds",
    "vb": "vb", "virtualboy": "vb",
    "sms": "sms", "mastersystem": "sms",
    "genesis": "genesis", "megadrive": "genesis", "md": "genesis",
    "segacd": "segacd", "megacd": "segacd",
    "32x": "32x", "sega32x": "32x",
    "gg": "gamegear", "gamegear": "gamegear",
    "saturn": "saturn", "segasaturn": "saturn",
    "dc": "dreamcast", "dreamcast": "dreamcast",
    "psx": "psx", "ps1": "psx", "playstation": "psx", "psone": "psx",
    "psp": "psp",
    "pce": "pce", "pcengine": "pce", "tg16": "pce", "turbografx": "pce", "turbografx16": "pce",
    "atari2600": "atari2600", "2600": "atari2600",
    "atari7800": "atari7800", "7800": "atari7800",
    "lynx": "lynx", "atarilynx": "lynx",
    "ngp": "ngp", "ngpc": "ngp", "neogeopocket": "ngp",
    "ws": "wonderswan", "wsc": "wonderswan", "wonderswan": "wonderswan",
    "arcade": "arcade", "fbneo": "arcade", "mame": "arcade", "neogeo": "arcade",
}


class System:
    __slots__ = ("id", "name", "db", "maker", "year", "exts", "cores")

    def __init__(self, sid, name, db, maker, year, exts, cores):
        self.id, self.name, self.db, self.maker, self.year = sid, name, db, maker, year
        self.exts, self.cores = set(exts), list(cores)

    def public(self) -> dict:
        return {"id": self.id, "name": self.name, "db": self.db, "maker": self.maker, "year": self.year}


BY_ID = {s[0]: System(*s) for s in SYSTEMS}
BY_DB = {s.db.lower(): s for s in BY_ID.values()}
# Extensions that only one system uses (".sfc" is always SNES).
BY_EXT: dict[str, System] = {}
for _s in BY_ID.values():
    for _e in _s.exts:
        if _e not in SHARED_EXT:
            BY_EXT.setdefault(_e, _s)


def _squash(s: str) -> str:
    return "".join(ch for ch in s.lower() if ch.isalnum())


def from_folder(name: str) -> System | None:
    """A ROM folder name ("SNES", "Super Nintendo", "Sony - PlayStation") to a system."""
    if name.lower() in BY_DB:
        return BY_DB[name.lower()]
    sid = FOLDER_ALIASES.get(_squash(name))
    return BY_ID.get(sid) if sid else None


def from_playlist(name: str) -> System | None:
    """A playlist name (its file name without .lpl) to a system, if it's one Relic knows."""
    s = BY_DB.get(name.lower())
    if s:
        return s
    return from_folder(name)
