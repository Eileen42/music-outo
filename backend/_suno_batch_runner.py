"""
Suno 일괄생성 오케스트레이터 — Creator + Collector 병렬 실행.

브라우저 1개를 공유하며:
  1. Creator Agent가 탭을 추가하며 순차 생성
  2. Creator 3곡째부터 Collector Agent가 병렬로 다운로드 시작
  3. Creator 완료 → Collector 나머지 다운로드
  4. QA Agent 검수 + 자동 연결
  5. 브라우저 닫기

별도 프로세스로 실행:
    python _suno_batch_runner.py <project_id>
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path

from playwright.async_api import async_playwright

_DIR = Path(__file__).parent
sys.path.insert(0, str(_DIR))

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

logging.basicConfig(level=logging.INFO, stream=sys.stderr)
logger = logging.getLogger("suno_orchestrator")

PARALLEL_START_AFTER = 3  # Creator N곡 후 Collector 병렬 시작


def _progress_path(project_id: str) -> Path:
    return _DIR / "storage" / "projects" / project_id / "_suno_progress.json"


def _write_progress(project_id: str, data: dict) -> None:
    p = _progress_path(project_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


async def main(project_id: str) -> None:
    from core.state_manager import state_manager
    from browser.suno_automation import _find_exe, _session_path
    from agents.suno_creator import SunoCreatorAgent
    from agents.suno_collector import SunoCollectorAgent
    from agents.suno_qa import suno_qa_agent

    state = state_manager.get(project_id)
    if not state:
        _write_progress(project_id, {"status": "failed", "phase": "init", "errors": ["프로젝트 없음"]})
        return

    tracks = state.get("designed_tracks") or []
    channel_id = state.get("channel_id", "")

    has_lyrics = False
    channel_path = _DIR / "storage" / "channels" / f"{channel_id}.json"
    if channel_path.exists():
        ch = json.loads(channel_path.read_text(encoding="utf-8"))
        has_lyrics = ch.get("has_lyrics", False)

    if not tracks:
        _write_progress(project_id, {"status": "failed", "phase": "init", "errors": ["설계된 트랙 없음"]})
        return

    # 이미 완료된 곡 건너뛰기
    existing_suno = state.get("suno_tracks") or []
    from collections import Counter
    idx_count = Counter(
        st["index"] for st in existing_suno
        if st.get("status") == "completed" and st.get("index")
    )
    fully_done = {idx for idx, cnt in idx_count.items() if cnt >= 2}

    songs_input = [
        {
            "title": t.get("title", f"Track {t.get('index', i+1)}"),
            "lyrics": t.get("lyrics", "") if has_lyrics else "",
            "suno_prompt": t.get("suno_prompt", ""),
            "is_instrumental": not has_lyrics,
            "index": t.get("index", i + 1),
        }
        for i, t in enumerate(tracks)
        if t.get("index", i + 1) not in fully_done
    ]

    if not songs_input:
        _write_progress(project_id, {
            "status": "completed", "phase": "done",
            "completed_batches": 0, "tracks_collected": 0, "errors": [],
        })
        return

    total = len(songs_input)
    skipped = len(tracks) - total
    if skipped:
        logger.info(f"이미 완료 {skipped}곡 건너뜀, {total}곡 생성 예정")

    project_dir = _DIR / "storage" / "projects" / project_id / "tracks"
    project_dir.mkdir(parents=True, exist_ok=True)

    task_tracker = {
        "status": "running",
        "phase": "creating",
        "total_batches": total,
        "completed_batches": 0,
        "tracks_collected": 0,
        "current_song": "",
        "errors": [],
    }
    _write_progress(project_id, task_tracker)

    # ═══════════════════════════════════════════════════
    # 브라우저 1개 공유 — Creator + Collector 동시 사용
    # ═══════════════════��═══════════════════════════════
    sp = _session_path()
    if not sp.exists():
        _write_progress(project_id, {"status": "failed", "phase": "init", "errors": ["Suno 세션 없음"]})
        return

    exe = _find_exe()
    pw = await async_playwright().start()

    try:
        browser = await pw.chromium.launch(
            executable_path=exe,
            headless=False,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--exclude-switches=enable-automation",
                "--no-first-run",
                "--disable-infobars",
            ],
        )
        context = await browser.new_context(
            storage_state=str(sp),
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/136.0.0.0 Safari/537.36 Edg/136.0.0.0"
            ),
        )

        # 에이전트 생성 (같은 context 공유)
        creator = SunoCreatorAgent(context)
        collector = SunoCollectorAgent(context)

        created_count = 0

        def on_creator_progress(info: dict):
            nonlocal created_count
            created_count = info.get("completed", 0)
            task_tracker["completed_batches"] = created_count
            task_tracker["current_song"] = info.get("current_title", "")
            task_tracker["phase"] = "creating"
            _write_progress(project_id, task_tracker)

        def on_song_created(result: dict):
            """Creator가 곡 하나 생성 완료 시 → Collector 큐에 추가."""
            if created_count >= PARALLEL_START_AFTER:
                collector.enqueue(result)

        def on_collector_progress(info: dict):
            task_tracker["tracks_collected"] = info.get("completed", 0) * 2
            task_tracker["phase"] = "collecting" if task_tracker["phase"] != "creating" else "creating"
            _write_progress(project_id, task_tracker)

        # ═══════════════════════════════════════════
        # Creator + Collector 병렬 실행
        # ══════════════════��════════════════════════
        logger.info(f"시작: {total}곡 (Creator {PARALLEL_START_AFTER}곡 후 Collector 병렬)")

        # Collector를 백그라운드 태스크로 실행
        collector_task = asyncio.create_task(
            collector.run_parallel(
                output_dir=str(project_dir),
                progress_callback=on_collector_progress,
            )
        )

        # Creator 실행 (완료까지 대기)
        creation_results = await creator.create_all(
            songs=songs_input,
            progress_callback=on_creator_progress,
            on_song_created=on_song_created,
        )

        # Creator 완료 → 처음 3곡(병렬 전) + 나머지 실패 곡 Collector에 추가
        early_songs = [r for r in creation_results[:PARALLEL_START_AFTER] if r["status"] == "created"]
        for song in early_songs:
            collector.enqueue(song)

        # Collector 종료 시그널
        collector.stop()
        await collector_task

        # Creator 탭 정리
        await creator.close_all_tabs()

        download_results = collector.get_results()
        downloaded = len([r for r in download_results if r["status"] == "completed"])
        created = len([r for r in creation_results if r["status"] == "created"])

        logger.info(f"Creator: {created}/{total}곡, Collector: {downloaded}파일")

        # state.json에 저장
        current_state = state_manager.get(project_id) or {}
        old_tracks = current_state.get("suno_tracks") or []
        new_keys = {(r.get("index"), r.get("slot")) for r in download_results}
        merged = [t for t in old_tracks if (t.get("index"), t.get("slot")) not in new_keys]
        merged.extend(download_results)
        merged.sort(key=lambda t: (t.get("index", 0), t.get("slot", 0)))
        state_manager.update(project_id, {"suno_tracks": merged})

        # ═══════════════════════════════════════════
        # Phase 3: QA Agent
        # ═══════════════════���═══════════════════════
        task_tracker["phase"] = "verifying"
        _write_progress(project_id, task_tracker)

        qa_report = suno_qa_agent.verify(project_id)
        fix_result = suno_qa_agent.fix_links(project_id)

        task_tracker["status"] = "completed"
        task_tracker["phase"] = "done"
        task_tracker["tracks_collected"] = downloaded
        task_tracker["qa_report"] = {
            "status": qa_report["status"],
            "total_files": qa_report["total_files"],
            "expected_files": qa_report["expected_files"],
            "missing_count": len(qa_report["missing"]),
            "fixed_links": fix_result["fixed"],
        }
        _write_progress(project_id, task_tracker)

        logger.info(f"완료: 생성 {created}/{total}, 다운 {downloaded}, QA {qa_report['status']}")

        # 브라우저 정리
        await context.close()
        await browser.close()

    except Exception as e:
        import traceback as _tb
        err = _tb.format_exc()
        task_tracker["status"] = "failed"
        task_tracker["errors"].append(f"[{type(e).__name__}] {e}")
        task_tracker["traceback"] = err
        _write_progress(project_id, task_tracker)
        logger.error(f"실패: {e}\n{err}")
    finally:
        await pw.stop()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python _suno_batch_runner.py <project_id>", file=sys.stderr)
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
