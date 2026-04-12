"""
Suno 일괄생성 오케스트레이터 — 3개 에이전트를 순서대로 실행.

1. Creator Agent → 순차적 곡 생성 (clip ID 수집)
2. Collector Agent → 곡 다운로드 (v1, v2)
3. QA Agent → 파일 검증 + 자동 연결

별도 프로세스로 실행 (Windows ProactorEventLoop 격리):
    python _suno_batch_runner.py <project_id>
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
logger = logging.getLogger("suno_orchestrator")


def _progress_path(project_id: str) -> Path:
    return _DIR / "storage" / "projects" / project_id / "_suno_progress.json"


def _write_progress(project_id: str, data: dict) -> None:
    p = _progress_path(project_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


async def main(project_id: str) -> None:
    from core.state_manager import state_manager
    from agents.suno_creator import SunoCreatorAgent
    from agents.suno_collector import SunoCollectorAgent
    from agents.suno_qa import suno_qa_agent

    state = state_manager.get(project_id)
    if not state:
        _write_progress(project_id, {"status": "failed", "phase": "init", "errors": ["프로젝트 없음"]})
        return

    tracks = state.get("designed_tracks") or []
    channel_id = state.get("channel_id", "")

    # 채널에서 has_lyrics 확인
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
        logger.info(f"모든 곡이 이미 완료됨: {project_id}")
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

    def on_creator_progress(info: dict):
        task_tracker["completed_batches"] = info.get("completed", 0)
        task_tracker["current_song"] = info.get("current_title", "")
        task_tracker["phase"] = "creating"
        _write_progress(project_id, task_tracker)

    def on_collector_progress(info: dict):
        task_tracker["tracks_collected"] = info.get("completed", 0) * 2
        task_tracker["current_song"] = info.get("current_title", "")
        task_tracker["phase"] = "collecting"
        _write_progress(project_id, task_tracker)

    try:
        # ═══════════════════════════════════════════
        # Phase 1: Creator Agent — 순차적 곡 생성
        # ═══════════════════════════════════════════
        logger.info(f"Phase 1: Creator Agent 시작 ({total}곡)")
        task_tracker["phase"] = "creating"
        _write_progress(project_id, task_tracker)

        async with SunoCreatorAgent() as creator:
            creation_results = await creator.create_all(
                songs=songs_input,
                progress_callback=on_creator_progress,
            )

        created_count = len([r for r in creation_results if r["status"] == "created"])
        logger.info(f"Phase 1 완료: {created_count}/{total}곡 생성됨")

        # ═══════════════════════════════════════════
        # Phase 2: Collector Agent — 다운로드
        # ═══════════════════════════════════════════
        logger.info(f"Phase 2: Collector Agent 시작")
        task_tracker["phase"] = "collecting"
        _write_progress(project_id, task_tracker)

        async with SunoCollectorAgent() as collector:
            download_results = await collector.collect_all(
                creation_results=creation_results,
                output_dir=str(project_dir),
                progress_callback=on_collector_progress,
            )

        downloaded = len([r for r in download_results if r["status"] == "completed"])
        logger.info(f"Phase 2 완료: {downloaded}개 파일 다운로드됨")

        # state.json에 저장
        current_state = state_manager.get(project_id) or {}
        old_tracks = current_state.get("suno_tracks") or []
        new_keys = {(r.get("index"), r.get("slot")) for r in download_results}
        merged = [t for t in old_tracks if (t.get("index"), t.get("slot")) not in new_keys]
        merged.extend(download_results)
        merged.sort(key=lambda t: (t.get("index", 0), t.get("slot", 0)))
        state_manager.update(project_id, {"suno_tracks": merged})

        # ═══════════════════════════════════════════
        # Phase 3: QA Agent — 검수 + 자동 연결
        # ═══════════════════════════════════════════
        logger.info("Phase 3: QA Agent 시작")
        task_tracker["phase"] = "verifying"
        _write_progress(project_id, task_tracker)

        qa_report = suno_qa_agent.verify(project_id)
        fix_result = suno_qa_agent.fix_links(project_id)

        # 최종 결과
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

        logger.info(
            f"전체 완료: {project_id} — "
            f"생성 {created_count}/{total}, "
            f"다운로드 {downloaded}, "
            f"QA {qa_report['status']}"
        )

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
