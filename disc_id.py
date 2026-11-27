"""Reading a disc image's ID (its serial), the way the console itself would.

PlayStation and PS2 discs name their boot file in SYSTEM.CNF ("BOOT2 = cdrom0:\\SLUS_209.46;1"),
PSP discs keep the ID in UMD_DATA.BIN, and GameCube/Wii discs start with a six-letter game ID.
libretro's database lists games by these IDs, so an ID gives the exact name, and with it the
right box art and details, whatever the file is called.

Only a few kilobytes are read from each file. Compressed images (CHD, CSO, GCZ) aren't opened;
for those, an ID written in the file name ("SLUS-20946", "SLUS_209.46") still works.
"""

from __future__ import annotations

import re
import struct
from pathlib import Path

SONY_ID = re.compile(r"\b(S[CL][UEPKA][SMDACT]|PAPX|PBP[XS]|SCAJ|SCCS|SCED|SCKA|SLKA|SLAJ|U[CL][UEJKA][SMDST]|NP[UEJHZ][A-Z])[-_ .]?(\d{3})\.?(\d{2})\b", re.I)
SECTOR = 2048


def norm(serial: str) -> str:
    """"SLUS-20946" / "SLUS_209.46" / "slus20946" -> "SLUS20946" (how both sides are compared)."""
    return re.sub(r"[^A-Z0-9]", "", serial.upper())


def from_name(name: str) -> str:
    m = SONY_ID.search(name)
    return norm(m[1] + m[2] + m[3]) if m else ""


class _Iso:
    """Just enough ISO 9660 to find a file in the root folder. Handles plain 2048-byte images
    and raw 2352-byte CD images (PlayStation .bin)."""

    def __init__(self, f):
        self.f = f
        self.raw = 0
        for raw, off in ((0, 0), (2352, 24), (2352, 16)):
            if self._pvd(raw, off):
                return
        raise ValueError("not an ISO 9660 image")

    def _read(self, lba: int, n: int = SECTOR) -> bytes:
        if not self.raw:
            self.f.seek(lba * SECTOR)
            return self.f.read(n)
        out = b""
        while len(out) < n:
            self.f.seek(lba * 2352 + self.off)
            chunk = self.f.read(SECTOR)
            if not chunk:
                break
            out += chunk
            lba += 1
        return out[:n]

    def _pvd(self, raw, off) -> bool:
        self.raw, self.off = raw, off
        d = self._read(16)
        if len(d) < 190 or d[1:6] != b"CD001":
            return False
        root = d[156:190]
        self.root_lba = struct.unpack_from("<I", root, 2)[0]
        self.root_len = struct.unpack_from("<I", root, 10)[0]
        return True

    def read_file(self, name: str, limit: int = 64 * 1024) -> bytes | None:
        want = name.upper()
        data = self._read(self.root_lba, min(self.root_len, 256 * 1024))
        i = 0
        while i < len(data):
            ln = data[i]
            if ln == 0:  # the rest of this sector is padding
                i = (i // SECTOR + 1) * SECTOR
                continue
            rec = data[i:i + ln]
            if len(rec) < 34:
                break
            nl = rec[32]
            fname = rec[33:33 + nl].decode("ascii", "replace").split(";")[0].upper()
            if fname == want:
                lba = struct.unpack_from("<I", rec, 2)[0]
                size = struct.unpack_from("<I", rec, 10)[0]
                return self._read(lba, min(size, limit))
            i += ln
        return None


def _sony(f) -> str:
    iso = _Iso(f)
    cnf = iso.read_file("SYSTEM.CNF")
    if cnf:
        m = re.search(rb"BOOT2?\s*=\s*cdrom0?:\\?\\?([^;\r\n]+)", cnf, re.I)
        if m:
            s = from_name(m[1].decode("ascii", "replace").replace("\\", "/").rsplit("/", 1)[-1])
            if s:
                return s
    umd = iso.read_file("UMD_DATA.BIN", 64)
    if umd:
        s = umd.split(b"|", 1)[0].decode("ascii", "replace")
        if re.fullmatch(r"[A-Z]{4}-?\d{5}", s.strip()):
            return norm(s)
    return ""


def _nintendo(f) -> str:
    head = f.read(0x260)
    if head[:4] in (b"RVZ\x01", b"WIA\x01"):
        gid = head[0x58:0x5E]  # Dolphin's formats keep a copy of the disc header
    elif head[:4] == b"WBFS":
        gid = head[0x200:0x206]
    elif head[:4] in (b"\x01\xc0\x0b\xb1", b"CISO"):
        return ""
    else:
        gid = head[:6]
    try:
        s = gid.decode("ascii")
    except UnicodeDecodeError:
        return ""
    return s.upper() if re.fullmatch(r"[A-Z0-9]{6}", s, re.I) else ""


def _cue_track(cue: Path) -> Path | None:
    try:
        m = re.search(r'FILE\s+"([^"]+)"', cue.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return None
    return (cue.parent / m[1]) if m else None


def read(path: str, system: str) -> str:
    """The disc's serial (normalised), or "" if it can't be read."""
    p = Path(path)
    s = from_name(p.name) if system in ("psx", "ps2", "psp") else ""
    if s:
        return s
    ext = p.suffix.lower()
    try:
        if system in ("psx", "ps2", "psp"):
            if ext == ".cue":
                p = _cue_track(p) or p
                ext = p.suffix.lower()
            if ext not in (".iso", ".bin", ".img"):
                return ""
            with open(p, "rb") as f:
                return _sony(f)
        if system in ("gamecube", "wii"):
            if ext not in (".iso", ".gcm", ".rvz", ".wia", ".wbfs", ".ciso"):
                return ""
            with open(p, "rb") as f:
                return _nintendo(f)
    except (OSError, ValueError, struct.error):
        return ""
    return ""


DISC_SYSTEMS = {"psx", "ps2", "psp", "gamecube", "wii"}
