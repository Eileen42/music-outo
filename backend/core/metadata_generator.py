"""
메타데이터 오케스트레이터 — 3개 에이전트 조율.

Step 1: MetaDesigner → 메타데이터 설계도 (구조/톤/필수요소)
Step 2: MetaWriter → 설계도에 따라 제목/설명/태그/댓글 작성
Step 3: MetaQA → 설계도 vs 결과 검수 → 불일치 시 수정

★ Step 1 spec 캐싱: 같은 입력 (instruction/template/language/곡수) 으로 재생성 시
   designer 호출(~10초) 을 스킵해 응답 속도 ↑.
"""
from __future__ import annotations

import hashlib
import json
import logging

from agents.meta_designer import meta_designer_agent
from agents.meta_writer import meta_writer_agent
from agents.meta_qa import meta_qa_agent

logger = logging.getLogger(__name__)

MAX_QA_RETRIES = 2


def _spec_cache_key(
    instruction: str,
    template,
    language: str,
    track_count: int,
    concept_name: str,
) -> str:
    """spec 캐시 무효화 키 — 입력이 같으면 같은 spec 재사용 가능.

    track_count 도 포함 — 곡 수 바뀌면 spec(특히 tags) 도 다시 짜야 함.
    """
    payload = json.dumps(
        {
            "i": (instruction or "").strip(),
            "t": template if template else "",
            "l": language,
            "n": track_count,
            "c": concept_name,
        },
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


class MetadataGenerator:
    """메타데이터 에이전트 오케스트레이터."""

    async def generate(
        self,
        project_state: dict,
        instruction: str = "",
        channel_videos: list[dict] | None = None,
        language: str = "ko",
        template: str | dict = "",
    ) -> dict:
        """
        3단계 메타데이터 생성.

        language: "ko" (기본) | "en". 설계 구조는 동일하고 출력 언어만 변경.
        template: 사용자가 참고로 제공하는 템플릿 (dict 또는 str). 빈 값이면 기본 동작.

        Returns: {"title": str, "description": str, "tags": list, "comment": str,
                  "_spec": dict, "_spec_key": str}
        - _spec / _spec_key 는 호출자가 다음 generate() 호출 시 재사용할 수 있도록
          state.metadata 에 함께 저장. 같은 입력이면 designer 단계 스킵.
        """
        # ── 캐시 검사 ──
        tracks = project_state.get("designed_tracks", [])
        concept_name = (project_state.get("project_concept") or {}).get("project_name", "")
        cache_key = _spec_cache_key(instruction, template, language, len(tracks), concept_name)

        cached_meta = project_state.get("metadata") or {}
        cached_spec = cached_meta.get("_spec")
        cached_key = cached_meta.get("_spec_key")
        spec: dict
        if cached_spec and cached_key == cache_key:
            logger.info(f"[1/3] MetaDesigner: ★ spec 캐시 적중 (key={cache_key}) — 호출 스킵")
            spec = cached_spec
        else:
            # ── Step 1: MetaDesigner — 설계도 ──
            logger.info(f"[1/3] MetaDesigner: 메타데이터 설계 중... (template={'있음' if template else '없음'})")
            spec = await meta_designer_agent.design(
                project_state, channel_videos, instruction, template=template,
            )
            logger.info(f"[1/3] 설계 완료 (cache_key={cache_key})")

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
        result = await meta_writer_agent.write_all(
            spec, project_state, instruction, language, template=template,
        )
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

        # spec 캐싱 — 다음 호출 시 같은 입력이면 designer 스킵
        result["_spec"] = spec
        result["_spec_key"] = cache_key

        return result


metadata_generator = MetadataGenerator()
