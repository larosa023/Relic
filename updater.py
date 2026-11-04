r"""Relic self-updater, backed by GitHub releases.

Install styles:
  dir     - the installed folder build (%LOCALAPPDATA%\Programs\Relic). Downloads
            Relic-win64.zip, unpacks it next to the app, and swaps it in after
            Relic exits (a running program can't replace its own files).
  single  - an old single-file Relic.exe. "Updating" installs the folder build
            (much faster to start) with Start menu and Desktop shortcuts.
  git     - running from a git clone. Runs `git pull --ff-only`.
  source  - running from an unzipped copy. Downloads the release source zip and
            unpacks it over the app folder.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

import install
from reliclog import log
from version import REPO, VERSION

API_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
EXE_ASSET = "Relic.exe"
ZIP_ASSET = "Relic-win64.zip"
_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def parse_version(s: str) -> tuple[int, ...]:
    nums = [int(n) for n in re.findall(r"\d+", s or "")[:3]]
    return tuple(nums + [0] * (3 - len(nums)))


def http_get(url: str, timeout: float = 15, accept: str = "*/*") -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": f"Relic/{VERSION}", "Accept": accept})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _download(url: str, dest: Path, progress) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": f"Relic/{VERSION}", "Accept": "application/octet-stream"})
    with urllib.request.urlopen(req, timeout=30) as r, open(dest, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = r.read(1 << 16)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if total:
                progress(done / total)


class Updater:
    def __init__(self, app_dir: Path):
        self.app_dir = app_dir
        self.frozen = bool(getattr(sys, "frozen", False))
        self.exe = Path(sys.executable).resolve() if self.frozen else None
        if self.frozen:
            self.mode = "dir" if install.is_folder_build() else "single"
        elif (app_dir / ".git").exists() and shutil.which("git"):
            self.mode = "git"
        else:
            self.mode = "source"
        self._lock = threading.Lock()
        self._release: dict | None = None
        self.state = {
            "current": VERSION,
            "mode": self.mode,
            "latest": None,
            "available": False,
            "notes": "",
            "url": f"https://github.com/{REPO}/releases",
            "checked_at": 0,
            "busy": False,
            "phase": "",
            "progress": None,
            "error": None,
            "ready": False,  # update applied, restart needed
            "migrate": False,  # single-file exe: offering the faster installed version
        }
        self._staged: Path | None = None

    # -- housekeeping -------------------------------------------------------
    def cleanup(self) -> None:
        """Remove leftovers from earlier updates (old exes, unused staged folders)."""
        if not self.exe:
            return
        if self.mode == "dir" and not self._staged and not self.state["busy"]:
            app = self.exe.parent
            for leftover in (app.parent / "Relic.update", app.parent / "Relic.install", app / "_internal.old"):
                shutil.rmtree(leftover, ignore_errors=True)
            try:
                (app / "Relic.exe.old").unlink(missing_ok=True)
            except OSError:
                pass
        olds = [self.exe.with_name(self.exe.name + ".old"), *Path(tempfile.gettempdir()).glob("Relic-previous-*.exe")]
        for old in olds:
            try:
                old.unlink(missing_ok=True)
            except OSError:
                pass

    def _set(self, **kw):
        with self._lock:
            self.state.update(kw)

    def snapshot(self) -> dict:
        with self._lock:
            return dict(self.state)

    # -- check --------------------------------------------------------------
    def check(self) -> dict:
        self._set(error=None)
        try:
            rel = json.loads(http_get(API_LATEST, accept="application/vnd.github+json"))
        except urllib.error.HTTPError as e:
            msg = "No releases published yet" if e.code == 404 else f"GitHub returned {e.code}"
            self._set(error=msg, checked_at=time.time())
            return self.snapshot()
        except Exception as e:
            self._set(error=f"Couldn't reach GitHub ({e.__class__.__name__})", checked_at=time.time())
            return self.snapshot()
        self._release = rel
        latest = (rel.get("tag_name") or "").lstrip("vV")
        available = parse_version(latest) > parse_version(VERSION)
        migrate = False
        if self.mode == "single" and self._zip_asset():
            # The single-file exe always offers to switch to the faster installed version.
            available = migrate = True
        elif available and self.mode in ("dir", "single") and not self._zip_asset():
            available = False
            self._set(error=f"Release {latest} has no {ZIP_ASSET} yet (it may still be building)")
        self._set(
            latest=latest,
            available=available,
            migrate=migrate,
            notes=(rel.get("body") or "")[:4000],
            url=rel.get("html_url") or self.state["url"],
            checked_at=time.time(),
        )
        return self.snapshot()

    def check_async(self) -> None:
        threading.Thread(target=self.check, daemon=True).start()

    def _asset(self, name: str) -> dict | None:
        for a in (self._release or {}).get("assets", []):
            if a.get("name", "").lower() == name.lower():
                return a
        return None

    def _zip_asset(self) -> dict | None:
        return self._asset(ZIP_ASSET)

    # -- apply --------------------------------------------------------------
    def apply_async(self) -> bool:
        with self._lock:
            if self.state["busy"] or not self.state["available"]:
                return False
            self.state.update(busy=True, error=None, phase="Starting", progress=None)
        threading.Thread(target=self._apply, daemon=True).start()
        return True

    def _apply(self):
        try:
            {"dir": self._apply_dir, "single": self._apply_single,
             "git": self._apply_git, "source": self._apply_source}[self.mode]()
            self._set(ready=True, available=False, phase="Restart Relic to finish", progress=None)
        except Exception as e:
            self._set(error=str(e) or e.__class__.__name__, phase="", progress=None)
        finally:
            self._set(busy=False)

    def _download_zip(self, dest: Path) -> None:
        asset = self._zip_asset()
        if not asset:
            raise RuntimeError(f"Release has no {ZIP_ASSET}")
        self._set(phase="Downloading")
        _download(asset["browser_download_url"], dest, lambda p: self._set(progress=p))
        digest = (asset.get("digest") or "").lower()
        if digest.startswith("sha256:"):
            self._set(phase="Verifying", progress=None)
            h = hashlib.sha256()
            with open(dest, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
            if h.hexdigest() != digest.split(":", 1)[1]:
                dest.unlink(missing_ok=True)
                raise RuntimeError("Download failed verification; nothing was changed")

    @staticmethod
    def _extract(zpath: Path, target: Path) -> None:
        """Unpack the release zip (Relic.exe + _internal/) into target, safely."""
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        target.mkdir(parents=True)
        root = target.resolve()
        with zipfile.ZipFile(zpath) as zf:
            names = zf.namelist()
            # Accept both "Relic.exe" at the root and "Relic/Relic.exe".
            prefix = "" if "Relic.exe" in names else next(
                (n[: -len("Relic.exe")] for n in names if n.endswith("/Relic.exe")), None)
            if prefix is None:
                raise RuntimeError("Release zip doesn't contain Relic.exe")
            for info in zf.infolist():
                if not info.filename.startswith(prefix) or info.is_dir():
                    continue
                rel = info.filename[len(prefix):]
                dest = (target / rel).resolve()
                if root not in dest.parents:
                    continue  # never write outside the target folder
                dest.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, open(dest, "wb") as dst:
                    shutil.copyfileobj(src, dst)
        if not (target / "Relic.exe").is_file() or not (target / "_internal").is_dir():
            raise RuntimeError("Release zip is incomplete")

    def _apply_dir(self):
        """Folder build: stage the new version next to the app; swapped in after exit."""
        app = Path(sys.executable).resolve().parent
        staged = app.parent / "Relic.update"
        with tempfile.TemporaryDirectory() as td:
            z = Path(td) / ZIP_ASSET
            self._download_zip(z)
            self._set(phase="Unpacking", progress=None)
            self._extract(z, staged)
        (staged / "version.txt").write_text(self.state["latest"] or "", encoding="utf-8")
        self._staged = staged

    def _apply_single(self):
        """Single-file exe: install the folder build and create shortcuts."""
        target = install.install_dir()
        staged = target.parent / "Relic.install"
        with tempfile.TemporaryDirectory() as td:
            z = Path(td) / ZIP_ASSET
            self._download_zip(z)
            self._set(phase="Installing", progress=None)
            self._extract(z, staged)
        (staged / "version.txt").write_text(self.state["latest"] or VERSION, encoding="utf-8")
        if target.exists():
            try:
                shutil.rmtree(target)
            except OSError as e:
                shutil.rmtree(staged, ignore_errors=True)
                raise RuntimeError("Close any other open Relic windows and try again") from e
        os.replace(staged, target)
        self._set(phase="Creating shortcuts")
        install.create_shortcuts(target / "Relic.exe")
        log.info("installed folder build to %s", target)

    def _apply_git(self):
        self._set(phase="Pulling from GitHub")
        r = subprocess.run(
            ["git", "-C", str(self.app_dir), "pull", "--ff-only"],
            capture_output=True, text=True, creationflags=_NO_WINDOW, timeout=180,
        )
        if r.returncode:
            raise RuntimeError((r.stderr or r.stdout).strip().splitlines()[-1] if (r.stderr or r.stdout) else "git pull failed")
        self._pip_install()

    def _apply_source(self):
        url = (self._release or {}).get("zipball_url")
        if not url:
            raise RuntimeError("Release has no source archive")
        self._set(phase="Downloading")
        with tempfile.TemporaryDirectory() as td:
            z = Path(td) / "src.zip"
            _download(url, z, lambda p: self._set(progress=p))
            self._set(phase="Installing", progress=None)
            with zipfile.ZipFile(z) as zf:
                for info in zf.infolist():
                    parts = Path(info.filename).parts[1:]  # strip "owner-repo-sha/"
                    if not parts or info.is_dir() or parts[0] in (".venv", ".git"):
                        continue
                    target = (self.app_dir / Path(*parts)).resolve()
                    if self.app_dir.resolve() not in target.parents:
                        continue  # never write outside the app folder
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(info) as src, open(target, "wb") as dst:
                        shutil.copyfileobj(src, dst)
        self._pip_install()

    def _pip_install(self):
        req = self.app_dir / "requirements.txt"
        if req.exists():
            self._set(phase="Updating dependencies")
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "-q", "-r", str(req)],
                capture_output=True, creationflags=_NO_WINDOW, timeout=600,
            )

    # -- restart ------------------------------------------------------------
    def restart_command(self) -> list[str]:
        if self.mode == "single":
            return [str(install.installed_exe()), "--migrated-from", str(self.exe)]
        if self.frozen:
            return [str(self.exe)]
        return [sys.executable, str(self.app_dir / "main.py"), *sys.argv[1:]]

    def spawn_new(self) -> None:
        """Start the new Relic. Call as the last thing before this process exits."""
        env = clean_env()
        if self.mode == "dir" and self._staged and self._staged.exists():
            install.schedule_swap(self._staged, Path(sys.executable).resolve().parent, os.getpid(), env)
            return
        kw = {"cwd": str(self.app_dir), "env": env}
        if sys.platform != "win32":
            kw["start_new_session"] = True
            subprocess.Popen(self.restart_command(), **kw)
            return
        if self.frozen:
            # Start it a moment later, from a hidden cmd, so this copy has fully exited and
            # cleaned up its temp folder before the new one starts.
            cmd = 'cmd.exe /d /c ping -n 3 127.0.0.1 >nul & start "" ' + subprocess.list2cmdline(self.restart_command())
            subprocess.Popen(cmd, creationflags=_NO_WINDOW | 0x00000200, **kw)
        else:
            subprocess.Popen(self.restart_command(), creationflags=0x00000008 | 0x00000200, **kw)


def clean_env() -> dict:
    """This process's environment minus anything pointing into PyInstaller's temp folder.

    pywebview adds that folder to PATH; if the new Relic inherited it, it would load
    DLLs from the old copy's temp folder and stop it being cleaned up.
    """
    env = dict(os.environ)
    mei = os.path.normcase(str(getattr(sys, "_MEIPASS", "") or ""))
    if mei:
        for k in [k for k in env if k.lower() == "path"]:
            env[k] = os.pathsep.join(p for p in env[k].split(os.pathsep)
                                     if p and not os.path.normcase(p).startswith(mei))
        for k in list(env):
            if k.lower() != "path" and mei in os.path.normcase(env[k]):
                env.pop(k)
    for k in list(env):
        if k.startswith(("_PYI_", "PYTHONNET_")) or k in ("_MEIPASS2", "PYTHONHOME", "PYTHONPATH"):
            env.pop(k)
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    return env
