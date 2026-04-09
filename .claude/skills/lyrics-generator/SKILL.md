---
name: lyrics-generator
description: YouTube 플레이리스트용 가사와 Suno AI 프롬프트를 배치 생성한다. Genspark 브라우저 자동화를 1차로, 실패 시 Gemini API로 자동 전환한다.
---

# 가사 생성 스킬

## 입력
- `channel_concept`: 채널 설정 dict (`storage/channels/{채널명}.json`)
- `count`: 생성할 곡 수 (기본 20)
- `project_id`: 결과 저장 경로용

## 출력
- `storage/projects/{project_id}/lyrics/batch.json`

```json
[
  {
    "title": "곡 제목",
    "lyrics": "전체 가사 (verse/chorus/bridge 구조)",
    "style_prompt": "lo-fi, melancholic, piano, slow tempo",
    "is_instrumental": false
  }
]
```

## 실행 방법

### 방법 1: Genspark 브라우저 자동화 (1차)
```python
import asyncio, json
from pathlib import Path
from browser.browser_manager import BrowserManager
from browser.genspark_automation import GensparkAutomation

async def run(channel_concept: dict, count: int, project_id: str):
    bm = BrowserManager()
    ga = GensparkAutomation(bm)

    results = await ga.generate_lyrics_batch(channel_concept, count=count)

    out_dir = Path(f"storage/projects/{project_id}/lyrics")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "batch.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"✅ {len(results)}곡 가사 생성 완료 → {out_dir}/batch.json")
    await bm.close()
    return results

asyncio.run(run(channel_concept, count, project_id))
```

### 방법 2: Gemini API 직접 (백업 / Genspark 세션 없을 때)
```python
import asyncio, json
from pathlib import Path
from core.gemini_client import gemini_client

PROMPT_TEMPLATE = """
I need {count} original song lyrics for a YouTube music playlist channel.
Channel: {name}
Genre: {genre}
Mood: {mood}
Target audience: {target_audience}
Language: {language}

For each song provide:
1. Title
2. Full lyrics (verse → chorus → verse → chorus → bridge → chorus structure)
3. Suno AI style prompt (comma-separated: genre, mood, instruments, tempo)
4. Whether it's instrumental (true/false)

Respond ONLY with a JSON array:
[{{"title": "...", "lyrics": "...", "style_prompt": "...", "is_instrumental": false}}]
"""

async def run(channel_concept: dict, count: int, project_id: str):
    prompt = PROMPT_TEMPLATE.format(count=count, **channel_concept)
    results = await gemini_client.generate_json(prompt)

    out_dir = Path(f"storage/projects/{project_id}/lyrics")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "batch.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"✅ {len(results)}곡 가사 생성 완료 (Gemini)")
    return results

asyncio.run(run(channel_concept, count, project_id))
```

## 실행 순서
1. Genspark 세션 파일 존재 확인: `storage/browser_sessions/genspark_context.json`
2. 있으면 → 방법 1 실행
3. 없거나 실패하면 → 방법 2 실행
4. 결과 JSON 검증: `title`, `lyrics`, `style_prompt` 필드 존재 여부 확인
5. 빠진 곡은 Gemini로 개별 보충 후 병합

## 주의사항
- Genspark 최초 사용 시 로그인 필요: `await ga.login()`
- `GensparkAutomation._fallback_gemini()`는 내부에서 자동 호출되므로 별도 처리 불필요
- 생성된 가사가 `count`보다 적으면 부족한 수만큼 Gemini로 추가 생성
- `language: "한국어"`이면 한국어 가사, `"영어"`이면 영어 가사 생성됨
- Genspark 응답 대기 최대 120초 (스트리밍 완료 감지)
