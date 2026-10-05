@echo off
rem Same as run_studio.bat, but keeps a console open so you can see any
rem messages. Useful if something goes wrong.
"%USERPROFILE%\.venvs\lambert\Scripts\python.exe" -X faulthandler "%~dp0src\lambert_studio.py" %*
echo.
echo Lambert Studio has stopped. Log folder: %USERPROFILE%\.lambert_studio\logs
pause
