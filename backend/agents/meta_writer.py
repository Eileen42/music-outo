"""
MetaWriter Agent — 설계도대로 메타데이터 작성.

MetaDesigner의 설계도(spec)를 받아 실제 제목/설명/태그/댓글을 AI로 생성.
설계도의 스타일, 톤, 필수 요소, 길이 제한을 엄격히 따른다.
"""
from __future__ import annotations

import json
import logging
import re

from agents.base import BaseAgent
from core.gemini_client import gemini_client

logger = logging.getLogger("meta_writer")

_HANGUL_RE = re.compile(r"[가-힯ᄀ-ᇿ]")


def _has_korean(text: str) -> bool:
    return bool(_HANGUL_RE.search(text))


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

        # spec/concept은 metadata_generator에서 이미 영어로 번역됨 (영어 모드).
        # playlist_title만 한국어가 남아있을 수 있어 여기서 처리.
        if language == "en" and _has_korean(playlist_title):
            playlist_title = await self._translate_text(playlist_title)

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

    async def _translate_text(self, text: str) -> str:
        """짧은 텍스트 한국어 → 영어. 빈 문자열/이미 영어면 그대로.

        한글 잔재 검증 + 1회 재시도. 실패해도 한글이 남아있으면 비영문 문자만 제거한 결과 반환
        (최후의 안전망 — 사용자 화면에 한글이 노출되는 것은 무조건 막는다).
        """
        if not text or not _has_korean(text):
            return text
        base_prompt = (
            "Translate the following Korean text to natural, idiomatic English suitable for a "
            "YouTube music channel. Output ONLY the English translation, no Korean characters, "
            "no explanation, no quotes.\n\n"
            f"{text}"
        )
        retry_prompt = base_prompt + (
            "\n\nIMPORTANT: Your previous attempt still contained Korean characters. "
            "Rewrite from scratch in pure English with NO Hangul whatsoever."
        )
        for attempt, p in enumerate((base_prompt, retry_prompt), start=1):
            try:
                out = (await gemini_client.generate_text(p)).strip()
                if not _has_korean(out):
                    return out
                logger.warning(f"_translate_text 시도 {attempt} — 한글 잔재")
            except Exception as e:
                logger.warning(f"_translate_text 시도 {attempt} 실패: {e}")
        # 두 번 다 실패 — 한글을 강제 제거 (영문만 남김)
        scrubbed = _HANGUL_RE.sub("", text).strip()
        logger.warning(f"_translate_text 최종 실패 — 한글 강제 제거: '{text[:30]}...' → '{scrubbed[:30]}...'")
        return scrubbed or text

    async def _translate_for_english(self, data: dict, label: str = "data") -> dict:
        """dict 안의 모든 한국어 텍스트(중첩 포함)를 영어로 번역. 구조/키 보존.

        부분 번역(한국어 잔재) 시 1회 재시도. 그래도 한국어가 남으면 원본 유지.
        """
        if not data:
            return data
        try:
            payload = json.dumps(data, ensure_ascii=False)
        except Exception:
            return data
        if not _has_korean(payload):
            return data
        prompt = (
            "Translate every Korean string value in the following JSON to natural English. "
            "Keep the JSON structure, keys, numbers, booleans, and any already-English values "
            "unchanged. Do NOT add commentary. Output a single JSON object only. "
            "The output must contain NO Korean (Hangul) characters whatsoever.\n\n"
            f"{payload}"
        )
        for attempt in (1, 2):
            try:
                result = await gemini_client.generate_json(prompt)
                if isinstance(result, dict):
                    leftover = json.dumps(result, ensure_ascii=False)
                    if not _has_korean(leftover):
                        logger.info(f"영어 모드 — {label} 번역 완료 (시도 {attempt})")
                        return result
                    logger.warning(f"{label} 번역에 한글 잔재 — 시도 {attempt}")
            except Exception as e:
                logger.warning(f"{label} 번역 실패(시도 {attempt}): {e}")
        logger.warning(f"{label} 번역 최종 실패 — 원문 유지")
        return data

    @staticmethod
    def _lang_directive(language: str) -> str:
        """프롬프트 맨 앞에 박는 강한 시스템 룰. spec/concept이 한국어여도 출력은 정확히 일치시킴."""
        if language == "en":
            # 강한 강제 — spec·concept·instruction 등이 한국어로 와도 출력은 영어로.
            return (
                "[SYSTEM RULE — ABSOLUTE OVERRIDE]\n"
                "OUTPUT LANGUAGE: English only.\n"
                "\n"
                "The design spec, project concept, must-include keywords, CTA, structure hints,\n"
                "and user instruction below may contain Korean text. Treat them as design INTENT,\n"
                "not as text to copy. You MUST translate or rewrite that intent into idiomatic English.\n"
                "\n"
                "Hard rules:\n"
                "  1. Do NOT copy any Korean phrase from the spec verbatim into the output.\n"
                "  2. Do NOT include any Korean (Hangul) characters in the output.\n"
                "  3. Do NOT mix Korean and English (e.g. 'Enjoy the 감성 vibes' is FORBIDDEN).\n"
                "  4. Write as a native English YouTube copywriter for an English-speaking audience.\n"
                "  5. Even Korean-style emoticons/phrases (예: 환영해요, 어떠셨나요) must be replaced\n"
                "     with natural English equivalents (e.g. 'Welcome!', 'How was it?').\n"
            )
        return (
            "[SYSTEM RULE — ABSOLUTE]\n"
            "출력 언어: 한국어.\n"
            "전체 출력(제목·설명·태그·댓글)을 자연스러운 한국어로 작성하세요.\n"
        )

    async def _gen_title(self, spec: dict, concept: dict, playlist: str, count: int, instruction: str, language: str = "ko") -> str:
        if language == "en":
            prompt = f"""{self._lang_directive(language)}

Write a YouTube video title.

━━ Design Spec (may contain Korean — interpret the intent and write the OUTPUT in English) ━━
- Style: {spec.get('style', '')}
- Must include: {', '.join(spec.get('must_include', []))}
- Tone: {spec.get('tone', '')}
- Template: {spec.get('template', '')}
- Max length: {spec.get('max_length', 50)} chars

━━ Project ━━
- Playlist: {playlist}
- Genre: {concept.get('genre', '')}
- Mood: {concept.get('core_mood', '')}
- Track count: {count}

{f'━━ User Instruction ━━{chr(10)}{instruction}' if instruction else ''}

Follow the spec's style and structure exactly. Output ONLY the title text in English, no markdown."""
        else:
            prompt = f"""{self._lang_directive(language)}

YouTube 영상 제목을 작성하세요.

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

    async def _gen_description(self, spec: dict, concept: dict, title: str, track_list: str, instruction: str, language: str = "ko") -> str:
        structure = "\n".join(f"  {i+1}. {s}" for i, s in enumerate(spec.get("structure", [])))
        if language == "en":
            prompt = f"""{self._lang_directive(language)}

