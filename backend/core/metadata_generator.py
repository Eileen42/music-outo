"""
메타데이터 오케스트레이터 — 3개 에이전트 조율.

Step 1: MetaDesigner → 메타데이터 설계도 (구조/톤/필수요소)
Step 2: MetaWriter → 설계도에 따라 제목/설명/태그/댓글 작성
Step 3: MetaQA → 설계도 vs 결과 검수 → 불일치 시 수정
"""
from __future__ import annotations

import json
import logging
import re

from agents.meta_designer import meta_designer_agent
from agents.meta_writer import meta_writer_agent
from agents.meta_qa import meta_qa_agent

logger = logging.getLogger(__name__)

MAX_QA_RETRIES = 2

_HANGUL_RE = re.compile(r"[가-힯ᄀ-ᇿ]")


def _has_korean(text: str) -> bool:
    return bool(_HANGUL_RE.search(text or ""))


def _safe_dump(data) -> str:
    """dict/list를 한글 검사용 JSON 문자열로 직렬화. 실패 시 빈 문자열."""
    try:
        return json.dumps(data, ensure_ascii=False)
    except Exception:
        return ""


class MetadataGenerator:
    """메타데이터 에이전트 오케스트레이터."""

    async def generate(
        self,
        project_state: dict,
        instruction: str = "",
        channel_videos: list[dict] | None = None,
        language: str = "ko",
    ) -> dict:
        """
        3단계 메타데이터 생성.

        language: "ko" (기본) | "en". 설계 구조는 동일하고 출력 언어만 변경.

        Returns: {"title": str, "description": str, "tags": list, "comment": str}
        """
        # ── Step 1: MetaDesigner — 설계도 ──
        # language를 designer에 전달 — 영어 모드면 spec을 처음부터 영어로 생성.
        # (과거: 한국어 spec → 사후 번역. 부분 누출 위험.)
        logger.info(f"[1/3] MetaDesigner: 메타데이터 설계 중 ({language})...")
        spec = await meta_designer_agent.design(
            project_state, channel_videos, instruction, language=language
        )
        logger.info(f"[1/3] 설계 완료")

        # 영어 모드 안전망 — designer가 한글을 남겼을 가능성 대비.
        if language == "en":
            if _has_korean(_safe_dump(spec)):
                logger.warning("[1/3] designer spec에 한글 잔재 — 추가 번역")
                spec = await meta_writer_agent._translate_for_english(spec, label="spec")
            concept_translated = await meta_writer_agent._translate_for_english(
                project_state.get("project_concept", {}), label="concept"
            )

            # 트랙 타이틀 일괄 번역 — 한국어 곡명이 description/comment 출력 언어를 한국어로 끌고 감.
            tracks = project_state.get("designed_tracks") or []
            translated_tracks = await self._translate_track_titles(tracks)

            project_state = {
                **project_state,
                "project_concept": concept_translated,
                "designed_tracks": translated_tracks,
            }

            # 사용자 instruction도 한국어면 영어로 번역.
            if instruction and _has_korean(instruction):
                instruction = await meta_writer_agent._translate_text(instruction)

        # ── Step 2: MetaWriter — 작성 ──
        logger.info(f"[2/3] MetaWriter: 메타데이터 작성 중 ({language})...")
        result = await meta_writer_agent.write_all(spec, project_state, instruction, language)
        logger.info(f"[2/3] 작성 완료: title={result.get('title', '')[:40]}")

        # ── Step 3: MetaQA — 검수 (최대 2회 재시도) ──
        for attempt in range(MAX_QA_RETRIES + 1):
            logger.info(f"[3/3] MetaQA: 검수 중 (시도 {attempt + 1})...")
            qa = await meta_qa_agent.verify(spec, result, project_state, language=language)

            if qa["passed"]:
                logger.info("[3/3] QA PASS")
                break

            logger.warning(f"[3/3] QA FAIL: {qa['error_count']} errors")

            fixes = qa.get("fixes", {})
            if fixes:
                for key in ("title", "description", "tags", "comment"):
                    if key in fixes:
                        result[key] = fixes[key]
                logger.info(f"[3/3] 수정 적용: {list(fixes.keys())}")
            else:
                break

        # 태그 개수 강제 제한
        max_tags = spec.get("tags_spec", {}).get("max_count", 30)
        result["tags"] = result.get("tags", [])[:max_tags]

        # 영어 모드 최종 가드 — QA fix까지 거쳤는데도 한글이 남았으면 강제로 영문 재작성.
        # 모델이 가끔 directive를 무시하고 한국어로 응답하는 경우의 안전망.
        if language == "en":
            result = await self._scrub_korean(result)

        return result

    @staticmethod
    async def _translate_track_titles(tracks: list[dict]) -> list[dict]:
        """designed_tracks의 title을 영어로 번역. 구조 유지."""
        if not tracks:
            return tracks
        translated: list[dict] = []
        for t in tracks:
            title = t.get("title", "")
            if title and _has_korean(title):
                title = await meta_writer_agent._translate_text(title)
            translated.append({**t, "title": title})
        return translated

    @staticmethod
    async def _scrub_korean(result: dict) -> dict:
        """결과 필드에 한국어가 남아있으면 영문으로 강제 재작성.

        _translate_text는 자체적으로 검증/재시도/한글 강제 제거까지 수행하므로
        여기서는 호출 후 한 번 더 검증만 한다.
        """
        scrubbed_fields: list[str] = []

        for field in ("title", "description", "comment"):
            val = result.get(field, "")
            if isinstance(val, str) and _has_korean(val):
                result[field] = await meta_writer_agent._translate_text(val)
                scrubbed_fields.append(field)

        tags = result.get("tags", [])
        if any(isinstance(t, str) and _has_korean(t) for t in tags):
            new_tags = []
            for t in tags:
                if isinstance(t, str) and _has_korean(t):
                    new_tags.append(await meta_writer_agent._translate_text(t))
                else:
                    new_tags.append(t)
            result["tags"] = new_tags
            scrubbed_fields.append("tags")

        if scrubbed_fields:
            logger.warning(f"영어 모드 가드 — 한글 누출 필드 강제 번역: {scrubbed_fields}")
            # 최종 검증 — 그래도 한글이 남았는지 체크
            still_leaking = [
                f for f in ("title", "description", "comment")
                if _has_korean(result.get(f, ""))
            ]
            if still_leaking:
                logger.error(f"영어 모드 가드 후에도 한글 잔재: {still_leaking}")
            elif any(_has_korean(t) for t in result.get("tags", []) if isinstance(t, str)):
                logger.error("영어 모드 가드 후에도 tags에 한글 잔재")

        return result


metadata_generator = MetadataGenerator()
