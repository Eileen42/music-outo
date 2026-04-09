"""
Google Flow 이미지 생성 자동화 + 수동 fallback.

전략: Playwright headed + stealth → reCAPTCHA 감지 시 수동 fallback
"""
from __future__ import annotations

import asyncio
import base64
import logging
import shutil
import time
import webbrowser
from pathlib import Path
from typing import Optional

from playwright.async_api import Page

from browser.browser_manager import browser_manager
from config import settings

logger = logging.getLogger(__name__)


class FlowAutomation:
    FLOW_HOME = "https://labs.google/fx/tools/flow"
    FLOW_NEW_PROJECT = "https://labs.google/fx/tools/flow/project/new"
    SERVICE_NAME = "google_flow"

    def __init__(self) -> None:
        self.mode = "auto"  # "auto" | "manual"

    # ── 로그인 ──────────────────────────────────────────────────────────

    async def login(self) -> None:
        """headed 모드로 Google Flow 수동 로그인 → 세션 저장."""
        await browser_manager.login_interactive(self.SERVICE_NAME, self.FLOW_HOME)

    # ── 프롬프트 생성 ─────────────────────────────────────────────────────

    async def generate_prompts(
        self,
        channel_concept: str,
        genre: str,
        mood: str,
        count: int = 5,
    ) -> list[dict]:
        """
        Gemini 텍스트 API(무료)로 이미지 프롬프트 생성.
        반환: [{"index": 1, "prompt": "...", "category": "nature"}, ...]
        """
        from core.gemini_client import make_gemini_client

        client = make_gemini_client()

        system_prompt = f"""Generate {count} image prompts for YouTube music video backgrounds.
Channel concept: {channel_concept}
Genre: {genre}
Mood: {mood}

Rules:
- English only
- Each prompt: 1-2 sentences describing a scene (no text, no watermark)
- Variety: mix categories (nature, indoor_cozy, city_night, city_day, abstract)
- Style: cinematic, high quality, 1920x1080
- Return JSON array only: [{{"index":1,"prompt":"...","category":"..."}}]"""

        response = await client.generate_json(system_prompt)

        suffix = settings.flow_prompts_suffix
        for p in response:
            if suffix and not p["prompt"].endswith(suffix):
                p["prompt"] += suffix

        return response

    # ── 자동 모드 ─────────────────────────────────────────────────────────

    async def create_images_auto(
        self, prompts: list[dict], output_dir: Path
    ) -> list[dict]:
        """
        Playwright headed 모드로 Flow에서 이미지 생성.
        reCAPTCHA 감지 시 self.mode = "manual"로 전환.
        반환: [{"index":1, "status":"success"|"failed"|"manual",
                "file_path":str|None, "error":str|None}]
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        results: list[dict] = []

        context = await browser_manager.get_context(self.SERVICE_NAME)
        page = await context.new_page()

        # stealth 적용 (설치된 경우)
        try:
            from playwright_stealth import stealth_async
            await stealth_async(page)
        except ImportError:
            pass

        try:
            await page.goto(
                self.FLOW_NEW_PROJECT, wait_until="networkidle", timeout=30_000
            )
            await asyncio.sleep(3)

            # 페이지 DOM 스냅샷 저장 (디버깅용)
            await self._save_dom_snapshot(page, output_dir, "initial_load")

            if await self._detect_recaptcha(page):
                logger.warning("reCAPTCHA detected on page load — switching to manual")
                self.mode = "manual"
                await page.close()
                return results

            for prompt_data in prompts:
                if self.mode == "manual":
                    results.append(
                        {
                            "index": prompt_data["index"],
                            "status": "manual",
                            "file_path": None,
                            "error": "switched_to_manual",
                        }
                    )
                    continue

                try:
                    result = await self._generate_single(page, prompt_data, output_dir)
                    results.append(result)
                    await asyncio.sleep(5)
                except Exception as e:
                    err = str(e)
                    logger.error(f"Image {prompt_data['index']} error: {err}")
                    if "recaptcha" in err.lower() or "captcha" in err.lower():
                        self.mode = "manual"
                    results.append(
                        {
                            "index": prompt_data["index"],
                            "status": "failed",
                            "file_path": None,
                            "error": err,
                        }
                    )
        finally:
            await page.close()

        return results

    async def _generate_single(
        self, page: Page, prompt_data: dict, output_dir: Path
    ) -> dict:
        """단일 이미지 생성. 실패 시 DOM 스냅샷 저장."""
        index = prompt_data["index"]
        prompt_text = prompt_data["prompt"]

        # DOM 스냅샷 (셀렉터 디버깅용)
        await self._save_dom_snapshot(page, output_dir, f"before_prompt_{index}")

        # ── 프롬프트 입력 ──
        input_selectors = [
            'textarea',
            '[contenteditable="true"]',
            'input[placeholder*="prompt" i]',
            'input[placeholder*="describe" i]',
            '[role="textbox"]',
        ]
        input_el = None
        for sel in input_selectors:
            try:
                el = page.locator(sel).first
                if await el.is_visible(timeout=3_000):
                    input_el = el
                    break
            except Exception:
                continue

        if input_el is None:
            raise Exception("Could not find prompt input field")

        await input_el.click()
        await input_el.fill("")
        await input_el.type(prompt_text, delay=30)
        await asyncio.sleep(1)

        # ── Generate 버튼 ──
        gen_selectors = [
            'button[aria-label*="Generate" i]',
            'button[aria-label*="Send" i]',
            'button[aria-label*="생성"]',
            'button[type="submit"]',
            'form button',
        ]
        gen_btn = None
        for sel in gen_selectors:
            try:
                el = page.locator(sel).first
                if await el.is_visible(timeout=3_000):
                    gen_btn = el
                    break
            except Exception:
                continue

        if gen_btn is None:
            raise Exception("Could not find Generate button")

        await gen_btn.click()

        # ── 이미지 생성 대기 (최대 settings.flow_generation_timeout 초) ──
        timeout = settings.flow_generation_timeout
        image_locator = page.locator(
            'img[src^="blob:"], img[src^="data:image"], '
            'img[src*="generated"], img[src*="usercontent"]'
        )
        image_appeared = False

        for _ in range(timeout // 5):
            await asyncio.sleep(5)

            if await self._detect_recaptcha(page):
                raise Exception("reCAPTCHA detected during generation")

            try:
                if await image_locator.count() > 0:
                    image_appeared = True
                    break
            except Exception:
                continue

        if not image_appeared:
            await self._save_dom_snapshot(page, output_dir, f"timeout_{index}")
            raise Exception(f"Image generation timed out ({timeout}s)")

        # ── 이미지 저장 ──
        filename = f"bg_{index:03d}.png"
        filepath = output_dir / filename
        img_src = await image_locator.first.get_attribute("src")

        if img_src and img_src.startswith("http"):
            resp = await page.request.get(img_src)
            filepath.write_bytes(await resp.body())
        elif img_src and img_src.startswith("blob:"):
            img_data: str = await page.evaluate(
                """async (src) => {
                    const r = await fetch(src);
                    const blob = await r.blob();
                    return new Promise(resolve => {
                        const reader = new FileReader();
                        reader.onload = () => resolve(reader.result);
                        reader.readAsDataURL(blob);
                    });
                }""",
                img_src,
            )
            _, data = img_data.split(",", 1)
            filepath.write_bytes(base64.b64decode(data))
        else:
            # 백업: 이미지 요소 스크린샷
            await image_locator.first.screenshot(path=str(filepath))

        logger.info(f"Image {index} saved: {filepath}")
        return {"index": index, "status": "success", "file_path": str(filepath), "error": None}

    async def _detect_recaptcha(self, page: Page) -> bool:
        try:
            frame = page.frame_locator('iframe[src*="recaptcha"]')
            if await frame.locator("body").count() > 0:
                return True
        except Exception:
            pass
        try:
            content = await page.content()
            if "unusual traffic" in content.lower() or "captcha" in content.lower():
                return True
        except Exception:
            pass
        return False

    async def _save_dom_snapshot(
        self, page: Page, output_dir: Path, tag: str
    ) -> None:
        try:
            content = await page.content()
            snap = output_dir / f"_dom_{tag}.html"
            snap.write_text(content, encoding="utf-8")
        except Exception:
            pass

    # ── 수동 fallback ─────────────────────────────────────────────────────

    async def fallback_manual(
        self,
        prompts: list[dict],
        output_dir: Path,
        timeout: int = 0,  # 0 → settings 값 사용
    ) -> list[Path]:
        """
        수동 모드 fallback.
        1. 프롬프트를 flow_prompts.txt에 저장
        2. 첫 번째 프롬프트를 클립보드에 복사
        3. Flow 페이지 오픈
        4. 다운로드 폴더 감시 → 이미지 도착 시 output_dir로 이동
        반환: 수집된 이미지 경로 리스트
        """
        from watchdog.observers import Observer
        from watchdog.events import FileSystemEventHandler

        if timeout == 0:
            timeout = settings.flow_manual_timeout

        output_dir.mkdir(parents=True, exist_ok=True)

        # 프롬프트 파일 저장
        prompts_file = output_dir.parent / "flow_prompts.txt"
        with open(prompts_file, "w", encoding="utf-8") as f:
            for p in prompts:
                f.write(f"[Image {p['index']}] {p['prompt']}\n\n")
        logger.info(f"Prompts saved: {prompts_file}")

        # 클립보드 복사 (첫 번째 프롬프트)
        try:
            import pyperclip
            pyperclip.copy(prompts[0]["prompt"])
            logger.info("First prompt copied to clipboard")
        except Exception:
            pass

        webbrowser.open(self.FLOW_HOME)

        # 다운로드 폴더 감시
        collected: list[Path] = []
        watch_dir = Path(settings.chrome_download_dir)

        class _ImageHandler(FileSystemEventHandler):
            def on_created(self_, event):  # noqa: N805
                if event.is_directory:
                    return
                p = Path(event.src_path)
                if p.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
                    return
                time.sleep(2)  # 파일 쓰기 완료 대기
                try:
                    if p.stat().st_size < 50_000:
                        return
                except Exception:
                    return
                idx = len(collected) + 1
                dst = output_dir / f"bg_{idx:03d}{p.suffix.lower()}"
                shutil.copy2(p, dst)
                collected.append(dst)
                logger.info(f"[Manual] Image {idx} collected: {dst}")

        observer = Observer()
        observer.schedule(_ImageHandler(), str(watch_dir), recursive=False)
        observer.start()

        expected = len(prompts)
        start = time.time()
        try:
            while len(collected) < expected and (time.time() - start) < timeout:
                await asyncio.sleep(2)
        finally:
            observer.stop()
            observer.join()

        return collected

    # ── 통합 실행 ─────────────────────────────────────────────────────────

    async def run(
        self,
        channel_concept: str,
        genre: str,
        mood: str,
        project_id: str,
        count: int = 5,
    ) -> dict:
        """
        전체 워크플로우 실행.
        반환: {
            "mode": "auto"|"manual"|"mixed",
            "prompts": [...],
            "results": [...],
            "output_dir": str,
            "total_success": int,
            "total_manual": int,
        }
        """
        output_dir = settings.storage_dir / "projects" / project_id / "bg_candidates"
        output_dir.mkdir(parents=True, exist_ok=True)

        # Step 1: 프롬프트 생성
        prompts = await self.generate_prompts(channel_concept, genre, mood, count)
        logger.info(f"Generated {len(prompts)} prompts")

        # Step 2: 자동 모드
        self.mode = "auto"
        results = await self.create_images_auto(prompts, output_dir)

        # Step 3: 실패/수동 전환된 항목은 수동 fallback
        failed_indices = {r["index"] for r in results if r["status"] in ("failed", "manual")}
        manual_prompts = [p for p in prompts if p["index"] in failed_indices]

        if manual_prompts:
            logger.info(f"Manual fallback for {len(manual_prompts)} prompts")
            manual_paths = await self.fallback_manual(manual_prompts, output_dir)
            path_iter = iter(manual_paths)
            for r in results:
                if r["index"] in failed_indices:
                    path = next(path_iter, None)
                    if path:
                        r["status"] = "manual_success"
                        r["file_path"] = str(path)

        total_success = sum(1 for r in results if r["status"] in ("success", "manual_success"))
        total_manual = sum(1 for r in results if "manual" in r.get("status", ""))
        mode = (
            "auto" if total_manual == 0
            else "manual" if total_success == 0
            else "mixed"
        )

        return {
            "mode": mode,
            "prompts": prompts,
            "results": results,
            "output_dir": str(output_dir),
            "total_success": total_success,
            "total_manual": total_manual,
        }
