"""
Suno v5.5 자동화.

설계:
  - 저장된 세션(suno_context.json)으로 Edge 브라우저 실행
  - asyncio.Semaphore 로 최대 N개 병렬 생성
  - page.wait_for_response() 로 API 응답 인터셉트 → 안정적인 완료 감지
  - 직접 HTTP 다운로드 (UI 다운로드보다 빠름)

셀렉터가 바뀌면 SELECTORS 딕셔너리만 수정.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import traceback
import aiohttp
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

logger = logging.getLogger("suno_automation")

# ──────────────────────── UI 셀렉터 ─────────────────────────────────────────
# 레코딩으로 확인된 v5.5 실제 셀렉터 우선, 하드코딩 fallback
SELECTORS: dict[str, str] = {
    # Lyrics — testid로 안정적
    "lyrics_area": (
        "[data-testid='lyrics-textarea'], "
        "textarea[placeholder*='Write some lyrics'], "
        "textarea[placeholder*='lyrics']"
    ),
    # 제목 — placeholder 안정적
    "title_input": (
        "input[placeholder='Song Title (Optional)'], "
        "input[placeholder*='Song Title'], "
        "input[placeholder*='Title']"
    ),
    # Create 버튼 — aria-label 녹화로 확인됨 (가장 안정적)
    "create_btn": (
        "[aria-label='Create song'], "
        "button:has-text('Create'), "
        "[data-testid='create-button']"
    ),
    # 곡 카드 (DOM 폴링 fallback용)
    "song_card": (
        "[data-testid='song-card'], "
        "a[href*='/song/'], "
        "[class*='SongCard'], "
        "[class*='song-card']"
    ),
}

# Edge 실행 파일 경로
_EDGE_EXES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
]


def _find_exe() -> str | None:
    for p in _EDGE_EXES:
        if Path(p).exists():
            return p
    return None


def _session_path() -> Path:
    return settings.browser_sessions_dir / "suno_context.json"


# ──────────────────────────── SunoAutomation ────────────────────────────────

class SunoAutomation:
    """
    병렬 Suno 곡 생성 + 다운로드.

    사용법:
        async with SunoAutomation() as suno:
            results = await suno.batch_create(songs, output_dir)
    """

    def __init__(self, max_concurrent: int = 3, headless: bool = False) -> None:
        self._max_concurrent = max_concurrent
        self._headless = headless
        self._pw: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None

    # ── context manager ──────────────────────────────────────────────────────

    async def __aenter__(self) -> "SunoAutomation":
        await self._start()
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self._stop()

    async def _start(self) -> None:
        sp = _session_path()
        if not sp.exists():
            raise RuntimeError(
                "저장된 Suno 세션이 없습니다. 먼저 로그인해주세요."
            )

        exe = _find_exe()
        self._pw = await async_playwright().start()

        self._browser = await self._pw.chromium.launch(
            executable_path=exe,
            headless=self._headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--exclude-switches=enable-automation",
                "--no-first-run",
                "--disable-infobars",
            ],
        )
        # 저장된 세션(쿠키) 로드
        self._context = await self._browser.new_context(
            storage_state=str(sp),
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/136.0.0.0 Safari/537.36 Edg/136.0.0.0"
            ),
        )
        logger.info(f"SunoAutomation 시작: exe={exe}, headless={self._headless}")

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
        logger.info("SunoAutomation 종료")

    # ── 배치 생성 (병렬) ─────────────────────────────────────────────────────

    async def batch_create(
        self,
        songs: list[dict],
        output_dir: str,
        task_tracker: dict | None = None,
    ) -> list[dict]:
        """
        여러 곡을 개별 생성.
        Suno는 1회 Create 시 2곡 출력 → 곡별로 slot 1, 2 저장.

        songs 예시:
          [{"title": "...", "lyrics": "...", "suno_prompt": "...",
            "is_instrumental": False, "index": 1}, ...]

        Returns:
          [{"index": int, "title": str, "file_path": str,
            "suno_id": str, "status": "completed"|"failed", "slot": 1|2}, ...]
        """
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        sem = asyncio.Semaphore(self._max_concurrent)
        total = len(songs)

        if task_tracker is not None:
            task_tracker["total_batches"] = total
            task_tracker["completed_batches"] = 0
            task_tracker["tracks_collected"] = 0

        async def _process_single(idx: int, song: dict) -> list[dict]:
            async with sem:
                logger.info(f"배치 [{idx+1}/{total}] 시작: {song.get('title')}")

                # 최대 2회 재시도 (Suno fail 시)
                result = None
                last_error = ""
                for attempt in range(3):
                    page = await self._context.new_page()
                    try:
                        result = await self._create_one(
                            page=page,
                            title=song.get("title", f"Track_{idx+1}"),
                            lyrics=song.get("lyrics", "") if not song.get("is_instrumental") else "",
                            style_prompt=song.get("suno_prompt", ""),
                            is_instrumental=song.get("is_instrumental", False),
                        )
                        await page.close()
                        break
                    except Exception as e:
                        last_error = str(e) or f"{type(e).__name__}"
                        try:
                            await page.close()
                        except Exception:
                            pass
                        if attempt < 2:
                            wait_sec = 15 * (attempt + 1)
                            logger.warning(f"배치 [{idx+1}/{total}] 시도 {attempt+1} 실패, {wait_sec}초 후 재시도: {last_error}")
                            await asyncio.sleep(wait_sec)
                        else:
                            logger.error(f"배치 [{idx+1}/{total}] 최종 실패: {last_error}")

                if result is None:
                    if task_tracker is not None:
                        task_tracker.setdefault("errors", []).append(last_error)
                        task_tracker["completed_batches"] = task_tracker.get("completed_batches", 0) + 1
                    return [
                        {
                            "index": song.get("index", idx + 1),
                            "title": song.get("title", ""),
                            "suno_id": "",
                            "file_path": "",
                            "status": "failed",
                            "slot": slot,
                            "error": last_error,
                        }
                        for slot in [1, 2]
                    ]

                try:
                    clips = result["clips"]

                    async def _dl_one(clip: dict, slot: int) -> dict:
                        safe_title = re.sub(r'[\u4E00-\u9FFF\u3400-\u4DBF\\/:*?"<>|]', "_", song.get("title", "unknown"))
                        prefix = f"{song.get('index', idx+1):02d}_{safe_title}_v{slot}"
                        file_path = await self._download(
                            clip_id=clip["id"],
                            audio_url=clip.get("audio_url", ""),
                            out_dir=out_dir,
                            prefix=prefix,
                        )
                        return {
                            "index":     song.get("index", idx + 1),
                            "title":     song.get("title", f"Track {idx + 1}"),
                            "suno_id":   clip["id"],
                            "file_path": file_path,
                            "status":    "completed" if file_path else "download_failed",
                            "slot":      slot,
                        }

                    dl_tasks = [_dl_one(clip, slot + 1) for slot, clip in enumerate(clips)]
                    out = list(await asyncio.gather(*dl_tasks))

                    if task_tracker is not None:
                        task_tracker["completed_batches"] = task_tracker.get("completed_batches", 0) + 1
                        task_tracker["tracks_collected"] = task_tracker.get("tracks_collected", 0) + len([o for o in out if o["status"] == "completed"])

                    logger.info(f"배치 [{idx+1}/{total}] 완료")
                    return out

                except Exception as e:
                    err_msg = str(e) or f"{type(e).__name__}"
                    err_tb = traceback.format_exc()
                    logger.error(f"배치 [{idx+1}/{total}] 다운로드 실패: {err_msg}\n{err_tb}")
                    if task_tracker is not None:
                        task_tracker.setdefault("errors", []).append(err_msg)
                        task_tracker["completed_batches"] = task_tracker.get("completed_batches", 0) + 1
                    return [
                        {
                            "index":     song.get("index", idx + 1),
                            "title":     song.get("title", ""),
                            "suno_id":   "",
                            "file_path": "",
                            "status":    "failed",
                            "slot":      slot,
                            "error":     err_msg,
                        }
                        for slot in [1, 2]
                    ]

        tasks = [_process_single(i, song) for i, song in enumerate(songs)]
        nested = await asyncio.gather(*tasks)
        results = [item for sublist in nested for item in sublist]

        if task_tracker is not None:
            task_tracker["status"] = "completed"

        return results

    # ── 단일 곡 생성 ─────────────────────────────────────────────────────────

    async def _create_one(
        self,
        page: Page,
        title: str,
        lyrics: str,
        style_prompt: str,
        is_instrumental: bool,
    ) -> dict:
        """
        suno.com/create 로 이동 → 입력 → Create 클릭 → 완료 대기.

        레시피가 있으면 녹화된 셀렉터로 재생, 없으면 기존 하드코딩 셀렉터 사용.
        """
        await page.goto("https://suno.com/create", wait_until="domcontentloaded", timeout=30_000)
        await page.wait_for_timeout(3_000)

        # 페이지 상태 디버그 스크린샷
        debug_dir = Path(__file__).parent.parent / "storage" / "debug"
        debug_dir.mkdir(parents=True, exist_ok=True)
        try:
            await page.screenshot(path=str(debug_dir / f"create_page_{title[:20].replace(' ','_')}.png"))
        except Exception:
            pass

        # Advanced 모드 전환 (기본이 Simple 모드)
        await self._switch_to_custom_mode(page)

        # Advanced 전환 후 스크린샷
        try:
            await page.screenshot(path=str(debug_dir / f"after_advanced_{title[:20].replace(' ','_')}.png"))
        except Exception:
            pass

        recipe = get_recipe()
        if recipe and recipe.get("actions"):
            logger.info(f"레시피 재생 모드 ({len(recipe['actions'])}개 동작): {title}")
            await self._replay_recipe(page, title, lyrics, style_prompt, is_instrumental, recipe)
        else:
            logger.info(f"하드코딩 셀렉터 모드 (레시피 없음): {title}")
            if not is_instrumental and lyrics:
                await self._react_fill(page, SELECTORS["lyrics_area"], lyrics, "lyrics")
            if style_prompt:
                if not await self._fill_style_by_position(page, style_prompt):
                    logger.warning("스타일 입력 실패, 건너뜀")
            if title:
                await self._react_fill_title(page, title)

        clips = await self._click_create_and_wait(page, title)
        return {"clips": clips}

    async def _switch_to_custom_mode(self, page: Page) -> None:
        """
        Suno create 페이지를 Advanced(Custom) 모드로 전환.
        Simple/Advanced 탭이 있을 때만 클릭.
        """
        try:
            # 먼저 'Advanced' 텍스트 요소 존재 여부 확인
            adv_el = await page.query_selector("text=Advanced")
            if adv_el:
                await adv_el.click()
                logger.info("Advanced 탭 클릭 완료")
                await page.wait_for_timeout(2_000)
            else:
                logger.info("Advanced 탭 없음 (이미 Advanced 모드)")
        except Exception as e:
            logger.warning(f"Advanced 모드 전환 실패: {e}")

    async def _replay_recipe(
        self,
        page: Page,
        title: str,
        lyrics: str,
        style_prompt: str,
        is_instrumental: bool,
        recipe: dict,
    ) -> None:
        """
        녹화된 레시피를 순서대로 재생.
        - lyrics → React setter (data-testid 안정적)
        - style  → 위치 기반 JS (_fill_style_by_position) - placeholder가 랜덤이므로 selector 사용 불가
        - title  → JS input setter
        - create → _click_create_and_wait 에서 처리하므로 여기선 break
        """
        for action in recipe["actions"]:
            role  = action.get("role", "other")
            atype = action.get("type", "")

            if atype != "fill":
                if atype == "click" and role == "create":
                    break  # Create 클릭은 _click_create_and_wait 가 담당
                continue

            if role == "lyrics":
                value = "" if is_instrumental else (lyrics or "")
                await self._react_fill(page, SELECTORS["lyrics_area"], value, "lyrics")

            elif role in ("style", "other"):
                # placeholder가 매번 바뀌므로 위치 기반으로 채움
                filled = await self._fill_style_by_position(page, style_prompt or "")
                if not filled:
                    logger.warning("스타일 입력 실패 (건너뜀)")

            elif role == "title":
                await self._react_fill_title(page, title or "")

            await page.wait_for_timeout(300)

    async def _react_fill(self, page: Page, selector: str, value: str, label: str) -> None:
        """React nativeValueSetter로 textarea/input을 채운다. 셀렉터 목록을 순서대로 시도."""
        for sel in [s.strip() for s in selector.split(",")]:
            try:
                ok = await page.evaluate("""
                    ([sel, text]) => {
                        const el = document.querySelector(sel);
                        if (!el) return false;
                        const proto = el.tagName === 'TEXTAREA'
                            ? window.HTMLTextAreaElement.prototype
                            : window.HTMLInputElement.prototype;
                        const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
                        el.focus();
                        setter.call(el, text);
                        el.dispatchEvent(new Event('input',  {bubbles: true}));
                        el.dispatchEvent(new Event('change', {bubbles: true}));
                        return true;
                    }
                """, [sel, value])
                if ok:
                    logger.info(f"{label} 입력 완료: {value[:40]}...")
                    return
            except Exception:
                pass
        # fallback: Playwright fill
        for sel in [s.strip() for s in selector.split(",")]:
            try:
                el = await page.wait_for_selector(sel, timeout=5_000)
                await el.click()
                await page.wait_for_timeout(100)
                await el.fill(value)
                logger.info(f"{label} 입력 완료 (fallback): {value[:40]}...")
                return
            except Exception:
                pass
        logger.warning(f"{label} 입력 실패 (모든 방법 실패)")

    async def _react_fill_title(self, page: Page, title: str) -> None:
        """제목 input에 React setter로 입력."""
        try:
            ok = await page.evaluate("""
                (text) => {
                    const inputs = Array.from(document.querySelectorAll('input'));
                    const el = inputs.find(i => {
                        const ph = i.placeholder || '';
                        return ph.includes('Optional') || ph.toLowerCase().includes('song title');
                    });
                    if (!el) return false;
                    const setter = Object.getOwnPropertyDescriptor(
                        window.HTMLInputElement.prototype, 'value'
                    ).set;
                    el.focus();
                    setter.call(el, text);
                    el.dispatchEvent(new Event('input',  {bubbles: true}));
                    el.dispatchEvent(new Event('change', {bubbles: true}));
                    return true;
                }
            """, title)
            if ok:
                logger.info(f"제목 입력 완료: {title}")
                return
        except Exception as e:
            logger.warning(f"제목 JS 입력 실패: {e}")
        # fallback
        await self._react_fill(page, SELECTORS["title_input"], title, "title")

    async def _fill_style_by_position(self, page: Page, style_prompt: str) -> bool:
        """
        Suno v5.5: 스타일 textarea = lyrics-textarea 다음의 첫 번째 textarea.
        Playwright visibility 체크를 우회해 React nativeValueSetter로 직접 입력.
        """
        try:
            result = await page.evaluate("""
                (text) => {
                    const lyricsTA = document.querySelector('[data-testid="lyrics-textarea"]');
                    const all = Array.from(document.querySelectorAll('textarea'));
                    let target = null;

                    if (lyricsTA) {
                        const idx = all.indexOf(lyricsTA);
                        for (let i = idx + 1; i < all.length; i++) {
                            const ph = all[i].placeholder || '';
                            if (!ph.includes('Ask me')) { target = all[i]; break; }
                        }
                    }
                    if (!target) {
                        // fallback: Ask me anything 이외의 첫 번째 textarea
                        target = all.find(t => !(t.placeholder||'').includes('Ask me') &&
                                               !(t.placeholder||'').includes('Write some lyrics'));
                    }
                    if (!target) return false;

                    // React nativeValueSetter 사용
                    const setter = Object.getOwnPropertyDescriptor(
                        window.HTMLTextAreaElement.prototype, 'value'
                    ).set;
                    target.focus();
                    setter.call(target, text);
                    target.dispatchEvent(new Event('input', {bubbles: true}));
                    target.dispatchEvent(new Event('change', {bubbles: true}));
                    return true;
                }
            """, style_prompt)
            if result:
                logger.info(f"스타일 입력 완료 (React setter): {style_prompt[:40]}...")
                return True
        except Exception as e:
            logger.warning(f"스타일 JS 입력 실패: {e}")
        return False


    async def _click_create_btn(self, page: Page, title: str) -> None:
        """Create 버튼 클릭. aria-label → text → JS 순으로 시도."""
        # 1) CSS selector 시도
        for sel in [s.strip() for s in SELECTORS["create_btn"].split(",")]:
            try:
                await page.wait_for_selector(sel, timeout=5_000)
                await page.click(sel)
                await page.wait_for_timeout(300)
                logger.info(f"Create 클릭됨 (selector): {title}")
                return
            except Exception:
                continue

        # 2) JS fallback: 'Create' 텍스트를 가진 버튼 찾기
        clicked = await page.evaluate("""
            () => {
                const btns = Array.from(document.querySelectorAll('button'));
                const btn = btns.find(b => {
                    const t = (b.textContent || b.innerText || '').trim();
                    return t === 'Create' || t === 'Create song' || t.startsWith('Create');
                });
                if (btn) { btn.click(); return true; }
                return false;
            }
        """)
        if clicked:
            logger.info(f"Create 클릭됨 (JS fallback): {title}")
            return

        raise RuntimeError(f"Create 버튼을 찾을 수 없습니다: {title}")

    async def _click_create_and_wait(self, page: Page, title: str) -> list[dict]:
        """
        Create 클릭 → API 응답 인터셉트로 clip 정보 수집.
        반환: [{id: str, audio_url: str}, ...]  최대 2개.

        인터셉트 전략:
          1) suno.com / suno.ai 의 모든 JSON 응답을 관찰
          2) 응답에 'clips' 배열이 있으면 id + audio_url 추출
          3) 10초 내 2개 미달 → DOM 폴링 fallback (clip_id만 수집, audio_url 없음)
        """
        uuid_re = re.compile(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
            re.IGNORECASE,
        )
        clips: list[dict] = []   # {id, audio_url}
        seen_ids: set[str] = set()

        async def on_response(response):
            url = response.url
            if "suno" not in url:
                return
            if response.status != 200:
                return
            ct = response.headers.get("content-type", "")
            if "json" not in ct:
                return
            try:
                data = await response.json()
            except Exception:
                return

            # clips 배열 탐색 (다양한 응답 구조 처리)
            raw_clips = data.get("clips") or data.get("data") or []
            if not isinstance(raw_clips, list):
                return
            for c in raw_clips:
                if not isinstance(c, dict):
                    continue
                cid = c.get("id") or c.get("clip_id", "")
                if not cid or not uuid_re.match(cid):
                    continue
                audio_url = (
                    c.get("audio_url") or
                    c.get("stream_audio_url") or
                    c.get("url") or
                    ""
                )
                if cid in seen_ids:
                    # 이미 있는 clip이지만 audio_url 업데이트 시도
                    if audio_url:
                        for existing in clips:
                            if existing["id"] == cid and not existing.get("audio_url"):
                                existing["audio_url"] = audio_url
                                logger.info(f"clip audio_url 업데이트: {cid[:8]} url={audio_url[:40]}")
                    continue
                seen_ids.add(cid)
                clips.append({"id": cid, "audio_url": audio_url})
                logger.info(f"clip 인터셉트: {cid[:8]} audio_url={bool(audio_url)}")

        page.on("response", on_response)
        await self._click_create_btn(page, title)

        # 단계 1: clip ID 수집 (최대 60초) + Suno fail 감지
        for tick in range(120):
            if len(clips) >= 2:
                break
            # Suno UI에서 에러/실패 감지 (5초마다)
            if tick > 0 and tick % 10 == 0:
                fail_detected = await page.evaluate("""
                    () => {
                        const body = document.body.innerText || '';
                        // Suno의 에러 메시지 패턴
                        if (body.includes('Something went wrong') ||
                            body.includes('Failed to create') ||
                            body.includes('Error creating') ||
                            body.includes('Insufficient credits') ||
                            body.includes('rate limit') ||
                            body.includes('try again')) {
                            return body.substring(0, 200);
                        }
                        // 에러 배너/toast 감지
                        const errEls = document.querySelectorAll('[role="alert"], .error, .toast-error, [class*="error"], [class*="Error"]');
                        for (const el of errEls) {
                            const t = (el.textContent || '').trim();
                            if (t && t.length > 5) return t.substring(0, 200);
                        }
                        return null;
                    }
                """)
                if fail_detected:
                    logger.error(f"Suno UI 에러 감지: {fail_detected}")
                    page.remove_listener("response", on_response)
                    raise RuntimeError(f"Suno 생성 실패: {fail_detected}")
            await asyncio.sleep(0.5)

        if len(clips) < 2:
            logger.info(f"API 인터셉트로 clip ID 미달({len(clips)}개), DOM 폴링 전환: {title}")
            dom_clips = await self._poll_for_clips(page, timeout_sec=120)
            # DOM 폴링 결과를 clips에 병합 (audio_url 없이 ID만)
            existing_ids = {c["id"] for c in clips}
            for dc in dom_clips:
                if dc["id"] not in existing_ids:
                    clips.append(dc)

        logger.info(f"clip ID 수집: {[c['id'][:8] for c in clips[:2]]}")

        # 단계 2: audio_url 대기 (최대 5분, clip ID가 있는 경우)
        # Suno는 생성 완료 후 API로 audio_url을 전달함
        if any(not c.get("audio_url") for c in clips[:2]):
            logger.info(f"audio_url 대기 중 (최대 5분): {title}")
            for _ in range(300):  # 최대 300 * 1초 = 5분
                if all(c.get("audio_url") for c in clips[:2]):
                    break
                await asyncio.sleep(1)

        page.remove_listener("response", on_response)
        logger.info(f"clips 수집 완료: {[(c['id'][:8], bool(c.get('audio_url'))) for c in clips[:2]]}")
        return clips[:2]

    async def _poll_for_clips(self, page: Page, timeout_sec: int) -> list[dict]:
        """
        DOM에서 song card href UUID를 수집 (fallback).
        반환: [{id, audio_url: ""}]
        """
        deadline = asyncio.get_event_loop().time() + timeout_sec
        uuid_re = re.compile(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
            re.IGNORECASE,
        )
        seen: dict[str, dict] = {}  # id → clip dict

        while asyncio.get_event_loop().time() < deadline:
            cards = await page.query_selector_all(SELECTORS["song_card"])
            for card in cards:
                href = await card.get_attribute("href") or ""
                m = uuid_re.search(href)
                if m and m.group() not in seen:
                    seen[m.group()] = {"id": m.group(), "audio_url": ""}
                if len(seen) >= 2:
                    return list(seen.values())[:2]

            if len(seen) >= 2:
                return list(seen.values())[:2]

            await asyncio.sleep(3)

        if seen:
            return list(seen.values())[:2]
        raise TimeoutError(f"곡 생성이 {timeout_sec}초 내에 완료되지 않았습니다.")

    # ── 다운로드 ─────────────────────────────────────────────────────────────

    async def _download(
        self,
        clip_id: str,
        out_dir: Path,
        prefix: str,
        audio_url: str = "",
    ) -> str:
        """
        MP3 다운로드. 시도 순서:
          1) API 인터셉트로 얻은 audio_url (가장 빠름)
          2) CDN 직접 URL 추측 (cdn1/cdn2.suno.ai)
          3) 곡 페이지에서 <audio> src 추출
        """
        if not clip_id:
            return ""

        dest = out_dir / f"{prefix}.mp3"
        cookies = await self._context.cookies("https://suno.com")
        cookie_header = "; ".join(f"{c['name']}={c['value']}" for c in cookies)
        headers = {
            "Cookie":     cookie_header,
            "Referer":    "https://suno.com/",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/136.0.0.0 Safari/537.36 Edg/136.0.0.0"
            ),
        }

        # 시도할 URL 목록 구성
        candidate_urls: list[str] = []
        if audio_url:
            candidate_urls.append(audio_url)
        candidate_urls += [
            f"https://cdn1.suno.ai/{clip_id}.mp3",
            f"https://cdn2.suno.ai/{clip_id}.mp3",
        ]

        async with aiohttp.ClientSession() as http:
            for url in candidate_urls:
                try:
                    async with http.get(
                        url,
                        headers=headers,
                        timeout=aiohttp.ClientTimeout(total=120),
                    ) as resp:
                        if resp.status == 200:
                            content = await resp.read()
                            dest.write_bytes(content)
                            logger.info(f"다운로드 완료: {dest.name} ({len(content)//1024}KB) [{url[:50]}]")
                            return str(dest)
                        logger.warning(f"다운로드 {resp.status}: {url[:60]}")
                except Exception as e:
                    logger.warning(f"다운로드 실패 ({url[:50]}): {e}")

        # 마지막 수단: 곡 페이지에서 <audio> src 추출
        return await self._audio_tag_download(clip_id, dest, headers)

    async def _audio_tag_download(self, clip_id: str, dest: Path, headers: dict) -> str:
        """suno.com/song/{id} 페이지의 <audio> src를 추출해 다운로드."""
        page = await self._context.new_page()
        try:
            await page.goto(
                f"https://suno.com/song/{clip_id}",
                wait_until="domcontentloaded",
                timeout=20_000,
            )
            await page.wait_for_timeout(3_000)

            audio_src = await page.evaluate(
                "() => { const a = document.querySelector('audio'); return a ? a.src : ''; }"
            )
            if audio_src and audio_src.startswith("http"):
                async with aiohttp.ClientSession() as http:
                    async with http.get(
                        audio_src, headers=headers,
                        timeout=aiohttp.ClientTimeout(total=120),
                    ) as resp:
                        if resp.status == 200:
                            dest.write_bytes(await resp.read())
                            logger.info(f"audio-tag 다운로드 완료: {dest.name}")
                            return str(dest)

            logger.error(f"모든 다운로드 방법 실패: {clip_id}")
            return ""
        except Exception as e:
            logger.error(f"audio-tag 다운로드 실패 [{clip_id}]: {e}")
            return ""
        finally:
            await page.close()

    # ── 헬퍼 ─────────────────────────────────────────────────────────────────

    async def _click(self, page: Page, selector: str, label: str) -> None:
        for sel in [s.strip() for s in selector.split(",")]:
            try:
                await page.wait_for_selector(sel, timeout=8_000)
                await page.click(sel)
                await page.wait_for_timeout(300)
                return
            except Exception:
                continue
        raise RuntimeError(f"셀렉터 없음: {label} ({selector})")

    async def find_siblings(
        self,
        known_ids: list[str],
        output_dir: str,
    ) -> list[dict]:
        """
        Suno 라이브러리 feed API에서 곡 목록 수집.
        같은 제목의 곡이 2개 → 하나는 이미 있고(known) 다른 하나가 형제.

        Returns: [{"suno_id": str, "sibling_of": str, "file_path": str,
                   "title": str, "status": str}, ...]
        """
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        known_set = set(known_ids)
        results: list[dict] = []

        page = await self._context.new_page()
        all_clips: list[dict] = []
        seen_ids: set[str] = set()

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
                    if cid and cid not in seen_ids:
                        seen_ids.add(cid)
                        all_clips.append({
                            "id": cid,
                            "title": c.get("title", ""),
                            "audio_url": c.get("audio_url", ""),
                        })
            except Exception:
                pass

        try:
            page.on("response", on_response)
            await page.goto("https://suno.com/me", wait_until="domcontentloaded", timeout=30_000)
            await page.wait_for_timeout(5_000)

            for scroll in range(50):
                found = known_set & seen_ids
                if found == known_set:
                    logger.info(f"모든 known ID 발견 (스크롤 {scroll+1}회, {len(all_clips)}곡)")
                    break

                prev = len(all_clips)
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(2_500)

                if len(all_clips) == prev:
                    await page.wait_for_timeout(3_000)
                    if len(all_clips) == prev:
                        logger.info(f"스크롤 끝 ({scroll+1}회, {len(all_clips)}곡, {len(found)}/{len(known_set)} known)")
                        break

            page.remove_listener("response", on_response)
        except Exception as e:
            logger.error(f"라이브러리 스캔 실패: {e}")
        finally:
            await page.close()

        logger.info(f"라이브러리 {len(all_clips)}곡 수집")

        # 제목으로 그룹핑: 같은 제목 = 같은 생성에서 나온 2곡
        from collections import defaultdict
        by_title: dict[str, list[dict]] = defaultdict(list)
        for clip in all_clips:
            title = clip.get("title", "").strip()
            if title:
                by_title[title].append(clip)

        # known에 있는 곡의 제목과 매칭 → 같은 제목의 다른 곡이 형제
        for title, clips in by_title.items():
            known_in_group = [c for c in clips if c["id"] in known_set]
            unknown_in_group = [c for c in clips if c["id"] not in known_set]

            if not known_in_group or not unknown_in_group:
                continue  # 형제 없음

            parent_id = known_in_group[0]["id"]
            for unk in unknown_in_group:
                safe_title = re.sub(r'[\u4E00-\u9FFF\u3400-\u4DBF\\/:*?"<>|]', "_", title)
                prefix = f"v2_{safe_title}"
                file_path = await self._download(
                    clip_id=unk["id"],
                    audio_url=unk.get("audio_url", ""),
                    out_dir=out_dir,
                    prefix=prefix,
                )
                results.append({
                    "suno_id": unk["id"],
                    "sibling_of": parent_id,
                    "file_path": file_path,
                    "title": title,
                    "status": "completed" if file_path else "download_failed",
                })
                logger.info(f"형제 다운로드: '{title}' {unk['id'][:8]} → {'OK' if file_path else 'FAIL'}")

        logger.info(f"형제 스캔 완료: {len(results)}개")
        return results

    async def find_siblings_by_search(
        self,
        titles: list[str],
        known_ids: set[str],
        output_dir: str,
        title_to_index: dict[str, int] | None = None,
    ) -> list[dict]:
        """
        Suno 검색(suno.com/search?q=제목)으로 각 제목의 곡을 찾아 최신 2곡 다운로드.
        기존에 다운받은 곡(known_ids)은 건너뜀.

        Returns: [{"suno_id", "title", "file_path", "status", "slot"}, ...]
        """
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        results: list[dict] = []

        for title in titles:
            if not title:
                continue

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
                                found_clips.append({
                                    "id": cid,
                                    "title": ctitle,
                                    "audio_url": c.get("audio_url", ""),
                                })
                    except Exception:
                        pass

                page.on("response", on_response)

                # /create 페이지의 "Search clips" 검색 사용
                await page.goto("https://suno.com/create", wait_until="domcontentloaded", timeout=30_000)
                await page.wait_for_timeout(3_000)

                search_input = await page.query_selector('input[aria-label="Search clips"]')
                if search_input:
                    await search_input.click()
                    await search_input.fill(title)
                    await page.wait_for_timeout(3_000)
                else:
                    logger.warning(f"Search clips 입력창 못 찾음, 건너뜀: {title}")
                    page.remove_listener("response", on_response)
                    await page.close()
                    continue

                page.remove_listener("response", on_response)

                # known 제외, 최신 2곡
                new_clips = [c for c in found_clips if c["id"] not in known_ids]
                to_dl = new_clips[:2]

                if not to_dl:
                    logger.info(f"'{title}': 새 곡 없음 ({len(found_clips)}곡 중 {len(new_clips)}곡 신규)")
                    await page.close()
                    continue

                logger.info(f"'{title}': {len(to_dl)}곡 다운로드")

                for slot, clip in enumerate(to_dl, 1):
                    safe_title = re.sub(r'[\u4E00-\u9FFF\u3400-\u4DBF\\/:*?"<>|]', "_", title)
                    idx = (title_to_index or {}).get(title, 0)
                    prefix = f"{idx:02d}_{safe_title}_v{slot}" if idx else f"{safe_title}_v{slot}"
                    file_path = await self._download(
                        clip_id=clip["id"],
                        audio_url=clip.get("audio_url", ""),
                        out_dir=out_dir,
                        prefix=prefix,
                    )
                    results.append({
                        "suno_id": clip["id"],
                        "title": title,
                        "file_path": file_path,
                        "status": "completed" if file_path else "download_failed",
                        "slot": slot,
                    })
                    known_ids.add(clip["id"])

            except Exception as e:
                logger.warning(f"'{title}' 검색 실패: {e}")
            finally:
                await page.close()

        logger.info(f"검색 완료: {len(results)}곡 다운로드")
        return results

    async def get_credits(self) -> int:
        """남은 크레딧 수 반환. 실패 시 -1."""
        page = await self._context.new_page()
        try:
            await page.goto("https://suno.com", wait_until="domcontentloaded")
            await page.wait_for_timeout(2_000)
            el = await page.query_selector("[data-testid='credits'], [class*='credits']")
            if el:
                text = await el.inner_text()
                m = re.search(r"\d+", text.replace(",", ""))
                return int(m.group()) if m else -1
            return -1
        except Exception:
            return -1
        finally:
            await page.close()
