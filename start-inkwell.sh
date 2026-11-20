#!/usr/bin/env bash
# Babel's Library for Linux. Run:  bash start-inkwell.sh   (works from a Windows/NTFS or exFAT drive too)
cd "$(dirname "$(readlink -f "$0")")" || exit 1
PY="$(command -v python3 || command -v python)"
if [ -z "$PY" ]; then
  echo "Babel's Library needs Python 3. Install it with your package manager, e.g.  sudo apt install python3"
  exit 1
fi
# PDF reading copies and phone notifications use add-ons built for Python 3.11 or newer (app/vendor_py/linux)
if ! "$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
  echo "Note: this Python is older than 3.11, so PDF reading copies and phone notifications won't work."
  echo "      (Ubuntu 24.04, Mint 22, Fedora 39+ and Debian 12 all have 3.11 or newer.)"
fi

# Native window: pywebview + GTK WebKit. Without them it opens in a Chrome/Chromium/Edge app window instead.
#   Debian/Ubuntu/Mint:  sudo apt install python3-gi gir1.2-webkit2-4.1 python3-webview
#   Fedora:              sudo dnf install python3-gobject webkit2gtk4.1
#   Arch:                sudo pacman -S python-gobject webkit2gtk-4.1
# Optional: dimming the monitor on the sleep screen:  sudo apt install ddcutil  (then: sudo usermod -aG i2c $USER, log out and in)
if ! "$PY" -c "import webview" 2>/dev/null; then
  echo "Setting up the window library (one time)..."
  "$PY" -m pip install --user --quiet pywebview 2>/dev/null \
    || "$PY" -m pip install --user --quiet --break-system-packages pywebview 2>/dev/null \
    || echo "Couldn't install pywebview; Babel's Library will use a browser app window."
fi

# One-time: add Babel's Library to the applications menu (updated if this folder moves)
APPS="$HOME/.local/share/applications"
DESK="$APPS/inkwell.desktop"
if [ ! -f "$DESK" ] || ! grep -qF "$PWD/start-inkwell.sh" "$DESK" || ! grep -q "Babel" "$DESK"; then
  mkdir -p "$APPS"
  cat > "$DESK" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Babel's Library
Comment=Your offline library
Exec=bash "$PWD/start-inkwell.sh"
Icon=$PWD/app/static/icon.png
Terminal=false
Categories=Office;Education;AudioVideo;
DESKTOP
  chmod +x "$DESK" 2>/dev/null
  echo "Added Babel's Library to your applications menu."
fi

exec "$PY" app/desktop.py "$@"
