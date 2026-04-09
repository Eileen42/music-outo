"""
Gemini API 클라이언트.

멀티키 로테이션 + 429 시 자동 쿨다운.
나중에 SaaS 전환 시 이 클래스를 상속해서
UserAwareGeminiClient(user_id, db) 만들면 됨.
지금은 .env의 키만 사용하는 단순 버전.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time

from google import genai
from google.genai import types as genai_types

logger = logging.getLogger(__name__)

_COOLDOWN_SEC = 60.0  # 429 발생 시 해당 키를 쉬게 할 시간


class GeminiClient:
    def __init__(self, api_keys: list[str]):
        self.api_keys = api_keys  # 빈 리스트 허용 — 호출 시점에 에러
        self.current_index = 0
        self.cooldowns: dict[int, float] = {}  # index → 쿨다운 만료 시각 (time.monotonic)

    # ──────────────────────────── public ────────────────────────────

    async def generate_text(self, prompt: str, model: str = "gemini-2.5-flash") -> str:
        """텍스트 생성. 429 발생 시 다음 키로 자동 전환."""
        last_err: Exception | None = None

        for _ in range(max(len(self.api_keys), 1)):
            key_index, key = self._get_available_key()
            client = genai.Client(api_key=key)
            try:
                response = await asyncio.to_thread(
                    client.models.generate_content,
                    model=model,
                    contents=prompt,
                )
                return response.text
            except Exception as e:
                if self._is_rate_limit(e):
                    logger.warning(f"키 [{key_index}] 429 — 쿨다운 {_COOLDOWN_SEC}s 설정")
                    self._set_cooldown(key_index)
                    last_err = e
                else:
                    raise

        raise last_err or RuntimeError("사용 가능한 Gemini 키가 없습니다.")

    async def generate_json(self, prompt: str, model: str = "gemini-2.5-flash") -> dict | list:
        """JSON 응답 생성. 마크다운 코드블록 자동 제거."""
        full_prompt = prompt + "\n\n반드시 유효한 JSON만 응답하세요. 마크다운 코드블록 없이 순수 JSON만."
        text = await self.generate_text(full_prompt, model)
        text = text.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            text = "\n".join(lines[1:-1]) if len(lines) > 2 else text
        return json.loads(text)

    async def generate_images(
        self,
        prompt: str,
        count: int = 1,
        aspect_ratio: str = "16:9",
    ) -> list[bytes]:
        """
        이미지 생성 (Nano Banana — 무료 티어 지원).
        generateContent + inline_data 방식 사용.
        모델 우선순위: gemini-3.1-flash-image-preview → gemini-2.5-flash-image
        반환값: PNG 바이트 리스트.
        """
        # aspect_ratio 힌트를 프롬프트에 추가
        ratio_hint = {
            "16:9": "wide landscape format, 16:9 aspect ratio, horizontal composition",
            "1:1":  "square format, 1:1 aspect ratio, centered composition",
            "9:16": "vertical portrait format, 9:16 aspect ratio",
        }.get(aspect_ratio, "")
        full_prompt = f"{prompt}. {ratio_hint}" if ratio_hint else prompt

        image_models = [
            "gemini-3.1-flash-image-preview",
            "gemini-2.5-flash-image",
        ]

        last_err: Exception | None = None

        for model in image_models:
            key_index, key = self._get_available_key()
            client = genai.Client(api_key=key)
            try:
                response = await asyncio.to_thread(
                    client.models.generate_content,
                    model=model,
                    contents=[full_prompt],
                    config=genai_types.GenerateContentConfig(
                        response_modalities=["TEXT", "IMAGE"],
                    ),
                )
                result: list[bytes] = []
                for part in response.parts:
                    if part.inline_data is not None:
                        result.append(part.inline_data.data)
                        if len(result) >= count:
                            break
                if result:
                    return result
                # 이미지가 없으면 다음 모델 시도
                last_err = RuntimeError(f"{model}: 응답에 이미지 없음")
            except Exception as e:
                err_str = str(e)
                if self._is_rate_limit(e):
                    logger.warning(f"키 [{key_index}] 429 (images/{model}) — 쿨다운 설정")
                    self._set_cooldown(key_index)
                    last_err = e
                elif "404" in err_str or "NOT_FOUND" in err_str:
                    last_err = e
                    continue  # 다음 모델 시도
                else:
                    raise

        raise last_err or RuntimeError("이미지 생성 실패: 사용 가능한 모델이 없습니다.")

    # ──────────────────────────── internal ────────────────────────────

    def _get_available_key(self) -> tuple[int, str]:
        """
        쿨다운 중이 아닌 키를 순서대로 반환.
        모든 키가 쿨다운 중이면 가장 빨리 풀리는 키 반환.
        """
        if not self.api_keys:
            raise RuntimeError("GEMINI_API_KEYS가 .env에 설정되지 않았습니다.")

        now = time.monotonic()
        total = len(self.api_keys)

        for offset in range(total):
            idx = (self.current_index + offset) % total
            if now >= self.cooldowns.get(idx, 0.0):
                self.current_index = (idx + 1) % total
                return idx, self.api_keys[idx]

        # 전부 쿨다운 중 → 가장 빨리 풀리는 키 강제 사용
        idx = min(self.cooldowns, key=lambda i: self.cooldowns[i])
        logger.warning(f"모든 키 쿨다운 중. 키 [{idx}] 강제 사용.")
        return idx, self.api_keys[idx]

    def _set_cooldown(self, index: int) -> None:
        self.cooldowns[index] = time.monotonic() + _COOLDOWN_SEC

    @staticmethod
    def _is_rate_limit(e: Exception) -> bool:
        msg = str(e).lower()
        return "429" in msg or "quota" in msg or "rate" in msg or "resource_exhausted" in msg


# ──────────────────────────── 싱글톤 ────────────────────────────

def make_gemini_client() -> GeminiClient:
    from config import settings
    return GeminiClient(api_keys=settings.gemini_api_keys)


# 모듈 로드 시 생성 — 키가 없어도 객체는 만들어짐, 호출 시점에 에러
def _init_default() -> GeminiClient:
    try:
        return make_gemini_client()
    except Exception:
        return GeminiClient(api_keys=[])


gemini_client: GeminiClient = _init_default()
