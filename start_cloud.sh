#!/bin/bash
# Railway 클라우드 시작 스크립트
# Playwright 브라우저를 볼륨에 캐시하여 재배포 시에도 유지

BROWSER_DIR="/app/storage/.playwright"

if [ ! -d "$BROWSER_DIR" ] || [ -z "$(ls -A "$BROWSER_DIR" 2>/dev/null)" ]; then
    echo "[startup] Playwright Firefox 브라우저 설치 중 (첫 실행, 1회만)..."
    PLAYWRIGHT_BROWSERS_PATH="$BROWSER_DIR" playwright install firefox
    echo "[startup] 브라우저 설치 완료."
else
    echo "[startup] Playwright 브라우저 캐시 사용: $BROWSER_DIR"
fi

export PLAYWRIGHT_BROWSERS_PATH="$BROWSER_DIR"

echo "[startup] 서버 시작: uvicorn main:app --host 0.0.0.0 --port 8000"
exec uvicorn main:app --host 0.0.0.0 --port 8000
