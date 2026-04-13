"""
Lyricist Agent — 가사 생성 전문.

Designer의 설계(lyrics_theme)와 Composer의 프롬프트를 참고하여
각 곡에 맞는 가사를 작성한다.

역할: "곡의 분위기와 주제에 맞는 가사를 전문적으로 작성"
"""
from __future__ import annotations

import logging
from agents.base import BaseAgent

logger = logging.getLogger("lyricist")


class LyricistAgent(BaseAgent):
    name = "lyricist"

    async def write_lyrics_batch(
        self,
        tracks: list[dict],
        concept: dict,
        channel_profile: dict,
        user_input: dict,
    ) -> list[dict]:
        """여러 곡의 가사를 한번에 생성."""
        genres = channel_profile.get("genre", [])
        skills = self.load_channel_skills(genres)

        template = self._load_prompt_template("write_lyrics_batch.txt")

        tracks_summary = "\n".join(
            f"  {t.get('index', i+1)}. \"{t.get('title', '')}\" — "
            f"mood: {t.get('mood', '')} | "
            f"theme: {t.get('lyrics_theme', '자유')} | "
            f"suno: {t.get('suno_prompt', '')[:80]}"
            for i, t in enumerate(tracks)
        )

        prompt = template.format(
            skills=skills,
            genre=concept.get("genre", ""),
            core_mood=concept.get("core_mood", ""),
            tempo=concept.get("tempo", ""),
            user_keywords=user_input.get("keywords") or "(없음)",
            user_lyrics_hint=user_input.get("lyrics_hint") or "(자유 작성)",
            tracks_summary=tracks_summary,
            count=len(tracks),
        )

        result = await self.call_gemini(prompt)
        if isinstance(result, dict):
            result = result.get("lyrics", result.get("tracks", []))
        if isinstance(result, list):
            logger.info(f"가사 생성: {len(result)}곡")
            return result
        return []

    async def write_lyrics_single(
        self,
        track: dict,
        concept: dict,
        channel_profile: dict,
        user_input: dict,
    ) -> str:
        """개별 곡 가사 생성."""
        genres = channel_profile.get("genre", [])
        skills = self.load_channel_skills(genres)

        template = self._load_prompt_template("write_lyrics_single.txt")
        prompt = template.format(
            skills=skills,
            track_title=track.get("title", ""),
            track_title_ko=track.get("title_ko", ""),
            track_mood=track.get("mood", ""),
            lyrics_theme=track.get("lyrics_theme", "자유"),
            suno_prompt=track.get("suno_prompt", ""),
            genre=concept.get("genre", ""),
            core_mood=concept.get("core_mood", ""),
            tempo=concept.get("tempo", ""),
            user_keywords=user_input.get("keywords") or "(없음)",
            user_lyrics_hint=user_input.get("lyrics_hint") or "(자유 작성)",
        )

        result = await self.call_gemini(prompt)
        if isinstance(result, dict):
            return result.get("lyrics", "")
        return str(result) if result else ""

    async def generate_affirmations(self, count: int, mood: str) -> list[str]:
        """확언 문구 생성."""
        skills = self._load_skill("affirmation")
        prompt = f"""━━ 확언 전문 지식 ━━
{skills}
━━━━━━━━━━━━━━━━━━

긍정 확언 문구 {count}개를 생성해.
분위기: {mood}

규칙:
- 한국어, 1문장씩
- 명상/수면용, 따뜻하고 위로가 되는 톤
- "나는", "나의", "오늘" 등으로 시작
- JSON 배열로 반환: ["문구1", "문구2", ...]"""

        result = await self.call_gemini(prompt)
        if isinstance(result, list):
            return [str(s) for s in result]
        if isinstance(result, dict):
            for v in result.values():
                if isinstance(v, list):
                    return [str(s) for s in v]
        return []


lyricist_agent = LyricistAgent()
