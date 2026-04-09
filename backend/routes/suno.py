"""
Suno 브라우저 세션 관리 API.

로그인 흐름:
  POST /api/suno/login/open    → Edge를 일반 프로세스로 실행 (자동화 감지 없음)
  POST /api/suno/login/confirm → Playwright가 CDP로 연결해 세션 저장
  GET  /api/suno/status        → 세션 파일 존재 여부
  DELETE /api/suno/session     → 세션 삭제

핵심:
  - Edge를 subprocess로 직접 실행 (Playwright launch 아님)
    → navigator.webdriver=false, 자동화 플래그 없음
    → Google OAuth 차단 없음
  - 로그인 후 Playwright가 CDP로 접속만 해서 쿠키 저장
"""
from __future__ import annotations

import asyncio
import logging
import subprocess
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException
from playwright.async_api import async_playwright, Browser, BrowserContext, Playwright

from config import settings
import browser.suno_recorder as recorder

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/suno", tags=["suno"])

_login_state: dict = {
    "playwright":  None,
    "browser":     None,   # CDP 연결된 Browser (confirm 시 생성)
    "edge_proc":   None,   # subprocess.Popen
    "status":      "idle",
    "error":       "",
}

_SESSION_NAME = "suno"
_DEBUG_PORT    = 9222

_EDGE_EXES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]

_LOGGED_IN_SELECTORS = [
    "[data-testid='credits']",
    "[class*='credits']",
    "[href='/account']",
    "[data-testid='user-avatar']",
    "button[aria-label*='Account']",
    "img[alt*='profile']",
    "img[alt*='avatar']",
]


def _session_path() -> Path:
    return settings.browser_sessions_dir / f"{_SESSION_NAME}_context.json"


def _suno_profile_dir() -> Path:
    d = settings.browser_sessions_dir / "suno_edge_profile"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _find_edge() -> str | None:
    for p in _EDGE_EXES:
        if Path(p).exists():
            return p
    return None


def _kill_debug_edge() -> None:
    """9222 포트를 쓰는 Edge 디버그 인스턴스만 종료."""
    try:
        result = subprocess.run(
            ["powershell", "-Command",
             f"Get-NetTCPConnection -LocalPort {_DEBUG_PORT} -ErrorAction SilentlyContinue "
             "| Select-Object -ExpandProperty OwningProcess"],
            capture_output=True, text=True, timeout=5,
        )
        pid = result.stdout.strip()
        if pid and pid.isdigit():
            subprocess.run(["taskkill", "/f", "/pid", pid], capture_output=True, timeout=5)
            time.sleep(1)
            logger.info(f"기존 디버그 Edge 종료 (PID {pid})")
    except Exception as e:
        logger.warning(f"디버그 Edge 종료 실패 (무시): {e}")


async def _check_logged_in_via_cdp(pw: Playwright) -> BrowserContext | None:
    """CDP로 Edge에 연결해 suno.com 로그인 여부 확인."""
    try:
        browser = await pw.chromium.connect_over_cdp(f"http://localhost:{_DEBUG_PORT}")
        _login_state["browser"] = browser

        # 기존 컨텍스트 사용
        contexts = browser.contexts
        ctx = contexts[0] if contexts else await browser.new_context()

        # suno.com 페이지 찾기 또는 새로 열기
        suno_page = None
        for page in ctx.pages:
            if "suno.com" in page.url:
                suno_page = page
                break

        if not suno_page:
            suno_page = await ctx.new_page()
            await suno_page.goto("https://suno.com", wait_until="domcontentloaded", timeout=20_000)
            await suno_page.wait_for_timeout(3_000)

        # 로그인 여부 확인
        for sel in _LOGGED_IN_SELECTORS:
            try:
                if await suno_page.query_selector(sel):
                    logger.info(f"로그인 확인됨: {sel}")
                    return ctx
            except Exception:
                continue

        cookies = await ctx.cookies("https://suno.com")
        auth = [c for c in cookies if any(k in c["name"].lower() for k in ("auth", "token", "session", "clerk"))]
        if auth:
            logger.info(f"인증 쿠키 확인: {[c['name'] for c in auth]}")
            return ctx

        return None

    except Exception as e:
        logger.warning(f"CDP 연결/로그인 확인 실패: {e}")
        return None


# ── 라우터 ──────────────────────────────────────────────────────────────────

@router.get("/status")
async def suno_status():
    return {
        "session_exists": _session_path().exists(),
        "session_path":   str(_session_path()),
        "login_status":   _login_state["status"],
        "error":          _login_state["error"],
    }


