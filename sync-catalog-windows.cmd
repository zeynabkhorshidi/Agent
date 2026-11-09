@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
 echo ابتدا start-windows.cmd را اجرا کنید.
 pause
 exit /b 1
)
".venv\Scripts\python.exe" -m sellora.sync_catalog
echo.
echo گزارش در پوشه data ذخیره شد. این ابزار باید از شبکه دارای دسترسی به کاتالوگ اجرا شود.
pause
