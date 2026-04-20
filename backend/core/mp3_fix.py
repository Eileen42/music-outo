"""Suno MP3 헤더 교정 — 다운로드 직후 호출해서 container/Xing 헤더를 재작성.

Suno 가 내려주는 일부 MP3 는 헤더의 bitrate/duration 값이 실제 프레임과
어긋나 있어, mutagen / pydub / ffprobe / CapCut 이 서로 다른 duration 을
보고한다. ffmpeg -c:a copy 로 stream copy 재mux 하면 헤더가 올바르게
재생성되어 모든 도구가 같은 값을 읽는다.
"""
from __future__ import annotations

import asyncio
import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def _remux_sync(path: Path) -> bool:
    """ffmpeg stream-copy 재mux. 성공 시 원본을 교체.

    반환: 교정 성공 True, 실패 또는 ffmpeg 없음 False.
    실패해도 원본은 보존되므로 downstream 에서 그대로 사용 가능.
    """
    if not path.exists() or path.suffix.lower() != ".mp3":
        return False
    tmp = path.with_name(path.stem + ".__fix__.mp3")
    try:
        r = subprocess.run(
            ["ffmpeg", "-v", "error", "-y",
             "-i", str(path),
             "-c:a", "copy",
             str(tmp)],
            capture_output=True, timeout=60,
        )
        if r.returncode != 0 or not tmp.exists() or tmp.stat().st_size < 1000:
            err = r.stderr.decode(errors="replace")[:200] if r.stderr else "(no stderr)"
            logger.warning(f"mp3_fix: ffmpeg fail {path.name}: {err}")
            tmp.unlink(missing_ok=True)
            return False
        tmp.replace(path)
        return True
    except FileNotFoundError:
        logger.warning("mp3_fix: ffmpeg not in PATH — 헤더 교정 스킵")
        return False
    except Exception as e:
        logger.warning(f"mp3_fix: {path.name}: {e}")
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        return False


async def fix_mp3_header(path: Path) -> bool:
    """비동기 wrapper — 블로킹 ffmpeg 를 to_thread 로 분리."""
    return await asyncio.to_thread(_remux_sync, path)


def fix_mp3_header_sync(path: Path) -> bool:
    """동기 호출자용."""
    return _remux_sync(path)
