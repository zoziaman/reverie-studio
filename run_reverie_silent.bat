@echo off
REM Reverie Automation (창 없이 실행)
cd /d "%~dp0"
cd src\gui
start "" pythonw main_window.py
