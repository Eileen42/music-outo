"""
Gemini를 사용하여 YouTube 플레이리스트 영상의 메타데이터를 생성.
"""
from __future__ import annotations

import re
from pathlib import Path

from core.gemini_client import gemini_client

TEMPLATES_DIR = Path(__file__).parent.parent / "templates" / "prompts"


def _load_template(name: str) -> str:
    p = TEMPLATES_DIR / name
    if p.exists():
        return p.read_text(encoding="utf-8")
    return ""


def _fill(template: str, **kwargs) -> str:
    for k, v in kwargs.items():
        template = template.replace(f"{{{{{k}}}}}", str(v))
    return template


class MetadataGenerator:
    async def generate(self, project_state: dict) -> dict:
        tracks = project_state.get("tracks", [])
        playlist_title = project_state.get("playlist_title", "")
        name = project_state.get("name", "")

        track_list = "\n".join(
            f"{i+1}. {t.get('title', '')} — {t.get('artist', '')}"
            for i, t in enumerate(tracks)
        )

        # 벤치마크 참조 정보
        benchmark = project_state.get("benchmark_data") or {}
        bm_analysis = benchmark.get("ai_analysis") or {}
        concept = project_state.get("project_concept") or {}

        benchmark_ref = ""
        if bm_analysis:
            benchmark_ref = (
                f"\n[참고 벤치마크 영상]\n"
                f"- 제목: {benchmark.get('title', '')}\n"
                f"- 스타일: {bm_analysis.get('music_style', '')}\n"
                f"- 타겟: {bm_analysis.get('target_audience', '')}\n"
                f"- 구조: {bm_analysis.get('content_structure', '')}\n"
                f"- SEO 키워드: {', '.join(bm_analysis.get('seo_keywords', []))}\n"
            )

        concept_ref = ""
        if concept:
            concept_ref = (
                f"\n[프로젝트 컨셉]\n"
                f"- 장르: {concept.get('genre', '')}\n"
                f"- 분위기: {concept.get('core_mood', '')}\n"
                f"- 템포: {concept.get('tempo', '')} ({concept.get('bpm_range', '')})\n"
                f"- 악기: {concept.get('instrumentation', '')}\n"
                f"- 분위기: {concept.get('atmosphere', '')}\n"
            )

        ctx = {
            "project_name": name,
            "playlist_title": playlist_title,
            "track_list": track_list,
            "track_count": len(tracks),
            "benchmark_ref": benchmark_ref,
            "concept_ref": concept_ref,
        }

        title = await self._gen_title(ctx)
        description = await self._gen_description(ctx, title)
        tags = await self._gen_tags(ctx)
        comment = await self._gen_comment(ctx)

        return {
            "title": title,
            "description": description,
            "tags": tags,
            "comment": comment,
        }

    async def _gen_title(self, ctx: dict) -> str:
        template = _load_template("metadata_title.txt")
        if template:
            prompt = _fill(template, **ctx)
        else:
            prompt = f"""
YouTube 음악 플레이리스트 영상 제목을 작성하세요.
플레이리스트: {ctx['playlist_title']}
트랙 수: {ctx['track_count']}
트랙 목록:
{ctx['track_list']}
{ctx['benchmark_ref']}{ctx['concept_ref']}
조건:
- 100자 이내
- 클릭하고 싶은 제목
- 벤치마크 영상의 제목 스타일을 참고하되 그대로 복사하지 않기
- 한국어 또는 영어 (플레이리스트 언어에 맞게)
- 마크다운 없이 제목만 출력
"""
        result = await gemini_client.generate_text(prompt)
        return result.strip().strip('"').strip("'")

    async def _gen_description(self, ctx: dict, title: str) -> str:
        template = _load_template("metadata_description.txt")
        if template:
            prompt = _fill(template, title=title, **ctx)
        else:
            prompt = f"""
YouTube 영상 설명란을 작성하세요.
영상 제목: {title}
플레이리스트: {ctx['playlist_title']}
트랙 목록:
{ctx['track_list']}
{ctx['benchmark_ref']}{ctx['concept_ref']}
형식:
- 첫 2~3줄: 영상 소개 (컨셉의 분위기를 반영)
- 트랙리스트 (타임스탬프 없이 제목만)
- 태그라인 또는 문구
- 구독/좋아요 유도 문구
- 벤치마크 영상의 설명란 구조를 참고하되 복사하지 않기
"""
        result = await gemini_client.generate_text(prompt)
        return result.strip()

    async def _gen_tags(self, ctx: dict) -> list[str]:
        prompt = f"""
YouTube 영상 태그를 생성하세요.
플레이리스트: {ctx['playlist_title']}
트랙 목록:
{ctx['track_list']}
{ctx['benchmark_ref']}{ctx['concept_ref']}
조건:
- 최대 30개 태그
- 벤치마크 영상의 SEO 키워드를 참고
- 장르, 분위기, 용도(수면, 명상, 집중 등) 포함
- 관련성 높은 것부터
- JSON 배열로만 응답: ["태그1", "태그2", ...]
"""
        try:
            result = await gemini_client.generate_json(prompt)
            if isinstance(result, list):
                return [str(t) for t in result[:30]]
        except Exception:
            pass
        return []

    async def _gen_comment(self, ctx: dict) -> str:
        template = _load_template("metadata_comment.txt")
        if template:
            prompt = _fill(template, **ctx)
        else:
            prompt = f"""
YouTube 영상에 고정할 첫 번째 댓글을 작성하세요.
플레이리스트: {ctx['playlist_title']}
트랙 목록:
{ctx['track_list']}
{ctx['concept_ref']}
조건:
- 친근하고 자연스러운 톤
- 컨셉의 분위기를 반영
- 트랙리스트 포함
- 500자 이내
"""
        result = await gemini_client.generate_text(prompt)
        return result.strip()


metadata_generator = MetadataGenerator()
