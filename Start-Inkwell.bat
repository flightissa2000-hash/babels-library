@echo off
setlocal
title Babel's Library setup
cd /d "%~dp0"

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY ( where python >nul 2>nul && set "PY=python" )
if not defined PY (
  echo Babel's Library needs Python 3. Install it from https://www.python.org/downloads/
  echo During setup tick "Add python.exe to PATH", then double-click this file again.
  pause
  exit /b 1
)

rem find pythonw.exe (runs without a console window)
for /f "delims=" %%i in ('%PY% -c "import sys,os;print(os.path.join(os.path.dirname(sys.executable),'pythonw.exe'))"') do set "PYW=%%i"

rem one-time: install the native window library (needs internet once)
%PY% -c "import webview" >nul 2>nul
if errorlevel 1 (
  echo Setting up Babel's Library's desktop window - this happens only once...
  %PY% -m pip install --user --disable-pip-version-check pywebview
  if errorlevel 1 echo Couldn't install pywebview. Babel's Library will open in an Edge app window instead.
)

rem Desktop and Start Menu shortcuts (re-made if it has moved, e.g. to another drive)
set "MARK=%~dp0app\.shortcuts-babel"
if not exist "%MARK%" (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0app\make-shortcuts.ps1" -Pythonw "%PYW%" -AppDir "%~dp0."
  echo made> "%MARK%"
  echo Added a Babel's Library shortcut to your Desktop and Start menu.
)

start "" "%PYW%" "%~dp0app\desktop.py"
endlocal
