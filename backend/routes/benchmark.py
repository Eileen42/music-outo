from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.benchmark_analyzer import benchmark_analyzer
from core.channel_profile import channel_profile

router = APIRouter(prefix="/api/benchmark", tags=["benchmark"])


# ──────────────────────────── schemas ────────────────────────────

class AnalyzeRequest(BaseModel):
    youtube_url: str
    channel_id: str


# ──────────────────────────── routes ────────────────────────────

@router.post("/analyze", summary="벤치마크 분석 실행")
async def analyze_benchmark(body: AnalyzeRequest):
    """
    YouTube 영상 분석 후 채널 프로필 benchmark_history에 추가.
    분석 결과 전체를 반환.
    """
    try:
        result = await benchmark_analyzer.analyze(body.youtube_url)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"분석 실패: {e}")

    # 채널 프로필에 히스토리 추가 (채널이 없으면 무시)
    try:
        channel_profile.add_benchmark(body.channel_id, result)
    except FileNotFoundError:
        raise HTTPException(404, f"채널을 찾을 수 없습니다: {body.channel_id}")

    return result


@router.get("/history/{channel_id}", summary="채널 벤치마크 히스토리")
async def get_benchmark_history(channel_id: str):
    """해당 채널의 벤치마크 분석 히스토리 목록."""
    try:
        profile = channel_profile.load(channel_id)
        return profile.get("benchmark_history", [])
    except FileNotFoundError:
        raise HTTPException(404, f"채널을 찾을 수 없습니다: {channel_id}")
