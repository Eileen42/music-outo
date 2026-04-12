"""
Suno 오케스트레이터 — Creator + Collector 독립 병렬.

Creator: 미생성 곡 순차 Create (실패해도 다음으로)
Collector: 독립 폴링 루프 — 30초마다 미다운 곡 Suno 검색 → 있으면 다운
  → Creator와 무관하게 동작. 사람이 수동 Create해도 자동 수집.

전체 흐름:
  1. QA 스캔 (미완료 곡 추출)
  2. Collector 루프 시작 (백그라운드)
  3. Creator 실행 (미생성 곡만)
  4. Creator 완료 → Collector가 나머지 수집할 때까지 대기
  5. QA 최종 검수 → 미완료 있으면 1번으로 (최대 3라운드)

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

MAX_ROUNDS = 3
COLLECTOR_POLL_SEC = 30
COLLECTOR_MAX_IDLE = 5  # 연속 N회 새 다운 없으면 종료


def _progress_path(pid: str) -> Path:
    return _DIR / "storage" / "projects" / pid / "_suno_progress.json"


def _write(pid: str, data: dict) -> None:
    p = _progress_path(pid)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _count_complete(all_tracks: list[dict], tracks_dir: Path) -> tuple[int, list[dict]]:
    """완료/미완료 곡 수 계산. (완료수, 미완료목록) 반환."""
    files = list(tracks_dir.glob("*.mp3")) if tracks_dir.exists() else []
    missing = []
    done = 0
    for i, t in enumerate(all_tracks):
        idx = t.get("index", i + 1)
        v1 = any(f.name.startswith(f"{idx:02d}_") and "_v1.mp3" in f.name and f.stat().st_size > 10_000 for f in files)
        v2 = any(f.name.startswith(f"{idx:02d}_") and "_v2.mp3" in f.name and f.stat().st_size > 10_000 for f in files)
        if v1 and v2:
            done += 1
        else:
            missing.append(t)
    return done, missing


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

    def update(**kw):
        tracker.update(kw)
        _write(project_id, tracker)

    def save_results(results: list[dict]):
        cur = state_manager.get(project_id) or {}
        old = cur.get("suno_tracks") or []
        keys = {(r.get("index"), r.get("slot")) for r in results}
        merged = [t for t in old if (t.get("index"), t.get("slot")) not in keys]
        merged.extend(results)
        merged.sort(key=lambda t: (t.get("index", 0), t.get("slot", 0)))
        state_manager.update(project_id, {"suno_tracks": merged})

    for rnd in range(1, MAX_ROUNDS + 1):
        tracker["round"] = rnd
        done_count, missing = _count_complete(all_tracks, tracks_dir)
        if not missing:
            logger.info(f"라운드 {rnd}: 전곡 완료!")
            break
        logger.info(f"라운드 {rnd}: {done_count}/{total} 완료, {len(missing)}곡 미완료")

        # ── 브라우저 열기 ──
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

            existing_ids = {s.get("suno_id", "") for s in (state_manager.get(project_id) or {}).get("suno_tracks", []) if s.get("suno_id")}

            # ══════════════════════════════════════════
            # Collector 독립 폴링 루프 (백그라운드)
            # ══════════════════════════════════════════
            collector_stop = asyncio.Event()

            async def collector_loop():
                """30초마다 미다운 곡을 Suno에서 검색하여 다운."""
                collector = SunoCollectorAgent(context)
                collector.set_known_ids(existing_ids.copy())
                idle_count = 0

                while not collector_stop.is_set():
                    _, cur_missing = _count_complete(all_tracks, tracks_dir)
                    if not cur_missing:
                        logger.info("[Collector] 모든 곡 완료!")
                        break

                    songs = [{"title": t.get("title", ""), "index": t.get("index", i+1)} for i, t in enumerate(cur_missing)]
                    update(phase="collecting", current_song=f"검색 중 ({len(songs)}곡)...")

                    prev_count = len([r for r in collector.get_results() if r.get("status") == "completed"])

                    await collector.collect_all(
                        songs=songs,
                        output_dir=str(tracks_dir),
                        progress_callback=lambda info: update(
                            tracks_collected=len([r for r in collector.get_results() if r.get("status") == "completed"]),
                            current_song=info.get("current_title", ""),
                        ),
                    )

                    # 결과 즉시 저장
                    new_results = collector.get_results()
                    save_results(new_results)
                    new_count = len([r for r in new_results if r.get("status") == "completed"])
                    update(tracks_collected=new_count)

                    if new_count > prev_count:
                        idle_count = 0
                        logger.info(f"[Collector] {new_count - prev_count}개 새로 다운, 총 {new_count}개")
                    else:
                        idle_count += 1
                        logger.info(f"[Collector] 새 다운 없음 (idle {idle_count}/{COLLECTOR_MAX_IDLE})")

                    if idle_count >= COLLECTOR_MAX_IDLE:
                        logger.info("[Collector] 최대 idle 도달, 종료")
                        break

                    # 검색 페이지 유지한 채 대기
                    try:
                        await asyncio.wait_for(collector_stop.wait(), timeout=COLLECTOR_POLL_SEC)
                        break  # stop 시그널 받으면 종료
                    except asyncio.TimeoutError:
                        pass  # 타임아웃 = 다음 폴링

                await collector.close()
                logger.info("[Collector] 루프 종료")

            collector_task = asyncio.create_task(collector_loop())

            # ══════════════════════════════════════════
            # Creator (미생성 곡만, 탭 1개)
            # ══════════════════════════════════════════
            # Collector가 이미 다운한 곡은 Creator에서 건너뛸 수 있도록
            # 파일 기반으로 판단
            songs_to_create = [
                {
                    "title": t.get("title", f"Track {t.get('index', i+1)}"),
                    "lyrics": t.get("lyrics", "") if has_lyrics else "",
                    "suno_prompt": t.get("suno_prompt", ""),
                    "is_instrumental": not has_lyrics,
                    "index": t.get("index", i + 1),
                }
                for i, t in enumerate(missing)
            ]

            # Creator 전에 잠시 대기 — Collector가 먼저 기존 곡 수집할 시간
            update(phase="collecting", total_batches=len(missing), completed_batches=0,
                   current_song="기존 곡 확인 중...")
            await asyncio.sleep(15)

            # Collector가 이미 해결한 곡 제외
            _, still_missing = _count_complete(all_tracks, tracks_dir)
            still_missing_idx = {t.get("index", i+1) for i, t in enumerate(still_missing)}
            songs_to_create = [s for s in songs_to_create if s["index"] in still_missing_idx]

            if songs_to_create:
                update(phase="creating", total_batches=len(songs_to_create), completed_batches=0)
                creator = SunoCreatorAgent(context)

                await creator.create_all(
                    songs=songs_to_create,
                    progress_callback=lambda info: update(
                        phase="creating",
                        completed_batches=info.get("completed", 0),
                        current_song=info.get("current_title", ""),
                    ),
                )
                await creator.close()
                logger.info(f"[Creator] 완료, Collector가 나머지 수집 중...")
            else:
                logger.info("[Creator] 생성할 곡 없음 (Collector가 이미 수집)")

            # Creator 완료 → Collector에게 충분한 시간 제공
            update(phase="collecting", current_song="새 곡 다운로드 대기 중...")

            # Collector가 나머지 수집할 때까지 최대 5분 대기
            for _ in range(10):
                done_now, _ = _count_complete(all_tracks, tracks_dir)
                if done_now >= total:
                    break
                await asyncio.sleep(30)

            # Collector 정지
            collector_stop.set()
            await collector_task

            await context.close()
            await browser.close()

        except Exception as e:
            import traceback as _tb
            tracker["errors"].append(f"R{rnd}: [{type(e).__name__}] {e}")
            logger.error(f"라운드 {rnd} 에러: {e}\n{_tb.format_exc()}")
        finally:
            await pw.stop()

        # QA
        suno_qa_agent.fix_links(project_id)
        qa = suno_qa_agent.verify(project_id)
        done_final = len([t for t in qa.get("tracks", []) if t["status"] == "complete"])
        logger.info(f"라운드 {rnd}: {done_final}/{total}곡 완성")
        if done_final >= total:
            break
        await asyncio.sleep(5)

    # 최종
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
    logger.info(f"종료: {complete}/{total}곡 완성, {tracker['round']} 라운드")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python _suno_batch_runner.py <project_id>", file=sys.stderr)
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
