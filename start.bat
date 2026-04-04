@echo off
chcp 65001 >nul

REM 1. Claude API Proxy
start "Proxy :3456" cmd /k node "C:\Users\User\AppData\Roaming\npm\node_modules\claude-max-api-proxy\dist\server\standalone.js"

timeout /t 1 /nobreak >nul

REM 2. Backend
start "Backend :8000" cmd /k "cd /d C:\Users\User\Documents\GitHub\AutoVideo && python -m uvicorn web.app:app --reload --host 0.0.0.0 --port 8000"

timeout /t 1 /nobreak >nul

REM 3. Frontend
start "Frontend :3000" cmd /k "cd /d C:\Users\User\Documents\GitHub\AutoVideo\frontend && npm run dev"

echo.
echo Services starting...
echo   Proxy    http://localhost:3456
echo   Backend  http://localhost:8000
echo   Frontend http://localhost:3000
echo.
pause
