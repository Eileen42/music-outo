"""
Composer Agent — 개별 곡 재생성 전용 (단일 트랙 Suno 프롬프트).

전체 일괄 생성은 Designer.design_tracks_full 로 통합됨. 이 모듈은 갤러리에서
"이 곡만 다시 만들기" 같은 단일 곡 재생성에만 사용된다.
"""
from __future__ import annotations

import logging
from agents.base import BaseAgent

logger = logging.getLogger("composer")


class ComposerAgent(BaseAgent):
    name = "composer"

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


composer_agent = ComposerAgent()
