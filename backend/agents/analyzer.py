"""
Analyzer Agent — 음악 요청 분석 전문.

채널 설정 + 사용자 입력 + 벤치마크를 종합 분석하여
Designer에게 전달할 분석 보고서를 생성한다.

역할: "이 채널과 이 요청에 맞는 음악은 어떤 특성을 가져야 하는가?"
"""
from __future__ import annotations

import logging
from agents.base import BaseAgent

logger = logging.getLogger("analyzer")


class AnalyzerAgent(BaseAgent):
    name = "analyzer"

    async def analyze(
        self,
        channel_profile: dict,
        benchmark: dict | None,
        user_input: dict,
        count: int,
    ) -> dict:
        """
        채널 + 사용자 요청 + 벤치마크를 종합 분석.

        Returns:
            {
                "target_audience": "타겟 청취자",
                "music_direction": "음악적 방향성",
                "mood_spectrum": ["시작 분위기", ..., "마무리 분위기"],
                "key_elements": ["핵심 요소1", "요소2"],
                "avoid": ["피해야 할 것"],
                "reference_insights": "벤치마크에서 얻은 인사이트",
                "playlist_flow": "플레이리스트 흐름 설계",
                "count": 곡 수,
            }
        """
        genres = channel_profile.get("genre", [])
        skills = self.load_channel_skills(genres)

        template = self._load_prompt_template("analyze_request.txt")
        bench_meta = self._format_benchmark(benchmark)

        prompt = template.format(
            skills=skills,
            genre=", ".join(genres),
            mood_keywords=", ".join(channel_profile.get("mood_keywords", [])) or "(없음)",
            has_lyrics="가사 있음" if channel_profile.get("has_lyrics") else "Instrumental",
            subtitle_type=channel_profile.get("subtitle_type", "none"),
            suno_base=channel_profile.get("suno_base_prompt", "") or "(없음)",
            benchmark_metadata=bench_meta,
            user_keywords=user_input.get("keywords") or "(없음)",
            user_mood=user_input.get("mood") or "(없음)",
            user_lyrics_hint=user_input.get("lyrics_hint") or "(없음)",
            user_extra=user_input.get("extra") or "(없음)",
            count=count,
        )

        result = await self.call_gemini(prompt)
        if isinstance(result, list):
            result = result[0] if result else {}
        result["count"] = count
        logger.info(f"분석 완료: direction={result.get('music_direction', '')[:50]}")
        return result

    @staticmethod
    def _format_benchmark(benchmark: dict | None) -> str:
        if not benchmark:
            return "벤치마크: 없음"
        lines = []
        for key in ("title", "description", "tags", "pinned_comment", "duration"):
            val = benchmark.get(key)
            if val:
                if isinstance(val, list):
                    val = ", ".join(val[:15])
                lines.append(f"- {key}: {str(val)[:300]}")
        ai = benchmark.get("ai_analysis", {})
        if ai.get("music_style"):
            lines.append(f"- AI분석 스타일: {ai['music_style']}")
        if ai.get("mood"):
            lines.append(f"- AI분석 분위기: {', '.join(ai['mood'])}")
        return "\n".join(lines) if lines else "벤치마크: 없음"


analyzer_agent = AnalyzerAgent()
