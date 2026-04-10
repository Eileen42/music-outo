import logging

from fastapi import APIRouter, HTTPException

from core.metadata_generator import metadata_generator
from core.state_manager import state_manager
from core.youtube_uploader import youtube_uploader

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/projects/{project_id}/metadata", tags=["메타데이터"])


@router.get("", summary="메타데이터 조회")
async def get_metadata(project_id: str):
    state = state_manager.require(project_id)
    return state.get("metadata", {})


@router.post("/generate", summary="메타데이터 AI 생성 (Gemini)")
async def generate_metadata(project_id: str, body: dict = None):
    """YouTube 제목·설명·태그·고정댓글을 Gemini로 자동 생성합니다.
    regenerate=true 시 재생성. instruction으로 사용자 지시사항 전달."""
    state = state_manager.require(project_id)

    existing = state.get("metadata", {})
    body = body or {}
    regenerate = body.get("regenerate", False)
    instruction = body.get("instruction", "")

    if existing.get("title") and not regenerate:
        return existing

    # 채널 연결된 경우 기존 영상 메타데이터 가져오기
    channel_id = state.get("channel_id", "")
    channel_videos = []
    if channel_id and youtube_uploader.is_authorized(channel_id):
        try:
            channel_videos = await youtube_uploader.fetch_recent_videos(channel_id, max_results=5)
        except Exception as e:
            logger.warning(f"채널 영상 가져오기 실패: {e}")

    generated = await metadata_generator.generate(state, instruction=instruction, channel_videos=channel_videos)
    state_manager.update(project_id, {"metadata": generated})
    return generated


@router.put("", summary="메타데이터 수동 수정")
async def update_metadata(project_id: str, body: dict):
    """title / description / tags / comment 수정 가능."""
    state_manager.require(project_id)

    allowed = {"title", "description", "tags", "comment"}
    updates = {k: v for k, v in body.items() if k in allowed}
    if not updates:
        raise HTTPException(400, f"수정 가능한 필드: {allowed}")

    state = state_manager.update(project_id, {"metadata": updates})
    return state["metadata"]
