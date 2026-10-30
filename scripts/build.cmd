@echo off
rem Build OpenDM: dist\OpenDM\, the portable ZIP and the installer. See scripts\build.py.
cd /d "%~dp0.."
".venv\Scripts\python.exe" scripts\build.py %*
