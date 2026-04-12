"""
Song Collector Agent — Suno에서 곡을 검색하여 다운로드.

Creator가 Create만 클릭하고 clip ID를 수집하지 않으므로,
Collector가 Suno 라이브러리/검색에서 제목으로 곡을 찾아 다운로드한다.

Creator가 일정 곡수 이상 진행하면 병렬로 시작.
"""
from __future__ import annotations

import asyncio
import logging
import re
import aiohttp
from pathlib import Path

from playwright.async_api import BrowserContext

logger = logging.getLogger("suno_collector")


class SunoCollectorAgent:
    """Suno에서 제목으로 곡을 찾아 다운로드하는 에이전트."""

    def __init__(self, context: BrowserContext) -> None:
        self._context = context
        self._queue: asyncio.Queue = asyncio.Queue()
        self._results: list[dict] = []
        self._running = True
        self._known_ids: set[str] = set()

    def set_known_ids(self, ids: set[str]) -> None:
        """이미 다운로드된 clip ID 설정."""
        self._known_ids = ids

    async def run_parallel(
        self,
        output_dir: str,
        title_to_index: dict[str, int],
        progress_callback=None,
    ) -> None:
        """
        병렬 모드: Creator가 큐에 넣으면 즉시 Suno에서 검색 후 다운로드.
        생성 직후에는 Suno에서 아직 처리 중일 수 있으므로 재시도 로직 포함.
        """
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

            logger.info(f"[Collector] 검색 시작: [{index:02d}] {title}")

            # 생성 직후라 Suno에서 아직 처리 중일 수 있음 → 최대 3회 재시도 (30초 간격)
            results = []
            for attempt in range(3):
                results = await self._search_and_download(
                    title=title,
                    index=index,
                    out_dir=out_dir,
                )
                if results:
                    break
                if attempt < 2:
                    wait = 30 * (attempt + 1)
                    logger.info(f"[Collector] '{title}' 아직 미완성, {wait}초 후 재시도")
                    await asyncio.sleep(wait)

            self._results.extend(results)
            collected_count += 1

            if progress_callback:
                progress_callback({
                    "current_index": index,
                    "current_title": title,
                    "phase": "collecting",
                    "completed": collected_count,
                    "total": collected_count,
                })

        logger.info(f"[Collector] 병렬 수집 완료: {len(self._results)}개 파일")

    async def collect_remaining(
        self,
        songs: list[dict],
        output_dir: str,
        progress_callback=None,
    ) -> None:
        """Creator 완료 후 남은 곡(초기 곡 포함)을 일괄 검색+다운로드."""
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        for i, song in enumerate(songs):
            title = song.get("title", "")
            index = song.get("index", 0)
            if not title:
                continue

            # 이미 다운받은 곡 건너뛰기
            safe_title = re.sub(r'[\u4E00-\u9FFF\u3400-\u4DBF\\/:*?"<>|]', "_", title)
            v1 = out_dir / f"{index:02d}_{safe_title}_v1.mp3"
            v2 = out_dir / f"{index:02d}_{safe_title}_v2.mp3"
            if v1.exists() and v2.exists():
                continue

            logger.info(f"[Collector] 잔여 검색: [{index:02d}] {title}")

            for attempt in range(3):
                results = await self._search_and_download(title=title, index=index, out_dir=out_dir)
                if results:
                    self._results.extend(results)
                    break
                if attempt < 2:
                    await asyncio.sleep(30 * (attempt + 1))

            if progress_callback:
                progress_callback({
                    "current_index": index,
                    "current_title": title,
                    "phase": "collecting",
                    "completed": i + 1,
                    "total": len(songs),
                })

    def enqueue(self, song_result: dict) -> None:
        self._queue.put_nowait(song_result)

    def stop(self) -> None:
        self._running = False

    def get_results(self) -> list[dict]:
        return self._results

    async def _search_and_download(
        self,
        title: str,
        index: int,
        out_dir: Path,
    ) -> list[dict]:
        """Suno에서 제목으로 검색 → 곡 2개 찾기 → 다운로드."""
        results = []
        page = await self._context.new_page()
        found_clips: list[dict] = []

        try:
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
                                    "id": cid,
                                    "title": ctitle,
                                    "audio_url": c.get("audio_url", ""),
                                })
                except Exception:
                    pass

            page.on("response", on_response)

            await page.goto("https://suno.com/create", wait_until="domcontentloaded", timeout=30_000)
            await page.wait_for_timeout(3_000)

            # Search clips 입력
            search_input = await page.query_selector('input[aria-label="Search clips"]')
            if not search_input:
                # fallback: 모든 input 중 search 관련 찾기
                search_input = await page.query_selector('input[placeholder*="Search"]')
            if not search_input:
                logger.warning(f"검색 입력창 못 찾음: {title}")
                return results

            await search_input.click()
            await search_input.fill(title)
            await page.wait_for_timeout(4_000)

            page.remove_listener("response", on_response)

            to_dl = found_clips[:2]
            if not to_dl:
                logger.info(f"'{title}': Suno에서 검색 결과 없음")
                return results

            # 다운로드
            for slot, clip in enumerate(to_dl, 1):
                safe_title = re.sub(r'[\u4E00-\u9FFF\u3400-\u4DBF\\/:*?"<>|]', "_", title)
                prefix = f"{index:02d}_{safe_title}_v{slot}"
                file_path = await self._download_clip(clip["id"], clip.get("audio_url", ""), out_dir, prefix)

                results.append({
                    "index": index,
                    "title": title,
                    "slot": slot,
                    "suno_id": clip["id"],
                    "file_path": file_path,
                    "status": "completed" if file_path else "download_failed",
                })
                self._known_ids.add(clip["id"])

        except Exception as e:
            logger.warning(f"'{title}' 검색/다운로드 실패: {e}")
        finally:
            await page.close()

        return results

    async def _download_clip(self, clip_id: str, audio_url: str, out_dir: Path, prefix: str) -> str:
        """MP3 다운로드."""
        dest = out_dir / f"{prefix}.mp3"
        if dest.exists() and dest.stat().st_size > 10_000:
            logger.info(f"이미 존재: {dest.name}")
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

        # Fallback: 곡 페이지에서 audio tag
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
