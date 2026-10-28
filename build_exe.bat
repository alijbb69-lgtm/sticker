@echo off
REM ساخت فایل اجرایی ویندوز (نیازمند: pip install pyinstaller PySide6)
pip install -r requirements.txt pyinstaller
pyinstaller --noconfirm --windowed --name TelegramDateStudio --add-data "assets;assets" main.py
echo.
echo 
pause
