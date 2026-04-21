@echo off
chcp 65001 >nul
title Music Outo

cd /d "%LOCALAPPDATA%\Programs\music-outo"

REM ── 0. 최신 설정 파일 가져오기 (docker-compose.prod.yml) ──
REM    네트워크/저장소 이슈 시 조용히 실패해 기존 파일로 진행
curl -fsL "https://raw.githubusercontent.com/Eileen42/music-outo/master/docker-compose.prod.yml" -o docker-compose.prod.yml.new 2>nul
if exist docker-compose.prod.yml.new (
    move /Y docker-compose.prod.yml.new docker-compose.prod.yml >nul 2>&1
)

REM ── Docker CLI 존재 확인 → 없으면 winget 으로 Docker Desktop 자동 설치 ──
where docker >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo.
    echo  처음 실행이네요. Docker Desktop 을 설치합니다 (5~10분 소요).
    echo  설치 중 관리자 권한 요청이 뜨면 "예" 를 눌러주세요.
    echo.
    winget install Docker.DockerDesktop --accept-package-agreements --accept-source-agreements --silent
    if %ERRORLEVEL% neq 0 (
        echo.
        echo  Docker Desktop 자동 설치에 실패했습니다.
        echo  아래 주소에서 수동으로 설치한 뒤 이 아이콘을 다시 실행해주세요:
        echo    https://www.docker.com/products/docker-desktop/
        start https://www.docker.com/products/docker-desktop/
        pause
        exit /b 1
    )
    echo.
    echo  Docker Desktop 설치 완료. PC 재부팅이 필요할 수 있습니다.
    echo  재부팅 후 바탕화면의 "Music Outo" 아이콘을 다시 실행해주세요.
    pause
    exit /b 0
)

REM ── Docker 엔진 실행 중인지 확인, 아니면 Docker Desktop 기동 후 대기 ──
docker info >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo Docker Desktop 시작 중...
    start "" "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    echo Docker 준비 대기 (최대 90초)...
    set /a WAITED=0
    :wait_docker
    timeout /t 3 /nobreak >nul
    docker info >nul 2>&1
    if %ERRORLEVEL% equ 0 goto docker_ready
    set /a WAITED+=3
    if %WAITED% geq 90 (
        echo Docker Desktop 시작에 실패했습니다. 수동으로 Docker Desktop 을 실행한 뒤 다시 시도하세요.
        pause
        exit /b 1
    )
    goto wait_docker
)

:docker_ready

REM 최신 이미지 확인 (Docker Hub에 새 버전 있으면 자동 갱신)
echo 최신 버전 확인 중...
docker compose -f docker-compose.prod.yml pull >nul 2>&1

REM 서비스 시작
echo 시작 중...
docker compose -f docker-compose.prod.yml up -d
if %ERRORLEVEL% neq 0 (
    echo 실행 실패. 로그를 확인해주세요.
    docker compose -f docker-compose.prod.yml logs --tail=30
    pause
    exit /b 1
)

REM 컨테이너가 포트 열 때까지 대기 (최대 30초)
set /a WAITED=0
:wait_port
timeout /t 1 /nobreak >nul
curl -s -o nul http://localhost:3000 && goto ready
set /a WAITED+=1
if %WAITED% geq 30 goto ready
goto wait_port

:ready
start http://localhost:3000

REM ── 마지막: 이 bat 자신도 최신본으로 갱신 (다음 실행부터 반영) ──
REM    실행 중 자기 자신 덮어쓰기가 위험하므로 파일 끝 한 줄 앞에서만 수행
curl -fsL "https://raw.githubusercontent.com/Eileen42/music-outo/master/installer/start-music-outo.bat" -o start-music-outo.bat.new 2>nul
if exist start-music-outo.bat.new (
    move /Y start-music-outo.bat.new start-music-outo.bat >nul 2>&1
)
exit /b 0
