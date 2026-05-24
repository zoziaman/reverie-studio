@echo off
REM Reverie Studio GUI launcher
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
python "%~dp0src\main_gui.py"
pause
