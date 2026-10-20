# Changelog

## 1.6.1

- **Better:** the standings are numbered 1, 2, 3 ... without repeats, even when players have the same points (they keep the order of the sheet).

## 1.6.0

- **New:** **points after every race**: 1st gets as many points as there are players, the last gets 1 (ties share). The results board has a new **PTS** column.
- **New:** **standings board**, its own window (*Umamusume Standings (Linux)*). It shows everybody's points and flips through the pages while the next race is set up, and goes away when it starts.
- **New:** **Standings tab**: use the points counted by the program (undo, save as .csv, new bracket) or read a **Google Sheet** link / `.csv` / `.xlsx` (choose the columns, reloaded every minute).
- **Numbering:** the standings are numbered 1, 2, 3 ... without repeats, even when players have the same points (they keep the order of the sheet).
- **Note:** copy the whole folder when you install this version: it adds `scoring.py`, `sheets.py` and `standings_board.py` in `race_overlay/`. The updater accepts them. Old settings keep working.

## 1.5.4

- **New:** **Status tab** in the Menu window: green / yellow / red checks (game running, Race Overlay server answers, Race Overlay folder found, race loaded, uma faces found) and a log viewer for this program and the start scripts' log files, with *Hide Wine noise* and *Copy for support*. No terminal needed. It only shows information.
- **Better:** the program now writes what it does (status changes, race loaded / started / finished) to its log.
- **Note:** copy the whole folder when you install this version, because it adds `diagnostics.py` and `logbuf.py` in `race_overlay/`. The updater accepts them.

## 1.5.3

- **New:** the Race Overlay folder can sit inside your project folder (next to `app`). It is found there first, and `.gitignore` makes sure it is never uploaded to GitHub.

## 1.5.2

- **New:** the start script now starts Race Overlay's **server** (`server.exe`) by itself when the game starts, so you no longer run it by hand. The server log is `/tmp/race-overlay-server.log`, and a popup tells you if it did not start. Your overlay only needs this server, so the Race Overlay window is not opened any more.
- **New:** `RACE_OVERLAY_START` in `settings.sh`: `server` (default), `app` (the whole Race Overlay program) or `both`.

## 1.5.1

- **New:** no terminal needed. **Install icon (double-click)** adds the menu / Desktop icon. Problems (and the first-time setup) are shown in a popup window, and the log is written to `/tmp/race-overlay-native.log`.
- **New:** Race Overlay is found automatically in your Documents, Downloads or Desktop folder and linked to the game's Wine prefix. A broken link is repaired. The new `RACE_OVERLAY_DIR` setting in `settings.sh` is for any other place. Race Overlay itself is still not part of this repository.
- **Fix:** the start script passed a cut-off option (`--disable-gpu-san`) to Race Overlay.
- **Fix:** a failed first-time install no longer leaves a half-made Python folder that stops every later start.
- **Note:** copy the whole folder when you install this version, because it adds `lib.sh`. The updater accepts it.

## 1.5.0

- **New:** **Umas tab** in the Menu window. Every uma that appears in a race is listed with her face. Choose your own picture for her, or press *Use default face* to go back. Your pictures are saved in `images/uma` (named after the card id), and the default faces are never changed.
- **New:** the option **Use the faces from Race Overlay when I have not chosen a picture**. Turn it off to show only your own pictures (umas without one get the letter circle). It is kept when you press *Reset look to defaults*.
- **Better:** the online updater link is filled in already, so **Check online** works without pasting anything.

## 1.4.0

- **New:** **results board.** After a race a second window (*Umamusume Race Results (Linux)*) shows the final places in two columns like a TV results graphic: place, picture, trainer and uma, finish time, gap to the winner, and the track name at the bottom. It slides in as the tower slides out. Add it to OBS as its own window source. Turn it on or off and choose how long it stays in the Look tab. *Show results board (to place it)* in the Menu and tray lets you position it before a race.
- **New:** **position arrows.** A small green up / red down arrow next to the rank when a uma gains or loses a place (Look tab to turn off).
- **New:** **auto size.** The window height now follows the umas that are shown (also when a setting changes), and the whole tower is scaled down when it would be taller than the screen. Your own size comes back for a smaller field.
- **New:** **Rows in the tower** (Look tab): show only the top N umas.
- **New:** **colour sets** (Look tab): Midnight, Charcoal and gold, Sakura, Mint, Daylight, High contrast. New **accent colour** setting for the results board.
- **New:** on a Wayland desktop the program starts through XWayland so the window can stay on top and OBS can capture it. `--keep-wayland` turns this off. See the new Wayland section in the README.
- **Better:** `settings.sh` finds Steam (also the Flatpak version) and the newest GE-Proton by itself instead of fixed paths, and every value can be set from outside. An existing `settings.sh` is still never overwritten by the updater.
- **Better:** the fallback letter in a picture circle is always white, so it can be read on light colour sets.
- **Better:** the move / resize code is shared by both windows (new `race_overlay/frameless.py`); the Rows spin box has the same look as the other inputs.
- **Fix:** removed the duplicate `gitignore` file, the hard coded `/home/darryl/...` paths and the outdated version in `latest.json.example`.
- **Note:** install this version by copying the whole folder, because it adds two new files in `race_overlay/` (`results_board.py` and `frameless.py`). The updater accepts them.

## 1.3.0

- **New:** the uma image and the player picture are now two separate pictures. The uma always shows its own image; the player gets a small picture on its corner. Choose *Uma image + player picture*, *Uma image only* or *Player picture* in the Look tab, the tray menu or the right-click menu (the **T** key cycles through them). A player without a picture shows no small picture.
- **Better:** the program is split into small files in the `race_overlay/` folder (one file per part). `race_overlay_native.py` is only the start file, so all start scripts, the desktop icon and the Steam option keep working. This makes new features much easier to add.
- **Better:** the updater understands the new folder and still never touches `settings.sh`, your pictures or your settings.
- **Note:** install this version by copying the whole folder (including `race_overlay/`). Older versions of the updater cannot add the new folder by themselves.
- **Fix:** removed two stray files from the repository.

## 1.2.0

- **New:** no overlay before the race. The window is hidden until the race starts, then the tower slides in from the side the window is on (or left / right, your choice) and slides out after the race. The window never takes the keyboard focus from the game.
- **New:** alternative outfits are shown as *Name (Outfit)*, the normal outfit as just *Name*. New **Outfits** tab to name them (saved in `images/outfits.json`). *Meisho Doto (Halloween)* is built in.
- **New:** **Start delay** setting for saved races. The game saves the race file when the race loads, so the overlay now waits before it shows the race instead of starting at once.
- **Better:** the Menu, Races and Look tabs scroll on small screens; shorter labels in the Look tab.
- **Note:** the overlay window is now hidden at start when a tray icon is available. Use **Show overlay window (to place it)** to move it, or untick **Hide the window until a race starts**.

## 1.1.0

- **New:** Races tab in the Menu window with a **Saved races folder** setting (Browse button). The folders inside it are searched too, and you can switch the folder while the program runs.
- **New:** choose where the races come from (Live, Saved races, or follow the start script) without editing `settings.sh`.
- **New:** dark settings window with a pink, yellow and mint theme, rounded cards and a scrolling Menu tab for small screens.
- **Better:** saved-races mode only opens `.json` files that are really races, so other files (like a veterans list) no longer interrupt the race that is playing.
- **Better:** "Reset look to defaults" no longer resets the saved races folder, the source or the update link.
- **Better:** the red status message now points to `/tmp/race-overlay-wine.log`.

## 1.0.1

- First public version.
