#!/usr/bin/env bash
# Sets up a private Python environment once, then starts the native overlay.
# Extra options are passed through, e.g.:  ./start_overlay.sh --chroma
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  echo "First run: installing PyQt6 (a few minutes)..."
  python3 -m venv .venv || { echo "Run: sudo apt install python3-venv"; exit 1; }
  .venv/bin/pip install PyQt6 || exit 1
fi
exec .venv/bin/python race_overlay_native.py "$@"
