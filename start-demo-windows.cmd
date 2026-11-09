@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set SELLORA_DB=data/sellora-demo.db
set SELLORA_DEMO_MODE=true
set SELLORA_SEED_CUSTOMERS=true
echo حالت نمایش: ۶ مشتری نمونه و دو کالای عیناً ارسال‌شده از کاتالوگ؛ قیمت‌ها و سابقه خرید ساختگی‌اند.
call start-windows.cmd
