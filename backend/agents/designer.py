"""
Designer Agent — 음악 설계 전문.

채널 + 사용자 입력을 분석한 뒤, 프로젝트 컨셉과 곡별 설계도(Suno 프롬프트 포함)까지
2회의 Gemini 호출로 완성한다.

이전 버전은 4단계(analyzer/concept/tracklist/composer)였으나, Gemini 503 폭주 환경에서
호출 횟수 자체가 병목이라 단계를 통합했다.

역할: "어떤 음악을 만들지(분석+컨셉) → 각 곡을 어떻게 만들지(설계+프롬프트)"
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

    async def design_tracks_full(
        self,
        concept: dict,
        analysis: dict,
        channel_profile: dict,
        user_input: dict,
        count: int,
    ) -> list[dict]:
        """곡별 설계도 + Suno 프롬프트를 한 번에 생성 (Gemini 1회)."""
        genres = channel_profile.get("genre", [])
        skills = self.load_channel_skills(genres)
        has_lyrics = channel_profile.get("has_lyrics", False)

        template = self._load_prompt_template("design_tracks_full.txt")
        prompt = template.format(
            skills=skills,
            concept=self._format_concept(concept),
            analysis=self._format_analysis(analysis),
            count=count,
            has_lyrics="있음 — lyrics_theme도 채워줄 것 (lyrics 본문은 빈 문자열)" if has_lyrics else "없음 (Instrumental, lyrics_theme/lyrics 모두 빈 문자열)",
            user_keywords=user_input.get("keywords") or "(없음)",
            user_mood=user_input.get("mood") or "(없음)",
            user_lyrics_hint=user_input.get("lyrics_hint") or "(없음)",
        )

        result = await self.call_gemini(prompt)
        if isinstance(result, dict):
            result = result.get("tracks", result.get("tracklist", []))
        if not isinstance(result, list):
            result = []

        logger.info(f"트랙+프롬프트: {len(result)}곡")
        return result

    @staticmethod
    def _format_analysis(analysis: dict) -> str:
        lines = []
        for key in ("target_audience", "music_direction", "mood_spectrum",
                    "key_elements", "avoid", "playlist_flow"):
            val = analysis.get(key)
            if val:
                if isinstance(val, list):
                    val = ", ".join(str(v) for v in val)
                lines.append(f"- {key}: {val}")
        return "\n".join(lines) if lines else "(분석 데이터 없음)"

    @staticmethod
    def _format_concept(concept: dict) -> str:
        lines = []
        for key in ("project_name", "genre", "core_mood", "tempo", "bpm_range",
                    "instrumentation", "atmosphere", "base_additional"):
            val = concept.get(key)
            if val:
                lines.append(f"- {key}: {val}")
        return "\n".join(lines) if lines else "(컨셉 없음)"


designer_agent = DesignerAgent()
