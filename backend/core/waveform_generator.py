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
        # 정확히 duration * fps 프레임 (여분 없음 — MOV 길이가 정확히 duration초여야 루프 이음매 없음)
        n_frames = int(duration * fps)
        clip = audio[:int(duration * 1000)]
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
        """프론트 drawWf()와 100% 동일한 렌더링 → FFmpeg 파이프.

        Canvas fillRect(x, y, w, h) 방식:
          - x, y: 왼쪽 상단 시작
          - w, h: 폭과 높이 (x+w는 포함 안 함)

        PIL draw.rectangle([x1, y1, x2, y2]) 방식:
          - x2, y2: 포함됨 → 실제 폭 = x2 - x1 + 1

        따라서 Canvas fillRect(x, y, bw, h) == PIL rectangle([x, y, x+bw-1, y+h-1])
        """
        from PIL import Image, ImageDraw

        r, g, b = self._hex_to_rgb(color)
        alpha = int(opacity * 255)

        # 프론트와 동일한 계산 (보정 없이 순수 값 사용)
        sc = scale
        bw = bar_width * sc       # Canvas fillRect의 w 값 그대로
        gap = bar_gap * sc         # Canvas fillRect의 gap 그대로
        max_h = bar_height * sc
        cx = pos_x * width
        cy = pos_y * height
        total_w = bar_count * (bw + gap)
        start_x = cx - total_w / 2

        # 루프 이음매를 자연스럽게 하기 위해 2-pass:
        # 1차: 전체 프레임을 한 번 돌려서 마지막 상태를 구함
        # 2차: 마지막 상태를 초기값으로 사용해서 렌더링 → 마지막→첫 프레임이 자연스럽게 연결
        import random
        total_frames = len(frames_data)

        def _simulate(init_prev, init_targ):
            """프레임 시뮬레이션 — 최종 상태 반환."""
            prev = list(init_prev)
            targ = list(init_targ)
            tk = 0
            for energy_bars in frames_data:
                tk += 1
                if tk % 6 == 0:
                    for i in range(bar_count):
                        targ[i] = max(energy_bars[i] * (1 - uniformity) + uniformity, uniformity)
                for i in range(bar_count):
                    prev[i] += (targ[i] - prev[i]) * 0.08
            return prev, targ

        # 1차: 랜덤 초기값으로 시뮬레이션
        random.seed(42)
        init_prev = [random.random() * (1 - uniformity) + uniformity for _ in range(bar_count)]
        init_targ = [random.random() * (1 - uniformity) + uniformity for _ in range(bar_count)]
        end_prev, end_targ = _simulate(init_prev, init_targ)

        # 2차: 마지막 상태를 초기값으로 → 루프 시 끊김 없음
        prev_bars = list(end_prev)
        targ_bars = list(end_targ)
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

            tick += 1
            if tick % 6 == 0:
                for i in range(bar_count):
                    targ_bars[i] = max(energy_bars[i] * (1 - uniformity) + uniformity, uniformity)

            for i in range(bar_count):
                prev_bars[i] += (targ_bars[i] - prev_bars[i]) * 0.08
                env = _bell(i, bar_count)
                h = prev_bars[i] * max_h * env
                # 프론트 Canvas는 h < 1이어도 렌더링하므로 skip 조건 제거
                # 다만 0 이하는 의미 없으므로 최소 1px 보장
                h = max(h, 1)
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
                    # PIL rectangle: x2 = x + bw - 1 (Canvas fillRect과 동일 폭)
                    x2 = x + bw - 1
                    if bar_align == "center":
                        draw.rectangle([x, cy - h/2, x2, cy + h/2 - 1], fill=(r, g, b, alpha))
                    elif bar_align == "top":
                        draw.rectangle([x, cy, x2, cy + h - 1], fill=(r, g, b, alpha))
                    else:
                        draw.rectangle([x, cy - h, x2, cy - 1], fill=(r, g, b, alpha))

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
