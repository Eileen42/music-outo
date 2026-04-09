# SKILLS.md — 개발 요청 파일

이 파일에 개발 요청을 작성하고 Claude Code에서 `/dev` 라고 말하면
에이전트가 구현 → QA(`qa/test_workflow.py`) 실행 → 결과 보고합니다.

## 사용법

1. `## [요청]` 섹션에 새 항목 추가
2. Claude Code 채팅에서 `/dev` 또는 `SKILLS.md 개발해줘` 입력
3. 에이전트가 구현 후 QA 실행, 이 파일을 `## [완료]`로 업데이트

## 요청 포맷

```
### SKILL-XXX: 제목
**우선순위**: high / medium / low
**영역**: frontend / backend / both
**설명**:
  - 구체적으로 무엇을 만들어야 하는지
**완료 조건**:
  - QA에서 확인할 항목들
  - 사용자가 확인할 UI 동작
```

## QA 실행 명령

```bash
# 전체 워크플로우 테스트
PYTHONIOENCODING=utf-8 python qa/test_workflow.py

# 테스트 후 프로젝트 보존
PYTHONIOENCODING=utf-8 python qa/test_workflow.py --keep

# 다른 서버 대상
PYTHONIOENCODING=utf-8 python qa/test_workflow.py --base-url http://localhost:8000
```

---

## QA 규칙 (필수)

모든 프론트엔드 변경 후 아래 QA를 **반드시** 수행한 뒤 사용자에게 보고:

1. **TypeScript 빌드**: `npx tsc --noEmit` 에러 0개
2. **서버 확인**: Backend(8000) + Frontend(3000) 응답 OK
3. **Playwright 브라우저 테스트**: 실제 브라우저에서 변경된 UI 확인
   - 페이지 이동, 버튼 클릭, 데이터 표시 확인
   - 에러 발생 시 콘솔 로그 캡처
   - 스크린샷 저장 (`storage/debug/`)
4. **API 테스트**: 변경된 엔드포인트 curl로 확인
5. **에러 잔존 확인**: 모든 프로젝트의 stale 에러 초기화

```python
# Playwright QA 예시
from playwright.async_api import async_playwright
async with async_playwright() as p:
    browser = await p.chromium.launch(headless=False)
    page = await browser.new_page()
    await page.goto('http://localhost:3000')
    # UI 확인 + 스크린샷
    await page.screenshot(path='storage/debug/qa.png')
```

---

## [요청]

<!-- 새 개발 요청을 여기에 추가하세요 -->

---

## [진행 중]

<!-- 에이전트가 작업 중인 항목 -->

---

## [완료]

<!-- 구현 + QA 통과 항목 -->

### SKILL-001: 업로드 에러 수정 + 대량 등록
**영역**: backend + frontend
**완료**: 2026-04-06
**결과**: QA 23/23 통과
- pydub(ffmpeg 필요) → mutagen(순수 Python)으로 메타데이터 추출 교체
- 드래그앤드롭 다중 파일 업로드 구현
- 반복 설정(횟수/목표 시간) 기능 추가

### SKILL-002: 이미지 설정 AI 기능 (레퍼런스 분위기 분석 → 이미지 생성)
**영역**: backend + frontend
**완료**: 2026-04-06
**결과**: QA 23/24 통과 (AI 엔드포인트 1건 SKIP — Gemini API 키 미설정 환경)
- Gemini Vision(`gemini-2.0-flash`)으로 레퍼런스 이미지 분위기 JSON 분석
- Imagen 3(`imagen-3.0-generate-002`)으로 동일 분위기 새 이미지 생성 (무료: 1~2장/일)
- ImageSelector.tsx 3탭 리디자인: 직접 업로드 / AI 분위기 분석 / AI 이미지 생성
- QA에 `/analyze`, `/generate` 엔드포인트 테스트 추가 (API 키 없으면 graceful SKIP)

### SKILL-000: 초기 UI 한국어화 및 UX 개선
**영역**: frontend
**완료**: 2026-04-06
**결과**: QA 23/23 통과
- App.tsx 사이드바 단계 번호/설명/완료 표시
- ProjectSetup 상태 한국어화, 진행 뱃지
- TrackEditor/BuildDownload/YouTubeUpload 안내문구 개선
