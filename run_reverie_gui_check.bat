@echo off
REM Reverie Studio GUI import readiness check
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
python "%~dp0src\reverie_gui_check.py" --json --out "%TEMP%\reverie-gui-check"
pause
