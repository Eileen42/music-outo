"""
Suno Creator Agent — 곡 생성 담당.

탭을 추가하며 순차적으로 곡 생성. 브라우저는 닫지 않음 (Collector와 공유).
곡마다: 새 탭 열기 → 입력 → Create → (탭 유지) → 다음 탭
모든 곡 Create 완료 시 탭들은 열린 채로 유지.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from playwright.async_api import BrowserContext, Page

from browser.suno_automation import SELECTORS, _find_exe, _session_path
from browser.suno_recorder import get_recipe

logger = logging.getLogger("suno_creator")


class SunoCreatorAgent:
    """순차적으로 탭을 열어 Suno 곡을 생성하는 에이전트. 브라우저는 외부에서 관리."""

    def __init__(self, context: BrowserContext) -> None:
        self._context = context
        self._pages: list[Page] = []  # 열린 탭 목록 (닫지 않음)

    async def create_all(
        self,
        songs: list[dict],
        progress_callback=None,
        on_song_created=None,
    ) -> list[dict]:
        """
        모든 곡을 순차적으로 생성.
        탭은 닫지 않고 유지 (Collector가 audio_url 업데이트를 받을 수 있도록).

        on_song_created: 곡 하나 생성될 때마다 호출 (Collector 병렬 트리거용)
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
                    self._pages.append(page)  # 탭 유지 (닫지 않음)
                    break
                except Exception as e:
                    last_error = str(e) or type(e).__name__
                    logger.warning(f"[{i+1}/{total}] 시도 {attempt+1} 실패: {last_error}")
                    try:
                        await page.close()
                    except Exception:
                        pass
                    if attempt < 2:
                        await asyncio.sleep(10 * (attempt + 1))

            result = {
                "index": index,
                "title": title,
                "clips": clip_result["clips"] if clip_result else [],
                "status": "created" if clip_result else "failed",
            }
            if not clip_result:
                result["error"] = last_error
            results.append(result)

            logger.info(f"[{i+1}/{total}] {'완료' if clip_result else '실패'}: {title}")

            if progress_callback:
                progress_callback({
                    "current_index": index,
                    "current_title": title,
                    "completed": i + 1,
                    "total": total,
                    "status": result["status"],
                })

            # Collector에게 생성 완료 알림 (병렬 처리 트리거)
            if on_song_created and clip_result:
                on_song_created(result)

            # 곡 사이 짧은 대기 (rate limit 방지)
            if i < total - 1:
                await asyncio.sleep(3)

        logger.info(f"전체 생성 완료: {len([r for r in results if r['status'] == 'created'])}/{total}곡 성공")
        return results

    async def close_all_tabs(self) -> None:
        """모든 탭 닫기 (브라우저 정리 시 호출)."""
        for page in self._pages:
            try:
                await page.close()
            except Exception:
                pass
        self._pages.clear()

    async def _create_one_song(
        self,
        page: Page,
        title: str,
        lyrics: str,
        style_prompt: str,
        is_instrumental: bool,
    ) -> dict:
        """suno.com/create → 입력 → Create → clip ID 수집."""
        from browser.suno_automation import SunoAutomation
        suno = SunoAutomation.__new__(SunoAutomation)
        suno._context = self._context

        await page.goto("https://suno.com/create", wait_until="domcontentloaded", timeout=30_000)
        await page.wait_for_timeout(3_000)
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

        clips = await suno._click_create_and_wait(page, title)
        return {"clips": clips}
