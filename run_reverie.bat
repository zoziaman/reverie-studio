@echo off
REM Reverie Automation 실행 스크립트
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
python src\main_gui.py
pause
