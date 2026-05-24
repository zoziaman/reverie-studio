@echo off
REM Reverie Studio silent launcher
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
start "" pythonw "%~dp0src\main_gui.py"
