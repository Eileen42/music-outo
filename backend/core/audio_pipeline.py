"""
오디오 파일 처리: 업로드, 변환, 정규화, 메타데이터 추출.
메타데이터 추출은 mutagen(순수 Python)으로 처리 — ffmpeg 없이 동작.
빌드(병합/변환) 단계만 ffmpeg(pydub)이 필요.
"""
from __future__ import annotations

import asyncio
import uuid
import wave
from pathlib import Path

import aiofiles
import mutagen

SUPPORTED_FORMATS = {".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".opus"}


class AudioPipeline:
    async def process_upload(
        self,
        file_bytes: bytes,
        filename: str,
        project_dir: Path,
    ) -> dict:
        """업로드된 오디오 파일을 저장하고 메타데이터를 반환."""
        ext = Path(filename).suffix.lower()
        if ext not in SUPPORTED_FORMATS:
            raise ValueError(f"지원하지 않는 형식입니다: {ext}")

        audio_dir = project_dir / "audio"
        audio_dir.mkdir(parents=True, exist_ok=True)

        file_id = str(uuid.uuid4())
        dest = audio_dir / f"{file_id}{ext}"

        async with aiofiles.open(dest, "wb") as f:
            await f.write(file_bytes)

        info = await asyncio.to_thread(self._get_info, dest)
        return {
            "id": file_id,
            "filename": filename,
            "stored_path": str(dest),
            **info,
        }

    def _get_info(self, path: Path) -> dict:
        """mutagen으로 오디오 메타데이터 추출 (ffmpeg 불필요)."""
        ext = path.suffix.lower()

        # WAV는 Python 내장 wave 모듈로 처리
        if ext == ".wav":
            try:
                with wave.open(str(path), "rb") as wf:
                    frames = wf.getnframes()
                    rate = wf.getframerate()
                    channels = wf.getnchannels()
                    duration = frames / float(rate) if rate else 0
                return {
                    "duration": round(duration, 3),
                    "sample_rate": rate,
                    "channels": channels,
                }
            except Exception:
                pass

        # 그 외 포맷은 mutagen으로 처리
        try:
            audio = mutagen.File(str(path))
            if audio is not None and audio.info is not None:
                duration = getattr(audio.info, "length", 0) or 0
                sample_rate = getattr(audio.info, "sample_rate", 44100) or 44100
                channels = getattr(audio.info, "channels", 2) or 2
                return {
                    "duration": round(float(duration), 3),
                    "sample_rate": int(sample_rate),
                    "channels": int(channels),
                }
        except Exception:
            pass

        # 파일 크기로 재생시간 추정 (최후 수단)
        size_mb = path.stat().st_size / (1024 * 1024)
        estimated_duration = size_mb * 60  # 대략 1MB ≈ 1분
        return {
            "duration": round(estimated_duration, 3),
            "sample_rate": 44100,
            "channels": 2,
        }

    async def convert_to_wav(self, input_path: Path, output_path: Path) -> Path:
        audio = await asyncio.to_thread(AudioSegment.from_file, str(input_path))
        await asyncio.to_thread(audio.export, str(output_path), format="wav")
        return output_path

    async def normalize(
        self,
        input_path: Path,
        output_path: Path,
        target_dbfs: float = -14.0,
    ) -> Path:
        audio = await asyncio.to_thread(AudioSegment.from_file, str(input_path))
        delta = target_dbfs - audio.dBFS
        normalized = audio.apply_gain(delta)
        await asyncio.to_thread(normalized.export, str(output_path), format="mp3", bitrate="320k")
        return output_path

    async def trim_silence(self, input_path: Path, output_path: Path) -> Path:
        from pydub.silence import strip_silence
        audio = await asyncio.to_thread(AudioSegment.from_file, str(input_path))
        trimmed = await asyncio.to_thread(strip_silence, audio, silence_len=500, silence_thresh=-50)
        await asyncio.to_thread(trimmed.export, str(output_path), format="mp3")
        return output_path

    async def merge_tracks(
        self,
        track_paths: list[Path],
        output_path: Path,
        crossfade_ms: int = 2000,
    ) -> Path:
        """여러 트랙을 크로스페이드로 병합."""
        def _merge():
            combined = AudioSegment.from_file(str(track_paths[0]))
            for p in track_paths[1:]:
                segment = AudioSegment.from_file(str(p))
                combined = combined.append(segment, crossfade=crossfade_ms)
            combined.export(str(output_path), format="mp3", bitrate="320k")

        await asyncio.to_thread(_merge)
        return output_path


audio_pipeline = AudioPipeline()
