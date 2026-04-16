@echo off
chcp 65001 >nul
title YPA 설치 프로그램
echo.
echo  ╔══════════════════════════════════════════╗
echo  ║  YouTube Playlist Automator 설치         ║
echo  ║  All-In-One Installer                    ║
echo  ╚══════════════════════════════════════════╝
echo.

set "PROJECT_DIR=%~dp0"
set "VENV_DIR=%PROJECT_DIR%backend\.venv"
set "BACKEND_DIR=%PROJECT_DIR%backend"
set "REQ_FILE=%BACKEND_DIR%\requirements.txt"

:: ───────────────────────────────────────────────
:: 1. Python 확인
:: ───────────────────────────────────────────────
echo [1/5] Python 확인 중...
where python >nul 2>&1
if ERRORLEVEL 1 (
    echo.
    echo  [!] Python이 설치되어 있지 않습니다.
    echo      https://www.python.org/downloads/ 에서 설치해주세요.
    echo      설치 시 "Add Python to PATH" 체크 필수!
    echo.
    pause
    exit /b 1
)
for /f "tokens=*" %%i in ('python --version 2^>^&1') do set PYVER=%%i
echo     %PYVER% 확인됨

:: ───────────────────────────────────────────────
:: 2. FFmpeg 확인
:: ───────────────────────────────────────────────
echo [2/5] FFmpeg 확인 중...
where ffmpeg >nul 2>&1
if ERRORLEVEL 1 (
    echo     FFmpeg 미설치 → winget으로 설치 중...
    winget install Gyan.FFmpeg --accept-source-agreements --accept-package-agreements >nul 2>&1
    if ERRORLEVEL 1 (
        echo.
        echo  [!] FFmpeg 자동 설치 실패.
        echo      수동 설치: winget install Gyan.FFmpeg
        echo      또는: https://ffmpeg.org/download.html
        echo.
        pause
        exit /b 1
    )
    echo     FFmpeg 설치 완료
) else (
    echo     FFmpeg 확인됨
)

:: ───────────────────────────────────────────────
:: 3. Python 가상환경 + 의존성 설치
:: ───────────────────────────────────────────────
echo [3/5] Python 가상환경 설정 중...
if not exist "%VENV_DIR%\Scripts\python.exe" (
    echo     가상환경 생성 중... (최초 1회)
    python -m venv "%VENV_DIR%"
    if ERRORLEVEL 1 (
        echo  [!] 가상환경 생성 실패
        pause
        exit /b 1
    )
)
echo     가상환경 확인됨: %VENV_DIR%

echo [4/5] Python 패키지 설치 중... (1-2분 소요)
"%VENV_DIR%\Scripts\pip" install --no-cache-dir -q -r "%REQ_FILE%"
if ERRORLEVEL 1 (
    echo  [!] 패키지 설치 실패. 로그를 확인해주세요.
    pause
    exit /b 1
)
:: Playwright 브라우저 설치
echo     Playwright Firefox 설치 중...
"%VENV_DIR%\Scripts\playwright" install firefox >nul 2>&1
"%VENV_DIR%\Scripts\playwright" install-deps firefox >nul 2>&1
echo     패키지 설치 완료

:: ───────────────────────────────────────────────
:: 5. 자동 시작 등록 + 서버 시작
:: ───────────────────────────────────────────────
echo [5/5] 자동 시작 등록 + 서버 시작...

:: start_backend.vbs 경로 업데이트 (venv 경로를 프로젝트 내부로)
set "STARTUP_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "SHORTCUT_NAME=YPA-Backend.lnk"

if not exist "%STARTUP_DIR%\%SHORTCUT_NAME%" (
    powershell -Command "$ws = New-Object -ComObject WScript.Shell; $sc = $ws.CreateShortcut('%STARTUP_DIR%\%SHORTCUT_NAME%'); $sc.TargetPath = 'wscript.exe'; $sc.Arguments = '\"' + '%PROJECT_DIR%start_backend.vbs' + '\"'; $sc.WorkingDirectory = '%PROJECT_DIR%'; $sc.WindowStyle = 7; $sc.Description = 'YouTube Playlist Automator Backend'; $sc.Save()"
    echo     자동 시작 등록 완료
) else (
    echo     자동 시작 이미 등록됨
)

:: 백엔드 시작
powershell -Command "if (Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue) { exit 1 } else { exit 0 }" >nul 2>&1
if ERRORLEVEL 1 (
    echo     백엔드가 이미 실행 중입니다
) else (
    start "" /MIN cmd /c "cd /d %BACKEND_DIR% && %VENV_DIR%\Scripts\uvicorn main:app --reload --port 8000 --host 0.0.0.0"
    echo     백엔드 시작됨
)

echo.
echo  ╔══════════════════════════════════════════╗
echo  ║  설치 완료!                               ║
echo  ║                                          ║
echo  ║  서버: http://localhost:8000              ║
echo  ║  PC를 재시작해도 서버가 자동 실행됩니다.  ║
echo  ╚══════════════════════════════════════════╝
echo.
pause
