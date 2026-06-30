"""Music Outo 로컬 실행 진입점.

PyInstaller 로 단일 EXE 로 묶이는 스크립트.
- uvicorn 서버를 백그라운드 스레드에서 시작
- 시스템 트레이 아이콘 (pystray) — 우클릭 메뉴: 열기 / 종료
- 시작 시 기본 브라우저 자동 오픈

개발 시에는 그냥 `python run_local.py` 로도 동일하게 동작.
"""
from __future__ import annotations

import sys
import threading
import time
import os
import webbrowser
from pathlib import Path

PORT = 8000
URL = f"http://localhost:{PORT}"


def _ensure_std_streams() -> None:
    """콘솔 없는(windowed) EXE 에서 표준 출력/에러를 로그 파일로 연결.

    PyInstaller windowed 빌드(console=False)에서는 sys.stdout/sys.stderr 가
    None 이다. 이 상태로 uvicorn/logging 이 출력하려 하면 예외가 나면서
    서버 스레드가 조용히 죽어버린다(=화면이 안 뜸). EXE 옆 music-outo.log 로
    출력을 돌려서 이를 막고, 동시에 문제 발생 시 들여다볼 로그도 남긴다.
    """
    if sys.stdout is not None and sys.stderr is not None:
        return
    try:
        log_dir = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent
        f = open(log_dir / "music-outo.log", "a", encoding="utf-8", buffering=1)
        if sys.stdout is None:
            sys.stdout = f
        if sys.stderr is None:
            sys.stderr = f
    except Exception:
        import io
        if sys.stdout is None:
            sys.stdout = io.StringIO()
        if sys.stderr is None:
            sys.stderr = io.StringIO()


def _add_bundled_ffmpeg_to_path() -> None:
    """EXE(frozen) 환경에서 함께 묶인 ffmpeg/ffprobe 를 PATH 앞에 추가.

    받는 PC 에 ffmpeg 가 설치돼 있지 않아도 영상 빌드(packager)·mp3 교정·
    파형 분석이 동작하도록 한다. 일반 python 실행 때는 시스템 ffmpeg 를 쓰므로 건너뜀.
    """
    if not getattr(sys, "frozen", False):
        return
    base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    ffmpeg_dir = base / "ffmpeg"
    if ffmpeg_dir.exists():
        os.environ["PATH"] = str(ffmpeg_dir) + os.pathsep + os.environ.get("PATH", "")


def _open_browser(url: str = URL) -> None:
    """Windows 우선 os.startfile → 실패 시 webbrowser fallback.
    PyInstaller frozen 환경에서 webbrowser.open 이 침묵 실패하는 경우 대비."""
    try:
        if sys.platform == "win32":
            os.startfile(url)  # type: ignore[attr-defined]
            return
    except Exception:
        pass
    try:
        webbrowser.open(url)
    except Exception:
        pass


def _ensure_cwd_on_path():
    """PyInstaller 환경에서도 main.py 가 import 되도록 sys.path 보정."""
    here = Path(__file__).parent
    if str(here) not in sys.path:
        sys.path.insert(0, str(here))


def _run_server() -> None:
    import uvicorn

    # reload 는 EXE 환경에서 안 씀. log_level info.
    uvicorn.run("main:app", host="127.0.0.1", port=PORT, log_level="info")


def _wait_for_server(timeout: float = 30.0) -> bool:
    """/health 가 200 OK 떨어질 때까지 폴링."""
    import urllib.error
    import urllib.request

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{URL}/health", timeout=1) as r:
                if r.status == 200:
                    return True
        except (urllib.error.URLError, ConnectionError, TimeoutError):
            pass
        time.sleep(0.5)
    return False


def _start_tray_icon() -> None:
    """시스템 트레이 아이콘. pystray 미설치면 콘솔 대기로 fallback."""
    try:
        from PIL import Image
        import pystray
    except ImportError:
        # pystray/Pillow 없으면 그냥 무한 대기 (Ctrl+C 로 종료)
        try:
            while True:
                time.sleep(60)
        except KeyboardInterrupt:
            return
        return

    # 24x24 보라색 사각형 (간단한 placeholder)
    icon_img = Image.new("RGB", (24, 24), "#7c3aed")

    def on_open(icon, item):
        _open_browser()

    def on_quit(icon, item):
        icon.stop()
        # uvicorn 스레드는 daemon 이라 메인 종료 시 같이 죽음
        sys.exit(0)

    menu = pystray.Menu(
        pystray.MenuItem("브라우저에서 열기", on_open, default=True),
        pystray.MenuItem("종료", on_quit),
    )
    icon = pystray.Icon("music-outo", icon_img, "Music Outo", menu)
    icon.run()


def main() -> None:
    _ensure_std_streams()          # 콘솔 없는 EXE 에서 로깅 충돌 방지 (가장 먼저)
    _ensure_cwd_on_path()
    _add_bundled_ffmpeg_to_path()  # 동봉 ffmpeg 를 PATH 에 (서버 임포트 전에 먼저)

    # uvicorn 을 백그라운드 스레드로
    server_thread = threading.Thread(target=_run_server, daemon=True)
    server_thread.start()

    # 서버 부팅 대기 후 브라우저 오픈
    if _wait_for_server(timeout=30):
        _open_browser()
    else:
        # 서버가 안 떴으면 그래도 트레이는 띄움 — 사용자가 로그 보고 종료할 수 있게
        pass

    # 메인 스레드는 트레이 아이콘이 점유 (Windows GUI 이벤트 루프 필요)
    _start_tray_icon()


if __name__ == "__main__":
    main()
