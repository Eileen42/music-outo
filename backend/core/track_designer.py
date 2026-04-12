"""
오케스트레이터 — 작곡/작사 에이전트를 조율하여 곡 목록을 설계한다.

흐름:
  1. composer_agent → 프로젝트 컨셉 확정
  2. composer_agent → 개별 곡 Suno 프롬프트 설계
  3. lyricist_agent → 가사 생성 (has_lyrics 채널만)
"""
from __future__ import annotations

import logging

from agents.composer import composer_agent
from agents.lyricist import lyricist_agent

logger = logging.getLogger(__name__)


class TrackDesigner:
    """오케스트레이터: 에이전트들을 조율하여 곡 설계 파이프라인 실행."""

    async def design_tracks(
        self,
        channel_profile: dict,
        benchmark: dict | None,
        count: int = 20,
        user_input: dict | None = None,
    ) -> dict:
        """
        전체 곡 설계 파이프라인.

        1. 컨셉 결정 (composer)
        2. 곡별 Suno 프롬프트 (composer)
        3. 가사 생성 (lyricist) — has_lyrics 채널만
        """
        ui = user_input or {}
        has_lyrics = channel_profile.get("has_lyrics", False)

        # ── Step 1: 프로젝트 컨셉 확정 (작곡 에이전트) ──
        concept = await composer_agent.design_concept(
            channel_profile, benchmark, count, ui
        )
        logger.info(f"[orchestrator] 컨셉 확정: {concept.get('project_name', '')}")

        # ── Step 2: 개별 곡 설계 (작곡 에이전트) ──
        tracks = await composer_agent.design_tracks(
            concept, channel_profile, count, ui
        )
        logger.info(f"[orchestrator] 곡 설계 완료: {len(tracks)}곡")

        # ── Step 3: 가사 생성 (작사 에이전트) — 가사 채널만 ──
        if has_lyrics and tracks:
            try:
                lyrics_list = await lyricist_agent.write_lyrics_batch(
                    tracks, concept, channel_profile, ui
                )
                # 가사를 각 트랙에 매칭
                lyrics_map = {item.get("index", i + 1): item.get("lyrics", "") for i, item in enumerate(lyrics_list)}
                for track in tracks:
                    idx = track.get("index", 0)
                    if idx in lyrics_map and lyrics_map[idx]:
                        track["lyrics"] = lyrics_map[idx]
                logger.info(f"[orchestrator] 가사 생성 완료: {len(lyrics_list)}곡")
            except Exception as e:
                logger.warning(f"[orchestrator] 가사 생성 실패 (곡 설계는 유지): {e}")

        return {"concept": concept, "tracks": tracks}

    async def regenerate_single(self, track: dict, channel_profile: dict, concept: dict | None = None) -> dict:
        """개별 곡 재생성 (작곡 에이전트 호출)."""
        return await composer_agent.regenerate_single(track, channel_profile, concept)

    async def generate_affirmations(self, count: int, mood: str) -> list[str]:
        """확언 문구 생성 (작사 에이전트 호출)."""
        return await lyricist_agent.generate_affirmations(count, mood)


# ──────────────────────────── 싱글톤 ────────────────────────────

track_designer = TrackDesigner()
