# Phase 2: SaaS 전환 할 일 목록

현재는 로컬 1인 사용 도구. 아래는 SaaS로 전환 시 해야 할 작업 목록.

---

## 인증

- [ ] NextAuth.js 또는 Supabase Auth 도입
- [ ] `user_id: "default"` → 실제 사용자 ID로 교체
- [ ] Google OAuth 멀티 사용자 토큰 분리 저장

## 데이터베이스

- [ ] `state.json` → PostgreSQL / Supabase 테이블로 마이그레이션
- [ ] 프로젝트, 트랙, 메타데이터 각각 테이블 분리
- [ ] 파일 경로 → S3 / R2 URL로 교체

## 파일 스토리지

- [ ] 로컬 `storage/` → AWS S3 / Cloudflare R2 / Supabase Storage
- [ ] 업로드 → presigned URL 방식으로 전환
- [ ] CDN 연동

## 백그라운드 작업

- [ ] FastAPI BackgroundTasks → Celery + Redis 또는 BullMQ
- [ ] 작업 큐 + 상태 추적 (processing, done, failed)
- [ ] 재시도 로직

## 크레딧/플랜

- [ ] 플랜 정의 (Free / Pro / Business)
- [ ] Gemini API 사용량 추적
- [ ] Stripe 연동

## 인프라

- [ ] Docker → Kubernetes / Railway / Render
- [ ] 백엔드 수평 확장
- [ ] FFmpeg 작업 → 전용 워커 분리

## 모니터링

- [ ] Sentry 에러 추적
- [ ] 빌드 성공/실패 알림 (이메일, Slack)
- [ ] 사용량 대시보드

## 보안

- [ ] Rate limiting
- [ ] 파일 크기 제한 (현재 무제한)
- [ ] 파일 타입 검증 강화

---

## 코드 변경 포인트

| 현재 (로컬) | SaaS |
|---|---|
| `user_id = "default"` | JWT에서 추출 |
| `storage/projects/{id}/state.json` | DB 테이블 |
| `BackgroundTasks` | Celery task |
| 로컬 파일 서빙 | S3 presigned URL |
| 단일 YouTube OAuth 토큰 | 사용자별 토큰 |
| Gemini 키 .env | 키 풀 + DB 관리 |
