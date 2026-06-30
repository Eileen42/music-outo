"""
Composer Agent — 곡별 6줄 Suno 프롬프트 작성 전문.

역할 분담 (재배치 후):
  - Designer: 채널 컨셉 (analysis + concept) — 전체 방향성
  - Composer: 곡별 6줄 Suno 프롬프트 ★ 이 파일
  - Lyricist: 가사 (가사 채널만)
  - QA Agent: 최종 검증 (no intro / no humming / 키워드 정합성)

이전엔 Designer 가 design_tracks_full 까지 했으나, "디자이너=컨셉 / 작곡가=곡별
프롬프트" 로 명확히 분리.
"""
from __future__ import annotations

import logging
from agents.base import BaseAgent

logger = logging.getLogger("composer")


class ComposerAgent(BaseAgent):
    name = "composer"

    async def compose_tracks(
        self,
        concept: dict,
        analysis: dict,
        channel_profile: dict,
        user_input: dict,
        count: int,
    ) -> list[dict]:
        """곡별 6줄 Suno 프롬프트를 일괄 생성 (Gemini 1회).

        Composer 가 채널의 장르 스킬 (검증된 5개 raw prompt 포함) 을 컨텍스트로 받아
        곡마다 다른 무드를 골라 변주한 6줄 형식 프롬프트를 만든다.

        ★ channel_profile.suno_base_prompt 도 명시적으로 전달 — 사용자가 채널 만들
        때 적은 Suno 기본 프롬프트가 곡마다 반영되도록 (이전엔 누락되던 버그).
        """
        genres = channel_profile.get("genre", [])
        skills = self.load_channel_skills(genres)
        has_lyrics = channel_profile.get("has_lyrics", False)

        template = self._load_prompt_template("compose_tracks.txt")
        prompt = template.format(
            skills=skills,
            concept=self._format_concept(concept),
            analysis=self._format_analysis(analysis),
            count=count,
            suno_base=channel_profile.get("suno_base_prompt", "") or "(없음)",
            has_lyrics=(
                "있음 — Additional Descriptors 에 'no intro, no humming, vocals start by 0:08' 필수 포함. lyrics_theme 도 채울 것."
                if has_lyrics else
                "없음 (Instrumental, lyrics_theme/lyrics 모두 빈 문자열)"
            ),
            user_keywords=user_input.get("keywords") or "(없음)",
            user_mood=user_input.get("mood") or "(없음)",
            user_lyrics_hint=user_input.get("lyrics_hint") or "(없음)",
        )

        result = await self.call_gemini(prompt)
        if isinstance(result, dict):
            result = result.get("tracks", result.get("tracklist", []))
        if not isinstance(result, list):
            result = []

        logger.info(f"compose_tracks: {len(result)}곡 (suno_base={'있음' if channel_profile.get('suno_base_prompt') else '없음'})")
        return result

    @staticmethod
    def _format_concept(concept: dict) -> str:
        lines = []
        for key in ("project_name", "genre", "core_mood", "tempo", "bpm_range",
                    "instrumentation", "atmosphere", "base_additional"):
            val = concept.get(key)
            if val:
                lines.append(f"- {key}: {val}")
        return "\n".join(lines) if lines else "(컨셉 없음)"

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
