"""
Suno 일괄생성 실행기 — 별도 프로세스로 실행 (Windows ProactorEventLoop 격리)

사용:
    python _suno_batch_runner.py <project_id>

progress.json 에 실시간으로 상태를 기록하고, 완료 시 result.json 을 저장한다.
uvicorn(SelectorEventLoop)과 완전히 격리돼 Playwright subprocess가 정상 동작한다.
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
import os
from pathlib import Path

# ── 경로 설정 ─────────────────────────────────────────────────────────────────
_DIR = Path(__file__).parent
sys.path.insert(0, str(_DIR))

# ── Windows ProactorEventLoop 설정 (uvicorn에서 격리된 독립 프로세스이므로 여기서 설정 가능) ──
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

logging.basicConfig(level=logging.INFO, stream=sys.stderr)
logger = logging.getLogger("suno_batch_runner")


def _progress_path(project_id: str) -> Path:
    return _DIR / "storage" / "projects" / project_id / "_suno_progress.json"


def _write_progress(project_id: str, data: dict) -> None:
    p = _progress_path(project_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


async def main(project_id: str) -> None:
    from core.state_manager import state_manager
    from browser.suno_automation import SunoAutomation

    state = state_manager.get(project_id)
    if not state:
        _write_progress(project_id, {"status": "failed", "errors": ["프로젝트 없음"]})
        return

    tracks = state.get("designed_tracks") or []
    channel_id = state.get("channel_id", "")
    has_lyrics = False
    if channel_id:
        channels_path = _DIR / "storage" / "channels.json"
        if channels_path.exists():
            channels = json.loads(channels_path.read_text(encoding="utf-8"))
            ch = next((c for c in channels if c.get("id") == channel_id), None)
            if ch:
                has_lyrics = ch.get("has_lyrics", False)

    if not tracks:
        _write_progress(project_id, {"status": "failed", "errors": ["설계된 트랙 없음"]})
        return

    # 이미 생성 완료된 곡은 건너뛰기
    existing_suno = state.get("suno_tracks") or []
    completed_indices: set[int] = set()
    for st in existing_suno:
        if st.get("status") == "completed" and st.get("index"):
            completed_indices.add(st["index"])
    # slot 1,2 모두 있는 index만 완료로 간주
    from collections import Counter
    idx_completed_count = Counter(
        st["index"] for st in existing_suno
        if st.get("status") == "completed" and st.get("index")
    )
    fully_done = {idx for idx, cnt in idx_completed_count.items() if cnt >= 2}

    songs_input = [
        {
            "title":           t.get("title", f"Track {t.get('index', i+1)}"),
            "lyrics":          t.get("lyrics", "") if has_lyrics else "",
            "suno_prompt":     t.get("suno_prompt", ""),
            "is_instrumental": not has_lyrics,
            "index":           t.get("index", i + 1),
        }
        for i, t in enumerate(tracks)
        if t.get("index", i + 1) not in fully_done
    ]

    if not songs_input:
        _write_progress(project_id, {"status": "completed", "completed_batches": 0, "tracks_collected": 0, "errors": []})
        logger.info(f"모든 곡이 이미 생성 완료됨: {project_id}")
        return

    skipped = len(tracks) - len(songs_input)
    if skipped:
        logger.info(f"이미 완료된 {skipped}곡 건너뜀, {len(songs_input)}곡 생성 예정")

    pairs = len(songs_input)  # 곡별 개별 생성 (1곡 = 1 Suno 호출 → 2 클립)
    task_tracker: dict = {
        "status":           "running",
        "total_batches":    pairs,
        "completed_batches": 0,
        "tracks_collected": 0,
        "errors":           [],
    }
    _write_progress(project_id, task_tracker)

    project_dir = _DIR / "storage" / "projects" / project_id / "tracks"
    project_dir.mkdir(parents=True, exist_ok=True)

    try:
        async with SunoAutomation(max_concurrent=3) as suno:
            results = await suno.batch_create(
                songs=songs_input,
                output_dir=str(project_dir),
                task_tracker=task_tracker,
            )

        task_tracker["status"]           = "completed"
        task_tracker["results"]          = results
        task_tracker["tracks_collected"] = len([r for r in results if r.get("status") == "completed"])
        _write_progress(project_id, task_tracker)

        # state.json에 병합 저장 (기존 완료된 곡 유지)
        current_state = state_manager.get(project_id) or {}
        old_tracks = current_state.get("suno_tracks") or []
        # 새 결과의 index+slot 조합으로 기존 항목 교체
        new_keys = {(r.get("index"), r.get("slot")) for r in results}
        merged = [t for t in old_tracks if (t.get("index"), t.get("slot")) not in new_keys]
        merged.extend(results)
        merged.sort(key=lambda t: (t.get("index", 0), t.get("slot", 0)))
        state_manager.update(project_id, {"suno_tracks": merged})
        logger.info(f"완료: {project_id}, 신규 {task_tracker['tracks_collected']}곡, 전체 {len(merged)}곡")

    except Exception as e:
        import traceback as _tb
        err = _tb.format_exc()
        task_tracker["status"] = "failed"
        task_tracker["errors"].append(f"[{type(e).__name__}] {e}")
        task_tracker["traceback"] = err
        _write_progress(project_id, task_tracker)
        logger.error(f"실패: {e}\n{err}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python _suno_batch_runner.py <project_id>", file=sys.stderr)
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
