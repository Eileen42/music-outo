"""
Suno Creator Agent — 곡 생성만 담당.

핵심 변경: Create 클릭 후 clip 수집을 기다리지 않음.
탭 열기 → 입력 → Create 클릭 → 바로 다음 탭 → ... → 전부 끝나면 완료.

clip 수집�� 다운로드는 Collector Agent가 담당.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from playwright.async_api import BrowserContext, Page

from browser.suno_automation import SELECTORS, SunoAutomation
from browser.suno_recorder import get_recipe

logger = logging.getLogger("suno_creator")


class SunoCreatorAgent:
    """순차적으로 탭을 열어 Suno Create만 클릭하는 에이전트."""

    def __init__(self, context: BrowserContext) -> None:
        self._context = context
        self._pages: list[dict] = []  # {"page": Page, "title": str, "index": int}

    async def create_all(
        self,
        songs: list[dict],
        progress_callback=None,
        on_song_created=None,
    ) -> list[dict]:
        """
        모든 곡을 순차적으로 Create 클릭.
        clip 수집을 기다리지 않고 바로 다음 곡으로 넘어감.
        """
        results = []
        total = len(songs)

        for i, song in enumerate(songs):
            title = song.get("title", f"Track_{i+1}")
            index = song.get("index", i + 1)
            logger.info(f"[{i+1}/{total}] Create 시작: {title}")

            if progress_callback:
                progress_callback({
                    "current_index": index,
                    "current_title": title,
                    "completed": i,
                    "total": total,
                    "status": "creating",
                })

            success = False
            last_error = ""
            for attempt in range(3):
                page = await self._context.new_page()
                try:
                    await self._create_and_move_on(
                        page=page,
                        title=title,
                        lyrics=song.get("lyrics", "") if not song.get("is_instrumental") else "",
                        style_prompt=song.get("suno_prompt", ""),
                        is_instrumental=song.get("is_instrumental", False),
                    )
                    self._pages.append({"page": page, "title": title, "index": index})
                    success = True
                    break
                except Exception as e:
                    last_error = str(e) or type(e).__name__
                    logger.warning(f"[{i+1}/{total}] 시도 {attempt+1} 실패: {last_error}")
                    try:
                        await page.close()
                    except Exception:
                        pass
                    if attempt < 2:
                        await asyncio.sleep(8 * (attempt + 1))

            result = {
                "index": index,
                "title": title,
                "status": "submitted" if success else "failed",
            }
            if not success:
                result["error"] = last_error
            results.append(result)

            logger.info(f"[{i+1}/{total}] {'Create 완료' if success else '실패'}: {title}")

            if progress_callback:
                progress_callback({
                    "current_index": index,
                    "current_title": title,
                    "completed": i + 1,
                    "total": total,
                    "status": result["status"],
                })

            if on_song_created and success:
                on_song_created(result)

            # 곡 사이 대기 (rate limit 방지)
            if i < total - 1:
                await asyncio.sleep(5)

        created = len([r for r in results if r["status"] == "submitted"])
        logger.info(f"전체 Create 완료: {created}/{total}곡")
        return results

    async def close_all_tabs(self) -> None:
        """모든 탭 닫기."""
        for item in self._pages:
            try:
                await item["page"].close()
            except Exception:
                pass
        self._pages.clear()

    async def _create_and_move_on(
        self,
        page: Page,
        title: str,
        lyrics: str,
        style_prompt: str,
        is_instrumental: bool,
    ) -> None:
        """
        suno.com/create → 입력 → Create 클릭 → 끝 (clip 수집 안 기다림).
        """
        # SunoAutomation의 입력 헬퍼 재사용
        suno = SunoAutomation.__new__(SunoAutomation)
        suno._context = self._context

        await page.goto("https://suno.com/create", wait_until="domcontentloaded", timeout=30_000)
        await page.wait_for_timeout(2_000)

        await suno._switch_to_custom_mode(page)

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

        # Create 클릭만 하고 끝 — clip 수집 안 함
        await suno._click_create_btn(page, title)
        logger.info(f"Create 클릭 완료 (clip 수집 안 함): {title}")

        # 클릭 후 짧은 대기 (Suno가 요청 접수하도록)
        await page.wait_for_timeout(2_000)
