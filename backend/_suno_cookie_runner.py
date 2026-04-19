"""
Suno 쿠키-직접 호출 런너 — 브라우저 없이 HTTP API로 일괄 생성/다운로드.

기존 _suno_batch_runner.py 와 동일한 인터페이스:
  - 입력: project_id (sys.argv[1])
  - state_manager.get(project_id) 로 designed_tracks 로드
  - 진행 상황은 _suno_progress.json 에 기록 (프론트가 폴링)
  - state.suno_tracks 에 결과 누적

차이점:
  - core.suno_api.SunoAPIClient 만 사용 (Playwright 없음)
  - max_concurrent=3 병렬 (안전선)
  - captcha 등으로 실패한 곡은 errors 에 기록, 나머지는 성공 처리
  - 토큰 만료 시 Clerk HTTP refresh 자동 실행

    python _suno_cookie_runner.py <project_id>
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path

_DIR = Path(__file__).parent
sys.path.insert(0, str(_DIR))

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

logging.basicConfig(level=logging.INFO, stream=sys.stderr)
logger = logging.getLogger("suno_cookie_runner")

# 동시 생성 (계정 1개 안전선 = 3)
MAX_CONCURRENT = 3


def _progress_path(pid: str) -> Path:
    return _DIR / "storage" / "projects" / pid / "_suno_progress.json"


def _write_progress(pid: str, data: dict) -> None:
    p = _progress_path(pid)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _count_done(all_tracks: list[dict], tracks_dir: Path) -> tuple[int, list[dict]]:
    """파일 시스템 기준 완료 수 + 미완료 트랙 목록.

    `_v1.mp3` (클린) 또는 `_v1_<uuid>.mp3` (구 형식) 양쪽 모두 인식.
    """
    files = list(tracks_dir.glob("*.mp3")) if tracks_dir.exists() else []

    def _has(idx: int, slot: int) -> bool:
        slot_clean = f"_v{slot}.mp3"
        slot_uuid  = f"_v{slot}_"
        for f in files:
            if not f.name.startswith(f"{idx:02d}_"):
                continue
            if not (f.name.endswith(slot_clean) or slot_uuid in f.name):
                continue
            try:
                if f.stat().st_size > 10_000:
                    return True
            except OSError:
                continue
        return False

    done, missing = 0, []
    for i, t in enumerate(all_tracks):
        idx = t.get("index", i + 1)
        if _has(idx, 1) and _has(idx, 2):
            done += 1
        else:
            missing.append(t)
    return done, missing


def _save_results(pid: str, results: list[dict]) -> None:
    """state.suno_tracks 에 결과 병합 (index, slot 키 기준 upsert)."""
    from core.state_manager import state_manager

    valid = [r for r in results if r.get("index") and r.get("slot")]
    if not valid:
        return

    cur = state_manager.get(pid) or {}
    old = cur.get("suno_tracks") or []
    old = [t for t in old if t.get("index") and t.get("slot")]
    keys = {(r["index"], r["slot"]) for r in valid}
    merged = [t for t in old if (t.get("index"), t.get("slot")) not in keys]
    merged.extend(valid)
    merged.sort(key=lambda t: (t.get("index", 0), t.get("slot", 0)))
    state_manager.update(pid, {"suno_tracks": merged})


async def main(project_id: str) -> None:
    from core.state_manager import state_manager
    from core.suno_api import suno_api

    state = state_manager.get(project_id)
    if not state:
        _write_progress(project_id, {"status": "failed", "errors": ["프로젝트 없음"]})
        return

    all_tracks: list[dict] = state.get("designed_tracks") or []
    if not all_tracks:
        _write_progress(project_id, {"status": "failed", "errors": ["설계된 곡 없음"]})
        return

    channel_id = state.get("channel_id", "")
    has_lyrics = False
    ch_path = _DIR / "storage" / "channels" / f"{channel_id}.json"
    if ch_path.exists():
        try:
            has_lyrics = json.loads(ch_path.read_text(encoding="utf-8")).get("has_lyrics", False)
        except Exception:
            has_lyrics = False

    total = len(all_tracks)
    tracks_dir = _DIR / "storage" / "projects" / project_id / "tracks"
    tracks_dir.mkdir(parents=True, exist_ok=True)

    tracker = {
        "status": "running",
        "phase": "checking",
        "mode": "cookie",
        "total_designed": total,
        "total_batches": total,
        "completed_batches": 0,
        "tracks_collected": 0,
        "current_song": "",
        "round": 0,
        "errors": [],
    }

    # 세션 로드
    if not suno_api.load_session():
        _write_progress(project_id, {
            "status": "failed",
            "errors": ["Suno 세션 없음 — 먼저 로그인하세요"],
        })
        return

    # 토큰 미리 갱신 (실패해도 진행 — 첫 호출에서 401이면 다시 갱신)
    refreshed = await suno_api.refresh_token()
    logger.info(f"초기 토큰 갱신: {'OK' if refreshed else 'SKIP'}")

    # 이미 완료된 곡 제외
    done_init, missing = _count_done(all_tracks, tracks_dir)
    logger.info(f"시작: {done_init}/{total}곡 이미 완료, {len(missing)}곡 생성 필요")

    if not missing:
        tracker.update(status="completed", phase="done", tracks_collected=done_init * 2)
        _write_progress(project_id, tracker)
        return

    tracker["completed_batches"] = done_init
    _write_progress(project_id, tracker)

    # 곡 → suno_api.batch_create 입력 형식으로 변환
    songs = [{
        "title": t.get("title", f"Track_{t.get('index', i+1)}"),
        "lyrics": t.get("lyrics", "") if has_lyrics else "",
        "suno_prompt": t.get("suno_prompt", ""),
        "is_instrumental": not has_lyrics,
        "index": t.get("index", i + 1),
    } for i, t in enumerate(missing)]

    def progress_cb(info: dict):
        phase = info.get("phase", "creating")
        title = info.get("current_title", "")
        if title:
            tracker["current_song"] = title
        tracker["phase"] = phase
        _write_progress(project_id, tracker)

    # 1곡 다운로드 완료될 때마다 state 즉시 갱신 → 프런트가 폴링으로 곧바로 본다
    def result_cb(track: dict):
        try:
            _save_results(project_id, [track])
        except Exception as e:
            logger.warning(f"점진 저장 실패(무시): {e}")
        if track.get("status") == "completed":
            tracker["tracks_collected"] = tracker.get("tracks_collected", 0) + 1
        # 한 곡(2 slot) 모두 완료된 index 기준으로 completed_batches 갱신
        d, _ = _count_done(all_tracks, tracks_dir)
        tracker["completed_batches"] = d
        _write_progress(project_id, tracker)

    tracker["phase"] = "creating"
    _write_progress(project_id, tracker)

    try:
        results = await suno_api.batch_create(
            songs=songs,
            output_dir=tracks_dir,
            progress_cb=progress_cb,
            result_cb=result_cb,
            max_concurrent=MAX_CONCURRENT,
        )
    except Exception as e:
        import traceback as _tb
        logger.error(f"batch_create 실패: {e}\n{_tb.format_exc()}")
        tracker["errors"].append(f"batch_create: {e}")
        results = []

    # 결과 → state.suno_tracks
    if results:
        _save_results(project_id, results)

    # 완료 카운트 (파일 기준)
    done_final, _ = _count_done(all_tracks, tracks_dir)
    tracks_collected = sum(1 for r in (results or []) if r.get("status") == "completed")

    # 최종 QA — verify + cleanup
    try:
        from agents.suno_qa import suno_qa_agent
        tracker.update(phase="verifying", current_song="최종 검수 중...")
        _write_progress(project_id, tracker)
        final = suno_qa_agent.final_check(project_id)
        complete_count = len([t for t in final.get("tracks", []) if t["status"] == "complete"])
        tracker.update(
            status="completed",
            phase="done",
            completed_batches=done_final,
            tracks_collected=final["total_files"],
            qa_report={
                "status": final["status"],
                "total_files": final["total_files"],
                "expected_files": final["expected_files"],
                "complete_count": complete_count,
                "cleanup": final.get("cleanup", {}),
            },
        )
        logger.info(f"종료: {complete_count}/{total}곡 완료, {tracks_collected}개 신규 다운로드")
    except Exception as e:
        logger.error(f"최종 검수 실패: {e}")
        tracker.update(
            status="completed",
            phase="done",
            completed_batches=done_final,
            tracks_collected=tracks_collected,
        )
    finally:
        _write_progress(project_id, tracker)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python _suno_cookie_runner.py <project_id>", file=sys.stderr)
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
