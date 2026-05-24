@echo off
REM Reverie Studio local .env bootstrap
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
python "%~dp0src\reverie_env_bootstrap.py" --json
pause
