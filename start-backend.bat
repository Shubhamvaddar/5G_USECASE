@echo off
setlocal
echo Starting SolarTwin 5G Backend (FastAPI + Dashboard)...
cd /d "%~dp0backend"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
pause
