# Changelog

## 1.9.5

- **New:** **When the boards come in** (Boards tab). The skill luck board, the match board and the standings board can each come in **one after the other** (as before) or **together with the results board**, so you can show all of them at once. Each one also has extra seconds of waiting time, and the results board has its own delay too. *Show all at once* and *One after the other* set all of them in one click.
- **Note:** nothing changes unless you change it. Boards that come in together appear at the same time, so give each one its own place in OBS.

## 1.9.4

- **New:** **team match (draft)**, for team events. The new **Draft** tab holds two teams (name, colour, players, drafted umas). After every race the best placed team players score for their team (**4 / 2 / 1** points, changeable) and the first team to reach the target (**25**, changeable) wins. Players on no team (NPCs) never score; the next team player takes the placement.
- **New:** **match board**, its own OBS window *Umamusume Match (Linux)*: both scores with a progress bar, the points of every race, the drafted umas and *TEAM X WINS!*. It comes in after the results board and stays until the next race. *Show match board (to place it)* is in the Home tab and the tray menu.
- **New:** on the results board the rows are tinted in the team colour and the PTS column shows the team points.
- **New:** *Undo last race*, *Add or take points...* (rulings by hand), *New match* and *Save as .csv...*. Saved in `match.json`.
- **Note:** off by default. While *Team match mode* is on, the single-player points and the standings board pause.

## 1.9.3

- **Better:** the Look tab is split into separate tabs: **Tower** (window, rows, small tower, corner), **Boards** (results board and skill luck board, one box each) and **Look** (pictures, colours, text, font). The tab bar is tighter so all eight tabs fit.
- **New:** **own title** for the results board and for the skill luck board (for example *GRAND FINAL*).
- **New:** **what each results row shows**: finish time and gap, finish time only, or names only.
- **New:** the skill luck board has its own **stay time** (or until the next race).
- **Note:** nothing was removed, and old settings keep working.

## 1.9.2

- **New:** **skill luck board**. After the results board it shows the **luckiest** and the **unluckiest** players: how many of the skills they brought activated (for example 13/16), who missed the most, and who hit every skill. Its own window for OBS: *Umamusume Skill Luck (Linux)*. Turn it on in the Look tab (*More options*) and choose how many players are shown on each side. *Show skill luck board (to place it)* is in the Home tab and the tray menu.
- **Note:** off by default. It needs the equipped skills, which saved race files contain. Without them it counts only the skills that activated.

## 1.9.1

- **Easier settings:** the settings window is tidier for people who never used the overlay. Six tabs now: **Home, Race data, Look, People, Points, Help**.
- **Home:** a short *Quick start* (3 steps) and the main buttons. Start-up options, picture folders and updates are folded under *More*.
- **Look:** only the basics are shown (pictures, colour set, text size, tower style, preview). Colours, window and results board options are folded under *More options*.
- **People:** Players, Umas and Outfits are now one tab with three small tabs inside.
- **Points:** the sheet settings show only when the source is *A spreadsheet*, and the program's own points box only when it is *Counted by this program*. Column settings and the board look are folded.
- **Fix:** the sheet status line on the Points tab updates again when the tab is opened.
- **Note:** nothing was removed and old settings keep working. Tabs were renamed: Races is now *Race data*, Status is now *Help*, Menu is now *Home*, Standings is now *Points*.

## 1.9.0

- **New:** **small corner tower**. In the Look tab, *Tower style* can be set to a compact tower that shows only the top umas (2 to 10, default 5) with place, picture, name and gap, and a short header with the race clock. At the finish it slides out and the results board comes in, as before. Also in the tray menu and the right-click menu.
- **New:** **Move window to** a corner of the screen (top left, top right, bottom left, bottom right).
- **Fix:** a round picture could be drawn outside the rows that are shown (a sliver of the next uma under the last row).
- **Note:** nothing changes unless you pick the small tower. Old settings keep working.

## 1.8.1

- **Faster:** the Race Overlay server now starts as soon as it can. Before, the start script waited a fixed time (15 s, or 60 s on a slow game) and the server did not find the game when that was too short. Now it tries right away and tries again every few seconds until the server has found the game, so it is up a few seconds after the game is ready. `RACE_OVERLAY_DELAY` in `settings.sh` is now 5 seconds.

## 1.8.0

- **New:** **avatars** in the standings: every player gets the picture you chose in the Players tab (the first letter when there is none). Can be turned off.
- **New:** **portrait or landscape**: one column, or two columns side by side (Standings tab, Look section).
- **New:** **show the standings only when you want**: after every N races (for example 5), or never automatically. The new *Show / hide the standings now* button (Standings tab and tray menu) shows them by hand.
- **Changed:** thinner border. The added-up views are now called **After Round 2** and **Overall Total**.

## 1.7.3

- **Fix:** Round 2, Round 3 and the added-up views were wrong with a Google Sheet, because Google leaves hidden columns out of the download and every column letter moves. The tables are now found by their headers (*Trainer / Uma / Score*, *Member / Round 1 / 2 / 3*), so it works either way. Columns typed by hand still work.
- **New:** players with 0 points are not shown in the standings (option in the Standings tab).

## 1.7.2

- **Fix:** the round views now read the right columns. Everything comes from the one sheet tab: Round 1, 2 and 3 from their own tables, and *Rounds 1 + 2* / *Rounds 1 + 2 + 3* from the *Final Rankings* table. The columns can be changed in the Standings tab (Rounds section).
- **Changed:** the gold / silver / bronze rows are now **borders**. One round: 9 points = gold, 8 = silver, 7 = bronze (editable). Rounds added up and points counted by the program: the best N players (default 10, editable) get a gold border.

## 1.7.1

- **New:** quitting the overlay now also closes the Race Overlay server that the start script started (Menu tab, can be turned off). A Race Overlay you opened yourself is never closed.
- **New:** **Replay a saved race (test)** in the Menu tab and the tray menu: choose a race file and the tower, results board and standings board play it, with no game and no server. It never gives points.

## 1.7.0

- **New:** **round views** for the standings board: *Round 1*, *Round 2*, *Round 3*, *Rounds 1 + 2* and *Rounds 1 + 2 + 3*. Set them up in the Standings tab (Rounds section) and switch while streaming: right click the standings board or use the tray menu, *Standings view*.
- **New:** the standings rows are coloured **gold / silver / bronze** in blocks (the first 5 gold, the next 5 silver, the next 5 bronze). The block size can be changed or switched off in the Standings tab.
- **Note:** old settings keep working. Round views read your *Final Rankings Calc* tab by default (player in column A, rounds in B, C, D, first row 3).

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
