"""Save backups, play stats, and starting with Windows.

Backups are plain .zip files (open them with anything): RetroArch's saves and Resume states, plus
Relic's own favorites, collections, play history and settings. One is made after each play session
(at most every 10 minutes) and the newest few are kept.
"""

from __future__ import annotations

import os
import sys
import threading
import time
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path

from reliclog import log

KEEP = 10
MIN_GAP = 600  # seconds between automatic backups
RELIC_FILES = ("config.json", "games.json", "sessions.json")


class Backups:
    def __init__(self, ra, config, data_dir: Path):
        self.ra, self.config, self.data_dir = ra, config, data_dir
        self._lock = threading.Lock()
        self.last_error = ""

    def folder(self) -> Path | None:
        d = self.config["backup_dir"]
        return Path(d) if d else None

    def latest(self) -> dict | None:
        d = self.folder()
        if not d or not d.is_dir():
            return None
        files = sorted(d.glob("Relic-backup-*.zip"))
        if not files:
            return None
        f = files[-1]
        return {"file": f.name, "time": f.stat().st_mtime, "count": len(files)}

    def run_async(self, reason: str = "auto") -> None:
        threading.Thread(target=self.run, args=(reason,), daemon=True).start()

    def run(self, reason: str = "manual") -> dict:
        dest = self.folder()
        if not dest:
            raise RuntimeError("Choose a backup folder first.")
        with self._lock:
            if reason == "auto":
                last = self.latest()
                if last and time.time() - last["time"] < MIN_GAP:
                    return last
            dest.mkdir(parents=True, exist_ok=True)
            name = f"Relic-backup-{datetime.now():%Y-%m-%d-%H%M%S}.zip"
            tmp = dest / (name + ".part")
            files = 0
            try:
                with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
                    for label, d in (("saves", self.ra._dir("savefile_directory", "saves")),
                                     ("states", self.ra.states_dir)):
                        if not d or not d.is_dir():
                            continue
                        for root, _dirs, fs in os.walk(d):
                            for f in fs:
                                p = Path(root) / f
                                try:
                                    if p.stat().st_size > 256 << 20:
                                        continue
                                    z.write(p, f"{label}/{p.relative_to(d).as_posix()}")
                                    files += 1
                                except (OSError, ValueError):
                                    continue
                    for f in RELIC_FILES:
                        p = self.data_dir / f
                        if p.is_file():
                            z.write(p, f"relic/{f}")
                            files += 1
                tmp.replace(dest / name)
                self.last_error = ""
            except OSError as e:
                tmp.unlink(missing_ok=True)
                self.last_error = f"Backup failed: {e.strerror or e}"
                log.exception("backup failed")
                raise RuntimeError(self.last_error)
            old = sorted(dest.glob("Relic-backup-*.zip"))[:-KEEP]
            for f in old:
                f.unlink(missing_ok=True)
            log.info("backup: %s (%d files)", name, files)
            return {"file": name, "time": time.time(), "files": files}


# ------------------------------------------------------------------ stats
def stats(sessions: list, library) -> dict:
    """Your play history, summed up: totals, streaks, this week, most played, by system."""
    by_game: dict[str, dict] = {}
    by_system: dict[str, float] = {}
    days: dict[date, float] = {}
    longest = None
    for gid, start, end in sessions:
        secs = max(0, end - start)
        g = library.get(gid)
        t = by_game.setdefault(gid, {"id": gid, "seconds": 0, "plays": 0, "last": 0})
        t["seconds"] += secs
        t["plays"] += 1
        t["last"] = max(t["last"], end)
        if g:
            by_system[g["system"]] = by_system.get(g["system"], 0) + secs
        d = datetime.fromtimestamp(start).date()
        days[d] = days.get(d, 0) + secs
        if not longest or secs > longest["seconds"]:
            longest = {"id": gid, "seconds": secs, "when": start}

    # Streaks: days in a row with at least one session.
    today = date.today()
    cur = 0
    d = today if today in days else today - timedelta(days=1)
    while d in days:
        cur += 1
        d -= timedelta(days=1)
    best = run = 0
    prev = None
    for d in sorted(days):
        run = run + 1 if prev and d - prev == timedelta(days=1) else 1
        best = max(best, run)
        prev = d

    week = []
    for i in range(6, -1, -1):
        d = today - timedelta(days=i)
        week.append({"day": d.strftime("%a"), "seconds": days.get(d, 0)})

    top = sorted(by_game.values(), key=lambda t: -t["seconds"])[:8]
    systems = sorted(({"id": k, "seconds": v} for k, v in by_system.items()), key=lambda x: -x["seconds"])
    return {
        "total": sum(t["seconds"] for t in by_game.values()),
        "sessions": len(sessions),
        "games": len(by_game),
        "streak": cur,
        "best_streak": best,
        "longest": longest,
        "week": week,
        "top": [t for t in top if library.get(t["id"])],
        "systems": systems,
        "first": min((s[1] for s in sessions), default=0),
    }


# ------------------------------------------------------------------ start with Windows
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    main = Path(__file__).resolve().parent / "main.py"
    pyw = Path(sys.executable).with_name("pythonw.exe")
    return f'"{pyw if pyw.exists() else sys.executable}" "{main}"'


def set_autostart(on: bool) -> bool:
    """Open Relic when you sign in to Windows (your account only)."""
    if sys.platform != "win32":
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            if on:
                winreg.SetValueEx(k, "Relic", 0, winreg.REG_SZ, _command())
            else:
                try:
                    winreg.DeleteValue(k, "Relic")
                except FileNotFoundError:
                    pass
        return True
    except OSError:
        log.exception("couldn't change start with Windows")
        return False
