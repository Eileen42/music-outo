"""
QA Agent — Composer + Lyricist 결과물 최종 검수.

검증 + 자동 수정 항목:
  1. Suno 프롬프트 6줄 형식 준수
  2. ★ 가사 곡: 'no intro / no humming / vocals start by 0:08' 강제 삽입
  3. 사용자 키워드 / 분위기 정합성
  4. 가사 ↔ 음악 분위기 일치 (가사 곡만)
  5. 곡별 다양성 점검

Gemini 호출이 실패해도 프로그램적으로 가능한 보정(ensure_no_intro 등) 은 무조건
수행하므로, 가사 곡의 인트로 최소화는 항상 보장된다.
"""
from __future__ import annotations

import logging
import re

from agents.base import BaseAgent

logger = logging.getLogger("qa")


# 가사 곡에 반드시 들어가야 하는 인트로 최소화 표현
_NO_INTRO_PHRASES = [
    "no intro",
    "minimal intro",
]
_NO_HUMMING_PHRASES = [
    "no humming",
    "no scat",
]
_VOCALS_START_PHRASES = [
    "vocals start",
    "vocal entry",
]


def _has_any(text: str, phrases: list[str]) -> bool:
    low = text.lower()
    return any(p in low for p in phrases)


def _ensure_no_intro_directives(suno_prompt: str) -> tuple[str, list[str]]:
    """가사 곡의 suno_prompt 에 인트로 최소화 지시가 빠져있으면 자동 추가.

    반환: (수정된 prompt, 추가된 항목 리스트)
    Additional Descriptors 줄이 있으면 거기에 추가, 없으면 마지막 줄에 보강.
    """
    additions: list[str] = []
    needs: list[str] = []

    if not _has_any(suno_prompt, _NO_INTRO_PHRASES):
        needs.append("no intro")
    if not _has_any(suno_prompt, _NO_HUMMING_PHRASES):
        needs.append("no humming, no scat")
    if not _has_any(suno_prompt, _VOCALS_START_PHRASES):
        needs.append("vocals start by 0:08")

    if not needs:
        return suno_prompt, []

    extra = ", ".join(needs)
    additions = needs

    # Additional Descriptors 줄에 보강. 못 찾으면 마지막에 새 줄로 추가.
    pattern = re.compile(r"^(Additional Descriptors:\s*)(.+)$", re.MULTILINE | re.IGNORECASE)
    m = pattern.search(suno_prompt)
    if m:
        existing = m.group(2).rstrip()
        if existing and not existing.endswith(","):
            existing += ","
        new_line = f"{m.group(1)}{existing} {extra}".rstrip()
        suno_prompt = pattern.sub(lambda _m: new_line, suno_prompt)
    else:
        # 형식이 깨진 경우 — 마지막에 추가
        suno_prompt = suno_prompt.rstrip() + f"\nAdditional Descriptors: {extra}"

    return suno_prompt, additions


def _is_six_line_format(suno_prompt: str) -> bool:
    """6줄 형식인지 빠른 검증."""
    required_labels = [
        "genre:", "mood:", "tempo:",
        "instrumentation:", "sound effects", "additional descriptors:",
    ]
    low = suno_prompt.lower()
    return all(lbl in low for lbl in required_labels)


