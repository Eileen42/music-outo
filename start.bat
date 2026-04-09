@echo off
title YouTube Playlist Automator
echo.
echo  ============================================
echo   YouTube Playlist Video Automator
echo  ============================================
echo.

:: 기존 포트 점유 프로세스 종료
echo [정리] 기존 프로세스 종료...
powershell -Command "Get-NetTCPConnection -LocalPort 8000,3000 -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }" >nul 2>&1
timeout /t 1 /nobreak >nul

:: Backend (FastAPI)
echo [1/2] 백엔드 시작 중... (http://localhost:8000)
start "YPA-Backend" /MIN cmd /c "cd /d %~dp0backend && d:\coding\.venv\Scripts\uvicorn main:app --reload --port 8000 --host 0.0.0.0 2>&1"
timeout /t 4 /nobreak >nul

:: Frontend (Vite)
echo [2/2] 프론트엔드 시작 중... (http://localhost:3000)
start "YPA-Frontend" /MIN cmd /c "cd /d %~dp0frontend && npm run dev 2>&1"
timeout /t 3 /nobreak >nul

echo.
echo  ✓ 백엔드:    http://localhost:8000
echo  ✓ 프론트엔드: http://localhost:3000
echo  ✓ API 문서:  http://localhost:8000/docs
echo.
echo  브라우저에서 http://localhost:3000 을 열어주세요.
echo  이 창을 닫으면 서버가 중단됩니다.
echo.

:: 브라우저 자동 오픈
start "" "http://localhost:3000"

:: 서버 유지 (아무 키나 누르면 종료)
pause
powershell -Command "Get-NetTCPConnection -LocalPort 8000,3000 -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }"
echo 서버 종료됨.
