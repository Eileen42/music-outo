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
        template: str | dict = "",
    ) -> dict:
        """
        설계도(spec)에 따라 제목, 설명, 태그, 고정댓글 생성.

        language: "ko" (한국어 기본) | "en" (영어). 구조/스타일/태그 개수는 동일,
        출력 언어만 바뀐다.
        template: 사용자 참고 템플릿. dict 면 항목별로, str 이면 모든 항목에 통째로 전달.

        Returns: {"title": str, "description": str, "tags": list, "comment": str}
        """
        tracks = project_state.get("designed_tracks", [])
        concept = project_state.get("project_concept", {})
        playlist_title = project_state.get("playlist_title", "")

        # spec/concept은 metadata_generator에서 이미 영어로 번역됨 (영어 모드).
        # playlist_title만 한국어가 남아있을 수 있어 여기서 처리.
        if language == "en" and _has_korean(playlist_title):
            playlist_title = await self._translate_text(playlist_title)

        # 트랙리스트는 mood/category 포함해서 작성. 메타데이터가 곡 다양성을
        # 반영하도록. 별도 mood_summary 도 description/tags/comment 컨텍스트로 사용.
        track_list = self._format_tracks_detailed(tracks)
        mood_summary = self._summarize_moods(tracks)

        title_spec = spec.get("title_spec", {})
        desc_spec = spec.get("description_spec", {})
        tags_spec = spec.get("tags_spec", {})
        comment_spec = spec.get("comment_spec", {})

        # 사용자 템플릿 항목별 추출 (dict 면 해당 키, str 이면 전체 텍스트 공유)
        tpl_title = self._template_for(template, "title")
        tpl_desc = self._template_for(template, "description")
        tpl_tags = self._template_for(template, "tags")
        tpl_comment = self._template_for(template, "comment")

        # 제목 생성
        title = await self._gen_title(title_spec, concept, playlist_title, len(tracks), instruction, language, template_ref=tpl_title)

        # 설명, 태그, 댓글 병렬 생성 (각자 mood_summary 도 컨텍스트로 받음)
        import asyncio
        desc_task = self._gen_description(desc_spec, concept, title, track_list, instruction, language, template_ref=tpl_desc, mood_summary=mood_summary)
        tags_task = self._gen_tags(tags_spec, concept, track_list, instruction, language, template_ref=tpl_tags, mood_summary=mood_summary)
        comment_task = self._gen_comment(comment_spec, title, track_list, len(tracks), instruction, language, template_ref=tpl_comment, mood_summary=mood_summary)

        description, tags, comment = await asyncio.gather(desc_task, tags_task, comment_task)

        result = {
            "title": title,
            "description": description,
            "tags": tags,
            "comment": comment,
        }
        logger.info(
            f"메타데이터 작성 완료 ({language}): title={title[:40]}, tags={len(tags)}개"
            f"{' (템플릿 적용)' if template else ''}"
        )
        return result

    @staticmethod
    def _template_for(template, key: str) -> str:
        """write_all 의 template 인자를 항목별로 추출.

        dict 형식: {"title":"...", "description":"..."} → 해당 key 값 반환
        str 형식: 모든 항목에 통째로 전달 (사용자가 구분 안 한 경우)
        빈 값/누락: "" → 프롬프트에서 자연스럽게 무시
        """
        if not template:
            return ""
        if isinstance(template, str):
            return template.strip()
        if isinstance(template, dict):
            val = template.get(key)
            if val is None:
                return ""
            if isinstance(val, list):
                val = ", ".join(str(x) for x in val)
            return str(val).strip()
        return ""

    @staticmethod
    def _format_tracks_detailed(tracks: list[dict]) -> str:
        """트랙리스트를 mood/category 포함해 표시 (meta_designer 와 동일 패턴)."""
        if not tracks:
            return "(트랙 없음)"
        lines: list[str] = []
        for i, t in enumerate(tracks):
            idx = t.get("index", i + 1)
            title = (t.get("title") or "").strip() or "(제목 없음)"
            mood = (t.get("mood") or "").strip()
            category = (t.get("category") or "").strip()
            extras = []
            if mood:
                extras.append(f"mood={mood}")
            if category:
                extras.append(f"category={category}")
            extras_str = f"  [{' / '.join(extras)}]" if extras else ""
            lines.append(f"  {idx}. {title}{extras_str}")
        return "\n".join(lines)

    @staticmethod
    def _summarize_moods(tracks: list[dict]) -> str:
        """곡들의 mood/category 분포 요약 (meta_designer 와 동일 패턴)."""
        if not tracks:
            return ""
        from collections import Counter
        mood_counts = Counter()
        cat_counts = Counter()
        for t in tracks:
            m = (t.get("mood") or "").strip()
            c = (t.get("category") or "").strip()
            if m:
                mood_counts[m] += 1
            if c:
                cat_counts[c] += 1
        parts: list[str] = []
        if mood_counts:
            parts.append("- 무드: " + ", ".join(f"{m}({n})" for m, n in mood_counts.most_common(6)))
        if cat_counts:
            parts.append("- 카테고리: " + ", ".join(f"{c}({n})" for c, n in cat_counts.most_common(6)))
        return "\n".join(parts)

    @staticmethod
    def _template_block(template_ref: str, language: str = "ko") -> str:
        """프롬프트에 끼워 넣을 '사용자 참고 템플릿' 블록 생성. 비어있으면 빈 문자열."""
        if not template_ref:
            return ""
        if language == "en":
            return (
                f"\n━━ ★ User Reference Template (follow this style/structure first) ━━\n"
                f"{template_ref}\n"
            )
        return (
            f"\n━━ ★ 사용자 참고 템플릿 (이 형식·구조를 우선 반영) ━━\n"
            f"{template_ref}\n"
        )

    async def _translate_text(self, text: str) -> str:
        """짧은 텍스트 한국어 → 영어. 빈 문자열/이미 영어면 그대로."""
        if not text or not _has_korean(text):
            return text
        prompt = (
            "Translate the following Korean text to natural, idiomatic English suitable for a "
            "YouTube music channel. Output ONLY the English translation, no explanation, no quotes.\n\n"
            f"{text}"
        )
        try:
            return (await gemini_client.generate_text(prompt)).strip()
        except Exception as e:
            logger.warning(f"번역 실패(원문 유지): {e}")
            return text

    async def _translate_for_english(self, data: dict, label: str = "data") -> dict:
        """dict 안의 모든 한국어 텍스트(중첩 포함)를 영어로 번역. 구조/키 보존."""
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
            "unchanged. Do NOT add commentary. Output a single JSON object only.\n\n"
            f"{payload}"
        )
        try:
            result = await gemini_client.generate_json(prompt)
            if isinstance(result, dict):
                logger.info(f"영어 모드 — {label} 번역 완료")
                return result
        except Exception as e:
            logger.warning(f"{label} 번역 실패(원문 유지): {e}")
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

    async def _gen_title(self, spec: dict, concept: dict, playlist: str, count: int, instruction: str, language: str = "ko", template_ref: str = "") -> str:
        tpl_block = self._template_block(template_ref, language)
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
{tpl_block}
{f'━━ User Instruction ━━{chr(10)}{instruction}' if instruction else ''}

