"""The consoles Relic knows about.

Each system's `db` is the libretro database name. RetroArch uses it for playlist
file names ("Nintendo - Super Nintendo Entertainment System.lpl") and for its
thumbnail folders, so it's how Relic matches playlists and finds box art.

`cores` are RetroArch core names (the file is <core>_libretro.dll), best first.
Relic launches with the first one you have installed, unless you pick another.
"""

from __future__ import annotations

import re

SYSTEMS = [
    # id, short name, db name, maker, year, extensions, cores (RetroArch core names, best first)
    # ---- Nintendo
    ("nes", "NES", "Nintendo - Nintendo Entertainment System", "Nintendo", 1983,
     ["nes", "unf", "unif"], ["mesen", "nestopia", "fceumm", "quicknes"]),
    ("fds", "Famicom Disk System", "Nintendo - Family Computer Disk System", "Nintendo", 1986,
     ["fds"], ["mesen", "fceumm", "nestopia"]),
    ("snes", "SNES", "Nintendo - Super Nintendo Entertainment System", "Nintendo", 1990,
     ["sfc", "smc", "swc", "fig", "bs"], ["snes9x", "bsnes", "bsnes_hd_beta", "mesen-s"]),
    ("n64", "Nintendo 64", "Nintendo - Nintendo 64", "Nintendo", 1996,
     ["n64", "z64", "v64"], ["mupen64plus_next", "parallel_n64"]),
    ("n64dd", "64DD", "Nintendo - Nintendo 64DD", "Nintendo", 1999,
     ["ndd"], ["mupen64plus_next"]),
    ("gamecube", "GameCube", "Nintendo - GameCube", "Nintendo", 2001,
     ["gcm", "gcz"], ["dolphin"]),
    ("wii", "Wii", "Nintendo - Wii", "Nintendo", 2006,
     ["wbfs", "wad"], ["dolphin"]),
    ("gw", "Game & Watch", "Handheld Electronic Game", "Nintendo", 1980,
     ["mgw"], ["gw"]),
    ("gb", "Game Boy", "Nintendo - Game Boy", "Nintendo", 1989,
     ["gb"], ["gambatte", "sameboy", "gearboy", "mgba"]),
    ("gbc", "Game Boy Color", "Nintendo - Game Boy Color", "Nintendo", 1998,
     ["gbc"], ["gambatte", "sameboy", "gearboy", "mgba"]),
    ("gba", "Game Boy Advance", "Nintendo - Game Boy Advance", "Nintendo", 2001,
     ["gba"], ["mgba", "vba_next", "vbam", "gpsp"]),
    ("nds", "Nintendo DS", "Nintendo - Nintendo DS", "Nintendo", 2004,
     ["nds", "dsi"], ["melondsds", "melonds", "desmume"]),
    ("3ds", "Nintendo 3DS", "Nintendo - Nintendo 3DS", "Nintendo", 2011,
     ["3ds", "3dsx", "cia", "cci", "cxi"], ["azahar", "citra"]),
    ("vb", "Virtual Boy", "Nintendo - Virtual Boy", "Nintendo", 1995,
     ["vb", "vboy"], ["mednafen_vb"]),
    ("pokemini", "Pokémon Mini", "Nintendo - Pokemon Mini", "Nintendo", 2001,
     ["min"], ["pokemini"]),
    # ---- Sega
    ("sg1000", "SG-1000", "Sega - SG-1000", "Sega", 1983,
     ["sg"], ["genesis_plus_gx", "gearsystem", "bluemsx"]),
    ("sms", "Master System", "Sega - Master System - Mark III", "Sega", 1986,
     ["sms"], ["genesis_plus_gx", "picodrive", "gearsystem"]),
    ("genesis", "Genesis", "Sega - Mega Drive - Genesis", "Sega", 1989,
     ["md", "gen", "smd", "bin"], ["genesis_plus_gx", "picodrive", "blastem"]),
    ("segacd", "Sega CD", "Sega - Mega-CD - Sega CD", "Sega", 1992,
     [], ["genesis_plus_gx", "picodrive"]),
    ("32x", "32X", "Sega - 32X", "Sega", 1994,
     ["32x"], ["picodrive"]),
    ("gamegear", "Game Gear", "Sega - Game Gear", "Sega", 1991,
     ["gg"], ["genesis_plus_gx", "gearsystem"]),
    ("saturn", "Saturn", "Sega - Saturn", "Sega", 1995,
     [], ["mednafen_saturn", "yabasanshiro", "kronos", "yabause"]),
    ("dreamcast", "Dreamcast", "Sega - Dreamcast", "Sega", 1999,
     ["gdi", "cdi"], ["flycast"]),
    ("naomi", "NAOMI", "Sega - Naomi", "Sega", 1998,
     ["lst"], ["flycast"]),
    # ---- Sony
    ("psx", "PlayStation", "Sony - PlayStation", "Sony", 1995,
     ["pbp"], ["swanstation", "pcsx_rearmed", "mednafen_psx_hw", "mednafen_psx"]),
    ("ps2", "PlayStation 2", "Sony - PlayStation 2", "Sony", 2000,
     [], ["pcsx2", "play"]),
    ("psp", "PSP", "Sony - PlayStation Portable", "Sony", 2005,
     [], ["ppsspp"]),
    # ---- NEC
    ("pce", "TurboGrafx-16", "NEC - PC Engine - TurboGrafx 16", "NEC", 1989,
     ["pce"], ["mednafen_pce_fast", "mednafen_pce", "geargrafx"]),
    ("pcecd", "TurboGrafx-CD", "NEC - PC Engine CD - TurboGrafx-CD", "NEC", 1989,
     [], ["mednafen_pce_fast", "mednafen_pce", "geargrafx"]),
    ("sgx", "SuperGrafx", "NEC - PC Engine SuperGrafx", "NEC", 1989,
     ["sgx"], ["mednafen_supergrafx", "mednafen_pce"]),
    ("pcfx", "PC-FX", "NEC - PC-FX", "NEC", 1994,
     [], ["mednafen_pcfx"]),
    ("pc98", "PC-98", "NEC - PC-98", "NEC", 1982,
     ["d98", "fdi", "hdi", "nhd"], ["np2kai"]),
    # ---- Atari
    ("atari2600", "Atari 2600", "Atari - 2600", "Atari", 1977,
     ["a26"], ["stella", "stella2014"]),
    ("atari5200", "Atari 5200", "Atari - 5200", "Atari", 1982,
     ["a52"], ["a5200", "atari800"]),
    ("atari7800", "Atari 7800", "Atari - 7800", "Atari", 1986,
     ["a78"], ["prosystem"]),
    ("atari800", "Atari 8-bit", "Atari - 8-bit", "Atari", 1979,
     ["atr", "xex", "xfd", "atx", "car"], ["atari800"]),
    ("lynx", "Lynx", "Atari - Lynx", "Atari", 1989,
     ["lnx"], ["handy", "mednafen_lynx"]),
    ("jaguar", "Jaguar", "Atari - Jaguar", "Atari", 1993,
     ["j64", "jag"], ["virtualjaguar"]),
    ("atarist", "Atari ST", "Atari - ST", "Atari", 1985,
     ["st", "stx", "msa"], ["hatari"]),
    # ---- SNK
    ("ngp", "Neo Geo Pocket", "SNK - Neo Geo Pocket Color", "SNK", 1999,
     ["ngp", "ngc", "npc"], ["mednafen_ngp", "race"]),
    ("neocd", "Neo Geo CD", "SNK - Neo Geo CD", "SNK", 1994,
     [], ["neocd"]),
    # ---- other consoles
    ("3do", "3DO", "The 3DO Company - 3DO", "3DO", 1993,
     [], ["opera"]),
    ("cdi", "CD-i", "Philips - CD-i", "Philips", 1991,
     [], ["same_cdi"]),
    ("coleco", "ColecoVision", "Coleco - ColecoVision", "Coleco", 1982,
     ["col"], ["gearcoleco", "bluemsx"]),
    ("intv", "Intellivision", "Mattel - Intellivision", "Mattel", 1979,
     ["int"], ["freeintv"]),
    ("vectrex", "Vectrex", "GCE - Vectrex", "GCE", 1982,
     ["vec"], ["vecx"]),
    ("odyssey2", "Odyssey²", "Magnavox - Odyssey2", "Magnavox", 1978,
     ["o2"], ["o2em"]),
    ("channelf", "Channel F", "Fairchild - Channel F", "Fairchild", 1976,
     ["chf"], ["freechaf"]),
    ("wonderswan", "WonderSwan", "Bandai - WonderSwan Color", "Bandai", 2000,
     ["ws", "wsc", "pc2"], ["mednafen_wswan"]),
    ("supervision", "Supervision", "Watara - Supervision", "Watara", 1992,
     ["sv"], ["potator"]),
    # ---- computers
    ("msx", "MSX", "Microsoft - MSX", "Microsoft", 1983,
     ["mx1", "mx2", "cas"], ["bluemsx", "fmsx"]),
    ("c64", "Commodore 64", "Commodore - 64", "Commodore", 1982,
     ["d64", "t64", "prg", "crt", "d71", "d81", "g64", "x64"], ["vice_x64sc", "vice_x64"]),
    ("amiga", "Amiga", "Commodore - Amiga", "Commodore", 1985,
     ["adf", "ipf", "lha", "adz", "dms", "uae"], ["puae", "puae2021"]),
    ("zx", "ZX Spectrum", "Sinclair - ZX Spectrum", "Sinclair", 1982,
     ["tzx", "z80", "szx", "scl", "trd"], ["fuse"]),
    ("cpc", "Amstrad CPC", "Amstrad - CPC", "Amstrad", 1984,
     ["cdt"], ["cap32", "crocods"]),
    ("x68000", "X68000", "Sharp - X68000", "Sharp", 1987,
     ["dim", "2hd", "xdf"], ["px68k"]),
    ("dos", "DOS", "DOS", "PC", 1981,
     ["dosz"], ["dosbox_pure", "dosbox_core"]),
    ("scummvm", "ScummVM", "ScummVM", "ScummVM", 2001,
     ["scummvm"], ["scummvm"]),
    ("pico8", "PICO-8", "PICO-8", "Lexaloffle", 2015,
     ["p8"], ["retro8", "fake08"]),
    ("tic80", "TIC-80", "TIC-80", "Nesbox", 2017,
     ["tic"], ["tic80"]),
    # ---- arcade
    ("arcade", "Arcade", "FBNeo - Arcade Games", "Arcade", 1980,
     [], ["fbneo", "mame2003_plus", "mame", "mame2010"]),
]

