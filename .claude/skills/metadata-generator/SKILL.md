---
name: metadata-generator
description: Gemini로 YouTube 영상의 제목·설명·태그(최대 30개)·고정댓글을 자동 생성한다.
---

# 메타데이터 생성 스킬

## 입력
- `project_id`: 프로젝트 경로용
- `project_state`: 프로젝트 상태 dict (tracks, playlist_title, name 포함)

## 출력
- `storage/projects/{project_id}/metadata.json`

```json
{
  "title": "YouTube 영상 제목 (100자 이내)",
  "description": "영상 설명 (소개 + 트랙리스트 + 구독 유도)",
  "tags": ["태그1", "태그2", "..."],
  "comment": "고정 댓글 (트랙리스트 + 문구)"
}
```

## 실행 방법

```python
import asyncio, json
from pathlib import Path
from core.metadata_generator import metadata_generator
from core.state_manager import state_manager

async def run(project_id: str):
    project_state = await state_manager.load(project_id)

    metadata = await metadata_generator.generate(project_state)

    out_path = Path(f"storage/projects/{project_id}/metadata.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"✅ 메타데이터 생성 완료 → {out_path}")
    return metadata

asyncio.run(run(project_id))
```

## 생성 로직 (`core/metadata_generator.py`)

### `generate(project_state)` — 4개 필드 순차 생성

| 메서드 | 입력 | 출력 | 프롬프트 소스 |
|--------|------|------|--------------|
| `_gen_title()` | playlist_title, track_list | 제목 (100자 이내) | `templates/prompts/metadata_title.txt` 또는 인라인 |
| `_gen_description()` | title, track_list | 설명 (소개+리스트+유도) | `metadata_description.txt` 또는 인라인 |
| `_gen_tags()` | playlist_title, track_list | 태그 최대 30개 (JSON 배열) | 인라인 |
| `_gen_comment()` | playlist_title, track_list | 고정 댓글 (500자 이내) | `metadata_comment.txt` 또는 인라인 |

### 템플릿 파일 우선 사용
- `backend/templates/prompts/metadata_title.txt` 존재 시 해당 템플릿 사용
- 없으면 인라인 프롬프트로 폴백
- 템플릿 내 `{{project_name}}`, `{{playlist_title}}`, `{{track_list}}`, `{{track_count}}` 치환

## project_state 필요 필드
```json
{
  "name": "프로젝트명",
  "playlist_title": "플레이리스트 제목",
  "tracks": [
    {"title": "Track 1", "artist": "Suno AI"},
    {"title": "Track 2", "artist": "Suno AI"}
  ]
}
```

## 주의사항
- 태그 파싱 실패 시 빈 배열 반환 (예외 발생 안 함)
- 제목은 YouTube 100자 제한, 설명은 5000자 제한 (업로드 시 자동 truncate)
- 생성 후 `localhost:3000` 메타데이터 화면에서 사용자 검토 필요
- 최종 확인된 메타데이터는 `project_state["metadata"]`에도 저장