★ If a User Reference Template is provided above, mirror its format (length, capitalization,
   punctuation pattern, emoji usage) while replacing topic-specific words with this project's.
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
{tpl_block}
{f'━━ 사용자 지시 ━━{chr(10)}{instruction}' if instruction else ''}

★ 위에 사용자 참고 템플릿이 있으면 그 형식(길이·이모지·구분자 패턴)을 그대로
   미러링하되 주제·키워드는 이 프로젝트에 맞게 교체하세요.
설계도의 스타일과 구조를 정확히 따라 제목을 작성하세요.
마크다운 없이 제목 텍스트만 출력."""

        return (await gemini_client.generate_text(prompt)).strip()

    async def _gen_description(self, spec: dict, concept: dict, title: str, track_list: str, instruction: str, language: str = "ko", template_ref: str = "", mood_summary: str = "") -> str:
        structure = "\n".join(f"  {i+1}. {s}" for i, s in enumerate(spec.get("structure", [])))
        tpl_block = self._template_block(template_ref, language)
        mood_block = (
            f"\n━━ Track Mood Distribution ━━\n{mood_summary}\n" if mood_summary and language == "en"
            else f"\n━━ 곡 분위기 분포 (반영 권장) ━━\n{mood_summary}\n" if mood_summary
            else ""
        )
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
{mood_block}{tpl_block}
{f'━━ User Instruction ━━{chr(10)}{instruction}' if instruction else ''}

★ If a User Reference Template is provided above, mirror its sectioning, line breaks,
   emoji placement, hashtag style. Replace topic-specific copy with this project's content.
★ The Track Mood Distribution shows the actual variety in this playlist — reflect it
   when describing the listening journey.
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
{mood_block}{tpl_block}
{f'━━ 사용자 지시 ━━{chr(10)}{instruction}' if instruction else ''}

★ 위에 사용자 참고 템플릿이 있으면 그 섹션 구조·줄바꿈·이모지 위치·해시태그 스타일을
   그대로 미러링하되 주제는 이 프로젝트에 맞게 교체하세요.
★ 곡 분위기 분포는 실제 플레이리스트의 다양성을 보여줍니다 — 청취 여정 묘사 시 반영.
설계도의 구조와 톤을 정확히 따르세요. 마크다운 없이 텍스트만."""

        return (await gemini_client.generate_text(prompt)).strip()

    async def _gen_tags(self, spec: dict, concept: dict, track_list: str, instruction: str, language: str = "ko", template_ref: str = "", mood_summary: str = "") -> list[str]:
        primary = ", ".join(spec.get("primary", []))
        secondary = ", ".join(spec.get("secondary", []))
        consistent = ", ".join(spec.get("channel_consistent", []))
        tpl_block = self._template_block(template_ref, language)
        mood_block = (
            f"\n━━ Track Mood Distribution (use as keyword source) ━━\n{mood_summary}\n" if mood_summary and language == "en"
            else f"\n━━ 곡 분위기 분포 (태그 소스로 활용) ━━\n{mood_summary}\n" if mood_summary
            else ""
        )

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
{mood_block}{tpl_block}
{f'━━ User Instruction ━━{chr(10)}{instruction}' if instruction else ''}

