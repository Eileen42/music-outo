FROM python:3.11-slim

# 단일 RUN으로 레이어 최소화 + 캐시 완전 제거
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ffmpeg \
        git \
    && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

WORKDIR /app

# 의존성 설치 (캐시 활용)
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Playwright: Chromium 대신 가벼운 Firefox만 + deps를 한 레이어에서 정리
RUN playwright install firefox && \
    playwright install-deps firefox && \
    rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/* /root/.cache

# 백엔드 코드 복사 (backend/ → /app/)
COPY backend/ .

# Storage 디렉토리 생성
RUN mkdir -p /app/storage/projects /app/storage/uploads /app/storage/outputs \
             /app/storage/browser_sessions

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
