"""
Suno 오케스트레이터 — 효율적 워크플로우.

1. QA 스캔 (로컬 파일 확인)
2. Collector (탭 1개) — Suno에 이미 있는 곡 먼저 다운
3. QA 재스캔
4. Creator (탭 1개 재사용) — 미생성 곡만 Create
5. 2분 대기 (Suno 처리 시간)
6. Collector 다시 — 새로 생성된 곡 다운
7. QA 최종 검수 → 미완료 있으면 4번으로 (최대 5라운드)

핵심: 탭은 항상 1개만. 열고닫기 최소화. Collector 먼저.

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

MAX_ROUNDS = 5


def _progress_path(pid: str) -> Path:
    return _DIR / "storage" / "projects" / pid / "_suno_progress.json"


def _write(pid: str, data: dict) -> None:
    p = _progress_path(pid)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _scan_missing(all_tracks: list[dict], tracks_dir: Path) -> list[dict]:
    """로컬 파일 기반으로 v1+v2 모두 없는 곡 추출."""
    files = list(tracks_dir.glob("*.mp3")) if tracks_dir.exists() else []
    missing = []
    for i, t in enumerate(all_tracks):
        idx = t.get("index", i + 1)
        v1 = any(f.name.startswith(f"{idx:02d}_") and "_v1.mp3" in f.name for f in files)
        v2 = any(f.name.startswith(f"{idx:02d}_") and "_v2.mp3" in f.name for f in files)
        if not (v1 and v2):
            missing.append(t)
    return missing


async def main(project_id: str) -> None:
    from core.state_manager import state_manager
    from browser.suno_automation import _find_exe, _session_path
    from agents.suno_creator import SunoCreatorAgent
    from agents.suno_collector import SunoCollectorAgent
    from agents.suno_qa import suno_qa_agent

    state = state_manager.get(project_id)
    if not state:
        _write(project_id, {"status": "failed", "errors": ["프로젝트 없음"]})
        return

    all_tracks = state.get("designed_tracks") or []
    channel_id = state.get("channel_id", "")
    has_lyrics = False
    ch_path = _DIR / "storage" / "channels" / f"{channel_id}.json"
    if ch_path.exists():
        has_lyrics = json.loads(ch_path.read_text(encoding="utf-8")).get("has_lyrics", False)

    if not all_tracks:
        _write(project_id, {"status": "failed", "errors": ["설계된 트랙 없음"]})
        return

    total = len(all_tracks)
    tracks_dir = _DIR / "storage" / "projects" / project_id / "tracks"
    tracks_dir.mkdir(parents=True, exist_ok=True)

    sp = _session_path()
    if not sp.exists():
        _write(project_id, {"status": "failed", "errors": ["Suno 세션 없음"]})
        return

    tracker = {
        "status": "running", "phase": "checking",
        "total_designed": total, "total_batches": 0,
        "completed_batches": 0, "tracks_collected": 0,
        "current_song": "", "round": 0, "errors": [],
    }
    _write(project_id, tracker)

    def update(phase: str, **kw):
        tracker["phase"] = phase
        tracker.update(kw)
        _write(project_id, tracker)

    def save_results(results: list[dict]):
        """다운로드 결과를 state.json에 병합."""
        cur = state_manager.get(project_id) or {}
        old = cur.get("suno_tracks") or []
        keys = {(r.get("index"), r.get("slot")) for r in results}
        merged = [t for t in old if (t.get("index"), t.get("slot")) not in keys]
        merged.extend(results)
        merged.sort(key=lambda t: (t.get("index", 0), t.get("slot", 0)))
        state_manager.update(project_id, {"suno_tracks": merged})

    for rnd in range(1, MAX_ROUNDS + 1):
        tracker["round"] = rnd

        # ── Phase 1: QA 스캔 ──
        update("checking", current_song="파일 확인 중...")
        missing = _scan_missing(all_tracks, tracks_dir)
        if not missing:
            logger.info(f"라운드 {rnd}: 전곡 완료!")
            break
        logger.info(f"라운드 {rnd}: {len(missing)}/{total}곡 미완료")
        tracker["total_batches"] = len(missing)

        # ── 브라우저 열기 (라운드당 1회) ──
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
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/136.0.0.0 Edg/136.0.0.0",
            )

            # ── Phase 2: Collector 먼저 — Suno에 이미 있는 곡 다운 ──
            update("collecting", current_song="Suno 검색 중...")
            collector = SunoCollectorAgent(context)

            # 기존 clip ID 수집
            existing = (state_manager.get(project_id) or {}).get("suno_tracks", [])
            collector.set_known_ids({s.get("suno_id", "") for s in existing if s.get("suno_id")})

            songs_for_search = [
                {"title": t.get("title", ""), "index": t.get("index", i+1)}
                for i, t in enumerate(missing)
            ]

            def on_collect(info):
                tracker["tracks_collected"] = len([r for r in collector.get_results() if r.get("status") == "completed"])
                tracker["current_song"] = info.get("current_title", "")
                _write(project_id, tracker)

            collect_results = await collector.collect_all(
                songs=songs_for_search,
                output_dir=str(tracks_dir),
                progress_callback=on_collect,
            )
            save_results(collect_results)
            await collector.close()

            # ── Phase 3: QA 재스캔 — 아직 미완료인 곡만 Creator에 전달 ──
            still_missing = _scan_missing(all_tracks, tracks_dir)
            if not still_missing:
                logger.info(f"라운드 {rnd}: Collector로 전부 해결!")
                await context.close()
                await browser.close()
                await pw.stop()
                break

            logger.info(f"라운드 {rnd}: Collector 후 {len(still_missing)}곡 미완료 → Creator 실행")

            # ── Phase 4: Creator — 미생성 곡만 Create (탭 1개) ──
            update("creating", total_batches=len(still_missing), completed_batches=0)
            creator = SunoCreatorAgent(context)

            songs_to_create = [
                {
                    "title": t.get("title", f"Track {t.get('index', i+1)}"),
                    "lyrics": t.get("lyrics", "") if has_lyrics else "",
                    "suno_prompt": t.get("suno_prompt", ""),
                    "is_instrumental": not has_lyrics,
                    "index": t.get("index", i + 1),
                }
                for i, t in enumerate(still_missing)
            ]

            def on_create(info):
                tracker["completed_batches"] = info.get("completed", 0)
                tracker["current_song"] = info.get("current_title", "")
                _write(project_id, tracker)

            creation_results = await creator.create_all(
                songs=songs_to_create,
                progress_callback=on_create,
            )
            await creator.close()

            created = len([r for r in creation_results if r["status"] == "submitted"])
            logger.info(f"라운드 {rnd}: {created}곡 Create 완료, Suno 처리 대기 중...")

            # ── Phase 5: 대기 (Suno가 곡을 처리할 시간) ──
            if created > 0:
                update("waiting", current_song=f"Suno 처리 대기 ({created}곡)...")
                await asyncio.sleep(120)  # 2분 대기

            # ── Phase 6: Collector 다시 — 새로 생성된 곡 다운 ──
            update("collecting", current_song="새 곡 다운로드 중...")
            collector2 = SunoCollectorAgent(context)
            collector2.set_known_ids(collector._known_ids)

            collect2_results = await collector2.collect_all(
                songs=songs_for_search,
                output_dir=str(tracks_dir),
                progress_callback=on_collect,
            )
            save_results(collect2_results)
            await collector2.close()

            # 브라우저 닫기
            await context.close()
            await browser.close()

        except Exception as e:
            import traceback as _tb
            tracker["errors"].append(f"R{rnd}: [{type(e).__name__}] {e}")
            logger.error(f"라운드 {rnd} 에러: {e}\n{_tb.format_exc()}")
        finally:
            await pw.stop()

        # ── QA 검수 + 자동 연결 ──
        update("verifying")
        suno_qa_agent.fix_links(project_id)
        qa = suno_qa_agent.verify(project_id)
        done = len([t for t in qa.get("tracks", []) if t["status"] == "complete"])
        logger.info(f"라운드 {rnd}: {done}/{total}곡 완성")

        if done >= total:
            break
        await asyncio.sleep(10)

    # ── 최종 보고 ──
    final = suno_qa_agent.verify(project_id)
    suno_qa_agent.fix_links(project_id)
    complete = len([t for t in final.get("tracks", []) if t["status"] == "complete"])
    tracker.update({
        "status": "completed", "phase": "done",
        "tracks_collected": final["total_files"],
        "qa_report": {"status": final["status"], "total_files": final["total_files"],
                       "expected_files": final["expected_files"], "complete_count": complete},
    })
    _write(project_id, tracker)
    logger.info(f"종료: {final['total_files']}/{final['expected_files']} 파일, {tracker['round']} 라운드")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python _suno_batch_runner.py <project_id>", file=sys.stderr)
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
