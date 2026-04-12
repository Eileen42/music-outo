"""
Suno Creator Agent — 탭 1개만 사용하여 곡 생성.

같은 탭에서: /create → 입력 → Create 클릭 → /create로 다시 이동 → 입력 → Create → 반복
탭을 추가하지 않음. 브라우저 리소스 최소화.
"""
from __future__ import annotations

import asyncio
import logging

from playwright.async_api import BrowserContext, Page

from browser.suno_automation import SELECTORS, SunoAutomation
from browser.suno_recorder import get_recipe

logger = logging.getLogger("suno_creator")


class SunoCreatorAgent:
    """탭 1개를 재사용하여 순차적으로 Suno 곡을 생성하는 에이전트."""

    def __init__(self, context: BrowserContext) -> None:
        self._context = context
        self._page: Page | None = None

    async def create_all(
        self,
        songs: list[dict],
        progress_callback=None,
    ) -> list[dict]:
        """
        탭 1개에서 모든 곡을 순차 생성.
        /create → 입력 → Create → 같은 탭에서 다시 /create → 반복
        """
        results = []
        total = len(songs)

        # 탭 1개만 생성
        self._page = await self._context.new_page()

        for i, song in enumerate(songs):
            title = song.get("title", f"Track_{i+1}")
            index = song.get("index", i + 1)
            logger.info(f"[{i+1}/{total}] Create: {title}")

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
                try:
                    await asyncio.wait_for(
                        self._create_one(
                            title=title,
                            lyrics=song.get("lyrics", "") if not song.get("is_instrumental") else "",
                            style_prompt=song.get("suno_prompt", ""),
                            is_instrumental=song.get("is_instrumental", False),
                        ),
                        timeout=60.0,
                    )
                    success = True
                    break
                except asyncio.TimeoutError:
                    last_error = f"타임아웃 (60초): {title}"
                    logger.warning(f"[{i+1}/{total}] 시도 {attempt+1} 타임아웃")
                except Exception as e:
                    last_error = str(e) or type(e).__name__
                    logger.warning(f"[{i+1}/{total}] 시도 {attempt+1} 실패: {last_error}")

                if attempt < 2:
                    await asyncio.sleep(8)
                    # 페이지가 이상해졌으면 새로고침
                    try:
                        await self._page.goto("https://suno.com/create", wait_until="domcontentloaded", timeout=15_000)
                        await self._page.wait_for_timeout(2_000)
                    except Exception:
                        pass

            results.append({
                "index": index,
                "title": title,
                "status": "submitted" if success else "failed",
                **({"error": last_error} if not success else {}),
            })

            if progress_callback:
                progress_callback({
                    "current_index": index,
                    "current_title": title,
                    "completed": i + 1,
                    "total": total,
                    "status": "submitted" if success else "failed",
                })

            # 곡 사이 대기 (Suno rate limit 방지)
            if i < total - 1:
                await asyncio.sleep(5)

        created = len([r for r in results if r["status"] == "submitted"])
        logger.info(f"전체 Create 완료: {created}/{total}곡")
        return results

    async def close(self) -> None:
        """탭 닫기."""
        if self._page and not self._page.is_closed():
            try:
                await self._page.close()
            except Exception:
                pass
            self._page = None

    async def _create_one(
        self,
        title: str,
        lyrics: str,
        style_prompt: str,
        is_instrumental: bool,
    ) -> None:
        """같은 탭에서 /create 이동 → 입력 → Create 클릭."""
        page = self._page
        suno = SunoAutomation.__new__(SunoAutomation)
        suno._context = self._context

        # 같은 탭에서 /create로 이동
        await page.goto("https://suno.com/create", wait_until="domcontentloaded", timeout=30_000)
        await page.wait_for_timeout(2_000)

        # 에러 사전 감지
        text = await page.evaluate("() => document.body.innerText.substring(0, 300)")
        if "Insufficient credits" in text:
            raise RuntimeError("크레딧 부족")

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

        # Create 클릭
        await suno._click_create_btn(page, title)
        await page.wait_for_timeout(3_000)

        # 클릭 후 에러 확인
        post = await page.evaluate("() => document.body.innerText.substring(0, 300)")
        if "Something went wrong" in post or "Error" in post[:50]:
            raise RuntimeError(f"Create 후 에러: {post[:100]}")

        logger.info(f"Create 완료: {title}")
