# Babel's Library on Linux

Everything Babel's Library needs is on this drive: the program (`Inkwell\app`), your library database and
settings (`Inkwell\library_data`) and your files (`Library`). Plug the drive in and start it from there.

## The first time
1. Install the window it runs in (Ubuntu / Mint / Debian):

       sudo apt install python3-gi gir1.2-webkit2-4.1 python3-webview

   Fedora: `sudo dnf install python3-gobject webkit2gtk4.1` · Arch: `sudo pacman -S python-gobject webkit2gtk-4.1`
2. Start it: open a terminal in the drive's `Inkwell` folder and run

       bash start-inkwell.sh

   It adds **Babel's Library** to your applications menu, so after this you can start it from there.
3. Optional, for the sleep screen to dim your monitor: `sudo apt install ddcutil`, then
   `sudo usermod -aG i2c $USER` and log out and back in.

Python 3.11 or newer is needed for PDF reading copies and phone notifications (Ubuntu 24.04, Mint 22,
Fedora 39+ and Debian 12 have it).

## What comes with you
- The whole library, reading places, notes, journal, collections, profiles, the Bulletin and settings.
- Paired phones stay paired. "Reach this library from anywhere" downloads its Linux tunnel program the first time.
- Browser history and bookmarks (from `library_data\carry-over`, picked up on the first start).

## What's different on Linux
- **Websites open in your own web browser** (Firefox, say). The browser inside the window (with its ad blocker,
  split view, password filling and time limits) is built on Windows' WebView2, so it is Windows only.
- **Saved passwords stay locked to Windows** (Windows encrypted them). Import your `passwords.csv` export into
  Firefox instead, then delete that file: it isn't encrypted.
- Not on Linux: "Start with Windows", devices with no drive letter (phones over MTP), the Windows shortcuts.
- The sleep screen knows you're away from GNOME's idle timer (or `xprintidle`); without either, it counts from the
  last key or mouse move in Babel's own window.

## Where the rest is
`F:\Babel-PC` (the drive's `Babel-PC` folder) holds what lived on the Windows computer: the Android app's source,
**its signing key and password** (`BabelPhone\babel-personal.keystore`, `keystore-password.txt`: keep these, a new key
can't update the app on your phone), the GitHub copies, database backups and the full browser database.
