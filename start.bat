@echo off
title YouTube Playlist Automator
echo.
echo  ============================================
echo   YouTube Playlist Video Automator
echo  ============================================
echo.

:: 인수 처리: --silent (시작프로그램용, 브라우저 안 열기)
set SILENT=0
if "%1"=="--silent" set SILENT=1

:: 이미 실행 중인지 체크
powershell -Command "if (Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue) { exit 1 } else { exit 0 }" >nul 2>&1
if ERRORLEVEL 1 (
    echo [!] 백엔드가 이미 실행 중입니다 (port 8000^)
    if %SILENT%==1 exit /b 0
    goto :SKIP_START
)

:: Backend (FastAPI)
echo [1/1] 백엔드 시작 중... (http://localhost:8000)
start "YPA-Backend" /MIN cmd /c "cd /d %~dp0backend && d:\coding\.venv\Scripts\uvicorn main:app --reload --port 8000 --host 0.0.0.0 2>&1"
timeout /t 4 /nobreak >nul

:SKIP_START
echo.
echo  ✓ 백엔드: http://localhost:8000
echo  ✓ API 문서: http://localhost:8000/docs
echo.

:: 브라우저 자동 오픈 (silent 모드가 아닐 때만)
if %SILENT%==0 (
    start "" "http://localhost:3000"
    echo  브라우저에서 http://localhost:3000 을 열어주세요.
)

if %SILENT%==1 (
    echo  [자동 시작 모드] 백엔드만 실행됩니다.
    exit /b 0
)

echo  이 창을 닫으면 서버가 중단됩니다.
echo.

:: 서버 유지 (아무 키나 누르면 종료)
pause
powershell -Command "Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }"
echo 서버 종료됨.
