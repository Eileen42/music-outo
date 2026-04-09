---
name: youtube-uploader
description: YouTube Data API v3로 최종 MP4를 업로드하고, 썸네일 설정 및 댓글 고정까지 수행한다.
---

# YouTube 업로더 스킬

## 입력
- `project_id`: 프로젝트 경로용
- `video_path`: `storage/projects/{project_id}/outputs/final.mp4`
- `metadata_path`: `storage/projects/{project_id}/metadata.json`
- `thumbnail_path` (선택): `storage/projects/{project_id}/images/thumbnail_candidate_N.png`

## 출력
- YouTube URL: `https://www.youtube.com/watch?v={video_id}`
- `storage/projects/{project_id}/upload_result.json`

```json
{
  "video_id": "YouTubeVideoID",
  "url": "https://www.youtube.com/watch?v=...",
  "uploaded_at": "ISO datetime"
}
```

## 실행 방법

```python
import asyncio, json
from datetime import datetime
from pathlib import Path
from core.youtube_uploader import youtube_uploader

async def run(project_id: str, privacy_status: str = "private"):
    # 파일 경로
    video_path = Path(f"storage/projects/{project_id}/outputs/final.mp4")
    metadata_path = Path(f"storage/projects/{project_id}/metadata.json")

    if not video_path.exists():
        raise FileNotFoundError(f"final.mp4 없음: {video_path}")

    # 인증 확인
    if not youtube_uploader.is_authorized():
        auth_url = youtube_uploader.get_auth_url()
        print(f"🔐 YouTube 인증 필요. 브라우저에서 열기:\n{auth_url}")
        print("인증 후 http://localhost:8000/api/youtube/callback 으로 리다이렉트됩니다.")
        return None

    # 메타데이터 로드
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))

    # 썸네일 경로 탐색
    images_dir = Path(f"storage/projects/{project_id}/images")
    thumbnail_path = None
    for name in ["thumbnail_selected.png", "thumbnail_candidate_1.png"]:
        candidate = images_dir / name
        if candidate.exists():
            thumbnail_path = candidate
            break

    # 업로드
    print(f"📤 업로드 시작: {metadata['title']}")
    result = await youtube_uploader.upload(
        video_path=video_path,
        title=metadata["title"],
        description=metadata["description"],
        tags=metadata.get("tags", []),
        privacy_status=privacy_status,  # "private" | "unlisted" | "public"
        thumbnail_path=thumbnail_path,
        pinned_comment=metadata.get("comment"),
    )

    # 결과 저장
    result["uploaded_at"] = datetime.now().isoformat()
    out_path = Path(f"storage/projects/{project_id}/upload_result.json")
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"✅ 업로드 완료 → {result['url']}")
    return result

asyncio.run(run(project_id))
```

## OAuth 인증 흐름
1. `youtube_uploader.is_authorized()` → `storage/youtube_token.json` 존재 여부 확인
2. 없으면 → `get_auth_url()` 호출 → 브라우저에서 Google 계정 로그인
3. `GET /api/youtube/callback?code=...` → `handle_callback(code)` → 토큰 저장
4. 토큰 만료 시 `refresh_token`으로 자동 갱신 (`_load_credentials()` 내부 처리)

## 업로드 세부 동작 (`core/youtube_uploader.py`)
- `upload()` → `asyncio.to_thread(_upload_sync)` (non-blocking)
- 10MB 청크 재개 가능 업로드 (`MediaFileUpload(resumable=True)`)
- `categoryId: "10"` (Music) 고정
- 제목: 100자 이하로 자동 truncate
- 설명: 5000자 이하로 자동 truncate
- 태그: 최대 30개
- 썸네일: 업로드 후 `thumbnails().set()` 별도 API 호출
- 고정 댓글: `commentThreads().insert()` → `comments().setModerationStatus("published")`

## 주의사항
- `privacy_status` 기본값: `"private"` (검토 후 수동으로 공개 전환 권장)
- OAuth 인증은 최초 1회만 필요 (refresh_token 영구 저장)
- `storage/youtube_token.json` 삭제 시 재인증 필요
- YouTube API 쿼터: 일일 10,000 유닛 (영상 업로드 ~1,600 유닛)
- 인증 API: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` `.env`에 필수
