"""
작곡 에이전트 — Suno 프롬프트 생성 전문.
채널의 장르 스킬을 참고하여 음악 프롬프트를 생성한다.
"""
from __future__ import annotations

import logging
from agents.base import BaseAgent

logger = logging.getLogger(__name__)


class ComposerAgent(BaseAgent):
    name = "composer"

    async def design_concept(
        self,
        channel_profile: dict,
        benchmark: dict | None,
        count: int,
        user_input: dict,
    ) -> dict:
        """Step 1: 프로젝트 공통 컨셉 확정."""
        genres = channel_profile.get("genre", [])
        skills = self.load_channel_skills(genres)
        bench_meta = self._build_benchmark_metadata(benchmark)

        template = self._load_prompt_template("track_concept.txt")
        prompt = template.format(
            count=count,
            genre=", ".join(genres),
            mood_keywords=", ".join(channel_profile.get("mood_keywords", [])) or "(없음)",
            lyrics_mode="가사 있음" if channel_profile.get("has_lyrics") else "Instrumental (가사 없음)",
            suno_base=channel_profile.get("suno_base_prompt", "") or "(없음)",
            benchmark_metadata=bench_meta,
            user_keywords=user_input.get("keywords") or "(없음)",
            user_mood=user_input.get("mood") or "(없음)",
            user_lyrics_hint=user_input.get("lyrics_hint") or "(없음)",
            user_extra=user_input.get("extra") or "(없음)",
        )

        # 스킬 지식을 프롬프트 앞에 삽입
        full_prompt = f"""━━ 장르 전문 지식 (작곡 참고) ━━
{skills}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{prompt}"""

        result = await self.call_gemini(full_prompt)
        if isinstance(result, list):
            result = result[0] if result else {}
        return result if isinstance(result, dict) else {}

    async def design_tracks(
        self,
        concept: dict,
        channel_profile: dict,
        count: int,
        user_input: dict,
    ) -> list[dict]:
        """Step 2: 컨셉 고정 후 개별 곡의 Suno 프롬프트 설계."""
        genres = channel_profile.get("genre", [])
        skills = self.load_channel_skills(genres)
        has_lyrics = channel_profile.get("has_lyrics", False)

        template = self._load_prompt_template("track_design.txt")
        prompt = template.format(
            count=count,
            genre=concept.get("genre", ""),
            core_mood=concept.get("core_mood", ""),
            tempo=concept.get("tempo", ""),
            bpm_range=concept.get("bpm_range", ""),
            instrumentation=concept.get("instrumentation", ""),
            atmosphere=concept.get("atmosphere", ""),
            base_additional=concept.get("base_additional", ""),
            user_keywords=user_input.get("keywords") or "(없음)",
            user_mood=user_input.get("mood") or "(없음)",
            user_lyrics_hint=user_input.get("lyrics_hint") or "(없음)",
            lyrics_rule="있음 (영어 2~3절 분량)" if has_lyrics else "없음 — lyrics 필드는 빈 문자열",
        )

        full_prompt = f"""━━ 장르 전문 지식 (작곡 참고) ━━
{skills}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{prompt}"""

        result = await self.call_gemini(full_prompt)
        if isinstance(result, dict):
            result = result.get("tracks", result.get("songs", []))
        return result if isinstance(result, list) else []

    async def regenerate_single(self, track: dict, channel_profile: dict, concept: dict | None = None) -> dict:
        """개별 곡 재생성."""
        genres = channel_profile.get("genre", [])
        skills = self.load_channel_skills(genres)
        has_lyrics = channel_profile.get("has_lyrics", False)

        concept_block = ""
        if concept:
            concept_block = f"""프로젝트 공통 컨셉 (반드시 유지):
- Genre: {concept.get('genre', '')}
- Tempo: {concept.get('tempo', '')} ({concept.get('bpm_range', '')} BPM)
- Instrumentation: {concept.get('instrumentation', '')}
- Atmosphere: {concept.get('atmosphere', '')}"""
        else:
            concept_block = f"채널 장르: {', '.join(genres)}"

        prompt = f"""━━ 장르 전문 지식 ━━
{skills}
━━━━━━━━━━━━━━━━━━

아래 기존 곡을 참고해서, 비슷한 분위기이지만 다른 새 곡을 1개 설계해줘.
{concept_block}

기존 곡:
- 제목: {track.get('title', '')}
- 무드: {track.get('mood', '')}
- Suno 프롬프트: {track.get('suno_prompt', '')}

가사 포함: {"있음" if has_lyrics else "없음 (Instrumental)"}

JSON 객체 1개로 반환:
{{
  "index": {track.get('index', 1)},
  "title": "새 곡 제목 (영어)",
  "title_ko": "새 곡 제목 (한국어)",
  "suno_prompt": "Genre: ...\\nMood: ...\\nTempo: ...\\nInstrumentation: ...\\nSound Effects/Atmosphere: ...\\nAdditional Descriptors: ...",
  "lyrics": "",
  "mood": "새 곡 분위기 한줄 설명 (한국어)",
  "duration_hint": "3:30",
  "category": "{track.get('category', 'relax')}"
}}"""

        result = await self.call_gemini(prompt)
        if isinstance(result, list):
            result = result[0] if result else {}
        return result

    @staticmethod
    def _build_benchmark_metadata(benchmark: dict | None) -> str:
        """벤치마크에서 메타데이터만 추출."""
        if not benchmark:
            return "벤치마크: 없음"
        lines = []
        if benchmark.get("title"):
            lines.append(f"- 참고 영상 제목: {benchmark['title']}")
        if benchmark.get("description"):
            lines.append(f"- 참고 영상 설명: {benchmark['description'][:500]}")
        if benchmark.get("tags"):
            lines.append(f"- 참고 영상 태그: {', '.join(benchmark['tags'][:15])}")
        if benchmark.get("pinned_comment"):
            lines.append(f"- 참고 영상 고정댓글: {benchmark['pinned_comment'][:300]}")
        ai = benchmark.get("ai_analysis", {})
        if ai.get("music_style"):
            lines.append(f"- AI 분석 스타일: {ai['music_style']}")
        if ai.get("mood"):
            lines.append(f"- AI 분석 분위기: {', '.join(ai['mood'])}")
        return "\n".join(lines) if lines else "벤치마크: 없음"


composer_agent = ComposerAgent()
