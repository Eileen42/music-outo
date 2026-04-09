---
name: capcut-builder
description: 병합 오디오 + 배경이미지 + 파형 + SRT를 조합해 CapCut 프로젝트 파일을 생성한다.
---

# CapCut 프로젝트 빌더 스킬

## 입력
- `project_id`: 프로젝트 경로용
- `project_state`: 프로젝트 전체 상태 dict (tracks, images, metadata, layers 포함)

## 출력
- `storage/projects/{project_id}/outputs/capcut_{project_id}.zip` 또는 `.jianying`
- 폴백: `storage/projects/{project_id}/outputs/draft_content.json`

## 실행 방법

```python
import asyncio, json
from pathlib import Path
from core.capcut_builder import capcut_builder
from core.state_manager import state_manager

async def run(project_id: str):
    # 프로젝트 상태 로드
    project_state = await state_manager.load(project_id)

    output_dir = Path(f"storage/projects/{project_id}/outputs")
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1차: pyJianYingDraft 사용 시도
    result_path = await capcut_builder.build(project_state, output_dir)

    # 폴백: 간단한 JSON 생성
    if result_path is None:
        result_path = await capcut_builder.build_simple_json(project_state, output_dir)
        print(f"⚠️ pyJianYingDraft 없음 → draft_content.json 생성")

    print(f"✅ CapCut 프로젝트 생성 완료 → {result_path}")
    return str(result_path)

asyncio.run(run(project_id))
```

## project_state 필요 필드
```json
{
  "id": "project_id",
  "name": "프로젝트명",
  "tracks": [
    {
      "title": "곡 제목",
      "stored_path": "storage/projects/.../audio/merged.mp3",
      "duration": 3600.0
    }
  ],
  "images": {
    "background": "storage/projects/.../images/candidate_1.png",
    "thumbnail": "storage/projects/.../images/thumbnail_candidate_1.png"
  },
  "metadata": {
    "title": "YouTube 영상 제목"
  },
  "layers": {
    "text_layers": [
      {"text": "채널명", "font_size": 48, "color": "#FFFFFF"}
    ]
  }
}
```

## 생성 로직 (`core/capcut_builder.py`)

### `build()` — pyJianYingDraft 사용
1. 배경 이미지: `images.background` 또는 `images.thumbnail` → `jy.VideoClip`
2. 오디오: `tracks[0].stored_path` → `jy.AudioClip` (병합된 merged.mp3)
3. 텍스트 레이어: `layers.text_layers` 순회 → `jy.TextClip`
4. `draft.save()` → `.jianying` / `.zip` / `_draft_content.json` 탐색 후 반환
5. ImportError 시 `None` 반환 (폴백으로 넘어감)

### `build_simple_json()` — 폴백
- CapCut이 부분적으로 읽을 수 있는 `draft_content.json` 생성
- 트랙별 `path`, `duration`, `title` 포함
- `pyJianYingDraft` 없어도 기본 구조 제공

## 사용자 수동 작업 (스킬 완료 후)
1. ZIP/jianying 파일을 CapCut에서 열기
2. 레이아웃 검수 + 파형 오버레이 위치 조정
3. SRT 자막 레이어 추가 (필요 시)
4. Export: 1920×1080, 30fps, MP4
5. 완성 파일 저장: `storage/projects/{project_id}/outputs/final.mp4`

## 주의사항
- `pyJianYingDraft` 패키지명: `pyjianying` 또는 `jianying` (버전마다 다름)
- `requirements.txt`에 없음 → 별도 `pip install pyjianying` 필요
- 폴백 JSON은 CapCut에서 완전하지 않게 열릴 수 있음
- 오디오는 개별 트랙 아닌 병합된 `audio/merged.mp3` 사용
