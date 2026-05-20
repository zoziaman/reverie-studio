@echo off
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat"
pip install simpleaudio
echo DONE_EXIT_CODE=%ERRORLEVEL%
pause
