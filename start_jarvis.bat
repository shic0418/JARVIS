@echo off
cd /d "%~dp0"
where pythonw >nul 2>nul && (start "" pythonw "%~dp0main.py") || (start "" python "%~dp0main.py")
