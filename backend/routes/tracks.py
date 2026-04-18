import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

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
        background_tasks.add_task(_rebuild_subtitles, project_id)

    return track


@router.patch("/{track_id}", summary="트랙 정보 수정")
async def update_track(
    project_id: str,
    track_id: str,
    body: dict,
    background_tasks: BackgroundTasks = None,
):
    state = state_manager.require(project_id)
    tracks = state.get("tracks", [])
    track = next((t for t in tracks if t["id"] == track_id), None)
    if not track:
        raise HTTPException(404, "트랙을 찾을 수 없습니다")

    allowed = {"title", "artist", "order", "lyrics"}
    lyrics_changed = "lyrics" in body and body.get("lyrics") != track.get("lyrics")
    order_changed = "order" in body and body.get("order") != track.get("order")
    for k, v in body.items():
        if k in allowed:
            track[k] = v

    state_manager.update(project_id, {"tracks": tracks})

    if background_tasks and (lyrics_changed or order_changed):
        background_tasks.add_task(_rebuild_subtitles, project_id)

    return track


@router.delete("/{track_id}", summary="트랙 삭제")
async def delete_track(project_id: str, track_id: str, background_tasks: BackgroundTasks = None):
    state = state_manager.require(project_id)
    tracks = [t for t in state.get("tracks", []) if t["id"] != track_id]
    state_manager.update(project_id, {"tracks": tracks})
    if background_tasks:
        background_tasks.add_task(_rebuild_subtitles, project_id)
    return {"deleted": track_id}


@router.post("/{track_id}/reorder", summary="트랙 순서 변경")
async def reorder_tracks(project_id: str, track_id: str, body: dict, background_tasks: BackgroundTasks = None):
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
    if background_tasks:
        background_tasks.add_task(_rebuild_subtitles, project_id)
    return reordered


@router.post("/{track_id}/subtitle/build", summary="단일 트랙 자막 즉시 빌드 (동기)")
async def build_track_subtitle(
    project_id: str,
    track_id: str,
    refine_sync: bool = True,
    smart_split: bool = True,
):
    """입력된 가사를 오디오와 forced alignment → 트랙 단위 SRT 생성. 완료 후 반환.

    Query params:
        refine_sync: librosa onset/RMS 기반 싱크 보정 (기본 True)
        smart_split: 묵음 전환점+의미 단위 스마트 분할 (기본 True)
    """
    state = state_manager.require(project_id)
    track = next((t for t in state.get("tracks", []) if t["id"] == track_id), None)
    if not track:
        raise HTTPException(404, "트랙을 찾을 수 없습니다")
    if not track.get("lyrics"):
        raise HTTPException(400, "가사가 없습니다")

    from core.subtitle_builder import build_for_project
    from core.channel_profile import channel_profile

    display_mode = "source_only"
    channel_id = state.get("channel_id")
    if channel_id:
        try:
            display_mode = channel_profile.load(channel_id).get("subtitle_display_mode", "source_only")
        except FileNotFoundError:
            pass

    project_dir = state_manager.project_dir(project_id)
    # 전체 프로젝트 재빌드 (병렬이므로 단일 트랙만 돌려도 비용 거의 동일)
    result = await build_for_project(
        project_id, state.get("tracks", []), project_dir,
        display_mode=display_mode,
        refine_sync_enabled=refine_sync,
        smart_split_enabled=smart_split,
    )
    state_manager.update(project_id, {
        "subtitle_entries": result["subtitle_entries"],
        "subtitle_srt_path": result["srt_path"],
    })

    # 이 트랙의 SRT 경로 찾기
    track_srt = next((r.get("srt_path") for r in result["track_results"] if r.get("track_id") == track_id), None)
    return {
        "track_id": track_id,
        "srt_path": track_srt,
        "project_srt_path": result["srt_path"],
        "entries_count": sum(r.get("segments_count", 0) for r in result["track_results"] if r.get("track_id") == track_id),
    }


@router.get("/{track_id}/subtitle", summary="트랙 SRT 파일 다운로드")
async def download_track_subtitle(project_id: str, track_id: str):
    """트랙 단위 SRT 파일 반환. 다운로드 파일명은 트랙 제목 기반."""
    import re
    state = state_manager.require(project_id)
    track = next((t for t in state.get("tracks", []) if t["id"] == track_id), None)
    if not track:
        raise HTTPException(404, "트랙을 찾을 수 없습니다")

    project_dir = state_manager.project_dir(project_id)
    srt_path = project_dir / "subtitles" / f"{track_id}.srt"
    if not srt_path.exists() or srt_path.stat().st_size == 0:
        raise HTTPException(404, "자막 파일이 없습니다. 먼저 가사 동기화를 실행하세요.")

    # 트랙 제목으로 파일명 생성 (파일시스템 금지 문자 제거)
    title = (track.get("title") or track_id).strip()
    safe_title = re.sub(r'[\\/:*?"<>|]', "_", title)[:80].strip() or track_id
    return FileResponse(
        path=str(srt_path),
        filename=f"{safe_title}.srt",
        media_type="application/x-subrip",
    )


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


async def _rebuild_subtitles(project_id: str):
    """트랙 변경 시 전체 자막을 재빌드한다 (forced alignment + 번역)."""
    import logging
    logger = logging.getLogger(__name__)
    try:
        from core.subtitle_builder import build_for_project
        from core.channel_profile import channel_profile

        state = state_manager.get(project_id)
        if not state:
            return
        tracks = state.get("tracks", [])
        if not tracks:
            return

        # 가사 있는 트랙이 하나라도 있을 때만 실행
        if not any(t.get("lyrics") for t in tracks):
            logger.info(f"자막 재빌드 건너뜀 (가사 있는 트랙 없음): {project_id}")
            return

        # 채널 설정 로드
        display_mode = "source_only"
        channel_id = state.get("channel_id")
        if channel_id:
            try:
                channel = channel_profile.load(channel_id)
                display_mode = channel.get("subtitle_display_mode", "source_only")
            except FileNotFoundError:
                pass

        project_dir = state_manager.project_dir(project_id)
        result = await build_for_project(
            project_id, tracks, project_dir, display_mode=display_mode
        )

        state_manager.update(project_id, {
            "subtitle_entries": result["subtitle_entries"],
            "subtitle_srt_path": result["srt_path"],
        })
        logger.info(f"자막 재빌드 완료: {project_id} — {len(result['subtitle_entries'])} 엔트리")
    except Exception as e:
        logger.error(f"자막 재빌드 실패 ({project_id}): {e}", exc_info=True)


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
