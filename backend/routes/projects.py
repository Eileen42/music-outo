import json
import logging
import os
import re
import subprocess
import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException
from models.schemas import ProjectCreate, ProjectUpdate
from config import settings
from core.state_manager import state_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/projects", tags=["프로젝트"])


# ─────────────────── 음악 폴더 열기 (재활용용 friendly 정션) ───────────────────

# 윈도우 파일명에 못 쓰는 문자 + 양 끝 공백/. 정리.
_INVALID_NAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _sanitize_name(s: str) -> str:
    s = _INVALID_NAME_CHARS.sub("_", s or "").strip().rstrip(".")
    return s[:80] or "unnamed"


def _build_folder_label(state: dict) -> str:
    """폴더 라벨: YYMMDD_채널명_프로젝트명. 사람이 보고 구분할 수 있도록.

    채널명은 `storage/channels/{channel_id}.json` 의 `name` (한글 가능),
    날짜는 `state.created_at` ISO 문자열 앞 10글자(YYYY-MM-DD)에서 YYMMDD 추출.
    어느 한 조각이 비어도 가능한 부분만 이어 붙인다.
    """
    created = (state.get("created_at") or "")[:10]
    yymmdd = ""
    if len(created) == 10 and created[4] == "-" and created[7] == "-":
        yymmdd = created[2:4] + created[5:7] + created[8:10]

    channel_id = state.get("channel_id") or ""
    channel_name = channel_id  # fallback
    if channel_id:
        ch_path = settings.storage_dir / "channels" / f"{channel_id}.json"
        if ch_path.exists():
            try:
                ch = json.loads(ch_path.read_text(encoding="utf-8"))
                channel_name = ch.get("name") or channel_id
            except Exception:
                pass

    project_name = state.get("name") or "unnamed"

    parts = [p for p in (yymmdd, _sanitize_name(channel_name), _sanitize_name(project_name)) if p]
    return "_".join(parts) or state.get("id", "unknown")[:8]


_PID_MARKER = "_project.txt"  # 라벨 폴더 안에 두는 프로젝트 식별 파일


def _ensure_friendly_folder(project_id: str, state: dict) -> Path:
    """`storage/downloads/{label}/{set_A,set_B}/` 구조로 mp3 를 깔끔히 정리.

    설계 원칙:
    - 원본 `storage/projects/{uuid}/tracks/` 는 그대로 둠 → 기존 코드 모두 무영향.
    - downloads 하위는 **하드링크**로 동기화. 같은 NTFS 볼륨이면 추가 디스크 소비 0,
      원본 파일을 절대 변형하지 않음 (복사도 아니라 inode 공유). 다른 볼륨이거나
      하드링크 실패 시 안전 복사(shutil.copy2)로 폴백.
    - 슬롯 1 → set_A/, 슬롯 2 → set_B/ 로 분리. 사용자가 곡당 두 버전 중 하나를
      골라 다른 프로젝트에 재활용하기 쉽게.
    - 파일명은 `{idx:02d}_{title}.mp3` (원본의 _v1/_v2 suffix 제거).
    - 이름이 바뀐 옛 라벨 폴더는 stale 표시(_project.txt 의 project_id 일치)로 찾아 정리.
    - 매 호출마다 desired set 과 실제 set 을 비교해 sync (트랙 삭제/추가에 즉시 반응).

    return: 라벨 폴더 경로 (열기 대상). 이 폴더 안에 set_A/set_B/_project.txt 가 있다.
    """
    import shutil

    actual_tracks = settings.storage_dir / "projects" / project_id / "tracks"
    actual_tracks.mkdir(parents=True, exist_ok=True)

    downloads_root = settings.storage_dir / "downloads"
    downloads_root.mkdir(exist_ok=True)

    label = _build_folder_label(state)
    target = downloads_root / label

    # 같은 project_id 를 가리키지만 라벨이 바뀐 옛 폴더 정리 (이름·채널 변경 후 stale).
    # 폴더가 정션이면 단순 rmdir 로 끊고, 일반 폴더면 _project.txt 마커 일치하면 통째 삭제.
    for existing in list(downloads_root.iterdir()):
        if existing.name == label or not existing.is_dir():
            continue
        try:
            marker = existing / _PID_MARKER
            if marker.exists() and marker.read_text(encoding="utf-8").strip() == project_id:
                shutil.rmtree(existing, ignore_errors=True)
                logger.info(f"stale 라벨 폴더 제거: {existing.name}")
                continue
            # 옛 버전이 만든 디렉터리 정션도 정리 — 같은 tracks/ 를 가리키면 끊는다.
            try:
                if existing.is_dir() and existing.resolve() == actual_tracks.resolve():
                    existing.rmdir()
                    logger.info(f"stale 정션 제거: {existing.name}")
            except OSError:
                pass
        except OSError:
            pass

    target.mkdir(exist_ok=True)
    (target / _PID_MARKER).write_text(project_id, encoding="utf-8")

    set_a = target / "set_A"
    set_b = target / "set_B"
    set_a.mkdir(exist_ok=True)
    set_b.mkdir(exist_ok=True)

    # 슬롯별로 보내야 할 파일 set 계산
    suno_tracks = state.get("suno_tracks") or []
    desired: dict[str, dict[str, Path]] = {"set_A": {}, "set_B": {}}
    for t in suno_tracks:
        if t.get("status") != "completed":
            continue
        fp = t.get("file_path", "")
        if not fp:
            continue
        src = Path(fp)
        if not src.exists():
            continue
        slot = t.get("slot")
        idx = t.get("index", 0)
        title = _sanitize_name(t.get("title", "untitled"))
        clean_name = f"{idx:02d}_{title}.mp3"
        if slot == 1:
            desired["set_A"][clean_name] = src
        elif slot == 2:
            desired["set_B"][clean_name] = src

    # 동기화: 각 set 폴더의 실제 내용을 desired 와 맞춤
    linked = {"set_A": 0, "set_B": 0}
    copied = {"set_A": 0, "set_B": 0}
    for set_name, set_dir in (("set_A", set_a), ("set_B", set_b)):
        wanted = desired[set_name]
        # 더이상 필요없는 파일 제거
        for existing in list(set_dir.iterdir()):
            if existing.name not in wanted:
                try:
                    existing.unlink()
                except OSError:
                    pass
        # 하드링크 생성 (이미 같은 inode 면 스킵)
        for name, src in wanted.items():
            dst = set_dir / name
            try:
                if dst.exists():
                    # 같은 inode 면 OK, 다르면 재링크
                    same = False
                    try:
                        same = dst.stat().st_ino == src.stat().st_ino and dst.stat().st_size == src.stat().st_size
                    except OSError:
                        same = False
                    if same:
                        continue
                    dst.unlink()
                # 우선 하드링크 시도
                try:
                    os.link(src, dst)
                    linked[set_name] += 1
                except OSError:
                    # 다른 볼륨 / 권한 / 기타 → 복사로 폴백 (원본 손상 없음)
                    shutil.copy2(src, dst)
                    copied[set_name] += 1
            except OSError as e:
                logger.warning(f"set 동기화 실패 {set_name}/{name}: {e}")

    logger.info(
        f"[open-folder] {label}: set_A={len(desired['set_A'])} "
        f"(link {linked['set_A']}, copy {copied['set_A']}), "
        f"set_B={len(desired['set_B'])} "
        f"(link {linked['set_B']}, copy {copied['set_B']})"
    )

    return target


