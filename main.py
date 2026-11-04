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
import install
from library import Library
from reliclog import log, setup as setup_log
from retroarch import RetroArch
from server import Context, make_server
from updater import Updater
from version import VERSION
from winsnap import IS_WIN, WinSnap

# Leaner WebView2: no background networking, sync, crash reporting or component updates.
WEBVIEW2_ARGS = ("--disable-features=ElasticOverscroll,msSmartScreenProtection "
                 "--disable-background-networking --disable-component-update --disable-sync "
                 "--disable-domain-reliability --disable-breakpad --no-first-run "
                 "--autoplay-policy=no-user-gesture-required")


def resource_dir() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))


def app_dir() -> Path:
    """Where Relic lives on disk (the exe's folder, or the source folder)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def launch_installed_instead() -> bool:
    """The single-file Relic.exe: if the faster installed version is there, open that instead."""
    if not install.is_frozen() or install.is_folder_build():
        return False
    from updater import clean_env, parse_version
    exe, ver = install.installed_exe(), install.installed_version()
    if not exe.is_file() or not ver or parse_version(ver) < parse_version(VERSION):
        return False
    import subprocess
    subprocess.Popen([str(exe), *sys.argv[1:]], cwd=str(exe.parent), env=clean_env(),
                     creationflags=0x00000008 | 0x00000200)
    return True


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
    ap.add_argument("--migrated-from", default="", help=argparse.SUPPRESS)
    args = ap.parse_args()

    ddir = data_dir()
    setup_log(ddir)
    if launch_installed_instead():
        log.info("opened the installed version instead of this single-file copy")
        return
    if install.is_folder_build():
        install.write_version_marker(VERSION)
    os.environ.setdefault("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", WEBVIEW2_ARGS)
    log.info("Relic %s starting (%s, frozen=%s)", VERSION, sys.platform, getattr(sys, "frozen", False))

    cfg = Config(ddir / "config.json")
    updater = Updater(app_dir())
    updater.cleanup()

    def _retry_cleanup():
        # Right after an update the previous copy may still be closing, which keeps its old exe locked.
        import time
        for _ in range(6):
            time.sleep(5)
            updater.cleanup()
    threading.Thread(target=_retry_cleanup, daemon=True).start()
    if cfg["check_updates"]:
        updater.check_async()
    if args.migrated_from:
        _remove_old_single_file(args.migrated_from)
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

    restart_requested = threading.Event()

    def restart():
        # Close this copy first; the new one starts once it has fully exited (end of main).
        restart_requested.set()

        def go():
            import time
            time.sleep(0.4)  # let the HTTP response go out first
            if window_api and window_api._window:
                window_api._window.destroy()
            else:
                srv.shutdown()
        threading.Thread(target=go, daemon=True).start()

    player = Player(sessions, on_start=on_start, on_stop=on_stop)
    ctx = Context(token=secrets.token_urlsafe(24), ra=ra, library=library, art=Art(ddir, ra, cfg),
                  config=cfg, meta=meta, sessions=sessions, player=player,
                  ui_dir=res / "ui", theme_dirs=[res / "themes", ddir / "themes"], data_dir=ddir,
                  window_api=window_api, updater=updater, restart=restart)
    srv = make_server(ctx, args.port)
    url = f"http://127.0.0.1:{srv.server_address[1]}/"

    if args.browser:
        print(f"Relic running at {url}  (Ctrl+C to quit)")
        webbrowser.open(url)
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            pass
        if restart_requested.is_set():
            updater.spawn_new()
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
    if restart_requested.is_set():
        log.info("restarting for the update")
        updater.spawn_new()


def _remove_old_single_file(path: str) -> None:
    """After moving to the installed version, delete the old single-file Relic.exe (once it has closed)."""
    old = Path(path)
    if old.suffix.lower() != ".exe" or old.name.lower() != "relic.exe" or old.resolve() == Path(sys.executable).resolve():
        return

    def go():
        import time
        for _ in range(10):
            time.sleep(2)
            try:
                old.unlink()
                log.info("removed the old single-file copy %s", old)
                return
            except FileNotFoundError:
                return
            except OSError:
                pass
    threading.Thread(target=go, daemon=True).start()


if __name__ == "__main__":
    main()
