from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

# .env를 backend/ 실행 시에도 프로젝트 루트에서 찾도록
_HERE = Path(__file__).parent          # backend/
_ROOT = _HERE.parent                   # 프로젝트 루트
_ENV_FILE = _ROOT / ".env" if (_ROOT / ".env").exists() else _HERE / ".env"


class Settings(BaseSettings):
    gemini_api_keys: list[str] = []
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/api/youtube/callback"
    storage_path: str = str(_ROOT / "backend" / "storage")
    browser_headless: bool = True
    youtube_api_key: str = ""

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
