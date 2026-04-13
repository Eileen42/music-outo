@echo off
chcp 65001 >nul
title Music Outo - 설치 프로그램

echo.
echo  ╔═══════════════════════════════════════════╗
echo  ║   YouTube Playlist Automator - 설치      ║
echo  ╚═══════════════════════════════════════════╝
echo.

:: ── 1. Docker Desktop 확인 ──────────────────────────────────────────
echo [1/4] Docker Desktop 확인 중...
where docker >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo.
    echo  ⚠ Docker Desktop이 설치되어 있지 않습니다.
    echo.
    echo  Docker Desktop을 먼저 설치해주세요:
    echo  https://www.docker.com/products/docker-desktop/
    echo.
    echo  설치 후 이 파일을 다시 실행해주세요.
    echo.
    start https://www.docker.com/products/docker-desktop/
    pause
    exit /b 1
)

:: Docker가 실행 중인지 확인
docker info >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo.
    echo  ⚠ Docker Desktop이 실행되고 있지 않습니다.
    echo  Docker Desktop을 시작합니다...
    start "" "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    echo  Docker가 시작될 때까지 30초 대기합니다...
    timeout /t 30 /nobreak >nul
    docker info >nul 2>&1
    if %ERRORLEVEL% neq 0 (
        echo  Docker가 아직 준비되지 않았습니다. Docker Desktop이 완전히 시작된 후 다시 실행해주세요.
        pause
        exit /b 1
    )
)
echo  ✓ Docker Desktop 확인 완료

:: ── 2. 설치 디렉토리 생성 ───────────────────────────────────────────
echo [2/4] 설치 준비 중...
set INSTALL_DIR=%USERPROFILE%\music-outo
if not exist "%INSTALL_DIR%" mkdir "%INSTALL_DIR%"
cd /d "%INSTALL_DIR%"

:: docker-compose.prod.yml 다운로드
echo  - docker-compose.prod.yml 다운로드...
curl -sL "https://raw.githubusercontent.com/Eileen42/music-outo/master/docker-compose.prod.yml" -o docker-compose.prod.yml
if %ERRORLEVEL% neq 0 (
    echo  ⚠ 다운로드 실패. 인터넷 연결을 확인해주세요.
    pause
    exit /b 1
)

:: .env 파일 생성 (없을 때만)
if not exist ".env" (
    echo  - 환경 설정 파일 생성...
    (
        echo GEMINI_API_KEYS=[""]
        echo GOOGLE_CLIENT_ID=
        echo GOOGLE_CLIENT_SECRET=
        echo GOOGLE_REDIRECT_URI=http://localhost:8000/api/youtube/callback
        echo STORAGE_PATH=/app/storage
        echo REDIS_URL=redis://redis:6379
    ) > .env
)
echo  ✓ 설치 준비 완료

:: ── 2.5 FFmpeg 설치 (파형 애니메이션 생성에 필요) ────────────────
echo [2.5/4] FFmpeg 확인 중...
where ffmpeg >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo  - FFmpeg 설치 중...
    winget install Gyan.FFmpeg --accept-package-agreements --accept-source-agreements >nul 2>&1
    if %ERRORLEVEL% equ 0 (
        echo  ✓ FFmpeg 설치 완료
    ) else (
        echo  ⚠ FFmpeg 자동 설치 실패. Docker 내장 FFmpeg를 사용합니다.
    )
) else (
    echo  ✓ FFmpeg 이미 설치됨
)

:: ── 3. Docker 이미지 pull & 실행 ────────────────────────────────────
echo [3/4] 프로그램 다운로드 및 실행...
docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml up -d
if %ERRORLEVEL% neq 0 (
    echo  ⚠ 실행 중 오류가 발생했습니다.
    pause
    exit /b 1
)
echo  ✓ 프로그램 실행 완료

:: ── 4. 시작프로그램 등록 ────────────────────────────────────────────
echo [4/4] 자동 시작 등록...
set STARTUP_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup
set STARTUP_BAT=%INSTALL_DIR%\start-music-outo.bat

:: 시작 스크립트 생성
(
    echo @echo off
    echo cd /d "%INSTALL_DIR%"
    echo docker compose -f docker-compose.prod.yml up -d
) > "%STARTUP_BAT%"

:: 시작프로그램 바로가기 생성
powershell -Command "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut('%STARTUP_DIR%\Music Outo.lnk'); $s.TargetPath = '%STARTUP_BAT%'; $s.WorkingDirectory = '%INSTALL_DIR%'; $s.WindowStyle = 7; $s.Save()"
echo  ✓ PC 시작 시 자동 실행됩니다

echo.
echo  ╔═══════════════════════════════════════════╗
echo  ║          설치가 완료되었습니다!           ║
echo  ║                                           ║
echo  ║  브라우저에서 접속하세요:                  ║
echo  ║  http://localhost:3000                    ║
echo  ╚═══════════════════════════════════════════╝
echo.
echo  설치 위치: %INSTALL_DIR%
echo.

:: 브라우저 열기
start http://localhost:3000

pause
