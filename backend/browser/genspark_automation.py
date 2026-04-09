"""
Genspark AI 자동화.

대화창에서 가사 + Suno 프롬프트를 배치 생성.
Genspark 응답 실패 시 Gemini API로 자동 폴백.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path

from playwright.async_api import BrowserContext, Page

from browser.browser_manager import BrowserManager
from config import settings
from core.gemini_client import gemini_client

logger = logging.getLogger("genspark_automation")

# ──────────────────────────── Genspark UI 셀렉터 ────────────────────────────

SELECTORS: dict[str, str] = {
    # 대화 입력창
    "chat_input":       "textarea[placeholder*='message'], textarea[placeholder*='Message'], [data-testid='chat-input'], [contenteditable='true']",

    # 전송 버튼
    "send_btn":         "[data-testid='send-button'], button[aria-label*='Send'], button[aria-label*='send'], button[type='submit']",

    # 전송 버튼 비활성화 (스트리밍 중 감지용 — 전송 불가 상태)
    "send_btn_disabled":"button[disabled][aria-label*='Send'], button[disabled][data-testid='send-button']",

    # 마지막 AI 응답 컨테이너
    "last_response":    "[data-testid='message-content']:last-child, [class*='assistant']:last-child [class*='content'], [class*='response']:last-child",

    # 로딩 인디케이터
    "loading_spinner":  "[data-testid='loading'], [class*='loading'], [class*='spinner'], [class*='thinking']",
}

# ──────────────────────────── 가사 생성 프롬프트 템플릿 ────────────────────────────

_LYRICS_PROMPT_TEMPLATE = """\
I need {count} original song lyrics for a YouTube music playlist channel.

Channel: {name}
Genre: {genre}
Mood: {mood}
Target audience: {target_audience}
Language: {language}

For each song, provide:
1. Title
2. Full lyrics (verse → chorus → verse → chorus → bridge → chorus structure)
3. Suno AI style prompt (comma-separated genre tags, mood, instruments, tempo)
4. Whether it's instrumental (true/false)

