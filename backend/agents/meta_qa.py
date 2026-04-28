"""
MetaQA Agent — 메타데이터 검수.

MetaDesigner의 설계도와 MetaWriter의 결과를 비교하여
불일치/오류를 감지하고, 문제 있으면 수정 요청.
"""
from __future__ import annotations

import logging
from agents.base import BaseAgent

logger = logging.getLogger("meta_qa")


class MetaQAAgent(BaseAgent):
    name = "meta_qa"

    async def verify(  # type: ignore[override]
        self,
        spec: dict,
        result: dict,
        project_state: dict,
        language: str = "ko",
    ) -> dict:
        """
        설계도(spec) vs 결과(result) 매칭 검수.

        Returns:
            {
                "passed": bool,
                "issues": [{"field": "title", "issue": "길이 초과", "severity": "error"}, ...],
                "fixes": {"title": "수정된 제목", ...} (문제 있을 때만)
            }
        """
        issues = []

        # 1. 제목 검수
        title = result.get("title", "")
        title_spec = spec.get("title_spec", {})
        max_len = title_spec.get("max_length", 50)
        if len(title) > max_len:
            issues.append({"field": "title", "issue": f"길이 초과 ({len(title)}/{max_len}자)", "severity": "error"})
        if not title.strip():
            issues.append({"field": "title", "issue": "제목 비어있음", "severity": "error"})
        for kw in title_spec.get("must_include", []):
            if kw.lower() not in title.lower():
                issues.append({"field": "title", "issue": f"필수 키워드 누락: {kw}", "severity": "warning"})

        # 2. 설명 검수
        desc = result.get("description", "")
        desc_spec = spec.get("description_spec", {})
        if len(desc) > desc_spec.get("max_length", 1000):
            issues.append({"field": "description", "issue": f"길이 초과 ({len(desc)}자)", "severity": "error"})
        if not desc.strip():
            issues.append({"field": "description", "issue": "설명 비어있음", "severity": "error"})

        # 트랙리스트 포함 확인
        tracks = project_state.get("designed_tracks", [])
        if tracks:
            first_title = tracks[0].get("title", "")
            if first_title and first_title.lower() not in desc.lower():
                issues.append({"field": "description", "issue": "트랙리스트가 설명에 없음", "severity": "warning"})

        # 3. 태그 검수
        tags = result.get("tags", [])
        tags_spec = spec.get("tags_spec", {})
        if len(tags) > tags_spec.get("max_count", 30):
            issues.append({"field": "tags", "issue": f"태그 수 초과 ({len(tags)}개)", "severity": "error"})
        if len(tags) < 5:
            issues.append({"field": "tags", "issue": f"태그 너무 적음 ({len(tags)}개)", "severity": "warning"})

        # 핵심 태그 포함 확인
        primary = [t.lower() for t in tags_spec.get("primary", [])]
        tag_lower = [t.lower() for t in tags]
        for pt in primary[:5]:
            if pt not in tag_lower:
                issues.append({"field": "tags", "issue": f"핵심 태그 누락: {pt}", "severity": "warning"})

        # 4. 댓글 검수
        comment = result.get("comment", "")
        comment_spec = spec.get("comment_spec", {})
        if len(comment) > comment_spec.get("max_length", 100):
            issues.append({"field": "comment", "issue": f"길이 초과 ({len(comment)}자)", "severity": "error"})

        errors = [i for i in issues if i["severity"] == "error"]
        passed = len(errors) == 0

        qa_result = {
            "passed": passed,
            "issues": issues,
            "error_count": len(errors),
            "warning_count": len(issues) - len(errors),
        }

        # error가 있으면 AI에게 수정 요청
        if errors:
            fixes = await self._request_fixes(spec, result, errors, language)
            qa_result["fixes"] = fixes

        logger.info(f"MetaQA: {'PASS' if passed else 'FAIL'} — {len(errors)} errors, {len(issues)-len(errors)} warnings")
        return qa_result

    async def _request_fixes(self, spec: dict, result: dict, errors: list[dict], language: str = "ko") -> dict:
        """에러 항목만 AI에게 수정 요청."""
        error_desc = "\n".join(f"- [{e['field']}] {e['issue']}" for e in errors)

        if language == "en":
            prompt = f"""[SYSTEM RULE — ABSOLUTE]
OUTPUT LANGUAGE: English only. Keep the original output language of the metadata
(English) — do NOT translate to Korean even if the spec contains Korean fields.

The YouTube metadata below has issues. Fix ONLY the problematic fields.

━━ Issues ━━
{error_desc}

━━ Current metadata ━━
- title: {result.get('title', '')}
- description: {result.get('description', '')[:300]}...
- tag count: {len(result.get('tags', []))}
- comment: {result.get('comment', '')}

━━ Design limits ━━
- title max: {spec.get('title_spec', {}).get('max_length', 50)} chars
- description max: {spec.get('description_spec', {}).get('max_length', 1000)} chars
- tags max: {spec.get('tags_spec', {}).get('max_count', 30)}
- comment max: {spec.get('comment_spec', {}).get('max_length', 100)} chars

Return ONLY problematic fields, fixed in English, as JSON:
{{
  "title": "fixed title (only if problematic)",
  "description": "fixed description (only if problematic)",
  "tags": ["fixed tags"] (only if problematic),
  "comment": "fixed comment (only if problematic)"
}}
Do NOT include fields that are fine. Do NOT use any Korean in the output."""
        else:
            prompt = f"""아래 YouTube 메타데이터에 문제가 있습니다. 문제가 있는 항목만 수정해주세요.

━━ 문제 목록 ━━
{error_desc}

━━ 현재 메타데이터 ━━
- 제목: {result.get('title', '')}
- 설명: {result.get('description', '')[:300]}...
- 태그 수: {len(result.get('tags', []))}개
- 댓글: {result.get('comment', '')}

━━ 설계 기준 ━━
- 제목 최대: {spec.get('title_spec', {}).get('max_length', 50)}자
- 설명 최대: {spec.get('description_spec', {}).get('max_length', 1000)}자
- 태그 최대: {spec.get('tags_spec', {}).get('max_count', 30)}개
- 댓글 최대: {spec.get('comment_spec', {}).get('max_length', 100)}자

문제가 있는 필드만 수정된 값을 JSON으로 반환:
{{
  "title": "수정된 제목 (문제 있을 때만)",
  "description": "수정된 설명 (문제 있을 때만)",
  "tags": ["수정된 태그"] (문제 있을 때만),
  "comment": "수정된 댓글 (문제 있을 때만)"
}}
문제 없는 필드는 포함하지 마세요."""

        fixes = await self.call_gemini(prompt)
        if isinstance(fixes, list):
            fixes = fixes[0] if fixes else {}
        return fixes if isinstance(fixes, dict) else {}


meta_qa_agent = MetaQAAgent()
