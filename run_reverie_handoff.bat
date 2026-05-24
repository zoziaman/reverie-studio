@echo off
REM Reverie Studio safe continuation handoff report
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
python "%~dp0src\reverie_solo_handoff.py" --json --out "%TEMP%\reverie-solo-handoff"
pause
