import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException

from core.gemini_client import gemini_client
from core.metadata_generator import metadata_generator
from core.state_manager import state_manager
from core.youtube_uploader import youtube_uploader

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/projects/{project_id}/metadata", tags=["메타데이터"])


@router.get("/read-thumbnail", summary="썸네일 텍스트 OCR (Gemini Vision)")
async def read_thumbnail_text(project_id: str):
    """썸네일 이미지에서 텍스트를 읽어 반환합니다."""
    state = state_manager.require(project_id)
    images = state.get("images", {})
    thumb_path = images.get("thumbnail")
    if not thumb_path:
        return {"text": ""}

    p = Path(thumb_path)
    if not p.exists():
        return {"text": ""}

    try:
        import asyncio
        from google import genai
        from google.genai import types as genai_types

        image_bytes = p.read_bytes()
        mime = "image/png" if p.suffix.lower() == ".png" else "image/jpeg"

        prompt = (
            "이 YouTube 썸네일 이미지에서 텍스트를 모두 읽어서 그대로 반환해줘. "
            "텍스트만 반환하고, 설명이나 마크다운은 붙이지 마."
        )

        key_idx, key = gemini_client._get_available_key()
        client = genai.Client(api_key=key)

        response = await asyncio.to_thread(
            client.models.generate_content,
            model="gemini-2.5-flash",
            contents=[
                genai_types.Content(parts=[
                    genai_types.Part.from_text(text=prompt),
                    genai_types.Part.from_bytes(data=image_bytes, mime_type=mime),
                ]),
            ],
        )
        text = (response.text or "").strip()
        return {"text": text}
    except Exception as e:
        logger.warning(f"썸네일 OCR 실패: {e}")
        return {"text": ""}


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
            logger.info(f"채널 영상 {len(channel_videos)}개 참조 로드 완료")
        except Exception as e:
            logger.warning(f"채널 영상 가져오기 실패 (무시하고 계속): {e}")

    try:
        generated = await metadata_generator.generate(state, instruction=instruction, channel_videos=channel_videos)
    except Exception as e:
        logger.error(f"메타데이터 생성 실패: {e}", exc_info=True)
        raise HTTPException(500, f"메타데이터 생성 실패: {str(e)}")

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
