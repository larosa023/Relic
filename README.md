# Relic

A sleek couch-mode launcher for your RetroArch games on Windows. Cinder's cousin for old consoles.

Relic reads what RetroArch already knows (its playlists, cores and thumbnails) and launches games through your installed RetroArch. It never changes RetroArch's own files.

## Features

- **Couch first**: opens full screen, driven by a controller. D-pad or stick moves (hold to scroll faster), **A** plays, **X** favorites, **Y** opens game options, **LB/RB** jump between systems, **Select** changes the sort, **Start** opens settings, **B** goes back. Mouse and keyboard work too: there's a **Back** button in the top bar, and the mouse's side back button goes back.
- **Your systems up front**: a row of system tiles (SNES, Genesis, PlayStation…) with game counts, then **Continue playing** and **Favorites**.
- **Fast with big libraries**: the library is kept on disk, so Relic opens instantly and rescans quietly in the background, updating the screen if something changed. Shelves with thousands of games open in a blink, and moving stays instant.
- **Find games quickly**: **LT/RT** (Page Up/Down) jump a shelf by letter. **Select** at home is *Surprise me*, a random pick nudged toward games you haven't played much. A *Recently added* row shows new games.
- **Box art shelves**: each system gets a shelf of covers shaped like that system's boxes, with the focused game's screenshot blurred behind.
- **Box art from**: your own picture, RetroArch's thumbnails folder, or the libretro thumbnails server. It matches loosely, so `Super Mario World.sfc` still finds `Super Mario World (USA)`. Art is cached in `%APPDATA%\Relic\art`.
- **67 systems**: every console, handheld and computer RetroArch runs well: Nintendo (NES and Famicom Disk System through Wii, 3DS, Game & Watch, Pokémon Mini), Sega (SG-1000 through Dreamcast and NAOMI), Sony (PS1, PS2, PSP), NEC, Atari (2600 to Jaguar and ST), SNK, 3DO, CD-i, ColecoVision, Intellivision, Vectrex and more, plus computers (C64, Amiga, MSX, ZX Spectrum, Amstrad, PC-98, X68000, DOS), ScummVM, PICO-8, TIC-80 and arcade. Folder names are matched loosely: `PS2 Games`, `Sony PlayStation 2 ISOs`, `Game Boy Advance (USA)` and `Nintendo/SNES` all work.
- **Newer consoles too**: PS4 (shadPS4), PS3 (RPCS3), Switch (Ryujinx), Wii U (Cemu), Xbox (xemu) and Xbox 360 (Xenia) run in their own emulators. Relic finds them in Program Files, AppData, Downloads, Desktop, Documents or an `Emulators` folder, or you choose the `.exe` in **Settings → Other emulators**. PS4 and PS3 games are read as game folders (with their real names from `param.sfo`). Xbox 360 `default.xex` and Wii U `code/*.rpx` games take their folder's name.
- **Library from**: every RetroArch playlist, plus any ROM folders you add. Name subfolders after the system (`SNES`, `Genesis`, `PS1`…) or keep one mixed folder (Relic sorts by file type). Multi-disc games with a `.m3u` show once.
- **Cores**: Relic picks the best installed core per system (Snes9x, Genesis Plus GX, SwanStation, mGBA…). You can change it per game with **Y → Core**, then make that the default for the whole system. If a core is missing, Relic tells you which one to download.
- **While you play**: Relic minimizes, records the session, and comes back when RetroArch closes. Play time and last played show on each game.
- **Updates built in**: Relic checks GitHub when it starts and shows **Update ready** on the Settings tile. In Settings → Updates, one button downloads, verifies and installs the new version, then restarts Relic. The single-file `Relic.exe` installs itself to `%LOCALAPPDATA%\Programs\Relic` (with Start menu and Desktop shortcuts) the first time you update. A copy run from source updates with `git pull`.
- **One copy at a time**: opening Relic again brings the open window to the front. **Settings → Quit Relic** closes it from the controller.
- **Your buttons**: Settings → Controller remaps every action to any controller button or key (pick the action, press the button). There's a one-press Nintendo layout that swaps A/B and X/Y. Hints on screen always show your layout.
- **Window**: in a window, drag any edge or corner to resize (Windows snapping works). Drag the top bar to move it, or double-click the bar to maximize.
- **Like a console**: **Select + Start** quits any game back to Relic (RetroArch and the standalone emulators). RetroArch saves when you quit, so games offer **Resume** or **Start over**. Controller profiles are installed for you, so Xbox, PlayStation, 8BitDo and Switch Pro pads just work.
- **Game details and search**: year, genre, players and developer from libretro's game database. Filter a shelf by players or genre, and search everything with the on-screen keyboard (or press `/`).
- **Collections**: make your own shelves (Y → Add to a collection); they show on the home screen.
- **CRT look**: off, retro consoles only, or everything (Settings → CRT look).
- **RetroAchievements**: sign in once in Settings (Relic keeps a token, not your password), with an optional hardcore mode.
- **BIOS import**: point Relic at the folder with your BIOS dumps; it recognises them and puts each where its emulator looks, now and after every new install.
- **Themes**: Relic, Arcade, Phosphor (with scanlines), Console Gray, Dot Matrix, Famicom, Vaporwave, Midnight, Sakura, Swirl, OLED Black and Paper (light). You can drop your own `.css` themes into `%APPDATA%\Relic\themes`.

## Run it

You don't need to install anything else first. Press Play on a game and Relic downloads what it needs: RetroArch (into `%LOCALAPPDATA%\Relic\RetroArch`), the right core for that console, or the standalone emulator for newer consoles (shadPS4, RPCS3, Cemu, xemu, Xenia). BIOS files are the exception: they're copyrighted, so for systems that need one (PS2, Sega CD, Saturn, TurboGrafx-CD, 3DO, Neo Geo CD, PC-FX) Relic says which file to add and opens the folder it goes in.

To run Relic:

- From source: double-click `run.bat` (it sets up Python packages the first time).
- Build an exe: double-click `build.bat`, which makes `dist\Relic\` and `dist\Relic.exe`.
- Releases: bump `VERSION` in `version.py` and push to `main`. GitHub builds `Relic.exe` and publishes the release.

Options: `--windowed` starts in a window, and `--browser` runs it in your web browser.

## Files

| | |
|---|---|
| `main.py` | window, start-up, tucking away while you play |
| `retroarch.py` | finding RetroArch, reading `retroarch.cfg`, cores, playlists, launching |
| `systems.py` | the consoles Relic knows, their file types, folder names and preferred cores |
| `library.py` | builds the library from playlists and ROM folders |
| `art.py` | box art, screenshots and title screens |
| `updater.py`, `install.py` | checking GitHub releases, downloading and swapping in updates, shortcuts |
| `setup_wizard.py`, `standalone.py` | downloading RetroArch, cores and emulators; BIOS checks; launching standalone emulators |
| `extras.py`, `metadata.py` | per-launch RetroArch settings (quit combo, resume, achievements, CRT), BIOS import, game details |
| `gamedata.py` | favorites, per-game core, play sessions |
| `server.py` | the local API the UI talks to (127.0.0.1 only) |
| `ui/` | the couch UI: `core.js` helpers, `pad.js` controller and keyboard, `app.js` screens |
| `themes/` | built-in themes |