# File types that several systems share: Relic decides by the folder name instead.
SHARED_EXT = {"cue", "chd", "iso", "m3u", "zip", "7z", "bin", "img", "ccd", "mds", "cso", "rvz",
              "rom", "dsk", "tap", "sna", "hdf", "ciso", "pbp", "exe", "bat", "elf"}

# Words people use for their ROM folders, mapped to a system id (lowercase, letters and digits only).
FOLDER_ALIASES = {
    "nes": "nes", "famicom": "nes", "fc": "nes", "nintendo": "nes", "nintendoentertainmentsystem": "nes",
    "fds": "fds", "famicomdisksystem": "fds", "disksystem": "fds",
    "snes": "snes", "sfc": "snes", "superfamicom": "snes", "supernintendo": "snes", "supernes": "snes", "satellaview": "snes",
    "n64": "n64", "nintendo64": "n64",
    "n64dd": "n64dd", "64dd": "n64dd",
    "gc": "gamecube", "gcn": "gamecube", "gamecube": "gamecube", "ngc": "gamecube", "nintendogamecube": "gamecube",
    "wii": "wii", "nintendowii": "wii", "wiiware": "wii",
    "gw": "gw", "gameandwatch": "gw", "gamewatch": "gw",
    "gb": "gb", "gameboy": "gb", "dmg": "gb",
    "gbc": "gbc", "gameboycolor": "gbc",
    "gba": "gba", "gameboyadvance": "gba",
    "nds": "nds", "ds": "nds", "nintendods": "nds", "dsi": "nds",
    "3ds": "3ds", "n3ds": "3ds", "nintendo3ds": "3ds",
    "vb": "vb", "virtualboy": "vb",
    "pokemini": "pokemini", "pokemonmini": "pokemini",
    "sg1000": "sg1000", "sg": "sg1000",
    "sms": "sms", "mastersystem": "sms", "segamastersystem": "sms", "markiii": "sms",
    "genesis": "genesis", "megadrive": "genesis", "md": "genesis", "segagenesis": "genesis", "segamegadrive": "genesis",
    "segacd": "segacd", "megacd": "segacd", "scd": "segacd",
    "32x": "32x", "sega32x": "32x",
    "gg": "gamegear", "gamegear": "gamegear", "segagamegear": "gamegear",
    "saturn": "saturn", "segasaturn": "saturn", "ss": "saturn",
    "dc": "dreamcast", "dreamcast": "dreamcast", "segadreamcast": "dreamcast",
    "naomi": "naomi", "naomi2": "naomi", "atomiswave": "naomi",
    "psx": "psx", "ps1": "psx", "ps": "psx", "playstation": "psx", "psone": "psx", "playstation1": "psx", "sonyplaystation": "psx",
    "ps2": "ps2", "playstation2": "ps2", "sonyplaystation2": "ps2",
    "psp": "psp", "playstationportable": "psp",
    "pce": "pce", "pcengine": "pce", "tg16": "pce", "turbografx": "pce", "turbografx16": "pce",
    "pcecd": "pcecd", "pcenginecd": "pcecd", "tgcd": "pcecd", "turbografxcd": "pcecd", "tg16cd": "pcecd",
    "sgx": "sgx", "supergrafx": "sgx",
    "pcfx": "pcfx",
    "pc98": "pc98", "pc9801": "pc98",
    "atari2600": "atari2600", "2600": "atari2600", "a2600": "atari2600", "vcs": "atari2600",
    "atari5200": "atari5200", "5200": "atari5200",
    "atari7800": "atari7800", "7800": "atari7800",
    "atari800": "atari800", "atari8bit": "atari800", "atarixl": "atari800", "atari": "atari2600",
    "lynx": "lynx", "atarilynx": "lynx",
    "jaguar": "jaguar", "atarijaguar": "jaguar",
    "atarist": "atarist", "st": "atarist",
    "ngp": "ngp", "ngpc": "ngp", "neogeopocket": "ngp", "neogeopocketcolor": "ngp",
    "neocd": "neocd", "neogeocd": "neocd",
    "3do": "3do", "panasonic3do": "3do",
    "cdi": "cdi", "philipscdi": "cdi",
    "coleco": "coleco", "colecovision": "coleco",
    "intv": "intv", "intellivision": "intv",
    "vectrex": "vectrex",
    "odyssey2": "odyssey2", "o2": "odyssey2", "videopac": "odyssey2",
    "channelf": "channelf", "fairchild": "channelf",
    "ws": "wonderswan", "wsc": "wonderswan", "wonderswan": "wonderswan", "wonderswancolor": "wonderswan",
    "supervision": "supervision",
    "msx": "msx", "msx2": "msx", "msx1": "msx",
    "c64": "c64", "commodore64": "c64", "commodore": "c64",
    "amiga": "amiga", "commodoreamiga": "amiga", "cd32": "amiga", "amigacd32": "amiga",
    "zx": "zx", "zxspectrum": "zx", "spectrum": "zx",
    "cpc": "cpc", "amstrad": "cpc", "amstradcpc": "cpc",
    "x68000": "x68000", "x68k": "x68000",
    "dos": "dos", "msdos": "dos", "pc": "dos",
    "scummvm": "scummvm", "scumm": "scummvm",
    "pico8": "pico8",
    "tic80": "tic80",
    "arcade": "arcade", "fbneo": "arcade", "fba": "arcade", "mame": "arcade", "neogeo": "arcade",
    "cps1": "arcade", "cps2": "arcade", "cps3": "arcade", "mame2003": "arcade", "mame2003plus": "arcade",
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


FILLER = {"roms", "rom", "isos", "iso", "collection", "library", "files", "set", "full",
          "usa", "us", "eu", "europe", "jp", "japan", "ntsc", "pal", "my", "the", "and", "chd", "cue", "zip"}


def from_folder(name: str) -> System | None:
    """A ROM folder name ("SNES", "Super Nintendo", "PS2 Games", "Sony - PlayStation") to a system."""
    if name.lower() in BY_DB:
        return BY_DB[name.lower()]
    sid = FOLDER_ALIASES.get(_squash(name))
    if sid:
        return BY_ID[sid]
    # Drop words like "ROMs" and "(USA)", then try the rest together, in pairs, and one by one.
    words = [w for w in re.split(r"[^a-z0-9]+", name.lower().replace("&", "and")) if w and w not in FILLER]
    tries = ["".join(words)] + [a + b for a, b in zip(words, words[1:])] + words
    for t in tries:
        if t in FOLDER_ALIASES:
            return BY_ID[FOLDER_ALIASES[t]]
    return None


def from_playlist(name: str) -> System | None:
    """A playlist name (its file name without .lpl) to a system, if it's one Relic knows."""
    s = BY_DB.get(name.lower())
    if s:
        return s
    return from_folder(name)
