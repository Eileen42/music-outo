"""
AI 곡 설계 모듈 — 핵심 자동화 엔진.

채널 프로필 + 벤치마크 분석 → 2단계로 곡 목록 설계.

Step 1. project_concept 확정 (BPM·악기·장르·분위기 공통값 결정)
Step 2. 개별 곡 생성 (컨셉 고정, 멜로디·뉘앙스만 변형)

Suno 프롬프트 출력 형식:
  Genre: ...
  Mood: ...
  Tempo: ...
  Instrumentation: ...
  Sound Effects/Atmosphere: ...
  Additional Descriptors: ...
"""
from __future__ import annotations

import json
import logging

from core.gemini_client import gemini_client

logger = logging.getLogger(__name__)


class TrackDesigner:
    """채널 프로필 + 벤치마크 분석 → 곡 설계"""

    # ──────────────────────────── public ────────────────────────────

    async def design_tracks(
        self,
        channel_profile: dict,
        benchmark: dict | None,
        count: int = 20,
    ) -> dict:
        """
        2단계 곡 설계.

        Returns:
            {
              "concept": { ... },   ← 프로젝트 공통 컨셉
              "tracks":  [ ... ],   ← 개별 곡 설계 리스트
            }
        """
        # ── Step 1: 프로젝트 컨셉 확정 ──
        concept = await self._build_concept(channel_profile, benchmark, count)
        logger.info(f"프로젝트 컨셉 확정: {concept.get('project_name', '')}")

        # ── Step 2: 개별 곡 설계 ──
        tracks = await self._build_tracks(concept, channel_profile, count)
        logger.info(f"곡 설계 완료: {len(tracks)}곡")

        return {"concept": concept, "tracks": tracks}

    async def generate_affirmations(self, count: int, mood: str) -> list[str]:
        """subtitle_type='affirmation' 채널용 확언 문구 생성."""
        prompt = f"""긍정 확언 문구 {count}개를 생성해.
분위기: {mood}

규칙:
- 한국어, 1문장씩
- 명상/수면용, 따뜻하고 위로가 되는 톤
- "나는", "나의", "오늘" 등으로 시작
- JSON 배열로 반환: ["문구1", "문구2", ...]"""

        try:
            result = await gemini_client.generate_json(prompt)
            if isinstance(result, list):
                return [str(s) for s in result]
            if isinstance(result, dict):
                for v in result.values():
                    if isinstance(v, list):
                        return [str(s) for s in v]
            return []
        except Exception as e:
            logger.error(f"확언 문구 생성 실패: {e}")
            raise

    async def regenerate_single(self, track: dict, channel_profile: dict, concept: dict | None = None) -> dict:
        """
        갤러리에서 개별 곡 재생성.
        concept가 있으면 프로젝트 컨셉을 유지하면서 다른 곡 생성.
        """
        has_lyrics = channel_profile.get("has_lyrics", False)

        concept_block = ""
        if concept:
            concept_block = f"""
프로젝트 공통 컨셉 (반드시 유지):
- Genre: {concept.get('genre', '')}
- Tempo: {concept.get('tempo', '')} ({concept.get('bpm_range', '')} BPM)
- Instrumentation: {concept.get('instrumentation', '')}
- Atmosphere: {concept.get('atmosphere', '')}
"""
        else:
            concept_block = f"채널 장르: {', '.join(channel_profile.get('genre', []))}"

        prompt = f"""아래 기존 곡을 참고해서, 비슷한 분위기이지만 다른 새 곡을 1개 설계해줘.
{concept_block}
기존 곡:
- 제목: {track.get('title', '')}
- 무드: {track.get('mood', '')}
- 기존 Suno 프롬프트:
{track.get('suno_prompt', '')}

가사 포함: {"있음" if has_lyrics else "없음 (Instrumental)"}

아래 형식의 JSON 객체 1개로 반환. suno_prompt는 반드시 아래 6줄 형식을 지켜:
{{
  "index": {track.get('index', 1)},
  "title": "새 곡 제목 (영어)",
  "title_ko": "새 곡 제목 (한국어)",
  "suno_prompt": "Genre: ...\\nMood: ...\\nTempo: ...\\nInstrumentation: ...\\nSound Effects/Atmosphere: ...\\nAdditional Descriptors: ...",
  "lyrics": "가사 (has_lyrics=true일 때만, 아니면 빈 문자열)",
  "mood": "새 곡 분위기 한줄 설명 (한국어)",
  "duration_hint": "3:30",
  "category": "{track.get('category', 'relax')}"
}}"""

        try:
            result = await gemini_client.generate_json(prompt)
            if isinstance(result, list):
                result = result[0] if result else {}
            logger.info(f"개별 곡 재생성 완료: index={track.get('index')}")
            return result
        except Exception as e:
            logger.error(f"개별 곡 재생성 실패: {e}")
            raise

    # ──────────────────────────── Step 1 ────────────────────────────

    async def _build_concept(
        self,
        channel_profile: dict,
        benchmark: dict | None,
        count: int,
    ) -> dict:
        """프로젝트 공통 컨셉 확정 (Gemini 1회 호출)."""
        genre    = ", ".join(channel_profile.get("genre", []))
        mood_kws = ", ".join(channel_profile.get("mood_keywords", []))
        base     = channel_profile.get("suno_base_prompt", "")
        bench    = self._build_benchmark_section(benchmark)

        prompt = f"""너는 경험 많은 음악 프로듀서야.
YouTube 플레이리스트 영상 1개 ({count}곡짜리)를 위한 공통 음악 컨셉을 확정해줘.
같은 영상 안의 곡들이므로 전체가 하나의 연속된 분위기여야 해.

채널 정보:
- 장르: {genre}
- 무드 키워드: {mood_kws}
- Suno 기본 프롬프트: {base}

{bench}

아래 JSON 1개로 반환. 모든 곡에 공통 적용될 값이므로 구체적으로:
{{
  "project_name": "프로젝트 이름 (영어, 분위기 표현)",
  "genre": "장르 (예: Ambient, Meditation, Sleep Music)",
  "core_mood": "전체 분위기 키워드 5~8개 (영어, 쉼표 구분)",
  "tempo": "템포 묘사 (예: Very slow, extremely relaxed, gentle)",
  "bpm_range": "BPM 범위 (예: 55-70)",
  "instrumentation": "핵심 악기 목록 (영어, 구체적. 예: Soft strings, gentle piano, warm pads, ethereal synths)",
  "atmosphere": "사운드 효과·분위기 (예: White noise, nature sounds, subtle wind)",
  "base_additional": "전체 공통 분위기 서술 (1~2문장 영어)"
}}"""

        try:
            result = await gemini_client.generate_json(prompt)
            if isinstance(result, list):
                result = result[0] if result else {}
            return result if isinstance(result, dict) else {}
        except Exception as e:
            logger.error(f"컨셉 생성 실패: {e}")
            # fallback: 빈 컨셉으로 진행
            return {
                "project_name": "Music Project",
                "genre": genre,
                "core_mood": mood_kws,
                "tempo": "Relaxed",
                "bpm_range": "60-80",
                "instrumentation": base,
                "atmosphere": "",
                "base_additional": "",
            }

    # ──────────────────────────── Step 2 ────────────────────────────

    async def _build_tracks(
        self,
        concept: dict,
        channel_profile: dict,
        count: int,
    ) -> list[dict]:
        """컨셉 고정 후 개별 곡 설계 (Gemini 1회 호출)."""
        has_lyrics = channel_profile.get("has_lyrics", False)

        prompt = f"""너는 음악 프로듀서야. 아래 프로젝트 컨셉을 기반으로 곡 {count}개를 설계해.

━━ 프로젝트 컨셉 (모든 곡에 고정 적용) ━━
Genre: {concept.get('genre', '')}
Core Mood: {concept.get('core_mood', '')}
Tempo: {concept.get('tempo', '')} ({concept.get('bpm_range', '')} BPM)
Instrumentation: {concept.get('instrumentation', '')}
Sound Effects/Atmosphere: {concept.get('atmosphere', '')}
Base Additional: {concept.get('base_additional', '')}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

설계 규칙:
1. Genre, Tempo, Instrumentation, BPM은 모든 곡이 동일하게 유지
2. Mood와 Additional Descriptors만 곡마다 살짝씩 달라짐 (전체 흐름: 부드럽게 시작 → 중반 약간 고조 → 마무리 잔잔)
3. suno_prompt는 반드시 아래 6줄 형식으로 작성:
   Genre: [고정값]
   Mood: [이 곡만의 무드 변형]
   Tempo: [고정값]
   Instrumentation: [고정값]
   Sound Effects/Atmosphere: [고정값 + 곡별 미세 변형 가능]
   Additional Descriptors: [이 곡만의 구체적 분위기 서술]
4. 가사 포함: {"있음 (영어 2~3절 분량)" if has_lyrics else "없음 — lyrics 필드는 빈 문자열"}

아래 JSON 배열 {count}개로 반환:
[
  {{
    "index": 1,
    "title": "곡 제목 (영어)",
    "title_ko": "곡 제목 (한국어)",
    "suno_prompt": "Genre: ...\\nMood: ...\\nTempo: ...\\nInstrumentation: ...\\nSound Effects/Atmosphere: ...\\nAdditional Descriptors: ...",
    "lyrics": "가사 또는 빈 문자열",
    "mood": "이 곡의 분위기 한줄 설명 (한국어)",
    "duration_hint": "3:30",
    "category": "sleep|focus|relax|morning|meditation|drive 중 하나"
  }}
]"""

        try:
            result = await gemini_client.generate_json(prompt)
            if isinstance(result, dict):
                result = result.get("tracks", result.get("songs", []))
            return result if isinstance(result, list) else []
        except Exception as e:
            logger.error(f"트랙 설계 실패: {e}")
            raise

    # ──────────────────────────── helpers ────────────────────────────

    @staticmethod
    def _build_benchmark_section(benchmark: dict | None) -> str:
        if not benchmark:
            return "벤치마크: 없음 (채널 기본 설정만 사용)"
        ai = benchmark.get("ai_analysis", {})
        lines = ["벤치마크 분석 (참고):"]
        if ai.get("music_style"):
            lines.append(f"- 스타일: {ai['music_style']}")
        if ai.get("mood"):
            lines.append(f"- 분위기: {', '.join(ai['mood'])}")
        if ai.get("estimated_track_count"):
            lines.append(f"- 참고 영상 곡 수: {ai['estimated_track_count']}")
        return "\n".join(lines)


# ──────────────────────────── 싱글톤 ────────────────────────────

track_designer = TrackDesigner()
