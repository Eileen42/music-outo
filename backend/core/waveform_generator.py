"""
오디오에서 파형 데이터(JSON) + 정적 이미지(PNG) + 애니메이션 동영상(MP4) 생성.

MP4: 5초 루프 애니메이션 — 바가 음악에 반응하며 움직임.
CapCut에서 비디오 에셋으로 추가하여 전체 길이 반복 재생.
"""
from __future__ import annotations

import asyncio
import json
import math
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Literal

from pydub import AudioSegment

# FFmpeg PATH 자동 설정
import os as _os
import shutil as _shutil

def _setup_ffmpeg():
    if _shutil.which("ffmpeg"):
        return
    winget_dir = Path.home() / "AppData" / "Local" / "Microsoft" / "WinGet" / "Packages"
    if winget_dir.exists():
        for p in winget_dir.rglob("ffmpeg.exe"):
            bin_dir = str(p.parent)
            _os.environ["PATH"] = bin_dir + _os.pathsep + _os.environ.get("PATH", "")
            return

_setup_ffmpeg()

WaveformStyle = Literal["bar", "line", "circle"]

LOOP_DURATION = 5.0   # 루프 길이 (초)
FPS = 30              # 프레임레이트
BAR_COUNT = 64        # 바 개수 (애니메이션용)


