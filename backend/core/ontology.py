"""
온톨로지 엔진 — 채널/카테고리/무드 기반 속성 자동 결정.

기존 코드 수정 없이 독립 모듈로 동작.
나중에 각 모듈(track_designer, visual_generator, metadata_generator)에서
ontology.resolve(channel_profile) 호출하여 일관된 속성을 받아 사용.

관계 구조:
  Channel → genre(카테고리) → mood → {음악, 이미지, 자막} 속성

주의: 파형(waveform)은 온톨로지 영역이 아님.
  파형은 사용자가 레이어 설정에서 직접 세팅하고, 프리뷰 = CapCut 결과가 100% 일치해야 함.
  템플릿으로 저장하여 재활용.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field, asdict
from typing import Optional

logger = logging.getLogger(__name__)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  속성 데이터 클래스
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@dataclass
class MusicAttributes:
    """음악 생성 속성."""
    tempo_range: tuple[int, int] = (90, 120)
    instruments: list[str] = field(default_factory=lambda: ["piano", "strings"])
    key_type: str = "major"            # major | minor | modal
    energy_level: str = "medium"       # low | medium | high
    vocal_type: str = "none"           # none | humming | vocal


@dataclass
class ImageAttributes:
    """이미지 생성 속성."""
    color_tone: str = "warm"           # warm | cool | dark | pastel | vivid
    subject_keywords: list[str] = field(default_factory=lambda: ["nature", "abstract"])
    lighting: str = "soft"             # soft | bright | dim | golden | neon
    style: str = "cinematic"           # cinematic | minimal | watercolor | 3d | anime


@dataclass
class SubtitleAttributes:
    """자막/텍스트 속성."""
    tone: str = "neutral"              # neutral | poetic | motivational | minimal
    language_style: str = "formal"     # formal | casual | poetic
    font_weight: str = "regular"       # light | regular | bold
    position: str = "bottom"           # top | center | bottom
    subtitle_type: str = "none"        # none | lyrics | affirmation | description


@dataclass
class ResolvedProfile:
    """온톨로지가 결정한 전체 속성 세트."""
    channel_name: str = ""
    genre: str = ""
    mood: str = ""
    music: MusicAttributes = field(default_factory=MusicAttributes)
    image: ImageAttributes = field(default_factory=ImageAttributes)
    subtitle: SubtitleAttributes = field(default_factory=SubtitleAttributes)
    # 파형(waveform)은 사용자 정의 영역 — 레이어 설정에서 직접 세팅 + 템플릿 저장

    def to_dict(self) -> dict:
        return asdict(self)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  장르 → 무드 매핑
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

GENRE_MOOD_MAP: dict[str, str] = {
    # 한국어 장르명
    "뉴에이지": "calm",
    "클래식": "calm",
    "어쿠스틱": "warm",
    "재즈": "warm",
    "카페음악": "warm",
    "힐링": "calm",
    "명상": "calm",
    "수면": "calm",
    "집중": "focused",
    "로파이": "chill",
    "앰비언트": "calm",
    "일렉트로닉": "energetic",
    "EDM": "energetic",
    "POP": "bright",
    "K-POP": "bright",
    "R&B": "warm",
    "힙합": "energetic",
    "록": "energetic",
    "인디": "warm",
    "동요": "bright",
    "OST": "emotional",
    "보사노바": "chill",
    "라운지": "chill",
    # 영어 장르명
    "new age": "calm",
    "classical": "calm",
    "acoustic": "warm",
    "jazz": "warm",
    "lo-fi": "chill",
    "ambient": "calm",
    "electronic": "energetic",
    "pop": "bright",
    "rock": "energetic",
    "hip-hop": "energetic",
    "r&b": "warm",
    "indie": "warm",
    "meditation": "calm",
    "sleep": "calm",
    "focus": "focused",
    "cafe": "warm",
}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  무드 → 속성 프리셋 (음악 + 이미지 + 자막만)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

MOOD_PRESETS: dict[str, dict] = {
    "calm": {
        "music": MusicAttributes(
            tempo_range=(55, 80), instruments=["piano", "strings", "flute"],
            key_type="major", energy_level="low", vocal_type="none",
        ),
        "image": ImageAttributes(
            color_tone="warm", subject_keywords=["nature", "sunset", "forest", "lake"],
            lighting="golden", style="cinematic",
        ),
        "subtitle": SubtitleAttributes(
            tone="poetic", language_style="formal", font_weight="light",
            position="bottom", subtitle_type="affirmation",
        ),
    },
    "warm": {
        "music": MusicAttributes(
            tempo_range=(70, 100), instruments=["acoustic guitar", "piano", "ukulele"],
            key_type="major", energy_level="medium", vocal_type="humming",
        ),
        "image": ImageAttributes(
            color_tone="warm", subject_keywords=["cafe", "cozy", "autumn", "books"],
            lighting="soft", style="cinematic",
        ),
        "subtitle": SubtitleAttributes(
            tone="neutral", language_style="casual", font_weight="regular",
            position="bottom", subtitle_type="affirmation",
        ),
    },
    "chill": {
        "music": MusicAttributes(
            tempo_range=(65, 90), instruments=["synth pad", "electric piano", "bass"],
            key_type="minor", energy_level="low", vocal_type="none",
        ),
        "image": ImageAttributes(
            color_tone="cool", subject_keywords=["city night", "rain", "neon", "window"],
            lighting="dim", style="cinematic",
        ),
        "subtitle": SubtitleAttributes(
            tone="minimal", language_style="casual", font_weight="light",
            position="bottom", subtitle_type="none",
        ),
    },
    "energetic": {
        "music": MusicAttributes(
            tempo_range=(110, 150), instruments=["synth", "drums", "bass", "electric guitar"],
            key_type="minor", energy_level="high", vocal_type="vocal",
        ),
        "image": ImageAttributes(
            color_tone="vivid", subject_keywords=["abstract", "geometric", "light trails"],
            lighting="bright", style="3d",
        ),
        "subtitle": SubtitleAttributes(
            tone="motivational", language_style="casual", font_weight="bold",
            position="center", subtitle_type="none",
        ),
    },
    "bright": {
        "music": MusicAttributes(
            tempo_range=(95, 130), instruments=["piano", "strings", "synth", "clap"],
            key_type="major", energy_level="medium", vocal_type="humming",
        ),
        "image": ImageAttributes(
            color_tone="pastel", subject_keywords=["sky", "flower", "spring", "bright"],
            lighting="bright", style="cinematic",
        ),
        "subtitle": SubtitleAttributes(
            tone="neutral", language_style="formal", font_weight="regular",
            position="bottom", subtitle_type="affirmation",
        ),
    },
    "focused": {
        "music": MusicAttributes(
            tempo_range=(60, 85), instruments=["piano", "ambient pad", "rain sfx"],
            key_type="modal", energy_level="low", vocal_type="none",
        ),
        "image": ImageAttributes(
            color_tone="dark", subject_keywords=["desk", "library", "minimal", "space"],
            lighting="dim", style="minimal",
        ),
        "subtitle": SubtitleAttributes(
            tone="minimal", language_style="formal", font_weight="light",
            position="bottom", subtitle_type="none",
        ),
    },
    "emotional": {
        "music": MusicAttributes(
            tempo_range=(65, 95), instruments=["piano", "cello", "violin", "choir"],
            key_type="minor", energy_level="medium", vocal_type="humming",
        ),
        "image": ImageAttributes(
            color_tone="cool", subject_keywords=["ocean", "sky", "solitude", "rain"],
            lighting="golden", style="cinematic",
        ),
        "subtitle": SubtitleAttributes(
            tone="poetic", language_style="poetic", font_weight="regular",
            position="bottom", subtitle_type="lyrics",
        ),
    },
}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  조합 규칙 (constraints) — 음악·이미지·자막 간 일관성 보정
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _apply_constraints(profile: ResolvedProfile) -> None:
    """속성 간 일관성 규칙 적용 (in-place)."""
    m, im, s = profile.music, profile.image, profile.subtitle

    # 1. energy_level "high" → 이미지 밝게
    if m.energy_level == "high":
        if im.lighting in ("dim", "soft"):
            im.lighting = "bright"

    # 2. vocal_type "none" → 자막은 lyrics 불가 (가사가 없으니까)
    if m.vocal_type == "none" and s.subtitle_type == "lyrics":
        s.subtitle_type = "affirmation"

    # 3. 자막 tone "poetic" → font_weight bold는 부자연스러움
    if s.tone == "poetic" and s.font_weight == "bold":
        s.font_weight = "regular"

    # 4. color_tone "pastel" + energy "high" → 부조화 보정
    if im.color_tone == "pastel" and m.energy_level == "high":
        im.color_tone = "vivid"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  온톨로지 엔진
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class OntologyEngine:
    """채널 프로필 → 일관된 속성 세트 결정."""

    def resolve(self, channel_profile: dict) -> ResolvedProfile:
        """
        채널 프로필(storage/channels/*.json)을 입력받아
        음악·이미지·자막 속성 세트를 반환.

        사용법:
            from core.ontology import ontology
            profile = ontology.resolve(channel_data)
            # profile.music.tempo_range → (55, 80)
            # profile.image.style → "cinematic"
        """
        genres = channel_profile.get("genre", [])
        name = channel_profile.get("name", "")

        # 1. 장르에서 무드 추론
        mood = self._infer_mood(genres, channel_profile)

        # 2. 무드 프리셋 로드
        preset = MOOD_PRESETS.get(mood, MOOD_PRESETS["warm"])

        # 3. ResolvedProfile 생성
        profile = ResolvedProfile(
            channel_name=name,
            genre=genres[0] if genres else "",
            mood=mood,
            music=MusicAttributes(**asdict(preset["music"])),
            image=ImageAttributes(**asdict(preset["image"])),
            subtitle=SubtitleAttributes(**asdict(preset["subtitle"])),
        )

        # 4. 채널 고유 설정 오버라이드
        self._apply_channel_overrides(profile, channel_profile)

        # 5. 조합 규칙 적용
        _apply_constraints(profile)

        logger.info(f"Ontology resolved: {name} → mood={mood}, energy={profile.music.energy_level}")
        return profile

    def resolve_by_mood(self, mood: str) -> ResolvedProfile:
        """무드를 직접 지정하여 속성 세트 반환 (채널 없이)."""
        preset = MOOD_PRESETS.get(mood, MOOD_PRESETS["warm"])
        profile = ResolvedProfile(
            mood=mood,
            music=MusicAttributes(**asdict(preset["music"])),
            image=ImageAttributes(**asdict(preset["image"])),
            subtitle=SubtitleAttributes(**asdict(preset["subtitle"])),
        )
        _apply_constraints(profile)
        return profile

    def list_moods(self) -> list[str]:
        """사용 가능한 무드 목록."""
        return list(MOOD_PRESETS.keys())

    def _infer_mood(self, genres: list[str], channel: dict) -> str:
        """장르 목록 + 채널 속성에서 무드 추론."""
        # mood_keywords가 있으면 직접 매핑 시도
        mood_kw = channel.get("mood_keywords", [])
        for kw in mood_kw:
            kw_lower = kw.lower().strip()
            if kw_lower in MOOD_PRESETS:
                return kw_lower

        # 장르에서 매핑
        for g in genres:
            g_lower = g.lower().strip()
            if g_lower in GENRE_MOOD_MAP:
                return GENRE_MOOD_MAP[g_lower]

        # has_lyrics 기반 fallback
        if channel.get("has_lyrics") is False:
            return "calm"

        return "warm"  # 기본값

    def _apply_channel_overrides(self, profile: ResolvedProfile, channel: dict) -> None:
        """채널 프로필의 명시적 설정을 온톨로지 결과에 반영."""
        # subtitle_type 오버라이드
        st = channel.get("subtitle_type")
        if st:
            profile.subtitle.subtitle_type = st

        # image_style 오버라이드
        styles = channel.get("image_style", [])
        if styles:
            profile.image.subject_keywords = styles

        # suno_base_prompt가 있으면 음악 속성에 힌트
        suno_prompt = channel.get("suno_base_prompt", "")
        if suno_prompt:
            prompt_lower = suno_prompt.lower()
            if "fast" in prompt_lower or "upbeat" in prompt_lower:
                profile.music.energy_level = "high"
            elif "slow" in prompt_lower or "gentle" in prompt_lower:
                profile.music.energy_level = "low"


    # ━━━ 채널 온톨로지 JSON 저장/로드/자동생성 ━━━━━━━━━━━━━━━━━━━━━━━━━

    def _ontology_dir(self) -> "Path":
        from config import settings
        d = settings.storage_dir / "ontology"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def load_channel_ontology(self, channel_id: str) -> Optional[dict]:
        """storage/ontology/{channel_id}.json 로드. 없으면 None."""
        import json
        from pathlib import Path
        p = self._ontology_dir() / f"{channel_id}.json"
        if not p.exists():
            return None
        return json.loads(p.read_text(encoding="utf-8"))

    def save_channel_ontology(self, channel_id: str, data: dict) -> "Path":
        """storage/ontology/{channel_id}.json 저장."""
        import json
        from pathlib import Path
        p = self._ontology_dir() / f"{channel_id}.json"
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info(f"Ontology saved: {p}")
        return p

    def generate_channel_ontology(self, channel_profile: dict) -> dict:
        """
        채널 프로필에서 온톨로지 JSON을 자동 생성.
        채널의 장르 목록 각각을 카테고리로, 무드 프리셋 기반으로 속성 결정.
        """
        channel_id = channel_profile.get("channel_id", "unknown")
        channel_name = channel_profile.get("name", "")
        genres = channel_profile.get("genre", [])
        has_lyrics = channel_profile.get("has_lyrics", False)
        subtitle_type = channel_profile.get("subtitle_type", "none")

        categories = {}
        for genre in genres:
            g_lower = genre.lower().strip()
            mood_key = GENRE_MOOD_MAP.get(g_lower, "warm")
            preset = MOOD_PRESETS.get(mood_key, MOOD_PRESETS["warm"])

            music_attr = MusicAttributes(**asdict(preset["music"]))
            image_attr = ImageAttributes(**asdict(preset["image"]))
            subtitle_attr = SubtitleAttributes(**asdict(preset["subtitle"]))

            # 채널 설정 반영
            if subtitle_type:
                subtitle_attr.subtitle_type = subtitle_type
            if not has_lyrics and subtitle_attr.subtitle_type == "lyrics":
                subtitle_attr.subtitle_type = "affirmation"

            # 무드 키워드 추출
            mood_words = [mood_key]
            if mood_key == "calm":
                mood_words += ["peaceful", "gentle"]
            elif mood_key == "warm":
                mood_words += ["cozy", "comforting"]
            elif mood_key == "chill":
                mood_words += ["relaxing", "laid-back"]
            elif mood_key == "energetic":
                mood_words += ["dynamic", "powerful"]
            elif mood_key == "bright":
                mood_words += ["cheerful", "upbeat"]
            elif mood_key == "focused":
                mood_words += ["concentrated", "minimal"]
            elif mood_key == "emotional":
                mood_words += ["touching", "deep"]

            # 카테고리명: 장르명을 영어 키로 변환
            cat_key = g_lower.replace(" ", "_")

            categories[cat_key] = {
                "mood": mood_words,
                "music": {
                    "tempo": list(music_attr.tempo_range),
                    "instruments": music_attr.instruments,
                    "energy": music_attr.energy_level,
                    "vocal": music_attr.vocal_type,
                },
                "image": {
                    "color_tone": image_attr.color_tone,
                    "subjects": image_attr.subject_keywords,
                    "lighting": image_attr.lighting,
                    "style": image_attr.style,
                },
                "subtitle": {
                    "tone": subtitle_attr.tone,
                    "style": subtitle_attr.subtitle_type,
                },
            }

        result = {
            "channel": channel_id,
            "channel_name": channel_name,
            "generated_from": "auto",
            "categories": categories,
        }

        # 자동 저장
        self.save_channel_ontology(channel_id, result)
        return result

    def ensure_channel_ontology(self, channel_profile: dict) -> dict:
        """온톨로지가 있으면 로드, 없으면 자동 생성."""
        channel_id = channel_profile.get("channel_id", "")
        existing = self.load_channel_ontology(channel_id)
        if existing:
            return existing
        return self.generate_channel_ontology(channel_profile)

    def list_channel_ontologies(self) -> list[dict]:
        """저장된 모든 채널 온톨로지 목록."""
        import json
        results = []
        for p in sorted(self._ontology_dir().glob("*.json")):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                results.append({
                    "channel": data.get("channel", p.stem),
                    "channel_name": data.get("channel_name", ""),
                    "categories": list(data.get("categories", {}).keys()),
                    "generated_from": data.get("generated_from", "unknown"),
                })
            except Exception:
                continue
        return results


# 싱글턴 인스턴스
ontology = OntologyEngine()
