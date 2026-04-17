"""
Suno 배치 생성 — HTTP API 기반.

브라우저 자동화 대신 HTTP로 직접 곡 생성 + 다운로드.
토큰 만료 시 Playwright headless로 자동 갱신.

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

logging.basicConfig(level=logging.INFO, stream=sys.stderr,
                    format="%(asctime)s [%(name)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("suno_batch")

MAX_ROUNDS = 3


def _progress_path(pid: str) -> Path:
    return _DIR / "storage" / "projects" / pid / "_suno_progress.json"


def _write_progress(pid: str, d: dict) -> None:
    p = _progress_path(pid)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")


def _count_done(all_tracks, tracks_dir):
    """완료/미완료 곡 수 카운트."""
    files = list(tracks_dir.glob("*.mp3")) if tracks_dir.exists() else []
    done, missing = 0, []
    for i, t in enumerate(all_tracks):
        idx = t.get("index", i + 1)
        v1 = any(f.name.startswith(f"{idx:02d}_") and "_v1" in f.name and f.stat().st_size > 10_000 for f in files)
        v2 = any(f.name.startswith(f"{idx:02d}_") and "_v2" in f.name and f.stat().st_size > 10_000 for f in files)
        if v1 and v2:
            done += 1
        else:
            missing.append(t)
    return done, missing


async def main(project_id: str) -> None:
    from core.state_manager import state_manager
    from core.suno_api import suno_api

    state = state_manager.get(project_id)
    if not state:
        _write_progress(project_id, {"status": "failed", "errors": ["프로젝트 없음"]})
        return

    all_tracks = state.get("designed_tracks") or []
    channel_id = state.get("channel_id", "")
    has_lyrics = False
    ch_path = _DIR / "storage" / "channels" / f"{channel_id}.json"
    if ch_path.exists():
        has_lyrics = json.loads(ch_path.read_text(encoding="utf-8")).get("has_lyrics", False)

    if not all_tracks:
        _write_progress(project_id, {"status": "failed", "errors": ["트랙 없음"]})
        return

    total = len(all_tracks)
    tracks_dir = _DIR / "storage" / "projects" / project_id / "tracks"
    tracks_dir.mkdir(parents=True, exist_ok=True)

    tracker = {
        "status": "running", "phase": "init", "total_designed": total,
        "total_batches": 0, "completed_batches": 0, "tracks_collected": 0,
        "current_song": "", "round": 0, "errors": [],
    }

    # 세션 로드 + 토큰 갱신
    logger.info("세션 로드 + 토큰 갱신...")
    suno_api.load_session()
    if not await suno_api.refresh_token():
        _write_progress(project_id, {"status": "failed", "errors": ["Suno 토큰 갱신 실패"]})
        return

    # 크레딧 확인
    credits_info = await suno_api.get_credits()
    remaining = credits_info.get("credits", 0)
    logger.info(f"크레딧: {remaining}")

    def save_suno_tracks(results):
        """결과를 state.json의 suno_tracks에 저장."""
        valid = [r for r in results if r.get("index") and r.get("slot")]
        if not valid:
            return
        cur = state_manager.get(project_id) or {}
        old = cur.get("suno_tracks") or []
        old = [t for t in old if t.get("index") and t.get("slot")]
        keys = {(r["index"], r["slot"]) for r in valid}
        merged = [t for t in old if (t.get("index"), t.get("slot")) not in keys]
        merged.extend(valid)
        merged.sort(key=lambda t: (t.get("index", 0), t.get("slot", 0)))
        state_manager.update(project_id, {"suno_tracks": merged})

    # 라운드 실행
    all_results = []

    for rnd in range(1, MAX_ROUNDS + 1):
        tracker["round"] = rnd
        done_now, missing = _count_done(all_tracks, tracks_dir)
        if not missing:
            logger.info("전곡 완료!")
            break

        tracker.update(phase="creating", total_batches=len(missing), completed_batches=done_now)
        _write_progress(project_id, tracker)

        logger.info(f"[라운드 {rnd}] {len(missing)}곡 생성 시작 (완료: {done_now}/{total})")

        # HTTP API로 배치 생성 (병렬)
        songs = []
        for i, t in enumerate(missing):
            idx = t.get("index", i + 1)
            songs.append({
                "title": t.get("title", f"Track_{idx}"),
                "suno_prompt": t.get("suno_prompt", ""),
                "lyrics": t.get("lyrics", "") if has_lyrics else "",
                "is_instrumental": not has_lyrics,
                "index": idx,
            })

        # 곡을 하나씩 생성 + 즉시 다운로드 (병렬 3곡)
        semaphore = asyncio.Semaphore(3)
        round_results = []

        async def process_song(song):
            async with semaphore:
                idx = song["index"]
                title = song["title"]
                tracker["current_song"] = title
                _write_progress(project_id, tracker)

                try:
                    logger.info(f"  [{idx}] 생성: {title}")

                    # 생성
                    clips = await suno_api.create_song(
                        prompt=song["suno_prompt"],
                        title=title,
                        lyrics=song.get("lyrics", ""),
                        instrumental=song["is_instrumental"],
                    )

                    # audio_url 대기
                    clip_ids = [c.get("id", "") for c in clips if c.get("id")]
                    logger.info(f"  [{idx}] 생성됨: {clip_ids}, audio 대기...")

                    ready = await suno_api.wait_for_audio(clips, timeout=300)

                    # 다운로드
                    for slot, clip in enumerate(ready[:2], 1):
                        prefix = f"{idx:02d}_{title[:30]}_v{slot}."
                        # 파일명 안전하게
                        safe_prefix = "".join(c if c.isalnum() or c in "-_ " else "_" for c in prefix)
                        file_path = await suno_api.download_clip(clip, tracks_dir, safe_prefix)

                        result = {
                            "index": idx, "title": title,
                            "suno_id": clip.get("id", ""),
                            "file_path": file_path,
                            "status": "completed" if file_path else "download_failed",
                            "slot": slot,
                        }
                        round_results.append(result)
                        all_results.append(result)

                        tracker["tracks_collected"] = sum(1 for r in all_results if r["status"] == "completed")
                        tracker["completed_batches"] = tracker["tracks_collected"] // 2
                        _write_progress(project_id, tracker)

                    logger.info(f"  [{idx}] 완료: {title}")

                    # rate limit 방지
                    await asyncio.sleep(5)

                except Exception as e:
                    logger.error(f"  [{idx}] 실패: {e}")
                    tracker["errors"].append(f"[{title}] {e}")
                    round_results.append({
                        "index": idx, "title": title, "suno_id": "",
                        "file_path": None, "status": "failed", "slot": 0,
                    })
                    _write_progress(project_id, tracker)

        # 병렬 실행
        tasks = [asyncio.create_task(process_song(s)) for s in songs]
        await asyncio.gather(*tasks, return_exceptions=True)

        # state.json에 저장
        save_suno_tracks(round_results)

        # QA
        done_after, still_missing = _count_done(all_tracks, tracks_dir)
        logger.info(f"[라운드 {rnd} 완료] {done_after}/{total} 곡")

        if not still_missing:
            break

    # 최종 상태
    final_done, _ = _count_done(all_tracks, tracks_dir)
    tracker.update(
        status="completed" if final_done >= total else "partial",
        phase="done",
        tracks_collected=final_done * 2,
        completed_batches=final_done,
    )
    _write_progress(project_id, tracker)
    save_suno_tracks(all_results)

    logger.info(f"배치 완료: {final_done}/{total}곡, 결과 {len(all_results)}개")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python _suno_batch_runner.py <project_id>")
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
