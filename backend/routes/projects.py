from fastapi import APIRouter, HTTPException
from models.schemas import ProjectCreate, ProjectUpdate
from core.state_manager import state_manager

router = APIRouter(prefix="/api/projects", tags=["프로젝트"])


@router.post("", summary="프로젝트 생성")
async def create_project(body: ProjectCreate):
    state = state_manager.create(name=body.name, playlist_title=body.playlist_title)
    return state


@router.get("", summary="프로젝트 목록 조회")
async def list_projects():
    return state_manager.list_all(summary=True)


@router.get("/{project_id}", summary="프로젝트 상세 조회")
async def get_project(project_id: str):
    return state_manager.require(project_id)


@router.patch("/{project_id}", summary="프로젝트 수정")
async def update_project(project_id: str, body: ProjectUpdate):
    updates = body.model_dump(exclude_none=True)
    # RepeatConfig pydantic 객체 → dict 변환
    if "repeat" in updates and hasattr(updates["repeat"], "model_dump"):
        updates["repeat"] = updates["repeat"].model_dump()
    state = state_manager.update(project_id, updates)
    if state is None:
        raise HTTPException(404, "프로젝트를 찾을 수 없습니다")
    return state


@router.delete("/{project_id}", summary="프로젝트 삭제")
async def delete_project(project_id: str):
    ok = state_manager.delete(project_id)
    if not ok:
        raise HTTPException(404, "프로젝트를 찾을 수 없습니다")
    return {"deleted": project_id}
