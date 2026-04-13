"""
Designer Agent — 음악 설계 전문.

Analyzer의 분석 보고서를 받아 구체적인 음악 설계도를 만든다.
프로젝트 컨셉 + 개별 곡의 구조/분위기/흐름까지 설계.

역할: "분석 결과를 바탕으로 각 곡을 어떻게 구성할 것인가?"
"""
from __future__ import annotations

import logging
from agents.base import BaseAgent

logger = logging.getLogger("designer")


class DesignerAgent(BaseAgent):
    name = "designer"

    async def design_concept(
        self,
        analysis: dict,
        channel_profile: dict,
    ) -> dict:
        """
        분석 결과를 바탕으로 프로젝트 공통 컨셉 확정.

        Returns:
            {
                "project_name": "프로젝트명",
                "genre": "장르",
                "core_mood": "분위기 키워드",
                "tempo": "템포 묘사",
                "bpm_range": "BPM 범위",
                "instrumentation": "악기 구성",
                "atmosphere": "사운드 효과/분위기",
                "base_additional": "공통 분위기 서술",
                "mood_flow": ["곡1 분위기", "곡2 분위기", ...],
            }
        """
        genres = channel_profile.get("genre", [])
        skills = self.load_channel_skills(genres)

        template = self._load_prompt_template("design_concept.txt")
        prompt = template.format(
            skills=skills,
            analysis=self._format_analysis(analysis),
            genre=", ".join(genres),
            suno_base=channel_profile.get("suno_base_prompt", "") or "(없음)",
            count=analysis.get("count", 20),
        )

        result = await self.call_gemini(prompt)
        if isinstance(result, list):
            result = result[0] if result else {}
        logger.info(f"컨셉 설계: {result.get('project_name', '')}")
        return result

    async def design_tracklist(
        self,
        concept: dict,
        analysis: dict,
        channel_profile: dict,
        count: int,
    ) -> list[dict]:
        """
        컨셉을 바탕으로 개별 곡의 설계도(제목, 분위기, 구조) 생성.
        Composer에게 전달할 곡별 블루프린트.

        Returns:
            [
                {
                    "index": 1,
                    "title": "곡 제목 (영어)",
                    "title_ko": "곡 제목 (한국어)",
                    "mood": "이 곡의 분위기",
                    "mood_detail": "구체적 분위기 서술",
                    "energy_level": "low|mid-low|mid|mid-high|high",
                    "special_elements": "이 곡만의 특별 요소",
                    "duration_hint": "3:30",
                    "category": "sleep|focus|relax|...",
                    "lyrics_theme": "가사 주제 (가사 채널만)",
                },
                ...
            ]
        """
        genres = channel_profile.get("genre", [])
        skills = self.load_channel_skills(genres)
        has_lyrics = channel_profile.get("has_lyrics", False)

        template = self._load_prompt_template("design_tracklist.txt")
        prompt = template.format(
            skills=skills,
            concept=self._format_concept(concept),
            analysis=self._format_analysis(analysis),
            count=count,
            has_lyrics="있음 — 각 곡의 가사 주제도 설계" if has_lyrics else "없음 (Instrumental)",
        )

        result = await self.call_gemini(prompt)
        if isinstance(result, dict):
            result = result.get("tracks", result.get("tracklist", []))
        if isinstance(result, list):
            logger.info(f"트랙리스트 설계: {len(result)}곡")
            return result
        return []

    @staticmethod
    def _format_analysis(analysis: dict) -> str:
        lines = []
        for key in ("target_audience", "music_direction", "mood_spectrum",
                     "key_elements", "avoid", "reference_insights", "playlist_flow"):
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
