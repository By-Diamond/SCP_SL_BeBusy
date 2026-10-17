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
rem pycaw / comtypes 是「调节程序音量」和「语音播报」用的（音量会话 + 语音引擎）；
rem 它们的子模块是动态导入的，所以要显式收进来，否则打包后会报「找不到音频接口」。
python -m PyInstaller --noconfirm --clean --onefile --windowed ^
  --name SCP_SL_BeBusy ^
  --icon assets\app.ico ^
  --version-file tools\version_info.txt ^
  --collect-submodules pycaw ^
  --collect-submodules comtypes ^
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
