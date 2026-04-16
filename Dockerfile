FROM python:3.11-slim

# FFmpeg + Playwright 최소 시스템 의존성만 설치 (브라우저 바이너리는 런타임에)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ffmpeg git \
        # Playwright Firefox 실행에 필요한 최소 시스템 라이브러리
        libnss3 libnspr4 libdbus-1-3 libatk1.0-0t64 \
        libatk-bridge2.0-0t64 libcups2t64 libxcomposite1 \
        libxdamage1 libxfixes3 libxrandr2 libgbm1 \
        libpango-1.0-0 libcairo2 libasound2t64 \
        libxkbcommon0 libatspi2.0-0t64 libgtk-3-0t64 \
    && rm -rf /var/lib/apt/lists/* /usr/share/doc /usr/share/man /tmp/*

WORKDIR /app

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \
    rm -rf /root/.cache /tmp/*

# 브라우저 바이너리는 설치하지 않음 → 런타임 start.sh에서 설치 + 볼륨에 캐시

COPY backend/ .
COPY start_cloud.sh .
RUN chmod +x start_cloud.sh && \
    mkdir -p /app/storage/projects /app/storage/uploads /app/storage/outputs \
             /app/storage/browser_sessions

EXPOSE 8000

CMD ["./start_cloud.sh"]
