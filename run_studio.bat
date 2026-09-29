@echo off
rem Double-click this file to start Lambert Studio.
rem It uses the project's own Python environment (created during setup) and
rem runs without a console window; problems are written to
rem %LOCALAPPDATA%\LambertStudio\logs.  Use run_studio_debug.bat to see output.
rem Options:  --qt  (Qt window instead of Edge)   --browser  (normal browser tab)
set VENV_DIR=%USERPROFILE%\.venvs\lambert\Scripts
if exist "%VENV_DIR%\pythonw.exe" (
    start "" "%VENV_DIR%\pythonw.exe" "%~dp0lambert_studio.py" %*
) else (
    echo The project environment was not found at %VENV_DIR%
    echo Trying the default Python instead...
    python "%~dp0lambert_studio.py" %*
    if errorlevel 1 pause
)
