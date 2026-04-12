"""
Song Collector Agent — 탭 1개로 Suno 검색 + 다운로드.

같은 탭에서: 검색어 입력 → 결과 확인 → 다운 → 검색어 교체 → 반복
"""
from __future__ import annotations

import asyncio
import logging
import re
import aiohttp
from pathlib import Path

from playwright.async_api import BrowserContext, Page

logger = logging.getLogger("suno_collector")


class SunoCollectorAgent:
    """탭 1개로 Suno 검색하여 곡을 다운로드하는 에이전트."""

    def __init__(self, context: BrowserContext) -> None:
        self._context = context
        self._page: Page | None = None
        self._results: list[dict] = []
        self._known_ids: set[str] = set()

    def set_known_ids(self, ids: set[str]) -> None:
        self._known_ids = ids

    async def collect_all(
        self,
        songs: list[dict],
        output_dir: str,
        progress_callback=None,
    ) -> list[dict]:
        """
        탭 1개에서 모든 곡을 순차적으로 검색+다운로드.
        이미 v1+v2 있는 곡은 건너뜀.
        """
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        # 검색 페이지 1번만 열기
        self._page = await self._context.new_page()
        await self._page.goto("https://suno.com/create", wait_until="domcontentloaded", timeout=30_000)
        await self._page.wait_for_timeout(3_000)

        for i, song in enumerate(songs):
            title = song.get("title", "")
            index = song.get("index", 0)
            if not title:
                continue

            # 이미 v1+v2 있으면 건너뛰기
            safe = re.sub(r'[\u4E00-\u9FFF\u3400-\u4DBF\\/:*?"<>|]', "_", title)
            v1 = out_dir / f"{index:02d}_{safe}_v1.mp3"
            v2 = out_dir / f"{index:02d}_{safe}_v2.mp3"
            if v1.exists() and v1.stat().st_size > 10_000 and v2.exists() and v2.stat().st_size > 10_000:
                logger.info(f"[{index:02d}] {title}: 이미 완료, 건너뜀")
                continue

            logger.info(f"[{index:02d}] {title}: 검색 중...")

            results = await self._search_one(title, index, out_dir)
            self._results.extend(results)

            if progress_callback:
                progress_callback({
                    "current_index": index,
                    "current_title": title,
                    "phase": "collecting",
                    "completed": i + 1,
                    "total": len(songs),
                })

        logger.info(f"수집 완료: {len(self._results)}개 파일")
        return self._results

    async def close(self) -> None:
        """탭 닫기."""
        if self._page and not self._page.is_closed():
            try:
                await self._page.close()
            except Exception:
                pass
            self._page = None

    def get_results(self) -> list[dict]:
        return self._results

    async def _search_one(self, title: str, index: int, out_dir: Path) -> list[dict]:
        """같은 탭에서 검색어만 교체하여 검색 + 다운로드."""
        page = self._page
        found_clips: list[dict] = []
        results = []

        async def on_response(resp):
            if "suno" not in resp.url:
                return
            ct = resp.headers.get("content-type", "")
            if "json" not in ct:
                return
            try:
                data = await resp.json()
                clips = data.get("clips") or data.get("data") or []
                if not isinstance(clips, list):
                    return
                for c in clips:
                    if not isinstance(c, dict):
                        continue
                    cid = c.get("id", "")
                    ctitle = c.get("title", "")
                    if cid and ctitle.strip().lower() == title.strip().lower():
                        if cid not in self._known_ids:
                            found_clips.append({
                                "id": cid, "title": ctitle,
                                "audio_url": c.get("audio_url", ""),
                            })
            except Exception:
                pass

        try:
            page.on("response", on_response)

            search_input = await page.query_selector('input[aria-label="Search clips"]')
            if not search_input:
                search_input = await page.query_selector('input[placeholder*="Search"]')
            if not search_input:
                # 페이지 새로고침
                await page.goto("https://suno.com/create", wait_until="domcontentloaded", timeout=15_000)
                await page.wait_for_timeout(2_000)
                search_input = await page.query_selector('input[aria-label="Search clips"]')

            if not search_input:
                logger.warning(f"[Collector] 검색 입력창 없음: {title}")
                page.remove_listener("response", on_response)
                return results

            # 검색어 교체
            await search_input.click()
            await search_input.fill("")
            await page.wait_for_timeout(300)
            await search_input.fill(title)
            await page.wait_for_timeout(4_000)

            page.remove_listener("response", on_response)

            to_dl = found_clips[:2]
            if not to_dl:
                logger.info(f"[Collector] '{title}': Suno에 없음")
                return results

            for slot, clip in enumerate(to_dl, 1):
                safe = re.sub(r'[\u4E00-\u9FFF\u3400-\u4DBF\\/:*?"<>|]', "_", title)
                prefix = f"{index:02d}_{safe}_v{slot}"
                file_path = await self._download_clip(clip["id"], clip.get("audio_url", ""), out_dir, prefix)
                results.append({
                    "index": index, "title": title, "slot": slot,
                    "suno_id": clip["id"], "file_path": file_path,
                    "status": "completed" if file_path else "download_failed",
                })
                self._known_ids.add(clip["id"])

            if results:
                logger.info(f"[Collector] '{title}': {len([r for r in results if r['status']=='completed'])}개 다운")

        except Exception as e:
            logger.warning(f"[Collector] '{title}' 실패: {e}")
            try:
                page.remove_listener("response", on_response)
            except Exception:
                pass

        return results

    async def _download_clip(self, clip_id: str, audio_url: str, out_dir: Path, prefix: str) -> str:
        dest = out_dir / f"{prefix}.mp3"
        if dest.exists() and dest.stat().st_size > 10_000:
            return str(dest)

        cookies = await self._context.cookies("https://suno.com")
        cookie_header = "; ".join(f"{c['name']}={c['value']}" for c in cookies)
        headers = {
            "Cookie": cookie_header, "Referer": "https://suno.com/",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/136.0.0.0",
        }

        urls = []
        if audio_url:
            urls.append(audio_url)
        urls += [f"https://cdn1.suno.ai/{clip_id}.mp3", f"https://cdn2.suno.ai/{clip_id}.mp3"]

        async with aiohttp.ClientSession() as http:
            for url in urls:
                try:
                    async with http.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=120)) as resp:
                        if resp.status == 200:
                            content = await resp.read()
                            if len(content) > 10_000:
                                dest.write_bytes(content)
                                return str(dest)
                except Exception:
                    pass
        return ""
