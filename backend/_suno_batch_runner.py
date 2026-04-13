"""
Suno 오케스트레이터 — 최초 생성 / 재생성 자동 구분.

최초 생성 (곡 파일 0개):
  1. Creator: 전곡 순차 Create (탭 1개)
  2. Collector: 생성된 곡 다운 (폴링 루프)
  3. QA 검수

재생성 (일부 곡 존재):
  1. Collector: Suno에 있지만 미다운 곡 먼저 수집
  2. Creator: 미생성 곡만 Create
  3. Collector: 새로 생성된 곡 수집 (폴링)
  4. QA 검수 → 미완료 시 반복

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

MAX_ROUNDS = 3
POLL_SEC = 30
MAX_IDLE = 5


def _p(pid: str) -> Path:
    return _DIR / "storage" / "projects" / pid / "_suno_progress.json"


def _w(pid: str, d: dict) -> None:
    p = _p(pid)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")


def _count(all_tracks, tracks_dir):
    files = list(tracks_dir.glob("*.mp3")) if tracks_dir.exists() else []
    done, missing = 0, []
    for i, t in enumerate(all_tracks):
        idx = t.get("index", i + 1)
        v1 = any(f.name.startswith(f"{idx:02d}_") and "_v1.mp3" in f.name and f.stat().st_size > 10_000 for f in files)
        v2 = any(f.name.startswith(f"{idx:02d}_") and "_v2.mp3" in f.name and f.stat().st_size > 10_000 for f in files)
        if v1 and v2:
            done += 1
        else:
            missing.append(t)
    return done, missing


async def _collector_loop(context, project_id, all_tracks, tracks_dir, tracker, save_fn, stop_event):
    """독립 Collector 폴링 루프."""
    from agents.suno_collector import SunoCollectorAgent
    from core.state_manager import state_manager

    collector = SunoCollectorAgent(context)
    existing = (state_manager.get(project_id) or {}).get("suno_tracks", [])
    collector.set_known_ids({s.get("suno_id", "") for s in existing if s.get("suno_id")})
    idle = 0

    while not stop_event.is_set():
        _, cur_missing = _count(all_tracks, tracks_dir)
        if not cur_missing:
            logger.info("[Collector] 전곡 완료")
            break

        songs = [{"title": t.get("title", ""), "index": t.get("index", i+1)} for i, t in enumerate(cur_missing)]
        prev = len([r for r in collector.get_results() if r.get("status") == "completed"])

        tracker["current_song"] = f"검색 중 ({len(songs)}곡)"
        if tracker["phase"] != "creating":
            tracker["phase"] = "collecting"
        _w(project_id, tracker)

        await collector.collect_all(
            songs=songs, output_dir=str(tracks_dir),
            progress_callback=lambda info: (
                tracker.update(tracks_collected=len([r for r in collector.get_results() if r.get("status") == "completed"]),
                               current_song=info.get("current_title", "")),
                _w(project_id, tracker),
            ) and None,
        )

        results = collector.get_results()
        save_fn(results)
        now = len([r for r in results if r.get("status") == "completed"])
        tracker["tracks_collected"] = now
        _w(project_id, tracker)

        if now > prev:
            idle = 0
            logger.info(f"[Collector] +{now - prev}개, 총 {now}개")
        else:
            idle += 1

        if idle >= MAX_IDLE:
            logger.info(f"[Collector] idle {MAX_IDLE}회, 종료")
            break

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=POLL_SEC)
            break
        except asyncio.TimeoutError:
            pass

    await collector.close()


async def main(project_id: str) -> None:
    from core.state_manager import state_manager
    from browser.suno_automation import _find_exe, _session_path
    from agents.suno_creator import SunoCreatorAgent
    from agents.suno_qa import suno_qa_agent

    state = state_manager.get(project_id)
    if not state:
        _w(project_id, {"status": "failed", "errors": ["프로젝트 없음"]})
        return

    all_tracks = state.get("designed_tracks") or []
    channel_id = state.get("channel_id", "")
    has_lyrics = False
    ch_path = _DIR / "storage" / "channels" / f"{channel_id}.json"
    if ch_path.exists():
        has_lyrics = json.loads(ch_path.read_text(encoding="utf-8")).get("has_lyrics", False)

    if not all_tracks:
        _w(project_id, {"status": "failed", "errors": ["트랙 없음"]})
        return

    total = len(all_tracks)
    tdir = _DIR / "storage" / "projects" / project_id / "tracks"
    tdir.mkdir(parents=True, exist_ok=True)
    sp = _session_path()
    if not sp.exists():
        _w(project_id, {"status": "failed", "errors": ["Suno 세션 없음"]})
        return

    tracker = {"status": "running", "phase": "checking", "total_designed": total,
               "total_batches": 0, "completed_batches": 0, "tracks_collected": 0,
               "current_song": "", "round": 0, "errors": []}

    def save_fn(results):
        # index/slot이 없는 항목 필터링
        valid = [r for r in results if r.get("index") and r.get("slot")]
        if not valid:
            return
        cur = state_manager.get(project_id) or {}
        old = cur.get("suno_tracks") or []
        # 기존에서도 index/slot 없는 것 제거
        old = [t for t in old if t.get("index") and t.get("slot")]
        keys = {(r["index"], r["slot"]) for r in valid}
        merged = [t for t in old if (t.get("index"), t.get("slot")) not in keys]
        merged.extend(valid)
        merged.sort(key=lambda t: (t.get("index", 0), t.get("slot", 0)))
        state_manager.update(project_id, {"suno_tracks": merged})

    done_init, _ = _count(all_tracks, tdir)
    is_first = done_init == 0
    logger.info(f"모드: {'최초 생성' if is_first else '재생성'} ({done_init}/{total} 완료)")

    for rnd in range(1, MAX_ROUNDS + 1):
        tracker["round"] = rnd
        done_now, missing = _count(all_tracks, tdir)
        if not missing:
            break

        tracker["total_batches"] = len(missing)
        _w(project_id, tracker)

        exe = _find_exe()
        pw = await async_playwright().start()
        try:
            browser = await pw.chromium.launch(
                executable_path=exe, headless=False,
                args=["--disable-blink-features=AutomationControlled", "--no-first-run", "--disable-infobars"],
            )
            context = await browser.new_context(
                storage_state=str(sp), viewport={"width": 1280, "height": 900},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/136.0.0.0 Edg/136.0.0.0",
            )
            stop_ev = asyncio.Event()

            if is_first and rnd == 1:
                # ═══════════════════════════════
                # 최초 생성: Creator 먼저 → Collector
                # ═══════════════════════════════
                logger.info(f"[최초] Creator: {len(missing)}곡 생성")
                tracker["phase"] = "creating"
                _w(project_id, tracker)

                songs = [{
                    "title": t.get("title", ""), "lyrics": t.get("lyrics", "") if has_lyrics else "",
                    "suno_prompt": t.get("suno_prompt", ""), "is_instrumental": not has_lyrics,
                    "index": t.get("index", i+1),
                } for i, t in enumerate(missing)]

                creator = SunoCreatorAgent(context)
                await creator.create_all(
                    songs=songs,
                    progress_callback=lambda info: (
                        tracker.update(phase="creating", completed_batches=info.get("completed", 0),
                                       current_song=info.get("current_title", "")),
                        _w(project_id, tracker),
                    ) and None,
                )
                await creator.close()

                # Creator 완료 → Collector 폴링 시작
                logger.info("[최초] Creator 완료, Collector 폴링 시작")
                await _collector_loop(context, project_id, all_tracks, tdir, tracker, save_fn, stop_ev)

            else:
                # ═══════════════════════════════
                # 재생성: Collector 먼저 → Creator → Collector
                # ═══════════════════════════════

                # Phase A: Collector 먼저 (기존 곡 수집)
                logger.info(f"[재생성] Collector: 기존 곡 수집")
                collector_task = asyncio.create_task(
                    _collector_loop(context, project_id, all_tracks, tdir, tracker, save_fn, stop_ev)
                )

                # Collector에게 15초 선행 시간
                await asyncio.sleep(15)

                # Phase B: Creator (미생성만)
                _, still = _count(all_tracks, tdir)
                if still:
                    still_idx = {t.get("index", i+1) for i, t in enumerate(still)}
                    songs = [{
                        "title": t.get("title", ""), "lyrics": t.get("lyrics", "") if has_lyrics else "",
                        "suno_prompt": t.get("suno_prompt", ""), "is_instrumental": not has_lyrics,
                        "index": t.get("index", i+1),
                    } for i, t in enumerate(all_tracks) if t.get("index", i+1) in still_idx]

                    if songs:
                        logger.info(f"[재생성] Creator: {len(songs)}곡 생성")
                        tracker.update(phase="creating", total_batches=len(songs), completed_batches=0)
                        _w(project_id, tracker)

                        creator = SunoCreatorAgent(context)
                        await creator.create_all(
                            songs=songs,
                            progress_callback=lambda info: (
                                tracker.update(phase="creating", completed_batches=info.get("completed", 0),
                                               current_song=info.get("current_title", "")),
                                _w(project_id, tracker),
                            ) and None,
                        )
                        await creator.close()
                        logger.info("[재생성] Creator 완료")

                # Phase C: Collector 계속 수집 (Creator가 만든 곡 + 수동 생성 곡)
                # Collector가 자동 종료될 때까지 대기 (MAX_IDLE 또는 전곡 완료)
                if not collector_task.done():
                    # Collector에게 전곡 완료 또는 idle까지 대기
                    logger.info("[재생성] Collector 수집 대기 중...")
                    for _ in range(10):  # 최대 5분
                        d, _ = _count(all_tracks, tdir)
                        if d >= total:
                            stop_ev.set()
                            break
                        await asyncio.sleep(30)
                    stop_ev.set()
                    await collector_task

            await context.close()
            await browser.close()

        except Exception as e:
            import traceback as _tb
            tracker["errors"].append(f"R{rnd}: {e}")
            logger.error(f"R{rnd}: {e}\n{_tb.format_exc()}")
        finally:
            await pw.stop()

        # 라운드 끝 검수 (cleanup + fix + verify)
        suno_qa_agent.final_check(project_id)
        d, _ = _count(all_tracks, tdir)
        logger.info(f"라운드 {rnd}: {d}/{total}곡")
        if d >= total:
            break
        is_first = False
        await asyncio.sleep(5)

    # 최종 검수 (중복/고아/빈파일 정리 + 연결 + 검증)
    update(phase="verifying", current_song="최종 검수 중...")
    final = suno_qa_agent.final_check(project_id)
    c = len([t for t in final.get("tracks", []) if t["status"] == "complete"])
    tracker.update(status="completed", phase="done", tracks_collected=final["total_files"],
                   qa_report={
                       "status": final["status"],
                       "total_files": final["total_files"],
                       "expected_files": final["expected_files"],
                       "complete_count": c,
                       "cleanup": final.get("cleanup", {}),
                   })
    _w(project_id, tracker)
    logger.info(f"종료: {c}/{total}곡, {tracker['round']}라운드, cleanup={final.get('cleanup', {})}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python _suno_batch_runner.py <project_id>", file=sys.stderr)
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
