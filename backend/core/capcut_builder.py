"""
CapCut(剪映) 프로젝트 폴더 생성.
CapCut이 인식하는 폴더 구조 + draft_content.json 생성.
"""
from __future__ import annotations

import json
import logging
import shutil
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def _uuid() -> str:
    return str(uuid.uuid4()).upper()


def _us(seconds: float) -> int:
    """초를 마이크로초로."""
    return int(seconds * 1_000_000)


# 샘플에서 추출한 segment 기본 키 (CapCut이 이 키들을 모두 요구)
_SEG_SKELETON: dict = {}


def _load_seg_skeleton() -> dict:
    global _SEG_SKELETON
    if _SEG_SKELETON:
        return _SEG_SKELETON
    p = Path(__file__).parent.parent / "assets" / "capcut_skeleton.json"
    if p.exists():
        skel = json.loads(p.read_text(encoding="utf-8"))
        ss = skel.get("segment_skeleton")
        if ss:
            _SEG_SKELETON = ss
            return ss
    # 하드코딩 기본값
    _SEG_SKELETON = {}
    return _SEG_SKELETON


def _make_speed(materials: dict) -> str:
    """speed material 생성, ID 반환."""
    sid = _uuid()
    materials["speeds"].append({
        "curve_speed": None, "id": sid, "mode": 0, "speed": 1.0, "type": "speed",
    })
    return sid


def _make_segment(
    material_id: str, start_us: int, duration_us: int,
    materials: dict,
    render_index: int = 0,
    clip: dict | None = None,
    extra_refs: list | None = None,
    source_start: int = 0,
) -> dict:
    """CapCut segment 생성 (모든 필수 키 포함)."""
    speed_id = _make_speed(materials)
    seg = dict(_load_seg_skeleton())  # 스켈레톤 복사
    seg.update({
        "id": _uuid(),
        "material_id": material_id,
        "target_timerange": {"start": start_us, "duration": duration_us},
        "source_timerange": {"start": source_start, "duration": duration_us},
        "render_index": render_index,
        "speed": 1.0,
        "extra_material_refs": extra_refs or [],
        "clip": clip or {"transform": {"x": 0.0, "y": 0.0}, "scale": {"x": 1.0, "y": 1.0}, "rotation": 0.0, "alpha": 1.0, "flip": {"horizontal": False, "vertical": False}},
        "visible": True,
        "volume": 1.0,
    })
    return seg


