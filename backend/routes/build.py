import asyncio
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse

from core.packager import packager
from core.state_manager import state_manager

router = APIRouter(prefix="/api/projects/{project_id}/build", tags=["빌드"])


@router.get("/status", summary="빌드 상태 조회")
async def get_build_status(project_id: str):
    state = state_manager.require(project_id)
    return state.get("build", {})


@router.post("", summary="영상 빌드 시작")
async def trigger_build(project_id: str, background_tasks: BackgroundTasks):
    """오디오·이미지·레이어를 합쳐 최종 MP4를 생성합니다. 백그라운드로 실행됩니다."""
    state = state_manager.require(project_id)

    if state.get("build", {}).get("status") == "processing":
        raise HTTPException(409, "이미 빌드가 진행 중입니다")

    state_manager.update(
        project_id,
        {"build": {"status": "processing", "progress": 0, "error": None}},
    )

    background_tasks.add_task(_run_build, project_id)
    return {"status": "processing"}


@router.get("/download", summary="완성 영상 다운로드 (MP4)")
async def download_output(project_id: str):
    state = state_manager.require(project_id)
    build = state.get("build", {})
    output_file = build.get("output_file")

    if not output_file or not Path(output_file).exists():
        raise HTTPException(404, "빌드된 영상이 없습니다. 먼저 빌드를 실행하세요.")

    return FileResponse(
        path=output_file,
        filename=f"{state.get('name', 'output')}.mp4",
        media_type="video/mp4",
    )


@router.get("/download-capcut", summary="CapCut 프로젝트 파일 다운로드")
async def download_capcut(project_id: str):
    state = state_manager.require(project_id)
    build = state.get("build", {})
    capcut_file = build.get("capcut_file")

    if not capcut_file or not Path(capcut_file).exists():
        raise HTTPException(404, "CapCut 파일이 없습니다. 먼저 빌드를 실행하세요.")

    return FileResponse(
        path=capcut_file,
        filename=Path(capcut_file).name,
        media_type="application/octet-stream",
    )


# ─── background task ─────────────────────────────────────────────────────────

async def _run_build(project_id: str):
    state = state_manager.get(project_id)
    if not state:
        return

    project_dir = state_manager.project_dir(project_id)

    def on_progress(pct: int, msg: str):
        state_manager.update(project_id, {"build": {"progress": pct}})

    result = await packager.build(state, project_dir, progress_cb=on_progress)

    state_manager.update(
        project_id,
        {
            "build": {
                "status": "done" if not result.get("error") else "error",
                "output_file": result.get("output_file"),
                "capcut_file": result.get("capcut_file"),
                "error": result.get("error"),
                "progress": 100 if not result.get("error") else 0,
            },
            "status": "ready" if not result.get("error") else "setup",
        },
    )
