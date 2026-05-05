"""
Designer Agent — 채널 컨셉 설계 전문 (재배치 후).

역할 분담:
  - Designer  ★ 이 파일 — 채널 분석 + 프로젝트 공통 컨셉 (analysis + concept)
  - Composer  → 곡별 6줄 Suno 프롬프트 (이전엔 design_tracks_full 가 했던 일)
  - Lyricist  → 가사
  - QA        → 최종 검증·보정

이전엔 design_tracks_full 메서드도 있었으나 Composer 로 이관됨 (commit dc87e6e).
"""
from __future__ import annotations

import logging
from agents.base import BaseAgent

logger = logging.getLogger("designer")


class DesignerAgent(BaseAgent):
    name = "designer"

    async def design_concept_full(
        self,
        channel_profile: dict,
        user_input: dict,
        count: int,
    ) -> dict:
        """채널/사용자 입력 분석 + 프로젝트 공통 컨셉을 한 번에 설계 (Gemini 1회)."""
        genres = channel_profile.get("genre", [])
        skills = self.load_channel_skills(genres)

        template = self._load_prompt_template("design_concept_full.txt")
        prompt = template.format(
            skills=skills,
            genre=", ".join(genres),
            mood_keywords=", ".join(channel_profile.get("mood_keywords", [])) or "(없음)",
            has_lyrics="가사 있음" if channel_profile.get("has_lyrics") else "Instrumental",
            subtitle_type=channel_profile.get("subtitle_type", "none"),
            suno_base=channel_profile.get("suno_base_prompt", "") or "(없음)",
            user_keywords=user_input.get("keywords") or "(없음)",
            user_mood=user_input.get("mood") or "(없음)",
            user_lyrics_hint=user_input.get("lyrics_hint") or "(없음)",
            user_extra=user_input.get("extra") or "(없음)",
            count=count,
        )

        result = await self.call_gemini(prompt)
        if isinstance(result, list):
            result = result[0] if result else {}

        analysis = result.get("analysis", {}) or {}
        concept = result.get("concept", {}) or {}
        analysis["count"] = count

        logger.info(f"분석+컨셉 완료: {concept.get('project_name', '(unnamed)')}")
        return {"analysis": analysis, "concept": concept}


designer_agent = DesignerAgent()
