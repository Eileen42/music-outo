"""
CapCut(剪映) 프로젝트 파일 생성.
pyJianYingDraft 라이브러리 사용.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional


class CapcutBuilder:
    async def build(
        self,
        project_state: dict,
        output_dir: Path,
    ) -> Optional[Path]:
        """
        프로젝트 상태를 기반으로 CapCut 프로젝트 파일(.jianying or draft_content.json) 생성.
        """
        try:
            return await asyncio.to_thread(self._build_sync, project_state, output_dir)
        except ImportError:
            # pyJianYingDraft 미설치 시 스킵
            import logging
            logging.getLogger(__name__).warning(
                "pyJianYingDraft not installed. CapCut export skipped."
            )
            return None
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"CapCut build failed: {e}")
            return None

    def _build_sync(self, project_state: dict, output_dir: Path) -> Path:
        try:
            import jianying as jy
        except ImportError:
            import pyjianying as jy

        tracks = project_state.get("tracks", [])
        metadata = project_state.get("metadata", {})
        layers = project_state.get("layers", {})
        images = project_state.get("images", {})

        # 드래프트 생성
        draft = jy.Draft()

        # 배경 이미지/영상
        bg = images.get("background") or images.get("thumbnail")
        if bg and Path(bg).exists():
            bg_clip = jy.VideoClip(str(bg))
            draft.add_video_track([bg_clip])

        # 오디오 트랙
        for track in tracks:
            audio_path = track.get("stored_path")
            if audio_path and Path(audio_path).exists():
                audio_clip = jy.AudioClip(str(audio_path))
                draft.add_audio_track([audio_clip])
                break  # 첫 번째 트랙만 (병합된 경우)

        # 텍스트 레이어
        for text_layer in layers.get("text_layers", []):
            text_clip = jy.TextClip(
                text=text_layer.get("text", ""),
                font_size=text_layer.get("font_size", 48),
                color=text_layer.get("color", "#FFFFFF"),
            )
            draft.add_text_track([text_clip])

        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / "capcut_project"
        draft.save(str(output_path))

        # 저장된 파일 찾기
        for ext in [".jianying", ".zip", "_draft_content.json"]:
            candidate = output_dir / f"capcut_project{ext}"
            if candidate.exists():
                return candidate

        return output_dir / "capcut_project"

    async def build_simple_json(
        self,
        project_state: dict,
        output_dir: Path,
    ) -> Path:
        """
        pyJianYingDraft 없을 때 fallback:
        CapCut이 읽을 수 있는 간단한 draft_content.json 생성.
        """
        import json

        tracks = project_state.get("tracks", [])
        metadata = project_state.get("metadata", {})

        draft = {
            "id": project_state.get("id", ""),
            "name": metadata.get("title") or project_state.get("name", ""),
            "tracks": [
                {
                    "type": "audio",
                    "clips": [
                        {
                            "path": t.get("stored_path", ""),
                            "duration": t.get("duration", 0),
                            "title": t.get("title", ""),
                        }
                        for t in tracks
                    ],
                }
            ],
        }

        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / "draft_content.json"
        output_path.write_text(json.dumps(draft, ensure_ascii=False, indent=2))
        return output_path


capcut_builder = CapcutBuilder()
