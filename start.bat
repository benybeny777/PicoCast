@echo off
cd /d "%~dp0"
.venv\Scripts\python.exe -m web_app.app --open-browser --reload
exit /b 0
