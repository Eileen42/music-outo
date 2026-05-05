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


def _ensure_friendly_junction(project_id: str, state: dict) -> Path:
    """`storage/downloads/{label}/` 정션이 프로젝트의 tracks/ 폴더를 가리키도록 보장.

    - 기존 UUID 폴더(`storage/projects/{uuid}/tracks/`)는 그대로 둠 → 모든 코드 무영향.
    - 정션은 cmd `mklink /J` (관리자 권한 불필요, 디렉터리 전용 junction) 로 생성.
    - 같은 프로젝트의 옛 라벨 정션은 정리 (이름 변경/채널 변경 후 stale 정션 제거).
    - 윈도우 외 OS 는 심볼릭 링크로 폴백.

    return: 정션 경로 (열기 대상)
    """
    actual = settings.storage_dir / "projects" / project_id / "tracks"
    actual.mkdir(parents=True, exist_ok=True)

    downloads_root = settings.storage_dir / "downloads"
    downloads_root.mkdir(exist_ok=True)

    label = _build_folder_label(state)
    target = downloads_root / label

    # 같은 프로젝트를 가리키는 다른 라벨 정션 정리 (stale).
    # 정션을 readlink 로 풀어 actual 와 같은지 비교.
    actual_resolved = actual.resolve()
    for existing in downloads_root.iterdir():
        if existing.name == label or not existing.is_dir():
            continue
        try:
            if existing.resolve() == actual_resolved:
                # 정션만 끊어내야 안전. rmdir 은 디렉터리 정션을 안전하게 끊음.
                # 실파일이 들어찬 디렉터리라도 정션은 링크만 제거되고 실데이터는 보존.
                existing.rmdir()
                logger.info(f"stale 정션 제거: {existing.name}")
        except OSError:
            pass

    if target.exists():
        # 이미 올바른 라벨 정션이 있는 경우. 그대로 사용.
        return target

    if sys.platform == "win32":
        # mklink /J 는 관리자 권한 없이 디렉터리 정션 생성. /D 는 심볼릭 링크라 권한 필요.
        proc = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(target), str(actual)],
            capture_output=True, text=True,
        )
        if proc.returncode != 0:
            raise HTTPException(500, f"폴더 정션 생성 실패: {proc.stderr.strip() or proc.stdout.strip()}")
    else:
        os.symlink(actual, target)

    return target


@router.post("/{project_id}/open-folder", summary="음악 파일 폴더 열기 (탐색기)")
async def open_project_folder(project_id: str):
    """프로젝트의 다운로드된 음악 mp3 폴더를 OS 탐색기로 연다.

    `storage/downloads/{YYMMDD_채널명_프로젝트명}/` 정션을 자동 생성·갱신해서
    사람이 보기 쉬운 이름으로 폴더 목록을 정리한 뒤, 그 폴더를 연다.
    원본 mp3 는 `storage/projects/{uuid}/tracks/` 그대로 — 정션은 링크일 뿐.
    """
    state = state_manager.require(project_id)
    folder = _ensure_friendly_junction(project_id, state)

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
