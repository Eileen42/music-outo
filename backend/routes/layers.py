import uuid
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile

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


@router.post("/srt", summary="SRT 자막 파일 업로드")
async def upload_srt(project_id: str, file: UploadFile = File(...)):
    """SRT 파일 업로드 → 파싱 → subtitle_entries로 저장."""
    state_manager.require(project_id)
    project_dir = state_manager.project_dir(project_id)

    content = (await file.read()).decode("utf-8", errors="replace")

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
