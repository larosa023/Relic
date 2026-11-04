@echo off
rem Builds Relic: dist\Relic\ (folder version, starts instantly) and dist\Relic.exe (single file).
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  py -3 -m venv .venv || python -m venv .venv
)
.venv\Scripts\python -m pip install --upgrade pip >nul
.venv\Scripts\python -m pip install -r requirements.txt pyinstaller
set OPTS=--noconfirm --clean --noconsole --optimize 1 --name Relic --icon assets\relic.ico ^
  --add-data "ui;ui" --add-data "themes;themes" --add-data "assets;assets" ^
  --exclude-module tkinter --exclude-module pydoc_data --exclude-module test --exclude-module lib2to3
.venv\Scripts\pyinstaller %OPTS% --onedir --distpath dist main.py
.venv\Scripts\pyinstaller %OPTS% --onefile --distpath dist --workpath build-one main.py
echo.
echo Done: dist\Relic\ and dist\Relic.exe
pause
