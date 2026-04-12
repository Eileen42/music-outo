"""
작사 에이전트 — 가사 생성 전문.
곡 컨셉 + 사용자 힌트를 기반으로 가사를 생성한다.
"""
from __future__ import annotations

import logging
from agents.base import BaseAgent

logger = logging.getLogger(__name__)


class LyricistAgent(BaseAgent):
    name = "lyricist"

    async def write_lyrics(
        self,
        track: dict,
        concept: dict,
        channel_profile: dict,
        user_input: dict,
    ) -> str:
        """개별 곡에 대한 가사 생성."""
        genres = channel_profile.get("genre", [])
        skills = self.load_channel_skills(genres)

        template = self._load_prompt_template("lyrics_write.txt")
        prompt = template.format(
            track_title=track.get("title", ""),
            track_title_ko=track.get("title_ko", ""),
            track_mood=track.get("mood", ""),
            suno_prompt=track.get("suno_prompt", ""),
            genre=concept.get("genre", ""),
            core_mood=concept.get("core_mood", ""),
            tempo=concept.get("tempo", ""),
            user_lyrics_hint=user_input.get("lyrics_hint") or "(자유 작성)",
            user_keywords=user_input.get("keywords") or "(없음)",
        )

        full_prompt = f"""━━ 장르별 작사 전문 지식 ━━
{skills}
━━━━━━━━━━━━━━━━━━━━━━━━

{prompt}"""

        result = await self.call_gemini(full_prompt)
        if isinstance(result, dict):
            return result.get("lyrics", "")
        if isinstance(result, str):
            return result
        return ""

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

        tracks_summary = "\n".join(
            f"  {t.get('index', i+1)}. \"{t.get('title', '')}\" — {t.get('mood', '')}"
            for i, t in enumerate(tracks)
        )

        prompt = f"""━━ 장르별 작사 전문 지식 ━━
{skills}
━━━━━━━━━━━━━━━━━━━━━━━━

너는 전문 작사가야. 아래 곡들에 대해 가사를 작성해줘.

프로젝트 컨셉:
- Genre: {concept.get('genre', '')}
- Mood: {concept.get('core_mood', '')}
- Tempo: {concept.get('tempo', '')}

사용자 요청:
- 키워드: {user_input.get('keywords') or '(없음)'}
- 가사/주제 힌트: {user_input.get('lyrics_hint') or '(자유 작성)'}

곡 목록:
{tracks_summary}

규칙:
1. 각 곡의 분위기(mood)에 맞는 가사 작성
2. 영어 가사, 2~3절 분량 (Verse 1, Chorus, Verse 2 구조)
3. Suno AI가 인식할 수 있도록 [Verse], [Chorus], [Bridge] 태그 사용
4. 전체 플레이리스트가 하나의 이야기처럼 연결되면 좋음

JSON 배열로 반환:
[
  {{
    "index": 1,
    "lyrics": "[Verse 1]\\n가사 내용...\\n\\n[Chorus]\\n가사 내용..."
  }}
]"""

        result = await self.call_gemini(prompt)
        if isinstance(result, dict):
            result = result.get("lyrics", result.get("tracks", []))
        if isinstance(result, list):
            return result
        return []

    async def generate_affirmations(self, count: int, mood: str) -> list[str]:
        """확언자막 채널용 문구 생성."""
        skills = self._load_skill("affirmation")

        prompt = f"""━━ 확언 작성 전문 지식 ━━
{skills}
━━━━━━━━━━━━━━━━━━━━━━━━

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
