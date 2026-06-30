"""
Suno UI 셀렉터 단일 출처(Single Source of Truth).

Suno 가 UI 를 변경하면 이 파일만 수정한다.
suno_automation.py 의 인라인 리터럴은 모두 여기서 import 한다.

설계 원칙:
  - data-testid > aria-label > placeholder > class/text 순으로 안정성이 높다.
  - 콤마로 구분된 fallback chain 을 두면 Suno 가 한쪽만 바꿔도 다른 쪽으로 잡힌다.
  - JS 내부(page.evaluate) 에서도 같은 값을 쓰도록 단일 상수로 노출한다.
"""
from __future__ import annotations


# ─── 단일 셀렉터 상수 (JS evaluate / Python 양쪽에서 공용) ────────────────────

LYRICS_TEXTAREA_TESTID: str = "[data-testid='lyrics-textarea']"

# Advanced(Custom) 모드 전환 탭
ADVANCED_TAB: str = "text=Advanced"

# 곡 검색 입력창 (/create 페이지)
SEARCH_CLIPS_INPUT: str = "input[aria-label='Search clips']"

# 크레딧 표시 영역
CREDITS_BADGE: str = "[data-testid='credits'], [class*='credits']"

# 에러 토스트/배너 (Suno 가 곡 생성 실패 시 띄우는 것들)
ERROR_TOAST: str = "[role='alert'], .error, .toast-error, [class*='error'], [class*='Error']"


# ─── Playwright 용 fallback chain 셀렉터 ────────────────────────────────────

SELECTORS: dict[str, str] = {
    # 가사 입력 영역 — testid 우선, placeholder fallback
    "lyrics_area": (
        f"{LYRICS_TEXTAREA_TESTID}, "
        "textarea[placeholder*='Write some lyrics'], "
        "textarea[placeholder*='lyrics']"
    ),
    # 곡 제목 입력 — placeholder 가 안정적
    "title_input": (
        "input[placeholder='Song Title (Optional)'], "
        "input[placeholder*='Song Title'], "
        "input[placeholder*='Title']"
    ),
    # Create 버튼 — aria-label 가 가장 안정적 (녹화로 확인됨)
    "create_btn": (
        "[aria-label='Create song'], "
        "button:has-text('Create'), "
        "[data-testid='create-button']"
    ),
    # 곡 카드 — DOM 폴링 fallback 용
    "song_card": (
        "[data-testid='song-card'], "
        "a[href*='/song/'], "
        "[class*='SongCard'], "
        "[class*='song-card']"
    ),
    # 위에서 정의한 단일 상수도 dict 로 접근 가능하게 (선택적)
    "advanced_tab": ADVANCED_TAB,
    "search_clips": SEARCH_CLIPS_INPUT,
    "credits": CREDITS_BADGE,
    "error_toast": ERROR_TOAST,
}


def parse_chain(s: str) -> list[str]:
    """콤마 구분 fallback chain 셀렉터 문자열을 리스트로 파싱. 빈 토큰 제거."""
    return [t.strip() for t in s.split(",") if t.strip()]


def selectors_list(key: str) -> list[str]:
    """SELECTORS[key] 를 fallback chain 리스트로 반환 (parse_chain 의 dict 버전)."""
    return parse_chain(SELECTORS[key])
