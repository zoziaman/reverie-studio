@echo off
REM 라이센스 관리자 GUI 실행 스크립트
cd /d "%~dp0"
cd src\utils
python license_manager_gui.py
pause
