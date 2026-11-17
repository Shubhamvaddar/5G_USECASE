@echo off
setlocal
cd /d "%~dp0"
where npm >nul 2>nul
if errorlevel 1 (
  echo Node.js and npm are required. Install Node.js 20 or newer, then retry.
  pause
  exit /b 1
)
if not exist node_modules (
  echo Installing dashboard dependencies...
  call npm install
  if errorlevel 1 (
    pause
    exit /b 1
  )
)
call npm run dev -- --open
pause
