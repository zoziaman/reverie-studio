@echo off
REM Reverie Studio no-credential dry run
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
python "%~dp0src\reverie_demo.py" --backend-profile local_dry_run --out "%TEMP%\reverie-solo-demo"
pause
