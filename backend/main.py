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

# CORS (개발환경: React dev server 허용)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
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
