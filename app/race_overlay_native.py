#!/usr/bin/env python3
"""Umamusume Race Overlay (Linux) - start file.

The program itself lives in the folder "race_overlay" next to this file.
Run it with:  python3 race_overlay_native.py   (or use start_auto.sh / the desktop icon)
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

try:
    from race_overlay.main import main
except ModuleNotFoundError:
    if not os.path.isdir(os.path.join(HERE, "race_overlay")):
        sys.exit("The folder 'race_overlay' is missing next to race_overlay_native.py.\n"
                 "This version needs it. Download the full zip from GitHub and copy the whole folder.")
    raise

if __name__ == "__main__":
    main()
