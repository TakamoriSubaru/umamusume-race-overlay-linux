# Changelog

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
