"""
SRT 자막 후처리: 싱크 보정 + 스마트 캡션 분할.

기존 forced-alignment 결과를 받아 librosa 기반 오디오 분석으로
1) 시작·종료 타임스탬프를 실제 보컬 onset/decay에 맞춰 보정하고,
2) 음악적 전환점(긴 묵음)과 의미 단위로 캡션을 재분할한다.

파이프라인:
    음원 + 가사 → forced alignment → _resegment_words
                → refine_sync()      ← 이 모듈 (onset snap + RMS end)
                → smart_split()      ← 이 모듈 (silence split + semantic)
                → SRT

# 설계 노트
- 보컬 분리(demucs) 없이 원본 믹스를 분석한다. 대부분의 노래에서 보컬이 에너지·onset의 주요 기여자이므로
  경험적으로 허용 가능한 결과를 얻지만, 악기 음량이 큰 구간에서는 오탐 가능.
- 보컬 전용 오디오가 이미 있는 경우(`vocal_audio_path` 인자) 그것을 사용한다.
- 싱크 스냅 허용 오차 `ONSET_SNAP_TOLERANCE_S = 0.3` — 규칙상 이 범위를 벗어나면 원본 유지.
- 모든 파라미터는 기본값 제공, 전체 기능 on/off 플래그로 제어 가능.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ───── 싱크 보정 파라미터 ──────────────────────────────────────────
ONSET_SNAP_TOLERANCE_S = 0.3     # 이 차이 이내일 때만 onset에 스냅
RMS_SILENCE_THRESHOLD_DB = -40   # 보컬 종료 판단 기준 (dB)
RMS_END_SEARCH_WINDOW_S = 0.8    # 세그먼트 끝부터 앞뒤로 검사할 범위

# ───── 스마트 분할 파라미터 ────────────────────────────────────────
SILENCE_SPLIT_THRESHOLD_S = 0.8  # 이보다 긴 묵음에서 반드시 분할
INTERLUDE_THRESHOLD_S = 3.0      # 이보다 긴 묵음 = 간주, 자막 넣지 않음
MAX_CHARS_PER_LINE = 25          # 한 줄 최대
MAX_LINES = 2                    # 최대 2줄
MIN_CAPTION_DURATION_S = 1.0     # 너무 짧은 캡션은 병합
MAX_CAPTION_DURATION_S = 6.0     # 너무 긴 캡션은 분할

# 문장 끝 판정용 구두점
_SENTENCE_ENDS = (".", "?", "!", "。", "?", "!", "…")
_CLAUSE_BREAKS = (",", ";", ":", "、", ",", "—", "–")


# ══════════════════════════════════════════════════════════════════
# 개선 1: 싱크 보정 (onset snap + RMS end)
# ══════════════════════════════════════════════════════════════════

def refine_sync(
    segments: list[dict],
    audio_path: Path,
    *,
    snap_tolerance: float = ONSET_SNAP_TOLERANCE_S,
    rms_threshold_db: float = RMS_SILENCE_THRESHOLD_DB,
) -> list[dict]:
    """
    각 세그먼트의 start/end를 실제 보컬 타이밍에 맞춰 보정.

    - start: 가장 가까운 onset 지점으로 스냅 (tolerance 이내일 때만)
    - end:   보컬 에너지(RMS)가 threshold 이하로 떨어지는 지점으로 조정
    """
    if not segments:
        return segments
    try:
        import librosa
        import numpy as np
    except ImportError as e:
        logger.warning(f"librosa import 실패 — 싱크 보정 생략: {e}")
        return segments

    try:
        y, sr = librosa.load(str(audio_path), sr=None, mono=True)
    except Exception as e:
        logger.warning(f"오디오 로드 실패 — 싱크 보정 생략: {e}")
        return segments

    # Onset detection
    try:
        onset_frames = librosa.onset.onset_detect(y=y, sr=sr, units="frames", backtrack=True)
        onsets = librosa.frames_to_time(onset_frames, sr=sr)
    except Exception as e:
        logger.warning(f"onset 추출 실패: {e}")
        onsets = np.array([])

    # RMS (에너지) 계산
    hop_length = 512
    rms = librosa.feature.rms(y=y, hop_length=hop_length)[0]
    rms_db = librosa.amplitude_to_db(rms, ref=np.max)
    rms_times = librosa.frames_to_time(np.arange(len(rms)), sr=sr, hop_length=hop_length)

    refined: list[dict] = []
    snapped_count = 0
    end_adjusted = 0

    for seg in segments:
        new_start = seg["start"]
        new_end = seg["end"]

        # 1) 시작: 가장 가까운 onset 찾기
        if len(onsets) > 0:
            idx = int(np.argmin(np.abs(onsets - seg["start"])))
            nearest = float(onsets[idx])
            diff = abs(nearest - seg["start"])
            if diff <= snap_tolerance:
                new_start = round(nearest, 3)
                if new_start != seg["start"]:
                    snapped_count += 1

        # 2) 종료: RMS가 threshold 아래로 떨어지는 지점 탐색
        #    (원래 end 근처 ±RMS_END_SEARCH_WINDOW_S 내에서)
        search_start = max(seg["start"] + 0.1, seg["end"] - RMS_END_SEARCH_WINDOW_S)
        search_end = min(seg["end"] + RMS_END_SEARCH_WINDOW_S, rms_times[-1] if len(rms_times) else seg["end"])
        mask = (rms_times >= search_start) & (rms_times <= search_end)
        if mask.any():
            window_db = rms_db[mask]
            window_t = rms_times[mask]
            # threshold 이하 첫 지점 찾기 (원래 end 이후 우선)
            below = np.where(window_db < rms_threshold_db)[0]
            if len(below) > 0:
                candidate = float(window_t[below[0]])
                # 최소 길이 보장: start보다 커야 하고, 너무 앞당기지 않음
                if candidate > new_start + 0.2 and abs(candidate - seg["end"]) <= RMS_END_SEARCH_WINDOW_S:
                    new_end = round(candidate, 3)
                    if new_end != seg["end"]:
                        end_adjusted += 1

        # start >= end 방지
        if new_end <= new_start:
            new_end = seg["end"]

        refined.append({**seg, "start": new_start, "end": new_end})

    # 인접 세그먼트 간 시간 역전·중첩 방지 (refine이 독립적으로 start/end를 옮기면서 발생 가능)
    for i in range(len(refined) - 1):
        if refined[i]["end"] > refined[i + 1]["start"]:
            refined[i]["end"] = refined[i + 1]["start"]
        # 최소 지속시간 0.1초 보장
        if refined[i]["end"] <= refined[i]["start"] + 0.1:
            refined[i]["end"] = refined[i]["start"] + 0.1

    logger.info(
        f"refine_sync: {len(segments)} 세그먼트 — "
        f"start 스냅 {snapped_count}개, end 조정 {end_adjusted}개"
    )
    return refined


# ══════════════════════════════════════════════════════════════════
# 개선 2: 스마트 캡션 분할 (묵음 전환점 + 의미 단위)
# ══════════════════════════════════════════════════════════════════

def detect_silences(
    audio_path: Path,
    *,
    min_silence_s: float = SILENCE_SPLIT_THRESHOLD_S,
    top_db: int = 30,
) -> list[tuple[float, float]]:
    """
    오디오에서 묵음 구간 [(start, end), ...] 반환 (초 단위).
    `min_silence_s` 이상 지속되는 구간만.
    """
    try:
        import librosa
    except ImportError:
        return []
    try:
        y, sr = librosa.load(str(audio_path), sr=None, mono=True)
    except Exception as e:
        logger.warning(f"묵음 감지용 오디오 로드 실패: {e}")
        return []

    # split은 비묵음(소리 있는) 구간 반환. 묵음은 그 사이.
    intervals = librosa.effects.split(y, top_db=top_db)
    silences: list[tuple[float, float]] = []
    sr_f = float(sr)
    audio_len = len(y) / sr_f

    # 첫 번째 비묵음 이전 묵음
    if len(intervals) > 0:
        first_nonsilence_start = intervals[0][0] / sr_f
        if first_nonsilence_start >= min_silence_s:
            silences.append((0.0, first_nonsilence_start))

    # 중간 묵음
    for i in range(len(intervals) - 1):
        gap_start = intervals[i][1] / sr_f
        gap_end = intervals[i + 1][0] / sr_f
        if gap_end - gap_start >= min_silence_s:
            silences.append((gap_start, gap_end))

    # 마지막 묵음
    if len(intervals) > 0:
        last_end = intervals[-1][1] / sr_f
        if audio_len - last_end >= min_silence_s:
            silences.append((last_end, audio_len))

    return silences


def smart_split(
    segments: list[dict],
    audio_path: Path,
    *,
    max_chars_per_line: int = MAX_CHARS_PER_LINE,
    max_lines: int = MAX_LINES,
    min_duration: float = MIN_CAPTION_DURATION_S,
    max_duration: float = MAX_CAPTION_DURATION_S,
    words_by_seg: Optional[list[list[dict]]] = None,
) -> list[dict]:
    """
    세그먼트를 재분할·병합한다.

    분할 우선순위:
      1) 보컬 묵음 전환점 (>= 0.8초, 간주 3초 이상은 자막 제외)
      2) 원문 줄바꿈 (\\n)
      3) 문장 끝 (. ? !)
      4) 쉼표·절 경계

    길이 제한: 최대 2줄, 한 줄 25자 (한국어 기준).
    지속시간: 1.0s ~ 6.0s 유지.

    Args:
        segments: 기존 세그먼트 [{start, end, text, words?}]
        words_by_seg: 세그먼트별 word-level 타임스탬프 (병행 제공 시 더 정확한 분할)
    """
    if not segments:
        return segments

    silences = detect_silences(audio_path)
    interlude_zones = [(s, e) for s, e in silences if (e - s) >= INTERLUDE_THRESHOLD_S]
    split_points = [s + (e - s) * 0.5 for s, e in silences if (e - s) < INTERLUDE_THRESHOLD_S]
    # 주의: split_points는 "이 시각 이후 새 캡션 시작" 기준으로 쓴다.

    # 1단계: 간주 구간을 피하도록 세그먼트 경계 조정
    adjusted: list[dict] = []
    for seg in segments:
        s, e = seg["start"], seg["end"]
        # 간주 구간과 겹치면 경계를 밀어냄
        for iz_start, iz_end in interlude_zones:
            if s < iz_end and e > iz_start:  # 겹침
                if s < iz_start and e <= iz_end:
                    e = iz_start  # 간주 시작 전까지만
                elif s >= iz_start and e > iz_end:
                    s = iz_end  # 간주 끝난 뒤부터
                # 세그먼트가 간주에 완전히 포함되는 건 거의 없지만 방어
        if e > s + 0.1:
            adjusted.append({**seg, "start": s, "end": e})

    # 2단계: silence split_points 기준으로 세그먼트를 더 나눈다
    further_split: list[dict] = []
    for seg in adjusted:
        s, e = seg["start"], seg["end"]
        # 이 세그먼트 내부에 있는 split_point 수집
        internal_points = sorted([p for p in split_points if s < p < e])
        if not internal_points:
            further_split.append(seg)
            continue

        # word-level 데이터가 있으면 split_point에 가장 가까운 word 경계로 분할
        words = seg.get("words") or []
        if words:
            parts = _split_segment_at_points_by_words(seg, internal_points)
            further_split.extend(parts)
        else:
            # 단어 정보가 없으면 텍스트를 시간 비율대로 기계적 분할
            further_split.extend(_split_segment_at_points_by_ratio(seg, internal_points))

    # 3단계: 길이 제한 적용 (한 줄 max_chars, 최대 max_lines)
    length_limited: list[dict] = []
    for seg in further_split:
        if _fits_length(seg["text"], max_chars_per_line, max_lines):
            length_limited.append(seg)
        else:
            length_limited.extend(_split_by_semantics(seg, max_chars_per_line, max_lines))

    # 4단계: 지속시간 보정 (짧으면 병합, 길면 분할)
    duration_normalized = _normalize_durations(length_limited, min_duration, max_duration)

    # 5단계: 두 줄로 레이아웃 (한 줄 초과 시 \n 삽입)
    final: list[dict] = []
    for seg in duration_normalized:
        final.append({**seg, "text": _wrap_to_lines(seg["text"], max_chars_per_line, max_lines)})

    logger.info(
        f"smart_split: 입력 {len(segments)} → 출력 {len(final)} "
        f"(silence 분할점 {len(split_points)}개, 간주 {len(interlude_zones)}개)"
    )
    return final


# ────────────────────────── 내부 헬퍼 ─────────────────────────────

def _split_segment_at_points_by_words(seg: dict, points: list[float]) -> list[dict]:
    """word 타임스탬프를 기준으로 split_point에 가까운 word 경계에서 분할."""
    words = seg["words"]
    parts: list[dict] = []
    current: list[dict] = []
    pi = 0
    for w in words:
        if pi < len(points) and w["start"] >= points[pi]:
            # 현재 누적을 마감하고 새 세그먼트 시작
            if current:
                parts.append(_words_to_seg(current))
                current = []
            pi += 1
        current.append(w)
    if current:
        parts.append(_words_to_seg(current))
    return parts if parts else [seg]


def _split_segment_at_points_by_ratio(seg: dict, points: list[float]) -> list[dict]:
    """단어 정보 없을 때: 텍스트 글자 수 비율로 분할."""
    s, e = seg["start"], seg["end"]
    text = seg["text"]
    duration = e - s
    if duration <= 0 or not text:
        return [seg]
    parts: list[dict] = []
    cursor_time = s
    cursor_char = 0
    for p in points:
        frac = (p - s) / duration
        target_char = int(len(text) * frac)
        # 단어 경계로 스냅
        while target_char < len(text) and text[target_char] not in (" ", "\n"):
            target_char += 1
        chunk = text[cursor_char:target_char].strip()
        if chunk:
            parts.append({"start": round(cursor_time, 3), "end": round(p, 3), "text": chunk})
        cursor_time = p
        cursor_char = target_char
    tail = text[cursor_char:].strip()
    if tail:
        parts.append({"start": round(cursor_time, 3), "end": round(e, 3), "text": tail})
    return parts if parts else [seg]


def _words_to_seg(words: list[dict]) -> dict:
    text = " ".join(w["text"] for w in words).strip()
    return {
        "start": round(words[0]["start"], 3),
        "end": round(words[-1]["end"], 3),
        "text": " ".join(text.split()),
        "words": words,
    }


def _fits_length(text: str, max_chars: int, max_lines: int) -> bool:
    return len(text) <= max_chars * max_lines and text.count("\n") + 1 <= max_lines


def _split_by_semantics(seg: dict, max_chars: int, max_lines: int) -> list[dict]:
    """
    긴 세그먼트를 의미 단위로 분할한다.
    우선순위: \\n → 문장끝 → 쉼표·접속사 → 공백.
    word-level 타임스탬프가 있으면 각 조각에 시간을 정확히 할당, 없으면 비율 분배.
    """
    text = seg["text"]
    words = seg.get("words") or []
    limit = max_chars * max_lines

    chunks = _semantic_chunks(text, limit)
    if len(chunks) == 1:
        return [seg]

    # 단어 타임스탬프가 있으면 그 기준으로 매핑
    if words:
        return _assign_times_by_words(chunks, words)
    else:
        return _assign_times_by_ratio(chunks, seg["start"], seg["end"])


def _semantic_chunks(text: str, limit: int) -> list[str]:
    """우선순위대로 분할을 시도해 각 조각이 limit 이내가 되도록."""
    # 1) \n 기준
    pieces = [p.strip() for p in text.split("\n") if p.strip()]
    # 2) 각 조각이 여전히 길면 문장 끝·쉼표로 추가 분할
    out: list[str] = []
    for p in pieces:
        out.extend(_chunk_by_punctuation(p, limit))
    return out


def _chunk_by_punctuation(text: str, limit: int) -> list[str]:
    if len(text) <= limit:
        return [text]
    # 우선 문장끝에서 끊기 시도
    chunks: list[str] = []
    current = ""
    i = 0
    while i < len(text):
        c = text[i]
        current += c
        if c in _SENTENCE_ENDS and len(current) >= limit // 2:
            chunks.append(current.strip())
            current = ""
        i += 1
    if current.strip():
        chunks.append(current.strip())

    # 그래도 limit 초과하는 조각은 쉼표로
    refined: list[str] = []
    for ch in chunks:
        if len(ch) <= limit:
            refined.append(ch)
            continue
        refined.extend(_chunk_at_clauses(ch, limit))
    return refined


def _chunk_at_clauses(text: str, limit: int) -> list[str]:
    # 쉼표·세미콜론 기준 greedy
    parts: list[str] = []
    current = ""
    tokens = _tokenize_by_clauses(text)
    for tok in tokens:
        if current and len(current) + len(tok) > limit:
            parts.append(current.strip())
            current = tok
        else:
            current = (current + tok) if current else tok
    if current.strip():
        parts.append(current.strip())
    # 여전히 limit 초과하는 부분은 공백 기준으로 마지막 분할
    final: list[str] = []
    for p in parts:
        if len(p) <= limit:
            final.append(p)
        else:
            final.extend(_chunk_at_spaces(p, limit))
    return final


def _tokenize_by_clauses(text: str) -> list[str]:
    """쉼표·접속사 기준 토큰화 (구분자 유지)."""
    tokens: list[str] = []
    current = ""
    for c in text:
        current += c
        if c in _CLAUSE_BREAKS:
            tokens.append(current)
            current = ""
    if current:
        tokens.append(current)
    return tokens


def _chunk_at_spaces(text: str, limit: int) -> list[str]:
    words = text.split()
    parts: list[str] = []
    current = ""
    for w in words:
        cand = (current + " " + w).strip() if current else w
        if len(cand) > limit and current:
            parts.append(current)
            current = w
        else:
            current = cand
    if current:
        parts.append(current)
    return parts


def _assign_times_by_words(chunks: list[str], words: list[dict]) -> list[dict]:
    """chunks의 각 조각에 해당하는 word 범위를 greedy로 할당."""
    out: list[dict] = []
    wi = 0
    for chunk in chunks:
        # chunk 길이만큼 words를 소비 (문자 기반)
        target_len = len(chunk)
        acc_text = ""
        used: list[dict] = []
        while wi < len(words) and len(acc_text.replace(" ", "")) < len(chunk.replace(" ", "")):
            w = words[wi]
            used.append(w)
            acc_text = (acc_text + " " + w["text"]).strip()
            wi += 1
        if used:
            out.append({
                "start": round(used[0]["start"], 3),
                "end": round(used[-1]["end"], 3),
                "text": chunk,
                "words": used,
            })
    return out or [{"start": words[0]["start"], "end": words[-1]["end"], "text": " ".join(chunks), "words": words}]


def _assign_times_by_ratio(chunks: list[str], start: float, end: float) -> list[dict]:
    total = sum(len(c) for c in chunks) or 1
    duration = end - start
    cursor = start
    out: list[dict] = []
    for c in chunks:
        share = duration * (len(c) / total)
        out.append({"start": round(cursor, 3), "end": round(cursor + share, 3), "text": c})
        cursor += share
    return out


def _normalize_durations(segments: list[dict], min_dur: float, max_dur: float) -> list[dict]:
    """너무 짧은 세그먼트는 다음과 병합, 너무 긴 세그먼트는 분할."""
    if not segments:
        return segments
    # 병합
    merged: list[dict] = []
    for seg in segments:
        dur = seg["end"] - seg["start"]
        if merged and dur < min_dur:
            prev = merged[-1]
            prev_dur = prev["end"] - prev["start"]
            # 병합 후도 max_dur 이내여야 함
            if prev_dur + dur <= max_dur and (seg["start"] - prev["end"]) <= 0.5:
                prev["end"] = seg["end"]
                prev["text"] = (prev["text"] + " " + seg["text"]).strip()
                if "words" in prev and "words" in seg:
                    prev["words"] = prev["words"] + seg["words"]
                continue
        merged.append(dict(seg))

    # 분할
    result: list[dict] = []
    for seg in merged:
        dur = seg["end"] - seg["start"]
        if dur <= max_dur:
            result.append(seg)
            continue
        # words 기반으로 균등 분할
        words = seg.get("words") or []
        if words:
            n = max(2, int(dur / max_dur) + 1)
            chunk_size = max(1, len(words) // n)
            parts: list[list[dict]] = []
            for i in range(0, len(words), chunk_size):
                parts.append(words[i:i + chunk_size])
            for p in parts:
                if p:
                    result.append(_words_to_seg(p))
        else:
            # 단순 시간 분할
            n = int(dur / max_dur) + 1
            step = dur / n
            chars = seg["text"]
            per = max(1, len(chars) // n)
            for i in range(n):
                s = seg["start"] + i * step
                e = seg["start"] + (i + 1) * step if i < n - 1 else seg["end"]
                start_c = i * per
                end_c = (i + 1) * per if i < n - 1 else len(chars)
                result.append({"start": round(s, 3), "end": round(e, 3), "text": chars[start_c:end_c].strip()})
    return result


def wrap_all_to_lines(
    segments: list[dict],
    max_chars: int = MAX_CHARS_PER_LINE,
    max_lines: int = MAX_LINES,
) -> list[dict]:
    """smart_split 비활성 시에도 최소한 줄바꿈 레이아웃(25자×2줄)은 적용."""
    return [{**s, "text": _wrap_to_lines(s["text"], max_chars, max_lines)} for s in segments]


def _wrap_to_lines(text: str, max_chars: int, max_lines: int) -> str:
    """단일 라인 텍스트를 필요시 max_lines 줄로 줄바꿈."""
    text = text.replace("\n", " ").strip()
    text = " ".join(text.split())
    if len(text) <= max_chars:
        return text
    # greedy 단어 단위로 줄바꿈
    words = text.split(" ")
    lines: list[str] = []
    current = ""
    for w in words:
        cand = (current + " " + w).strip() if current else w
        if len(cand) > max_chars and current:
            lines.append(current)
            current = w
        else:
            current = cand
        if len(lines) >= max_lines - 1 and len(current) > max_chars:
            # 마지막 줄에 나머지 전부 밀어넣되, max_chars 초과해도 둔다
            remaining = " ".join(words[words.index(w) + 1:]) if w in words else ""
            if remaining:
                current = (current + " " + remaining).strip()
            break
    if current:
        lines.append(current)
    return "\n".join(lines[:max_lines])
