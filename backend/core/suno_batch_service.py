"""
Suno 일괄 생성·검색·다운로드 백그라운드 작업.

routes/track_design.py 에서 추출 (Phase 1-2a). 라우트는 그대로 두고
오래 걸리는 백그라운드 작업만 분리해 라우트 파일 가독성을 회복한다.

공유 상태:
    _suno_tasks  ── 프로젝트별 진행 상황 (in-memory)
                    디스크 영속은 별도 프로세스가 _suno_progress.json 에 기록한다.

함수:
    run_suno_batch         ── /batch-create 백그라운드. runner 프로세스 띄우고 진행 폴링.
    run_sibling_scan_http  ── /scan-siblings 백그라운드. Suno 피드 HTTP 검색 + CDN 다운로드.
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


# 프로젝트별 Suno 자동화 진행 상태 (in-memory)
# 디스크 영속: storage/projects/{id}/_suno_progress.json (별도 프로세스가 기록)
_suno_tasks: dict[str, dict] = {}


# ──────────────────────────── /batch-create 워커 ────────────────────────────

async def run_suno_batch(
    project_id: str,
    tracks: list[dict],
    has_lyrics: bool,
    mode: str = "cookie",
) -> None:
    """
    Suno 일괄 생성 백그라운드 작업.

    mode="cookie": _suno_cookie_runner.py (HTTP 직접 호출, 브라우저 없음, 빠름)
    mode="browser": _suno_batch_runner.py (Playwright 자동화 — 캡차 발생 시 사용)

    Windows uvicorn의 SelectorEventLoop에서는 Playwright subprocess를 실행할 수 없으므로
    런너를 별도 Python 프로세스로 띄워 완전히 격리한다.
    진행 상황은 _suno_progress.json 을 폴링해 task dict에 반영한다.
    """
    task = _suno_tasks.get(project_id)
    if not task:
        return

    from config import settings as _settings
    progress_path = _settings.storage_dir / "projects" / project_id / "_suno_progress.json"

    def _read_progress() -> None:
        if progress_path.exists():
            try:
                data = json.loads(progress_path.read_text(encoding="utf-8"))
                task["completed_batches"] = data.get("completed_batches", 0)
                task["tracks_collected"]  = data.get("tracks_collected", 0)
                if data.get("errors"):
                    task["errors"] = data["errors"]
            except Exception:
                pass

    def _read_final() -> None:
        if progress_path.exists():
            try:
                final = json.loads(progress_path.read_text(encoding="utf-8"))
                task.update({
                    "status":           final.get("status", "failed"),
                    "completed_batches": final.get("completed_batches", 0),
                    "tracks_collected": final.get("tracks_collected", 0),
                    "errors":           final.get("errors", []),
                    "traceback":        final.get("traceback", ""),
                })
                if final.get("results"):
                    task["results"] = final["results"]
            except Exception as e:
                task["status"] = "failed"
                task["errors"].append(f"progress.json 읽기 실패: {e}")

    # ── frozen(EXE) 환경: subprocess 안 됨 (.py 파일 디스크에 없음, sys.executable=EXE)
    #    → runner 모듈을 직접 import 해서 같은 프로세스 asyncio task 로 실행
    if getattr(sys, "frozen", False):
        try:
            import importlib
            mod_name = "_suno_cookie_runner" if mode == "cookie" else "_suno_batch_runner"
            runner_mod = importlib.import_module(mod_name)
            logger.info(f"Suno runner 직접 호출 (frozen, mode={mode}): project={project_id}")
            bg_task = asyncio.create_task(runner_mod.main(project_id))
            while not bg_task.done():
                await asyncio.sleep(2)
                _read_progress()
            _read_final()
            if bg_task.exception() and task.get("status") != "completed":
                task["status"] = "failed"
                task["errors"].append(f"runner 예외: {bg_task.exception()}")
        except Exception as e:
            task["status"] = "failed"
            task["errors"].append(f"runner 시작 실패: {e}")
        return

    # ── 개발 환경(venv): 별도 프로세스로 격리 (Playwright/이벤트루프 호환)
    import subprocess as _sp
    backend_dir = Path(__file__).parent.parent  # core/ → backend/

    runner_name = "_suno_cookie_runner.py" if mode == "cookie" else "_suno_batch_runner.py"
    runner = backend_dir / runner_name
    if not runner.exists():
        runner = backend_dir / "_suno_batch_runner.py"
        mode = "browser"

    # ⚠️ 중요: stdout/stderr 를 PIPE 로 두면 Windows 익명 파이프 버퍼(~4KB) 가
    # 가득 차는 순간 child 의 write() 가 block 되어 deadlock. 4-5곡 후 멈춤의
    # 가장 큰 원인이었음. PIPE 대신 로그 파일에 직접 redirect → 버퍼 자체 제거.
    log_path = _settings.storage_dir / "projects" / project_id / "_suno_runner.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_fp = open(log_path, "w", encoding="utf-8", buffering=1)  # line-buffered

    try:
        proc = _sp.Popen(
            [sys.executable, str(runner), project_id],
            stdout=log_fp,
            stderr=_sp.STDOUT,  # stderr 도 같은 로그 파일로
        )
        logger.info(
            f"Suno runner subprocess 시작 (mode={mode}): PID={proc.pid}, "
            f"project={project_id}, log={log_path.name}"
        )

        while proc.poll() is None:
            await asyncio.sleep(2)
            _read_progress()

        # subprocess 가 fd 를 잡고 있을 수 있어 close 는 종료 후
        try:
            log_fp.close()
        except Exception:
            pass

        if progress_path.exists():
            _read_final()
        else:
            rc = proc.returncode
            try:
                tail = log_path.read_text(encoding="utf-8", errors="replace")[-1500:]
            except Exception:
                tail = ""
            task["status"] = "failed"
            task["errors"].append(f"runner 종료 (code={rc}): {tail[-500:]}")

        logger.info(f"Suno 배치 완료: {project_id}, status={task['status']}, {task['tracks_collected']}곡")

    except Exception as e:
        import traceback as _tb
        try:
            log_fp.close()
        except Exception:
            pass
        task["status"] = "failed"
        task["errors"].append(f"[{type(e).__name__}] {e}")
        task["traceback"] = _tb.format_exc()
        logger.error(f"Suno 배치 실패: {e}")


# ──────────────────────── /scan-siblings 워커 (HTTP) ────────────────────────

async def run_sibling_scan_http(
    project_id: str,
    designed: list[dict],
    missing_indices: list[int],
) -> None:
    """HTTP API로 Suno 피드 검색 + CDN 다운로드. 브라우저 불필요."""
    from core.suno_api import suno_api, BASE_URL as SUNO_BASE_URL
    from core.state_manager import state_manager

    logger.info(f"[HTTP 스캔] 시작: {len(missing_indices)}곡 누락")

    try:
        # 토큰 갱신
        suno_api.load_session()
        if not await suno_api.refresh_token():
            logger.error("[HTTP 스캔] 토큰 갱신 실패")
            return

        # Suno 피드에서 최근 곡 가져오기 (전체 워크스페이스)
        import aiohttp
        auth = await suno_api._get_auth_token()
        headers = {**suno_api._headers, "Cookie": suno_api._cookie_header()}
        if auth:
            headers["Authorization"] = auth

        # 피드 조회 (최근 100곡) — transient 5xx/네트워크 오류는 with_retry 가 자동 복구
        from core.retry import with_retry as _retry

        async def _fetch_page(payload_: dict) -> list:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{SUNO_BASE_URL}/api/feed/v3",
                    json=payload_, headers=headers,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    if resp.status != 200:
                        # 5xx 는 재시도 후보, 4xx 는 즉시 실패
                        body = (await resp.text())[:200]
                        raise RuntimeError(f"feed/v3 HTTP {resp.status}: {body}")
                    data = await resp.json()
                    return data if isinstance(data, list) else data.get("clips", [])

        all_clips: list = []
        cursor = None
        for page_idx in range(3):  # 최대 3페이지 (60곡)
            payload = {
                "cursor": cursor,
                "limit": 20,
                "filters": {
                    "disliked": "False",
                    "trashed": "False",
                    "workspace": {"presence": "True", "workspaceId": "default"},
                },
            }
            try:
                clips = await _retry(
                    lambda p=payload: _fetch_page(p),
                    max_attempts=3,
                    base_delay=1.0,
                    label=f"[HTTP 스캔] 피드 page {page_idx + 1}",
                    logger=logger,
                )
            except Exception as e:
                logger.error(f"[HTTP 스캔] 피드 조회 실패 (재시도 모두 소진): {e}")
                break
            if not clips:
                break
            all_clips.extend(clips)
            # 다음 페이지 커서
            if isinstance(clips, list) and clips:
                cursor = clips[-1].get("id")
            else:
                break

        logger.info(f"[HTTP 스캔] 피드에서 {len(all_clips)}개 clip 조회")

        # designed_tracks 제목과 매칭
        title_to_index = {}
        for dt in designed:
            title_to_index[dt.get("title", "").strip().lower()] = dt.get("index", 0)

        # 매칭 + 다운로드
        project_dir = Path(__file__).parent.parent / "storage" / "projects" / project_id / "tracks"
        project_dir.mkdir(parents=True, exist_ok=True)

        results = []
        matched_indices = set()

        for clip in all_clips:
            clip_title = (clip.get("title", "") or "").strip().lower()
            audio_url = clip.get("audio_url") or clip.get("stream_audio_url", "")
            clip_id = clip.get("id", "")

            if clip_title not in title_to_index:
                continue

            idx = title_to_index[clip_title]
            if idx not in missing_indices:
                continue

            # 이미 이 index의 슬롯을 2개 채웠으면 스킵
            slots_filled = sum(1 for r in results if r["index"] == idx)
            if slots_filled >= 2:
                continue

            slot = slots_filled + 1
            orig_title = next((dt.get("title", "") for dt in designed if dt.get("index") == idx), clip_title)
            safe_title = "".join(c if c.isalnum() or c in "-_ " else "_" for c in orig_title[:30])
            prefix = f"{idx:02d}_{safe_title}_v{slot}."

            file_path = await suno_api.download_clip(
                {"id": clip_id, "audio_url": audio_url},
                project_dir, prefix,
            )

            results.append({
                "index": idx,
                "title": orig_title,
                "suno_id": clip_id,
                "file_path": file_path,
                "status": "completed" if file_path else "download_failed",
                "slot": slot,
            })
            matched_indices.add(idx)

            logger.info(f"[HTTP 스캔] [{idx}] v{slot} {'OK' if file_path else 'FAIL'}: {orig_title}")

        # state.json 업데이트
        if results:
            state = state_manager.get(project_id) or {}
            old_tracks = state.get("suno_tracks") or []
            # 매칭된 index의 기존 항목 삭제
            old_tracks = [t for t in old_tracks if t.get("index") not in matched_indices]
            old_tracks.extend(results)
            old_tracks.sort(key=lambda t: (t.get("index", 0), t.get("slot", 0)))
            state_manager.update(project_id, {"suno_tracks": old_tracks})

        logger.info(f"[HTTP 스캔] 완료: {len(results)}개 다운로드, {len(matched_indices)}곡 매칭")

    except Exception as e:
        logger.error(f"[HTTP 스캔] 실패: {e}")


# run_sibling_scan_subprocess (legacy Playwright fallback) 는 실제로 호출되는 곳이
# 한 군데도 없어 제거됨. 필요해지면 git history (commit aefb949 이전) 에서 복구.
