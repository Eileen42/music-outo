import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

# Windows에서 Playwright subprocess 지원 (SelectorEventLoop → ProactorEventLoop)
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from config import settings, ENV_FILE_PATH
from core.errors import SunoUIChangedError, SunoGenerationError, SunoSessionError
from core.state_manager import state_manager
from routes import build, flow_images, images, layers, metadata, projects, tracks, youtube
from routes import channels, track_design, suno_batch, suno as suno_routes
from routes import ontology_routes

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 스토리지 디렉토리 초기화
    for d in ["projects", "uploads", "outputs"]:
        (settings.storage_dir / d).mkdir(parents=True, exist_ok=True)
    logger.info(f"Storage: {settings.storage_dir.absolute()}")
    logger.info(f"Gemini keys loaded: {len(settings.gemini_api_keys)}")
    # 서버 재시작 시 stuck된 빌드 자동 초기화
    _cleanup_stuck_builds()
    # 곡 설계 진행상황도 동일 처리 — running 으로 남은 task 는 interrupted 로 강등
    _cleanup_stuck_design()
    # Suno 일괄 생성도 동일 처리. 서버 재시작 시 in-memory _suno_tasks 는 비어있어
    # 무관하지만, _suno_progress.json 디스크 상태가 "running" 으로 남아있으면
    # /suno-status 폴링이나 stale 감지가 헷갈려 새 batch-create 가 409 로 떨어질 수 있음.
    _cleanup_stuck_suno()
    yield


def _cleanup_stuck_builds():
    """서버 종료로 중단된 processing 상태 빌드를 error로 전환."""
    import json
    projects_dir = settings.storage_dir / "projects"
    if not projects_dir.exists():
        return
    for state_file in projects_dir.glob("*/state.json"):
        try:
            data = json.loads(state_file.read_text(encoding="utf-8"))
            build = data.get("build", {})
            if build.get("status") == "processing":
                name = data.get("name", state_file.parent.name)
                logger.info(f"Stuck build 초기화: {name} (progress={build.get('progress')})")
                build["status"] = None
                build["progress"] = 0
                build["error"] = None
                data["build"] = build
                state_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            logger.warning(f"Stuck build cleanup failed for {state_file}: {e}")


