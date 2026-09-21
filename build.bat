@echo off
cd /d "%~dp0"

echo ========================================
echo   Building exe (using system browser)...
echo ========================================

python -m PyInstaller --noconfirm --onefile --windowed --name "AttendanceScraper" --add-data "config.json;." main.py

echo.
echo ========================================
echo   Done! Check dist\ folder
echo ========================================
pause
