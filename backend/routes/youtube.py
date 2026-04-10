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

    # output_file이 없으면 outputs/ 폴더에서 MP4 자동 탐색
    output_file = build.get("output_file")
    if not output_file or not Path(output_file).exists():
        project_dir = state_manager.project_dir(project_id)
        outputs_dir = project_dir / "outputs"
        mp4s = sorted(outputs_dir.glob("*.mp4"), key=lambda f: f.stat().st_mtime, reverse=True) if outputs_dir.exists() else []
        if mp4s:
            output_file = str(mp4s[0])
            state_manager.update(project_id, {"build": {**build, "output_file": output_file}})
        else:
            raise HTTPException(400, f"영상 파일이 없습니다. outputs 폴더에 MP4를 넣어주세요: {outputs_dir}")

    state_manager.update(project_id, {"status": "uploading"})
    background_tasks.add_task(_run_upload, project_id, body.privacy_status)
    return {"status": "업로드 시작됨"}


@router.post("/open-studio/{project_id}", summary="YouTube Studio 업로드 페이지 열기")
async def open_studio(project_id: str):
    """브라우저에서 YouTube Studio 업로드 페이지를 열고 메타데이터 반환."""
    import os
    state = state_manager.require(project_id)
    metadata = state.get("metadata", {})
    build = state.get("build", {})

    # outputs 폴더에서 MP4 찾기
    project_dir = state_manager.project_dir(project_id)
    outputs_dir = project_dir / "outputs"
    mp4s = sorted(outputs_dir.glob("*.mp4"), key=lambda f: f.stat().st_mtime, reverse=True) if outputs_dir.exists() else []

    # YouTube Studio 업로드 페이지 열기
    os.startfile("https://studio.youtube.com/channel/UC/videos/upload?d=ud")

    # outputs 폴더도 열기 (파일 드래그용)
    if outputs_dir.exists():
        os.startfile(str(outputs_dir))

    return {
        "status": "opened",
        "title": metadata.get("title", ""),
        "description": metadata.get("description", ""),
        "tags": metadata.get("tags", []),
        "comment": metadata.get("comment", ""),
        "video_file": str(mp4s[0]) if mp4s else None,
        "outputs_folder": str(outputs_dir),
    }


@router.get("/upload/{project_id}/status", summary="업로드 상태 확인")
async def get_upload_status(project_id: str):
    state = state_manager.require(project_id)
    return {
        "status": state.get("status"),
        "youtube": state.get("youtube", {}),
        "upload_progress": state.get("upload_progress", 0),
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

    def on_progress(pct: int):
        state_manager.update(project_id, {"upload_progress": pct})

    try:
        result = await youtube_uploader.upload(
            video_path=video_path,
            title=metadata.get("title") or state.get("name", ""),
            description=metadata.get("description") or "",
            tags=metadata.get("tags") or [],
            privacy_status=privacy_status,
            thumbnail_path=Path(thumbnail_path) if thumbnail_path else None,
            pinned_comment=metadata.get("comment"),
            progress_cb=on_progress,
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
