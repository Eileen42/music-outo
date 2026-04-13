"""
오디오에서 파형 데이터(JSON) + 정적 이미지(PNG) + 애니메이션 동영상(MP4) 생성.

MP4: FFmpeg showwaves 필터로 1~2초 만에 생성 (PIL 프레임 렌더링 대신).
"""
from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path
from typing import Literal

from pydub import AudioSegment

# FFmpeg PATH 자동 설정
import os as _os
import shutil as _shutil

def _find_ffmpeg_bin() -> str | None:
    """FFmpeg 실행 파일 경로 반환."""
    ff = _shutil.which("ffmpeg")
    if ff:
        return ff
    winget_dir = Path.home() / "AppData" / "Local" / "Microsoft" / "WinGet" / "Packages"
    if winget_dir.exists():
        for p in winget_dir.rglob("ffmpeg.exe"):
            # PATH에도 추가 (pydub용)
            _os.environ["PATH"] = str(p.parent) + _os.pathsep + _os.environ.get("PATH", "")
            return str(p)
    return None

_FFMPEG = _find_ffmpeg_bin()

WaveformStyle = Literal["bar", "line", "circle"]
LOOP_DURATION = 5.0
BAR_COUNT = 64


class WaveformGenerator:
    def __init__(self, samples: int = 200):
        self.samples = samples

    # ── 데이터 추출 ──────────────────────────────────────────────

    async def generate_data(self, audio_path: Path, output_json: Path) -> dict:
        data = await asyncio.to_thread(self._extract_peaks, audio_path)
        output_json.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(output_json.write_text, json.dumps(data, ensure_ascii=False))
        return data

    def _extract_peaks(self, audio_path: Path) -> dict:
        audio = AudioSegment.from_file(str(audio_path))
        mono = audio.set_channels(1)
        raw = mono.get_array_of_samples()
        total = len(raw)
        chunk_size = max(total // self.samples, 1)
        peaks = []
        max_val = float(2 ** (mono.sample_width * 8 - 1))
        for i in range(self.samples):
            start = i * chunk_size
            end = min(start + chunk_size, total)
            chunk = raw[start:end]
            peak = max(abs(v) for v in chunk) / max_val if chunk else 0.0
            peaks.append(round(peak, 4))
        return {"samples": self.samples, "peaks": peaks, "duration": len(audio) / 1000.0}

    # ── 정적 이미지 (PNG) ────────────────────────────────────────

    async def generate_image(
        self, audio_path: Path, output_png: Path,
        width: int = 1920, height: int = 200,
        color: str = "#FFFFFF", style: WaveformStyle = "bar",
    ) -> Path:
        data = await self.generate_data(audio_path, output_png.with_suffix(".json"))
        await asyncio.to_thread(self._draw_image, data["peaks"], output_png, width, height, color, style)
        return output_png

    def _draw_image(self, peaks, output_png, width, height, color, style):
        from PIL import Image, ImageDraw
        img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        n = len(peaks)
        bar_w = max(width // n - 1, 1)
        cx = height // 2
        r, g, b = self._hex_to_rgb(color)
        for i, peak in enumerate(peaks):
            x = int(i * width / n)
            bar_h = max(int(peak * height * 0.9), 1)
            if style == "bar":
                draw.rectangle([x, cx - bar_h // 2, x + bar_w, cx + bar_h // 2], fill=(r, g, b, 220))
            elif style == "line" and i > 0:
                prev_x = int((i - 1) * width / n)
                prev_h = max(int(peaks[i - 1] * height * 0.9), 1)
                draw.line([(prev_x, cx - prev_h // 2), (x, cx - bar_h // 2)], fill=(r, g, b, 255), width=2)
        output_png.parent.mkdir(parents=True, exist_ok=True)
        img.save(str(output_png), "PNG")

    # ── 애니메이션 동영상 (MP4) — FFmpeg showwaves 필터 ──────────

    async def generate_video(
        self, audio_path: Path, output_mp4: Path,
        width: int = 1920, height: int = 200,
        color: str = "#FFFFFF", style: WaveformStyle = "bar",
        loop_duration: float = LOOP_DURATION,
        **_kwargs,
    ) -> Path:
        """
        FFmpeg showwaves 필터로 파형 애니메이션 MP4 생성.
        PIL 프레임 렌더링 대신 FFmpeg 네이티브 → 1~2초 만에 완료.
        """
        ffmpeg = _FFMPEG or _find_ffmpeg_bin()
        if not ffmpeg:
            raise RuntimeError("FFmpeg를 찾을 수 없습니다")

        output_mp4.parent.mkdir(parents=True, exist_ok=True)

        # 색상 변환 (hex → FFmpeg 형식)
        hex_clean = color.lstrip("#")
        r = int(hex_clean[0:2], 16)
        g = int(hex_clean[2:4], 16)
        b = int(hex_clean[4:6], 16)
        fg_color = f"0x{hex_clean}"

        # showwaves 모드 결정
        wf_mode = "cline" if style == "line" else "p2p"  # p2p = 바 형태

        cmd = [
            ffmpeg, "-y",
            "-t", str(loop_duration),
            "-i", str(audio_path),
            "-filter_complex", (
                f"[0:a]showwaves=s={width}x{height}:mode={wf_mode}:rate=30"
                f":colors={fg_color}:scale=sqrt"
                f",format=yuv420p"
            ),
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-crf", "28",
            "-an",  # 오디오 제거 (비주얼만)
            "-movflags", "+faststart",
            str(output_mp4),
        ]

        await asyncio.to_thread(
            subprocess.run, cmd, capture_output=True, timeout=30
        )

        if output_mp4.exists() and output_mp4.stat().st_size > 1000:
            return output_mp4

        raise RuntimeError(f"파형 MP4 생성 실패: {output_mp4}")

    @staticmethod
    def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
        hex_color = hex_color.lstrip("#")
        return tuple(int(hex_color[i: i + 2], 16) for i in (0, 2, 4))


waveform_generator = WaveformGenerator()
