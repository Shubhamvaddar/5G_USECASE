@echo off
setlocal
echo Starting SolarTwin 5G Data Acquisition Collector...
cd /d "%~dp0backend"
python -m data_acquisition.collector
pause
