"""Where Relic lives on Windows, and the bits that tie it into Windows.

Relic installs as a folder (Relic.exe + _internal) in
%LOCALAPPDATA%\\Programs\\Relic, so it starts instantly instead of unpacking
itself on every launch. This module handles shortcuts, the version marker, and swapping in an update after Relic exits.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

from reliclog import log

IS_WIN = sys.platform == "win32"
_NO_WINDOW = 0x08000000


def install_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "Programs" / "Relic"


def installed_exe() -> Path:
    return install_dir() / "Relic.exe"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def is_folder_build() -> bool:
    """True when running from an unpacked folder build (not the single-file exe)."""
    if not is_frozen():
        return False
    exe_dir = Path(sys.executable).resolve().parent
    try:
        return Path(sys._MEIPASS).resolve().parent == exe_dir  # _internal sits next to the exe
    except AttributeError:
        return False


def installed_version() -> str | None:
    try:
        return (install_dir() / "version.txt").read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def write_version_marker(version: str) -> None:
    try:
        p = Path(sys.executable).resolve().parent / "version.txt"
        if not p.exists() or p.read_text(encoding="utf-8").strip() != version:
            p.write_text(version, encoding="utf-8")
    except OSError:
        pass


# ------------------------------------------------------------------- shortcuts

def _special_folder(name: str) -> Path | None:
    """Desktop / Programs (Start menu) folder for this user."""
    if not IS_WIN:
        return None
    import ctypes
    from ctypes import wintypes
    csidl = {"desktop": 0x10, "programs": 0x02}[name]
    buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
    if ctypes.windll.shell32.SHGetFolderPathW(None, csidl, None, 0, buf) == 0:
        return Path(buf.value)
    return None


def create_shortcuts(exe: Path) -> None:
    """Start menu + Desktop shortcuts to the installed Relic."""
    if not IS_WIN:
        return
    targets = [d / "Relic.lnk" for d in (_special_folder("programs"), _special_folder("desktop")) if d]
    script = "; ".join(
        f"$s=$w.CreateShortcut('{str(t).replace(chr(39), chr(39) * 2)}'); "
        f"$s.TargetPath='{str(exe).replace(chr(39), chr(39) * 2)}'; "
        f"$s.WorkingDirectory='{str(exe.parent).replace(chr(39), chr(39) * 2)}'; "
        f"$s.IconLocation='{str(exe).replace(chr(39), chr(39) * 2)},0'; "
        f"$s.Description='Relic'; $s.Save()"
        for t in targets
    )
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-Command", "$w=New-Object -ComObject WScript.Shell; " + script],
            creationflags=_NO_WINDOW, timeout=30, capture_output=True,
        )
        log.info("shortcuts created: %s", ", ".join(str(t) for t in targets))
    except Exception as e:
        log.warning("couldn't create shortcuts: %r", e)


# --------------------------------------------------------------- update swap

def schedule_swap(staged: Path, app: Path, pid: int, env: dict) -> None:
    """After process `pid` exits, replace app/{Relic.exe,_internal} with the staged copy and start it.

    Runs from a hidden cmd script, because a running program can't replace its own files.
    If anything fails, the old copy is put back and started instead.
    """
    q = lambda p: str(p).replace("%", "%%")  # noqa: E731
    script = Path(tempfile.gettempdir()) / f"relic-update-{pid}.cmd"
    script.write_text("\r\n".join([
        "@echo off",
        "chcp 65001 >nul",
        "setlocal",
        f'set "APP={q(app)}"',
        f'set "NEW={q(staged)}"',
        ":wait",
        f'tasklist /FI "PID eq {pid}" /NH 2>nul | find " {pid} " >nul && (ping -n 2 127.0.0.1 >nul & goto wait)',
        'ping -n 2 127.0.0.1 >nul',
        'if exist "%APP%\\_internal.old" rmdir /s /q "%APP%\\_internal.old"',
        'move "%APP%\\_internal" "%APP%\\_internal.old" >nul || goto fail',
        'move "%NEW%\\_internal" "%APP%\\_internal" >nul || (move "%APP%\\_internal.old" "%APP%\\_internal" >nul & goto fail)',
        'move /y "%APP%\\Relic.exe" "%APP%\\Relic.exe.old" >nul',
        'move /y "%NEW%\\Relic.exe" "%APP%\\Relic.exe" >nul || (move /y "%APP%\\Relic.exe.old" "%APP%\\Relic.exe" >nul)',
        'if exist "%NEW%\\version.txt" move /y "%NEW%\\version.txt" "%APP%\\version.txt" >nul',
        'start "" "%APP%\\Relic.exe"',
        'ping -n 4 127.0.0.1 >nul',
        'rmdir /s /q "%APP%\\_internal.old" 2>nul',
        'del /f /q "%APP%\\Relic.exe.old" 2>nul',
        'rmdir /s /q "%NEW%" 2>nul',
        '(goto) 2>nul & del "%~f0"',
        ":fail",
        'start "" "%APP%\\Relic.exe"',
        '(goto) 2>nul & del "%~f0"',
    ]) + "\r\n", encoding="utf-8")
    subprocess.Popen(["cmd.exe", "/d", "/c", str(script)], creationflags=_NO_WINDOW | 0x00000200,
                     cwd=str(Path(tempfile.gettempdir())), env=env)
    log.info("update swap scheduled: %s -> %s", staged, app)
