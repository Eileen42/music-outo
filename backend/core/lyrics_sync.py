"""
faster-whisper + stable-ts 를 사용한 가사 추출 및 타임스탬프 동기화.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Optional


class LyricsSyncEngine:
    def __init__(self, model_size: str = "base", device: str = "cpu"):
        self.model_size = model_size
        self.device = device
        self._model = None
        self._stable_model = None

    def _load_model(self):
        """모델 지연 로딩 (첫 사용 시)."""
        if self._model is None:
            from faster_whisper import WhisperModel
            self._model = WhisperModel(self.model_size, device=self.device)

    def _load_stable_model(self):
        if self._stable_model is None:
            import stable_whisper
            self._stable_model = stable_whisper.load_faster_whisper(
                self.model_size, device=self.device
            )

    async def align_with_lyrics(
        self,
        audio_path: Path,
        lyrics: str,
        language: Optional[str] = None,
    ) -> dict:
        """
        가사 텍스트를 오디오에 forced alignment.
        Whisper ASR과 달리 가사 원문이 그대로 유지되고 타임스탬프만 맞춰짐.
        실패 시(음원과 가사 불일치 등) ASR 폴백.

        Returns: {"text", "segments": [{start, end, text}], "language", "source": "align"|"asr"}
        """
        cleaned = _clean_lyrics(lyrics)
        if not cleaned.strip():
            raise ValueError("정렬할 가사 텍스트가 비어있습니다")

        try:
            result = await asyncio.to_thread(self._align, audio_path, cleaned, language)
            if result:
                result["source"] = "align"
                return result
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(
                f"forced alignment 실패 → ASR 폴백: {type(e).__name__}: {e}"
            )

        # 폴백: ASR
        result = await self.transcribe(audio_path, language=language)
        result["source"] = "asr"
        return result

    def _align(self, audio_path: Path, text: str, language: Optional[str]) -> Optional[dict]:
        """
        Forced alignment. 세그먼트 분할은 호출자(subtitle_builder._resegment)에 위임.
        여기서는 word-level 타임스탬프가 포함된 raw segments만 반환한다.
        """
        self._load_stable_model()
        lang = language or "ko"  # stable_whisper.align은 language=None 불가
        result = self._stable_model.align(str(audio_path), text, language=lang)
        if result is None:
            return None

        seg_list = []
        words = []
        for seg in result.segments:
            seg_words = []
            for w in (seg.words or []):
                wd = {
                    "start": round(w.start, 3),
                    "end": round(w.end, 3),
                    "text": (w.word or "").strip(),
                }
                if wd["text"] and wd["end"] > wd["start"]:
                    seg_words.append(wd)
                    words.append(wd)
            t = seg.text.strip()
            if not t:
                continue
            seg_list.append({
                "start": round(seg.start, 3),
                "end": round(seg.end, 3),
                "text": t,
                "words": seg_words,
            })

        return {
            "text": "\n".join(s["text"] for s in seg_list),
            "segments": seg_list,
            "words": words,
            "language": getattr(result, "language", language) or "unknown",
        }

    async def transcribe(
        self,
        audio_path: Path,
        language: Optional[str] = None,
        use_stable: bool = True,
    ) -> dict:
        """
        오디오에서 가사를 추출하고 타임스탬프와 함께 반환.

        Returns:
            {
                "text": "전체 가사",
                "segments": [{"start": 0.0, "end": 1.5, "text": "..."}],
                "language": "ko"
            }
        """
        if use_stable:
            return await asyncio.to_thread(self._transcribe_stable, audio_path, language)
        return await asyncio.to_thread(self._transcribe_whisper, audio_path, language)

    def _transcribe_whisper(self, audio_path: Path, language: Optional[str]) -> dict:
        self._load_model()
        segments, info = self._model.transcribe(
            str(audio_path),
            language=language,
            word_timestamps=True,
        )
        seg_list = []
        full_text = []
        for seg in segments:
            seg_list.append({
                "start": round(seg.start, 3),
                "end": round(seg.end, 3),
                "text": seg.text.strip(),
            })
            full_text.append(seg.text.strip())

        return {
            "text": " ".join(full_text),
            "segments": seg_list,
            "language": info.language,
        }

    def _transcribe_stable(self, audio_path: Path, language: Optional[str]) -> dict:
        self._load_stable_model()
        kwargs = {"word_timestamps": True}
        if language:
            kwargs["language"] = language
        result = self._stable_model.transcribe(str(audio_path), **kwargs)
        seg_list = []
        full_text = []
        for seg in result.segments:
            seg_list.append({
                "start": round(seg.start, 3),
                "end": round(seg.end, 3),
                "text": seg.text.strip(),
            })
            full_text.append(seg.text.strip())

        return {
            "text": " ".join(full_text),
            "segments": seg_list,
            "language": result.language or "unknown",
        }

    async def save_sync_file(
        self,
        transcription: dict,
        output_path: Path,
        format: str = "json",  # json | srt | lrc
    ) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)

        if format == "json":
            content = json.dumps(transcription, ensure_ascii=False, indent=2)
            output_path = output_path.with_suffix(".json")
        elif format == "srt":
            content = self._to_srt(transcription["segments"])
            output_path = output_path.with_suffix(".srt")
        elif format == "lrc":
            content = self._to_lrc(transcription["segments"])
            output_path = output_path.with_suffix(".lrc")
        else:
            raise ValueError(f"Unknown format: {format}")

        output_path.write_text(content, encoding="utf-8")
        return output_path

    def _to_srt(self, segments: list[dict]) -> str:
        lines = []
        for i, seg in enumerate(segments, 1):
            start = self._seconds_to_srt_time(seg["start"])
            end = self._seconds_to_srt_time(seg["end"])
            lines.append(f"{i}\n{start} --> {end}\n{seg['text']}\n")
        return "\n".join(lines)

    def _to_lrc(self, segments: list[dict]) -> str:
        lines = []
        for seg in segments:
            mm = int(seg["start"] // 60)
            ss = seg["start"] % 60
            lines.append(f"[{mm:02d}:{ss:05.2f}]{seg['text']}")
        return "\n".join(lines)

    @staticmethod
    def _seconds_to_srt_time(seconds: float) -> str:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = seconds % 60
        ms = int((s % 1) * 1000)
        return f"{h:02d}:{m:02d}:{int(s):02d},{ms:03d}"


def _clean_lyrics(raw: str) -> str:
    """Suno 태그([Verse], [Chorus] 등)와 공백줄 제거. 음절 단위 정렬 품질 향상."""
    import re
    lines = []
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        # [Verse 1], [Chorus], (Intro) 등 섹션 태그 제거
        if re.match(r"^\s*[\[\(].*[\]\)]\s*$", stripped):
            continue
        # 괄호 안 효과음 제거: (fading guitar) 등 — 단, 가사 자체 괄호는 유지
        stripped = re.sub(r"\(([^)]{0,80})\)", lambda m: "" if any(
            kw in m.group(1).lower() for kw in ("fading", "intro", "outro", "instrumental", "humming", "guitar", "strings")
        ) else m.group(0), stripped).strip()
        if stripped:
            lines.append(stripped)
    return "\n".join(lines)


lyrics_sync = LyricsSyncEngine()
