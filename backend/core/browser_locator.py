"""
Edge/Chrome 실행 파일 위치 단일 출처.

여러 모듈(browser_manager, suno_automation, suno_recorder, suno_api, routes/suno,
routes/youtube) 에 같은 경로 리스트가 흩어져 있어서 ① 새 설치 위치가 추가되면
6곳 수정 필요 ② macOS/Linux 지원이 모듈마다 제각각 인 문제 해결.

전부 이 모듈에서 import 한다.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Optional


# ─── 플랫폼별 후보 경로 ─────────────────────────────────────────────────────

def _windows_edge_candidates() -> list[Path]:
    """Windows 표준 Edge/Chrome 설치 경로 후보."""
    return [
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
    ]


def _macos_candidates() -> list[Path]:
    return [
        Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
        Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
    ]


def _linux_path_lookup() -> list[Path]:
    """Linux 는 PATH 에서 찾는다."""
    found: list[Path] = []
    for name in ("microsoft-edge", "microsoft-edge-stable", "google-chrome", "chromium", "chromium-browser"):
        which = shutil.which(name)
        if which:
            found.append(Path(which))
    return found


def _candidates() -> list[Path]:
    if sys.platform == "win32":
        return _windows_edge_candidates()
    if sys.platform == "darwin":
        return _macos_candidates()
    return _linux_path_lookup()


# ─── 공개 API ────────────────────────────────────────────────────────────────

def find_browser() -> Optional[Path]:
    """Edge 우선, Chrome fallback. 첫 번째로 존재하는 실행 파일 반환.

    못 찾으면 None — 사용처는 사용자에게 'Edge/Chrome 설치 후 다시 시도' 안내.
    """
    for candidate in _candidates():
        if candidate.exists():
            return candidate
    return None


def find_browser_str() -> Optional[str]:
    """find_browser() 의 문자열 버전. 기존 코드와의 호환을 위해."""
    p = find_browser()
    return str(p) if p else None


# 후보 리스트(하위 호환) — 기존 코드들이 임시로 import 해서 쓸 수 있도록
EDGE_CANDIDATES_WIN: list[str] = [str(p) for p in _windows_edge_candidates()]


def kill_running_edge() -> None:
    """현재 떠 있는 Edge/Chrome 프로세스를 모두 종료.

    youtube.py 의 'CDP 디버그 포트로 띄울 때 기존 Edge 정리' 용도.
    플랫폼별로 적절한 명령 사용.
    """
    if sys.platform == "win32":
        os.system('taskkill /F /IM msedge.exe >nul 2>&1')
    elif sys.platform == "darwin":
        os.system('pkill -f "Microsoft Edge" 2>/dev/null')
    else:
        os.system('pkill -f microsoft-edge 2>/dev/null')
