"""
Suno 일괄생성 오케스트레이터 — QA 주도 재시도 루프.

흐름:
  1. QA Agent가 현재 상태 검수 (어디까지 완료?)
  2. 미완료 곡만 추출
  3. Creator Agent → 미완료 곡만 생성 (탭 추가 방식)
  4. Collector Agent → 병렬 다운로드
  5. QA 재검수 → 아직 미완료 있으면 → 2번으로 돌아감
  6. 전부 완료 or 최대 재시도 초과 → 종료

중간에 끊겨도 다시 실행하면 QA가 진행 상황을 파악하고 이어서 진행.

별도 프로세스:
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
MAX_RETRY_ROUNDS = 5      # 최대 재시도 라운드


def _progress_path(project_id: str) -> Path:
    return _DIR / "storage" / "projects" / project_id / "_suno_progress.json"


def _write_progress(project_id: str, data: dict) -> None:
    p = _progress_path(project_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _get_incomplete_songs(
    project_id: str,
    all_tracks: list[dict],
    has_lyrics: bool,
) -> list[dict]:
    """QA 기반으로 미완료 곡 목록 추출."""
    from agents.suno_qa import suno_qa_agent
    qa = suno_qa_agent.verify(project_id)

    # 완료된 index 집합
    done_indices = {
        t["index"] for t in qa.get("tracks", [])
        if t["status"] == "complete"
    }

    # 미완료 곡만 추출
    songs = []
    for i, t in enumerate(all_tracks):
        idx = t.get("index", i + 1)
        if idx in done_indices:
            continue
        songs.append({
            "title": t.get("title", f"Track {idx}"),
            "lyrics": t.get("lyrics", "") if has_lyrics else "",
            "suno_prompt": t.get("suno_prompt", ""),
            "is_instrumental": not has_lyrics,
            "index": idx,
        })

    return songs


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

    all_tracks = state.get("designed_tracks") or []
    channel_id = state.get("channel_id", "")

    has_lyrics = False
    channel_path = _DIR / "storage" / "channels" / f"{channel_id}.json"
    if channel_path.exists():
        ch = json.loads(channel_path.read_text(encoding="utf-8"))
        has_lyrics = ch.get("has_lyrics", False)

    if not all_tracks:
        _write_progress(project_id, {"status": "failed", "phase": "init", "errors": ["설계된 트랙 없음"]})
        return

    total_designed = len(all_tracks)
    project_dir = _DIR / "storage" / "projects" / project_id / "tracks"
    project_dir.mkdir(parents=True, exist_ok=True)

    sp = _session_path()
    if not sp.exists():
        _write_progress(project_id, {"status": "failed", "phase": "init", "errors": ["Suno 세션 없음"]})
        return

    task_tracker = {
        "status": "running",
        "phase": "checking",
        "total_designed": total_designed,
        "total_batches": 0,
        "completed_batches": 0,
        "tracks_collected": 0,
        "current_song": "",
        "round": 0,
        "errors": [],
    }
    _write_progress(project_id, task_tracker)

    # ═══════════════════════════════════════════
    # QA 주도 재시도 루프
    # ═══════════════════════════════════════════
    for round_num in range(1, MAX_RETRY_ROUNDS + 1):
        # Step 1: QA 검수 — 미완료 곡 확인
        task_tracker["phase"] = "checking"
        task_tracker["round"] = round_num
        _write_progress(project_id, task_tracker)

        songs_todo = _get_incomplete_songs(project_id, all_tracks, has_lyrics)

        if not songs_todo:
            logger.info(f"라운드 {round_num}: 모든 곡 완료!")
            break

        logger.info(f"라운드 {round_num}: {len(songs_todo)}/{total_designed}곡 미완료, 생성 시작")
        task_tracker["total_batches"] = len(songs_todo)
        task_tracker["completed_batches"] = 0

        # Step 2: 브라우저 열기
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
                if created_count >= PARALLEL_START_AFTER:
                    collector.enqueue(result)

            def on_collector_progress(info: dict):
                task_tracker["tracks_collected"] = info.get("completed", 0) * 2
                if task_tracker["phase"] != "creating":
                    task_tracker["phase"] = "collecting"
                _write_progress(project_id, task_tracker)

            # Step 3: Creator + Collector 병렬 실행
            collector_task = asyncio.create_task(
                collector.run_parallel(
                    output_dir=str(project_dir),
                    progress_callback=on_collector_progress,
                )
            )

            creation_results = await creator.create_all(
                songs=songs_todo,
                progress_callback=on_creator_progress,
                on_song_created=on_song_created,
            )

            # 병렬 시작 전 곡들을 Collector에 추가
            early_songs = [r for r in creation_results[:PARALLEL_START_AFTER] if r["status"] == "created"]
            for song in early_songs:
                collector.enqueue(song)

            collector.stop()
            await collector_task
            await creator.close_all_tabs()

            download_results = collector.get_results()

            # state.json에 저장
            current_state = state_manager.get(project_id) or {}
            old_tracks = current_state.get("suno_tracks") or []
            new_keys = {(r.get("index"), r.get("slot")) for r in download_results}
            merged = [t for t in old_tracks if (t.get("index"), t.get("slot")) not in new_keys]
            merged.extend(download_results)
            merged.sort(key=lambda t: (t.get("index", 0), t.get("slot", 0)))
            state_manager.update(project_id, {"suno_tracks": merged})

            # 브라우저 정리
            await context.close()
            await browser.close()

        except Exception as e:
            import traceback as _tb
            err = _tb.format_exc()
            task_tracker["errors"].append(f"라운드{round_num}: [{type(e).__name__}] {e}")
            logger.error(f"라운드 {round_num} 에러: {e}\n{err}")
        finally:
            await pw.stop()

        # Step 4: QA 검수 + 자동 연결
        task_tracker["phase"] = "verifying"
        _write_progress(project_id, task_tracker)

        suno_qa_agent.fix_links(project_id)
        qa = suno_qa_agent.verify(project_id)

        completed = len([t for t in qa.get("tracks", []) if t["status"] == "complete"])
        logger.info(f"라운드 {round_num} 완료: {completed}/{total_designed}곡 완성")

        if completed >= total_designed:
            logger.info("전체 완료!")
            break

        # 다음 라운드 전 잠시 대기
        logger.info(f"미완료 {total_designed - completed}곡, 10초 후 다음 라운드 시작")
        await asyncio.sleep(10)

    # ═══════════════════════════════════════════
    # 최종 QA 보고
    # ═══════════════════════════════════════════
    final_qa = suno_qa_agent.verify(project_id)
    suno_qa_agent.fix_links(project_id)

    task_tracker["status"] = "completed"
    task_tracker["phase"] = "done"
    task_tracker["qa_report"] = {
        "status": final_qa["status"],
        "total_files": final_qa["total_files"],
        "expected_files": final_qa["expected_files"],
        "missing_count": len(final_qa["missing"]),
        "complete_count": len([t for t in final_qa["tracks"] if t["status"] == "complete"]),
    }
    _write_progress(project_id, task_tracker)

    logger.info(
        f"전체 종료: {final_qa['total_files']}/{final_qa['expected_files']} 파일, "
        f"QA {final_qa['status']}, {task_tracker.get('round', 0)} 라운드"
    )


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python _suno_batch_runner.py <project_id>", file=sys.stderr)
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
