# YouTube Playlist Video Automator

로컬 1인 사용 도구. YouTube 플레이리스트용 음악 영상 자동 생성기.

## Architecture
- Backend: FastAPI (port 8000) — Python 3.11
- Frontend: React + Vite (port 3000)
- Redis: WebSocket pub/sub (port 6379)
- Storage: JSON 파일 기반 (`storage/projects/{id}/state.json`)

## Key Rules
- DB 없음. 상태는 JSON 파일로 저장
- 인증 없음. user_id는 항상 "default"
- 크레딧/플랜 시스템 없음
- Celery 없음. 무거운 작업은 BackgroundTasks
- 핵심 로직은 반드시 `core/` 모듈에 클래스로 분리

## Dev Start
```bash
# Docker
docker-compose up --build

# Local
cd backend && uvicorn main:app --reload --port 8000
cd frontend && npm run dev
```

## Storage Structure
```
storage/
  projects/{id}/
    state.json      ← 프로젝트 상태 전체
    audio/          ← 업로드된 오디오 파일
    images/         ← 이미지
    outputs/        ← 빌드 결과물 (영상, CapCut 파일)
```

## Workflow (7 Steps)
1. Project Setup — 이름, 플레이리스트 제목
2. Track Editor — 오디오 업로드, 순서 조정
3. Image Selector — 이미지 업로드 / AI 카테고리 분류
4. Metadata Preview — Gemini로 제목/설명/태그 생성
5. Layer Preview — CapCut 레이어 설정
6. Build & Download — 빌드 트리거, 결과 다운로드
7. YouTube Upload — OAuth + 업로드

## SaaS 전환 시 → docs/PHASE2_SAAS.md
