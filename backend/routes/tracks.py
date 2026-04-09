import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile

from core.audio_pipeline import audio_pipeline
from core.lyrics_sync import lyrics_sync
from core.state_manager import state_manager
from core.waveform_generator import waveform_generator

router = APIRouter(prefix="/api/projects/{project_id}/tracks", tags=["트랙"])


@router.get("", summary="트랙 목록 조회")
async def list_tracks(project_id: str):
    state = state_manager.require(project_id)
    return state.get("tracks", [])


@router.post("", summary="오디오 파일 업로드")
async def upload_track(
    project_id: str,
    file: UploadFile = File(...),
    title: str = Form(""),
    lyrics: str = Form(""),
    background_tasks: BackgroundTasks = None,
):
    state = state_manager.require(project_id)
    project_dir = state_manager.project_dir(project_id)

    file_bytes = await file.read()
    info = await audio_pipeline.process_upload(file_bytes, file.filename, project_dir)

    track_id = info["id"]
    track = {
        "id": track_id,
        "title": title or Path(file.filename).stem,
        "artist": "",
        "order": len(state.get("tracks", [])),
        "filename": file.filename,
        "stored_path": info["stored_path"],
        "duration": info["duration"],
        "sample_rate": info["sample_rate"],
        "channels": info["channels"],
        "waveform_file": None,
        "lyrics": lyrics or None,
        "lyrics_sync_file": None,
    }

    tracks = state.get("tracks", [])
    tracks.append(track)
    state_manager.update(project_id, {"tracks": tracks})

    if background_tasks:
        background_tasks.add_task(
            _generate_waveform, project_id, track_id, Path(info["stored_path"]), project_dir
        )

    return track


@router.patch("/{track_id}", summary="트랙 정보 수정")
async def update_track(project_id: str, track_id: str, body: dict):
    state = state_manager.require(project_id)
    tracks = state.get("tracks", [])
    track = next((t for t in tracks if t["id"] == track_id), None)
    if not track:
        raise HTTPException(404, "트랙을 찾을 수 없습니다")

    allowed = {"title", "artist", "order", "lyrics"}
    for k, v in body.items():
        if k in allowed:
            track[k] = v

    state_manager.update(project_id, {"tracks": tracks})
    return track


@router.delete("/{track_id}", summary="트랙 삭제")
async def delete_track(project_id: str, track_id: str):
    state = state_manager.require(project_id)
    tracks = [t for t in state.get("tracks", []) if t["id"] != track_id]
    state_manager.update(project_id, {"tracks": tracks})
    return {"deleted": track_id}


@router.post("/{track_id}/reorder", summary="트랙 순서 변경")
async def reorder_tracks(project_id: str, track_id: str, body: dict):
    """body: {"order": [...track_ids...]}"""
    state = state_manager.require(project_id)
    order: list[str] = body.get("order", [])
    tracks_map = {t["id"]: t for t in state.get("tracks", [])}

    reordered = []
    for i, tid in enumerate(order):
        if tid in tracks_map:
            tracks_map[tid]["order"] = i
            reordered.append(tracks_map[tid])

    state_manager.update(project_id, {"tracks": reordered})
    return reordered


@router.post("/{track_id}/transcribe", summary="가사 자동 추출 (Whisper)")
async def transcribe_track(
    project_id: str,
    track_id: str,
    background_tasks: BackgroundTasks,
    language: str = None,
):
    state = state_manager.require(project_id)
    track = next((t for t in state.get("tracks", []) if t["id"] == track_id), None)
    if not track:
        raise HTTPException(404, "트랙을 찾을 수 없습니다")

    background_tasks.add_task(
        _run_transcription,
        project_id,
        track_id,
        Path(track["stored_path"]),
        state_manager.project_dir(project_id),
        language,
    )
    return {"status": "가사 추출 시작됨"}


# ─── background helpers ───────────────────────────────────────────────────────

async def _generate_waveform(
    project_id: str, track_id: str, audio_path: Path, project_dir: Path
):
    try:
        out = project_dir / "audio" / f"{track_id}_waveform.png"
        await waveform_generator.generate_image(audio_path, out)

        state = state_manager.get(project_id)
        if state:
            tracks = state.get("tracks", [])
            for t in tracks:
                if t["id"] == track_id:
                    t["waveform_file"] = str(out)
            state_manager.update(project_id, {"tracks": tracks})
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"파형 생성 실패: {e}")


async def _run_transcription(
    project_id: str,
    track_id: str,
    audio_path: Path,
    project_dir: Path,
    language: str | None,
):
    try:
        result = await lyrics_sync.transcribe(audio_path, language=language)
        out = project_dir / "audio" / f"{track_id}_lyrics.json"
        await lyrics_sync.save_sync_file(result, out, format="json")

        state = state_manager.get(project_id)
        if state:
            tracks = state.get("tracks", [])
            for t in tracks:
                if t["id"] == track_id:
                    t["lyrics"] = result.get("text", "")
                    t["lyrics_sync_file"] = str(out)
            state_manager.update(project_id, {"tracks": tracks})
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"가사 추출 실패: {e}")
