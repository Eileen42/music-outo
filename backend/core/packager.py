"""
빌드 파이프라인: 오디오 병합 → 영상 합성 → CapCut 파일 생성 → 패키징.
FFmpeg subprocess 기반.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Callable, Optional

from core.audio_pipeline import audio_pipeline
from core.capcut_builder import capcut_builder
from core.waveform_generator import waveform_generator


class Packager:
    async def build(
        self,
        project_state: dict,
        project_dir: Path,
        progress_cb: Optional[Callable[[int, str], None]] = None,
    ) -> dict:
        """
        전체 빌드 파이프라인 실행.

        Returns:
            {"output_file": str, "capcut_file": str | None, "error": None}
        """
        output_dir = project_dir / "outputs"
        output_dir.mkdir(parents=True, exist_ok=True)

        def report(pct: int, msg: str):
            if progress_cb:
                progress_cb(pct, msg)

        try:
            tracks = project_state.get("tracks", [])
            images = project_state.get("images", {})
            layers = project_state.get("layers", {})

            # 1. 오디오 병합
            report(10, "오디오 병합 중...")
            audio_paths = [Path(t["stored_path"]) for t in tracks if t.get("stored_path")]
            if not audio_paths:
                raise ValueError("업로드된 오디오 트랙이 없습니다.")

            merged_audio = output_dir / "merged_audio.mp3"
            if len(audio_paths) == 1:
                import shutil
                shutil.copy(audio_paths[0], merged_audio)
            else:
                await audio_pipeline.merge_tracks(audio_paths, merged_audio)

            # 2. 파형 이미지 생성
            report(30, "파형 생성 중...")
            waveform_config = layers.get("waveform_layer") or {}
            waveform_img = output_dir / "waveform.png"
            if waveform_config.get("enabled", True):
                await waveform_generator.generate_image(
                    merged_audio,
                    waveform_img,
                    color=waveform_config.get("color", "#FFFFFF"),
                    style=waveform_config.get("style", "bar"),
                )

            # 3. 배경 이미지 결정
            report(40, "배경 설정 중...")
            bg_path = images.get("background") or images.get("thumbnail")

            # 4. FFmpeg로 영상 합성
            report(50, "영상 합성 중...")
            output_video = output_dir / "output.mp4"
            await self._build_video(
                audio_path=merged_audio,
                bg_path=Path(bg_path) if bg_path else None,
                waveform_path=waveform_img if waveform_img.exists() else None,
                text_layers=layers.get("text_layers", []),
                output_path=output_video,
            )

            # 5. CapCut 파일 생성
            report(85, "CapCut 파일 생성 중...")
            capcut_file = await capcut_builder.build(project_state, output_dir)
            if not capcut_file:
                capcut_file = await capcut_builder.build_simple_json(project_state, output_dir)

            report(100, "빌드 완료!")
            return {
                "output_file": str(output_video),
                "capcut_file": str(capcut_file) if capcut_file else None,
                "error": None,
            }

        except Exception as e:
            return {"output_file": None, "capcut_file": None, "error": str(e)}

    async def build_capcut_only(
        self,
        project_state: dict,
        project_dir: Path,
        progress_cb: Optional[Callable[[int, str], None]] = None,
    ) -> dict:
        """CapCut 프로젝트 파일만 생성 (FFmpeg 불필요)."""
        output_dir = project_dir / "outputs"
        output_dir.mkdir(parents=True, exist_ok=True)

        def report(pct: int, msg: str = ""):
            if progress_cb:
                progress_cb(pct, msg)

        try:
            tracks = project_state.get("tracks", [])
            if not tracks:
                raise ValueError("트랙이 없습니다.")

            # 오디오 병합 (단일 트랙이면 복사)
            report(20, "오디오 준비 중...")
            audio_paths = [Path(t["stored_path"]) for t in tracks if t.get("stored_path")]
            merged_audio = output_dir / "merged_audio.mp3"
            if len(audio_paths) == 1:
                import shutil
                if not merged_audio.exists() or merged_audio.stat().st_size == 0:
                    shutil.copy(audio_paths[0], merged_audio)
            elif len(audio_paths) > 1:
                await audio_pipeline.merge_tracks(audio_paths, merged_audio)

            report(50, "CapCut 프로젝트 생성 중...")
            capcut_file = await capcut_builder.build(project_state, output_dir)
            if not capcut_file:
                capcut_file = await capcut_builder.build_simple_json(project_state, output_dir)

            report(100, "완료!")
            return {
                "output_file": None,
                "capcut_file": str(capcut_file) if capcut_file else None,
                "error": None,
            }

        except Exception as e:
            return {"output_file": None, "capcut_file": None, "error": str(e)}

    async def _build_video(
        self,
        audio_path: Path,
        bg_path: Optional[Path],
        waveform_path: Optional[Path],
        text_layers: list[dict],
        output_path: Path,
    ) -> None:
        """FFmpeg 명령으로 영상 합성."""
        cmd = await asyncio.to_thread(
            self._compose_ffmpeg_cmd,
            audio_path, bg_path, waveform_path, text_layers, output_path,
        )
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"FFmpeg failed: {stderr.decode()[-500:]}")

    def _compose_ffmpeg_cmd(
        self,
        audio_path: Path,
        bg_path: Optional[Path],
        waveform_path: Optional[Path],
        text_layers: list[dict],
        output_path: Path,
    ) -> list[str]:
        inputs = []
        filter_parts = []
        current_stream = None

        # 배경 입력
        if bg_path and bg_path.exists():
            inputs += ["-loop", "1", "-i", str(bg_path)]
            idx = len(inputs) // 2 - 1
            filter_parts.append(f"[{idx}:v]scale=1920:1080,setsar=1[bg]")
            current_stream = "bg"
        else:
            # 검은 배경 생성
            filter_parts.append("color=black:s=1920x1080:r=30[bg]")
            current_stream = "bg"

        # 파형 오버레이
        if waveform_path and waveform_path.exists():
            inputs += ["-i", str(waveform_path)]
            wf_idx = len(inputs) // 2 - 1
            y_pos = 480  # 화면 중앙
            filter_parts.append(
                f"[{wf_idx}:v]scale=1920:200[wf];"
                f"[{current_stream}][wf]overlay=0:{y_pos}[composited]"
            )
            current_stream = "composited"

        # 텍스트 레이어
        for i, tl in enumerate(text_layers):
            text = tl.get("text", "").replace("'", r"\'").replace(":", r"\:")
            font_size = tl.get("font_size", 48)
            color = tl.get("color", "white").lstrip("#")
            x = f"w*{tl.get('position_x', 0.5)}-tw/2"
            y = f"h*{tl.get('position_y', 0.1)}"
            label = f"txt{i}"
            filter_parts.append(
                f"[{current_stream}]drawtext="
                f"text='{text}':fontsize={font_size}:fontcolor=0x{color}:"
                f"x={x}:y={y}[{label}]"
            )
            current_stream = label

        audio_idx = len(inputs) // 2
        inputs += ["-i", str(audio_path)]

        filter_complex = ";".join(filter_parts) if filter_parts else ""

        cmd = ["ffmpeg", "-y"]
        cmd += inputs
        if filter_complex:
            cmd += ["-filter_complex", filter_complex, "-map", f"[{current_stream}]"]
        else:
            cmd += ["-map", "0:v"]
        cmd += [
            "-map", f"{audio_idx}:a",
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "18",
            "-c:a", "aac",
            "-b:a", "192k",
            "-shortest",
            "-movflags", "+faststart",
            str(output_path),
        ]
        return cmd


packager = Packager()
