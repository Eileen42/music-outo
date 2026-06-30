import sys
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

# .env / storage 루트 결정.
# - 일반 Python 실행: __file__ 기준 backend/, 그 부모를 프로젝트 루트로
# - PyInstaller frozen (EXE): sys.executable 의 폴더(= dist/music-outo) 를 루트로
#   → 사용자 친화적 위치. EXE 옆에 .env, storage 폴더가 생김.
_HERE = Path(__file__).parent          # backend/ (또는 frozen 시 _internal/)
if getattr(sys, "frozen", False):
    _ROOT = Path(sys.executable).parent  # EXE 가 있는 폴더
else:
    _ROOT = _HERE.parent                 # 프로젝트 루트


def _resolve_env_file() -> Path:
    """기존 .env 가 _ROOT 또는 _HERE 에 있으면 그걸 사용. 둘 다 없으면 _ROOT 디폴트.
    덕분에 GeminiSetup 으로 저장한 .env 가 다음 시작 시 같은 위치에서 읽힘."""
    for candidate in (_ROOT / ".env", _HERE / ".env"):
        if candidate.exists():
            return candidate
    return _ROOT / ".env"


_ENV_FILE = _resolve_env_file()
ENV_FILE_PATH = _ENV_FILE  # 외부에서 import 해서 동일 경로에 쓰도록


class Settings(BaseSettings):
    gemini_api_keys: list[str] = []
    storage_path: str = str(_ROOT / "backend" / "storage")
    browser_headless: bool = True

    # Google Flow 자동화
    chrome_download_dir: str = str(Path.home() / "Downloads")
    flow_prompts_suffix: str = (
        ", 1920x1080, cinematic, high quality, "
        "YouTube music video background, no text, no watermark"
    )
    flow_generation_timeout: int = 120   # 이미지 생성 대기 최대 초
    flow_manual_timeout: int = 600       # 수동 fallback 대기 최대 초

    model_config = SettingsConfigDict(env_file=str(_ENV_FILE), extra="ignore")

    @property
    def storage_dir(self) -> Path:
        p = Path(self.storage_path)
        # 상대경로면 프로젝트 루트 기준으로 해석
        if not p.is_absolute():
            p = _ROOT / p
        return p

    @property
    def projects_path(self) -> Path:
        p = self.storage_dir / "projects"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def browser_sessions_dir(self) -> Path:
        p = self.storage_dir / "browser_sessions"
        p.mkdir(parents=True, exist_ok=True)
        return p


settings = Settings()
