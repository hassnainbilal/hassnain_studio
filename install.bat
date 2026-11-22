@echo off
setlocal
cd /d "%~dp0"
echo === HASSNAIN STUDIO: install ===
where python >nul 2>nul || (echo [ERROR] Python 3.10+ not found. Install from https://www.python.org/downloads/ and tick "Add to PATH". & pause & exit /b 1)
where node >nul 2>nul || (echo [ERROR] Node.js 18+ not found. Install from https://nodejs.org/ & pause & exit /b 1)
where ffmpeg >nul 2>nul || (echo [ERROR] FFmpeg not found on PATH. Run: winget install Gyan.FFmpeg   then reopen this window. & pause & exit /b 1)
if not exist backend\.venv (python -m venv backend\.venv || (echo [ERROR] Could not create virtual environment. & pause & exit /b 1))
call backend\.venv\Scripts\python.exe -m pip install --upgrade pip
call backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt || (echo [ERROR] Python dependencies failed to install. & pause & exit /b 1)
if not exist backend\.env copy .env.example backend\.env >nul
pushd frontend
call npm install || (echo [ERROR] npm install failed. & popd & pause & exit /b 1)
popd
echo.
echo Install complete. Run start.bat to launch.
pause
