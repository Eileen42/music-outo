from fastapi import APIRouter, HTTPException

from core.metadata_generator import metadata_generator
from core.state_manager import state_manager

router = APIRouter(prefix="/api/projects/{project_id}/metadata", tags=["메타데이터"])


@router.get("", summary="메타데이터 조회")
async def get_metadata(project_id: str):
    state = state_manager.require(project_id)
    return state.get("metadata", {})


@router.post("/generate", summary="메타데이터 AI 생성 (Gemini)")
async def generate_metadata(project_id: str, body: dict = None):
    """YouTube 제목·설명·태그·고정댓글을 Gemini로 자동 생성합니다. regenerate=true 시 재생성."""
    state = state_manager.require(project_id)

    existing = state.get("metadata", {})
    regenerate = (body or {}).get("regenerate", False)

    if existing.get("title") and not regenerate:
        return existing

    generated = await metadata_generator.generate(state)
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
