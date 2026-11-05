import json
import os
import threading
from pathlib import Path

APP_NAME = "Relic"

DEFAULTS = {
    "theme": "relic",
    "retroarch_path": "",       # folder with retroarch.exe; empty = find it
    "rom_folders": [],          # extra folders to scan besides RetroArch's playlists
    "hidden_playlists": [],
    "system_cores": {},         # {"snes": "bsnes"}: your pick per system
    "download_art": True,       # fetch box art from the libretro thumbnails server
    "start_fullscreen": True,   # couch first: open filling the screen
    "launch_fullscreen": True,  # start RetroArch with -f
    "when_playing": "minimize", # minimize | none
    "restore_after_play": True,
    "frameless": True,
    "sounds": True,
    "shelf_sort": "title",      # title | recent | played
    "controller_nav": True,
    "emulators": {},            # {"ps4": "C:\\...\\shadPS4.exe"}: standalone emulators you chose
    "pad_map": {},              # {"a": 1, "b": 0}: your controller layout (standard button numbers)
    "key_map": {},              # {"x": ["g"]}: your keyboard layout
    "resume": True,             # RetroArch saves when you quit and picks up there next time
    "quit_combo": True,         # Select + Start closes the game and you're back in Relic
    "crt": "off",               # off | retro | all: RetroArch's CRT shader
    "game_details": True,       # download year/genre/players from libretro's game database
    "retroachievements": {},    # {"user", "token", "hardcore"}: never the password
    "collections": [],          # [{"id", "name", "games": [game ids]}]
    "bios_dir": "",             # where your BIOS files are; Relic re-imports from it after new installs
    "check_updates": True,      # look for a new Relic on GitHub when it starts
    "seen_version": "",
}
EDITABLE = set(DEFAULTS)


def data_dir() -> Path:
    base = os.environ.get("APPDATA") or (Path.home() / ".config")
    d = Path(base) / APP_NAME
    (d / "themes").mkdir(parents=True, exist_ok=True)
    return d


class Config:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        self.data = dict(DEFAULTS)
        try:
            self.data.update(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass

    def public(self) -> dict:
        return dict(self.data)

    def __getitem__(self, key):
        return self.data.get(key, DEFAULTS.get(key))

    def update(self, changes: dict) -> dict:
        with self._lock:
            for k, v in changes.items():
                if k in EDITABLE:
                    self.data[k] = v
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
            os.replace(tmp, self.path)
            return dict(self.data)
