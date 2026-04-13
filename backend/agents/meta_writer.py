"""
MetaWriter Agent — 설계도대로 메타데이터 작성.

MetaDesigner의 설계도(spec)를 받아 실제 제목/설명/태그/댓글을 AI로 생성.
설계도의 스타일, 톤, 필수 요소, 길이 제한을 엄격히 따른다.
"""
from __future__ import annotations

import logging
from agents.base import BaseAgent
from core.gemini_client import gemini_client

logger = logging.getLogger("meta_writer")


class MetaWriterAgent(BaseAgent):
    name = "meta_writer"

    async def write_all(
        self,
        spec: dict,
        project_state: dict,
        instruction: str = "",
    ) -> dict:
        """
        설계도(spec)에 따라 제목, 설명, 태그, 고정댓글 생성.

        Returns: {"title": str, "description": str, "tags": list, "comment": str}
        """
        tracks = project_state.get("designed_tracks", [])
        concept = project_state.get("project_concept", {})
        playlist_title = project_state.get("playlist_title", "")

        track_list = "\n".join(
            f"  {t.get('index', i+1)}. {t.get('title', '')}"
            for i, t in enumerate(tracks)
        )

        title_spec = spec.get("title_spec", {})
        desc_spec = spec.get("description_spec", {})
        tags_spec = spec.get("tags_spec", {})
        comment_spec = spec.get("comment_spec", {})

        # 제목 생성
        title = await self._gen_title(title_spec, concept, playlist_title, len(tracks), instruction)

        # 설명, 태그, 댓글 병렬 생성
        import asyncio
        desc_task = self._gen_description(desc_spec, concept, title, track_list, instruction)
        tags_task = self._gen_tags(tags_spec, concept, track_list, instruction)
        comment_task = self._gen_comment(comment_spec, title, track_list, len(tracks), instruction)

        description, tags, comment = await asyncio.gather(desc_task, tags_task, comment_task)

        result = {
            "title": title,
            "description": description,
            "tags": tags,
            "comment": comment,
        }
        logger.info(f"메타데이터 작성 완료: title={title[:40]}, tags={len(tags)}개")
        return result

    async def _gen_title(self, spec: dict, concept: dict, playlist: str, count: int, instruction: str) -> str:
        prompt = f"""YouTube 영상 제목을 작성하세요.

━━ 설계도 ━━
- 스타일: {spec.get('style', '')}
- 필수 키워드: {', '.join(spec.get('must_include', []))}
- 톤: {spec.get('tone', '')}
- 구조 템플릿: {spec.get('template', '')}
- 최대 길이: {spec.get('max_length', 50)}자

━━ 프로젝트 정보 ━━
- 플레이리스트: {playlist}
- 장르: {concept.get('genre', '')}
- 분위기: {concept.get('core_mood', '')}
- 곡 수: {count}곡

{f'━━ 사용자 지시 ━━{chr(10)}{instruction}' if instruction else ''}

설계도의 스타일과 구조를 정확히 따라 제목을 작성하세요.
마크다운 없이 제목 텍스트만 출력."""

        return (await gemini_client.generate_text(prompt)).strip()

    async def _gen_description(self, spec: dict, concept: dict, title: str, track_list: str, instruction: str) -> str:
        structure = "\n".join(f"  {i+1}. {s}" for i, s in enumerate(spec.get("structure", [])))
        prompt = f"""YouTube 영상 설명란을 작성하세요.

━━ 설계도 ━━
- 구조:
{structure}
- 톤: {spec.get('tone', '')}
- 필수 포함: {', '.join(spec.get('must_include', []))}
- 최대 길이: {spec.get('max_length', 1000)}자

━━ 영상 정보 ━━
- 제목: {title}
- 장르: {concept.get('genre', '')}
- 분위기: {concept.get('core_mood', '')}

━━ 트랙리스트 ━━
{track_list}

{f'━━ 사용자 지시 ━━{chr(10)}{instruction}' if instruction else ''}

설계도의 구조와 톤을 정확히 따르세요. 마크다운 없이 텍스트만."""

        return (await gemini_client.generate_text(prompt)).strip()

    async def _gen_tags(self, spec: dict, concept: dict, track_list: str, instruction: str) -> list[str]:
        primary = ", ".join(spec.get("primary", []))
        secondary = ", ".join(spec.get("secondary", []))
        consistent = ", ".join(spec.get("channel_consistent", []))

        prompt = f"""YouTube 태그를 생성하세요.

━━ 설계도 ━━
- 핵심 태그: {primary}
- 보조 태그: {secondary}
- 채널 공통 태그: {consistent}
- 최대: {spec.get('max_count', 30)}개

━━ 프로젝트 ━━
- 장르: {concept.get('genre', '')}
- 분위기: {concept.get('core_mood', '')}

{f'━━ 사용자 지시 ━━{chr(10)}{instruction}' if instruction else ''}

설계도의 핵심/보조/채널 태그를 기반으로 최대 {spec.get('max_count', 30)}개.
관련성 높은 순. JSON 배열만: ["태그1", "태그2", ...]"""

        result = await gemini_client.generate_json(prompt)
        if isinstance(result, list):
            return [str(t) for t in result[:spec.get("max_count", 30)]]
        if isinstance(result, dict):
            for v in result.values():
                if isinstance(v, list):
                    return [str(t) for t in v[:spec.get("max_count", 30)]]
        return []

    async def _gen_comment(self, spec: dict, title: str, track_list: str, count: int, instruction: str) -> str:
        prompt = f"""YouTube 고정댓글을 작성하세요.

━━ 설계도 ━━
- 스타일: {spec.get('style', '')}
- 트랙리스트 포함: {spec.get('include_tracklist', True)}
- CTA: {spec.get('cta', '')}
- 최대 길이: {spec.get('max_length', 100)}자

━━ 영상 ━━
- 제목: {title}
- 곡 수: {count}곡

━━ 트랙리스트 ━━
{track_list}

{f'━━ 사용자 지시 ━━{chr(10)}{instruction}' if instruction else ''}

설계도의 스타일과 CTA를 따르세요. 마크다운 없이 텍스트만."""

        return (await gemini_client.generate_text(prompt)).strip()


meta_writer_agent = MetaWriterAgent()
