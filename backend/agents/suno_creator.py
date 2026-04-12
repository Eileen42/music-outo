"""
Suno Creator Agent — 곡 생성만 담당.

흐름: 탭 열기 → 메타데이터 입력 → Create → 다음 탭 → ... → 마지막 곡까지 → 브라우저 닫기

기존 병렬(Semaphore) 방식 대신 순차적으로 처리하여 안정성 확보.
각 곡 생성 시 clip ID만 수집하고, 다운로드는 Collector Agent가 담당.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Any

from playwright.async_api import (
    async_playwright,
    Browser,
    BrowserContext,
    Page,
    Playwright,
)

from config import settings
from browser.suno_recorder import get_recipe

logger = logging.getLogger("suno_creator")

# 기존 suno_automation.py의 셀렉터/헬퍼 재사용
from browser.suno_automation import SELECTORS, _find_exe, _session_path


class SunoCreatorAgent:
    """순차적으로 Suno에서 곡을 생성하는 에이전트."""

    def __init__(self) -> None:
        self._pw: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None

    async def __aenter__(self) -> "SunoCreatorAgent":
        await self._start()
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self._stop()

    async def _start(self) -> None:
        sp = _session_path()
        if not sp.exists():
            raise RuntimeError("저장된 Suno 세션이 없습니다. 먼저 로그인해주세요.")

        exe = _find_exe()
        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(
            executable_path=exe,
            headless=False,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--exclude-switches=enable-automation",
                "--no-first-run",
                "--disable-infobars",
            ],
        )
        self._context = await self._browser.new_context(
            storage_state=str(sp),
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/136.0.0.0 Safari/537.36 Edg/136.0.0.0"
            ),
        )
        logger.info(f"SunoCreatorAgent 시작: exe={exe}")

    async def _stop(self) -> None:
        for obj in (self._context, self._browser):
            if obj:
                try:
                    await obj.close()
                except Exception:
                    pass
        if self._pw:
            try:
                await self._pw.stop()
            except Exception:
                pass
        logger.info("SunoCreatorAgent 종료 — 브라우저 닫힘")

    # ── 메인: 순차적 곡 생성 ─────────────────────────────────────────

    async def create_all(
        self,
        songs: list[dict],
        progress_callback=None,
    ) -> list[dict]:
        """
        모든 곡을 순차적으로 생성.
        각 곡마다: 탭 열기 → 입력 → Create → clip ID 수집 → 탭 닫기 → 다음 곡

        songs: [{"title", "lyrics", "suno_prompt", "is_instrumental", "index"}, ...]
        Returns: [{"index", "title", "clips": [{"id", "audio_url"}], "status"}, ...]
        """
        results = []
        total = len(songs)

        for i, song in enumerate(songs):
            title = song.get("title", f"Track_{i+1}")
            index = song.get("index", i + 1)
            logger.info(f"[{i+1}/{total}] 곡 생성 시작: {title}")

            if progress_callback:
                progress_callback({
                    "current_index": index,
                    "current_title": title,
                    "completed": i,
                    "total": total,
                    "status": "creating",
                })

            # 최대 3회 재시도
            clip_result = None
            last_error = ""
            for attempt in range(3):
                page = await self._context.new_page()
                try:
                    clip_result = await self._create_one_song(
                        page=page,
                        title=title,
                        lyrics=song.get("lyrics", "") if not song.get("is_instrumental") else "",
                        style_prompt=song.get("suno_prompt", ""),
                        is_instrumental=song.get("is_instrumental", False),
                    )
                    break
                except Exception as e:
                    last_error = str(e) or type(e).__name__
                    logger.warning(f"[{i+1}/{total}] 시도 {attempt+1} 실패: {last_error}")
                    if attempt < 2:
                        await asyncio.sleep(15 * (attempt + 1))
                finally:
                    try:
                        await page.close()
                    except Exception:
                        pass

            if clip_result:
                results.append({
                    "index": index,
                    "title": title,
                    "clips": clip_result["clips"],
                    "status": "created",
                })
                logger.info(f"[{i+1}/{total}] 곡 생성 완료: {title} ({len(clip_result['clips'])} clips)")
            else:
                results.append({
                    "index": index,
                    "title": title,
                    "clips": [],
                    "status": "failed",
                    "error": last_error,
                })
                logger.error(f"[{i+1}/{total}] 곡 생성 실패: {title} — {last_error}")

            if progress_callback:
                progress_callback({
                    "current_index": index,
                    "current_title": title,
                    "completed": i + 1,
                    "total": total,
                    "status": "created" if clip_result else "failed",
                })

            # 곡 사이 짧은 대기 (Suno rate limit 방지)
            if i < total - 1:
                await asyncio.sleep(3)

        logger.info(f"전체 생성 완료: {len([r for r in results if r['status'] == 'created'])}/{total}곡 성공")
        return results

    # ── 단일 곡 생성 (기존 _create_one 로직 재사용) ─────────────────

    async def _create_one_song(
        self,
        page: Page,
        title: str,
        lyrics: str,
        style_prompt: str,
        is_instrumental: bool,
    ) -> dict:
        """suno.com/create → 입력 → Create → clip ID 수집."""
        # 기존 SunoAutomation의 _create_one과 동일한 로직
        from browser.suno_automation import SunoAutomation
        suno = SunoAutomation.__new__(SunoAutomation)
        suno._context = self._context

        await page.goto("https://suno.com/create", wait_until="domcontentloaded", timeout=30_000)
        await page.wait_for_timeout(3_000)

        # Advanced 모드 전환
        await suno._switch_to_custom_mode(page)

        # 입력 (레시피 또는 하드코딩)
        recipe = get_recipe()
        if recipe and recipe.get("actions"):
            await suno._replay_recipe(page, title, lyrics, style_prompt, is_instrumental, recipe)
        else:
            if not is_instrumental and lyrics:
                await suno._react_fill(page, SELECTORS["lyrics_area"], lyrics, "lyrics")
            if style_prompt:
                await suno._fill_style_by_position(page, style_prompt)
            if title:
                await suno._react_fill_title(page, title)

        # Create 클릭 → clip 수집
        clips = await suno._click_create_and_wait(page, title)
        return {"clips": clips}


suno_creator_agent = SunoCreatorAgent()
