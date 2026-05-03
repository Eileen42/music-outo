"""
Async 재시도 헬퍼 — exponential backoff.

transient 한 네트워크 오류 (5xx, 타임아웃, DNS 일시 장애 등) 에 대해 자동 복구.
영구 오류 (4xx 클라이언트 오류, 인증 실패) 는 재시도해도 같은 결과라 should_retry
콜백으로 분기 가능.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable, Optional

_default_logger = logging.getLogger(__name__)


async def with_retry(
    fn: Callable[[], Awaitable[Any]],
    *,
    max_attempts: int = 3,
    base_delay: float = 1.0,
    label: str = "op",
    should_retry: Optional[Callable[[Exception], bool]] = None,
    logger: Optional[logging.Logger] = None,
) -> Any:
    """fn() 을 최대 max_attempts 번 시도, 실패 사이에 base_delay * 2^n 초 대기.

    Args:
        fn:           인자 없는 async 호출 (lambda 로 래핑하면 매개변수 전달 가능)
        max_attempts: 총 시도 횟수 (기본 3 = 첫 시도 + 재시도 2)
        base_delay:   첫 재시도 전 대기 시간 (초). 이후 2배씩 증가.
                      기본 1.0 → 1초, 2초, 4초 ...
        label:        로그용 식별자
        should_retry: 예외를 받아 True 면 재시도. None 이면 모든 예외 재시도.
                      예: lambda e: not isinstance(e, PermanentAuthError)
        logger:       로그 출력용 logger (없으면 모듈 logger)

    Returns:
        fn 의 정상 반환값.

    Raises:
        마지막 시도에서 발생한 예외를 그대로 re-raise.
    """
    log = logger or _default_logger
    last_exc: Exception | None = None

    for attempt in range(max_attempts):
        try:
            return await fn()
        except Exception as e:
            last_exc = e
            if should_retry is not None and not should_retry(e):
                # 영구 오류 — 재시도 의미 없음
                raise
            if attempt == max_attempts - 1:
                # 마지막 시도였음 — 더 이상 재시도 X
                raise
            delay = base_delay * (2 ** attempt)
            log.warning(
                f"{label} 실패 (시도 {attempt + 1}/{max_attempts}): "
                f"{type(e).__name__}: {e} — {delay:.1f}초 후 재시도"
            )
            await asyncio.sleep(delay)

    # 이 지점은 도달 불가 (위에서 raise 됨)
    assert last_exc is not None
    raise last_exc