# 한글 키워드 → 영문 키워드 hint 매핑 (rule-based 검증용).
# 사용자가 한글로 입력해도 영문 prompt 안에서 의미적으로 등장하는지 확인할 수 있도록.
# 빠진 단어가 있어도 큰 문제는 아니고 (Gemini 가 영문 변환), 핵심 키워드만 있으면 충분.
_KW_HINTS_KR_EN: dict[str, list[str]] = {
    "비": ["rain", "rainy", "raindrop", "wet"],
    "비오는": ["rain", "rainy", "raindrop"],
    "카페": ["cafe", "coffee", "lounge"],
    "아침": ["morning", "dawn", "sunrise"],
    "저녁": ["evening", "dusk", "twilight"],
    "밤": ["night", "midnight", "nocturnal"],
    "새벽": ["dawn", "early morning", "predawn"],
    "잔잔": ["calm", "gentle", "soft", "tranquil"],
    "감성": ["emotional", "sentimental", "evocative"],
    "감성적": ["emotional", "sentimental", "evocative"],
    "따뜻": ["warm", "cozy", "tender"],
    "따뜻한": ["warm", "cozy", "tender"],
    "차가운": ["cold", "icy", "chilled"],
    "신나는": ["upbeat", "energetic", "lively"],
    "슬픈": ["sad", "melancholic", "somber"],
    "행복": ["happy", "joyful", "uplifting"],
    "사랑": ["love", "romantic", "tender"],
    "겨울": ["winter", "snow", "icy"],
    "여름": ["summer", "sunny", "tropical"],
    "봄": ["spring", "blossom", "fresh"],
    "가을": ["autumn", "fall", "leaves"],
    "수면": ["sleep", "drowsy", "dreamy"],
    "명상": ["meditation", "meditative", "contemplative"],
    "공부": ["study", "focus", "concentration"],
    "운동": ["workout", "energetic", "powerful"],
    "운전": ["drive", "driving", "road trip"],
}


def _expand_keyword_hints(kw: str) -> list[str]:
    """한글 키워드에서 가능한 영문 hint 단어 리스트 반환.

    예: "비 오는 날" → ["rain", "rainy", "raindrop", "wet"]
    매칭이 0개면 원본 kw 자체를 반환 (이미 영문이거나 일반 단어).
    """
    kw_low = kw.strip().lower()
    if not kw_low:
        return []
    hints: list[str] = []
    for kr, ens in _KW_HINTS_KR_EN.items():
        if kr in kw_low:
            hints.extend(ens)
    if not hints:
        # 한글이 매핑에 없거나 영문 입력 — 원본 그대로 검색
        hints = [kw_low]
    return list(dict.fromkeys(hints))  # dedupe, preserve order


def _check_keyword_coverage(suno_prompt: str, user_keywords: str) -> list[str]:
    """suno_prompt 안에 user_keywords 의 어떤 변형도 등장 안 하면 누락 키워드 반환.

    user_keywords 가 빈 문자열이면 빈 리스트 (검증 skip).
    """
    if not user_keywords or not user_keywords.strip():
        return []
    raw_kws = [k.strip() for k in user_keywords.split(",") if k.strip()]
    sp_low = (suno_prompt or "").lower()
    missing: list[str] = []
    for kw in raw_kws:
        hints = _expand_keyword_hints(kw)
        if not any(h.lower() in sp_low for h in hints):
            missing.append(kw)
    return missing


