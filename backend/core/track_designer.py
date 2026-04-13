"""
오케스트레이터 — 4개 에이전트를 조율하여 곡 설계 파이프라인 실행.

Step 1: Analyzer  → 요청 분석 (채널+사용자+벤치마크 종합)
Step 2: Designer  → 컨셉 설계 + 트랙리스트 설계
Step 3: Composer  → Suno 프롬프트 생성
Step 4: Lyricist  → 가사 생성 (has_lyrics 채널만)
"""
from __future__ import annotations

import logging

from agents.analyzer import analyzer_agent
from agents.designer import designer_agent
from agents.composer import composer_agent
from agents.lyricist import lyricist_agent

logger = logging.getLogger(__name__)


class TrackDesigner:
    """오케스트레이터: 4개 에이전트를 순서대로 호출."""

    async def design_tracks(
        self,
        channel_profile: dict,
        benchmark: dict | None,
        count: int = 20,
        user_input: dict | None = None,
    ) -> dict:
        """
        4단계 곡 설계 파이프라인.

        Returns:
            {
                "analysis": { ... },
                "concept": { ... },
                "tracklist": [ ... ],
                "tracks": [ ... ],  ← Suno 프롬프트 포함 최종 트랙
            }
        """
        ui = user_input or {}
        has_lyrics = channel_profile.get("has_lyrics", False)

        # ── Step 1: Analyzer — 요청 분석 ──
        logger.info("[1/4] Analyzer: 요청 분석 중...")
        analysis = await analyzer_agent.analyze(
            channel_profile, benchmark, ui, count
        )
        logger.info(f"[1/4] 분석 완료: {analysis.get('music_direction', '')[:60]}")

        # ── Step 2: Designer — 컨셉 + 트랙리스트 설계 ──
        logger.info("[2/4] Designer: 컨셉 설계 중...")
        concept = await designer_agent.design_concept(analysis, channel_profile)
        logger.info(f"[2/4] 컨셉: {concept.get('project_name', '')}")

        logger.info("[2/4] Designer: 트랙리스트 설계 중...")
        tracklist = await designer_agent.design_tracklist(
            concept, analysis, channel_profile, count
        )
        logger.info(f"[2/4] 트랙리스트: {len(tracklist)}곡 설계")

        # ── Step 3: Composer — Suno 프롬프트 생성 ──
        logger.info("[3/4] Composer: Suno 프롬프트 생성 중...")
        tracks = await composer_agent.compose_all(
            tracklist, concept, channel_profile, ui
        )
        logger.info(f"[3/4] 프롬프트: {len(tracks)}곡 완료")

        # ── Step 4: Lyricist — 가사 생성 (선택) ──
        if has_lyrics and tracks:
            logger.info("[4/4] Lyricist: 가사 생성 중...")
            try:
                # tracklist의 lyrics_theme을 tracks에 매핑
                theme_map = {t.get("index"): t.get("lyrics_theme", "") for t in tracklist}
                for track in tracks:
                    idx = track.get("index")
                    if idx in theme_map:
                        track["lyrics_theme"] = theme_map[idx]

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
                logger.info(f"[4/4] 가사: {len(lyrics_list)}곡 완료")
            except Exception as e:
                logger.warning(f"[4/4] 가사 생성 실패 (곡 설계는 유지): {e}")
        else:
            logger.info("[4/4] Lyricist: 건너뜀 (Instrumental)")

        return {
            "analysis": analysis,
            "concept": concept,
            "tracklist": tracklist,
            "tracks": tracks,
        }

    async def regenerate_single(
        self,
        track: dict,
        channel_profile: dict,
        concept: dict | None = None,
    ) -> dict:
        """개별 곡 재생성 (Composer 호출)."""
        return await composer_agent.regenerate_single(
            track, concept or {}, channel_profile
        )

    async def generate_affirmations(self, count: int, mood: str) -> list[str]:
        """확언 문구 생성 (Lyricist 호출)."""
        return await lyricist_agent.generate_affirmations(count, mood)


track_designer = TrackDesigner()
