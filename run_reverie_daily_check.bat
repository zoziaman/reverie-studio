@echo off
REM Reverie Studio safe daily preflight
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
python "%~dp0src\reverie_solo_preflight.py" --json --out "%TEMP%\reverie-solo-preflight"
pause
