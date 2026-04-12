import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

# Windows에서 Playwright subprocess 지원 (SelectorEventLoop → ProactorEventLoop)
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from config import settings
from routes import build, flow_images, images, layers, metadata, projects, tracks, youtube
from routes import benchmark, channels, track_design, suno as suno_routes

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 스토리지 디렉토리 초기화
    for d in ["projects", "uploads", "outputs"]:
        (settings.storage_dir / d).mkdir(parents=True, exist_ok=True)
    logger.info(f"Storage: {settings.storage_dir.absolute()}")
    logger.info(f"Gemini keys loaded: {len(settings.gemini_api_keys)}")
    yield


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
app.include_router(benchmark.router)
app.include_router(track_design.router)
app.include_router(suno_routes.router)

# 정적 파일 서빙 (빌드된 영상 등)
storage_static = settings.storage_dir
if storage_static.exists():
    app.mount("/storage", StaticFiles(directory=str(storage_static)), name="storage")


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
import subprocess
import json


# ─── API 키 관리 ─────────────────────────────────────────────────────────────

@app.get("/api/settings/gemini")
async def get_gemini_status():
    """Gemini API 키 설정 여부 확인"""
    has_keys = len(settings.gemini_api_keys) > 0 and any(k.strip() for k in settings.gemini_api_keys)
    return {"configured": has_keys, "key_count": len(settings.gemini_api_keys)}


@app.post("/api/settings/gemini")
async def set_gemini_keys(body: dict):
    """Gemini API 키 저장 (.env 파일에 기록)"""
    keys = body.get("keys", [])
    if not keys or not any(k.strip() for k in keys):
        return {"error": "API 키를 입력해주세요"}, 400

    # .env 파일 업데이트
    env_path = Path(settings.storage_dir).parent / ".env"
    if not env_path.exists():
        env_path = Path("/app/.env")

    env_lines = []
    if env_path.exists():
        env_lines = env_path.read_text(encoding="utf-8").splitlines()

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

    env_path.write_text("\n".join(env_lines) + "\n", encoding="utf-8")

    # 런타임에도 반영
    settings.gemini_api_keys = [k.strip() for k in keys if k.strip()]

    return {"status": "ok", "key_count": len(settings.gemini_api_keys)}


@app.get("/api/settings/google-oauth")
async def get_google_oauth_status():
    """Google OAuth 설정 여부 확인"""
    return {
        "configured": bool(settings.google_client_id and settings.google_client_secret),
        "has_client_id": bool(settings.google_client_id),
        "has_client_secret": bool(settings.google_client_secret),
    }


@app.post("/api/settings/google-oauth")
async def set_google_oauth(body: dict):
    """Google OAuth 키 저장"""
    client_id = body.get("client_id", "").strip()
    client_secret = body.get("client_secret", "").strip()

    if not client_id or not client_secret:
        return {"error": "Client ID와 Client Secret 모두 필요합니다"}, 400

    env_path = Path(settings.storage_dir).parent / ".env"
    if not env_path.exists():
        env_path = Path("/app/.env")

    env_lines = []
    if env_path.exists():
        env_lines = env_path.read_text(encoding="utf-8").splitlines()

    updates = {
        "GOOGLE_CLIENT_ID": client_id,
        "GOOGLE_CLIENT_SECRET": client_secret,
    }

    for key, value in updates.items():
        found = False
        for i, line in enumerate(env_lines):
            if line.startswith(key + "="):
                env_lines[i] = f"{key}={value}"
                found = True
                break
        if not found:
            env_lines.append(f"{key}={value}")

    env_path.write_text("\n".join(env_lines) + "\n", encoding="utf-8")

    settings.google_client_id = client_id
    settings.google_client_secret = client_secret

    return {"status": "ok"}


# ─── 에이전트 스킬 관리 ──────────────────────────────────────────────────────

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


@app.post("/api/update")
async def trigger_update():
    """Docker 이미지를 최신으로 pull하고 컨테이너를 재시작합니다."""
    try:
        result = subprocess.run(
            ["docker", "compose", "-f", "docker-compose.prod.yml", "pull", "backend"],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            return {"status": "error", "message": result.stderr}

        # 백그라운드에서 재시작 (현재 요청은 응답 후 종료됨)
        subprocess.Popen(
            ["docker", "compose", "-f", "docker-compose.prod.yml", "up", "-d", "--force-recreate", "backend"],
        )
        return {"status": "updating", "message": "업데이트를 시작합니다. 잠시 후 새로고침해주세요."}
    except Exception as e:
        return {"status": "error", "message": str(e)}
