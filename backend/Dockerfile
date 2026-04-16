FROM python:3.11-slim

# FFmpeg 설치
RUN apt-get update && apt-get install -y \
    ffmpeg \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Playwright Firefox 바이너리 설치
RUN playwright install firefox && playwright install-deps firefox

COPY . .

# Storage 디렉토리 생성
RUN mkdir -p /app/storage/projects /app/storage/uploads /app/storage/outputs \
             /app/storage/browser_sessions

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
