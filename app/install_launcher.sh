#!/usr/bin/env bash
# Creates an "Umamusume Race Overlay (Linux)" icon in your application menu AND on your Desktop,
# so you can start everything with a double-click (no terminal needed).
DIR="$(cd "$(dirname "$0")" && pwd)"
chmod +x "$DIR"/*.sh

if [ ! -f "$DIR/icon.png" ]; then
  echo "icon.png was not found in $DIR"
  echo "Copy icon.png into that folder, then run this script again."
  exit 1
fi

# keep a copy of the icon where the desktop looks for icons
ICON_DIR="$HOME/.local/share/icons/hicolor/512x512/apps"
mkdir -p "$ICON_DIR"
cp "$DIR/icon.png" "$ICON_DIR/uma-race-overlay.png"
gtk-update-icon-cache -f -t "$HOME/.local/share/icons/hicolor" >/dev/null 2>&1

ENTRY="[Desktop Entry]
Version=1.0
Type=Application
Name=Umamusume Race Overlay (Linux)
Comment=Native Linux race tower for OBS
Exec=$DIR/start_auto.sh
Path=$DIR
Icon=$DIR/icon.png
Terminal=false
Categories=Game;
StartupNotify=false"

APPS="$HOME/.local/share/applications"
mkdir -p "$APPS"
printf '%s\n' "$ENTRY" > "$APPS/uma-race-overlay.desktop"
chmod +x "$APPS/uma-race-overlay.desktop"
update-desktop-database "$APPS" >/dev/null 2>&1

DESK="$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")"
if [ -d "$DESK" ]; then
  rm -f "$DESK/Uma Race Overlay.desktop"    # icon from older versions
  NEW="$DESK/Umamusume Race Overlay (Linux).desktop"
  rm -f "$NEW"
  printf '%s\n' "$ENTRY" > "$NEW"
  chmod +x "$NEW"
  gio set "$NEW" metadata::trusted true 2>/dev/null
fi

echo "Done! Look for the 'Umamusume Race Overlay (Linux)' icon on your Desktop or in the application menu."
echo "If the Desktop icon still looks like a plain document: right-click it and choose 'Allow Launching'."
