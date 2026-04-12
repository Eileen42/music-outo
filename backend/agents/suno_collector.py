"""
Song Collector Agent — 곡 다운로드 담당.

같은 브라우저 context를 Creator와 공유.
탭을 추가하며 검색/다운로드. 탭은 다운 완료 후 닫음.
Creator가 3곡째부터 병렬로 시작 가능.
"""
from __future__ import annotations

import asyncio
import logging
import re
import aiohttp
from pathlib import Path

from playwright.async_api import BrowserContext

from config import settings

logger = logging.getLogger("suno_collector")


class SunoCollectorAgent:
    """Creator와 같은 브라우저를 공유하며 곡을 다운로드하는 에이전트."""

    def __init__(self, context: BrowserContext) -> None:
        self._context = context
        self._queue: asyncio.Queue = asyncio.Queue()
        self._results: list[dict] = []
        self._running = True

    async def collect_all(
        self,
        creation_results: list[dict],
        output_dir: str,
        progress_callback=None,
    ) -> list[dict]:
        """Creator 완료 후 남은 곡들을 일괄 다운로드."""
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        successful = [r for r in creation_results if r["status"] == "created" and r.get("clips")]
        total = len(successful)
        logger.info(f"일괄 다운로드 시작: {total}곡")

        for i, song in enumerate(successful):
            results = await self._download_song(song, out_dir)
            self._results.extend(results)

            if progress_callback:
                progress_callback({
                    "current_index": song["index"],
                    "current_title": song["title"],
                    "phase": "collected",
                    "completed": i + 1,
                    "total": total,
                })

        return self._results

    async def run_parallel(
        self,
        output_dir: str,
        progress_callback=None,
    ) -> None:
        """
        병렬 모드: Creator가 on_song_created로 큐에 넣으면 바로 다운로드 시작.
        Creator와 동시에 실행됨.
        """
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        collected_count = 0
        while self._running or not self._queue.empty():
            try:
                song = await asyncio.wait_for(self._queue.get(), timeout=5.0)
            except asyncio.TimeoutError:
                continue

            results = await self._download_song(song, out_dir)
            self._results.extend(results)
            collected_count += 1

            if progress_callback:
                progress_callback({
                    "current_index": song["index"],
                    "current_title": song["title"],
                    "phase": "collecting",
                    "completed": collected_count,
                    "total": collected_count,  # 동적 총합
                })

        logger.info(f"병렬 수집 완료: {len(self._results)}개 파일")

    def enqueue(self, song_result: dict) -> None:
        """Creator가 곡 생성 완료 시 큐에 추가."""
        self._queue.put_nowait(song_result)

    def stop(self) -> None:
        """병렬 모드 종료 시그널."""
        self._running = False

    def get_results(self) -> list[dict]:
        """수집된 전체 결과."""
        return self._results

    async def _download_song(self, song: dict, out_dir: Path) -> list[dict]:
        """곡 하나의 v1, v2를 다운로드."""
        results = []
        index = song["index"]
        title = song["title"]
        clips = song.get("clips", [])

        for slot, clip in enumerate(clips[:2], 1):
            clip_id = clip.get("id", "")
            audio_url = clip.get("audio_url", "")

            if not clip_id:
                results.append({
                    "index": index, "title": title, "slot": slot,
                    "suno_id": "", "file_path": "", "status": "failed",
                })
                continue

            safe_title = re.sub(r'[\u4E00-\u9FFF\u3400-\u4DBF\\/:*?"<>|]', "_", title)
            prefix = f"{index:02d}_{safe_title}_v{slot}"

            file_path = await self._download_clip(clip_id, audio_url, out_dir, prefix)

            results.append({
                "index": index,
                "title": title,
                "slot": slot,
                "suno_id": clip_id,
                "file_path": file_path,
                "status": "completed" if file_path else "download_failed",
            })

            logger.info(f"[{index:02d}] {title} v{slot}: {'OK' if file_path else 'FAIL'}")

        return results

    async def _download_clip(
        self,
        clip_id: str,
        audio_url: str,
        out_dir: Path,
        prefix: str,
    ) -> str:
        """MP3 다운로드. HTTP 직접 → CDN → 페이지 대기."""
        dest = out_dir / f"{prefix}.mp3"
        cookies = await self._context.cookies("https://suno.com")
        cookie_header = "; ".join(f"{c['name']}={c['value']}" for c in cookies)
        headers = {
            "Cookie": cookie_header,
            "Referer": "https://suno.com/",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/136.0.0.0 Safari/537.36 Edg/136.0.0.0"
            ),
        }

        urls = []
        if audio_url:
            urls.append(audio_url)
        urls += [
            f"https://cdn1.suno.ai/{clip_id}.mp3",
            f"https://cdn2.suno.ai/{clip_id}.mp3",
        ]

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
                except Exception as e:
                    logger.debug(f"다운로드 실패 ({url[:50]}): {e}")

        # Fallback: 곡 페이지에서 대기 후 다운로드 (탭 추가 → 완료 후 닫기)
        return await self._wait_and_download(clip_id, dest, headers)

    async def _wait_and_download(self, clip_id: str, dest: Path, headers: dict) -> str:
        """Suno 곡 페이지에서 생성 완료 대기 후 다운로드. 탭 열고 → 다운 → 닫기."""
        page = await self._context.new_page()
        try:
            await page.goto(f"https://suno.com/song/{clip_id}", wait_until="domcontentloaded", timeout=30_000)

            for _ in range(60):  # 최대 5분
                audio_src = await page.evaluate(
                    "() => { const a = document.querySelector('audio'); return a ? a.src : ''; }"
                )
                if audio_src and audio_src.startswith("http"):
                    async with aiohttp.ClientSession() as http:
                        async with http.get(audio_src, headers=headers, timeout=aiohttp.ClientTimeout(total=120)) as resp:
                            if resp.status == 200:
                                content = await resp.read()
                                if len(content) > 10_000:
                                    dest.write_bytes(content)
                                    logger.info(f"페이지 다운로드 OK: {dest.name}")
                                    return str(dest)
                await asyncio.sleep(5)

            logger.error(f"페이지 다운로드 실패 (5분 초과): {clip_id}")
            return ""
        except Exception as e:
            logger.error(f"페이지 다운로드 에러 [{clip_id}]: {e}")
            return ""
        finally:
            await page.close()
