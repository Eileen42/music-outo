"""
트랙 가사 → CapCut 자막(SRT) 빌더.

# SRT 생성 지침 (가사 자막 규칙)

1. **타임스탬프 소스**: Whisper forced alignment의 **word-level** 타임스탬프.
   실제 노래의 발성 시작·종료 시점과 자막 전환이 동일해야 한다.
   (ASR recognizing은 오탈자 위험, align은 가사 원문을 기준으로 timing만 추정)

2. **한 줄 최대 20자** (`MAX_CHARS = 20`).
   길면 단어 경계에서 분할. 단, 최소 1단어는 반드시 포함.

3. **가사 간 간격(gap) > 1초**이면 강제로 끊는다 (`GAP_THRESHOLD_S = 1.0`).
   노래 중 긴 반주 구간에서는 자막도 사라지고, 다음 가사가 시작할 때 재등장.

4. **한 세그먼트 최대 6초** (`MAX_DURATION_S = 6.0`).
   gap이 없어도 너무 길면 분할 (시청자 읽기 부담 경감).

5. **빈 세그먼트·단일 공백 제거**. 특수 태그([Verse], (fading)) 는 `_clean_lyrics`에서 사전 제거.

6. **언어 힌트**: 가사에서 한글 비율 ≥10% → 'ko', 그 외 'en'. (forced alignment 품질 향상용)

7. **fallback**: forced alignment 실패 시 (음원-가사 불일치, STT 신뢰도 낮음 등)
   일반 Whisper ASR로 폴백. 이 경우 텍스트는 Whisper가 들은 대로.

# 트리거
- 트랙 업로드/가사 저장/Suno 세트 등록/순서 변경 → 백그라운드 재빌드
- CapCut 빌드 직전에도 subtitle_entries 비어 있으면 동기 실행(안전망)

# 출력
- `storage/projects/{pid}/subtitles/{track_id}.srt` — 트랙 단위
- `storage/projects/{pid}/subtitles/{track_id}.json` — 원본 정렬·번역 데이터
- `storage/projects/{pid}/subtitles/project.srt` — 프로젝트 통합 (트랙 순서대로 시간 오프셋 누적)
- `state.subtitle_entries` — CapCut 빌더가 읽는 최종 리스트
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Optional

from core.lyrics_sync import lyrics_sync

logger = logging.getLogger(__name__)

_CONCURRENCY = 3         # 동시 정렬 최대치 (CPU bound)
# NOTE: 한 줄 25자×최대 2줄 = 50자 상한. smart_split이 켜진 경우 레이아웃은 smart_split이 담당.
#       smart_split이 꺼진 경우에도 후행에서 _wrap_to_lines가 25×2로 맞추므로 50자 상한 유지.
MAX_CHARS = 50
GAP_THRESHOLD_S = 1.0    # 이보다 긴 단어 간 간격에서는 강제로 분할
MAX_DURATION_S = 6.0     # 한 세그먼트의 최대 지속 시간
MIN_DURATION_S = 0.3     # 이보다 짧은 세그먼트는 이전/다음과 병합


async def build_for_project(
    project_id: str,
    tracks: list[dict],
    project_dir: Path,
    display_mode: str = "source_only",
    channel_lang: Optional[str] = None,
    refine_sync_enabled: bool = True,
    smart_split_enabled: bool = True,
) -> dict:
    """
    전체 프로젝트의 자막을 생성·집계한다.

    Args:
        display_mode: "source_only" | "translation_only" | "source_and_translation"
        channel_lang: 채널 기준 언어 (보통 "ko"). 번역 대상.
        refine_sync_enabled: 개선1 — librosa onset/RMS로 싱크 보정 (기본 True)
        smart_split_enabled: 개선2 — 묵음 전환점+의미 단위 재분할 (기본 True)

    Returns:
        {"subtitle_entries": [...], "srt_path": str, "track_results": [{track_id, srt_path, source}]}
    """
    subtitle_dir = project_dir / "subtitles"
    subtitle_dir.mkdir(parents=True, exist_ok=True)

    sem = asyncio.Semaphore(_CONCURRENCY)

    async def _process(track: dict) -> Optional[dict]:
        async with sem:
            return await _align_single_track(
                track, subtitle_dir, display_mode, channel_lang or "ko",
                refine_sync_enabled=refine_sync_enabled,
                smart_split_enabled=smart_split_enabled,
            )

    aligned_results = await asyncio.gather(
        *[_process(t) for t in tracks if t.get("stored_path")],
        return_exceptions=True,
    )

    # 트랙 순서대로 오프셋 누적
    all_entries = []
    time_offset = 0.0
    track_summaries = []
    track_map = {t["id"]: t for t in tracks}

    for res in aligned_results:
        if isinstance(res, Exception):
            logger.error(f"트랙 정렬 실패: {res}")
            continue
        if not res:
            continue
        track = track_map.get(res["track_id"])
        if not track:
            continue

        for seg in res["segments"]:
            all_entries.append({
                "start": round(time_offset + seg["start"], 3),
                "end": round(time_offset + seg["end"], 3),
                "text": seg["text"],
            })

        time_offset += track.get("duration", 0) or 0
        track_summaries.append({
            "track_id": res["track_id"],
            "srt_path": res.get("srt_path"),
            "source": res.get("source"),
            "segments_count": len(res["segments"]),
        })

    # 프로젝트 통합 SRT 저장
    srt_path = subtitle_dir / "project.srt"
    srt_path.write_text(_to_srt(all_entries), encoding="utf-8")

    logger.info(
        f"자막 빌드 완료: {len(track_summaries)} 트랙, {len(all_entries)} 엔트리, "
        f"mode={display_mode}, 총 {time_offset:.0f}s"
    )

    return {
        "subtitle_entries": all_entries,
        "srt_path": str(srt_path),
        "track_results": track_summaries,
    }


async def _align_single_track(
    track: dict,
    subtitle_dir: Path,
    display_mode: str,
    target_lang: str,
    refine_sync_enabled: bool = True,
    smart_split_enabled: bool = True,
) -> Optional[dict]:
    """단일 트랙 정렬 + 번역(필요 시) + SRT 저장."""
    track_id = track["id"]
    audio_path = Path(track.get("stored_path", ""))
    lyrics_text = track.get("lyrics") or ""

    if not audio_path.exists():
        logger.warning(f"트랙 {track_id}: 오디오 파일 없음 — 건너뜀")
        return None

    # 1. 정렬 (가사 있으면 forced alignment, 없으면 ASR)
    if lyrics_text.strip():
        lang_hint = _detect_language(lyrics_text)
        try:
            result = await lyrics_sync.align_with_lyrics(audio_path, lyrics_text, language=lang_hint)
        except ValueError:
            return None
    else:
        result = await lyrics_sync.transcribe(audio_path)
        result["source"] = "asr"

    # 2. 재세그먼트: word-level 데이터가 있으면 규칙 기반으로 재묶음.
    #    없으면(ASR 폴백 등) 원본 세그먼트 사용.
    raw_segments = result.get("segments", [])
    words = result.get("words") or [
        w for s in raw_segments for w in (s.get("words") or [])
    ]
    if words:
        segments = _resegment_words(words)
    else:
        segments = [{"start": s["start"], "end": s["end"], "text": s["text"]} for s in raw_segments]

    # 3. 후처리: 싱크 보정 + 스마트 분할 (플래그로 on/off)
    from core.subtitle_refiner import refine_sync, smart_split, wrap_all_to_lines
    if refine_sync_enabled and segments:
        try:
            segments = await asyncio.to_thread(refine_sync, segments, audio_path)
        except Exception as e:
            logger.warning(f"refine_sync 실패 — 원본 유지: {e}")
    if smart_split_enabled and segments:
        try:
            segments = await asyncio.to_thread(smart_split, segments, audio_path)
        except Exception as e:
            logger.warning(f"smart_split 실패 — 원본 유지: {e}")
    else:
        # smart_split 미사용 시에도 한 줄 25자×최대 2줄 레이아웃만 적용 (시간 분할은 하지 않음)
        segments = wrap_all_to_lines(segments)

    detected_lang = result.get("language", "unknown")

    # 2. 번역 필요한지 결정
    needs_translation = (
        display_mode in ("translation_only", "source_and_translation")
        and detected_lang != target_lang
        and bool(segments)
    )

    translations: list[str] = []
    if needs_translation:
        try:
            translations = await _translate_segments(
                [s["text"] for s in segments],
                source_lang=detected_lang,
                target_lang=target_lang,
            )
        except Exception as e:
            logger.warning(f"트랙 {track_id} 번역 실패: {e} — 원문만 사용")
            translations = []

    # 3. 세그먼트 텍스트를 display_mode에 맞춰 포맷
    formatted_segments = []
    for i, seg in enumerate(segments):
        src = seg["text"]
        tr = translations[i] if i < len(translations) else ""
        if display_mode == "translation_only" and tr:
            text = tr
        elif display_mode == "source_and_translation" and tr:
            text = f"{src}\n{tr}"
        else:
            text = src
        formatted_segments.append({"start": seg["start"], "end": seg["end"], "text": text})

    # 4. 트랙 단위 SRT 저장
    srt_path = subtitle_dir / f"{track_id}.srt"
    srt_path.write_text(_to_srt(formatted_segments), encoding="utf-8")

    # 5. 원본 정렬 결과 JSON 저장 (디버깅·재사용)
    json_path = subtitle_dir / f"{track_id}.json"
    json_path.write_text(
        json.dumps({
            "track_id": track_id,
            "source": result.get("source"),
            "language": detected_lang,
            "display_mode": display_mode,
            "segments": formatted_segments,
            "raw_segments": segments,
            "translations": translations,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return {
        "track_id": track_id,
        "segments": formatted_segments,
        "srt_path": str(srt_path),
        "json_path": str(json_path),
        "source": result.get("source"),
        "language": detected_lang,
    }


async def _translate_segments(
    lines: list[str],
    source_lang: str,
    target_lang: str,
) -> list[str]:
    """가사 라인 배치 번역 (Gemini)."""
    from core.gemini_client import gemini_client

    numbered = "\n".join(f"{i+1}. {line}" for i, line in enumerate(lines))
    prompt = (
        f"다음은 '{source_lang}' 가사의 각 줄이다. 각 줄을 '{target_lang}'로 자연스럽게 번역하라. "
        f"직역보다는 노래 가사로서 자연스러움을 우선한다. "
        f"원문 줄 번호를 유지하여 동일 개수로 응답한다.\n\n"
        f"{numbered}\n\n"
        f"응답은 JSON 배열만. 각 원소는 번역된 한 줄 문자열. 설명·마크다운 금지. "
        f"예: [\"번역1\", \"번역2\"]"
    )

    result = await gemini_client.generate_json(prompt)
    if not isinstance(result, list):
        raise ValueError("번역 응답이 배열이 아님")
    # 길이가 안 맞으면 원문 개수만큼 패딩
    if len(result) < len(lines):
        result = list(result) + [""] * (len(lines) - len(result))
    return [str(x).strip() for x in result[: len(lines)]]


def _resegment_words(
    words: list[dict],
    max_chars: int = MAX_CHARS,
    gap_threshold: float = GAP_THRESHOLD_S,
    max_duration: float = MAX_DURATION_S,
) -> list[dict]:
    """
    word-level 타임스탬프 리스트를 자막 세그먼트로 재묶음한다.

    분할 규칙 (우선순위 순):
    1. 현재 단어와 이전 단어 사이 gap > gap_threshold  → 강제 분할
    2. 현재 세그먼트에 단어를 추가했을 때 길이 > max_chars → 분할
    3. 현재 세그먼트 지속시간이 max_duration 초과 예정 → 분할
    (단, 세그먼트에 단어가 하나도 없으면 단일 단어라도 추가)

    Args:
        words: [{"start": float, "end": float, "text": str}, ...]
    Returns:
        [{"start", "end", "text"}, ...]
    """
    if not words:
        return []

    segments: list[dict] = []
    cur: list[dict] = []
    cur_text_len = 0

    def close():
        if not cur:
            return
        text = " ".join(w["text"] for w in cur).strip()
        # 연속 공백·공백만 있는 경우 제거
        text = " ".join(text.split())
        if text:
            segments.append({
                "start": round(cur[0]["start"], 3),
                "end": round(cur[-1]["end"], 3),
                "text": text,
                "words": list(cur),  # 후처리(refine_sync/smart_split)에서 활용
            })

    prev_end = None
    for w in words:
        gap = (w["start"] - prev_end) if prev_end is not None else 0.0
        wt = w["text"]
        next_len = cur_text_len + (1 if cur else 0) + len(wt)  # +1 for space

        need_split = False
        if cur and gap > gap_threshold:
            need_split = True
        elif cur and next_len > max_chars:
            need_split = True
        elif cur and (w["end"] - cur[0]["start"]) > max_duration:
            need_split = True

        if need_split:
            close()
            cur = []
            cur_text_len = 0

        cur.append(w)
        cur_text_len = cur_text_len + (1 if cur_text_len else 0) + len(wt)
        prev_end = w["end"]

    close()

    # 최소 지속시간 미달 세그먼트 병합 (이전과)
    merged: list[dict] = []
    for s in segments:
        if merged and (s["end"] - s["start"]) < MIN_DURATION_S:
            # 다음 세그먼트와 gap이 짧으면 병합
            last = merged[-1]
            if s["start"] - last["end"] <= GAP_THRESHOLD_S and len(last["text"]) + 1 + len(s["text"]) <= max_chars + 4:
                last["end"] = s["end"]
                last["text"] = (last["text"] + " " + s["text"]).strip()
                continue
        merged.append(s)
    return merged


def _detect_language(text: str) -> str:
    """가사 텍스트에서 한글이 10% 이상이면 'ko', 아니면 'en'."""
    if not text:
        return "ko"
    kor = sum(1 for c in text if "\uac00" <= c <= "\ud7a3")
    alpha = sum(1 for c in text if c.isalpha())
    if alpha == 0:
        return "ko"
    return "ko" if kor / alpha >= 0.1 else "en"


def _to_srt(entries: list[dict]) -> str:
    """[{start, end, text}] → SRT 문자열."""
    def fmt(s: float) -> str:
        h = int(s // 3600)
        m = int((s % 3600) // 60)
        sec = s % 60
        ms = int((sec % 1) * 1000)
        return f"{h:02d}:{m:02d}:{int(sec):02d},{ms:03d}"

    out = []
    for i, e in enumerate(entries, 1):
        out.append(f"{i}\n{fmt(e['start'])} --> {fmt(e['end'])}\n{e['text']}\n")
    return "\n".join(out)