Respond ONLY with a JSON array in this exact format:
```json
[
  {{
    "title": "Song Title",
    "lyrics": "Full lyrics here...",
    "style_prompt": "genre, mood, instrument, tempo",
    "is_instrumental": false
  }}
]
```
No explanations outside the JSON block.
"""


class GensparkAutomation:
    def __init__(self, manager: BrowserManager) -> None:
        self._manager = manager
        self._error_dir = settings.browser_sessions_dir

    # ──────────────────────────── 로그인 ────────────────────────────

    async def login(self) -> bool:
        """수동 로그인 (최초 1회). Google 계정 로그인 가능."""
        try:
            await self._manager.login_interactive("genspark", "https://www.genspark.ai")
            return True
        except Exception as e:
            logger.error(f"Genspark 로그인 실패: {e}")
            return False

    # ──────────────────────────── 가사 배치 생성 ────────────────────────────

    async def generate_lyrics_batch(
        self,
        channel_concept: dict,
        count: int = 20,
    ) -> list[dict]:
        """
        Genspark 대화창에서 가사 + Suno 프롬프트 배치 생성.

        Args:
            channel_concept: {
                "name": str,
                "genre": str,
                "mood": str,
                "target_audience": str,
                "language": str,
            }
            count: 생성할 곡 수

        Returns:
            [{"title", "lyrics", "style_prompt", "is_instrumental"}, ...]
        """
        context = await self._manager.get_context("genspark")
        page = await context.new_page()

        try:
            logger.info(f"Genspark 가사 생성 시작: {count}곡")
            await page.goto("https://www.genspark.ai", wait_until="networkidle")

            prompt = _LYRICS_PROMPT_TEMPLATE.format(count=count, **channel_concept)

            # 입력창에 프롬프트 입력
            await self._type_message(page, prompt)

            # 전송
            await self._send_message(page)

            # 응답 완료 대기 (최대 120초)
            response_text = await self._wait_for_response(page, timeout_sec=120)

            # JSON 파싱
            result = self._parse_json_response(response_text)
            if result:
                logger.info(f"Genspark 생성 완료: {len(result)}곡")
                return result

            logger.warning("Genspark 응답 파싱 실패 → Gemini 폴백")
            return await self._fallback_gemini(channel_concept, count)

        except Exception as e:
            logger.error(f"Genspark 자동화 실패: {e}")
            await self._save_error_screenshot(page, "generate_lyrics")
            logger.info("Gemini API 폴백 시도")
            return await self._fallback_gemini(channel_concept, count)

        finally:
            await page.close()

    # ──────────────────────────── Gemini 폴백 ────────────────────────────

    async def _fallback_gemini(
        self,
        channel_concept: dict,
        count: int,
    ) -> list[dict]:
        """Genspark 실패 시 Gemini API로 동일한 작업 수행."""
        logger.info("Gemini API로 가사 생성 중...")

        prompt = _LYRICS_PROMPT_TEMPLATE.format(count=count, **channel_concept)
        # JSON 블록 요청이므로 generate_json 사용
        try:
            result = await gemini_client.generate_json(prompt)
            if isinstance(result, list):
                logger.info(f"Gemini 생성 완료: {len(result)}곡")
                return result
            logger.error("Gemini 응답이 리스트가 아님")
            return []
        except Exception as e:
            logger.error(f"Gemini 폴백도 실패: {e}")
            return []

    # ──────────────────────────── 내부 헬퍼 ────────────────────────────

    async def _type_message(self, page: Page, text: str) -> None:
        """입력창에 텍스트 입력."""
        for sel in SELECTORS["chat_input"].split(", "):
            try:
                await page.wait_for_selector(sel.strip(), timeout=10_000)
                await page.fill(sel.strip(), text)
                logger.debug("메시지 입력 완료")
                return
            except Exception:
                continue
        raise RuntimeError(f"입력창을 찾을 수 없음: {SELECTORS['chat_input']}")

    async def _send_message(self, page: Page) -> None:
        """전송 버튼 클릭 또는 Enter 키 전송."""
        # 전송 버튼 시도
        for sel in SELECTORS["send_btn"].split(", "):
            try:
                btn = await page.query_selector(sel.strip())
                if btn and await btn.is_enabled():
                    await btn.click()
                    logger.debug("전송 버튼 클릭")
                    return
            except Exception:
                continue

        # 버튼이 없으면 Ctrl+Enter
        for sel in SELECTORS["chat_input"].split(", "):
            try:
                await page.press(sel.strip(), "Control+Enter")
                logger.debug("Ctrl+Enter 전송")
                return
            except Exception:
                continue

        raise RuntimeError("전송 버튼/단축키 동작 실패")

    async def _wait_for_response(self, page: Page, timeout_sec: int) -> str:
        """
        응답 완료 대기.
        전송 버튼이 다시 활성화되는 시점 또는 로딩 스피너가 사라지는 시점으로 감지.
        """
        import asyncio

        deadline = asyncio.get_event_loop().time() + timeout_sec
        await asyncio.sleep(2)  # 전송 직후 짧은 대기

        while asyncio.get_event_loop().time() < deadline:
            # 로딩 스피너 소멸 확인
            spinner = await page.query_selector(SELECTORS["loading_spinner"])
            # 전송 버튼 활성화 확인
            send_disabled = await page.query_selector(SELECTORS["send_btn_disabled"])

            streaming_done = (spinner is None) and (send_disabled is None)

            if streaming_done:
                await asyncio.sleep(1)  # 안정화 대기
                break

            await asyncio.sleep(2)
        else:
            logger.warning(f"응답 대기 타임아웃 ({timeout_sec}s) — 현재 상태 수집")

        # 마지막 응답 블록에서 텍스트 추출
        return await self._extract_last_response(page)

    async def _extract_last_response(self, page: Page) -> str:
        """페이지에서 마지막 AI 응답 텍스트 추출."""
        for sel in SELECTORS["last_response"].split(", "):
            try:
                elements = await page.query_selector_all(sel.strip())
                if elements:
                    return await elements[-1].inner_text()
            except Exception:
                continue

        # fallback: 전체 body 텍스트
        return await page.inner_text("body")

    def _parse_json_response(self, text: str) -> list[dict] | None:
        """응답 텍스트에서 JSON 배열 추출 및 파싱."""
        # ```json ... ``` 코드블록 우선 탐색
        block_match = re.search(r"```(?:json)?\s*([\s\S]+?)```", text, re.IGNORECASE)
        if block_match:
            json_str = block_match.group(1).strip()
        else:
            # 대괄호로 시작하는 첫 JSON 배열 탐색
            arr_match = re.search(r"\[[\s\S]+\]", text)
            if arr_match:
                json_str = arr_match.group()
            else:
                return None

        try:
            data = json.loads(json_str)
            if isinstance(data, list) and data:
                # 최소 검증: title 필드 존재 여부
                return [d for d in data if isinstance(d, dict) and d.get("title")]
        except json.JSONDecodeError as e:
            logger.warning(f"JSON 파싱 실패: {e}")

        return None

    async def _save_error_screenshot(self, page: Page, tag: str) -> None:
        try:
            self._error_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            path = self._error_dir / f"genspark_error_{tag}_{ts}.png"
            await page.screenshot(path=str(path))
            logger.info(f"에러 스크린샷 저장: {path}")
        except Exception as e:
            logger.warning(f"스크린샷 저장 실패: {e}")
