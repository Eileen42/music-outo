"""
메타데이터 오케스트레이터 — 3개 에이전트 조율.

Step 1: MetaDesigner → 메타데이터 설계도 (구조/톤/필수요소)
Step 2: MetaWriter → 설계도에 따라 제목/설명/태그/댓글 작성
Step 3: MetaQA → 설계도 vs 결과 검수 → 불일치 시 수정
"""
from __future__ import annotations

import logging

from agents.meta_designer import meta_designer_agent
from agents.meta_writer import meta_writer_agent
from agents.meta_qa import meta_qa_agent

logger = logging.getLogger(__name__)

MAX_QA_RETRIES = 2


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
        logger.info("[1/3] MetaDesigner: 메타데이터 설계 중...")
        spec = await meta_designer_agent.design(
            project_state, channel_videos, instruction
        )
        logger.info(f"[1/3] 설계 완료")

        # 영어 모드 — spec을 한 번만 영어로 번역해 Writer + QA가 모두 영어 spec으로 동작.
        # (이전: Writer만 번역 → QA가 한국어 spec 기준으로 영어 결과를 위반으로 보고 한국어로 수정)
        if language == "en":
            spec = await meta_writer_agent._translate_for_english(spec, label="spec")
            concept_translated = await meta_writer_agent._translate_for_english(
                project_state.get("project_concept", {}), label="concept"
            )
            project_state = {**project_state, "project_concept": concept_translated}

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

        return result


metadata_generator = MetadataGenerator()
