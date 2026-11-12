@echo off
chcp 65001 >nul
cd /d "%~dp0"
".env\Scripts\python.exe" uyandir.py --simdi
pause
