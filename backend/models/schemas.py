"""
YouTube Playlist Automator - 핵심 스키마 정의.

SaaS 관련 필드 없음. user_id는 기본값 "default"로 파라미터에만 존재.
나중에 DB+인증 붙일 때 호출부에서 실제 값으로 교체하면 됨.
"""
from __future__ import annotations

from typing import Literal, Optional
from pydantic import BaseModel, Field


# ──────────────────────────── 프로젝트 요청 ────────────────────────────

class ProjectCreate(BaseModel):
    name: str
    playlist_title: str = ""


class RepeatConfig(BaseModel):
    mode: Literal["count", "duration"] = "count"
    count: int = 1           # mode=count: 전체 트랙 반복 횟수
    target_minutes: int = 60  # mode=duration: 목표 총 재생 시간(분)


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    playlist_title: Optional[str] = None
    genre: Optional[str] = None
    mood: Optional[str] = None
    repeat: Optional[RepeatConfig] = None
    channel_id: Optional[str] = None


# ──────────────────────────── 프로젝트 ────────────────────────────

class ProjectConfig(BaseModel):
    """플레이리스트 영상 프로젝트의 기본 설정."""

    project_id: str
    name: str
    genre: str = ""
    mood: str = ""
    target_duration_hours: float = 1.0
    crossfade_ms: int = 3000


# ──────────────────────────── 트랙 ────────────────────────────

class TrackInfo(BaseModel):
    """업로드된 오디오 트랙 하나의 정보."""

    track_id: str
    order: int
    file_name: str
    file_path: str
    title: str = ""
    artist: str = ""
    duration_ms: int = 0
    has_lyrics: bool = False
    lyrics_text: Optional[str] = None
    srt_file_path: Optional[str] = None


# ──────────────────────────── 이미지 카테고리 ────────────────────────────

class SubCategory(BaseModel):
    """이미지 세부 카테고리."""

    sub_id: str
    label: str
    example_keywords: list[str] = []


class ImageCategory(BaseModel):
    """이미지 생성 요청 시 선택 가능한 카테고리."""

    category_id: str
    label: str
    sub_categories: list[SubCategory] = []


class ImageGenRequest(BaseModel):
    """Gemini 이미지 생성 요청 파라미터."""

    category_id: str
    sub_id: str = ""
    mood: str = ""
    time_of_day: str = ""        # morning | afternoon | evening | night
    weather: str = ""             # clear | cloudy | rainy | snowy
    color_tone: str = ""          # warm | cool | neutral | vibrant
    custom_prompt: str = ""
    count: int = 5


# ──────────────────────────── 레이어 설정 ────────────────────────────

class BackgroundConfig(BaseModel):
    """배경 이미지 설정."""

    image_path: str = ""
    ken_burns_effect: bool = True   # 켄번스 효과 (줌인/아웃 애니메이션)
    source: Literal["upload", "generated", "none"] = "none"


class WaveformConfig(BaseModel):
    """파형 비주얼라이저 설정."""

    color: str = "#FFFFFF"
    height: int = 200               # 픽셀
    position: Literal["bottom", "middle", "top"] = "bottom"
    opacity: float = 0.8
    mode: Literal["bar", "line", "mirror"] = "bar"


class TextOverlayConfig(BaseModel):
    """트랙 제목 텍스트 오버레이 설정."""

    show_track_title: bool = True
    track_title_duration_sec: float = 5.0   # 트랙 시작 후 표시 시간
    position: Literal["top-left", "top-center", "bottom-left", "bottom-center"] = "bottom-left"
    font_name: str = "NotoSansKR"
    font_size: int = 48
    font_color: str = "#FFFFFF"


class LyricsConfig(BaseModel):
    """가사 자막 설정."""

    mode: Literal["off", "manual", "srt", "whisper"] = "off"
    lyrics_text: Optional[str] = None      # mode=manual 일 때
    srt_path: Optional[str] = None         # mode=srt 일 때
    font_size: int = 36
    position: Literal["top", "middle", "bottom"] = "bottom"


# ──────────────────────────── 메타데이터 ────────────────────────────

class TimestampEntry(BaseModel):
    """타임스탬프 항목 (설명란에 삽입)."""

    time_str: str       # 예: "0:00", "3:42"
    track_title: str


class Metadata(BaseModel):
    """YouTube 업로드용 메타데이터."""

    title: str = ""
    description: str = ""
    tags: list[str] = []
    pinned_comment: str = ""
    timestamps: list[TimestampEntry] = []


# ──────────────────────────── 레이어 요청 ────────────────────────────

class TextLayerConfig(BaseModel):
    text: str
    font_size: int = 48
    color: str = "#FFFFFF"
    position_x: float = 0.5
    position_y: float = 0.1
    bold: bool = False


class WaveformLayerConfig(BaseModel):
    color: str = "#FFFFFF"
    height: int = 200
    position: Literal["bottom", "middle", "top"] = "bottom"
    opacity: float = 0.8
    style: Literal["bar", "line"] = "bar"


class LayersData(BaseModel):
    text_layers: list[dict] = []
    waveform_layer: Optional[dict] = None


class LayersUpdateRequest(BaseModel):
    layers: LayersData


# ──────────────────────────── YouTube 요청 ────────────────────────────

class YouTubeUploadRequest(BaseModel):
    privacy_status: Literal["private", "unlisted", "public"] = "private"


# ──────────────────────────── CapCut 레이어 ────────────────────────────

class LayerInfo(BaseModel):
    """CapCut 프로젝트의 레이어 하나."""

    layer_name: str
    layer_type: Literal["video", "audio", "text", "effect", "image"]
    start_time_ms: int
    end_time_ms: int
    properties: dict = Field(default_factory=dict)   # 레이어 타입별 추가 속성


# ──────────────────────────── YouTube ────────────────────────────

class YouTubeChannel(BaseModel):
    """연결된 YouTube 채널 정보."""

    channel_id: str
    channel_name: str
    account_email: str
    is_brand_account: bool = False


class UploadRequest(BaseModel):
    """YouTube 업로드 요청."""

    channel_id: str
    video_file_path: str
    metadata: Metadata
    thumbnail_path: Optional[str] = None
    privacy_status: Literal["private", "unlisted", "public"] = "private"


# ──────────────────────────── 프로젝트 전체 상태 ────────────────────────────

class ProjectState(BaseModel):
    """
    프로젝트의 전체 상태. storage/projects/{id}/state.json 에 저장.

    user_id는 현재 항상 "default". 나중에 인증 붙이면 실제 ID로 교체.
    """

    user_id: str = "default"
    project: ProjectConfig
    tracks: list[TrackInfo] = []
    background: BackgroundConfig = Field(default_factory=BackgroundConfig)
    waveform: WaveformConfig = Field(default_factory=WaveformConfig)
    text_overlay: TextOverlayConfig = Field(default_factory=TextOverlayConfig)
    lyrics_config: LyricsConfig = Field(default_factory=LyricsConfig)
    metadata: Metadata = Field(default_factory=Metadata)
    layers: list[LayerInfo] = []
    build_status: Literal["idle", "processing", "done", "error"] = "idle"
    current_step: str = "setup"
    progress_percent: int = 0
