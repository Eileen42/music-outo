"""
파형 생성기 — 사전 생성 방식.

레이어 설정에서 "파형 만들기" → 10초 24fps 투명 MOV 생성.
빌드 시 capcut_builder가 이 MOV를 반복 배치.
"""
from __future__ import annotations

import asyncio
import json
import math
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

# 프론트와 동일한 bellEnvelope
def _bell(i: int, n: int) -> float:
    x = (i / max(n - 1, 1)) * 2 - 1
    return 0.2 + 0.8 * math.exp(-3.0 * x * x)


class WaveformGenerator:
    """파형 MOV 사전 생성기."""

    def __init__(self, samples: int = 200):
        self.samples = samples

    # ── 데이터 추출 ──────────────────────────────────────────────

    def _extract_peaks(self, audio_path: Path) -> dict:
        audio = AudioSegment.from_file(str(audio_path))
        mono = audio.set_channels(1)
        raw = mono.get_array_of_samples()
        total = len(raw)
        chunk = max(total // self.samples, 1)
        peaks = []
        mx = float(2 ** (mono.sample_width * 8 - 1))
        for i in range(self.samples):
            s, e = i * chunk, min((i + 1) * chunk, total)
            pk = max(abs(v) for v in raw[s:e]) / mx if s < e else 0.0
            peaks.append(round(pk, 4))
        return {"samples": self.samples, "peaks": peaks, "duration": len(audio) / 1000.0}

    def _extract_energy(self, audio_path: Path, duration: float, fps: int, bar_count: int) -> list[list[float]]:
        audio = AudioSegment.from_file(str(audio_path))
        # 여분 프레임 2개 추가 — FFmpeg 인코딩 시 마지막 프레임 누락 방지 (루프 이음매 공백 제거)
        n_frames = int(duration * fps) + 2
        clip = audio[:int((n_frames / fps) * 1000)]
        mono = clip.set_channels(1)
        raw = mono.get_array_of_samples()
        mx = float(2 ** (mono.sample_width * 8 - 1))
        spf = max(len(raw) // n_frames, 1)
        frames = []
        for f in range(n_frames):
            fs, fe = f * spf, min((f + 1) * spf, len(raw))
            fr = raw[fs:fe]
            bars = []
            bs = max(len(fr) // bar_count, 1)
            for b in range(bar_count):
                s, e = b * bs, min((b + 1) * bs, len(fr))
                chunk = fr[s:e]
                energy = min(sum(abs(v) for v in chunk) / len(chunk) / mx * 3.5, 1.0) if chunk else 0.0
                bars.append(energy)
            frames.append(bars)
        return frames

    # ── PNG (정적) ───────────────────────────────────────────────

    async def generate_image(self, audio_path: Path, output_png: Path,
                              width=1920, height=200, color="#FFFFFF",
                              style: WaveformStyle = "bar") -> Path:
        data = await asyncio.to_thread(self._extract_peaks, audio_path)
        output_png.parent.mkdir(parents=True, exist_ok=True)
        json_path = output_png.with_suffix(".json")
        json_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        await asyncio.to_thread(self._draw_png, data["peaks"], output_png, width, height, color, style)
        return output_png

    def _draw_png(self, peaks, out, w, h, color, style):
        from PIL import Image, ImageDraw
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        n = len(peaks); bw = max(w // n - 1, 1); cy = h // 2
        r, g, b = self._hex_to_rgb(color)
        for i, pk in enumerate(peaks):
            x = int(i * w / n); bh = max(int(pk * h * 0.9), 1)
            if style == "bar":
                draw.rectangle([x, cy - bh//2, x+bw, cy+bh//2], fill=(r, g, b, 220))
        img.save(str(out), "PNG")

    # ── MOV (투명 애니메이션) — 사전 생성 ────────────────────────

    async def create_waveform_mov(
        self,
        audio_path: Path,
        output_dir: Path,
        duration: int = 10,
        fps: int = 24,
        bar_count: int = 20,
        bar_width: int = 4,
        bar_gap: int = 3,
        uniformity: float = 0.3,
        color: str = "#FFFFFF",
        opacity: float = 0.8,
        bar_height: int = 120,
        bar_align: str = "center",
        scale: float = 1.0,
        position_x: float = 0.5,
        position_y: float = 0.7,
        style: str = "bar",
        progress_cb=None,
    ) -> Path:
        """
        10초 24fps 투명 MOV 생성.
        PIL로 프레임 렌더링 → FFmpeg 파이프 인코딩.
        """
        ffmpeg = _FFMPEG or _find_ffmpeg_bin()
        if not ffmpeg:
            raise RuntimeError("FFmpeg를 찾을 수 없습니다")

        output_dir.mkdir(parents=True, exist_ok=True)
        output_mov = output_dir / "waveform_loop.mov"

        # 에너지 데이터 추출
        if progress_cb:
            progress_cb(10)
        frames_data = await asyncio.to_thread(
            self._extract_energy, audio_path, duration, fps, bar_count
        )

        # PIL 렌더링 + FFmpeg 파이프
        if progress_cb:
            progress_cb(30)
        await asyncio.to_thread(
            self._render_mov, frames_data, output_mov,
            1920, 1080,  # 항상 1920x1080
            bar_count, bar_width, bar_gap, bar_height, uniformity,
            color, opacity, bar_align, scale, position_x, position_y, style,
            fps, ffmpeg, progress_cb,
        )

        if progress_cb:
            progress_cb(100)
        return output_mov

    def _render_mov(
        self, frames_data, output_mov,
        width, height,
        bar_count, bar_width, bar_gap, bar_height, uniformity,
        color, opacity, bar_align, scale, pos_x, pos_y, style,
        fps, ffmpeg, progress_cb,
    ):
        """프론트 drawWf()와 동일한 렌더링 → FFmpeg 파이프."""
        from PIL import Image, ImageDraw

        r, g, b = self._hex_to_rgb(color)
        alpha = int(opacity * 255)

        sc = scale
        # PIL rectangle는 [x1,y1,x2,y2]에서 x2를 포함 → 폭이 1px 늘어남
        # Canvas fillRect(x,y,w,h)와 일치시키기 위해 -1 보정
        bw = max(bar_width * sc - 1, 1)
        gap = bar_gap * sc + 1  # bw가 줄어든 만큼 gap 보정으로 전체 간격 유지
        max_h = bar_height * sc
        cx = pos_x * width
        cy = pos_y * height
        total_w = bar_count * (bw + gap)
        start_x = cx - total_w / 2

        prev_bars = [uniformity] * bar_count
        targ_bars = [uniformity] * bar_count
        tick = 0
        total_frames = len(frames_data)

        cmd = [
            ffmpeg, "-y",
            "-f", "rawvideo", "-pix_fmt", "rgba",
            "-s", f"{width}x{height}", "-r", str(fps),
            "-i", "pipe:0",
            "-c:v", "qtrle", "-an",
            str(output_mov),
        ]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        for f_idx, energy_bars in enumerate(frames_data):
            img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)

            tick += 1
            if tick % 6 == 0:
                for i in range(bar_count):
                    targ_bars[i] = max(energy_bars[i] * (1 - uniformity) + uniformity, uniformity)

            for i in range(bar_count):
                prev_bars[i] += (targ_bars[i] - prev_bars[i]) * 0.08
                env = _bell(i, bar_count)
                h = prev_bars[i] * max_h * env
                if h < 1:
                    continue
                x = start_x + i * (bw + gap)

                if style == "circle":
                    cr = height * 0.12 * sc
                    cbw = max(2, bw * 0.8)
                    angle = (i / bar_count) * math.pi * 2 - math.pi / 2
                    x1 = cx + math.cos(angle) * cr
                    y1 = cy + math.sin(angle) * cr
                    x2 = cx + math.cos(angle) * (cr + h)
                    y2 = cy + math.sin(angle) * (cr + h)
                    draw.line([(x1, y1), (x2, y2)], fill=(r, g, b, alpha), width=max(int(cbw), 1))
                else:
                    if bar_align == "center":
                        draw.rectangle([x, cy - h/2, x + bw, cy + h/2], fill=(r, g, b, alpha))
                    elif bar_align == "top":
                        draw.rectangle([x, cy, x + bw, cy + h], fill=(r, g, b, alpha))
                    else:
                        draw.rectangle([x, cy - h, x + bw, cy], fill=(r, g, b, alpha))

            proc.stdin.write(img.tobytes())

            if progress_cb and f_idx % 24 == 0:
                pct = 30 + int(f_idx / total_frames * 65)
                progress_cb(pct)

        proc.stdin.close()
        proc.wait(timeout=120)

    @staticmethod
    def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
        hex_color = hex_color.lstrip("#")
        return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))


waveform_generator = WaveformGenerator()
