import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, UploadFile

from config import settings
from core.state_manager import state_manager

router = APIRouter(prefix="/api/projects/{project_id}/layers", tags=["레이어"])


@router.get("")
async def get_layers(project_id: str):
    state = state_manager.require(project_id)
    return state.get("layers", {})


@router.put("")
async def update_layers(project_id: str, body: dict):
    """layers 전체 업데이트 (dict 직접 저장)."""
    state_manager.require(project_id)
    layers_data = body.get("layers", body)
    state = state_manager.update(project_id, {"layers": layers_data})
    return state["layers"]


@router.put("/waveform")
async def update_waveform(project_id: str, body: dict):
    state_manager.require(project_id)
    state = state_manager.update(project_id, {"layers": {"waveform_layer": body}})
    return state["layers"]


@router.post("/text")
async def add_text_layer(project_id: str, body: dict):
    state = state_manager.require(project_id)
    layers = state.get("layers", {})
    text_layers = layers.get("text_layers", [])

    new_layer = dict(body)
    new_layer["id"] = str(uuid.uuid4())
    text_layers.append(new_layer)

    state_manager.update(project_id, {"layers": {"text_layers": text_layers}})
    return new_layer


@router.put("/text/{layer_id}")
async def update_text_layer(project_id: str, layer_id: str, body: dict):
    state = state_manager.require(project_id)
    layers = state.get("layers", {})
    text_layers = layers.get("text_layers", [])

    layer = next((l for l in text_layers if l["id"] == layer_id), None)
    if not layer:
        raise HTTPException(404, "Text layer not found")

    protected = {"id"}
    for k, v in body.items():
        if k not in protected:
            layer[k] = v

    state_manager.update(project_id, {"layers": {"text_layers": text_layers}})
    return layer


@router.delete("/text/{layer_id}")
async def delete_text_layer(project_id: str, layer_id: str):
    state = state_manager.require(project_id)
    layers = state.get("layers", {})
    text_layers = [l for l in layers.get("text_layers", []) if l["id"] != layer_id]
    state_manager.update(project_id, {"layers": {"text_layers": text_layers}})
    return {"deleted": layer_id}


@router.post("/image", summary="이미지 레이어 업로드")
async def upload_image_layer(project_id: str, file: UploadFile = File(...)):
    """이미지 파일 업로드 → image_layers에 추가."""
    state_manager.require(project_id)
    project_dir = state_manager.project_dir(project_id)

    img_dir = project_dir / "images" / "layers"
    img_dir.mkdir(parents=True, exist_ok=True)

    layer_id = str(uuid.uuid4())
    ext = Path(file.filename).suffix or ".png"
    dest = img_dir / f"{layer_id}{ext}"
    content = await file.read()
    dest.write_bytes(content)

    new_layer = {
        "id": layer_id,
        "name": file.filename,
        "stored_path": str(dest),
        "position_x": 0.5,
        "position_y": 0.5,
        "scale": 1.0,
        "opacity": 1.0,
    }

    state = state_manager.require(project_id)
    layers = state.get("layers", {})
    image_layers = layers.get("image_layers", [])
    image_layers.append(new_layer)
    state_manager.update(project_id, {"layers": {"image_layers": image_layers}})

    return new_layer


@router.delete("/image/{layer_id}", summary="이미지 레이어 삭제")
async def delete_image_layer(project_id: str, layer_id: str):
    state = state_manager.require(project_id)
    layers = state.get("layers", {})
    image_layers = [l for l in layers.get("image_layers", []) if l["id"] != layer_id]
    state_manager.update(project_id, {"layers": {"image_layers": image_layers}})
    return {"deleted": layer_id}


@router.get("/fonts", summary="시스템 폰트 목록")
async def list_fonts():
    """Windows 레지스트리에서 설치된 폰트의 정식 이름을 가져옵니다."""
    import winreg

    fonts_dir = Path("C:/Windows/Fonts")
    custom_dir = Path.home() / "AppData" / "Local" / "Microsoft" / "Windows" / "Fonts"

    fonts = []
    # 레지스트리에서 정식 이름 → 파일명 매핑 읽기
    for reg_path in [
        r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts",
    ]:
        try:
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, reg_path)
            count = winreg.QueryInfoKey(key)[1]
            for i in range(count):
                reg_name, filename, _ = winreg.EnumValue(key, i)
                if not filename.lower().endswith((".ttf", ".otf")):
                    continue
                # "Arial Bold (TrueType)" → "Arial Bold"
                family = reg_name.split(" (")[0].strip()
                # 파일 경로 결정
                fp = Path(filename)
                if not fp.is_absolute():
                    fp = fonts_dir / filename
                fonts.append({"name": family, "path": str(fp)})
            winreg.CloseKey(key)
        except OSError:
            pass

    # 사용자 폰트 폴더 (레지스트리에 없는 것 보완)
    if custom_dir.exists():
        registered_files = {f["path"].lower() for f in fonts}
        for f in list(custom_dir.glob("*.ttf")) + list(custom_dir.glob("*.otf")):
            if str(f).lower() not in registered_files:
                fonts.append({"name": f.stem, "path": str(f)})

    # 이름순 정렬, 중복 이름 제거 (Bold/Italic 변형 포함)
    seen = set()
    unique = []
    for f in sorted(fonts, key=lambda x: x["name"].lower()):
        if f["name"] not in seen:
            seen.add(f["name"])
            unique.append(f)

    return unique


