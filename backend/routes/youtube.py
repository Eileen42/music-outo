"""YouTube 업로드 — 브라우저 기반.

사용자가 MP4 파일을 직접 드래그 업로드하고, 이 라우트는:
1. Edge 를 CDP 모드로 띄워 YouTube Studio 업로드 페이지 + outputs 폴더 표시
2. Playwright 워커가 제목/설명/태그/썸네일을 자동 입력

Google OAuth / YouTube Data API v3 를 사용하지 않는다. 따라서 토큰 파일,
client_secret, API 업로드 진행률 등 OAuth 관련 엔드포인트는 없음.
"""
import asyncio
import logging
import os
import subprocess
from datetime import datetime

import httpx
from fastapi import APIRouter, BackgroundTasks, HTTPException

from core.state_manager import state_manager

router = APIRouter(prefix="/api/youtube", tags=["YouTube"])
log = logging.getLogger(__name__)


@router.post("/open-studio/{project_id}", summary="YouTube 업로드 브라우저 열기")
async def open_studio(project_id: str):
    """Edge 를 CDP 모드(9224)로 기동해 업로드 페이지 진입, outputs 폴더도 연다."""
    state_manager.require(project_id)
    project_dir = state_manager.project_dir(project_id)
    outputs_dir = project_dir / "outputs"

    upload_url = "https://www.youtube.com/upload"

    cdp_alive = False
    try:
        async with httpx.AsyncClient(timeout=2) as client:
            resp = await client.get("http://localhost:9224/json/version")
        cdp_alive = resp.status_code == 200
    except Exception:
        pass

    if not cdp_alive:
        def _launch_edge():
            import time as _t
            os.system('taskkill /F /IM msedge.exe >nul 2>&1')
            _t.sleep(2)
            subprocess.Popen([
                r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                "--remote-debugging-port=9224",
                "--restore-last-session",
                upload_url,
            ])
            _t.sleep(3)
        await asyncio.to_thread(_launch_edge)
    else:
        try:
            async with httpx.AsyncClient(timeout=3) as client:
                await client.put(f"http://localhost:9224/json/new?{upload_url}")
        except Exception:
            await asyncio.to_thread(
                subprocess.Popen,
                [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe", upload_url],
            )

    if outputs_dir.exists():
        await asyncio.to_thread(os.startfile, str(outputs_dir))

    return {"status": "opened", "cdp_port": 9224, "url": upload_url}


@router.post("/fill-metadata/{project_id}", summary="YouTube Studio 메타데이터 자동 입력")
async def fill_metadata(project_id: str, background_tasks: BackgroundTasks):
    """CDP 로 열려있는 YouTube Studio 페이지에 제목/설명/태그/썸네일을 자동 입력."""
    log.info(f"[메타입력] API 요청 수신: project_id={project_id}")
    state_manager.require(project_id)

    from routes._fill_meta_worker import fill_metadata as worker_task

    async def _run():
        def _write_initial():
            state_manager.update(project_id, {
                "browser_fill_progress": {
                    "step": "워커 시작됨", "current": 0, "total": 10,
                    "done": False, "error": "", "updated_at": datetime.now().isoformat(),
                }
            })
        try:
            await asyncio.to_thread(_write_initial)
        except Exception:
            pass
        try:
            await worker_task(project_id)
        except Exception as e:
            log.error(f"[메타입력] 워커 예외: {e}", exc_info=True)
            def _write_fail():
                state_manager.update(project_id, {
                    "browser_fill_progress": {
                        "step": f"실패: {type(e).__name__}",
                        "current": 0, "total": 10, "done": True, "error": str(e)[:200],
                        "updated_at": datetime.now().isoformat(),
                    }
                })
            try:
                await asyncio.to_thread(_write_fail)
            except Exception:
                pass

    asyncio.create_task(_run())
    log.info("[메타입력] 인라인 워커 시작됨")
    return {"status": "filling"}


@router.get("/fill-progress/{project_id}", summary="메타데이터 자동 입력 진행상황")
async def get_fill_progress(project_id: str):
    state = state_manager.get(project_id)
    if not state:
        raise HTTPException(404, "프로젝트 없음")
    return state.get("browser_fill_progress") or {
        "step": "대기 중", "current": 0, "total": 10, "done": False, "error": "",
    }
