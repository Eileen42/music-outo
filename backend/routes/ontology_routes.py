"""
온톨로지 API 라우트.

채널 온톨로지 조회/생성/재생성 + 채널 생성 시 자동 생성 훅.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from core.ontology import ontology
from core.channel_profile import channel_profile

router = APIRouter(prefix="/api/ontology", tags=["ontology"])


@router.get("", summary="전체 채널 온톨로지 목록")
async def list_ontologies():
    """저장된 모든 채널 온톨로지 목록 반환."""
    return ontology.list_channel_ontologies()


@router.get("/{channel_id}", summary="채널 온톨로지 조회")
async def get_ontology(channel_id: str):
    """
    채널 온톨로지 조회. 없으면 채널 프로필에서 자동 생성.
    """
    # 이미 저장된 온톨로지가 있으면 바로 반환
    existing = ontology.load_channel_ontology(channel_id)
    if existing:
        return existing

    # 없으면 채널 프로필에서 자동 생성
    try:
        ch = channel_profile.load(channel_id)
    except FileNotFoundError:
        raise HTTPException(404, f"채널을 찾을 수 없습니다: {channel_id}")

    return ontology.generate_channel_ontology(ch)


@router.post("/{channel_id}/generate", summary="채널 온톨로지 재생성")
async def regenerate_ontology(channel_id: str):
    """
    채널 프로필 기반으로 온톨로지를 새로 생성 (기존 덮어쓰기).
    채널 설정이 변경된 후 호출.
    """
    try:
        ch = channel_profile.load(channel_id)
    except FileNotFoundError:
        raise HTTPException(404, f"채널을 찾을 수 없습니다: {channel_id}")

    result = ontology.generate_channel_ontology(ch)
    return {"status": "generated", "channel": channel_id, "categories": list(result["categories"].keys())}


@router.get("/{channel_id}/resolve", summary="채널 속성 실시간 해석")
async def resolve_channel(channel_id: str):
    """
    온톨로지 엔진으로 채널 속성을 실시간 해석.
    (저장된 온톨로지가 아닌 현재 채널 프로필 기준)
    """
    try:
        ch = channel_profile.load(channel_id)
    except FileNotFoundError:
        raise HTTPException(404, f"채널을 찾을 수 없습니다: {channel_id}")

    resolved = ontology.resolve(ch)
    return resolved.to_dict()


@router.get("/moods/list", summary="사용 가능한 무드 목록")
async def list_moods():
    return {"moods": ontology.list_moods()}