@router.post("/srt/auto", summary="음원에서 자동 SRT 생성 (Whisper)")
async def auto_generate_srt(project_id: str, background_tasks: BackgroundTasks):
    """전체 트랙을 순서대로 Whisper로 추출 → subtitle_entries에 저장."""
    from fastapi import BackgroundTasks as _BT
    state = state_manager.require(project_id)
    tracks = state.get("tracks", [])
    if not tracks:
        raise HTTPException(400, "트랙이 없습니다")

    background_tasks.add_task(_run_auto_srt, project_id, tracks)
    return {"status": "processing", "message": "자막 자동 생성 시작됨"}


async def _run_auto_srt(project_id: str, tracks: list):
    """전체 트랙을 순서대로 Whisper 추출 → 통합 SRT."""
    import logging
    logger = logging.getLogger(__name__)
    try:
        from core.lyrics_sync import lyrics_sync

        all_entries = []
        time_offset = 0.0

        for track in tracks:
            audio_path = track.get("stored_path", "")
            if not audio_path or not Path(audio_path).exists():
                time_offset += track.get("duration", 0)
                continue

            result = await lyrics_sync.transcribe(Path(audio_path))
            for seg in result.get("segments", []):
                all_entries.append({
                    "start": round(time_offset + seg["start"], 3),
                    "end": round(time_offset + seg["end"], 3),
                    "text": seg["text"],
                })
            time_offset += track.get("duration", 0)

        # SRT 파일 저장
        project_dir = state_manager.project_dir(project_id)
        srt_dir = project_dir / "subtitles"
        srt_dir.mkdir(parents=True, exist_ok=True)
        srt_path = srt_dir / "auto_generated.srt"

        lines = []
        for i, e in enumerate(all_entries, 1):
            def fmt(s):
                h = int(s // 3600); m = int((s % 3600) // 60); sec = s % 60; ms = int((sec % 1) * 1000)
                return f"{h:02d}:{m:02d}:{int(sec):02d},{ms:03d}"
            lines.append(f"{i}\n{fmt(e['start'])} --> {fmt(e['end'])}\n{e['text']}\n")
        srt_path.write_text("\n".join(lines), encoding="utf-8")

        state_manager.update(project_id, {
            "subtitle_entries": all_entries,
            "subtitle_srt_path": str(srt_path),
        })
        logger.info(f"Auto SRT: {len(all_entries)} entries for {project_id}")
    except Exception as e:
        logger.error(f"Auto SRT failed: {e}", exc_info=True)


@router.post("/srt", summary="SRT 자막 파일 업로드")
async def upload_srt(project_id: str, file: UploadFile = File(...)):
    """SRT 파일 업로드 → 파싱 → subtitle_entries로 저장."""
    state_manager.require(project_id)
    project_dir = state_manager.project_dir(project_id)

    raw = await file.read()
    # 다양한 줄바꿈 정규화: \r\r\n, \r\n, \r → \n
    import re as _re
    content = raw.decode("utf-8-sig", errors="replace")
    content = _re.sub(r"\r+\n", "\n", content)
    content = content.replace("\r", "\n")

    # SRT 파싱
    entries = []
    blocks = content.strip().split("\n\n")
    for block in blocks:
        lines = block.strip().split("\n")
        if len(lines) < 3:
            continue
        # 타임코드 줄
        tc_line = lines[1] if len(lines) > 1 else ""
        parts = tc_line.split("-->")
        if len(parts) != 2:
            continue

        def parse_tc(s: str) -> float:
            s = s.strip().replace(",", ".")
            segs = s.split(":")
            if len(segs) == 3:
                return float(segs[0]) * 3600 + float(segs[1]) * 60 + float(segs[2])
            return 0

        start = parse_tc(parts[0])
        end = parse_tc(parts[1])
        text = "\n".join(lines[2:]).strip()
        if text:
            entries.append({"start": start, "end": end, "text": text})

    # 파일 저장
    srt_dir = project_dir / "subtitles"
    srt_dir.mkdir(parents=True, exist_ok=True)
    dest = srt_dir / file.filename
    dest.write_text(content, encoding="utf-8")

    state_manager.update(project_id, {
        "subtitle_srt_path": str(dest),
        "subtitle_entries": entries,
    })

    return {
        "filename": file.filename,
        "entries_count": len(entries),
        "stored_path": str(dest),
    }
