@echo off
setlocal
cd /d "%~dp0"

echo ==================================================
echo  SCP_SL_BeBusy - onefile build (PyInstaller)
echo ==================================================
echo.

where python >nul 2>nul
if errorlevel 1 (
  echo [X] python not found in PATH. Install Python 3.9+ first.
  goto :fail
)

echo [1/4] Installing build dependencies ...
python -m pip install -r requirements-build.txt
if errorlevel 1 goto :fail

echo.
echo [2/4] Generating app icon ...
python tools\make_icon.py
if errorlevel 1 goto :fail

echo.
echo [3/4] Building single-file exe (this takes a while) ...
python -m PyInstaller --noconfirm --clean --onefile --windowed ^
  --name SCP_SL_BeBusy ^
  --icon assets\app.ico ^
  --version-file tools\version_info.txt ^
  scpsl_auto_player.py
if errorlevel 1 goto :fail

echo.
echo [4/4] Done.
echo.
echo   Output : dist\SCP_SL_BeBusy.exe
echo   First run creates settings.json / SCP_SL_BeBusy.log next to the exe.
echo   Run it, then check the tray icon (left click = window, right click = menu).
echo.
pause
exit /b 0

:fail
echo.
echo [X] Build failed - scroll up for the error message.
pause
exit /b 1