class WaveformGenerator:
    def __init__(self, samples: int = 200):
        self.samples = samples

    # ── 데이터 추출 ──────────────────────────────────────────────

    async def generate_data(self, audio_path: Path, output_json: Path) -> dict:
        """오디오에서 파형 데이터(peak values)를 추출하여 JSON으로 저장."""
        data = await asyncio.to_thread(self._extract_peaks, audio_path)
        output_json.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(
            output_json.write_text,
            json.dumps(data, ensure_ascii=False),
        )
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

    def _extract_realtime_peaks(self, audio_path: Path, duration: float, fps: int, bar_count: int) -> list[list[float]]:
        """실시간 에너지 데이터 추출 — 프레임별 바 높이."""
        audio = AudioSegment.from_file(str(audio_path))
        # duration만큼만 사용
        clip = audio[:int(duration * 1000)]
        mono = clip.set_channels(1)
        raw = mono.get_array_of_samples()
        sample_rate = mono.frame_rate
        max_val = float(2 ** (mono.sample_width * 8 - 1))

        total_frames = int(duration * fps)
        samples_per_frame = max(len(raw) // total_frames, 1)
        frames = []

        for f in range(total_frames):
            start = f * samples_per_frame
            end = min(start + samples_per_frame, len(raw))
            frame_samples = raw[start:end]

            # bar_count개 구간으로 나눠 각 바의 에너지 계산
            bars = []
            chunk = max(len(frame_samples) // bar_count, 1)
            for b in range(bar_count):
                bs = b * chunk
                be = min(bs + chunk, len(frame_samples))
                bar_samples = frame_samples[bs:be]
                if bar_samples:
                    energy = sum(abs(v) for v in bar_samples) / len(bar_samples) / max_val
                    energy = min(energy * 3.0, 1.0)  # 부스트 + 클리핑
                else:
                    energy = 0.0
                bars.append(energy)
            frames.append(bars)

        return frames

    # ── 정적 이미지 (PNG) ────────────────────────────────────────

    async def generate_image(
        self,
        audio_path: Path,
        output_png: Path,
        width: int = 1920,
        height: int = 200,
        color: str = "#FFFFFF",
        style: WaveformStyle = "bar",
    ) -> Path:
        """파형 PNG 이미지 생성."""
        data = await self.generate_data(audio_path, output_png.with_suffix(".json"))
        await asyncio.to_thread(
            self._draw_image, data["peaks"], output_png, width, height, color, style
        )
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

    # ── 애니메이션 동영상 (MP4) ──────────────────────────────────

    async def generate_video(
        self,
        audio_path: Path,
        output_mp4: Path,
        width: int = 1920,
        height: int = 200,
        color: str = "#FFFFFF",
        style: WaveformStyle = "bar",
        loop_duration: float = LOOP_DURATION,
        fps: int = FPS,
        bar_count: int = BAR_COUNT,
    ) -> Path:
        """
        파형 애니메이션 MP4 생성 (루프용).

        - 오디오의 처음 loop_duration초를 분석하여 바가 음악에 반응하는 애니메이션 생성
        - 검은 배경 (CapCut에서 Screen blend로 합성)
        - 루프 재생 가능하도록 시작/끝 분위기를 맞춤
        """
        frames_data = await asyncio.to_thread(
            self._extract_realtime_peaks, audio_path, loop_duration, fps, bar_count
        )
        output_mp4.parent.mkdir(parents=True, exist_ok=True)

        await asyncio.to_thread(
            self._render_video, frames_data, output_mp4, width, height, color, style, fps, bar_count
        )
        return output_mp4

    def _render_video(
        self,
        frames_data: list[list[float]],
        output_mp4: Path,
        width: int,
        height: int,
        color: str,
        style: str,
        fps: int,
        bar_count: int,
    ) -> None:
        """프레임별 이미지 생성 → FFmpeg로 MP4 인코딩."""
        from PIL import Image, ImageDraw, ImageFilter

        r, g, b = self._hex_to_rgb(color)
        bar_w = max(width // bar_count - 2, 2)
        gap = max((width - bar_count * bar_w) // (bar_count + 1), 1)
        cx = height // 2

        # 이전 프레임의 바 높이 (스무딩용)
        prev_bars = [0.0] * bar_count
        smoothing = 0.3  # 낮을수록 부드러움

        tmp_dir = Path(tempfile.mkdtemp(prefix="waveform_"))

        try:
            for f_idx, bars in enumerate(frames_data):
                img = Image.new("RGB", (width, height), (0, 0, 0))
                draw = ImageDraw.Draw(img)

                for i, energy in enumerate(bars):
                    # 스무딩 — 급격한 변화 방지
                    smoothed = prev_bars[i] * (1 - smoothing) + energy * smoothing
                    prev_bars[i] = smoothed

                    bar_h = max(int(smoothed * height * 0.85), 2)
                    x = gap + i * (bar_w + gap)

                    if style == "bar":
                        # 그라데이션 효과 (위: 밝은, 아래: 어두운)
                        alpha_top = min(int(smoothed * 255) + 60, 255)
                        alpha_bot = max(alpha_top - 80, 40)
                        draw.rectangle(
                            [x, cx - bar_h // 2, x + bar_w, cx],
                            fill=(r, g, b),
                        )
                        draw.rectangle(
                            [x, cx, x + bar_w, cx + bar_h // 2],
                            fill=(max(r - 30, 0), max(g - 30, 0), max(b - 30, 0)),
                        )
                    elif style == "line":
                        if i > 0:
                            prev_h = max(int(prev_bars[i - 1] * height * 0.85), 2)
                            prev_x = gap + (i - 1) * (bar_w + gap) + bar_w // 2
                            cur_x = x + bar_w // 2
                            draw.line(
                                [(prev_x, cx - prev_h // 2), (cur_x, cx - bar_h // 2)],
                                fill=(r, g, b), width=3,
                            )

                # 글로우 효과 (살짝 블러)
                glow = img.filter(ImageFilter.GaussianBlur(radius=2))
                img = Image.blend(img, glow, alpha=0.3)

                frame_path = tmp_dir / f"frame_{f_idx:05d}.png"
                img.save(str(frame_path), "PNG")

            # FFmpeg 찾기
            ffmpeg = shutil.which("ffmpeg")
            if not ffmpeg:
                # winget 설치 경로 탐색
                winget_dir = Path.home() / "AppData" / "Local" / "Microsoft" / "WinGet" / "Packages"
                if winget_dir.exists():
                    for p in winget_dir.rglob("ffmpeg.exe"):
                        ffmpeg = str(p)
                        break
            if not ffmpeg:
                raise RuntimeError("FFmpeg를 찾을 수 없습니다")

            cmd = [
                ffmpeg, "-y",
                "-framerate", str(fps),
                "-i", str(tmp_dir / "frame_%05d.png"),
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                "-preset", "fast",
                "-crf", "23",
                "-movflags", "+faststart",
                str(output_mp4),
            ]
            subprocess.run(cmd, capture_output=True, timeout=120)

        finally:
            # 임시 프레임 파일 정리
            shutil.rmtree(tmp_dir, ignore_errors=True)

    @staticmethod
    def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
        hex_color = hex_color.lstrip("#")
        return tuple(int(hex_color[i: i + 2], 16) for i in (0, 2, 4))


waveform_generator = WaveformGenerator()
