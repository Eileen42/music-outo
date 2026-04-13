"""
오디오에서 파형 데이터(JSON) + 정적 이미지(PNG) + 투명 애니메이션(MOV) 생성.

MOV: 프론트 LayerPreview와 100% 동일한 렌더링.
프론트의 WaveformLayerConfig(bar_count, bar_width, bar_gap, bar_height,
position, opacity, color, bar_align, scale, bar_min)을 그대로 반영.
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
LOOP_DURATION = 5.0
FPS = 20
# 캡컷 출력 해상도
OUTPUT_W = 1920
OUTPUT_H = 1080


def _bell_envelope(i: int, count: int) -> float:
    """프론트와 동일한 bellEnvelope — 중앙이 높고 양쪽이 낮은 곡선."""
    x = (i / max(count - 1, 1)) * 2 - 1  # -1 ~ 1
    return math.exp(-2.5 * x * x)


class WaveformGenerator:
    def __init__(self, samples: int = 200):
        self.samples = samples

    # ── 데이터 ───────────────────────────────────────────────────

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
        audio = AudioSegment.from_file(str(audio_path))
        clip = audio[:int(duration * 1000)]
        mono = clip.set_channels(1)
        raw = mono.get_array_of_samples()
        max_val = float(2 ** (mono.sample_width * 8 - 1))
        total_frames = int(duration * fps)
        spf = max(len(raw) // total_frames, 1)
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
                energy = min(sum(abs(v) for v in chunk) / len(chunk) / max_val * 3.5, 1.0) if chunk else 0.0
                bars.append(energy)
            frames.append(bars)
        return frames

    # ── PNG ───────────────────────────────────────────────────────

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

    # ── 투명 MOV (프론트 프리뷰와 동일한 렌더링) ────────────────

    async def generate_video(
        self, audio_path: Path, output_mp4: Path,
        width: int = OUTPUT_W, height: int = OUTPUT_H,
        color: str = "#FFFFFF", style: WaveformStyle = "bar",
        loop_duration: float = LOOP_DURATION, fps: int = FPS,
        waveform_config: dict | None = None, **_kw,
    ) -> Path:
        """
        프론트 LayerPreview와 동일한 파형 애니메이션 생성.
        waveform_config: 프론트의 WaveformLayerConfig 전체.
        """
        ffmpeg = _FFMPEG or _find_ffmpeg_bin()
        if not ffmpeg:
            raise RuntimeError("FFmpeg를 찾을 수 없습니다")

        cfg = waveform_config or {}
        bar_count = cfg.get("bar_count", 60)

        frames_data = await asyncio.to_thread(
            self._extract_realtime_energy, audio_path, loop_duration, fps, bar_count
        )

        output_mov = output_mp4.with_suffix(".mov")
        output_mov.parent.mkdir(parents=True, exist_ok=True)

        await asyncio.to_thread(
            self._render_matched, frames_data, output_mov, width, height, cfg, fps, ffmpeg
        )

        if output_mov.exists():
            import shutil
            shutil.copy(output_mov, output_mp4)
        return output_mp4

    def _render_matched(
        self, frames_data, output_mov, width, height, cfg, fps, ffmpeg,
    ) -> None:
        """프론트 LayerPreview의 drawWf()와 정확히 동일한 렌더링."""
        from PIL import Image, ImageDraw

        # 프론트 설정 파싱 (DEF_WF 기본값 포함)
        bar_count = cfg.get("bar_count", 60)
        bar_width = cfg.get("bar_width", 4)
        bar_gap = cfg.get("bar_gap", 2)
        bar_height = cfg.get("bar_height", 120)
        bar_min = cfg.get("bar_min", 0.1)
        bar_align = cfg.get("bar_align", "bottom")
        scale = cfg.get("scale", 1.0)
        opacity = cfg.get("opacity", 0.8)
        pos_x = cfg.get("position_x", 0.5)
        pos_y = cfg.get("position_y", 0.7)
        color = cfg.get("color", "#FFFFFF")
        style = cfg.get("style", "bar")

        r, g, b = self._hex_to_rgb(color)
        alpha = int(opacity * 255)

        # 1920x1080 기준 실제 크기 (보정 없음)
        sc = scale
        bw = bar_width * sc
        gap = bar_gap * sc
        max_h = bar_height * sc
        cx = pos_x * width
        cy = pos_y * height
        total_w = bar_count * (bw + gap)
        start_x = cx - total_w / 2

        # 스무딩용
        prev_bars = [0.0] * bar_count
        targ_bars = [0.0] * bar_count
        smooth = 0.08  # 프론트와 동일
        tick = 0

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

            # 프론트 애니메이션 로직 그대로 재현
            tick += 1
            if tick % 6 == 0:
                for i in range(bar_count):
                    # 프론트: targRef[i] = Math.random() * (1 - bmin) + bmin
                    # 여기서는 실제 에너지 데이터 사용 (더 정확)
                    targ_bars[i] = max(energy_bars[i] * (1 - bar_min) + bar_min, bar_min)

            for i in range(bar_count):
                # 스무딩: 프론트와 동일
                prev_bars[i] += (targ_bars[i] - prev_bars[i]) * smooth
                env = _bell_envelope(i, bar_count)
                h = prev_bars[i] * max_h * env
                if h < 1:
                    continue  # bar_min=0이면 에너지 없는 바는 안 그림
                x = start_x + i * (bw + gap)

                if style == "circle":
                    # circle 모드 — 프론트와 동일
                    circle_r = height * (cfg.get("circle_radius", 0.12)) * scale
                    cbw = max(2, bw * 0.8)
                    angle = (i / bar_count) * math.pi * 2 - math.pi / 2
                    x1 = cx + math.cos(angle) * circle_r
                    y1 = cy + math.sin(angle) * circle_r
                    x2 = cx + math.cos(angle) * (circle_r + h)
                    y2 = cy + math.sin(angle) * (circle_r + h)
                    draw.line([(x1, y1), (x2, y2)], fill=(r, g, b, alpha), width=max(int(cbw), 1))
                else:
                    # bar 모드 — align에 따라 위치
                    if bar_align == "center":
                        draw.rectangle([x, cy - h / 2, x + bw, cy + h / 2], fill=(r, g, b, alpha))
                    elif bar_align == "top":
                        draw.rectangle([x, cy, x + bw, cy + h], fill=(r, g, b, alpha))
                    else:  # bottom
                        draw.rectangle([x, cy - h, x + bw, cy], fill=(r, g, b, alpha))

            proc.stdin.write(img.tobytes())

        proc.stdin.close()
        proc.wait(timeout=60)

    @staticmethod
    def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
        hex_color = hex_color.lstrip("#")
        return tuple(int(hex_color[i: i + 2], 16) for i in (0, 2, 4))


waveform_generator = WaveformGenerator()
