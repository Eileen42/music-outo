"""
MetaDesigner Agent — 메타데이터 구조 설계.

벤치마크 영상 + 채널 기존 영상 + 프로젝트 컨셉을 분석하여
메타데이터(제목/설명/태그/댓글)의 "설계도"를 만든다.

역할: "이 영상의 메타데이터는 어떤 구조와 톤으로 작성해야 하는가?"
"""
from __future__ import annotations

import logging
from agents.base import BaseAgent

logger = logging.getLogger("meta_designer")


class MetaDesignerAgent(BaseAgent):
    name = "meta_designer"

    async def design(
        self,
        project_state: dict,
        channel_videos: list[dict] | None = None,
        instruction: str = "",
    ) -> dict:
        """
        메타데이터 설계도 생성.

        Returns:
            {
                "title_spec": {
                    "style": "채널 제목 스타일 분석",
                    "must_include": ["키워드1", "키워드2"],
                    "tone": "톤 설명",
                    "max_length": 50,
                    "template": "제목 구조 템플릿",
                },
                "description_spec": {
                    "structure": ["섹션1 설명", "섹션2 설명"],
                    "tone": "톤",
                    "must_include": ["필수 요소"],
                    "max_length": 1000,
                },
                "tags_spec": {
                    "primary": ["핵심 태그"],
                    "secondary": ["보조 태그"],
                    "channel_consistent": ["채널 공통 태그"],
                    "max_count": 30,
                },
                "comment_spec": {
                    "style": "댓글 스타일",
                    "include_tracklist": true,
                    "cta": "CTA 문구 방향",
                    "max_length": 100,
                },
            }
        """
        concept = project_state.get("project_concept", {})
        benchmark = project_state.get("benchmark_data", {})
        tracks = project_state.get("designed_tracks", [])

        channel_ref = self._format_channel_videos(channel_videos)
        bench_ref = self._format_benchmark(benchmark)
        concept_ref = self._format_concept(concept)
        track_list = "\n".join(
            f"  {t.get('index', i+1)}. {t.get('title', '')}"
            for i, t in enumerate(tracks)
        )

        prompt = f"""너는 YouTube 메타데이터 전략가야.
아래 정보를 분석하여 메타데이터(제목/설명/태그/댓글)의 설계도를 만들어줘.

━━ 프로젝트 컨셉 ━━
{concept_ref}

━━ 트랙리스트 ({len(tracks)}곡) ━━
{track_list}

━━ 벤치마크 영상 ━━
{bench_ref}

━━ 내 채널 기존 영상 ━━
{channel_ref}

━━ 사용자 지시사항 ━━
{instruction or "(없음)"}

분석해야 할 것:
1. 채널 기존 영상의 제목/설명/태그 패턴 (일관성 유지를 위해)
2. 벤치마크의 SEO 전략 (참고만, 복사 X)
3. 이 프로젝트 컨셉에 맞는 최적 메타데이터 구조

JSON으로 반환:
{{
  "title_spec": {{
    "style": "채널 기존 제목 분석 + 이 영상에 적합한 스타일 (한국어)",
    "must_include": ["반드시 포함할 키워드"],
    "tone": "제목 톤 (예: 감성적, 직관적, SEO 최적화)",
    "max_length": 50,
    "template": "제목 구조 예시 (예: [분위기] + [장르] + [용도] | [곡수]곡)"
  }},
  "description_spec": {{
    "structure": ["1. 영상 소개 (2~3줄)", "2. 트랙리스트", "3. 저작권/라이선스", "4. 구독/좋아요 유도"],
    "tone": "설명란 톤",
    "must_include": ["필수 포함 요소"],
    "max_length": 1000
  }},
  "tags_spec": {{
    "primary": ["핵심 태그 5~10개"],
    "secondary": ["보조 태그 10~15개"],
    "channel_consistent": ["채널 공통 태그 (기존 영상에서 추출)"],
    "max_count": 30
  }},
  "comment_spec": {{
    "style": "댓글 톤/스타일",
    "include_tracklist": true,
    "cta": "CTA 방향 (예: 좋아하는 곡 번호 댓글로 알려주세요)",
    "max_length": 100
  }}
}}"""

        result = await self.call_gemini(prompt)
        if isinstance(result, list):
            result = result[0] if result else {}
        logger.info(f"메타데이터 설계 완료: title_style={result.get('title_spec', {}).get('style', '')[:40]}")
        return result

    @staticmethod
    def _format_channel_videos(videos: list[dict] | None) -> str:
        if not videos:
            return "(채널 영상 없음 — 새 채널)"
        lines = []
        for i, v in enumerate(videos[:5], 1):
            title = v.get("title", "")
            tags = ", ".join(v.get("tags", [])[:10])
            desc = (v.get("description", "") or "")[:200]
            lines.append(f"  {i}. 제목: {title}\n     태그: {tags}\n     설명: {desc}")
        return "\n".join(lines)

    @staticmethod
    def _format_benchmark(benchmark: dict) -> str:
        if not benchmark:
            return "(벤치마크 없음)"
        lines = []
        if benchmark.get("title"):
            lines.append(f"- 제목: {benchmark['title']}")
        if benchmark.get("description"):
            lines.append(f"- 설명: {benchmark['description'][:300]}")
        if benchmark.get("tags"):
            lines.append(f"- 태그: {', '.join(benchmark['tags'][:15])}")
        ai = benchmark.get("ai_analysis", {})
        if ai.get("seo_keywords"):
            lines.append(f"- SEO: {', '.join(ai['seo_keywords'])}")
        return "\n".join(lines) if lines else "(벤치마크 없음)"

    @staticmethod
    def _format_concept(concept: dict) -> str:
        if not concept:
            return "(컨셉 없음)"
        return "\n".join(
            f"- {k}: {v}" for k, v in concept.items()
            if v and k in ("project_name", "genre", "core_mood", "tempo", "bpm_range", "instrumentation", "atmosphere")
        )


meta_designer_agent = MetaDesignerAgent()
