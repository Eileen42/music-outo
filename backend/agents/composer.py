"""
Composer Agent — Suno 프롬프트 생성 전문.

Designer의 설계도(tracklist)를 받아 각 곡의 Suno 프롬프트를 작성한다.
장르별 스킬을 참조하여 최적의 Suno 프롬프트 형식으로 변환.

역할: "설계도를 실제 Suno가 이해하는 프롬프트로 변환"
"""
from __future__ import annotations

import logging
from agents.base import BaseAgent

logger = logging.getLogger("composer")


class ComposerAgent(BaseAgent):
    name = "composer"

    async def compose_all(
        self,
        tracklist: list[dict],
        concept: dict,
        channel_profile: dict,
        user_input: dict,
    ) -> list[dict]:
        """
        Designer의 tracklist를 받아 각 곡의 Suno 프롬프트를 생성.

        Returns: tracklist 각 항목에 suno_prompt 추가
        """
        genres = channel_profile.get("genre", [])
        skills = self.load_channel_skills(genres)
        has_lyrics = channel_profile.get("has_lyrics", False)

        template = self._load_prompt_template("compose_prompts.txt")
        prompt = template.format(
            skills=skills,
            concept=self._format_concept(concept),
            tracklist=self._format_tracklist(tracklist),
            count=len(tracklist),
            lyrics_rule="있음 — lyrics 필드에 빈 문자열 (Lyricist Agent가 별도 생성)" if has_lyrics else "없음 — lyrics 필드는 빈 문자열",
            user_keywords=user_input.get("keywords") or "(없음)",
            user_mood=user_input.get("mood") or "(없음)",
        )

        result = await self.call_gemini(prompt)
        if isinstance(result, dict):
            result = result.get("tracks", result.get("songs", []))
        if not isinstance(result, list):
            result = []

        logger.info(f"프롬프트 생성: {len(result)}곡")
        return result

    async def regenerate_single(
        self,
        track: dict,
        concept: dict,
        channel_profile: dict,
    ) -> dict:
        """개별 곡 Suno 프롬프트 재생성."""
        genres = channel_profile.get("genre", [])
        skills = self.load_channel_skills(genres)
        has_lyrics = channel_profile.get("has_lyrics", False)

        prompt = f"""━━ 장르 전문 지식 ━━
{skills}
━━━━━━━━━━━━━━━━━━

프로젝트 컨셉:
{self._format_concept(concept)}

아래 기존 곡을 참고해서, 비슷하지만 다른 새 곡의 Suno 프롬프트를 1개 만들어줘.

기존 곡:
- 제목: {track.get('title', '')}
- 무드: {track.get('mood', '')}
- Suno 프롬프트: {track.get('suno_prompt', '')}

가사: {"있음" if has_lyrics else "없음 (Instrumental)"}

JSON 객체 1개:
{{
  "index": {track.get('index', 1)},
  "title": "새 곡 제목 (영어)",
  "title_ko": "새 곡 제목 (한국어)",
  "suno_prompt": "Genre: ...\\nMood: ...\\nTempo: ...\\nInstrumentation: ...\\nSound Effects/Atmosphere: ...\\nAdditional Descriptors: ...",
  "lyrics": "",
  "mood": "분위기 (한국어)",
  "duration_hint": "3:30",
  "category": "{track.get('category', 'relax')}"
}}"""

        result = await self.call_gemini(prompt)
        if isinstance(result, list):
            result = result[0] if result else {}
        return result

    @staticmethod
    def _format_concept(concept: dict) -> str:
        return "\n".join(
            f"- {k}: {v}" for k, v in concept.items()
            if v and k in ("project_name", "genre", "core_mood", "tempo",
                           "bpm_range", "instrumentation", "atmosphere", "base_additional")
        )

    @staticmethod
    def _format_tracklist(tracklist: list[dict]) -> str:
        lines = []
        for t in tracklist:
            parts = [f"{t.get('index', '?')}. \"{t.get('title', '')}\""]
            if t.get("mood"):
                parts.append(f"mood={t['mood']}")
            if t.get("energy_level"):
                parts.append(f"energy={t['energy_level']}")
            if t.get("special_elements"):
                parts.append(f"special={t['special_elements']}")
            lines.append(" | ".join(parts))
        return "\n".join(lines)


composer_agent = ComposerAgent()
