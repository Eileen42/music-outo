"""
오디오에서 파형 데이터(JSON) + 정적 이미지(PNG) + 투명 애니메이션(MOV) 생성.

MOV: PIL 렌더링(프론트 프리뷰와 동일) + FFmpeg 파이프 인코딩.
RGBA 투명 배경 → CapCut에서 오버레이로 바로 사용.
"""
from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path
from typing import Literal

from pydub import AudioSegment

import os as _os
import shutil as _shutil


def _find_ffmpeg_bin() -> str | None:
    ff = _shutil.which("ffmpeg")
    if ff:
        return ff
    winget_dir = Path.home() / "AppData" / "Local" / "Microsoft" / "WinGet" / "Packages"
    if winget_dir.exists():
        for p in winget_dir.rglob("ffmpeg.exe"):
            _os.environ["PATH"] = str(p.parent) + _os.pathsep + _os.environ.get("PATH", "")
            return str(p)
    return None

_FFMPEG = _find_ffmpeg_bin()

WaveformStyle = Literal["bar", "line", "circle"]
LOOP_DURATION = 5.0
FPS = 20           # 20fps로 충분 (15→20 자연스러움)
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
            s = i * chunk_size
            e = min(s + chunk_size, total)
            chunk = raw[s:e]
            peak = max(abs(v) for v in chunk) / max_val if chunk else 0.0
            peaks.append(round(peak, 4))
        return {"samples": self.samples, "peaks": peaks, "duration": len(audio) / 1000.0}

    def _extract_realtime_energy(self, audio_path: Path, duration: float, fps: int, bar_count: int) -> list[list[float]]:
        """프레임별 바 에너지 데이터 추출."""
        audio = AudioSegment.from_file(str(audio_path))
        clip = audio[:int(duration * 1000)]
        mono = clip.set_channels(1)
        raw = mono.get_array_of_samples()
        max_val = float(2 ** (mono.sample_width * 8 - 1))
        total_frames = int(duration * fps)
        spf = max(len(raw) // total_frames, 1)  # samples per frame
        frames = []
        for f in range(total_frames):
            fs = f * spf
            fe = min(fs + spf, len(raw))
            frame_raw = raw[fs:fe]
            bars = []
            bsize = max(len(frame_raw) // bar_count, 1)
            for b in range(bar_count):
                bs = b * bsize
                be = min(bs + bsize, len(frame_raw))
                chunk = frame_raw[bs:be]
                if chunk:
                    energy = min(sum(abs(v) for v in chunk) / len(chunk) / max_val * 3.5, 1.0)
                else:
                    energy = 0.0
                bars.append(energy)
            frames.append(bars)
        return frames

    # ── 정적 이미지 (PNG) ────────────────────────────────────────

    async def generate_image(
        self, audio_path: Path, output_png: Path,
        width: int = 1920, height: int = 200,
        color: str = "#FFFFFF", style: WaveformStyle = "bar",
    ) -> Path:
        data = await self.generate_data(audio_path, output_png.with_suffix(".json"))
        await asyncio.to_thread(self._draw_static, data["peaks"], output_png, width, height, color, style)
        return output_png

    def _draw_static(self, peaks, out, w, h, color, style):
        from PIL import Image, ImageDraw
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        n = len(peaks)
        bw = max(w // n - 1, 1)
        cy = h // 2
        r, g, b = self._hex_to_rgb(color)
        for i, pk in enumerate(peaks):
            x = int(i * w / n)
            bh = max(int(pk * h * 0.9), 1)
            if style == "bar":
                draw.rectangle([x, cy - bh // 2, x + bw, cy + bh // 2], fill=(r, g, b, 220))
            elif style == "line" and i > 0:
                px = int((i - 1) * w / n)
                ph = max(int(peaks[i - 1] * h * 0.9), 1)
                draw.line([(px, cy - ph // 2), (x, cy - bh // 2)], fill=(r, g, b, 255), width=2)
        out.parent.mkdir(parents=True, exist_ok=True)
        img.save(str(out), "PNG")

    # ── 투명 애니메이션 (MOV) — PIL + FFmpeg 파이프 ──────────────

    async def generate_video(
        self, audio_path: Path, output_mp4: Path,
        width: int = 1920, height: int = 200,
        color: str = "#FFFFFF", style: WaveformStyle = "bar",
        loop_duration: float = LOOP_DURATION, fps: int = FPS,
        bar_count: int = BAR_COUNT, **_kw,
    ) -> Path:
        """
        투명 배경 파형 애니메이션 생성.
        PIL로 프론트 프리뷰와 동일한 스타일 렌더링 → FFmpeg 파이프로 MOV 인코딩.
        """
        ffmpeg = _FFMPEG or _find_ffmpeg_bin()
        if not ffmpeg:
            raise RuntimeError("FFmpeg를 찾을 수 없습니다")

        frames_data = await asyncio.to_thread(
            self._extract_realtime_energy, audio_path, loop_duration, fps, bar_count
        )

        # .mov 확장자로 변경 (투명도 지원)
        output_mov = output_mp4.with_suffix(".mov")
        output_mov.parent.mkdir(parents=True, exist_ok=True)

        await asyncio.to_thread(
            self._render_piped, frames_data, output_mov, width, height, color, style, fps, bar_count, ffmpeg
        )

        # capcut_builder가 .mp4로 찾으니 .mp4 심볼릭 링크/복사
        if output_mov.exists():
            import shutil
            shutil.copy(output_mov, output_mp4)

        return output_mp4

    def _render_piped(
        self, frames_data, output_mov, width, height, color, style, fps, bar_count, ffmpeg,
    ) -> None:
        """PIL RGBA 프레임 → FFmpeg stdin 파이프 → MOV (qtrle, 투명도)."""
        from PIL import Image, ImageDraw

        r, g, b = self._hex_to_rgb(color)
        bw = max(width // bar_count - 2, 2)
        gap = max((width - bar_count * bw) // (bar_count + 1), 1)
        cy = height // 2
        prev_bars = [0.0] * bar_count
        smooth = 0.35

        # FFmpeg: stdin에서 raw RGBA 프레임 받아서 MOV(qtrle) 인코딩
        cmd = [
            ffmpeg, "-y",
            "-f", "rawvideo",
            "-pix_fmt", "rgba",
            "-s", f"{width}x{height}",
            "-r", str(fps),
            "-i", "pipe:0",
            "-c:v", "qtrle",       # QuickTime Animation — RGBA 투명도 지원
            "-an",
            str(output_mov),
        ]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        for bars in frames_data:
            img = Image.new("RGBA", (width, height), (0, 0, 0, 0))  # 투명 배경
            draw = ImageDraw.Draw(img)

            for i, energy in enumerate(bars):
                s = prev_bars[i] * (1 - smooth) + energy * smooth
                prev_bars[i] = s
                bh = max(int(s * height * 0.85), 2)
                x = gap + i * (bw + gap)
                alpha = min(int(s * 200) + 50, 230)

                if style == "bar":
                    # 상반: 밝은, 하반: 약간 어둡게
                    draw.rectangle(
                        [x, cy - bh // 2, x + bw, cy],
                        fill=(r, g, b, alpha),
                    )
                    draw.rectangle(
                        [x, cy, x + bw, cy + bh // 2],
                        fill=(max(r - 20, 0), max(g - 20, 0), max(b - 20, 0), max(alpha - 30, 30)),
                    )
                elif style == "line":
                    if i > 0:
                        ph = max(int(prev_bars[i - 1] * height * 0.85), 2)
                        px = gap + (i - 1) * (bw + gap) + bw // 2
                        cx_ = x + bw // 2
                        draw.line([(px, cy - ph // 2), (cx_, cy - bh // 2)], fill=(r, g, b, alpha), width=3)

            # raw RGBA 바이트를 FFmpeg에 전달
            proc.stdin.write(img.tobytes())

        proc.stdin.close()
        proc.wait(timeout=30)

    @staticmethod
    def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
        hex_color = hex_color.lstrip("#")
        return tuple(int(hex_color[i: i + 2], 16) for i in (0, 2, 4))


waveform_generator = WaveformGenerator()
