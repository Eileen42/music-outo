"""
오디오에서 파형 데이터 생성 (JSON) + 파형 이미지 생성 (PNG).
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Literal

from pydub import AudioSegment

WaveformStyle = Literal["bar", "line", "circle"]


class WaveformGenerator:
    def __init__(self, samples: int = 200):
        self.samples = samples

    async def generate_data(self, audio_path: Path, output_json: Path) -> dict:
        """오디오에서 파형 데이터(peak values)를 추출하여 JSON으로 저장."""
        data = await asyncio.to_thread(self._extract_peaks, audio_path)
        output_json.parent.mkdir(parents=True, exist_ok=True)
        async_write = asyncio.to_thread(
            output_json.write_text,
            json.dumps(data, ensure_ascii=False),
        )
        await async_write
        return data

    def _extract_peaks(self, audio_path: Path) -> dict:
        audio = AudioSegment.from_file(str(audio_path))
        # 모노로 변환
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
            if chunk:
                peak = max(abs(v) for v in chunk) / max_val
            else:
                peak = 0.0
            peaks.append(round(peak, 4))

        return {
            "samples": self.samples,
            "peaks": peaks,
            "duration": len(audio) / 1000.0,
        }

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

    def _draw_image(
        self,
        peaks: list[float],
        output_png: Path,
        width: int,
        height: int,
        color: str,
        style: WaveformStyle,
    ) -> None:
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
                draw.rectangle(
                    [x, cx - bar_h // 2, x + bar_w, cx + bar_h // 2],
                    fill=(r, g, b, 220),
                )
            elif style == "line":
                if i > 0:
                    prev_x = int((i - 1) * width / n)
                    prev_h = max(int(peaks[i - 1] * height * 0.9), 1)
                    draw.line(
                        [(prev_x, cx - prev_h // 2), (x, cx - bar_h // 2)],
                        fill=(r, g, b, 255),
                        width=2,
                    )

        output_png.parent.mkdir(parents=True, exist_ok=True)
        img.save(str(output_png), "PNG")

    @staticmethod
    def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
        hex_color = hex_color.lstrip("#")
        return tuple(int(hex_color[i: i + 2], 16) for i in (0, 2, 4))


waveform_generator = WaveformGenerator()
