"""
Google Flow 이미지 생성 라우터.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from browser.flow_automation import FlowAutomation
from config import settings

router = APIRouter(prefix="/api/flow-images", tags=["flow-images"])

# 실행 상태 저장 (메모리)
_tasks: dict[str, dict] = {}


# ── 요청 모델 ──────────────────────────────────────────────────────────────

class GenerateRequest(BaseModel):
    project_id: str
    channel_concept: str
    genre: str
    mood: str
    count: int = 5


class SelectRequest(BaseModel):
    project_id: str
    selected_images: list[str]


# ── 엔드포인트 ─────────────────────────────────────────────────────────────

@router.post("/login", summary="Google Flow 수동 로그인 (headed 브라우저 열림)")
async def login_flow():
    flow = FlowAutomation()
    await flow.login()
    return {"status": "logged_in", "message": "세션 저장 완료"}


@router.post("/run", summary="Flow 이미지 생성 워크플로우 시작")
async def run_flow_images(req: GenerateRequest, background_tasks: BackgroundTasks):
    _tasks[req.project_id] = {"status": "running", "result": None}

    async def _run() -> None:
        flow = FlowAutomation()
        try:
            result = await flow.run(
                channel_concept=req.channel_concept,
                genre=req.genre,
                mood=req.mood,
                project_id=req.project_id,
                count=req.count,
            )
            _tasks[req.project_id] = {"status": "complete", "result": result}
        except Exception as e:
            _tasks[req.project_id] = {"status": "error", "result": str(e)}

    background_tasks.add_task(_run)
    return {"status": "started", "project_id": req.project_id}


@router.get("/status/{project_id}", summary="생성 진행 상태 조회")
async def get_status(project_id: str):
    if project_id not in _tasks:
        raise HTTPException(404, "Task not found")
    return _tasks[project_id]


@router.get("/list/{project_id}", summary="생성된 이미지 목록")
async def list_images(project_id: str):
    img_dir = settings.storage_dir / "projects" / project_id / "bg_candidates"
    if not img_dir.exists():
        return {"images": [], "count": 0}
    images = sorted(
        f.name for f in img_dir.iterdir()
        if f.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")
        and not f.name.startswith("_dom_")  # 스냅샷 제외
    )
    return {"images": images, "count": len(images)}


@router.get("/preview/{project_id}/{filename}", summary="이미지 미리보기")
async def preview_image(project_id: str, filename: str):
    filepath = (
        settings.storage_dir / "projects" / project_id / "bg_candidates" / filename
    )
    if not filepath.exists():
        raise HTTPException(404, "Image not found")
    return FileResponse(filepath)


@router.post("/select", summary="최종 이미지 선택 → bg_selected/ 로 복사")
async def select_images(req: SelectRequest):
    src_dir = settings.storage_dir / "projects" / req.project_id / "bg_candidates"
    dst_dir = settings.storage_dir / "projects" / req.project_id / "bg_selected"
    dst_dir.mkdir(parents=True, exist_ok=True)

    selected = []
    for fname in req.selected_images:
        src = src_dir / fname
        if src.exists():
            shutil.copy2(src, dst_dir / fname)
            selected.append(fname)

    return {"selected": selected, "output_dir": str(dst_dir)}