@router.post("/login/open")
async def open_login():
    """
    Edge를 subprocess로 실행 (자동화 아님 → Google 차단 없음).
    --remote-debugging-port 로 나중에 Playwright가 세션만 읽어감.
    """
    if _login_state["status"] == "waiting":
        raise HTTPException(409, "이미 로그인 창이 열려 있습니다.")

    exe = _find_edge()
    if not exe:
        raise HTTPException(500, "Edge를 찾을 수 없습니다. Edge를 설치해주세요.")

    await _cleanup_login_state()
    _login_state.update({"status": "opening", "error": ""})

    try:
        # 기존 디버그 포트 인스턴스 정리
        _kill_debug_edge()

        profile_dir = str(_suno_profile_dir())

        # ★ subprocess로 일반 Edge 실행 (Playwright 자동화 아님)
        proc = subprocess.Popen([
            exe,
            f"--remote-debugging-port={_DEBUG_PORT}",
            f"--user-data-dir={profile_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            "https://suno.com",
        ])

        _login_state.update({"edge_proc": proc, "status": "waiting"})
        logger.info(f"Edge 일반 실행 (PID {proc.pid}, debug port {_DEBUG_PORT})")

        return {
            "status": "waiting",
            "message": (
                "Edge가 열렸습니다. Suno에 로그인해주세요. "
                "(Google 로그인 또는 이메일 모두 가능) "
                "로그인 완료 후 '로그인 완료' 버튼을 눌러주세요."
            ),
        }

    except Exception as e:
        _login_state.update({"status": "failed", "error": str(e)})
        logger.error(f"Edge 실행 실패: {e}", exc_info=True)
        raise HTTPException(500, f"Edge 실행 실패: {e}")


@router.post("/login/confirm")
async def confirm_login():
    """CDP로 Edge에 접속해 로그인 확인 후 세션 저장."""
    if _login_state["status"] != "waiting":
        raise HTTPException(400, f"로그인 창이 열려있지 않습니다. (상태: {_login_state['status']})")

    try:
        pw: Playwright = await async_playwright().start()
        _login_state["playwright"] = pw
    except Exception as e:
        raise HTTPException(500, f"Playwright 시작 실패: {e}")

    ctx = await _check_logged_in_via_cdp(pw)
    if ctx is None:
        await _stop_playwright()
        raise HTTPException(409, "아직 로그인되지 않은 것 같습니다. Suno에 로그인 후 다시 시도해주세요.")

    try:
        sp = _session_path()
        sp.parent.mkdir(parents=True, exist_ok=True)
        await ctx.storage_state(path=str(sp))
        _login_state["status"] = "confirmed"
        logger.info(f"Suno 세션 저장 완료: {sp}")
        asyncio.create_task(_cleanup_login_state())
        return {"status": "confirmed", "message": "로그인이 확인되어 세션을 저장했습니다."}
    except Exception as e:
        _login_state.update({"status": "failed", "error": str(e)})
        raise HTTPException(500, f"세션 저장 실패: {e}")


@router.post("/login/cancel")
async def cancel_login():
    await _cleanup_login_state()
    return {"status": "idle", "message": "로그인 창이 닫혔습니다."}


@router.delete("/session")
async def delete_session():
    p = _session_path()
    if p.exists():
        p.unlink()
        return {"deleted": True}
    return {"deleted": False}


async def _stop_playwright() -> None:
    bw = _login_state.get("browser")
    pw = _login_state.get("playwright")
    if bw:
        try:
            await bw.close()
        except Exception:
            pass
        _login_state["browser"] = None
    if pw:
        try:
            await pw.stop()
        except Exception:
            pass
        _login_state["playwright"] = None


# ── 레시피 녹화 엔드포인트 ───────────────────────────────────────────────────

@router.post("/record/start")
async def record_start():
    """Suno 브라우저를 열고 사용자 동작 녹화를 시작한다."""
    try:
        return await recorder.start_recording()
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"녹화 시작 실패: {e}")


@router.get("/record/status")
async def record_status():
    """현재 녹화 상태 및 기록된 동작 수를 반환한다."""
    return await recorder.get_status()


@router.post("/record/stop")
async def record_stop():
    """녹화를 완료하고 레시피를 저장한다."""
    try:
        return await recorder.stop_recording()
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"녹화 완료 실패: {e}")


@router.delete("/record")
async def record_cancel():
    """녹화를 취소하고 브라우저를 닫는다."""
    await recorder.cancel_recording()
    return {"status": "cancelled"}


@router.get("/recipe")
async def get_recipe():
    """저장된 레시피 정보를 반환한다."""
    r = recorder.get_recipe()
    if r is None:
        return {"exists": False}
    return {
        "exists":       True,
        "action_count": len(r.get("actions", [])),
        "recorded_at":  r.get("recorded_at"),
        "actions":      r.get("actions", []),
    }


@router.delete("/recipe")
async def delete_recipe():
    """저장된 레시피를 삭제한다."""
    rp = recorder.recipe_path()
    if rp.exists():
        rp.unlink()
        return {"deleted": True}
    return {"deleted": False}


async def _cleanup_login_state() -> None:
    await _stop_playwright()

    proc = _login_state.get("edge_proc")
    if proc:
        try:
            proc.terminate()
        except Exception:
            pass
        _login_state["edge_proc"] = None

    _login_state.update({"status": "idle", "error": ""})
    logger.info("로그인 상태 초기화")
