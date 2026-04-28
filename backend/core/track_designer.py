"""
오케스트레이터 — Designer + Lyricist 2~3회 Gemini 호출로 곡 설계 완료.

이전: 4~5회 (analyzer + concept + tracklist + composer + lyricist)
현재: 2회 (instrumental) / 3회 (가사 채널)
- Step 1: design_concept_full → analysis + concept
- Step 2: design_tracks_full → tracklist + suno_prompt (composer 통합)
- Step 3: write_lyrics_batch (가사 채널만)

벤치마크 분석은 제거 (URL 입력 시에도 제대로 동작 안 함). 사용자 입력과 채널 프로필만 사용.
"""
from __future__ import annotations

import logging
from typing import Callable

from agents.designer import designer_agent
from agents.composer import composer_agent
from agents.lyricist import lyricist_agent

logger = logging.getLogger(__name__)


class TrackDesigner:
    async def design_tracks(
        self,
        channel_profile: dict,
        count: int = 20,
        user_input: dict | None = None,
        progress_cb: Callable[[str, str, int], None] | None = None,
    ) -> dict:
        """
        곡 설계 파이프라인.

        progress_cb(phase, message, progress%) — 백그라운드 작업의 진행상황 보고용.

        Returns:
            { "analysis": {...}, "concept": {...}, "tracklist": [...], "tracks": [...] }
        """
        ui = user_input or {}
        has_lyrics = channel_profile.get("has_lyrics", False)
        cb = progress_cb or (lambda *_a, **_kw: None)

        # ── Step 1: 분석 + 컨셉 (1 Gemini call) ──
        cb("step1", f"음악 방향성 + 컨셉 설계 중... ({count}곡)", 25)
        logger.info("[1/2] 분석+컨셉 시작")
        result1 = await designer_agent.design_concept_full(channel_profile, ui, count)
        analysis = result1.get("analysis", {})
        concept = result1.get("concept", {})
        logger.info(f"[1/2] 컨셉: {concept.get('project_name', '(unnamed)')}")

        # ── Step 2: 트랙리스트 + Suno 프롬프트 (1 Gemini call) ──
        cb("step2", f"{count}곡 트랙리스트 + Suno 프롬프트 생성 중...", 60)
        logger.info("[2/2] 트랙+프롬프트 시작")
        tracks = await designer_agent.design_tracks_full(
            concept=concept,
            analysis=analysis,
            channel_profile=channel_profile,
            user_input=ui,
            count=count,
        )
        logger.info(f"[2/2] 완료: {len(tracks)}곡")

        # ── Step 3 (옵션): 가사 (1 Gemini call) ──
        if has_lyrics and tracks:
            cb("step3", f"가사 {len(tracks)}곡 생성 중...", 85)
            logger.info("[3/3] 가사 생성")
            try:
                lyrics_list = await lyricist_agent.write_lyrics_batch(
                    tracks, concept, channel_profile, ui
                )
                lyrics_map = {
                    item.get("index", i + 1): item.get("lyrics", "")
                    for i, item in enumerate(lyrics_list)
                }
                for track in tracks:
                    idx = track.get("index", 0)
                    if idx in lyrics_map and lyrics_map[idx]:
                        track["lyrics"] = lyrics_map[idx]
                logger.info(f"[3/3] 가사: {len(lyrics_list)}곡")
            except Exception as e:
                # 가사 실패해도 곡 설계는 살림
                logger.warning(f"[3/3] 가사 생성 실패 (곡 설계는 유지): {e}")

        return {
            "analysis": analysis,
            "concept": concept,
            "tracklist": tracks,
            "tracks": tracks,
        }

    async def regenerate_single(
        self,
        track: dict,
        channel_profile: dict,
        concept: dict | None = None,
    ) -> dict:
        """개별 곡 재생성 — composer 단독 호출은 유지 (단일 곡이라 부담 없음)."""
        return await composer_agent.regenerate_single(
            track, concept or {}, channel_profile
        )

    async def generate_affirmations(self, count: int, mood: str) -> list[str]:
        return await lyricist_agent.generate_affirmations(count, mood)


track_designer = TrackDesigner()