Write a YouTube video description.

━━ Design Spec (may contain Korean — interpret the intent and write the OUTPUT in English) ━━
- Structure:
{structure}
- Tone: {spec.get('tone', '')}
- Must include: {', '.join(spec.get('must_include', []))}
- Max length: {spec.get('max_length', 1000)} chars

━━ Video Info ━━
- Title: {title}
- Genre: {concept.get('genre', '')}
- Mood: {concept.get('core_mood', '')}

━━ Tracklist ━━
{track_list}

{f'━━ User Instruction ━━{chr(10)}{instruction}' if instruction else ''}

Follow the spec's structure and tone exactly. Output text only in English, no markdown."""
        else:
            prompt = f"""{self._lang_directive(language)}

YouTube 영상 설명란을 작성하세요.

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

    async def _gen_tags(self, spec: dict, concept: dict, track_list: str, instruction: str, language: str = "ko") -> list[str]:
        primary = ", ".join(spec.get("primary", []))
        secondary = ", ".join(spec.get("secondary", []))
        consistent = ", ".join(spec.get("channel_consistent", []))

        if language == "en":
            prompt = f"""{self._lang_directive(language)}

Generate YouTube tags.

━━ Design Spec (may contain Korean — interpret the intent and OUTPUT tags in English) ━━
- Primary tags: {primary}
- Secondary tags: {secondary}
- Channel-wide tags: {consistent}
- Max count: {spec.get('max_count', 30)}

━━ Project ━━
- Genre: {concept.get('genre', '')}
- Mood: {concept.get('core_mood', '')}

{f'━━ User Instruction ━━{chr(10)}{instruction}' if instruction else ''}

Up to {spec.get('max_count', 30)} tags ordered by relevance.
Tags MUST be in English (lowercase preferred). Use natural English keywords an English-speaking audience would search.
JSON array only: ["tag1", "tag2", ...]"""
        else:
            prompt = f"""{self._lang_directive(language)}

YouTube 태그를 생성하세요.

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
태그는 한국어로. 일반화된 영문 음악 키워드(lofi, jazz)는 그대로 사용 가능.
관련성 높은 순. JSON 배열만: ["태그1", "태그2", ...]"""

        result = await gemini_client.generate_json(prompt)
        if isinstance(result, list):
            return [str(t) for t in result[:spec.get("max_count", 30)]]
        if isinstance(result, dict):
            for v in result.values():
                if isinstance(v, list):
                    return [str(t) for t in v[:spec.get("max_count", 30)]]
        return []

    async def _gen_comment(self, spec: dict, title: str, track_list: str, count: int, instruction: str, language: str = "ko") -> str:
        if language == "en":
            prompt = f"""{self._lang_directive(language)}

Write a YouTube pinned comment.

━━ Design Spec (may contain Korean — interpret the intent and write the OUTPUT in English) ━━
- Style: {spec.get('style', '')}
- Include tracklist: {spec.get('include_tracklist', True)}
- CTA: {spec.get('cta', '')}
- Max length: {spec.get('max_length', 100)} chars

━━ Video ━━
- Title: {title}
- Track count: {count}

━━ Tracklist ━━
{track_list}

{f'━━ User Instruction ━━{chr(10)}{instruction}' if instruction else ''}

Follow the spec's style and CTA. Output text only in English, no markdown."""
        else:
            prompt = f"""{self._lang_directive(language)}

YouTube 고정댓글을 작성하세요.

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