@router.post("/{project_id}/open-folder", summary="음악 파일 폴더 열기 (탐색기)")
async def open_project_folder(project_id: str):
    """프로젝트의 다운로드된 음악 mp3 폴더를 OS 탐색기로 연다.

    `storage/downloads/{YYMMDD_채널명_프로젝트명}/` 정션을 자동 생성·갱신해서
    사람이 보기 쉬운 이름으로 폴더 목록을 정리한 뒤, 그 폴더를 연다.
    원본 mp3 는 `storage/projects/{uuid}/tracks/` 그대로 — 정션은 링크일 뿐.
    """
    state = state_manager.require(project_id)
    folder = _ensure_friendly_folder(project_id, state)

    try:
        if sys.platform == "win32":
            os.startfile(str(folder))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(folder)])
        else:
            subprocess.Popen(["xdg-open", str(folder)])
    except Exception as e:
        # 폴더 자체는 만들어졌으니 경로만이라도 돌려준다 — 사용자가 수동 열기 가능.
        logger.warning(f"폴더 자동 열기 실패: {e}")
        return {"folder": str(folder), "label": folder.name, "opened": False, "error": str(e)}

    return {"folder": str(folder), "label": folder.name, "opened": True}


@router.post("", summary="프로젝트 생성")
async def create_project(body: ProjectCreate):
    state = state_manager.create(name=body.name, playlist_title=body.playlist_title)
    return state


@router.get("", summary="프로젝트 목록 조회")
async def list_projects():
    return state_manager.list_all(summary=True)


@router.get("/{project_id}", summary="프로젝트 상세 조회")
async def get_project(project_id: str):
    return state_manager.require(project_id)


@router.patch("/{project_id}", summary="프로젝트 수정")
async def update_project(project_id: str, body: ProjectUpdate):
    updates = body.model_dump(exclude_none=True)
    # RepeatConfig pydantic 객체 → dict 변환
    if "repeat" in updates and hasattr(updates["repeat"], "model_dump"):
        updates["repeat"] = updates["repeat"].model_dump()
    state = state_manager.update(project_id, updates)
    if state is None:
        raise HTTPException(404, "프로젝트를 찾을 수 없습니다")
    return state


@router.delete("/{project_id}", summary="프로젝트 삭제")
async def delete_project(project_id: str):
    ok = state_manager.delete(project_id)
    if not ok:
        raise HTTPException(404, "프로젝트를 찾을 수 없습니다")
    return {"deleted": project_id}
