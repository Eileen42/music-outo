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
        language: str = "ko",
    ) -> dict:
        """
        설계도(spec)에 따라 제목, 설명, 태그, 고정댓글 생성.

        language: "ko" (한국어 기본) | "en" (영어). 구조/스타일/태그 개수는 동일,
        출력 언어만 바뀐다.

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
        title = await self._gen_title(title_spec, concept, playlist_title, len(tracks), instruction, language)

        # 설명, 태그, 댓글 병렬 생성
        import asyncio
        desc_task = self._gen_description(desc_spec, concept, title, track_list, instruction, language)
        tags_task = self._gen_tags(tags_spec, concept, track_list, instruction, language)
        comment_task = self._gen_comment(comment_spec, title, track_list, len(tracks), instruction, language)

        description, tags, comment = await asyncio.gather(desc_task, tags_task, comment_task)

        result = {
            "title": title,
            "description": description,
            "tags": tags,
            "comment": comment,
        }
        logger.info(f"메타데이터 작성 완료 ({language}): title={title[:40]}, tags={len(tags)}개")
        return result

    @staticmethod
    def _lang_directive(language: str) -> str:
        """프롬프트 끝에 붙일 언어 지시. 영어 채널 대응."""
        if language == "en":
            return (
                "━━ Output Language ━━\n"
                "Write the entire output in natural English. "
                "Do NOT use Korean characters. Avoid translated-feeling phrasing — "
                "use idiomatic English suitable for an English-speaking YouTube audience."
            )
        return (
            "━━ 출력 언어 ━━\n"
            "전체 출력을 자연스러운 한국어로 작성하세요."
        )

    async def _gen_title(self, spec: dict, concept: dict, playlist: str, count: int, instruction: str, language: str = "ko") -> str:
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

{self._lang_directive(language)}

설계도의 스타일과 구조를 정확히 따라 제목을 작성하세요.
마크다운 없이 제목 텍스트만 출력."""

        return (await gemini_client.generate_text(prompt)).strip()

    async def _gen_description(self, spec: dict, concept: dict, title: str, track_list: str, instruction: str, language: str = "ko") -> str:
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

{self._lang_directive(language)}

설계도의 구조와 톤을 정확히 따르세요. 마크다운 없이 텍스트만."""

        return (await gemini_client.generate_text(prompt)).strip()

    async def _gen_tags(self, spec: dict, concept: dict, track_list: str, instruction: str, language: str = "ko") -> list[str]:
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

{self._lang_directive(language)}

설계도의 핵심/보조/채널 태그를 기반으로 최대 {spec.get('max_count', 30)}개.
태그 자체도 출력 언어에 맞게 작성하되, 일반화된 영문 음악 키워드(예: lofi, jazz)는 그대로 사용 가능.
관련성 높은 순. JSON 배열만: ["tag1", "tag2", ...]"""

        result = await gemini_client.generate_json(prompt)
        if isinstance(result, list):
            return [str(t) for t in result[:spec.get("max_count", 30)]]
        if isinstance(result, dict):
            for v in result.values():
                if isinstance(v, list):
                    return [str(t) for t in v[:spec.get("max_count", 30)]]
        return []

    async def _gen_comment(self, spec: dict, title: str, track_list: str, count: int, instruction: str, language: str = "ko") -> str:
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

{self._lang_directive(language)}

설계도의 스타일과 CTA를 따르세요. 마크다운 없이 텍스트만."""

        return (await gemini_client.generate_text(prompt)).strip()


meta_writer_agent = MetaWriterAgent()
