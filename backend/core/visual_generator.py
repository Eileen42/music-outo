"""
이미지 처리, 분위기 분석, AI 이미지 생성.

핵심 기능:
  1. 레퍼런스 이미지를 Gemini Vision으로 분석 → 분위기 JSON
  2. 분위기 JSON을 바탕으로 Imagen 3으로 새 이미지 생성
  3. 업로드 이미지 저장 + 리사이즈
"""
from __future__ import annotations

import asyncio
import base64
import json
import uuid
from pathlib import Path

import aiofiles
from PIL import Image

from core.gemini_client import gemini_client

SUPPORTED_IMAGE_FORMATS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


class VisualGenerator:

    # ──────────────────── 업로드 저장 ────────────────────

    async def process_upload(
        self,
        file_bytes: bytes,
        filename: str,
        project_dir: Path,
        category: str = "additional",
    ) -> dict:
        ext = Path(filename).suffix.lower()
        if ext not in SUPPORTED_IMAGE_FORMATS:
            raise ValueError(f"지원하지 않는 이미지 형식: {ext}")

        images_dir = project_dir / "images"
        images_dir.mkdir(parents=True, exist_ok=True)

        file_id = str(uuid.uuid4())
        dest = images_dir / f"{file_id}{ext}"

        async with aiofiles.open(dest, "wb") as f:
            await f.write(file_bytes)

        info = await asyncio.to_thread(self._get_image_info, dest)
        return {"id": file_id, "filename": filename, "stored_path": str(dest), "category": category, **info}

    def _get_image_info(self, path: Path) -> dict:
        with Image.open(str(path)) as img:
            return {"width": img.width, "height": img.height, "mode": img.mode}

    # ──────────────────── 핵심: 분위기 분석 ────────────────────

    async def analyze_mood(self, image_bytes: bytes, filename: str = "") -> dict:
        """
        Gemini Vision으로 레퍼런스 이미지 분위기를 분석하여 JSON 반환.
        반환 JSON은 generate_from_mood()의 입력으로 사용됨.
        """
        from google import genai
        from google.genai import types as genai_types
        from config import settings

        if not settings.gemini_api_keys:
            raise RuntimeError("GEMINI_API_KEYS가 .env에 설정되지 않았습니다.")

        # 이미지 MIME 타입 결정
        ext = Path(filename).suffix.lower() if filename else ".jpg"
        mime_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                    ".png": "image/png", ".webp": "image/webp"}
        mime_type = mime_map.get(ext, "image/jpeg")

        prompt = """이 이미지를 YouTube 음악 영상용 레퍼런스로 분석하세요.
핵심은 이 이미지의 분위기를 정확히 파악하여, 동일한 분위기의 새 이미지를 AI로 생성할 수 있도록 하는 것입니다.

다음 JSON 형식으로만 응답하세요 (마크다운 없이):
{
  "mood": "전체 분위기 한 줄 설명 (영어)",
  "atmosphere": "공간감/느낌 설명 (영어)",
  "colors": {
    "dominant": ["#hex1", "#hex2", "#hex3"],
    "tone": "warm/cool/neutral/vibrant/muted",
    "warmth": "warm/cool/neutral"
  },
  "style": "사진 스타일 (영어, 예: cinematic photography, digital art, watercolor)",
  "lighting": "조명 설명 (영어)",
  "elements": ["주요 요소1", "요소2", "요소3"],
  "time_of_day": "dawn/morning/afternoon/evening/night/golden hour/blue hour",
  "season": "spring/summer/autumn/winter/unknown",
  "emotion": "감정 키워드들 (영어, 쉼표 구분)",
  "music_genre_fit": "어울리는 음악 장르 (예: lo-fi, ambient, classical)",
  "image_prompt": "이 이미지와 동일한 분위기로 새 이미지를 생성하기 위한 최적화된 영문 프롬프트 (100단어 내외, Imagen 3용)",
  "thumbnail_prompt": "16:9 YouTube 썸네일용 프롬프트 (동일 분위기, 영문)",
  "background_prompt": "1920x1080 영상 배경용 프롬프트 (동일 분위기, 영문, 더 넓고 심플하게)"
}"""

        key = settings.gemini_api_keys[0]
        client = genai.Client(api_key=key)

        image_part = genai_types.Part.from_bytes(data=image_bytes, mime_type=mime_type)

        # 모델 폴백: 할당량 초과 시 다음 모델 시도
        models_to_try = [
            "gemini-2.0-flash",
            "gemini-2.0-flash-lite",
            "gemini-2.5-flash",
            "gemini-2.5-flash-lite",
        ]
        response = None
        last_error = None
        for model in models_to_try:
            try:
                response = await asyncio.to_thread(
                    client.models.generate_content,
                    model=model,
                    contents=[image_part, prompt],
                )
                break
            except Exception as e:
                err_str = str(e)
                if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str or "quota" in err_str.lower():
                    last_error = e
                    continue  # 다음 모델 시도
                raise  # 다른 에러는 즉시 raise

        if response is None:
            raise RuntimeError(f"모든 모델 할당량 초과. 마지막 오류: {last_error}")

        text = response.text.strip()
        # JSON 추출
        if "```" in text:
            lines = text.splitlines()
            start = next((i for i, l in enumerate(lines) if l.strip().startswith("{")), 1)
            end = next((i for i, l in enumerate(reversed(lines)) if l.strip() == "}"), 1)
            text = "\n".join(lines[start: len(lines) - end])

        return json.loads(text)

    # ──────────────────── 핵심: AI 이미지 생성 ────────────────────

    def _build_detailed_prompt(self, mood: dict | None, target: str) -> str:
        """분석 결과에서 간결하고 자연스러운 프롬프트 생성."""
        if not mood:
            return "peaceful landscape, soft focus, natural photograph"

        m = mood
        parts = []

        if m.get("mood"):
            parts.append(f"{m['mood']}, {m.get('atmosphere', '')}")

        colors = m.get("colors", {})
        if colors.get("dominant"):
            parts.append(f"colors: {', '.join(colors['dominant'])}, {colors.get('tone', '')} tone")

        if m.get("style"):
            parts.append(m["style"])
        if m.get("lighting"):
            parts.append(f"{m['lighting']} lighting")
        if m.get("time_of_day"):
            parts.append(m["time_of_day"])
        if m.get("season"):
            parts.append(m["season"])

        if m.get("elements"):
            parts.append(", ".join(m["elements"]))

        existing = m.get("background_prompt" if target == "background" else "thumbnail_prompt", "")
        if existing:
            parts.append(existing)

        parts.append("soft focus, gentle grain, no people")

        return ", ".join(parts)

    async def generate_from_mood(
        self,
        mood: dict | None,
        target: str = "background",  # "thumbnail" | "background" | "both"
        count: int = 2,
        project_dir: Path | None = None,
        custom_prompt: str | None = None,
    ) -> list[dict]:
        """
        분위기 JSON 또는 custom_prompt로 이미지 생성.
        custom_prompt가 있으면 mood 프롬프트 대신 사용.
        반환: [{"stored_path": ..., "target": ..., "prompt": ...}, ...]
        """
        results = []

        # 타겟에 따른 프롬프트 + 비율 선택
        tasks = []
        if target in ("thumbnail", "both"):
            if custom_prompt:
                prompt = custom_prompt
            else:
                prompt = self._build_detailed_prompt(mood, "thumbnail")
            tasks.append(("thumbnail", prompt, "1:1"))
        if target in ("background", "both"):
            if custom_prompt:
                prompt = custom_prompt
            else:
                prompt = self._build_detailed_prompt(mood, "background")
            tasks.append(("background", prompt, "16:9"))

        for tgt, prompt, ratio in tasks:
            full_prompt = (
                f"{prompt}, "
                f"soft focus, gentle film grain, natural photograph, "
                f"no people, no text, no watermark"
            )

            try:
                images_bytes = await gemini_client.generate_images(
                    prompt=full_prompt,
                    count=min(count, 2),  # 무료 할당량 절약
                    aspect_ratio=ratio,
                )

                if project_dir:
                    images_dir = project_dir / "images"
                    images_dir.mkdir(parents=True, exist_ok=True)

                for i, img_bytes in enumerate(images_bytes):
                    if project_dir:
                        file_id = str(uuid.uuid4())
                        dest = images_dir / f"{file_id}_gen.png"
                        dest.write_bytes(img_bytes)
                        stored = str(dest)
                    else:
                        stored = ""

                    results.append({
                        "stored_path": stored,
                        "target": tgt,
                        "prompt": full_prompt,
                        "image_b64": base64.b64encode(img_bytes).decode(),
                        "index": i,
                    })
            except Exception as e:
                results.append({
                    "stored_path": "",
                    "target": tgt,
                    "prompt": full_prompt,
                    "error": str(e),
                })

        return results

    # ──────────────────── 보조 기능 ────────────────────

    async def classify_image(self, image_path: Path, context: str = "") -> dict:
        prompt = f"""
파일명: {image_path.name}
컨텍스트: {context}
YouTube 음악 영상에서의 용도를 분류하세요.
JSON: {{"category": "thumbnail"|"background"|"additional", "reason": "이유", "confidence": 0.0~1.0}}
"""
        try:
            return await gemini_client.generate_json(prompt)
        except Exception:
            return {"category": "additional", "reason": "분류 실패", "confidence": 0.0}

    async def resize_for_youtube(self, input_path: Path, output_path: Path, target: str = "thumbnail") -> Path:
        sizes = {"thumbnail": (1280, 720), "background": (1920, 1080)}
        size = sizes.get(target, (1280, 720))
        await asyncio.to_thread(self._resize, input_path, output_path, size)
        return output_path

    def _resize(self, src: Path, dst: Path, size: tuple[int, int]) -> None:
        with Image.open(str(src)) as img:
            resized = img.resize(size, Image.LANCZOS)
            dst.parent.mkdir(parents=True, exist_ok=True)
            resized.save(str(dst))


visual_generator = VisualGenerator()
