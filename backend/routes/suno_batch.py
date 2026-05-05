"""
Suno 일괄 생성·다운로드 라우트.

routes/track_design.py 에서 분리 (Phase 1-2b). 곡 설계(Gemini) 와
Suno 자동화(Playwright/HTTP) 책임 분리가 목적.

prefix 는 /api/tracks 로 동일 — 기존 클라이언트 API 계약을 깨지 않는다.
main.py 에서 track_design.router(가 가진 catch-all /{pid}/{track_index})
보다 먼저 등록해 라우트 매칭 순서를 명시적으로 관리한다.

공유 상태/헬퍼는 모두 core/suno_batch_service.py 에 있다.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from config import settings
from core.channel_profile import channel_profile
from core.state_manager import state_manager
from core.suno_batch_service import (
    _suno_tasks,
    run_suno_batch,
    run_sibling_scan_http,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tracks", tags=["track-design"])


# ──────────────────────── stale 감지 헬퍼 ────────────────────────

# 진행파일이 이 시간(초) 이상 갱신 안 됐으면 죽은 task 로 간주.
# runner 의 polling/sleep 주기가 2초이므로 30초만 갱신 끊겨도 비정상.
# (이전 90초는 폴링 행이 있을 때 너무 관대해서 stuck 회복이 늦었음)
_STALE_PROGRESS_THRESHOLD_SEC = 30

# 시작 후 이 시간(초) 이상 지나면 진행파일 상태와 무관하게 stale 로 강제 처리.
# 가장 큰 배치라도 30분 안엔 끝나야 함. 이 안전망이 없으면 progress 파일이
# 계속 갱신되지만 진짜로는 hang 상태인 케이스를 영영 못 빠져나옴.
_ABSOLUTE_RUN_TIMEOUT_SEC = 30 * 60


def _is_suno_task_stale(project_id: str) -> bool:
    """메모리 _suno_tasks 는 running 인데 실제로는 죽은 task 인지 판별.

    True 면 memory dict 의 running 을 무시하고 새 요청 허용 (자동 reset).
    이전 batch-create 가 deadlock / 비정상 종료된 후 사용자가 다시 누를 때
    매번 batch-reset 을 명시적으로 호출하지 않아도 되도록.

    판정 기준 (하나라도 해당하면 stale):
      1) 메모리 task 의 started_at 이 절대 타임아웃을 넘김 (안전망)
      2) _suno_progress.json 자체가 없음 (시작도 안 됐는데 dict 만 있음)
      3) 진행파일이 30초 이상 갱신 안 됨 (subprocess 가 죽은 후 갱신 끊김)
      4) 진행파일 status 가 running 이 아님
         — completed/failed/interrupted 는 명백히 끝
         — runner 가 비정상 종료해 status 가 그 외 값이거나 누락되어도 정리
    """
    import time as _time
    task = _suno_tasks.get(project_id, {})
    started_at = task.get("started_at")
    if started_at and _time.time() - started_at > _ABSOLUTE_RUN_TIMEOUT_SEC:
        return True

    progress_path = settings.storage_dir / "projects" / project_id / "_suno_progress.json"
    if not progress_path.exists():
        return True
    try:
        age = _time.time() - progress_path.stat().st_mtime
        if age > _STALE_PROGRESS_THRESHOLD_SEC:
            return True
        data = json.loads(progress_path.read_text(encoding="utf-8"))
        # status 가 명시적으로 running 이 아니면 stale 로 간주 (메모리만 stuck).
        # 기존엔 완료/실패/중단 만 체크해 그 외 비정상 상태(or 누락)를 놓쳤음.
        if data.get("status") != "running":
            return True
    except Exception:
        # 파싱 실패 등 비정상 → stale 로 간주해 새 요청 허용
        return True
    return False


# ──────────────────────────── schemas ────────────────────────────

class BatchCreateRequest(BaseModel):
    channel_id: str
    # "cookie" (기본·빠름) | "browser" (캡차 발생 시 fallback)
    mode: str = "cookie"


# ──────────────────────────── batch routes ────────────────────────────

@router.post("/{project_id}/batch-create", summary="Suno 일괄 생성 시작")
async def batch_create(
    project_id: str,
    body: BatchCreateRequest,
    background_tasks: BackgroundTasks,
):
    """
    설계된 곡 전체를 Suno 자동화에 전달.
    20곡 → 10회 생성 (1회 = 2곡).
    """
    state = state_manager.require(project_id)
    tracks: list = state.get("designed_tracks", [])

    if not tracks:
        raise HTTPException(400, "설계된 곡이 없습니다. /design 먼저 실행하세요.")

    # 진행 중일 때만 중복 방지 (failed/completed는 재시작 허용)
    existing = _suno_tasks.get(project_id, {})
    if existing.get("status") == "running":
        if _is_suno_task_stale(project_id):
            # 진행파일 갱신이 멈춘 / 종료된 task 인데 메모리만 stuck — 자동 reset
            logger.info(f"stale Suno task 자동 reset: project={project_id}")
            _suno_tasks.pop(project_id, None)
        else:
            raise HTTPException(409, "이미 Suno 생성이 진행 중입니다. 취소하려면 /batch-reset을 호출하세요.")

    try:
        profile = channel_profile.load(body.channel_id)
    except FileNotFoundError:
        raise HTTPException(404, f"채널을 찾을 수 없습니다: {body.channel_id}")

    total_batches = len(tracks)  # 곡별 개별 생성 (1곡 = 1 Suno 호출 → 2 클립)

    import time as _time
    _suno_tasks[project_id] = {
        "status":           "running",
        "total_batches":    total_batches,
        "completed":        0,
        "tracks_collected": 0,
        "errors":           [],
        # 절대 타임아웃 안전망 — _is_suno_task_stale 이 사용. 시작 후 30분 넘으면
        # progress 파일 mtime 과 무관하게 stale 처리해 hang 회복.
        "started_at":       _time.time(),
    }

    background_tasks.add_task(
        run_suno_batch,
        project_id=project_id,
        tracks=tracks,
        has_lyrics=profile.get("has_lyrics", False),
        mode=body.mode,
    )

    return {
        "status":        "started",
        "mode":          body.mode,
        "total_batches": total_batches,
        "total_tracks":  len(tracks),
    }


@router.post("/{project_id}/batch-reset", summary="Suno 배치 상태 초기화")
async def batch_reset(project_id: str):
    """stuck 된 running 상태를 강제로 초기화."""
    state_manager.require(project_id)
    existing = _suno_tasks.get(project_id, {})
    old_status = existing.get("status", "idle")
    _suno_tasks.pop(project_id, None)
    return {"reset": True, "previous_status": old_status}


@router.get("/{project_id}/suno-status", summary="Suno 자동화 진행 상태")
async def suno_status(project_id: str):
    """
    Suno 일괄 생성 진행 상태.
    progress.json 파일에서 직접 읽음 (별도 프로세스가 실시간 기록).
    """
    progress_path = settings.storage_dir / "projects" / project_id / "_suno_progress.json"
    if progress_path.exists():
        try:
            data = json.loads(progress_path.read_text(encoding="utf-8"))
            return data
        except Exception:
            pass

    # fallback: in-memory
    task = _suno_tasks.get(project_id)
    if not task:
        return {"status": "idle"}
    return task


@router.get("/{project_id}/suno-tracks", summary="완성된 Suno 트랙 목록")
async def get_suno_tracks(project_id: str):
    """
    Suno 자동화로 생성·다운로드된 트랙 목록 반환.
    file_path를 /storage/... URL로 변환해 프론트엔드에서 바로 재생 가능.
    중복 파일 감지: 같은 음원이 다른 트랙에 할당된 경우 duplicate_of 표시.
    """
    import hashlib as _hl

    state = state_manager.require(project_id)
    tracks: list[dict] = state.get("suno_tracks", [])

    storage_root = settings.storage_dir
    # 워크트리 junction / symlink 등으로 prefix가 달라도 매칭되도록 resolve
    try:
        storage_root_resolved = storage_root.resolve()
    except OSError:
        storage_root_resolved = storage_root

    # 1차: file_path → audio_url 변환
    entries = []
    for t in tracks:
        fp = t.get("file_path", "")
        audio_url = ""
        if fp:
            try:
                fp_path = Path(fp)
                try:
                    fp_resolved = fp_path.resolve()
                except OSError:
                    fp_resolved = fp_path
                # 1) 우선 resolved 경로로 relative_to 시도
                try:
                    rel = fp_resolved.relative_to(storage_root_resolved)
                except ValueError:
                    # 2) 원본 경로로도 시도
                    rel = fp_path.relative_to(storage_root)
                mtime = int(fp_resolved.stat().st_mtime) if fp_resolved.exists() else 0
                audio_url = f"/storage/{rel.as_posix()}?t={mtime}"
            except (ValueError, OSError):
                audio_url = fp
        entries.append({**t, "audio_url": audio_url, "slot": t.get("slot", 0)})

    # 2차: 중복 감지 — 같은 index 내에서 slot 1,2가 같은 파일인지만 체크
    from collections import defaultdict as _dd
    idx_hashes: dict[int, list[str]] = _dd(list)
    for entry in entries:
        fp = entry.get("file_path", "")
        if entry.get("status") != "completed" or not fp or not Path(fp).exists():
            continue
        try:
            h = _hl.md5(Path(fp).read_bytes()).hexdigest()
        except Exception:
            continue
        idx = entry.get("index", 0)
        if h in idx_hashes[idx]:
            # 같은 곡의 slot 1,2가 동일 파일
            entry["status"] = "duplicate"
            entry["duplicate_of"] = idx
            entry["audio_url"] = ""
        else:
            idx_hashes[idx].append(h)

    return {"tracks": entries, "total": len(entries)}


@router.post("/{project_id}/suno-tracks/retry-download", summary="실패한 Suno 트랙 재다운로드")
async def retry_download(project_id: str, body: dict):
    """
    suno_id가 있는 download_failed 트랙의 재다운로드 시도.
    body: {"suno_id": str} 또는 {"retry_all": true}
    """
    import aiohttp

    state = state_manager.require(project_id)
    tracks: list[dict] = state.get("suno_tracks", [])
    storage_root = settings.storage_dir

    retry_all = body.get("retry_all", False)
    target_suno_id = body.get("suno_id", "")

    retried = 0
    for t in tracks:
        if t.get("status") != "download_failed":
            continue
        if not t.get("suno_id"):
            continue
        if not retry_all and t.get("suno_id") != target_suno_id:
            continue

        clip_id = t["suno_id"]
        safe_title = t.get("title", "unknown").replace("/", "_").replace("\\", "_")
        slot_suffix = f"_v{t.get('slot', 1)}" if t.get("slot") else ""
        prefix = f"{t.get('index', 0):02d}_{safe_title}{slot_suffix}"
        out_dir = storage_root / "projects" / project_id / "tracks"
        out_dir.mkdir(parents=True, exist_ok=True)
        dest = out_dir / f"{prefix}.mp3"

        urls = [
            f"https://cdn1.suno.ai/{clip_id}.mp3",
            f"https://cdn2.suno.ai/{clip_id}.mp3",
        ]
        downloaded = False
        async with aiohttp.ClientSession() as http:
            for url in urls:
                try:
                    async with http.get(url, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                        if resp.status == 200:
                            content = await resp.read()
                            if len(content) > 1000:  # 유효한 MP3인지 최소 크기 체크
                                dest.write_bytes(content)
                                # Suno MP3 헤더 교정 (container/Xing 재mux)
                                from core.mp3_fix import fix_mp3_header
                                await fix_mp3_header(dest)
                                t["file_path"] = str(dest)
                                t["status"] = "completed"
                                downloaded = True
                                retried += 1
                                logger.info(f"재다운로드 성공: {clip_id[:8]} → {dest.name}")
                                break
                except Exception as e:
                    logger.warning(f"재다운로드 실패 ({url[:40]}): {e}")

    state_manager.update(project_id, {"suno_tracks": tracks})

    # audio_url 변환해서 반환
    result = []
    for t in tracks:
        fp = t.get("file_path", "")
        audio_url = ""
        if fp:
            try:
                rel = Path(fp).relative_to(storage_root)
                audio_url = "/storage/" + rel.as_posix()
            except ValueError:
                audio_url = fp
        entry = {**t, "audio_url": audio_url, "slot": t.get("slot", 0)}
        result.append(entry)

    return {"tracks": result, "retried": retried, "total": len(result)}


@router.post("/{project_id}/suno-tracks/scan-siblings", summary="Suno에서 누락곡 제목 검색·다운로드")
async def scan_siblings(project_id: str, background_tasks: BackgroundTasks):
    """
    모든 designed_tracks 제목으로 Suno 검색 → 곡당 최신 2곡 다운로드.
    기존 해당 index의 suno_tracks는 삭제 후 새 2곡으로 교체.
    slot이 정확히 2개가 아닌 곡만 대상.
    """
    state = state_manager.require(project_id)
    suno_tracks: list[dict] = state.get("suno_tracks", [])
    designed: list[dict] = state.get("designed_tracks", [])

    if not designed:
        raise HTTPException(400, "설계된 곡이 없습니다.")

    # slot 1,2가 모두 있는 index만 완료로 판단
    from collections import Counter
    slot_count = Counter()
    for t in suno_tracks:
        if t.get("status") == "completed" and t.get("slot") in (1, 2):
            slot_count[t.get("index")] += 1

    missing_titles = []
    missing_indices = []
    for dt in designed:
        idx = dt.get("index", 0)
        if slot_count.get(idx, 0) != 2:  # 정확히 2개가 아니면 재검색
            missing_titles.append(dt.get("title", ""))
            missing_indices.append(idx)

    missing_titles = [t for t in missing_titles if t]

    if not missing_titles:
        return {"status": "all_complete", "message": "모든 곡이 2개씩 완료됨"}

    background_tasks.add_task(
        run_sibling_scan_http,
        project_id=project_id,
        designed=designed,
        missing_indices=missing_indices,
    )

    return {"status": "started", "missing_count": len(missing_titles), "titles": missing_titles[:5]}


@router.put("/{project_id}/suno-tracks/reorder", summary="Suno 트랙 순서 변경")
async def reorder_suno_tracks(project_id: str, body: dict):
    """body: {"order": [0, 2, 1, ...]}  — 새 순서의 인덱스 배열"""
    state = state_manager.require(project_id)
    tracks: list[dict] = state.get("suno_tracks", [])
    order: list[int] = body.get("order", [])

    if len(order) != len(tracks):
        raise HTTPException(400, f"order 길이({len(order)}) ≠ 트랙 수({len(tracks)})")
    if set(order) != set(range(len(tracks))):
        raise HTTPException(400, "order에 중복 또는 범위 초과 인덱스가 있습니다.")

    reordered = [tracks[i] for i in order]
    state_manager.update(project_id, {"suno_tracks": reordered})
    return {"tracks": reordered}


@router.delete("/{project_id}/suno-tracks/{track_index}", summary="Suno 트랙 삭제")
async def delete_suno_track(project_id: str, track_index: int):
    """인덱스 기반 Suno 트랙 삭제 (파일은 유지, 목록에서만 제거)."""
    state = state_manager.require(project_id)
    tracks: list[dict] = state.get("suno_tracks", [])

    if track_index < 0 or track_index >= len(tracks):
        raise HTTPException(404, f"트랙 인덱스 범위 초과: {track_index}")

    removed = tracks.pop(track_index)
    state_manager.update(project_id, {"suno_tracks": tracks})
    return {"deleted": removed}
