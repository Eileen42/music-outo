"""
Song Collector Agent — Creator Agent 완료 후 곡 다운로드 담당.

흐름:
  1. Creator가 수집한 clip ID + audio_url로 직접 다운로드 시도
  2. audio_url 없는 곡은 Suno 곡 페이지에서 대기 후 다운로드
  3. 파일명: {번호}_{제목}_v1.mp3, {번호}_{제목}_v2.mp3
"""
from __future__ import annotations

import asyncio
import logging
import re
import aiohttp
from pathlib import Path
from typing import Any

from playwright.async_api import (
    async_playwright,
    Browser,
    BrowserContext,
    Playwright,
)

from config import settings
from browser.suno_automation import _find_exe, _session_path

logger = logging.getLogger("suno_collector")


class SunoCollectorAgent:
    """Creator가 생성한 곡을 다운로드하는 에이전트."""

    def __init__(self) -> None:
        self._pw: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None

    async def __aenter__(self) -> "SunoCollectorAgent":
        await self._start()
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self._stop()

    async def _start(self) -> None:
        sp = _session_path()
        if not sp.exists():
            raise RuntimeError("저장된 Suno 세션이 없습니다.")

        exe = _find_exe()
        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(
            executable_path=exe,
            headless=False,
            args=["--disable-blink-features=AutomationControlled", "--no-first-run"],
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
        logger.info("SunoCollectorAgent 시작")

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
        logger.info("SunoCollectorAgent 종료")

    # ── 메인: 곡 수집 ────────────────────────────────────────────────

    async def collect_all(
        self,
        creation_results: list[dict],
        output_dir: str,
        progress_callback=None,
    ) -> list[dict]:
        """
        Creator 결과를 받아서 모든 곡을 다운로드.

        creation_results: [{"index", "title", "clips": [{"id", "audio_url"}], "status"}, ...]
        Returns: [{"index", "title", "slot", "suno_id", "file_path", "status"}, ...]
        """
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        results = []
        total = len(creation_results)
        successful = [r for r in creation_results if r["status"] == "created" and r.get("clips")]

        logger.info(f"곡 수집 시작: {len(successful)}/{total}곡 다운로드 대상")

        for i, song in enumerate(successful):
            index = song["index"]
            title = song["title"]
            clips = song["clips"]

            if progress_callback:
                progress_callback({
                    "current_index": index,
                    "current_title": title,
                    "phase": "collecting",
                    "completed": i,
                    "total": len(successful),
                })

            for slot, clip in enumerate(clips[:2], 1):
                clip_id = clip.get("id", "")
                audio_url = clip.get("audio_url", "")

                if not clip_id:
                    results.append({
                        "index": index, "title": title, "slot": slot,
                        "suno_id": "", "file_path": "", "status": "failed",
                        "error": "clip ID 없음",
                    })
                    continue

                safe_title = re.sub(r'[\u4E00-\u9FFF\u3400-\u4DBF\\/:*?"<>|]', "_", title)
                prefix = f"{index:02d}_{safe_title}_v{slot}"

                # 다운로드 시도
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

            if progress_callback:
                progress_callback({
                    "current_index": index,
                    "current_title": title,
                    "phase": "collected",
                    "completed": i + 1,
                    "total": len(successful),
                })

        completed = len([r for r in results if r["status"] == "completed"])
        logger.info(f"곡 수집 완료: {completed}/{len(results)}개 다운로드 성공")
        return results

    # ── 다운로드 ─────────────────────────────────────────────────────

    async def _download_clip(
        self,
        clip_id: str,
        audio_url: str,
        out_dir: Path,
        prefix: str,
    ) -> str:
        """
        MP3 다운로드. 시도 순서:
          1) audio_url (Creator가 수집한 URL)
          2) CDN 직접 URL
          3) 곡 페이지 대기 → audio tag 추출
        """
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

        # URL 목록 구성
        urls = []
        if audio_url:
            urls.append(audio_url)
        urls += [
            f"https://cdn1.suno.ai/{clip_id}.mp3",
            f"https://cdn2.suno.ai/{clip_id}.mp3",
        ]

        # HTTP 직접 다운로드
        async with aiohttp.ClientSession() as http:
            for url in urls:
                try:
                    async with http.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=120)) as resp:
                        if resp.status == 200:
                            content = await resp.read()
                            if len(content) > 10_000:  # 최소 10KB (빈 파일 방지)
                                dest.write_bytes(content)
                                logger.info(f"다운로드 OK: {dest.name} ({len(content)//1024}KB)")
                                return str(dest)
                except Exception as e:
                    logger.debug(f"다운로드 실패 ({url[:50]}): {e}")

        # Fallback: 곡 페이지에서 대기 후 audio tag
        return await self._wait_and_download_from_page(clip_id, dest, headers)

    async def _wait_and_download_from_page(
        self,
        clip_id: str,
        dest: Path,
        headers: dict,
    ) -> str:
        """Suno 곡 페이지에서 생성 완료를 기다린 후 다운로드."""
        page = await self._context.new_page()
        try:
            await page.goto(f"https://suno.com/song/{clip_id}", wait_until="domcontentloaded", timeout=30_000)

            # 최대 5분 대기 — audio src가 나타날 때까지
            for _ in range(60):
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


suno_collector_agent = SunoCollectorAgent()
