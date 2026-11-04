"""What Relic remembers about your games: favorites, ratings, core picks, and play sessions."""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

FIELDS = {"favorite", "hidden", "rating", "status", "notes", "core"}


class _Store:
    def __init__(self, path: Path, default):
        self.path = path
        self._lock = threading.Lock()
        try:
            self.data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.data = default

    def _save(self):
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data), encoding="utf-8")
        os.replace(tmp, self.path)


class GameMeta(_Store):
    """{"<game id>": {"favorite": true, "rating": 4, "core": "bsnes", ...}}"""

    def __init__(self, data_dir: Path):
        super().__init__(data_dir / "games.json", {})

    def get(self, gid: str) -> dict:
        return self.data.get(gid, {})

    def update(self, gid: str, changes: dict) -> dict:
        with self._lock:
            m = dict(self.data.get(gid, {}))
            for k, v in changes.items():
                if k not in FIELDS:
                    continue
                if v in (None, "", False, 0):
                    m.pop(k, None)
                else:
                    m[k] = v
            if m:
                self.data[gid] = m
            else:
                self.data.pop(gid, None)
            self._save()
            return m


class Sessions(_Store):
    """Every time you play: [[game id, start, end], ...]."""

    def __init__(self, data_dir: Path):
        super().__init__(data_dir / "sessions.json", [])

    def record(self, gid: str, start: float, end: float) -> None:
        if end - start < 5:
            return  # opened and closed straight away
        with self._lock:
            self.data.append([gid, round(start), round(end)])
            self._save()

    def totals(self) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for gid, start, end in self.data:
            t = out.setdefault(gid, {"seconds": 0, "last": 0, "plays": 0})
            t["seconds"] += end - start
            t["last"] = max(t["last"], end)
            t["plays"] += 1
        return out


class Player:
    """Runs one game at a time and tells Relic when it starts and stops."""

    def __init__(self, sessions: Sessions, on_start=None, on_stop=None):
        self.sessions = sessions
        self.on_start = on_start or (lambda g: None)
        self.on_stop = on_stop or (lambda g, s: None)
        self.current: dict | None = None
        self._proc = None

    def snapshot(self) -> dict | None:
        if not self.current:
            return None
        return {"id": self.current["id"], "title": self.current["title"], "since": self.current["since"]}

    def run(self, game: dict, start) -> None:
        if self._proc and self._proc.poll() is None:
            raise RuntimeError(f"{self.current['title']} is still running. Close RetroArch first.")
        proc = start()
        self._proc = proc
        self.current = {"id": game["id"], "title": game["title"], "since": time.time()}
        self.on_start(game)

        def wait():
            proc.wait()
            cur, self.current = self.current, None
            end = time.time()
            if cur:
                self.sessions.record(cur["id"], cur["since"], end)
                self.on_stop(game, end - cur["since"])
        threading.Thread(target=wait, daemon=True).start()