class CapcutBuilder:
    async def build(
        self,
        project_state: dict,
        output_dir: Path,
    ) -> Optional[Path]:
        """CapCut 프로젝트 폴더 생성. 반환: 폴더 경로."""
        try:
            return self._build_project_folder(project_state, output_dir)
        except Exception as e:
            logger.error(f"CapCut build failed: {e}", exc_info=True)
            raise

    async def build_simple_json(self, project_state: dict, output_dir: Path) -> Path:
        """fallback — 간단한 JSON만."""
        return self._build_project_folder(project_state, output_dir)

    def _build_project_folder(self, state: dict, output_dir: Path) -> Path:
        """CapCut 프로젝트 폴더 구조 생성."""
        import re
        assets_dir = Path(__file__).parent.parent / "assets"
        tracks = state.get("tracks", [])
        metadata = state.get("metadata", {})
        layers = state.get("layers", {})
        images = state.get("images", {})
        subtitle_entries = state.get("subtitle_entries", [])
        project_name = metadata.get("title") or state.get("name", "Untitled")

        # 안전한 폴더명
        safe_name = re.sub(r'[\\/:*?"<>|]', '_', project_name)[:60].strip() or "project"

        # CapCut 프로젝트 폴더 (실제 CapCut이 인식하는 위치)
        capcut_root = Path.home() / "AppData" / "Local" / "CapCut" / "User Data" / "Projects" / "com.lveditor.draft"
        if capcut_root.exists():
            project_dir = capcut_root / safe_name
        else:
            project_dir = output_dir / safe_name

        if project_dir.exists():
            shutil.rmtree(project_dir)
        project_dir.mkdir(parents=True)

        # 빈 폴더들
        for d in ["adjust_mask", "matting", "qr_upload", "smart_crop", "subdraft", "Resources", "common_attachment"]:
            (project_dir / d).mkdir(exist_ok=True)

        # GUID 폴더 (빈 폴더 3개)
        for _ in range(3):
            (project_dir / f"{{{_uuid()}}}").mkdir(exist_ok=True)

        # 오디오 총 길이 계산
        total_duration = sum(t.get("duration", 0) for t in tracks)
        total_us = _us(total_duration)

        # draft_content.json 생성
        draft_content = self._build_draft_content(
            state, tracks, images, layers, subtitle_entries, total_us, project_name
        )
        (project_dir / "draft_content.json").write_text(
            json.dumps(draft_content, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        # draft_meta_info.json (스켈레톤 기반)
        draft_id = _uuid()
        ts_us = int(time.time() * 1_000_000)
        meta_skeleton_path = assets_dir / "capcut_meta_skeleton.json"
        if meta_skeleton_path.exists():
            meta_info = json.loads(meta_skeleton_path.read_text(encoding="utf-8"))
        else:
            meta_info = {}
        meta_info.update({
            "draft_cover": "draft_cover.jpg",
            "draft_fold_path": str(project_dir).replace("\\", "/"),
            "draft_id": draft_id,
            "draft_name": safe_name,
            "draft_new_version": "163.0.0",
            "draft_root_path": str(project_dir.parent).replace("\\", "/"),
            "tm_draft_create": ts_us,
            "tm_draft_modified": ts_us,
            "tm_duration": total_us,
        })
        (project_dir / "draft_meta_info.json").write_text(
            json.dumps(meta_info, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        # draft_settings
        ts = int(time.time())
        (project_dir / "draft_settings").write_text(
            f"[General]\ndraft_create_time={ts}\ndraft_last_edit_time={ts}\nreal_edit_seconds=0\nreal_edit_keys=0\ncloud_last_modify_platform=windows\n",
            encoding="utf-8",
        )

        # 나머지 필수 파일 (빈/기본값)
        (project_dir / "draft.extra").write_text('{"category_id":"","category_name":""}', encoding="utf-8")
        (project_dir / "draft_agency_config.json").write_text(
            '{"is_auto_agency_enabled":false,"is_auto_agency_popup":false,"is_single_agency_mode":false,"marterials":null,"use_converter":false,"video_resolution":720}',
            encoding="utf-8",
        )
        (project_dir / "draft_biz_config.json").write_text("{}", encoding="utf-8")
        (project_dir / "draft_virtual_store.json").write_text('{"draft_materials":[],"draft_virtual_store":[]}', encoding="utf-8")
        (project_dir / "performance_opt_info.json").write_text('{"manual_cancle_precombine_segs":null,"need_auto_precombine_segs":null}', encoding="utf-8")

        tl_id = _uuid()
        (project_dir / "timeline_layout.json").write_text(
            json.dumps({"dockItems": [{"dockIndex": 0, "ratio": 1, "timelineIds": [tl_id], "timelineNames": [tl_id]}], "layoutOrientation": 1}),
            encoding="utf-8",
        )

        # 배경 이미지를 커버로 복사
        bg = images.get("background") or images.get("thumbnail")
        if bg and Path(bg).exists():
            try:
                shutil.copy(bg, project_dir / "draft_cover.jpg")
            except Exception:
                pass

        # 샘플에서 복사한 필수 파일들
        assets_dir = Path(__file__).parent.parent / "assets"
        for src_name, dst_name in [
            ("capcut_key_value.json", "key_value.json"),
            ("capcut_attachment_editing.json", "attachment_editing.json"),
            ("capcut_attachment_pc_common.json", "attachment_pc_common.json"),
        ]:
            src = assets_dir / src_name
            if src.exists():
                shutil.copy(src, project_dir / dst_name)

        # CapCut 폴더에 직접 생성된 경우 ZIP도 별도로 만들어 다운로드용
        zip_path = output_dir / f"{safe_name}.zip"
        shutil.make_archive(str(zip_path.with_suffix("")), "zip", str(project_dir))

        logger.info(f"CapCut project folder: {project_dir}")
        logger.info(f"CapCut ZIP: {zip_path}")

        # CapCut 프로젝트 폴더 경로 반환 (CapCut에서 바로 열 수 있음)
        # 다운로드용으로는 ZIP 경로 반환
        return zip_path

    def _build_draft_content(
        self, state: dict, tracks: list, images: dict, layers: dict,
        subtitle_entries: list, total_us: int, project_name: str,
    ) -> dict:
        """draft_content.json — 샘플 스켈레톤 기반."""
        # 스켈레톤 로드
        assets_dir = Path(__file__).parent.parent / "assets"
        skeleton_path = assets_dir / "capcut_skeleton.json"
        if skeleton_path.exists():
            skel = json.loads(skeleton_path.read_text(encoding="utf-8"))
            base = dict(skel.get("content_skeleton", {}))
            mat_keys = skel.get("materials_keys", [])
        else:
            base = {}
            mat_keys = []

        # materials: 모든 키를 빈 배열로 초기화
        materials: dict = {k: [] for k in mat_keys}
        # 우리가 사용하는 키도 보장
        for k in ["audios", "videos", "texts", "video_effects", "material_animations", "speeds", "canvases", "sound_channel_mappings"]:
            materials.setdefault(k, [])
        track_list: list = []

        # ── 1. 배경 이미지 트랙 ──
        bg_path = images.get("background") or images.get("thumbnail")
        if bg_path and Path(bg_path).exists():
            vid_id = _uuid()
            materials["videos"].append({
                "id": vid_id,
                "path": str(bg_path),
                "type": "photo",
                "width": 1920,
                "height": 1080,
                "duration": total_us,
            })
            track_list.append({
                "type": "video",
                "attribute": 0, "flag": 0, "id": _uuid(), "is_default_name": True, "name": "",
                "segments": [_make_segment(vid_id, 0, total_us, materials, render_index=0)],
            })

        # ── 2. 효과 트랙 (반딧불이 등) ──
        effect_layers = layers.get("effect_layers", [])
        for eff in effect_layers:
            if not eff.get("enabled"):
                continue
            eff_id = _uuid()
            materials["video_effects"].append({
                "id": eff_id,
                "name": eff.get("name", "효과"),
                "type": "video_effect",
                "effect_id": eff.get("effect_id", ""),
                "resource_id": eff.get("effect_id", ""),
                "adjust_params": [
                    {"name": k, "value": v, "default_value": v}
                    for k, v in eff.get("params", {}).items()
                ],
            })
            track_list.append({
                "type": "effect",
                "attribute": 0, "flag": 0, "id": _uuid(), "is_default_name": True, "name": "",
                "segments": [_make_segment(eff_id, 0, total_us, materials, render_index=11000)],
            })

        # ── 3. 자막 트랙 (SRT) ──
        if subtitle_entries:
            sub_style = layers.get("subtitle_style", {})
            sub_segments = []
            for entry in subtitle_entries:
                txt_id = _uuid()
                anim_id = _uuid()

                font_size = sub_style.get("font_size", 15)
                font_family = sub_style.get("font_family", "")
                color = sub_style.get("color", "#FFFFFF")
                italic = sub_style.get("italic", False)
                shadow = sub_style.get("shadow", {})

                materials["texts"].append({
                    "id": txt_id,
                    "type": "text",
                    "content": json.dumps({
                        "text": entry["text"],
                        "styles": [{"font": {"path": font_family}, "size": font_size,
                                    "fill": {"content": {"render_type": "solid", "solid": {"color": [1, 1, 1]}}}}],
                    }, ensure_ascii=False),
                    "font_size": float(font_size),
                    "text_color": color,
                    "has_shadow": shadow.get("enabled", False),
                    "shadow_alpha": shadow.get("alpha", 0.36),
                    "shadow_angle": shadow.get("angle", -45),
                    "shadow_color": shadow.get("color", "#000000"),
                    "shadow_distance": shadow.get("distance", 5),
                    "shadow_smoothing": shadow.get("blur", 1.75),
                    "alignment": 1,
                    "italic_degree": 12 if italic else 0,
                })

                # 애니메이션
                anim_in = sub_style.get("animation_in", {})
                animations = []
                if anim_in and anim_in.get("type") != "none":
                    animations.append({
                        "name": anim_in.get("type", "fade_in"),
                        "duration": _us(anim_in.get("duration", 3)),
                        "category_name": "인",
                    })
                materials["material_animations"].append({"id": anim_id, "animations": animations})

                start_us = _us(entry["start"])
                dur_us = _us(entry["end"] - entry["start"])
                sub_segments.append(_make_segment(
                    txt_id, start_us, dur_us, materials, render_index=14000,
                    clip={"transform": {"x": 0.0, "y": 0.0}, "scale": {"x": 0.325, "y": 0.325}, "rotation": 0.0, "alpha": 1.0, "flip": {"horizontal": False, "vertical": False}},
                    extra_refs=[anim_id],
                ))

            track_list.append({
                "type": "text",
                "attribute": 0, "flag": 0, "id": _uuid(), "is_default_name": True, "name": "",
                "segments": sub_segments,
            })

        # ── 4. 텍스트 레이어 트랙 (제목/설명) ──
        text_layers = layers.get("text_layers", [])
        for tl in text_layers:
            txt_id = _uuid()
            anim_id = _uuid()
            shadow = tl.get("shadow", {})
            anim_in = tl.get("animation_in", {})

            materials["texts"].append({
                "id": txt_id,
                "type": "text",
                "content": json.dumps({
                    "text": tl.get("text", ""),
                    "styles": [{"font": {"path": tl.get("font_family", "")}, "size": tl.get("font_size", 15),
                                "fill": {"content": {"render_type": "solid", "solid": {"color": [1, 1, 1]}}}}],
                }, ensure_ascii=False),
                "font_size": float(tl.get("font_size", 15)),
                "text_color": tl.get("color", "#FFFFFF"),
                "has_shadow": shadow.get("enabled", False),
                "shadow_alpha": shadow.get("alpha", 0.86),
                "shadow_angle": shadow.get("angle", -45),
                "shadow_color": shadow.get("color", "#000000"),
                "shadow_distance": shadow.get("distance", 5),
                "shadow_smoothing": shadow.get("blur", 2),
                "alignment": {"left": 0, "center": 1, "right": 2}.get(tl.get("alignment", "center"), 1),
                "italic_degree": 12 if tl.get("italic") else 0,
                "bold_width": 0.08 if tl.get("bold") else 0,
                "letter_spacing": tl.get("letter_spacing", 0),
                "line_spacing": tl.get("line_spacing", 0),
            })

            animations = []
            if anim_in and anim_in.get("type") != "none":
                animations.append({
                    "name": anim_in.get("type", "fade_in"),
                    "duration": _us(anim_in.get("duration", 3)),
                    "category_name": "인",
                })
            materials["material_animations"].append({"id": anim_id, "animations": animations})

            track_list.append({
                "type": "text",
                "attribute": 0, "flag": 0, "id": _uuid(), "is_default_name": True, "name": "",
                "segments": [_make_segment(
                    txt_id, 0, total_us, materials, render_index=14000,
                    clip={
                        "transform": {"x": tl.get("position_x", 0.5) * 2 - 1, "y": tl.get("position_y", 0.5) * 2 - 1},
                        "scale": {"x": tl.get("scale_x", 0.25), "y": tl.get("scale_y", 0.25)},
                        "rotation": 0.0, "alpha": 1.0, "flip": {"horizontal": False, "vertical": False},
                    },
                    extra_refs=[anim_id],
                )],
            })

        # ── 5. 오디오 트랙 ──
        audio_segments = []
        time_offset = 0
        for track in tracks:
            audio_path = track.get("stored_path", "")
            if not audio_path or not Path(audio_path).exists():
                continue
            aud_id = _uuid()
            dur = track.get("duration", 0)
            dur_us = _us(dur)
            materials["audios"].append({
                "id": aud_id,
                "path": str(audio_path),
                "duration": dur_us,
                "type": "extract_music",
                "name": track.get("title", ""),
            })
            audio_segments.append(_make_segment(
                aud_id, _us(time_offset), dur_us, materials, render_index=0,
            ))
            time_offset += dur

        if audio_segments:
            track_list.append({
                "type": "audio",
                "attribute": 0, "flag": 0, "id": _uuid(), "is_default_name": True, "name": "",
                "segments": audio_segments,
            })

        # 스켈레톤 + 우리 데이터 병합
        result = dict(base)
        result.update({
            "canvas_config": {"height": 1080, "ratio": "original", "width": 1920},
            "create_time": int(time.time()),
            "duration": total_us,
            "fps": 30.0,
            "id": state.get("id", _uuid()),
            "materials": materials,
            "name": project_name,
            "tracks": track_list,
            "new_version": "163.0.0",
            "version": 360000,
        })
        return result


capcut_builder = CapcutBuilder()
