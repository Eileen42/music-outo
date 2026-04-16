"""
CapCut(剪映) 프로젝트 폴더 생성.
CapCut이 인식하는 폴더 구조 + draft_content.json 생성.

⚠️ 크래시 방지 규칙 (반드시 준수):
  - text segment: extra_material_refs = [] (speed/animation ref 금지)
  - audio segment: clip = None, enable_adjust = False
  - font path: 빈 문자열 금지 → _resolve_font() 사용
  - segment 생성: _make_segment(track_type=...) 필수
  - 상세: memory/project_capcut_solved.md
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


# CapCut 캐시 폰트 정보 (content.styles.font에 path+id 필수)
_CAPCUT_FONT: dict | None = None


def _load_capcut_font() -> dict:
    """CapCut 기본 캐시 폰트 정보 로드."""
    global _CAPCUT_FONT
    if _CAPCUT_FONT is not None:
        return _CAPCUT_FONT
    p = Path(__file__).parent.parent / "assets" / "capcut_default_font.json"
    if p.exists():
        _CAPCUT_FONT = json.loads(p.read_text(encoding="utf-8"))
    else:
        _CAPCUT_FONT = {}
    return _CAPCUT_FONT


def _resolve_font(_family: str) -> str:
    """CapCut용 폰트 경로 — 캐시 폰트 사용 (시스템 폰트 직접 참조 시 크래시)."""
    font_info = _load_capcut_font()
    return font_info.get("cache_path", "C:/Windows/Fonts/malgun.ttf")


def _resolve_content_font(_family: str) -> dict:
    """content.styles[0].font 객체 — path + id 필수."""
    font_info = _load_capcut_font()
    return dict(font_info.get("content_font", {"path": "C:/Windows/Fonts/malgun.ttf"}))


def _resolve_fonts_entry() -> dict:
    """materials.texts[].fonts[] 엔트리."""
    import copy as _copy
    font_info = _load_capcut_font()
    entry = _copy.deepcopy(font_info.get("fonts_entry", {}))
    entry["id"] = _uuid()  # 각 text마다 고유 ID
    return entry


def _uuid() -> str:
    return str(uuid.uuid4()).upper()


def _us(seconds: float) -> int:
    """초를 마이크로초로."""
    return int(seconds * 1_000_000)


# 샘플에서 추출한 스켈레톤들 (CapCut이 모든 키를 요구)
_SEG_SKELETON: dict = {}
_TXT_MAT_SKELETON: dict | None = None
_AUD_MAT_SKELETON: dict | None = None


def _load_text_mat_skeleton() -> dict:
    global _TXT_MAT_SKELETON
    if _TXT_MAT_SKELETON is None:
        p = Path(__file__).parent.parent / "assets" / "capcut_text_material_skeleton.json"
        if p.exists():
            _TXT_MAT_SKELETON = json.loads(p.read_text(encoding="utf-8"))
        else:
            _TXT_MAT_SKELETON = {}
    # 딥 카피 + 내부 참조 ID들 새로 생성 (CapCut은 각 text마다 고유 ID 요구)
    import copy
    result = copy.deepcopy(_TXT_MAT_SKELETON)
    # fonts 배열의 ID 갱신
    for f in result.get("fonts", []):
        f["id"] = _uuid()
    return result


def _load_audio_mat_skeleton() -> dict:
    global _AUD_MAT_SKELETON
    if _AUD_MAT_SKELETON is not None:
        return dict(_AUD_MAT_SKELETON)
    p = Path(__file__).parent.parent / "assets" / "capcut_audio_material_skeleton.json"
    if p.exists():
        _AUD_MAT_SKELETON = json.loads(p.read_text(encoding="utf-8"))
        return dict(_AUD_MAT_SKELETON)
    return {}


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


def _make_audio_aux_materials(materials: dict) -> list[str]:
    """오디오 segment에 필요한 보조 material 생성 — ID 목록 반환.
    CapCut은 오디오마다 beats, sound_channel_mapping, vocal_separation,
    placeholder_info를 요구함."""
    ids = []

    pid = _uuid()
    materials.setdefault("placeholder_infos", []).append({
        "error_path": "", "error_text": "", "id": pid,
        "meta_type": "none", "res_path": "", "res_text": "", "type": "placeholder_info",
    })
    ids.append(pid)

    bid = _uuid()
    materials.setdefault("beats", []).append({
        "ai_beats": {"beat_speed_infos": [], "beats_path": "", "beats_url": "",
                     "melody_path": "", "melody_percents": [0.0], "melody_url": ""},
        "enable_ai_beats": False, "gear": 404, "gear_count": 0,
        "id": bid, "mode": 404, "type": "beats",
        "user_beats": [], "user_delete_ai_beats": None,
    })
    ids.append(bid)

    scid = _uuid()
    materials.setdefault("sound_channel_mappings", []).append({
        "audio_channel_mapping": 0, "id": scid, "is_config_open": False, "type": "none",
    })
    ids.append(scid)

    vsid = _uuid()
    materials.setdefault("vocal_separations", []).append({
        "choice": 0, "enter_from": "", "final_algorithm": "", "id": vsid,
        "production_path": "", "removed_sounds": [], "time_range": None, "type": "vocal_separation",
    })
    ids.append(vsid)

    return ids


def _make_segment(
    material_id: str, start_us: int, duration_us: int,
    materials: dict,
    track_type: str = "video",
    render_index: int = 0,
    clip: dict | None = None,
    extra_refs: list | None = None,
    source_start: int = 0,
) -> dict:
    """CapCut segment 생성 — 트랙 타입별 스켈레톤 사용."""
    speed_id = _make_speed(materials)

    # 타입별 스켈레톤 로드
    p = Path(__file__).parent.parent / "assets" / "capcut_skeleton.json"
    type_skels = {}
    if p.exists():
        skel = json.loads(p.read_text(encoding="utf-8"))
        type_skels = skel.get("segment_by_type", {})

    base = dict(type_skels.get(track_type, type_skels.get("video", {})))

    # audio/video: speed + 보조 materials, text: 없음
    if track_type == "audio":
        aux_ids = _make_audio_aux_materials(materials)
        refs = [speed_id] + aux_ids + (extra_refs or [])
    elif track_type == "video":
        refs = [speed_id] + (extra_refs or [])
    else:
        refs = extra_refs or []

    base.update({
        "id": _uuid(),
        "material_id": material_id,
        "target_timerange": {"start": start_us, "duration": duration_us},
        "source_timerange": {"start": source_start, "duration": duration_us},
        "render_index": render_index,
        "speed": 1.0,
        "extra_material_refs": refs,
    })

    # clip은 트랙 타입에 따라: audio/effect → None, video/text → dict
    if clip is not None:
        base["clip"] = clip
    elif track_type in ("audio", "effect"):
        base["clip"] = None
    elif "clip" not in base or base.get("clip") is None:
        base["clip"] = {"transform": {"x": 0.0, "y": 0.0}, "scale": {"x": 1.0, "y": 1.0}, "rotation": 0.0, "alpha": 1.0, "flip": {"horizontal": False, "vertical": False}}

    return base


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

        # 기존 폴더가 CapCut에 의해 잠겨있을 수 있으므로 삭제 대신 덮어쓰기
        try:
            if project_dir.exists():
                shutil.rmtree(project_dir)
        except PermissionError:
            # CapCut이 파일을 잠그고 있음 → 새 이름으로 생성
            import datetime as _dt
            suffix = _dt.datetime.now().strftime("%H%M")
            project_dir = project_dir.parent / f"{safe_name}_{suffix}"
            if project_dir.exists():
                shutil.rmtree(project_dir, ignore_errors=True)
            logger.warning(f"CapCut 잠금 → 새 폴더: {project_dir.name}")
        project_dir.mkdir(parents=True, exist_ok=True)

        # 빈 폴더들
        for d in ["adjust_mask", "matting", "qr_upload", "smart_crop", "subdraft", "Resources", "common_attachment"]:
            (project_dir / d).mkdir(exist_ok=True)

        # GUID 폴더 (빈 폴더 3개)
        for _ in range(3):
            (project_dir / f"{{{_uuid()}}}").mkdir(exist_ok=True)

        # 반복 설정 적용
        repeat_cfg = state.get("repeat", {})
        repeat_mode = repeat_cfg.get("mode", "count")
        single_duration = sum(t.get("duration", 0) for t in tracks)

        if repeat_mode == "count":
            repeat_count = max(1, repeat_cfg.get("count", 1))
        elif repeat_mode == "duration" and single_duration > 0:
            target_sec = repeat_cfg.get("target_minutes", 60) * 60
            repeat_count = max(1, int(target_sec / single_duration))
        else:
            repeat_count = 1

        total_duration = single_duration * repeat_count
        total_us = _us(total_duration)
        logger.info(f"Repeat: {repeat_count}x, single={single_duration:.0f}s, total={total_duration:.0f}s")

        # draft_content.json 생성
        draft_content = self._build_draft_content(
            state, tracks, images, layers, subtitle_entries, total_us, project_name, project_dir,
            repeat_count=repeat_count, output_dir=output_dir,
        )
        # draft_content.json은 에셋 복사 후 경로 업데이트 뒤에 저장 (아래에서)

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

        # ── 에셋을 Resources 폴더에 모으기 ──
        resources_dir = project_dir / "Resources"
        resources_dir.mkdir(parents=True, exist_ok=True)

        # draft_content.json의 절대경로 → Resources 내 상대경로로 변환
        path_map: dict[str, str] = {}  # 원본절대경로 → Resources 내 파일명

        def _copy_asset(src_path: str, prefix: str = "") -> str:
            """에셋을 Resources에 복사하고 새 경로 반환."""
            src = Path(src_path)
            if not src.exists():
                return src_path
            dest_name = f"{prefix}{src.name}" if prefix else src.name
            dest = resources_dir / dest_name
            if not dest.exists():
                shutil.copy(src, dest)
            new_path = str(dest.resolve())
            path_map[src_path] = new_path
            return new_path

        # materials의 모든 경로를 Resources로 복사
        for mat in draft_content.get("materials", {}).get("videos", []):
            if mat.get("path"):
                mat["path"] = _copy_asset(mat["path"], "")
        for mat in draft_content.get("materials", {}).get("audios", []):
            if mat.get("path"):
                mat["path"] = _copy_asset(mat["path"], "")

        # draft_content 재저장 (경로 업데이트)
        (project_dir / "draft_content.json").write_text(
            json.dumps(draft_content, ensure_ascii=False), encoding="utf-8"
        )

        # 커버 이미지
        bg = images.get("background") or images.get("thumbnail")
        if bg and Path(bg).exists():
            try:
                shutil.copy(bg, project_dir / "draft_cover.jpg")
            except Exception:
                pass

        # 샘플 필수 파일들
        assets_dir = Path(__file__).parent.parent / "assets"
        for src_name, dst_name in [
            ("capcut_key_value.json", "key_value.json"),
            ("capcut_attachment_editing.json", "attachment_editing.json"),
            ("capcut_attachment_pc_common.json", "attachment_pc_common.json"),
        ]:
            src = assets_dir / src_name
            if src.exists():
                shutil.copy(src, project_dir / dst_name)

        # ZIP 생성 (Resources 폴더 포함)
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
        project_dir: Path = None, repeat_count: int = 1, output_dir: Path = None,
    ) -> dict:
        """draft_content.json — 실제 작동하는 샘플 템플릿 기반."""
        assets_dir = Path(__file__).parent.parent / "assets"

        # 샘플에서 추출한 전체 템플릿 로드 (구조가 CapCut과 100% 동일)
        tpl_path = assets_dir / "capcut_draft_template.json"
        if tpl_path.exists():
            base = json.loads(tpl_path.read_text(encoding="utf-8"))
        else:
            base = {"tracks": [], "materials": {}}

        materials = base.get("materials", {})
        track_list: list = []

        # canvas material (CapCut 필수)
        if not materials.get("canvases"):
            materials["canvases"] = [{
                "album_image": "", "blur": 0.0, "color": "", "id": _uuid(),
                "image": "", "image_id": "", "image_name": "",
                "source_platform": 0, "team_id": "", "type": "canvas_color",
            }]

        # ── 1. 배경 이미지 트랙 ──
        bg_path = images.get("background") or images.get("thumbnail")
        if bg_path and Path(bg_path).exists():
            vid_id = _uuid()
            materials["videos"].append({
                "id": vid_id,
                "path": str(Path(bg_path).resolve()),
                "type": "photo",
                "width": 1920,
                "height": 1080,
                "duration": total_us,
            })
            track_list.append({
                "type": "video",
                "attribute": 0, "flag": 0, "id": _uuid(), "is_default_name": True, "name": "",
                "segments": [_make_segment(vid_id, 0, total_us, materials, track_type="video", render_index=0)],
            })

        # ── 2. 효과 트랙 ──
        # 프론트엔드 프리뷰용 효과(firefly 등)는 CapCut 리소스 ID가 아니므로
        # CapCut 빌드에 포함하면 크래시 발생. CapCut에서 직접 추가해야 함.
        # (효과 레이어는 프리뷰 전용)

        # ── 3. 자막 트랙 (SRT) ──
        subtitle_enabled = layers.get("subtitle_enabled", True)
        if subtitle_entries and subtitle_enabled:
            sub_style = layers.get("subtitle_style", {})
            sub_segments = []
            for entry in subtitle_entries:
                txt_id = _uuid()
                font_size = sub_style.get("font_size", 15)
                font_family = sub_style.get("font_family", "")
                color = sub_style.get("color", "#FFFFFF")
                italic = sub_style.get("italic", False)
                shadow = sub_style.get("shadow", {})
                font_path = _resolve_font(font_family)
                content_font = _resolve_content_font(font_family)

                txt_mat = _load_text_mat_skeleton()
                txt_mat["fonts"] = [_resolve_fonts_entry()]
                txt_mat.update({
                    "id": txt_id,
                    "type": "text",
                    "content": json.dumps({
                        "text": entry["text"],
                        "styles": [{"font": content_font, "size": font_size,
                                    "fill": {"content": {"render_type": "solid", "solid": {"color": [1, 1, 1]}}},
                                    "range": [0, len(entry["text"])],
                                    "useLetterColor": True,
                                    "shadows": [{"thickness_projection_angle": -45, "thickness_projection_enable": False, "diffuse": 0.1, "alpha": shadow.get("alpha", 0.36), "distance": 0, "content": {"render_type": "solid", "solid": {"color": [0, 0, 0]}}, "angle": 0, "thickness_projection_distance": 0}],
                                    }],
                    }, ensure_ascii=False),
                    "font_size": float(font_size),
                    "font_path": font_path,
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
                materials["texts"].append(txt_mat)

                start_us = _us(entry["start"])
                dur_us = _us(entry["end"] - entry["start"])
                sub_segments.append(_make_segment(
                    txt_id, start_us, dur_us, materials, track_type="text", render_index=14000,
                    clip={"transform": {"x": 0.0, "y": 0.0}, "scale": {"x": 0.325, "y": 0.325}, "rotation": 0.0, "alpha": 1.0, "flip": {"horizontal": False, "vertical": False}},
                    extra_refs=[],
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
            shadow = tl.get("shadow", {})
            font_path = _resolve_font(tl.get("font_family", ""))
            content_font = _resolve_content_font(tl.get("font_family", ""))

            txt_mat = _load_text_mat_skeleton()
            txt_mat["fonts"] = [_resolve_fonts_entry()]
            txt_mat.update({
                "id": txt_id,
                "type": "text",
                "content": json.dumps({
                    "text": tl.get("text", ""),
                    "styles": [{"font": content_font, "size": tl.get("font_size", 15),
                                "fill": {"content": {"render_type": "solid", "solid": {"color": [1, 1, 1]}}},
                                "range": [0, len(tl.get("text", ""))],
                                "useLetterColor": True,
                                "shadows": [{"thickness_projection_angle": -45, "thickness_projection_enable": False, "diffuse": 0.1, "alpha": shadow.get("alpha", 0.86), "distance": 0, "content": {"render_type": "solid", "solid": {"color": [0, 0, 0]}}, "angle": 0, "thickness_projection_distance": 0}],
                                }],
                }, ensure_ascii=False),
                "font_size": float(tl.get("font_size", 15)),
                "font_path": font_path,
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
            materials["texts"].append(txt_mat)

            track_list.append({
                "type": "text",
                "attribute": 0, "flag": 0, "id": _uuid(), "is_default_name": True, "name": "",
                "segments": [_make_segment(
                    txt_id, 0, total_us, materials, track_type="text", render_index=14000,
                    clip={
                        "transform": {"x": tl.get("position_x", 0.5) * 2 - 1, "y": tl.get("position_y", 0.5) * 2 - 1},
                        "scale": {"x": tl.get("scale_x", 0.25), "y": tl.get("scale_y", 0.25)},
                        "rotation": 0.0, "alpha": 1.0, "flip": {"horizontal": False, "vertical": False},
                    },
                    extra_refs=[],
                )],
            })

        # ── 5. 오디오 트랙 (반복 적용) ──
        audio_segments = []
        time_offset = 0

        # audio material은 1세트만 생성 (반복 시 같은 material 재사용)
        audio_mats: list[tuple[str, float]] = []  # (material_id, duration_sec)
        for track in tracks:
            audio_path = track.get("stored_path", "")
            if not audio_path or not Path(audio_path).exists():
                continue
            aud_id = _uuid()
            dur = track.get("duration", 0)
            dur_us = _us(dur)
            res_path = str(Path(audio_path).resolve())
            aud_mat = _load_audio_mat_skeleton()
            aud_mat.update({
                "id": aud_id,
                "path": res_path,
                "duration": dur_us,
                "type": "extract_music",
                "name": track.get("title", ""),
            })
            materials["audios"].append(aud_mat)
            audio_mats.append((aud_id, dur))

        # repeat_count만큼 반복 배치
        for _rep in range(repeat_count):
            for aud_id, dur in audio_mats:
                dur_us = _us(dur)
                audio_segments.append(_make_segment(
                    aud_id, _us(time_offset), dur_us, materials, track_type="audio", render_index=0,
                ))
                time_offset += dur

        if audio_segments:
            track_list.append({
                "type": "audio",
                "attribute": 0, "flag": 0, "id": _uuid(), "is_default_name": True, "name": "",
                "segments": audio_segments,
            })

        # ── 6. 파형 비디오 레이어 (사전 생성된 MOV 반복 배치) ──
        # assets/waveform_loop.mov가 있을 때만 포함 (없으면 건너뜀)
        wf_mov = None
        if state.get("id"):
            from config import settings as _s
            assets_dir = _s.storage_dir / "projects" / state["id"] / "assets"
            candidate = assets_dir / "waveform_loop.mov"
            if candidate.exists():
                wf_mov = candidate

        if wf_mov:
            wf_id = _uuid()
            wf_path = str(wf_mov.resolve())
            # 파형 MOV는 항상 정확히 10초 (waveform_generator가 보장)
            loop_us = 10_000_000

            materials["videos"].append({
                "id": wf_id,
                "path": wf_path,
                "type": "video",
                "width": 1920,
                "height": 1080,
                "duration": loop_us,
            })

            # 전체 오디오 길이에 맞게 반복 배치 (갭 0)
            wf_segments = []
            cursor = 0
            while cursor < total_us:
                seg_dur = min(loop_us, total_us - cursor)
                wf_segments.append(_make_segment(
                    wf_id, cursor, seg_dur, materials, track_type="video",
                    render_index=1,
                    clip={
                        "alpha": 1.0,
                        "flip": {"horizontal": False, "vertical": False},
                        "rotation": 0.0,
                        "scale": {"x": 1.0, "y": 1.0},
                        "transform": {"x": 0.0, "y": 0.0},
                    },
                ))
                cursor += loop_us

            track_list.append({
                "type": "video",
                "attribute": 0, "flag": 0, "id": _uuid(),
                "is_default_name": True, "name": "waveform",
                "segments": wf_segments,
            })

        # ── 7. 이미지/로고 레이어 트랙 (타임라인 자동 배치) ──
        image_layers = layers.get("image_layers", [])
        for il in image_layers:
            img_path = il.get("stored_path", "")
            if not img_path or not Path(img_path).exists():
                continue
            img_id = _uuid()
            res_path = str(Path(img_path).resolve())
            materials["videos"].append({
                "id": img_id,
                "path": res_path,
                "type": "photo",
                "width": 1920,
                "height": 1080,
                "duration": total_us,
            })
            # 위치/크기를 CapCut 좌표로 변환 (0~1 → -1~1)
            pos_x = il.get("position_x", 0.5) * 2 - 1
            pos_y = il.get("position_y", 0.5) * 2 - 1
            scale = il.get("scale", 1.0) * 0.3  # 프리뷰 스케일 → CapCut 스케일
            track_list.append({
                "type": "video",
                "attribute": 0, "flag": 0, "id": _uuid(), "is_default_name": True, "name": "",
                "segments": [_make_segment(
                    img_id, 0, total_us, materials, track_type="video", render_index=2,
                    clip={
                        "alpha": il.get("opacity", 1.0),
                        "flip": {"horizontal": False, "vertical": False},
                        "rotation": 0.0,
                        "scale": {"x": scale, "y": scale},
                        "transform": {"x": pos_x, "y": pos_y},
                    },
                )],
            })

        # 템플릿 유지 + 우리 데이터만 교체
        base["tracks"] = track_list
        base["materials"] = materials
        base["duration"] = total_us
        base["id"] = state.get("id", _uuid())
        base["name"] = project_name
        base["create_time"] = int(time.time())
        return base


capcut_builder = CapcutBuilder()
