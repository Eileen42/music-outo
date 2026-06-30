"""
곡 설계 라우터 (Gemini 4단계 파이프라인 + 갤러리/CRUD).

prefix: /api/tracks
기존 /api/projects/{id}/tracks (오디오 업로드)와 별개.

Suno 일괄 생성·다운로드 라우트는 routes/suno_batch.py 로 분리했다.
이 파일은 곡 설계와 곡 단위 CRUD 만 담당한다.
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
from core.track_designer import track_designer

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tracks", tags=["track-design"])

# 프로젝트별 곡 설계(/design) 진행 상태 (in-memory + 디스크 미러)
# Gemini 4단계 파이프라인이 30~60초 걸려 동기 응답 시 hang 위험. BackgroundTask로 분리.
# 서버 재시작 시 메모리는 비지만 _design_progress.json 으로 마지막 상태 복원 가능.
_design_tasks: dict[str, dict] = {}


def _design_progress_path(project_id: str) -> Path:
    return settings.storage_dir / "projects" / project_id / "_design_progress.json"


def _persist_design_task(project_id: str) -> None:
    """현재 _design_tasks[project_id] 를 디스크에 원자적으로 저장.
    실패해도 메모리 진행 상황은 살아있으므로 경고만 남기고 계속 진행한다."""
    task = _design_tasks.get(project_id)
    if task is None:
        return
    path = _design_progress_path(project_id)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(task, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(path)
    except Exception as e:
        logger.warning(f"_design_progress 저장 실패 ({project_id}): {e}")


# ──────────────────────────── schemas ────────────────────────────

class DesignRequest(BaseModel):
    channel_id: str
    project_id: str
    count: int = 20
    # 사용자 입력 (키워드, 분위기, 가사 힌트 등)
    keywords: str = ""
    mood: str = ""
    lyrics_hint: str = ""
    extra: str = ""


# ──────────────────────────── routes ────────────────────────────

@router.post("/design", summary="AI 곡 설계 시작 (백그라운드)")
async def design_tracks(body: DesignRequest, background_tasks: BackgroundTasks):
    """
    Gemini 4단계 파이프라인이 30~60초 걸려 동기 응답이면 브라우저가 hang/timeout 한다.
    이 라우트는 즉시 {status:"started"}만 반환하고 처리는 백그라운드로 실행.
    프론트는 GET /api/tracks/design-status/{project_id} 폴링으로 진행상황을 받는다.
    """
    try:
        profile = channel_profile.load(body.channel_id)
    except FileNotFoundError:
        raise HTTPException(404, f"채널을 찾을 수 없습니다: {body.channel_id}")

    state_manager.require(body.project_id)

    existing = _design_tasks.get(body.project_id, {})
    if existing.get("status") == "running":
        raise HTTPException(409, "이미 곡 설계가 진행 중입니다.")

    _design_tasks[body.project_id] = {
        "status":   "running",
        "phase":    "queued",
        "progress": 0,
        "total":    body.count,
        "message":  "대기 중...",
    }
    _persist_design_task(body.project_id)

    background_tasks.add_task(
        _run_design_task,
        project_id=body.project_id,
        channel_id=body.channel_id,
        profile=profile,
        body=body,
    )

    return {"status": "started", "project_id": body.project_id, "total": body.count}


@router.get("/design-status/{project_id}", summary="곡 설계 진행 상태")
async def design_status(project_id: str):
    """폴링용. status: idle | running | completed | failed.

    서버가 재시작된 직후엔 메모리가 비어있을 수 있으니 디스크 미러를 fallback 으로 읽는다.
    """
    task = _design_tasks.get(project_id)
    if task:
        return task
    # 서버 재시작 시: 메모리는 비었지만 디스크엔 마지막 상태가 남아있다.
    path = _design_progress_path(project_id)
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            # running 상태 그대로 두면 영원히 running. 재시작이 일어났다는 것은
            # 작업도 함께 죽었다는 뜻이므로 interrupted 로 강등.
            if data.get("status") == "running":
                data["status"] = "interrupted"
                data["message"] = "서버 재시작으로 작업이 중단되었습니다. 다시 시작해주세요."
            return data
        except Exception:
            pass
    return {"status": "idle"}


async def _run_design_task(
    project_id: str,
    channel_id: str,
    profile: dict,
    body: DesignRequest,
) -> None:
    """곡 설계 백그라운드 작업. _design_tasks[project_id]에 진행 상태 기록."""
    task = _design_tasks[project_id]

    def _set(phase: str, message: str, progress: int | None = None) -> None:
        task["phase"] = phase
        task["message"] = message
        if progress is not None:
            task["progress"] = progress
        _persist_design_task(project_id)

    try:
        _set("designing", "곡 설계 시작 (사용자 입력 + 채널 프로필 기반)...", 10)
        user_input = {
            "keywords":    body.keywords,
            "mood":        body.mood,
            "lyrics_hint": body.lyrics_hint,
            "extra":       body.extra,
        }
        result = await track_designer.design_tracks(
            channel_profile=profile,
            count=body.count,
            user_input=user_input,
            progress_cb=_set,
        )

        analysis  = result.get("analysis", {})
        concept   = result.get("concept", {})
        tracklist = result.get("tracklist", [])
        tracks    = result.get("tracks", [])

        _set("saving", "프로젝트에 저장 중...", 95)
        state_manager.update(project_id, {
            "designed_tracks":   tracks,
            "project_concept":   concept,
            "project_analysis":  analysis,
            "project_tracklist": tracklist,
        })

        task.update({
            "status":   "completed",
            "phase":    "done",
            "progress": 100,
            "message":  f"{len(tracks)}곡 설계 완료",
            "tracks":   tracks,
            "concept":  concept,
            "total":    len(tracks),
        })
        _persist_design_task(project_id)
        logger.info(f"[design] 완료: project={project_id}, {len(tracks)}곡")

    except Exception as e:
        import traceback as _tb
        task.update({
            "status":    "failed",
            "phase":     "error",
            "error":     f"[{type(e).__name__}] {e}",
            "traceback": _tb.format_exc()[-2000:],
        })
        _persist_design_task(project_id)
        logger.error(f"[design] 실패: project={project_id}, {e}")


@router.get("/{project_id}", summary="프로젝트 곡 목록 (갤러리)")
async def get_designed_tracks(project_id: str):
    """해당 프로젝트의 설계된 곡 목록 + 컨셉."""
    state = state_manager.require(project_id)
    return {
        "tracks":  state.get("designed_tracks", []),
        "concept": state.get("project_concept", {}),
    }


# ── Suno 관련 라우트 (반드시 /{project_id}/{track_index} 보다 먼저 등록) ────
# FastAPI는 라우트를 위에서부터 순서대로 매칭하므로, 리터럴 경로 세그먼트
# (suno-status, suno-tracks)가 있는 라우트를 파라미터 라우트보다 먼저 등록해야
# "Method Not Allowed 405" 오류를 피할 수 있음.


class RegisterSetRequest(BaseModel):
    slot: int  # 1 or 2


@router.post("/{project_id}/register-suno-set", summary="Suno 세트를 프로젝트 트랙으로 등록")
async def register_suno_set(project_id: str, body: RegisterSetRequest, background_tasks: BackgroundTasks = None):
    """
    특정 slot(1 or 2)의 suno_tracks를 프로젝트 tracks로 변환·등록.
    Suno가 곡당 2곡 생성 → slot 1 = 세트 A, slot 2 = 세트 B.
    """
    import uuid as _uuid
    from core.audio_pipeline import audio_pipeline

    state = state_manager.require(project_id)
    suno_tracks: list[dict] = state.get("suno_tracks", [])

    slot = body.slot
    if slot not in (1, 2):
        raise HTTPException(400, "slot은 1 또는 2여야 합니다")

    # 해당 slot의 completed 트랙만 필터
    slot_tracks = [t for t in suno_tracks if t.get("slot") == slot and t.get("status") == "completed"]

    # slot 없는 이전 데이터 호환: slot==0이면 모든 completed 트랙을 slot 1로 취급
    if not slot_tracks and slot == 1:
        slot_tracks = [t for t in suno_tracks if t.get("slot", 0) == 0 and t.get("status") == "completed"]

    if not slot_tracks:
        raise HTTPException(400, f"세트 {'A' if slot == 1 else 'B'}에 완료된 트랙이 없습니다")

    # index 순으로 정렬
    slot_tracks.sort(key=lambda t: t.get("index", 0))

    # 중복 감지 (같은 suno_id = 같은 음원)
    import hashlib as _hl
    seen_hashes: dict[str, int] = {}  # md5 → first index
    duplicates: list[dict] = []
    for st in slot_tracks:
        fp = st.get("file_path", "")
        if fp and Path(fp).exists():
            h = _hl.md5(Path(fp).read_bytes()).hexdigest()
            first = seen_hashes.get(h)
            if first is not None:
                duplicates.append({"index": st.get("index"), "duplicate_of": first, "suno_id": st.get("suno_id", "")[:8]})
            else:
                seen_hashes[h] = st.get("index", 0)

    # designed_tracks에서 가사 매핑 (index → lyrics)
    designed_tracks_map: dict[int, dict] = {
        dt.get("index", i + 1): dt
        for i, dt in enumerate(state.get("designed_tracks", []) or [])
    }

    # suno_track → Track 변환 (중복 제외)
    dup_indices = {d["index"] for d in duplicates}
    tracks = []
    for order, st in enumerate([s for s in slot_tracks if s.get("index") not in dup_indices]):
        fp = st.get("file_path", "")
        if not fp or not Path(fp).exists():
            continue

        # MP3 메타데이터 읽기
        try:
            info = audio_pipeline._get_info(Path(fp))
        except Exception:
            info = {"duration": 0, "sample_rate": 48000, "channels": 2}

        # 설계 시점의 가사를 복사 (채널이 가사형이면 Suno가 실제로 부른 가사 = designed lyrics)
        designed = designed_tracks_map.get(st.get("index"), {})
        designed_lyrics = designed.get("lyrics") or None

        track_id = str(_uuid.uuid4())
        tracks.append({
            "id": track_id,
            "title": st.get("title", f"Track {order + 1}"),
            "artist": "",
            "order": order,
            "filename": Path(fp).name,
            "stored_path": fp,
            "duration": info.get("duration", 0),
            "sample_rate": info.get("sample_rate", 48000),
            "channels": info.get("channels", 2),
            "waveform_file": None,
            "lyrics": designed_lyrics,
            "lyrics_sync_file": None,
        })

    set_label = "A" if slot == 1 else "B"
    state_manager.update(project_id, {
        "tracks": tracks,
        "active_suno_set": set_label,
    })

    # 가사 있는 트랙이 있으면 자막 자동 빌드
    if background_tasks and any(t.get("lyrics") for t in tracks):
        from routes.tracks import _rebuild_subtitles
        background_tasks.add_task(_rebuild_subtitles, project_id)

    return {
        "set": set_label,
        "slot": slot,
        "tracks_count": len(tracks),
        "tracks": tracks,
        "duplicates": duplicates,
        "unique_count": len(tracks),
        "skipped_duplicates": len(duplicates),
    }


@router.get("/{project_id}/active-set", summary="현재 활성 세트 조회")
async def get_active_set(project_id: str):
    state = state_manager.require(project_id)
    return {
        "active_set": state.get("active_suno_set", None),
        "tracks_count": len(state.get("tracks", [])),
    }




@router.post("/{project_id}/regenerate/{track_index}", summary="개별 곡 재생성")
async def regenerate_track(project_id: str, track_index: int, body: dict):
    """
    갤러리에서 개별 곡 재생성 요청.
    body: {"channel_id": str}
    """
    channel_id = body.get("channel_id", "")
    if not channel_id:
        raise HTTPException(400, "channel_id가 필요합니다")

    try:
        profile = channel_profile.load(channel_id)
    except FileNotFoundError:
        raise HTTPException(404, f"채널을 찾을 수 없습니다: {channel_id}")

    state = state_manager.require(project_id)
    tracks: list  = state.get("designed_tracks", [])
    concept: dict = state.get("project_concept", {})

    if track_index < 0 or track_index >= len(tracks):
        raise HTTPException(404, f"트랙 인덱스 범위 초과: {track_index}")

    new_track = await track_designer.regenerate_single(
        track=tracks[track_index],
        channel_profile=profile,
        concept=concept or None,
    )
    tracks[track_index] = new_track
    state_manager.update(project_id, {"designed_tracks": tracks})
    return new_track


# ── 개별 곡 수정/삭제 (파라미터 라우트 — 반드시 마지막에) ──────────────────

@router.put("/{project_id}/{track_index}", summary="개별 곡 수정")
async def update_track(project_id: str, track_index: int, body: dict):
    """인덱스 기반 곡 수정."""
    state = state_manager.require(project_id)
    tracks: list = state.get("designed_tracks", [])

    if track_index < 0 or track_index >= len(tracks):
        raise HTTPException(404, f"트랙 인덱스 범위 초과: {track_index}")

    allowed = {"title", "title_ko", "suno_prompt", "lyrics", "mood", "duration_hint", "category"}
    for k, v in body.items():
        if k in allowed:
            tracks[track_index][k] = v

    state_manager.update(project_id, {"designed_tracks": tracks})
    return tracks[track_index]


@router.delete("/{project_id}/{track_index}", summary="곡 삭제")
async def delete_track(project_id: str, track_index: int):
    """인덱스 기반 곡 삭제 + suno_tracks 동기화."""
    state = state_manager.require(project_id)
    tracks: list = state.get("designed_tracks", [])

    if track_index < 0 or track_index >= len(tracks):
        raise HTTPException(404, f"트랙 인덱스 범위 초과: {track_index}")

    removed = tracks.pop(track_index)
    removed_title = removed.get("title", "")

    # index 재정렬
    for i, t in enumerate(tracks):
        t["index"] = i + 1

    # suno_tracks도 동기화: 삭제된 곡 제거 + index 재매핑 (title 기준)
    suno_tracks: list = state.get("suno_tracks", [])
    title_to_new_idx = {t["title"]: t["index"] for t in tracks}
    new_suno = []
    for st in suno_tracks:
        new_idx = title_to_new_idx.get(st.get("title"))
        if new_idx is None:
            continue  # 삭제된 곡
        st["index"] = new_idx
        new_suno.append(st)
    new_suno.sort(key=lambda t: (t.get("index", 0), t.get("slot", 0)))

    state_manager.update(project_id, {"designed_tracks": tracks, "suno_tracks": new_suno})
    return {"deleted": removed}
