"""
프로젝트 상태를 JSON 파일로 관리하는 싱글톤 매니저.
DB 없음 — storage/projects/{id}/state.json 이 유일한 진실의 원천.
"""
from __future__ import annotations

import json
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from config import settings


class ProjectStateManager:
    def __init__(self):
        self._root = settings.projects_path
        # 프로젝트별 쓰기 락 (같은 프로세스 내 동시 update 직렬화)
        import threading
        self._locks: dict[str, threading.Lock] = {}
        self._locks_mutex = threading.Lock()

    def _get_lock(self, project_id: str):
        import threading
        with self._locks_mutex:
            lock = self._locks.get(project_id)
            if lock is None:
                lock = threading.Lock()
                self._locks[project_id] = lock
            return lock

    # ──────────────────────── internal helpers ────────────────────────

    def _dir(self, project_id: str) -> Path:
        return self._root / project_id

    def _state_file(self, project_id: str) -> Path:
        return self._dir(project_id) / "state.json"

    def _load(self, project_id: str) -> Optional[dict]:
        f = self._state_file(project_id)
        if not f.exists():
            return None
        with open(f, "r", encoding="utf-8") as fp:
            return json.load(fp)

    def _save(self, project_id: str, state: dict) -> None:
        """원자적 쓰기 + 락 — 동시 쓰기 시 JSON 파일 손상 방지.

        write(*.tmp) → os.replace(tmp, state.json)로 원자적 교체.
        같은 프로세스 내 동시 update는 프로젝트별 락으로 직렬화.
        """
        import os
        f = self._state_file(project_id)
        lock = self._get_lock(project_id)
        with lock:
            tmp = f.with_suffix(".json.tmp")
            with open(tmp, "w", encoding="utf-8") as fp:
                json.dump(state, fp, ensure_ascii=False, indent=2)
            os.replace(tmp, f)

    @staticmethod
    def _now() -> str:
        return datetime.utcnow().isoformat()

    # ──────────────────────── public API ────────────────────────

    def create(self, name: str, playlist_title: str = "") -> dict:
        pid = str(uuid.uuid4())
        d = self._dir(pid)
        d.mkdir(parents=True, exist_ok=True)
        (d / "audio").mkdir(exist_ok=True)
        (d / "images").mkdir(exist_ok=True)
        (d / "outputs").mkdir(exist_ok=True)

        state = {
            "id": pid,
            "user_id": "default",
            "name": name,
            "playlist_title": playlist_title,
            "created_at": self._now(),
            "updated_at": self._now(),
            "status": "setup",
            "tracks": [],
            "images": {"thumbnail": None, "background": None, "additional": []},
            "metadata": {"title": None, "description": None, "tags": [], "comment": None},
            "layers": {"background_video": None, "waveform_layer": None, "text_layers": []},
            "build": {"status": None, "output_file": None, "capcut_file": None, "error": None, "progress": 0},
            "youtube": {"video_id": None, "url": None, "uploaded_at": None},
            "repeat": {"mode": "count", "count": 1, "target_minutes": 60},
            "image_mood": None,
        }
        self._save(pid, state)
        return state

    def get(self, project_id: str) -> Optional[dict]:
        return self._load(project_id)

    # 목록 조회 시 제외할 무거운 필드
    _HEAVY_KEYS = {"designed_tracks", "suno_tracks", "subtitle_entries", "benchmark_data"}

    def list_all(self, summary: bool = False) -> list[dict]:
        if not self._root.exists():
            return []
        projects = []
        for d in self._root.iterdir():
            if d.is_dir():
                s = self._load(d.name)
                if s:
                    if summary:
                        s = {k: v for k, v in s.items() if k not in self._HEAVY_KEYS}
                    projects.append(s)
        projects.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
        return projects

    def update(self, project_id: str, updates: dict) -> Optional[dict]:
        # read-modify-write 구간을 락으로 감싸 lost-update 방지
        lock = self._get_lock(project_id)
        with lock:
            state = self._load(project_id)
            if state is None:
                return None
            _deep_update(state, updates)
            state["updated_at"] = self._now()
            # _save 내부의 락 재진입 — threading.Lock은 non-reentrant이므로
            # 중복 획득 방지 위해 내부 _save를 우회하고 직접 원자 쓰기
            import os
            f = self._state_file(project_id)
            tmp = f.with_suffix(".json.tmp")
            with open(tmp, "w", encoding="utf-8") as fp:
                json.dump(state, fp, ensure_ascii=False, indent=2)
            os.replace(tmp, f)
        return state

    def delete(self, project_id: str) -> bool:
        d = self._dir(project_id)
        if d.exists():
            shutil.rmtree(d)
            return True
        return False

    def project_dir(self, project_id: str) -> Path:
        return self._dir(project_id)

    def require(self, project_id: str) -> dict:
        """get() + 없으면 404 raise."""
        from fastapi import HTTPException
        s = self._load(project_id)
        if s is None:
            raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
        return s


def _deep_update(base: dict, new: dict) -> None:
    for k, v in new.items():
        if isinstance(v, dict) and k in base and isinstance(base[k], dict):
            _deep_update(base[k], v)
        else:
            base[k] = v


state_manager = ProjectStateManager()
