"""
MetaQA Agent — 메타데이터 검수.

MetaDesigner의 설계도와 MetaWriter의 결과를 비교하여
불일치/오류를 감지하고, 문제 있으면 수정 요청.
"""
from __future__ import annotations

import logging
import re

from agents.base import BaseAgent

logger = logging.getLogger("meta_qa")

_HANGUL_RE = re.compile(r"[가-힯ᄀ-ᇿ]")


def _has_korean(text: str) -> bool:
    return bool(_HANGUL_RE.search(text or ""))


def _issue_text(code: str, language: str, **kw) -> str:
    """이슈 메시지를 요청 언어로 생성. 영어 모드에선 fix 프롬프트가 영어 컨텍스트를 받아야 한다."""
    en = {
        "title_too_long": f"title too long ({kw.get('cur')}/{kw.get('max')} chars)",
        "title_empty": "title is empty",
        "title_missing_kw": f"title missing required keyword: {kw.get('kw')}",
        "title_korean_leak": "title contains Korean characters but English output is required",
        "desc_too_long": f"description too long ({kw.get('cur')} chars)",
        "desc_empty": "description is empty",
        "desc_no_tracklist": "tracklist not present in description",
        "desc_korean_leak": "description contains Korean characters but English output is required",
        "tags_too_many": f"too many tags ({kw.get('cur')})",
        "tags_too_few": f"too few tags ({kw.get('cur')})",
        "tags_missing_primary": f"missing primary tag: {kw.get('kw')}",
        "tags_korean_leak": "tags contain Korean characters but English output is required",
        "comment_too_long": f"comment too long ({kw.get('cur')} chars)",
        "comment_korean_leak": "comment contains Korean characters but English output is required",
    }
    ko = {
        "title_too_long": f"길이 초과 ({kw.get('cur')}/{kw.get('max')}자)",
        "title_empty": "제목 비어있음",
        "title_missing_kw": f"필수 키워드 누락: {kw.get('kw')}",
        "title_korean_leak": "제목에 한글이 섞여있음",  # ko 모드에선 호출 안 됨
        "desc_too_long": f"길이 초과 ({kw.get('cur')}자)",
        "desc_empty": "설명 비어있음",
        "desc_no_tracklist": "트랙리스트가 설명에 없음",
        "desc_korean_leak": "설명에 한글이 섞여있음",
        "tags_too_many": f"태그 수 초과 ({kw.get('cur')}개)",
        "tags_too_few": f"태그 너무 적음 ({kw.get('cur')}개)",
        "tags_missing_primary": f"핵심 태그 누락: {kw.get('kw')}",
        "tags_korean_leak": "태그에 한글이 섞여있음",
        "comment_too_long": f"길이 초과 ({kw.get('cur')}자)",
        "comment_korean_leak": "댓글에 한글이 섞여있음",
    }
    table = en if language == "en" else ko
    return table.get(code, code)


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

        def add(field: str, code: str, severity: str = "error", **kw):
            issues.append({
                "field": field,
                "issue": _issue_text(code, language, **kw),
                "severity": severity,
            })

        # 1. 제목 검수
        title = result.get("title", "")
        title_spec = spec.get("title_spec", {})
        max_len = title_spec.get("max_length", 50)
        if len(title) > max_len:
            add("title", "title_too_long", cur=len(title), max=max_len)
        if not title.strip():
            add("title", "title_empty")
        for kw in title_spec.get("must_include", []):
            if kw.lower() not in title.lower():
                add("title", "title_missing_kw", "warning", kw=kw)
        if language == "en" and _has_korean(title):
            add("title", "title_korean_leak")

        # 2. 설명 검수
        desc = result.get("description", "")
        desc_spec = spec.get("description_spec", {})
        if len(desc) > desc_spec.get("max_length", 1000):
            add("description", "desc_too_long", cur=len(desc))
        if not desc.strip():
            add("description", "desc_empty")

        # 트랙리스트 포함 확인
        tracks = project_state.get("designed_tracks", [])
        if tracks:
            first_title = tracks[0].get("title", "")
            if first_title and first_title.lower() not in desc.lower():
                add("description", "desc_no_tracklist", "warning")

        if language == "en" and _has_korean(desc):
            add("description", "desc_korean_leak")

        # 3. 태그 검수
        tags = result.get("tags", [])
        tags_spec = spec.get("tags_spec", {})
        if len(tags) > tags_spec.get("max_count", 30):
            add("tags", "tags_too_many", cur=len(tags))
        if len(tags) < 5:
            add("tags", "tags_too_few", "warning", cur=len(tags))

        # 핵심 태그 포함 확인
        primary = [t.lower() for t in tags_spec.get("primary", [])]
        tag_lower = [t.lower() for t in tags]
        for pt in primary[:5]:
            if pt not in tag_lower:
                add("tags", "tags_missing_primary", "warning", kw=pt)

        if language == "en" and any(_has_korean(t) for t in tags):
            add("tags", "tags_korean_leak")

        # 4. 댓글 검수
        comment = result.get("comment", "")
        comment_spec = spec.get("comment_spec", {})
        if len(comment) > comment_spec.get("max_length", 100):
            add("comment", "comment_too_long", cur=len(comment))
        if language == "en" and _has_korean(comment):
            add("comment", "comment_korean_leak")

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
            # 영어 모드 — 현재 결과에 한글이 섞였을 수 있음. 컨텍스트로 전달하면 모델이
            # 그 언어에 동조하므로 한국어 누출 필드는 길이만 알리고 본문은 잘라낸다.
            cur_title = result.get("title", "")
            cur_desc = result.get("description", "")
            cur_comment = result.get("comment", "")
            cur_tags = result.get("tags", [])

            def safe(text: str, cap: int) -> str:
                """한국어가 섞였으면 컨텍스트에서 제거. 영어만 전달."""
                if _has_korean(text):
                    return f"<previous output had Korean leak — REWRITE FROM SCRATCH IN ENGLISH; length was {len(text)} chars>"
                return text[:cap]

            tags_ctx = "<previous tags had Korean leak — REWRITE IN ENGLISH>" if any(_has_korean(t) for t in cur_tags) else ", ".join(cur_tags[:10])

            prompt = f"""[SYSTEM RULE — ABSOLUTE OVERRIDE]
OUTPUT LANGUAGE: English only.

You are fixing YouTube metadata. The output language MUST be English.
- Do NOT include any Korean (Hangul) characters in the output.
- Do NOT mix Korean and English (e.g. 'Enjoy the 감성 vibes' is FORBIDDEN).
- If the previous output leaked Korean, rewrite that field from scratch in idiomatic English.
- Even Korean-style phrases (예: 환영해요, 어떠셨나요) must be replaced with natural English equivalents.

━━ Issues to fix ━━
{error_desc}

━━ Current metadata (Korean-leaking fields are masked — rewrite them in English) ━━
- title: {safe(cur_title, 200)}
- description: {safe(cur_desc, 300)}
- tag count: {len(cur_tags)} (sample: {tags_ctx})
- comment: {safe(cur_comment, 200)}

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
