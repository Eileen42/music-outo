"""
채널 프로필 관리 모듈.

DB 없음 — storage/channels/{channel_id}.json 이 유일한 진실의 원천.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from config import settings

logger = logging.getLogger(__name__)

_MAX_BENCHMARK_HISTORY = 10


class ChannelProfile:
    """채널 프로필 로드 / 저장 / 수정"""

    @property
    def _profiles_dir(self) -> Path:
        p = settings.storage_dir / "channels"
        p.mkdir(parents=True, exist_ok=True)
        return p

    # ──────────────────────────── internal ────────────────────────────

    def _path(self, channel_id: str) -> Path:
        return self._profiles_dir / f"{channel_id}.json"

    def _read(self, channel_id: str) -> dict:
        p = self._path(channel_id)
        if not p.exists():
            raise FileNotFoundError(f"채널 프로필을 찾을 수 없습니다: {channel_id}")
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)

    def _write(self, channel_id: str, profile: dict) -> Path:
        p = self._path(channel_id)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(profile, f, ensure_ascii=False, indent=2)
        return p

    @staticmethod
    def _now() -> str:
        return datetime.utcnow().isoformat()

    # ──────────────────────────── public API ────────────────────────────

    def load(self, channel_id: str) -> dict:
        """storage/channels/{channel_id}.json 로드. 없으면 FileNotFoundError."""
        return self._read(channel_id)

    def save(self, channel_id: str, profile: dict) -> Path:
        """JSON 저장, 경로 반환."""
        profile["updated_at"] = self._now()
        return self._write(channel_id, profile)

    def list_all(self) -> list[dict]:
        """모든 채널 프로필 요약 목록 반환."""
        result = []
        for p in sorted(self._profiles_dir.glob("*.json")):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                result.append({
                    "channel_id": data.get("channel_id", p.stem),
                    "name":       data.get("name", ""),
                    "genre":      data.get("genre", []),
                    "has_lyrics": data.get("has_lyrics", False),
                    "subtitle_type": data.get("subtitle_type", "none"),
                    "updated_at": data.get("updated_at", ""),
                })
            except Exception as e:
                logger.warning(f"채널 프로필 읽기 실패 [{p.name}]: {e}")
        return result

    def get_latest_benchmark(self, channel_id: str) -> Optional[dict]:
        """benchmark_history에서 최신 항목 반환. 없으면 None."""
        profile = self._read(channel_id)
        history: list = profile.get("benchmark_history", [])
        return history[-1] if history else None

    def add_benchmark(self, channel_id: str, benchmark: dict) -> None:
        """benchmark_history에 추가 후 저장. 최대 10개 유지."""
        profile = self._read(channel_id)
        history: list = profile.setdefault("benchmark_history", [])
        history.append(benchmark)
        if len(history) > _MAX_BENCHMARK_HISTORY:
            profile["benchmark_history"] = history[-_MAX_BENCHMARK_HISTORY:]
        self.save(channel_id, profile)

    def create_default(
        self,
        channel_id: str,
        name: str,
        genre: list[str],
        has_lyrics: bool,
        subtitle_type: str,
        mood_keywords: list[str],
        image_style: list[str],
        suno_base_prompt: str,
    ) -> dict:
        """새 채널 프로필 생성 및 저장."""
        profile = {
            "channel_id":       channel_id,
            "name":             name,
            "genre":            genre,
            "has_lyrics":       has_lyrics,
            "subtitle_type":    subtitle_type,   # "none" | "affirmation" | "lyrics"
            "mood_keywords":    mood_keywords,
            "image_style":      image_style,
            "suno_base_prompt": suno_base_prompt,
            "benchmark_history": [],
            "created_at":       self._now(),
            "updated_at":       self._now(),
        }
        self._write(channel_id, profile)
        logger.info(f"채널 프로필 생성: {channel_id} ({name})")
        return profile

    def update(self, channel_id: str, updates: dict) -> dict:
        """부분 업데이트 후 저장된 프로필 반환."""
        profile = self._read(channel_id)
        for k, v in updates.items():
            if k not in ("channel_id", "created_at", "benchmark_history"):
                profile[k] = v
        self.save(channel_id, profile)
        return profile


# ──────────────────────────── 싱글톤 ────────────────────────────

channel_profile = ChannelProfile()


# ──────────────────────────── 기본 채널 3개 초기화 ────────────────────────────

def init_default_channels() -> list[dict]:
    """
    기본 채널 3개 생성.
    이미 존재하면 건너뜀.

    - serenity_m : 명상/수면, 가사없음, 확언자막
    - jazz_cafe  : 재즈,     가사없음, 자막없음
    - sunday_pop : 팝,       가사있음, 가사자막
    """
    defaults = [
        dict(
            channel_id="serenity_m",
            name="Serenity M",
            genre=["meditation", "sleep", "ambient"],
            has_lyrics=False,
            subtitle_type="affirmation",
            mood_keywords=["peaceful", "calming", "healing", "gentle"],
            image_style=["soft bokeh", "nature landscape", "minimalist", "pastel tones"],
            suno_base_prompt=(
                "ambient meditation music, soft piano, gentle strings, "
                "528hz healing frequency, slow tempo, no lyrics, peaceful"
            ),
        ),
        dict(
            channel_id="jazz_cafe",
            name="Jazz Café",
            genre=["jazz", "lofi", "cafe"],
            has_lyrics=False,
            subtitle_type="none",
            mood_keywords=["cozy", "warm", "relaxed", "sophisticated"],
            image_style=["cafe interior", "warm lighting", "vintage", "urban"],
            suno_base_prompt=(
                "smooth jazz, acoustic guitar, upright bass, light drums, "
                "cafe atmosphere, instrumental, laid-back tempo"
            ),
        ),
        dict(
            channel_id="sunday_pop",
            name="Sunday Pop",
            genre=["pop", "indie pop"],
            has_lyrics=True,
            subtitle_type="lyrics",
            mood_keywords=["uplifting", "cheerful", "energetic", "feel-good"],
            image_style=["bright colors", "sunshine", "outdoor", "youthful"],
            suno_base_prompt=(
                "indie pop, catchy melody, electric guitar, synth, "
                "upbeat tempo, feel-good vibes, radio-friendly"
            ),
        ),
    ]

    created = []
    for kw in defaults:
        cid = kw["channel_id"]
        try:
            channel_profile.load(cid)
            logger.info(f"채널 이미 존재 — 건너뜀: {cid}")
        except FileNotFoundError:
            profile = channel_profile.create_default(**kw)
            created.append(profile)

    return created