def _cleanup_stuck_design():
    """곡 설계 백그라운드 task 가 서버 재시작으로 사라졌는데 _design_progress.json 에
    running 으로 남아있으면 사용자 안내 메시지와 함께 interrupted 로 강등.

    routes/track_design.py 의 GET 엔드포인트도 같은 강등을 on-demand 로 한다.
    이쪽은 startup 시 디스크 상태를 미리 정리해두는 것이 다름 (UI 첫 폴링 전에도 OK).
    """
    import json
    projects_dir = settings.storage_dir / "projects"
    if not projects_dir.exists():
        return
    for progress_file in projects_dir.glob("*/_design_progress.json"):
        try:
            data = json.loads(progress_file.read_text(encoding="utf-8"))
            if data.get("status") == "running":
                pid = progress_file.parent.name
                logger.info(f"Stuck design 초기화: project={pid}")
                data["status"] = "interrupted"
                data["message"] = "서버 재시작으로 작업이 중단되었습니다. 다시 시작해주세요."
                progress_file.write_text(
                    json.dumps(data, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
        except Exception as e:
            logger.warning(f"Stuck design cleanup failed for {progress_file}: {e}")


def _cleanup_stuck_suno():
    """Suno 일괄 생성 runner subprocess 가 서버 재시작 / 비정상 종료로 사라졌는데
    _suno_progress.json 이 "running" 으로 남아있으면 interrupted 로 강등.

    in-memory _suno_tasks 는 서버 재시작 시 자동으로 비워지지만, 디스크 진행파일은
    그대로 남아 stale 감지(age/status)를 통과해버려 새 batch-create 가 영영 409 로
    떨어지는 케이스를 차단한다.
    """
    import json
    projects_dir = settings.storage_dir / "projects"
    if not projects_dir.exists():
        return
    for progress_file in projects_dir.glob("*/_suno_progress.json"):
        try:
            data = json.loads(progress_file.read_text(encoding="utf-8"))
            if data.get("status") == "running":
                pid = progress_file.parent.name
                logger.info(f"Stuck Suno 초기화: project={pid}")
                data["status"] = "interrupted"
                data["message"] = "서버 재시작으로 작업이 중단되었습니다. 다시 시작해주세요."
                progress_file.write_text(
                    json.dumps(data, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
        except Exception as e:
            logger.warning(f"Stuck Suno cleanup failed for {progress_file}: {e}")


app = FastAPI(
    title="YouTube 플레이리스트 영상 자동화",
    description="로컬 1인 사용 도구. 오디오 트랙 → 이미지 → 메타데이터 → 빌드 → YouTube 업로드",
    version="1.0.0",
    lifespan=lifespan,
    openapi_tags=[
        {"name": "프로젝트", "description": "프로젝트 생성·조회·수정·삭제"},
        {"name": "트랙", "description": "오디오 파일 업로드·관리·파형 생성·가사 추출"},
        {"name": "이미지", "description": "배경·썸네일 이미지 업로드 및 카테고리 분류"},
        {"name": "메타데이터", "description": "YouTube 제목·설명·태그·고정댓글 AI 생성"},
        {"name": "레이어", "description": "텍스트·파형 레이어 설정"},
        {"name": "빌드", "description": "영상 빌드 실행·상태 확인·결과 다운로드"},
        {"name": "YouTube", "description": "OAuth 인증 및 YouTube 업로드"},
    ],
)

# CORS (로컬 dev + Vercel 호스팅 허용)
_cors_origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:8000",
]
# Vercel 도메인 허용 (.env에 ALLOWED_ORIGINS 추가 가능)
import os as _os
_extra = _os.getenv("ALLOWED_ORIGINS", "")
if _extra:
    _cors_origins.extend(o.strip() for o in _extra.split(",") if o.strip())

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_origin_regex=r"https://.*\.vercel\.app",  # 모든 Vercel 배포 URL 허용
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── 도메인 예외 → HTTP 응답 매핑 ────────────────────────────────────────────
# 라우트에서 명시적으로 잡지 않고 raise SunoXxxError 만 해도 적절한 코드로 변환된다.
# 라우트가 자체적으로 try/except 로 처리한 경우엔 거기서 끝나므로 이 핸들러까지 안 옴.

@app.exception_handler(SunoUIChangedError)
async def _suno_ui_changed_handler(_request: Request, exc: SunoUIChangedError) -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={"detail": f"Suno 화면이 변경된 것 같습니다. 잠시 후 다시 시도해주세요. ({exc})"},
    )


@app.exception_handler(SunoGenerationError)
async def _suno_generation_handler(_request: Request, exc: SunoGenerationError) -> JSONResponse:
    # rate limit / insufficient credits / try again — 429 Too Many Requests
    return JSONResponse(status_code=429, content={"detail": str(exc)})


@app.exception_handler(SunoSessionError)
async def _suno_session_handler(_request: Request, _exc: SunoSessionError) -> JSONResponse:
    return JSONResponse(
        status_code=401,
        content={"detail": "Suno 로그인 세션이 만료되었습니다. 다시 로그인해주세요."},
    )


# 라우터 등록
app.include_router(projects.router)
app.include_router(tracks.router)
app.include_router(images.router)
app.include_router(metadata.router)
app.include_router(layers.router)
app.include_router(build.router)
app.include_router(youtube.router)
app.include_router(flow_images.router)
app.include_router(channels.router)
app.include_router(ontology_routes.router)
# suno_batch 의 명시적 /{pid}/suno-* 라우트가 track_design 의 catch-all
# /{pid}/{track_index} 보다 먼저 매칭되도록 등록 순서를 명시한다.
app.include_router(suno_batch.router)
app.include_router(track_design.router)
app.include_router(suno_routes.router)

# 정적 파일 서빙 (빌드된 영상 등)
storage_static = settings.storage_dir
if storage_static.exists():
    app.mount("/storage", StaticFiles(directory=str(storage_static)), name="storage")


# ─── SPA 프론트엔드 서빙 ─────────────────────────────────────────────────────
# 일반 Python 실행: backend/../frontend/dist
# PyInstaller(frozen): sys._MEIPASS/frontend_dist 에 번들됨
def _resolve_frontend_dist() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "frontend_dist"  # type: ignore[attr-defined]
    return Path(__file__).parent.parent / "frontend" / "dist"


_frontend_dist = _resolve_frontend_dist()
if _frontend_dist.exists():
    # html=True 가 디렉토리 접근 시 index.html 반환. /api/* 와 /ws/* 는 라우트 우선이므로 안전.
    # ※ 라우터/Mount 모두 등록된 뒤 마지막 catch-all 로 동작하도록 파일 끝에서도 mount 가능.
    pass  # 실제 mount 는 모든 라우터 등록 후 파일 끝에서 수행


# ─── WebSocket (빌드 진행상황 실시간 전달) ─────────────────────────────────────

class ConnectionManager:
    def __init__(self):
        self.active: dict[str, list[WebSocket]] = {}

    async def connect(self, project_id: str, ws: WebSocket):
        await ws.accept()
        self.active.setdefault(project_id, []).append(ws)

    def disconnect(self, project_id: str, ws: WebSocket):
        if project_id in self.active:
            self.active[project_id].discard(ws)

    async def broadcast(self, project_id: str, data: dict):
        for ws in list(self.active.get(project_id, [])):
            try:
                await ws.send_json(data)
            except Exception:
                self.active[project_id].discard(ws)


manager = ConnectionManager()


@app.websocket("/ws/{project_id}")
async def websocket_endpoint(ws: WebSocket, project_id: str):
    await manager.connect(project_id, ws)
    try:
        while True:
            await ws.receive_text()  # 연결 유지 (ping)
    except WebSocketDisconnect:
        manager.disconnect(project_id, ws)


@app.get("/health")
async def health():
    return {"status": "ok", "storage": str(settings.storage_path)}


# ─── 버전 & 업데이트 ─────────────────────────────────────────────────────────

from version import VERSION
import json


# ─── API 키 관리 ─────────────────────────────────────────────────────────────

@app.get("/api/settings/gemini")
async def get_gemini_status():
    """Gemini API 키 설정 여부 확인"""
    has_keys = len(settings.gemini_api_keys) > 0 and any(k.strip() for k in settings.gemini_api_keys)
    return {"configured": has_keys, "key_count": len(settings.gemini_api_keys)}


_LOCALHOSTS = {"127.0.0.1", "::1", "localhost"}


@app.post("/api/settings/gemini")
async def set_gemini_keys(request: Request, body: dict):
    """Gemini API 키 저장 (.env 파일에 기록).

    이 엔드포인트는 .env 파일을 직접 덮어쓰므로 외부에서 호출되면 위험하다.
    1인 로컬 도구라는 정체성을 지키기 위해 클라이언트가 localhost 일 때만 허용한다.
    """
    client_host = request.client.host if request.client else ""
    if client_host not in _LOCALHOSTS:
        raise HTTPException(403, "이 엔드포인트는 로컬에서만 호출 가능합니다.")

    keys = body.get("keys", [])
    if not keys or not any(k.strip() for k in keys):
        return {"error": "API 키를 입력해주세요"}, 400

    # config.py 의 _resolve_env_file() 과 동일 위치에 저장 (저장/읽기 일관성)
    env_path = ENV_FILE_PATH
    try:
        env_path.parent.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        return {"error": f".env 디렉토리 생성 실패: {e}"}, 500

    env_lines = []
    if env_path.exists():
        try:
            env_lines = env_path.read_text(encoding="utf-8").splitlines()
        except Exception:
            env_lines = []

    # GEMINI_API_KEYS 라인 교체 또는 추가
    new_line = f'GEMINI_API_KEYS={json.dumps(keys)}'
    found = False
    for i, line in enumerate(env_lines):
        if line.startswith("GEMINI_API_KEYS"):
            env_lines[i] = new_line
            found = True
            break
    if not found:
        env_lines.append(new_line)

    try:
        env_path.write_text("\n".join(env_lines) + "\n", encoding="utf-8")
    except Exception as e:
        return {"error": f".env 저장 실패 ({env_path}): {e}"}, 500

    # 런타임에도 반영 (다음 재시작 안 해도 즉시 사용 가능)
    settings.gemini_api_keys = [k.strip() for k in keys if k.strip()]

    return {"status": "ok", "key_count": len(settings.gemini_api_keys), "saved_to": str(env_path)}


# ─── 에이전트 스킬 관리 ──────────────────────────────────────────────────────

# ─── 파형 사전 생성 ──────────────────────────────────────────────────────────

_wf_progress: dict[str, dict] = {}


@app.post("/api/waveform/create")
async def create_waveform(body: dict, background_tasks: BackgroundTasks):
    """파형 MOV 사전 생성 (비동기)."""
    pid = body.get("project_id", "")
    state = state_manager.require(pid)
    tracks = state.get("tracks", [])
    if not tracks:
        raise HTTPException(400, "트랙이 없습니다")

    # 첫 번째 트랙 오디오 사용 (에너지 추출용)
    audio_path = Path(tracks[0].get("stored_path", ""))
    if not audio_path.exists():
        raise HTTPException(400, "오디오 파일 없음")

    assets_dir = settings.storage_dir / "projects" / pid / "assets"

    _wf_progress[pid] = {"ready": False, "progress": 0}

    def on_progress(pct: int):
        _wf_progress[pid]["progress"] = pct

    async def _task():
        try:
            from core.waveform_generator import waveform_generator
            await waveform_generator.create_waveform_mov(
                audio_path=audio_path,
                output_dir=assets_dir,
                duration=body.get("duration", 10),
                fps=body.get("fps", 24),
                bar_count=body.get("bar_count", 20),
                bar_width=body.get("bar_width", 4),
                bar_gap=body.get("bar_gap", 3),
                uniformity=body.get("uniformity", 0.3),
                color=body.get("color", "#FFFFFF"),
                opacity=body.get("opacity", 0.8),
                bar_height=body.get("bar_height", 120),
                bar_align=body.get("bar_align", "center"),
                scale=body.get("scale", 1.0),
                position_x=body.get("position_x", 0.5),
                position_y=body.get("position_y", 0.7),
                style=body.get("style", "bar"),
                progress_cb=on_progress,
            )
            mov = assets_dir / "waveform_loop.mov"
            _wf_progress[pid] = {
                "ready": True, "progress": 100,
                "file_size": f"{mov.stat().st_size / 1024 / 1024:.1f}MB" if mov.exists() else "0",
            }
        except Exception as e:
            _wf_progress[pid] = {"ready": False, "progress": 0, "error": str(e)}

    background_tasks.add_task(_task)
    return {"status": "creating", "project_id": pid}


@app.get("/api/waveform/status/{project_id}")
async def waveform_status(project_id: str):
    """파형 생성 상태."""
    if project_id in _wf_progress:
        return _wf_progress[project_id]
    # 이미 파일이 있는지 확인
    mov = settings.storage_dir / "projects" / project_id / "assets" / "waveform_loop.mov"
    if mov.exists():
        return {"ready": True, "progress": 100, "file_size": f"{mov.stat().st_size / 1024 / 1024:.1f}MB"}
    return {"ready": False, "progress": 0}


@app.get("/api/waveform/energy/{project_id}")
async def waveform_energy(project_id: str):
    """파형 에너지 데이터 (프론트 프리뷰용)."""
    import json as _json
    energy_file = settings.storage_dir / "projects" / project_id / "assets" / "waveform_energy.json"
    if not energy_file.exists():
        raise HTTPException(404, "에너지 데이터 없음 — 파형을 먼저 생성하세요")
    return _json.loads(energy_file.read_text(encoding="utf-8"))


# ─── Suno HTTP API ───────────────────────────────────────────────────────────

@app.post("/api/suno/capture")
async def suno_capture_api():
    """Suno 내부 API 엔드포인트 캡처 (Edge CDP 필요)."""
    from core.suno_api import suno_api
    result = await suno_api.capture_api()
    return {"endpoints": len(result.get("endpoints", [])), "captured": result}


@app.post("/api/suno/refresh-token")
async def suno_refresh():
    """Suno JWT 토큰 갱신 (Playwright headless)."""
    from core.suno_api import suno_api
    ok = await suno_api.refresh_token()
    return {"refreshed": ok}


@app.get("/api/suno/credits")
async def suno_credits():
    """Suno 크레딧 조회 (토큰 만료 시 자동 갱신)."""
    from core.suno_api import suno_api
    if not suno_api._cookies:
        suno_api.load_session()
    # 토큰 갱신 후 조회
    auth = await suno_api._get_auth_token()
    if not auth:
        return {"error": "토큰 갱신 실패"}
    return await suno_api.get_credits()


@app.post("/api/suno/test-create")
async def suno_test_create(body: dict):
    """Suno HTTP API로 곡 1개 테스트 생성."""
    from core.suno_api import suno_api
    clips = await suno_api.create_song(
        prompt=body.get("prompt", "peaceful piano ambient"),
        title=body.get("title", "Test Song"),
        lyrics=body.get("lyrics", ""),
        instrumental=body.get("instrumental", True),
    )
    return {"clips": clips}


# ─── QA 검수 ─────────────────────────────────────────────────────────────────

@app.get("/api/projects/{project_id}/qa")
async def qa_verify(project_id: str):
    """프로젝트의 곡 파일 완성도 검수."""
    from agents.suno_qa import suno_qa_agent
    return suno_qa_agent.verify(project_id)


@app.post("/api/projects/{project_id}/qa/fix")
async def qa_fix_links(project_id: str):
    """파일은 있지만 연결 안 된 곡 자동 연결."""
    from agents.suno_qa import suno_qa_agent
    return suno_qa_agent.fix_links(project_id)


@app.post("/api/projects/{project_id}/qa/cleanup")
async def qa_cleanup(project_id: str):
    """중복/고아/빈파일 정리."""
    from agents.suno_qa import suno_qa_agent
    return suno_qa_agent.cleanup(project_id)


@app.post("/api/projects/{project_id}/qa/final")
async def qa_final_check(project_id: str):
    """최종 검수 (cleanup + fix + verify)."""
    from agents.suno_qa import suno_qa_agent
    return suno_qa_agent.final_check(project_id)


@app.get("/api/agents/skills")
async def list_agent_skills():
    """작곡/작사 에이전트의 사용 가능한 스킬 목록."""
    from agents.composer import ComposerAgent
    from agents.lyricist import LyricistAgent
    return {
        "composer": ComposerAgent.list_available_skills(),
        "lyricist": LyricistAgent.list_available_skills(),
    }


@app.get("/api/agents/skills/{agent_name}/{skill_id}")
async def get_skill_content(agent_name: str, skill_id: str):
    """스킬 파일 내용 조회 (미리보기용)."""
    skill_dir = Path(__file__).parent / "templates" / "skills" / agent_name
    skill_path = skill_dir / f"{skill_id}.md"
    if not skill_path.exists():
        return {"error": "스킬을 찾을 수 없습니다"}, 404
    content = skill_path.read_text(encoding="utf-8")
    return {"id": skill_id, "agent": agent_name, "content": content}


@app.get("/api/version")
async def get_version():
    return {"version": VERSION}


def _parse_ver(v: str) -> tuple:
    """'1.2.3' → (1,2,3). 숫자 외 문자는 무시. 비교 가능한 튜플로 변환."""
    out = []
    for part in (v or "").split("."):
        digits = "".join(ch for ch in part if ch.isdigit())
        out.append(int(digits) if digits else 0)
    return tuple(out) or (0,)


def _is_newer(latest: str, current: str) -> bool:
    """latest 가 current 보다 '진짜 더 높은' 버전일 때만 True.

    단순 문자열 비교(!=)는 더 낮은/옛 버전으로도 업데이트를 권하는 위험이 있어
    반드시 숫자 버전 비교를 쓴다. (예: 1.0.2 는 1.1.0 보다 낮으므로 업데이트 아님)
    """
    return bool(latest) and _parse_ver(latest) > _parse_ver(current)


@app.get("/api/update/check")
async def check_update():
    """GitHub Releases 에서 최신 버전 확인. EXE 사용자는 새 EXE 받아서 재설치."""
    import urllib.request
    try:
        req = urllib.request.Request(
            "https://api.github.com/repos/Eileen42/music-outo/releases/latest",
            headers={"Accept": "application/vnd.github+json"},
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            data = json.loads(r.read())
        latest = (data.get("tag_name") or "").lstrip("v")
        return {
            "current": VERSION,
            "latest": latest,
            "update_available": _is_newer(latest, VERSION),
            "release_url": data.get("html_url"),
            "exe_download_url": next(
                (a["browser_download_url"] for a in data.get("assets", [])
                 if a.get("name", "").endswith(".exe")),
                None,
            ),
        }
    except Exception as e:
        return {"error": str(e), "current": VERSION}


# 자동 업데이트 진행 상태 (프론트가 /api/update/progress 로 폴링)
#   phase: idle | downloading | installing | restarting | error
_update_progress = {
    "phase": "idle", "percent": 0,
    "downloaded_mb": 0.0, "total_mb": 0.0,
    "latest": "", "error": "",
}


def _do_update(url: str, latest: str) -> None:
    """백그라운드 스레드: 설치파일을 진행률과 함께 내려받고 설치 → 앱 재시작."""
    import os
    import subprocess
    import tempfile
    import time
    import urllib.request

    try:
        tmp = Path(tempfile.gettempdir()) / "music-outo-update"
        tmp.mkdir(parents=True, exist_ok=True)
        setup_path = tmp / "music-outo-setup.exe"

        # ── 다운로드 (청크 단위로 받아 % 갱신) ──
        _update_progress.update(phase="downloading", percent=0, downloaded_mb=0.0, latest=latest, error="")
        req = urllib.request.Request(url, headers={"Accept": "application/octet-stream"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            total = int(resp.headers.get("Content-Length") or 0)
            _update_progress["total_mb"] = round(total / 1024 / 1024, 1)
            downloaded = 0
            with open(setup_path, "wb") as f:
                while True:
                    chunk = resp.read(262144)  # 256KB
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    _update_progress["downloaded_mb"] = round(downloaded / 1024 / 1024, 1)
                    if total:
                        _update_progress["percent"] = int(downloaded * 100 / total)
        _update_progress.update(phase="installing", percent=100)

        # ── 설치 배치 작성 (앱 종료 대기 → 조용히 설치 → 재실행 → 자기삭제) ──
        app_exe = Path(sys.executable)
        bat = tmp / "apply_update.bat"
        bat.write_text(
            "@echo off\r\n"
            ":waitloop\r\n"
            'tasklist /FI "IMAGENAME eq music-outo.exe" 2>nul | find /I "music-outo.exe" >nul && (\r\n'
            "  timeout /t 1 /nobreak >nul\r\n"
            "  goto waitloop\r\n"
            ")\r\n"
            f'"{setup_path}" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART\r\n'
            f'start "" "{app_exe}"\r\n'
            'del "%~f0" >nul 2>&1\r\n',
            encoding="utf-8",
        )
        flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
        subprocess.Popen(["cmd", "/c", str(bat)], creationflags=flags, close_fds=True)

        # ── 앱 강제 종료 (파일 잠금 해제 → 배치가 설치 진행) ──
        _update_progress["phase"] = "restarting"
        time.sleep(1.5)
        os._exit(0)
    except Exception as e:
        _update_progress.update(phase="error", error=str(e)[:200])


@app.get("/api/update/progress")
async def update_progress():
    """자동 업데이트 진행 상태 (다운로드 %, 단계)."""
    return _update_progress


@app.post("/api/update/install")
async def install_update():
    """최신 버전 설치파일을 진행률과 함께 내려받아 설치하고 앱을 자동 재시작한다.

    실제 다운로드/설치는 백그라운드 스레드(_do_update)에서 진행하며,
    프론트는 /api/update/progress 로 진행률(%)·단계를 폴링한다.
    ※ EXE(설치본)에서만 동작. ※ 사용자 데이터(storage/.env)는 Excludes 로 보존.
    """
    import threading

    if not getattr(sys, "frozen", False):
        return {"ok": False, "error": "개발 모드에서는 자동 업데이트를 사용할 수 없습니다. (설치본에서만 가능)"}

    # 이미 진행 중이면 중복 시작 방지
    if _update_progress["phase"] in ("downloading", "installing", "restarting"):
        return {"ok": True, "alreadyRunning": True}

    # 최신 릴리스의 setup.exe 주소 확인
    import urllib.request
    try:
        req = urllib.request.Request(
            "https://api.github.com/repos/Eileen42/music-outo/releases/latest",
            headers={"Accept": "application/vnd.github+json"},
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
        latest = (data.get("tag_name") or "").lstrip("v")
        url = next(
            (a["browser_download_url"] for a in data.get("assets", [])
             if a.get("name", "").endswith(".exe")),
            None,
        )
    except Exception as e:
        return {"ok": False, "error": f"릴리스 확인 실패: {e}"}
    if not url:
        return {"ok": False, "error": "릴리스에 설치파일(.exe)이 없습니다."}
    if not _is_newer(latest, VERSION):
        return {"ok": False, "error": f"이미 최신 버전입니다. (현재 {VERSION}, 최신 {latest})"}

    threading.Thread(target=_do_update, args=(url, latest), daemon=True).start()
    return {"ok": True, "started": True, "latest": latest}


# ─── SPA mount (catch-all) ──────────────────────────────────────────────────
# 모든 라우트 등록 뒤에 와야 /api/*, /ws/*, /health, /storage 가 우선순위 가짐.
if _frontend_dist.exists():
    app.mount("/", StaticFiles(directory=str(_frontend_dist), html=True), name="spa")
