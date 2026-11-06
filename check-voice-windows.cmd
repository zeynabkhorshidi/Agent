@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
 echo ابتدا start-windows.cmd را اجرا کنید.
 pause
 exit /b 1
)
".venv\Scripts\python.exe" -m sellora.diagnostics
pause
