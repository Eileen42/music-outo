import uuid

from fastapi import APIRouter, HTTPException

from core.state_manager import state_manager
from models.schemas import LayersUpdateRequest, TextLayerConfig, WaveformLayerConfig

router = APIRouter(prefix="/api/projects/{project_id}/layers", tags=["레이어"])


@router.get("")
async def get_layers(project_id: str):
    state = state_manager.require(project_id)
    return state.get("layers", {})


@router.put("")
async def update_layers(project_id: str, body: LayersUpdateRequest):
    state_manager.require(project_id)
    state = state_manager.update(
        project_id, {"layers": body.layers.model_dump()}
    )
    return state["layers"]


@router.put("/waveform")
async def update_waveform(project_id: str, body: WaveformLayerConfig):
    state_manager.require(project_id)
    state = state_manager.update(
        project_id, {"layers": {"waveform_layer": body.model_dump()}}
    )
    return state["layers"]


@router.post("/text")
async def add_text_layer(project_id: str, body: TextLayerConfig):
    state = state_manager.require(project_id)
    layers = state.get("layers", {})
    text_layers = layers.get("text_layers", [])

    new_layer = body.model_dump()
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

    allowed = {"text", "font_size", "color", "position_x", "position_y", "bold"}
    for k, v in body.items():
        if k in allowed:
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
