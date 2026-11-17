@echo off
setlocal
echo ============================================================
echo   SolarTwin 5G — Starting Complete System
echo ============================================================
echo.
echo [1/2] Launching Backend Server (API + Dashboard at http://127.0.0.1:8000)...
start "SolarTwin 5G Backend & Dashboard" cmd /k "cd /d %~dp0backend && python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload"

timeout /t 3 /nobreak >nul

echo [2/2] Launching Data Acquisition Collector...
start "SolarTwin 5G Collector" cmd /k "cd /d %~dp0backend && python -m data_acquisition.collector"

timeout /t 2 /nobreak >nul
echo Opening Dashboard in your browser...
start http://127.0.0.1:8000/

echo.
echo System started successfully!
echo   Dashboard : http://127.0.0.1:8000/
echo   API Docs  : http://127.0.0.1:8000/docs
echo.
pause