★ If a User Reference Template is provided above (sample tags), include those exact tags
   when relevant + add complementary tags for this project. Match the template's style
   (lowercase vs CamelCase, length, hashtag format).
★ Mine the Track Mood Distribution as additional tag candidates (each distinct mood/category).
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
{mood_block}{tpl_block}
{f'━━ 사용자 지시 ━━{chr(10)}{instruction}' if instruction else ''}

★ 위에 사용자 참고 템플릿(예시 태그) 이 있으면 그 중 관련 있는 것은 그대로 포함 +
   이 프로젝트에 맞는 보완 태그 추가. 템플릿 스타일(소문자/카멜케이스/해시태그 형식) 맞춤.
★ 곡 분위기 분포의 각 무드/카테고리도 태그 후보로 활용.
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

    async def _gen_comment(self, spec: dict, title: str, track_list: str, count: int, instruction: str, language: str = "ko", template_ref: str = "", mood_summary: str = "") -> str:
        tpl_block = self._template_block(template_ref, language)
        # 댓글은 짧으니 mood_summary 한 줄만 힌트로
        mood_hint = (
            f"\n(Mood mix: {mood_summary.replace(chr(10), ' | ')})\n" if mood_summary and language == "en"
            else f"\n(곡 분위기 믹스: {mood_summary.replace(chr(10), ' | ')})\n" if mood_summary
            else ""
        )
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
{tpl_block}
{f'━━ User Instruction ━━{chr(10)}{instruction}' if instruction else ''}

★ If a User Reference Template is provided above, mirror its emoji usage, sentence count,
   and CTA pattern. Replace topic-specific words with this project's.
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
{tpl_block}
{f'━━ 사용자 지시 ━━{chr(10)}{instruction}' if instruction else ''}

★ 위에 사용자 참고 템플릿이 있으면 이모지·문장 수·CTA 패턴을 그대로 미러링하되
   주제는 이 프로젝트에 맞게 교체하세요.
설계도의 스타일과 CTA를 따르세요. 마크다운 없이 텍스트만."""

        return (await gemini_client.generate_text(prompt)).strip()


meta_writer_agent = MetaWriterAgent()
