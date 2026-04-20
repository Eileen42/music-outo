@echo off
chcp 65001 >nul
title Music Outo

cd /d "%USERPROFILE%\music-outo"

REM Docker 실행 중인지 확인, 아니면 Docker Desktop 시작하고 대기
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
        echo Docker Desktop 시작에 실패했습니다. 수동으로 Docker Desktop을 실행한 뒤 다시 시도하세요.
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
exit /b 0
