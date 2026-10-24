#!/bin/bash
cd "$(dirname "$0")"
python3 -c "import webview" 2>/dev/null || python3 -m pip install --user pywebview
exec python3 app/desktop.py
