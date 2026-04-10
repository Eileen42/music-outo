from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import RedirectResponse

from core.state_manager import state_manager
from core.youtube_uploader import youtube_uploader
from models.schemas import YouTubeUploadRequest

router = APIRouter(prefix="/api/youtube", tags=["YouTube"])


@router.get("/status", summary="YouTube 인증 상태 확인")
async def get_auth_status():
    return {"authorized": youtube_uploader.is_authorized()}


@router.get("/auth", summary="YouTube OAuth 인증 시작")
async def start_auth():
    """반환된 auth_url을 브라우저에서 열어 Google 계정으로 로그인하세요."""
    url = youtube_uploader.get_auth_url()
    return {"auth_url": url}


@router.get("/callback", summary="OAuth 콜백 (자동 호출)")
async def oauth_callback(request: Request, code: str):
    try:
        youtube_uploader.handle_callback(code)
        # 요청의 Referer 또는 Origin으로 리다이렉트 (Vercel/로컬 모두 지원)
        origin = request.headers.get("referer", "").split("?")[0].rstrip("/")
        if not origin:
            origin = "http://localhost:3000"
        return RedirectResponse(url=f"{origin}/?youtube_auth=success")
    except Exception as e:
        raise HTTPException(500, f"OAuth 실패: {e}")


@router.post("/revoke", summary="YouTube 인증 해제")
async def revoke_auth():
    youtube_uploader.revoke()
    return {"status": "인증 해제됨"}


@router.post("/upload/{project_id}", summary="YouTube 업로드")
async def upload_video(
    project_id: str,
    body: YouTubeUploadRequest,
    background_tasks: BackgroundTasks,
):
    """빌드된 MP4를 YouTube에 업로드합니다. privacy_status: private / unlisted / public"""
    if not youtube_uploader.is_authorized():
        raise HTTPException(401, "YouTube 인증이 필요합니다. /api/youtube/auth 를 먼저 호출하세요.")

    state = state_manager.require(project_id)
    build = state.get("build", {})

    if not build.get("output_file"):
        raise HTTPException(400, "빌드된 영상이 없습니다. 먼저 빌드를 실행하세요.")

    state_manager.update(project_id, {"status": "uploading"})
    background_tasks.add_task(_run_upload, project_id, body.privacy_status)
    return {"status": "업로드 시작됨"}


@router.get("/upload/{project_id}/status", summary="업로드 상태 확인")
async def get_upload_status(project_id: str):
    state = state_manager.require(project_id)
    return {
        "status": state.get("status"),
        "youtube": state.get("youtube", {}),
    }


# ─── background task ─────────────────────────────────────────────────────────

async def _run_upload(project_id: str, privacy_status: str):
    state = state_manager.get(project_id)
    if not state:
        return

    build = state.get("build", {})
    metadata = state.get("metadata", {})
    images = state.get("images", {})

    video_path = Path(build["output_file"])
    thumbnail_path = images.get("thumbnail")

    try:
        result = await youtube_uploader.upload(
            video_path=video_path,
            title=metadata.get("title") or state.get("name", ""),
            description=metadata.get("description") or "",
            tags=metadata.get("tags") or [],
            privacy_status=privacy_status,
            thumbnail_path=Path(thumbnail_path) if thumbnail_path else None,
            pinned_comment=metadata.get("comment"),
        )

        from datetime import datetime
        state_manager.update(
            project_id,
            {
                "status": "uploaded",
                "youtube": {
                    "video_id": result["video_id"],
                    "url": result["url"],
                    "uploaded_at": datetime.utcnow().isoformat(),
                },
            },
        )
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"YouTube 업로드 실패: {e}")
        state_manager.update(project_id, {"status": "ready"})
