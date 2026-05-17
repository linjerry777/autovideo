@echo off
chcp 65001 >nul

REM 1. Claude API Proxy
start "Proxy :3456" cmd /k node "C:\Users\User\AppData\Roaming\npm\node_modules\claude-max-api-proxy\dist\server\standalone.js"

timeout /t 1 /nobreak >nul

REM 2. Backend
start "Backend :9000" cmd /k "cd /d C:\Users\User\Documents\GitHub\AutoVideo && python -m uvicorn web.app:app --reload --host 0.0.0.0 --port 9000"

timeout /t 1 /nobreak >nul

timeout /t 3 /nobreak >nul

REM 3. Open UI in browser
start "" "http://localhost:9000/ui"

echo.
echo Services starting...
echo   Proxy    http://localhost:3456
echo   Backend  http://localhost:9000
echo   UI       http://localhost:9000/ui
echo.
pause
