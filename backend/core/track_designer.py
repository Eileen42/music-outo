"""
오케스트레이터 — 4역할 에이전트 순차 호출로 곡 설계 완료.

역할 분담:
  Step 1. Designer  → 채널 컨셉만 (analysis + concept)
  Step 2. Composer  → 곡별 6줄 Suno 프롬프트 (★ suno_base_prompt 반영)
  Step 3. Lyricist  → 가사 (가사 채널만)
  Step 4. QA Agent  → 최종 검수·수정 (★ no intro/no humming 강제, 키워드 정합성)

Gemini 호출:
  - 가사 없는 채널: 3회 (Designer + Composer + QA)
  - 가사 채널:     4회 (위 + Lyricist)

QA 의 rule-based 보정은 항상 적용되므로, 가사 곡의 인트로 최소화는
Gemini 가 실패해도 보장된다.
"""
from __future__ import annotations

import logging
from typing import Callable

from agents.designer import designer_agent
from agents.composer import composer_agent
from agents.lyricist import lyricist_agent
from agents.qa import qa_agent

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
        곡 설계 파이프라인 — Designer → Composer → Lyricist → QA.

        progress_cb(phase, message, progress%) — 백그라운드 작업의 진행상황 보고용.

        Returns:
            { "analysis": {...}, "concept": {...}, "tracklist": [...], "tracks": [...] }
        """
        ui = user_input or {}
        has_lyrics = channel_profile.get("has_lyrics", False)
        cb = progress_cb or (lambda *_a, **_kw: None)

        # ── Step 1: Designer — 채널 컨셉 ─────────────────────────────────
        cb("designer", f"채널 컨셉 설계 중... ({count}곡)", 20)
        logger.info("[1/4] Designer: 분석+컨셉 시작")
        result1 = await designer_agent.design_concept_full(channel_profile, ui, count)
        analysis = result1.get("analysis", {})
        concept = result1.get("concept", {})
        logger.info(f"[1/4] Designer 완료: {concept.get('project_name', '(unnamed)')}")

        # ── Step 2: Composer — 곡별 6줄 Suno 프롬프트 ───────────────────
        cb("composer", f"{count}곡 Suno 프롬프트 작성 중...", 50)
        logger.info("[2/4] Composer: 곡별 프롬프트 시작")
        tracks = await composer_agent.compose_tracks(
            concept=concept,
            analysis=analysis,
            channel_profile=channel_profile,
            user_input=ui,
            count=count,
        )
        logger.info(f"[2/4] Composer 완료: {len(tracks)}곡")

        # ── Step 3 (옵션): Lyricist — 가사 ─────────────────────────────
        if has_lyrics and tracks:
            cb("lyricist", f"가사 {len(tracks)}곡 작성 중...", 75)
            logger.info("[3/4] Lyricist: 가사 시작")
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
                logger.info(f"[3/4] Lyricist 완료: {len(lyrics_list)}곡")
            except Exception as e:
                # 가사 실패해도 곡 설계는 살림
                logger.warning(f"[3/4] Lyricist 실패 (곡 설계는 유지): {e}")

        # ── Step 4: QA Agent — 최종 검수·수정 ──────────────────────────
        # rule-based 보정 (인트로 최소화 등) 은 Gemini 실패해도 항상 적용.
        if tracks:
            cb("qa", "최종 검수 및 자동 수정 중...", 92)
            logger.info("[4/4] QA: 검수 시작")
            try:
                tracks = await qa_agent.verify_and_fix(
                    tracks=tracks,
                    concept=concept,
                    channel_profile=channel_profile,
                    user_input=ui,
                )
                fixed = sum(1 for t in tracks if t.get("qa_notes") and t.get("qa_notes") != "ok")
                logger.info(f"[4/4] QA 완료: {fixed}/{len(tracks)}곡 보정")
            except Exception as e:
                logger.warning(f"[4/4] QA 실패 (Composer 결과 유지): {e}")

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
