@echo off
chcp 65001 >nul

REM Codex Pro / ChatGPT subscription route via CliRelay (:3458).
REM The original start.bat is kept for the Claude proxy route (:3456).

set "CLIRELAY_EXE=C:\Users\User\Documents\GitHub\_proxy-lab\CliRelay\clirelay-test.exe"
set "CLIRELAY_CONFIG=C:\Users\User\Documents\GitHub\_proxy-lab\clirelay-test.yaml"

if exist "%CLIRELAY_EXE%" (
  start "CliRelay :3458" cmd /k ""%CLIRELAY_EXE%" -config "%CLIRELAY_CONFIG%""
) else (
  echo CliRelay executable not found:
  echo   %CLIRELAY_EXE%
  echo Start it manually, or run the proxy lab setup first.
)

timeout /t 1 /nobreak >nul

set "LLM_PROVIDER=codex"
set "LLM_PROXY_URL=http://127.0.0.1:3458"
set "CODEX_PROXY_URL=http://127.0.0.1:3458"
set "LLM_MODEL=gpt-5.5"
set "CODEX_TEXT_MODEL=gpt-5.5"
set "CODEX_IMAGE_MODEL=gpt-image-2"

start "Backend :9000" cmd /k "cd /d C:\Users\User\Documents\GitHub\AutoVideo && python -m uvicorn web.app:app --reload --host 0.0.0.0 --port 9000"

timeout /t 3 /nobreak >nul

start "" "http://localhost:9000/ui"

echo.
echo Services starting with Codex Pro / CliRelay...
echo   Proxy    http://127.0.0.1:3458
echo   Backend  http://localhost:9000
echo   UI       http://localhost:9000/ui
echo.
pause
