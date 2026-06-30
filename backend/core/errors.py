"""
Suno/외부 자동화 도메인의 커스텀 예외 계층.

설계:
  - 모든 예외는 RuntimeError 를 상속한다 → 기존 `except RuntimeError` 핸들러
    (routes/suno.py 등) 가 그대로 동작.
  - 세밀한 분기가 필요한 곳에서는 구체 클래스로 잡으면 된다.

사용 예:
    try:
        await suno.create_song(...)
    except SunoUIChangedError as e:
        # Suno 가 UI 를 바꾼 경우. selectors 갱신이 필요함을 사용자에게 안내.
        raise HTTPException(503, "Suno 화면이 변경되었습니다. 잠시 후 다시 시도해주세요.")
    except SunoGenerationError as e:
        # 생성 자체가 실패 (rate limit, insufficient credits 등). UI 정상.
        raise HTTPException(429, str(e))
    # RuntimeError 로 잡으면 위 두 가지 모두 잡힘 (역호환).
"""
from __future__ import annotations


class SunoAutomationError(RuntimeError):
    """Suno 자동화 도메인의 베이스 예외. 항상 RuntimeError 호환."""


class SunoUIChangedError(SunoAutomationError):
    """예상한 셀렉터를 찾을 수 없음 → Suno 가 UI 를 변경했을 가능성이 높다.
    suno_selectors.py 의 fallback chain 갱신이 필요하다."""


class SunoGenerationError(SunoAutomationError):
    """Suno 가 응답으로 명시적 실패를 반환 (insufficient credits / rate limit / try again 등).
    UI 자체는 정상이지만 곡 생성 작업이 거절됐다."""


class SunoSessionError(SunoAutomationError):
    """세션 만료 / 토큰 갱신 실패 / 로그인 안 됨. 사용자가 다시 로그인해야 한다."""
