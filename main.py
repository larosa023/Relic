"""Relic - a couch-mode launcher for your RetroArch games."""

from __future__ import annotations

import argparse
import os
import secrets
import sys
import threading
import webbrowser
from pathlib import Path

from art import Art
from config import Config, data_dir
from gamedata import GameMeta, Player, Sessions
from library import Library
from reliclog import log, setup as setup_log
from retroarch import RetroArch
from server import Context, make_server
from version import VERSION
from winsnap import IS_WIN, WinSnap

# Leaner WebView2: no background networking, sync, crash reporting or component updates.
WEBVIEW2_ARGS = ("--disable-features=ElasticOverscroll,msSmartScreenProtection "
                 "--disable-background-networking --disable-component-update --disable-sync "
                 "--disable-domain-reliability --disable-breakpad --no-first-run "
                 "--autoplay-policy=no-user-gesture-required")


def resource_dir() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))


class WindowApi:
    """Exposed to the page as window.pywebview.api."""

    def __init__(self):
        self._window = None
        self._snap = WinSnap("Relic")
        self._fs = False

    def _attach(self, window):
        self._window = window
        self._snap.window = window

    def minimize(self):
        self._window.minimize()

    def toggle_maximize(self):
        if IS_WIN:
            return self._snap.toggle_maximize()
        self._window.toggle_fullscreen()
        return "max"

    def fullscreen(self, on):
        on = bool(on)
        if on == self._fs:
            return on
        self._fs = on
        if IS_WIN and self._snap.fullscreen(on):
            return on
        self._window.toggle_fullscreen()
        return on

    def is_fullscreen(self):
        return self._fs

    def foreground(self):
        """Controller presses only count while Relic is the window in front."""
        return self._snap.foreground()

    def pick_folder(self):
        import webview
        r = self._window.create_file_dialog(webview.FOLDER_DIALOG)
        return (r[0] if r else "") or ""

    def pick_file(self, kind="any"):
        import webview
        types = {"image": ("Images (*.png;*.jpg;*.jpeg;*.webp)",),
                 "exe": ("RetroArch (retroarch.exe)", "Programs (*.exe)")}.get(kind, ("All files (*.*)",))
        r = self._window.create_file_dialog(webview.OPEN_DIALOG, file_types=types)
        return (r[0] if r else "") or ""

    def drag(self):
        return self._snap.drag()

    def resize(self, edge):
        return self._snap.resize(edge) if isinstance(edge, str) else self._snap.state

    def state(self):
        return self._snap.state

    def close(self):
        self._window.destroy()


def main() -> None:
    ap = argparse.ArgumentParser(description="Relic retro game launcher")
    ap.add_argument("--browser", action="store_true", help="open in your web browser instead of a window")
    ap.add_argument("--port", type=int, default=0, help="fixed port (default: random)")
    ap.add_argument("--windowed", action="store_true", help="start in a window instead of full screen")
    args = ap.parse_args()

    ddir = data_dir()
    setup_log(ddir)
    os.environ.setdefault("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", WEBVIEW2_ARGS)
    log.info("Relic %s starting (%s, frozen=%s)", VERSION, sys.platform, getattr(sys, "frozen", False))

    cfg = Config(ddir / "config.json")
    ra = RetroArch(cfg["retroarch_path"] or None)
    library = Library(ra, cfg)
    threading.Thread(target=library.games, daemon=True).start()  # warm up while the window opens
    meta, sessions = GameMeta(ddir), Sessions(ddir)
    res = resource_dir()
    window_api = None if args.browser else WindowApi()
    tucked = {"on": False}

    def on_start(game):
        if window_api and window_api._window and cfg["when_playing"] == "minimize":
            window_api._window.minimize()
            tucked["on"] = True

    def on_stop(game, seconds):
        log.info("played %s for %ds", game["title"], seconds)
        if tucked["on"] and cfg["restore_after_play"] and window_api and window_api._window:
            try:
                window_api._window.restore()
                window_api._window.show()
                if IS_WIN and window_api._snap.hwnd():
                    import ctypes
                    ctypes.windll.user32.SetForegroundWindow(window_api._snap.hwnd())
            except Exception:
                log.exception("couldn't bring the window back")
        tucked["on"] = False

    player = Player(sessions, on_start=on_start, on_stop=on_stop)
    ctx = Context(token=secrets.token_urlsafe(24), ra=ra, library=library, art=Art(ddir, ra, cfg),
                  config=cfg, meta=meta, sessions=sessions, player=player,
                  ui_dir=res / "ui", theme_dirs=[res / "themes", ddir / "themes"], data_dir=ddir,
                  window_api=window_api)
    srv = make_server(ctx, args.port)
    url = f"http://127.0.0.1:{srv.server_address[1]}/"

    if args.browser:
        print(f"Relic running at {url}  (Ctrl+C to quit)")
        webbrowser.open(url)
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            pass
        return

    threading.Thread(target=srv.serve_forever, daemon=True).start()
    import webview

    window = webview.create_window(
        "Relic", url, width=1280, height=760, min_size=(900, 560),
        frameless=bool(cfg["frameless"]), easy_drag=False,
        background_color="#0a0a0f", js_api=window_api,
    )
    window_api._attach(window)
    if cfg["start_fullscreen"] and not args.windowed:
        window.events.shown += lambda: threading.Timer(0.3, lambda: window_api.fullscreen(True)).start()
    webview.start(private_mode=False, storage_path=str(ddir / "webview"))
    srv.shutdown()


if __name__ == "__main__":
    main()