class QAAgent(BaseAgent):
    name = "qa"

    async def verify_and_fix(
        self,
        tracks: list[dict],
        concept: dict,
        channel_profile: dict,
        user_input: dict,
    ) -> list[dict]:
        """곡 리스트 최종 검수 + 자동 수정.

        2단계 처리:
          1) 프로그램적 보정 (Gemini 안 거침) — 가사 곡 인트로 최소화 강제 등
             API 실패해도 핵심 보정은 항상 수행.
          2) Gemini 검수 — 더 미묘한 정합성 (가사 톤, 키워드 반영 등) 보강.
             실패해도 1)의 결과는 유지.
        """
        if not tracks:
            return tracks

        has_lyrics = channel_profile.get("has_lyrics", False)
        user_keywords = (user_input or {}).get("keywords", "") or ""
        suno_base = channel_profile.get("suno_base_prompt", "") or ""

        # 채널의 suno_base_prompt 도 키워드처럼 검증 — 채널마다 일관된 톤이 들어가야
        # 하므로 누락 시 알람.
        combined_keywords = ", ".join(filter(None, [user_keywords, suno_base]))

        # ── 1단계: 프로그램적 강제 보정 ────────────────────────────────────
        rule_based_count = 0
        keyword_missing_count = 0
        for t in tracks:
            sp = t.get("suno_prompt", "") or ""
            qa_notes: list[str] = []

            # (a) 가사 곡 — 인트로 / humming 자동 보강
            if has_lyrics and sp:
                fixed, added = _ensure_no_intro_directives(sp)
                if added:
                    t["suno_prompt"] = fixed
                    qa_notes.append(f"인트로 보강: {', '.join(added)}")
                    rule_based_count += 1

            # (b) 6줄 형식 깨짐 플래그 (Gemini 가 고치도록 노트만 남김)
            if sp and not _is_six_line_format(sp):
                qa_notes.append("형식 점검 필요 (라벨 누락)")

            # (c) 사용자 키워드 / 채널 suno_base 정합성 — 한글→영문 hint 매핑으로 검증
            if sp and combined_keywords:
                missing = _check_keyword_coverage(sp, combined_keywords)
                if missing:
                    qa_notes.append(f"키워드 누락 의심: {', '.join(missing)} (Gemini 재검증 권장)")
                    keyword_missing_count += 1

            if qa_notes:
                prev = t.get("qa_notes", "")
                t["qa_notes"] = (prev + " | " if prev and prev != "ok" else "") + "; ".join(qa_notes)

        if rule_based_count:
            logger.info(f"[QA rule-based] {rule_based_count}곡 인트로/humming 자동 보강")
        if keyword_missing_count:
            logger.info(f"[QA rule-based] {keyword_missing_count}곡 사용자 키워드 누락 감지 — Gemini 재검증 단계로 위임")

        # ── 2단계: Gemini 검수 (실패해도 1단계 결과는 유지) ─────────────────
        try:
            return await self._gemini_verify(tracks, concept, channel_profile, user_input)
        except Exception as e:
            logger.warning(f"[QA Gemini] 검수 실패, rule-based 결과 유지: {e}")
            return tracks

    async def _gemini_verify(
        self,
        tracks: list[dict],
        concept: dict,
        channel_profile: dict,
        user_input: dict,
    ) -> list[dict]:
        """Gemini 로 더 미묘한 검증 (정합성·가사·다양성)."""
        genres = channel_profile.get("genre", [])
        skills = self.load_channel_skills(genres)
        has_lyrics = channel_profile.get("has_lyrics", False)

        # 트랙 요약 (Gemini 컨텍스트 절약)
        tracks_summary_lines = []
        for t in tracks:
            tracks_summary_lines.append(
                f"  {t.get('index', '?')}. \"{t.get('title', '')}\" "
                f"[{t.get('mood', '')}] "
                f"suno: {t.get('suno_prompt', '')[:300]}"
                + (f" | lyrics: {t.get('lyrics', '')[:120]}" if has_lyrics else "")
            )
        tracks_summary = "\n".join(tracks_summary_lines)

        template = self._load_prompt_template("qa_check.txt")
        prompt = template.format(
            skills=skills,
            concept=self._format_concept(concept),
            user_keywords=user_input.get("keywords") or "(없음)",
            user_mood=user_input.get("mood") or "(없음)",
            user_lyrics_hint=user_input.get("lyrics_hint") or "(없음)",
            has_lyrics="있음" if has_lyrics else "없음 (Instrumental)",
            suno_base=channel_profile.get("suno_base_prompt", "") or "(없음)",
            count=len(tracks),
            tracks_summary=tracks_summary,
        )

        result = await self.call_gemini(prompt)
        if isinstance(result, dict):
            result = result.get("tracks", result.get("tracklist", []))
        if not isinstance(result, list) or not result:
            logger.warning("[QA Gemini] 응답 형식 이상, rule-based 결과 유지")
            return tracks

        logger.info(f"[QA Gemini] {len(result)}곡 검수 완료")
        return result

    @staticmethod
    def _format_concept(concept: dict) -> str:
        lines = []
        for key in ("project_name", "genre", "core_mood", "tempo", "bpm_range",
                    "instrumentation", "atmosphere", "base_additional"):
            val = concept.get(key)
            if val:
                lines.append(f"- {key}: {val}")
        return "\n".join(lines) if lines else "(컨셉 없음)"


qa_agent = QAAgent()
