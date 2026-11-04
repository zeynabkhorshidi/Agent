@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    py -3.12 -m venv .venv
    if errorlevel 1 (
        echo Python 3.12 را نصب کنید و این فایل را دوباره اجرا کنید.
        echo https://www.python.org/downloads/windows/
        pause
        exit /b 1
    )
)
if not exist ".env" copy ".env.example" ".env" >nul
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo نصب وابستگی‌ها انجام نشد. اتصال شبکه و خروجی بالا را بررسی کنید.
    pause
    exit /b 1
)
echo مرورگر را روی نشانی زیر باز کنید و این پنجره را باز نگه دارید:
echo http://127.0.0.1:8000
echo میکروفون به localhost یا HTTPS نیاز دارد. بک‌اند باید به شبکه شرکت متصل باشد.
".venv\Scripts\python.exe" -m uvicorn sellora.app:app --host 127.0.0.1 --port 8000
if errorlevel 1 pause
