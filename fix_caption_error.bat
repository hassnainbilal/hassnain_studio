@echo off
setlocal
cd /d "%~dp0"
if not exist backend\.venv\Scripts\python.exe (
  echo [ERROR] Project environment not found. Run install.bat first.
  pause
  exit /b 1
)
echo Fixing Faster-Whisper / PyAV compatibility...
call backend\.venv\Scripts\python.exe -m pip install --upgrade "av>=12,<18"
if errorlevel 1 (
  echo [ERROR] Could not install the compatible PyAV version.
  pause
  exit /b 1
)
call backend\.venv\Scripts\python.exe -c "import av; print('Installed PyAV:', av.__version__)"
echo.
echo Caption dependency fix completed. Close old backend windows and run start.bat again.
pause
