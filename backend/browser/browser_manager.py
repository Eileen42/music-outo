"""
Playwright 브라우저 세션 매니저.

Chrome 기반 (stealth 모드로 Google OAuth 차단 우회).
서비스별 세션을 storage/browser_sessions/{service_name}_context.json 에 저장.
login_interactive()는 최초 1회만 실행하면 이후 자동 재사용.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Optional

from playwright.async_api import (
    BrowserContext,
    Playwright,
    async_playwright,
)

from config import settings

logger = logging.getLogger(__name__)

# Edge 우선 → Chrome 순서 (Edge가 Google OAuth 차단 덜 받음)
_BROWSER_EXES = [
    (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe", "Edge"),
    (r"C:\Program Files\Microsoft\Edge\Application\msedge.exe", "Edge"),
    (r"C:\Program Files\Google\Chrome\Application\chrome.exe", "Chrome"),
    (r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe", "Chrome"),
]

_STEALTH_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
delete navigator.__proto__.webdriver;
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
Object.defineProperty(navigator, 'languages', { get: () => ['ko-KR', 'ko', 'en-US', 'en'] });
window.chrome = { runtime: {} };
"""

_LAUNCH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--exclude-switches=enable-automation",
    "--disable-infobars",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-default-apps",
    "--lang=ko-KR",
]


def _find_browser_exe() -> tuple[str, str] | tuple[None, None]:
    for path, name in _BROWSER_EXES:
        if Path(path).exists():
            return path, name
    return None, None


class BrowserManager:
    def __init__(self) -> None:
        self._playwright: Optional[Playwright] = None
        self._context: Optional[BrowserContext] = None  # persistent context
        self._contexts: dict[str, BrowserContext] = {}
        self._lock = asyncio.Lock()

    # ──────────────────────────── persistent context ────────────────────────────

    async def _get_persistent_context(self, profile_dir: str, headless: bool) -> BrowserContext:
        """Chrome stealth persistent context."""
        if self._playwright is None:
            self._playwright = await async_playwright().start()

        exe_path, label = _find_browser_exe()

        kwargs: dict = {
            "headless": headless,
            "viewport": {"width": 1280, "height": 900},
            "ignore_default_args": ["--enable-automation", "--enable-blink-features=IdleDetection"],
            "args": _LAUNCH_ARGS,
        }

        # 1. executable_path 직접 지정
        if exe_path:
            try:
                ctx = await self._playwright.chromium.launch_persistent_context(
                    profile_dir, executable_path=exe_path, **kwargs
                )
                await ctx.add_init_script(_STEALTH_SCRIPT)
                logger.info(f"persistent context: {label} ({exe_path}), headless={headless}")
                return ctx
            except Exception as e:
                logger.warning(f"executable_path 실패 ({exe_path}): {e}")

        # 2. channel 방식
        for channel in ("chrome", "msedge"):
            try:
                ctx = await self._playwright.chromium.launch_persistent_context(
                    profile_dir, channel=channel, **kwargs
                )
                await ctx.add_init_script(_STEALTH_SCRIPT)
                logger.info(f"persistent context: channel={channel}, headless={headless}")
                return ctx
            except Exception as e:
                logger.warning(f"channel 실패 ({channel}): {e}")

        # 3. 내장 Chromium (최후 수단)
        ctx = await self._playwright.chromium.launch_persistent_context(profile_dir, **kwargs)
        await ctx.add_init_script(_STEALTH_SCRIPT)
        logger.warning("persistent context: 내장 Chromium (Google 차단 가능)")
        return ctx

    # ──────────────────────────── 컨텍스트 ────────────────────────────

    async def get_context(self, service_name: str) -> BrowserContext:
        """
        서비스별 BrowserContext 반환.
        persistent profile dir 재사용 → 쿠키/세션 자동 유지.
        """
        if service_name in self._contexts:
            return self._contexts[service_name]

        profile_dir = str(settings.browser_sessions_dir / f"{service_name}_chrome_profile")
        Path(profile_dir).mkdir(parents=True, exist_ok=True)

        ctx = await self._get_persistent_context(profile_dir, headless=settings.browser_headless)

        # 저장된 세션이 있으면 cookies/storage 주입
        session_file = self._session_path(service_name)
        if session_file.exists():
            try:
                import json
                data = json.loads(session_file.read_text())
                if data.get("cookies"):
                    await ctx.add_cookies(data["cookies"])
                logger.info(f"[{service_name}] 저장된 세션 쿠키 로드: {session_file}")
            except Exception as e:
                logger.warning(f"[{service_name}] 세션 로드 실패: {e}")

        self._contexts[service_name] = ctx
        return ctx

    async def save_context(self, service_name: str, context: BrowserContext) -> None:
        """현재 컨텍스트 state를 JSON으로 저장."""
        session_file = self._session_path(service_name)
        session_file.parent.mkdir(parents=True, exist_ok=True)
        await context.storage_state(path=str(session_file))
        logger.info(f"[{service_name}] 세션 저장 완료: {session_file}")

    # ──────────────────────────── 수동 로그인 ────────────────────────────

    async def login_interactive(self, service_name: str, url: str) -> BrowserContext:
        """
        Headed Chrome으로 열어 사용자가 수동 로그인.
        로그인 후 터미널에서 Enter를 누르면 세션 저장.
        """
        logger.info(f"[{service_name}] 수동 로그인 모드 시작")

        profile_dir = str(settings.browser_sessions_dir / f"{service_name}_chrome_profile")
        Path(profile_dir).mkdir(parents=True, exist_ok=True)

        ctx = await self._get_persistent_context(profile_dir, headless=False)
        page = await ctx.new_page()
        await page.goto(url)

        print(f"\n{'='*60}")
        print(f"[{service_name}] Chrome이 열렸습니다.")
        print(f"  URL: {url}")
        print(f"  로그인을 완료한 후 터미널에서 Enter를 누르세요.")
        print(f"{'='*60}\n")

        await asyncio.to_thread(input, "로그인 완료 후 Enter ▶ ")

        await self.save_context(service_name, ctx)
        self._contexts[service_name] = ctx

        logger.info(f"[{service_name}] 수동 로그인 완료, 세션 저장됨")
        return ctx

    # ──────────────────────────── 종료 ────────────────────────────

    async def close(self) -> None:
        for name, ctx in self._contexts.items():
            try:
                await ctx.close()
            except Exception as e:
                logger.warning(f"[{name}] 컨텍스트 종료 실패: {e}")
        self._contexts.clear()

        if self._playwright:
            await self._playwright.stop()
            self._playwright = None

        logger.info("BrowserManager 종료 완료")

    # ──────────────────────────── 내부 헬퍼 ────────────────────────────

    def _session_path(self, service_name: str) -> Path:
        return settings.browser_sessions_dir / f"{service_name}_context.json"


# 싱글톤
browser_manager = BrowserManager()
