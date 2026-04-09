---
name: suno-automation
description: Suno 웹사이트에서 곡을 배치 생성하고 MP3를 다운로드한다. Playwright Firefox 브라우저 자동화 사용.
---

# Suno 곡 생성 스킬

## 입력
- `lyrics_batch`: `storage/projects/{project_id}/lyrics/batch.json` 의 곡 목록
- `project_id`: 결과 저장 경로용

## 출력
- `storage/projects/{project_id}/tracks/{MMDD}_{제목}.mp3` (각 곡)
- `storage/projects/{project_id}/tracks/results.json` (생성 결과 요약)

```json
[
  {
    "title": "곡 제목",
    "suno_id": "UUID",
    "file_path": "storage/projects/.../tracks/0406_제목.mp3",
    "status": "completed"
  }
]
```

## 실행 방법

```python
import asyncio, json
from pathlib import Path
from browser.browser_manager import BrowserManager
from browser.suno_automation import SunoAutomation

async def run(project_id: str):
    lyrics_path = Path(f"storage/projects/{project_id}/lyrics/batch.json")
    songs = json.loads(lyrics_path.read_text(encoding="utf-8"))

    output_dir = f"storage/projects/{project_id}/tracks"

    bm = BrowserManager()
    sa = SunoAutomation(bm)

    # 크레딧 확인
    credits = await sa.get_remaining_credits()
    if 0 <= credits < len(songs):
        print(f"⚠️ 크레딧 부족: {credits}개 남음, {len(songs)}곡 필요")
        # 크레딧 내 범위만 처리
        songs = songs[:credits]

    results = await sa.batch_create_and_download(songs, output_dir)

    out_path = Path(output_dir) / "results.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    completed = [r for r in results if r["status"] == "completed"]
    print(f"✅ {len(completed)}/{len(results)}곡 생성 완료 → {output_dir}")
    await bm.close()
    return results

asyncio.run(run(project_id))
```

## 실행 순서
1. Suno 세션 파일 확인: `storage/browser_sessions/suno_context.json`
2. 없으면 → `await sa.login()` 으로 수동 로그인 (Facebook 또는 이메일 — Google 불가)
3. `get_remaining_credits()` 로 크레딧 확인
4. `batch_create_and_download(songs, output_dir)` 실행
5. 각 곡: `create_song()` → 180초 대기 → `download_song()` → 30초 대기 후 다음 곡

## 파일명 규칙
- `{MMDD}_{제목}.mp3` (예: `0406_Midnight_Rain.mp3`)
- 제목의 특수문자(`\/:*?"<>|`)는 `_`로 대체

## 주의사항
- Google 로그인은 Firefox에서도 차단 가능 → Facebook 또는 이메일/비밀번호 로그인 사용
- 곡 생성 최대 대기: 180초, 곡 간 쿨다운: 30초
- 에러 시 스크린샷 저장: `storage/browser_sessions/suno_error_{tag}_{ts}.png`
- 크레딧 조회 실패(-1 반환) 시 크레딧 제한 없이 진행
- `status: "download_failed"` 인 곡은 `file_path` 가 빈 문자열 → 수동 처리 필요
