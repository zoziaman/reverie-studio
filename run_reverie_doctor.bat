@echo off
REM Reverie Studio local setup doctor
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
python "%~dp0src\reverie_doctor.py" --json
pause
