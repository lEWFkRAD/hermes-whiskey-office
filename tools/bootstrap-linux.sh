#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ "${1:-}" == "--system" ]]; then
  sudo apt-get update
  sudo apt-get install -y python3-venv python3-pyatspi xvfb x11-utils xauth \
    dbus-x11 at-spi2-core gnome-terminal nautilus remmina xterm pulseaudio-utils git curl unzip
fi
python3 -m venv --system-site-packages .venv
.venv/bin/python -m pip install --require-hashes -r requirements.lock
printf '%s\n' 'Activate with: source .venv/bin/activate' 'Next: python tools/fetch_godot.py and follow docs/SETUP.md.'
