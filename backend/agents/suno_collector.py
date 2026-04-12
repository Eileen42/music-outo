"""
Song Collector Agent — Suno에서 곡을 검색하여 다운로드.

핵심: 검색 페이지를 한 번만 열고 곡마다 검색어만 교체.
페이지 열고닫기 없이 검색 → 다운 → 다음 검색 → 다운 → ... 반복.
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
    """Suno 검색 페이지 1개로 모든 곡을 찾아 다운로드하는 에이전트."""

    def __init__(self, context: BrowserContext) -> None:
        self._context = context
        self._queue: asyncio.Queue = asyncio.Queue()
        self._results: list[dict] = []
        self._running = True
        self._known_ids: set[str] = set()
        self._search_page: Page | None = None

    def set_known_ids(self, ids: set[str]) -> None:
        self._known_ids = ids

    async def _get_search_page(self) -> Page:
        """검색 페이지를 한 번만 열고 재사용."""
        if self._search_page and not self._search_page.is_closed():
            return self._search_page

        self._search_page = await self._context.new_page()
        await self._search_page.goto("https://suno.com/create", wait_until="domcontentloaded", timeout=30_000)
        await self._search_page.wait_for_timeout(3_000)
        logger.info("[Collector] 검색 페이지 오픈")
        return self._search_page

    async def close_search_page(self) -> None:
        """작업 완료 후 검색 페이지 닫기."""
        if self._search_page and not self._search_page.is_closed():
            try:
                await self._search_page.close()
            except Exception:
                pass
            self._search_page = None

    async def run_parallel(
        self,
        output_dir: str,
        title_to_index: dict[str, int],
        progress_callback=None,
    ) -> None:
        """병렬 모드: Creator 큐에서 꺼내 즉시 검색+다운."""
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        collected_count = 0

        while self._running or not self._queue.empty():
            try:
                song = await asyncio.wait_for(self._queue.get(), timeout=10.0)
            except asyncio.TimeoutError:
                continue

            title = song.get("title", "")
            index = song.get("index", 0)
            if not title:
                continue

            logger.info(f"[Collector] 검색: [{index:02d}] {title}")

            for attempt in range(3):
                results = await self._search_one(title, index, out_dir)
                if results:
                    self._results.extend(results)
                    break
                if attempt < 2:
                    wait = 30 * (attempt + 1)
                    logger.info(f"[Collector] '{title}' 미완성, {wait}초 후 재시도")
                    await asyncio.sleep(wait)

            collected_count += 1
            if progress_callback:
                progress_callback({
                    "current_index": index, "current_title": title,
                    "phase": "collecting", "completed": collected_count, "total": collected_count,
                })

        logger.info(f"[Collector] 병렬 수집 완료: {len(self._results)}개")

    async def collect_remaining(
        self,
        songs: list[dict],
        output_dir: str,
        progress_callback=None,
    ) -> None:
        """Creator 완료 후 남은 곡 일괄 검색+다운. 페이지 재사용."""
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        for i, song in enumerate(songs):
            title = song.get("title", "")
            index = song.get("index", 0)
            if not title:
                continue

            # 이미 v1+v2 있으면 건너뛰기
            safe = re.sub(r'[\u4E00-\u9FFF\u3400-\u4DBF\\/:*?"<>|]', "_", title)
            if (out_dir / f"{index:02d}_{safe}_v1.mp3").exists() and (out_dir / f"{index:02d}_{safe}_v2.mp3").exists():
                continue

            for attempt in range(3):
                results = await self._search_one(title, index, out_dir)
                if results:
                    self._results.extend(results)
                    break
                if attempt < 2:
                    await asyncio.sleep(30 * (attempt + 1))

            if progress_callback:
                progress_callback({
                    "current_index": index, "current_title": title,
                    "phase": "collecting", "completed": i + 1, "total": len(songs),
                })

    def enqueue(self, song_result: dict) -> None:
        self._queue.put_nowait(song_result)

    def stop(self) -> None:
        self._running = False

    def get_results(self) -> list[dict]:
        return self._results

    # ── 핵심: 페이지 재사용 검색 ─────────────────────────────────

    async def _search_one(self, title: str, index: int, out_dir: Path) -> list[dict]:
        """
        검색 페이지에서 검색어만 교체하여 곡 찾기 + 다운로드.
        페이지를 열고 닫지 않음.
        """
        page = await self._get_search_page()
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

            # 검색 입력 찾기
            search_input = await page.query_selector('input[aria-label="Search clips"]')
            if not search_input:
                search_input = await page.query_selector('input[placeholder*="Search"]')
            if not search_input:
                # 페이지가 이상한 상태 → 새로고침
                logger.warning(f"[Collector] 검색 입력창 없음, 페이지 새로고침")
                await page.goto("https://suno.com/create", wait_until="domcontentloaded", timeout=30_000)
                await page.wait_for_timeout(3_000)
                search_input = await page.query_selector('input[aria-label="Search clips"]')
                if not search_input:
                    logger.warning(f"[Collector] 검색 입력창 재시도 실패: {title}")
                    page.remove_listener("response", on_response)
                    return results

            # 검색어 입력 (기존 내용 지우고 새로 입력)
            await search_input.click()
            await search_input.fill("")
            await page.wait_for_timeout(300)
            await search_input.fill(title)
            await page.wait_for_timeout(4_000)

            page.remove_listener("response", on_response)

            to_dl = found_clips[:2]
            if not to_dl:
                logger.info(f"[Collector] '{title}': 검색 결과 없음")
                return results

            # 다운로드
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

            logger.info(f"[Collector] '{title}': {len(results)}개 다운로드")

        except Exception as e:
            logger.warning(f"[Collector] '{title}' 검색 실패: {e}")
            page.remove_listener("response", on_response)

        return results

    # ── 다운로드 ─────────────────────────────────────────────────

    async def _download_clip(self, clip_id: str, audio_url: str, out_dir: Path, prefix: str) -> str:
        dest = out_dir / f"{prefix}.mp3"
        if dest.exists() and dest.stat().st_size > 10_000:
            return str(dest)

        cookies = await self._context.cookies("https://suno.com")
        cookie_header = "; ".join(f"{c['name']}={c['value']}" for c in cookies)
        headers = {
            "Cookie": cookie_header,
            "Referer": "https://suno.com/",
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
                                logger.info(f"다운로드 OK: {dest.name} ({len(content)//1024}KB)")
                                return str(dest)
                except Exception:
                    pass

        # Fallback: 곡 페이지에서 audio tag (별도 탭)
        return await self._page_download(clip_id, dest, headers)

    async def _page_download(self, clip_id: str, dest: Path, headers: dict) -> str:
        page = await self._context.new_page()
        try:
            await page.goto(f"https://suno.com/song/{clip_id}", wait_until="domcontentloaded", timeout=30_000)
            for _ in range(60):
                src = await page.evaluate("() => { const a = document.querySelector('audio'); return a ? a.src : ''; }")
                if src and src.startswith("http"):
                    async with aiohttp.ClientSession() as http:
                        async with http.get(src, headers=headers, timeout=aiohttp.ClientTimeout(total=120)) as resp:
                            if resp.status == 200:
                                content = await resp.read()
                                if len(content) > 10_000:
                                    dest.write_bytes(content)
                                    return str(dest)
                await asyncio.sleep(5)
            return ""
        except Exception:
            return ""
        finally:
            await page.close()
