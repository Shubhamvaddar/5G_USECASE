@echo off
setlocal
echo ========================================================
echo  SolarTwin 5G / Anubhav 5G Dashboard
echo ========================================================
echo Starting FastAPI Integrated Server (API + Dashboard)...
cd /d "%~dp0..\..\backend"
call python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
pause
