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
import webbrowser
from pathlib import Path

PORT = 8000
URL = f"http://localhost:{PORT}"


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
        webbrowser.open(URL)

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
    _ensure_cwd_on_path()

    # uvicorn 을 백그라운드 스레드로
    server_thread = threading.Thread(target=_run_server, daemon=True)
    server_thread.start()

    # 서버 부팅 대기 후 브라우저 오픈
    if _wait_for_server(timeout=30):
        webbrowser.open(URL)
    else:
        # 서버가 안 떴으면 그래도 트레이는 띄움 — 사용자가 로그 보고 종료할 수 있게
        pass

    # 메인 스레드는 트레이 아이콘이 점유 (Windows GUI 이벤트 루프 필요)
    _start_tray_icon()


if __name__ == "__main__":
    main()
