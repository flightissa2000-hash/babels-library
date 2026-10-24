@echo off
cd /d "%~dp0"
where py >nul 2>nul && (py -3 app\server.py & goto :eof)
python app\server.py
