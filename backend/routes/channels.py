from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.channel_profile import channel_profile, init_default_channels

router = APIRouter(prefix="/api/channels", tags=["channels"])


# ──────────────────────────── schemas ────────────────────────────

class UploadSettings(BaseModel):
    default_privacy: str = "private"        # private | unlisted | public
    default_tags: list[str] = []
    default_description: str = ""
    auto_add_playlist: bool = False


class ChannelCreate(BaseModel):
    channel_id: str
    name: str
    genre: list[str]
    has_lyrics: bool = False
    subtitle_type: str = "none"   # "none" | "affirmation" | "lyrics"
    mood_keywords: list[str] = []
    image_style: list[str] = []
    suno_base_prompt: str = ""
    upload_settings: UploadSettings = UploadSettings()


class ChannelUpdate(BaseModel):
    name: str | None = None
    genre: list[str] | None = None
    has_lyrics: bool | None = None
    subtitle_type: str | None = None
    mood_keywords: list[str] | None = None
    image_style: list[str] | None = None
    suno_base_prompt: str | None = None
    upload_settings: UploadSettings | None = None


# ──────────────────────────── routes ────────────────────────────

@router.get("", summary="전체 채널 목록")
async def list_channels():
    return channel_profile.list_all()


@router.get("/{channel_id}", summary="특정 채널 프로필")
async def get_channel(channel_id: str):
    try:
        return channel_profile.load(channel_id)
    except FileNotFoundError:
        raise HTTPException(404, f"채널을 찾을 수 없습니다: {channel_id}")


@router.post("", summary="새 채널 생성")
async def create_channel(body: ChannelCreate):
    try:
        channel_profile.load(body.channel_id)
        raise HTTPException(409, f"이미 존재하는 채널 ID: {body.channel_id}")
    except FileNotFoundError:
        pass

    profile = channel_profile.create_default(
        channel_id=body.channel_id,
        name=body.name,
        genre=body.genre,
        has_lyrics=body.has_lyrics,
        subtitle_type=body.subtitle_type,
        mood_keywords=body.mood_keywords,
        image_style=body.image_style,
        suno_base_prompt=body.suno_base_prompt,
    )
    # 업로드 설정 추가 저장
    profile["upload_settings"] = body.upload_settings.model_dump()
    channel_profile.save(body.channel_id, profile)
    return profile


@router.put("/{channel_id}", summary="채널 수정")
async def update_channel(channel_id: str, body: ChannelUpdate):
    try:
        updates = body.model_dump(exclude_none=True)
        # upload_settings Pydantic 객체 → dict 변환
        if "upload_settings" in updates and hasattr(updates["upload_settings"], "model_dump"):
            updates["upload_settings"] = updates["upload_settings"].model_dump()
        return channel_profile.update(channel_id, updates)
    except FileNotFoundError:
        raise HTTPException(404, f"채널을 찾을 수 없습니다: {channel_id}")


@router.post("/init-defaults", summary="기본 3개 채널 생성")
async def init_defaults():
    created = init_default_channels()
    return {
        "created": len(created),
        "channels": [c["channel_id"] for c in created],
        "message": "이미 존재하는 채널은 건너뜀",
    }
