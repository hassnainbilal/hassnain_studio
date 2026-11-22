@echo off
setlocal
cd /d "%~dp0"
if not exist backend\.venv\Scripts\python.exe (echo [ERROR] Not installed yet. Run install.bat first. & pause & exit /b 1)
if not exist frontend\node_modules (echo [ERROR] Frontend not installed. Run install.bat first. & pause & exit /b 1)

rem Reuse an already-running HASSNAIN STUDIO backend instead of starting a duplicate.
set "API_PID="
for /f "tokens=5" %%P in ('netstat -ano ^| findstr LISTENING ^| findstr ":8000 "') do set "API_PID=%%P"
if defined API_PID (
  powershell -NoProfile -Command "try { $h=Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/health' -TimeoutSec 2; if ($h.mode -like '*HASSNAIN STUDIO*') { exit 0 } else { exit 1 } } catch { exit 1 }"
  if errorlevel 1 (
    echo [ERROR] Port 8000 is already being used by another program. PID: %API_PID%
    echo Close that program or stop it with: taskkill /PID %API_PID% /F
    echo Then run start.bat again.
    pause
    exit /b 1
  ) else (
    echo Existing HASSNAIN STUDIO backend found on port 8000. Reusing it.
  )
) else (
  start "HASSNAIN STUDIO Backend" cmd /k "cd /d %~dp0backend && .venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000"
)
start "HASSNAIN STUDIO Frontend" cmd /k "cd /d %~dp0frontend && npm run dev -- --host 127.0.0.1"
timeout /t 5 >nul
echo HASSNAIN STUDIO is running at http://localhost:5173
echo Backend API: http://127.0.0.1:8000/docs
start http://localhost:5173
