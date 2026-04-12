"""
Suno 일괄생성 오케스트레이터 — QA 주도 재시도 루프.

Creator: Create 클릭만 (clip 수집 안 함) → 빠르게 다음 곡으로
Collector: Suno 검색으로 곡 찾아서 다운로드 (Creator와 병렬)
QA: 검수 후 미완료 있으면 재시도

    python _suno_batch_runner.py <project_id>
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import sys
from pathlib import Path

from playwright.async_api import async_playwright

_DIR = Path(__file__).parent
sys.path.insert(0, str(_DIR))

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

logging.basicConfig(level=logging.INFO, stream=sys.stderr)
logger = logging.getLogger("suno_orchestrator")

COLLECTOR_START_AFTER = 3
MAX_RETRY_ROUNDS = 5


def _progress_path(project_id: str) -> Path:
    return _DIR / "storage" / "projects" / project_id / "_suno_progress.json"


def _write_progress(project_id: str, data: dict) -> None:
    p = _progress_path(project_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _get_incomplete_songs(project_id: str, all_tracks: list[dict], has_lyrics: bool, tracks_dir: Path) -> list[dict]:
    """파일 기반으로 미완료 곡 추출 (v1+v2 모두 있는 곡만 완료)."""
    existing = list(tracks_dir.glob("*.mp3")) if tracks_dir.exists() else []
    songs = []
    for i, t in enumerate(all_tracks):
        idx = t.get("index", i + 1)
        title = t.get("title", "")
        safe = re.sub(r'[\u4E00-\u9FFF\u3400-\u4DBF\\/:*?"<>|]', "_", title)
        v1 = any(f.name.startswith(f"{idx:02d}_") and "_v1.mp3" in f.name for f in existing)
        v2 = any(f.name.startswith(f"{idx:02d}_") and "_v2.mp3" in f.name for f in existing)
        if v1 and v2:
            continue
        songs.append({
            "title": title,
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
        "status": "running", "phase": "checking",
        "total_designed": total_designed, "total_batches": 0,
        "completed_batches": 0, "tracks_collected": 0,
        "current_song": "", "round": 0, "errors": [],
    }
    _write_progress(project_id, task_tracker)

    for round_num in range(1, MAX_RETRY_ROUNDS + 1):
        task_tracker["round"] = round_num
        task_tracker["phase"] = "checking"
        _write_progress(project_id, task_tracker)

        songs_todo = _get_incomplete_songs(project_id, all_tracks, has_lyrics, project_dir)
        if not songs_todo:
            logger.info(f"라운드 {round_num}: 모든 곡 완료!")
            break

        logger.info(f"라운드 {round_num}: {len(songs_todo)}/{total_designed}곡 미완료")
        task_tracker["total_batches"] = len(songs_todo)
        task_tracker["completed_batches"] = 0

        exe = _find_exe()
        pw = await async_playwright().start()

        try:
            browser = await pw.chromium.launch(
                executable_path=exe, headless=False,
                args=["--disable-blink-features=AutomationControlled", "--no-first-run", "--disable-infobars"],
            )
            context = await browser.new_context(
                storage_state=str(sp),
                viewport={"width": 1280, "height": 900},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/136.0.0.0 Safari/537.36 Edg/136.0.0.0",
            )

            creator = SunoCreatorAgent(context)
            collector = SunoCollectorAgent(context)

            # 기존 clip ID 수집 (중복 다운로드 방지)
            existing_suno = (state_manager.get(project_id) or {}).get("suno_tracks", [])
            collector.set_known_ids({s.get("suno_id", "") for s in existing_suno if s.get("suno_id")})

            created_count = 0

            def on_creator_progress(info):
                nonlocal created_count
                created_count = info.get("completed", 0)
                task_tracker["completed_batches"] = created_count
                task_tracker["current_song"] = info.get("current_title", "")
                task_tracker["phase"] = "creating"
                _write_progress(project_id, task_tracker)

            def on_song_created(result):
                if created_count >= COLLECTOR_START_AFTER:
                    collector.enqueue(result)

            def on_collector_progress(info):
                task_tracker["tracks_collected"] = len([r for r in collector.get_results() if r.get("status") == "completed"])
                task_tracker["phase"] = "collecting" if task_tracker["phase"] != "creating" else "creating"
                _write_progress(project_id, task_tracker)

            # Collector 병렬 시작
            collector_task = asyncio.create_task(
                collector.run_parallel(
                    output_dir=str(project_dir),
                    title_to_index={s["title"]: s["index"] for s in songs_todo},
                    progress_callback=on_collector_progress,
                )
            )

            # Creator 실행 (Create만 클릭 → 빠르게 순회)
            creation_results = await creator.create_all(
                songs=songs_todo,
                progress_callback=on_creator_progress,
                on_song_created=on_song_created,
            )

            # Creator 완료 → Collector에 초기 곡들도 추가
            early_songs = [r for r in creation_results[:COLLECTOR_START_AFTER] if r["status"] == "submitted"]
            for song in early_songs:
                collector.enqueue(song)

            collector.stop()
            await collector_task

            # Creator 탭 정리 → 브라우저 닫기
            await creator.close_all_tabs()

            # Collector 결과 저장
            download_results = collector.get_results()
            current = state_manager.get(project_id) or {}
            old = current.get("suno_tracks") or []
            new_keys = {(r.get("index"), r.get("slot")) for r in download_results}
            merged = [t for t in old if (t.get("index"), t.get("slot")) not in new_keys]
            merged.extend(download_results)
            merged.sort(key=lambda t: (t.get("index", 0), t.get("slot", 0)))
            state_manager.update(project_id, {"suno_tracks": merged})

            # Collector가 못 찾은 곡들 재시도 (Creator 완료 후 시간 지났으니 Suno에서 생성 완료됐을 수 있음)
            task_tracker["phase"] = "collecting"
            _write_progress(project_id, task_tracker)
            await collector.collect_remaining(
                songs=songs_todo,
                output_dir=str(project_dir),
                progress_callback=on_collector_progress,
            )

            # 추가 다운로드 결과 저장
            all_results = collector.get_results()
            current2 = state_manager.get(project_id) or {}
            old2 = current2.get("suno_tracks") or []
            new_keys2 = {(r.get("index"), r.get("slot")) for r in all_results}
            merged2 = [t for t in old2 if (t.get("index"), t.get("slot")) not in new_keys2]
            merged2.extend(all_results)
            merged2.sort(key=lambda t: (t.get("index", 0), t.get("slot", 0)))
            state_manager.update(project_id, {"suno_tracks": merged2})

            await context.close()
            await browser.close()

        except Exception as e:
            import traceback as _tb
            task_tracker["errors"].append(f"라운드{round_num}: [{type(e).__name__}] {e}")
            logger.error(f"라운드 {round_num} 에러: {e}\n{_tb.format_exc()}")
        finally:
            await pw.stop()

        # QA 검수 + 자동 연결
        task_tracker["phase"] = "verifying"
        _write_progress(project_id, task_tracker)
        suno_qa_agent.fix_links(project_id)
        qa = suno_qa_agent.verify(project_id)
        done = len([t for t in qa.get("tracks", []) if t["status"] == "complete"])
        logger.info(f"라운드 {round_num} QA: {done}/{total_designed}곡 완성")

        if done >= total_designed:
            break
        await asyncio.sleep(10)

    # 최종 보고
    final_qa = suno_qa_agent.verify(project_id)
    suno_qa_agent.fix_links(project_id)
    task_tracker["status"] = "completed"
    task_tracker["phase"] = "done"
    task_tracker["qa_report"] = {
        "status": final_qa["status"],
        "total_files": final_qa["total_files"],
        "expected_files": final_qa["expected_files"],
        "complete_count": len([t for t in final_qa["tracks"] if t["status"] == "complete"]),
    }
    _write_progress(project_id, task_tracker)
    logger.info(f"종료: {final_qa['total_files']}/{final_qa['expected_files']} 파일, {task_tracker['round']} 라운드")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python _suno_batch_runner.py <project_id>", file=sys.stderr)
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
