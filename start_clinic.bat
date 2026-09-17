@echo off
title Fayz Control CRM (Port 3000)
cd /d "%~dp0"
echo ===================================================================
echo     FAYZ CONTROL — HOSPITAL MANAGEMENT & CRM (PORT 3000)
echo ===================================================================
echo.
echo Server: http://localhost:3000
echo.
start http://localhost:3000
python server.py 3000
pause
