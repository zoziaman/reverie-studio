@echo off
REM Reverie Studio video-toon local smoke bundle and Remotion staging
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
set "PYTHONPATH=%~dp0src"
set "SMOKE_OUT=%TEMP%\reverie-videotoon-smoke"
python -m utils.videotoon_smoke local --source-repo-root "%~dp0." --output-dir "%SMOKE_OUT%" --duration-seconds 10
if errorlevel 1 goto failed
python -m utils.videotoon_smoke stage-remotion "%SMOKE_OUT%\smoke_manifest.json" --remotion-project "%~dp0remotion-poc"
if errorlevel 1 goto failed
echo.
echo Wrote smoke bundle and staged Remotion assets:
echo %SMOKE_OUT%
pause
exit /b 0

:failed
echo.
echo Video-toon smoke check failed. Read the message above, then run run_reverie_doctor.bat if the cause is unclear.
pause
exit /b 1
