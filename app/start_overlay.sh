#!/usr/bin/env bash
# Sets up a private Python environment once, then starts the native overlay.
# Extra options are passed through, e.g.:  ./start_overlay.sh --chroma
cd "$(dirname "$0")"
source ./lib.sh
if [ ! -d .venv ]; then
  say "Umamusume Race Overlay" "First start: installing the parts it needs (PyQt6).\nThis takes a few minutes and only happens once. The overlay opens when it is done."
  python3 -m venv .venv || { rm -rf .venv; say "Umamusume Race Overlay" "Python's venv is missing.\nOpen a terminal once and run:  sudo apt install python3-venv"; exit 1; }
  .venv/bin/pip install PyQt6 || { rm -rf .venv; say "Umamusume Race Overlay" "Could not install PyQt6. Check your internet connection and start again."; exit 1; }
fi
exec .venv/bin/python race_overlay_native.py "$@"
