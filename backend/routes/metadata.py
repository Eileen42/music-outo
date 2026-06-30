import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException

from core.gemini_client import gemini_client
from core.metadata_generator import metadata_generator
from core.state_manager import state_manager

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
    meta = state.get("metadata", {}) or {}
    # _spec / _spec_key 등 내부 캐시는 응답에서 제외
    return {k: v for k, v in meta.items() if not k.startswith("_")}


@router.post("/generate", summary="메타데이터 AI 생성 (Gemini)")
async def generate_metadata(project_id: str, body: dict = None):
    """YouTube 제목·설명·태그·고정댓글을 Gemini로 자동 생성합니다.

    body 필드:
      - regenerate (bool): 기존 메타데이터가 있어도 재생성
      - instruction (str): 자유 지시사항 (예: "제목은 영어로")
      - language (str): "ko" | "en"
      - template (dict | str): ★ 신규 — 사용자 참고 템플릿
        · dict 형식 권장: {"title": "...", "description": "...", "tags": "...", "comment": "..."}
        · str 형식도 허용: 통째로 던지면 모든 항목에 참고로 전달
        · 비어있거나 누락 시 → 기존 동작 (자동 설계만)
    """
    state = state_manager.require(project_id)

    existing = state.get("metadata", {})
    body = body or {}
    regenerate = body.get("regenerate", False)
    instruction = body.get("instruction", "")
    language = body.get("language", "ko")
    template = body.get("template", "") or ""
    if language not in ("ko", "en"):
        language = "ko"

    if existing.get("title") and not regenerate:
        return existing

    try:
        generated = await metadata_generator.generate(
            state,
            instruction=instruction,
            channel_videos=[],
            language=language,
            template=template,
        )
    except Exception as e:
        logger.error(f"메타데이터 생성 실패: {e}", exc_info=True)
        raise HTTPException(500, f"메타데이터 생성 실패: {str(e)}")

    # _spec / _spec_key 는 다음 재생성 시 designer 스킵용 캐시 — 디스크엔 저장하되
    # 프론트 응답에선 제외해 노이즈/페이로드 절감.
    state_manager.update(project_id, {"metadata": generated})
    public = {k: v for k, v in generated.items() if not k.startswith("_")}
    return public


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
