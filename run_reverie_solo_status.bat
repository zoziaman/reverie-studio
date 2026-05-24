@echo off
REM Reverie Studio solo-use local readiness report
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
python "%~dp0src\reverie_solo_status.py" --json
pause
