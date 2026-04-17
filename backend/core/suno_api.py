"""
Suno HTTP API 클라이언트 — 브라우저 없이 직접 HTTP 호출.

Suno 웹앱의 내부 API를 그대로 사용.
세션 쿠키만 있으면 브라우저 없이 곡 생성/조회/다운로드 가능.

사용법:
    from core.suno_api import suno_api
    clips = await suno_api.create_song("peaceful piano", "Morning Light", instrumental=True)
    await suno_api.wait_for_audio(clips)
    await suno_api.download(clips, output_dir)
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)

_SESSION_DIR = Path(__file__).parent.parent / "storage" / "browser_sessions"
_CAPTURE_DIR = Path(__file__).parent.parent / "storage" / "suno_api_captures"

# Suno 내부 API 엔드포인트 (2026-04 캡처 기준)
BASE_URL = "https://studio-api-prod.suno.com"
CDN_URLS = ["https://cdn1.suno.ai", "https://cdn2.suno.ai"]
WEB_URL = "https://suno.com"
GENERATE_ENDPOINT = "/api/generate/v2-web/"
FEED_ENDPOINT = "/api/feed/v3"
CHECK_ENDPOINT = "/api/c/check"
BILLING_ENDPOINT = "/api/billing/info/"
SESSION_ENDPOINT = "/api/session/"


class SunoAPIClient:
    """Suno HTTP API 클라이언트."""

    def __init__(self):
        self._cookies: dict[str, str] = {}
        self._headers: dict[str, str] = {}
        self._token_expires: float = 0

    # ━━━ 세션 관리 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def load_session(self) -> bool:
        """저장된 Suno 세션 쿠키 로드."""
        sp = _SESSION_DIR / "suno_context.json"
        if not sp.exists():
            logger.error("Suno 세션 파일 없음: suno_context.json")
            return False

        data = json.loads(sp.read_text(encoding="utf-8"))
        cookies_list = data.get("cookies", [])

        self._cookies = {}
        for c in cookies_list:
            name = c.get("name", "")
            value = c.get("value", "")
            if name and value:
                self._cookies[name] = value

        has_session = "__session" in self._cookies or "sessionid" in self._cookies
        if not has_session:
            logger.error("Suno 세션 쿠키 없음")
            return False

        self._headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36 Edg/136.0.0.0",
            "Referer": "https://suno.com/",
            "Origin": "https://suno.com",
            "Accept": "application/json",
        }

        logger.info(f"Suno 세션 로드: {len(self._cookies)}개 쿠키")
        return True

    async def refresh_token(self) -> bool:
        """
        Playwright로 Suno에 접속하여 JWT 토큰 갱신.
        저장된 세션 쿠키로 로그인 → 새 __session JWT 발급 → 저장.
        """
        sp = _SESSION_DIR / "suno_context.json"
        if not sp.exists():
            logger.error("세션 파일 없음 — 먼저 Suno 로그인 필요")
            return False

        try:
            from playwright.async_api import async_playwright

            exe = None
            for p in [
                r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            ]:
                if Path(p).exists():
                    exe = p
                    break

            pw = await async_playwright().start()
            browser = await pw.chromium.launch(
                executable_path=exe,
                headless=True,
                args=["--disable-blink-features=AutomationControlled", "--no-first-run"],
            )
            context = await browser.new_context(
                storage_state=str(sp),
                user_agent=self._headers.get("User-Agent", ""),
            )
            page = await context.new_page()

            logger.info("토큰 갱신: Suno 접속 중...")
            await page.goto("https://suno.com/create", wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(5000)

            # 갱신된 쿠키 저장
            cookies = await context.cookies("https://suno.com")
            storage = await context.storage_state()

            # suno_context.json 업데이트
            sp.write_text(json.dumps(storage, ensure_ascii=False), encoding="utf-8")

            # 메모리에도 반영
            self._cookies = {}
            for c in cookies:
                self._cookies[c["name"]] = c["value"]

            # 토큰 캐시
            self._bearer_token = None
            for c in cookies:
                if c["name"] == "__session":
                    self._bearer_token = f"Bearer {c['value']}"
                    exp = c.get("expires", 0)
                    self._token_expires = exp
                    logger.info(f"토큰 갱신 성공 (만료: {exp})")
                    break

            await browser.close()
            await pw.stop()

            return self._bearer_token is not None

        except Exception as e:
            logger.error(f"토큰 갱신 실패: {e}")
            return False

    def _cookie_header(self) -> str:
        """쿠키를 HTTP 헤더 형식으로."""
        return "; ".join(f"{k}={v}" for k, v in self._cookies.items())

    # ━━━ API 캡처 (1회) ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    async def capture_api(self) -> dict:
        """
        Suno 웹앱의 네트워크 요청을 CDP로 캡처하여 API 엔드포인트 파악.
        Edge가 CDP 모드로 열려있어야 함 (port 9224).
        """
        import httpx
        import websockets

        _CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
        captured = {"endpoints": [], "headers": {}, "cookies": {}}

        try:
            # CDP 탭 찾기
            r = httpx.get("http://localhost:9224/json", timeout=3)
            tabs = r.json()
            suno_tab = None
            for t in tabs:
                if "suno.com" in t.get("url", ""):
                    suno_tab = t
                    break

            if not suno_tab:
                logger.error("Suno 탭 없음 — Edge에서 suno.com을 열어주세요")
                return captured

            ws_url = suno_tab["webSocketDebuggerUrl"]

            async with websockets.connect(ws_url, max_size=50_000_000) as ws:
                # Network 이벤트 활성화
                await ws.send(json.dumps({"id": 1, "method": "Network.enable"}))
                await ws.recv()

                logger.info("네트워크 캡처 시작 — Suno에서 곡을 만들어주세요...")
                logger.info("30초 대기 중... (곡 생성 버튼을 누르세요)")

                deadline = time.time() + 60
                while time.time() < deadline:
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=2)
                        event = json.loads(raw)
                        method = event.get("method", "")

                        if method == "Network.requestWillBeSent":
                            req = event.get("params", {}).get("request", {})
                            url = req.get("url", "")
                            req_method = req.get("method", "")
                            headers = req.get("headers", {})

                            # Suno API 요청만 필터링
                            if ("studio-api" in url or "suno.ai/api" in url or "suno.com/api" in url) and req_method in ("POST", "GET", "PUT"):
                                entry = {
                                    "method": req_method,
                                    "url": url,
                                    "headers": dict(headers),
                                    "postData": req.get("postData", ""),
                                    "timestamp": time.time(),
                                }
                                captured["endpoints"].append(entry)
                                logger.info(f"캡처: {req_method} {url[:80]}")

                                # Authorization 헤더 저장
                                if "Authorization" in headers:
                                    captured["headers"]["Authorization"] = headers["Authorization"]
                                if "Cookie" in headers:
                                    captured["cookies"] = headers["Cookie"]

                    except asyncio.TimeoutError:
                        continue

                # Network 비활성화
                await ws.send(json.dumps({"id": 2, "method": "Network.disable"}))

        except Exception as e:
            logger.error(f"API 캡처 실패: {e}")

        # 결과 저장
        capture_file = _CAPTURE_DIR / f"capture_{int(time.time())}.json"
        capture_file.write_text(json.dumps(captured, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info(f"캡처 결과 저장: {capture_file} ({len(captured['endpoints'])}개 엔드포인트)")

        return captured

    # ━━━ 곡 생성 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    async def create_song(
        self,
        prompt: str,
        title: str = "",
        lyrics: str = "",
        instrumental: bool = True,
    ) -> list[dict]:
        """
        곡 생성 요청 → clip ID 목록 반환.
        Suno는 1회 요청에 2개 clip을 생성.
        """
        if not self._cookies:
            if not self.load_session():
                raise RuntimeError("Suno 세션 없음")

        endpoint = f"{BASE_URL}{GENERATE_ENDPOINT}"

        # 캡처된 실제 payload 형식에 맞춤
        payload = {
            "token": None,
            "generation_type": "TEXT",
            "title": title,
            "tags": prompt,  # style/genre/mood 프롬프트는 tags 필드
        }
        if lyrics:
            payload["prompt"] = lyrics
            payload["generation_type"] = "TEXT"
        else:
            payload["prompt"] = ""
            payload["make_instrumental"] = True

        headers = {**self._headers, "Cookie": self._cookie_header()}

        auth = await self._get_auth_token()
        if auth:
            headers["Authorization"] = auth

        # 생성 전 체크 (captcha/rate limit)
        await self._pre_generate_check(headers)

        for attempt in range(2):
            async with aiohttp.ClientSession() as session:
                async with session.post(endpoint, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        clips = data.get("clips", data.get("data", []))
                        logger.info(f"곡 생성 성공: {len(clips)}개 clip, title={title}")
                        return clips
                    elif resp.status == 401 and attempt == 0:
                        logger.info("401 — 토큰 갱신 후 재시도")
                        if await self.refresh_token():
                            headers["Authorization"] = self._bearer_token
                            headers["Cookie"] = self._cookie_header()
                            continue
                    text = await resp.text()
                    logger.error(f"곡 생성 실패: HTTP {resp.status} — {text[:200]}")
                    raise RuntimeError(f"Suno API 에러: {resp.status}")
        raise RuntimeError("Suno API: 재시도 실패")

    async def _pre_generate_check(self, headers: dict) -> None:
        """생성 전 captcha/rate-limit 체크."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{BASE_URL}{CHECK_ENDPOINT}",
                    json={"ctype": "generation"},
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status == 200:
                        logger.debug("pre-check OK")
                    else:
                        text = await resp.text()
                        logger.warning(f"pre-check: HTTP {resp.status} — {text[:100]}")
        except Exception as e:
            logger.warning(f"pre-check 실패 (무시): {e}")

    async def _get_auth_token(self) -> Optional[str]:
        """Bearer 토큰 반환. 만료 시 자동 갱신."""
        # 캐시된 토큰이 있고 유효하면 바로 반환
        if hasattr(self, '_bearer_token') and self._bearer_token:
            if self._token_expires == 0 or time.time() < self._token_expires - 60:
                return self._bearer_token

        # __session 쿠키에서 토큰 추출
        token = self._cookies.get("__session", "")
        if token:
            self._bearer_token = f"Bearer {token}"
            return self._bearer_token

        # 토큰 없으면 갱신 시도
        logger.info("토큰 만료 — 자동 갱신 시도")
        if await self.refresh_token():
            return self._bearer_token

        return None

    # ━━━ 상태 확인 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    async def get_clip_status(self, clip_ids: list[str]) -> list[dict]:
        """clip들의 현재 상태 조회 (feed/v3 POST 방식)."""
        if not self._cookies:
            self.load_session()

        url = f"{BASE_URL}{FEED_ENDPOINT}"
        headers = {**self._headers, "Cookie": self._cookie_header()}
        auth = await self._get_auth_token()
        if auth:
            headers["Authorization"] = auth

        payload = {
            "filters": {
                "ids": {"presence": "True", "clipIds": clip_ids}
            },
            "limit": len(clip_ids),
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    # feed/v3 응답: {"clips": [...]} 또는 직접 리스트
                    clips = data.get("clips", data) if isinstance(data, dict) else data
                    return clips if isinstance(clips, list) else []
                else:
                    logger.warning(f"상태 조회 실패: HTTP {resp.status}")
                    return []

    async def wait_for_audio(self, clips: list[dict], timeout: int = 300) -> list[dict]:
        """
        clip들의 audio_url이 채워질 때까지 폴링.
        timeout: 최대 대기 시간 (초).
        """
        clip_ids = [c.get("id", "") for c in clips if c.get("id")]
        if not clip_ids:
            return clips

        deadline = time.time() + timeout
        while time.time() < deadline:
            statuses = await self.get_clip_status(clip_ids)
            all_ready = True
            for s in statuses:
                audio = s.get("audio_url") or s.get("stream_audio_url", "")
                if not audio:
                    all_ready = False
                    break

            if all_ready and statuses:
                logger.info(f"전체 audio_url 준비 완료: {len(statuses)}개")
                return statuses

            await asyncio.sleep(10)

        logger.warning(f"audio_url 대기 타임아웃: {timeout}초")
        return await self.get_clip_status(clip_ids)

    # ━━━ 다운로드 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    async def download_clip(self, clip: dict, output_dir: Path, prefix: str = "") -> Optional[str]:
        """clip 1개 MP3 다운로드."""
        clip_id = clip.get("id", "")
        audio_url = clip.get("audio_url") or clip.get("stream_audio_url", "")

        urls_to_try = [u for u in [
            audio_url,
            f"{CDN_URLS[0]}/{clip_id}.mp3",
            f"{CDN_URLS[1]}/{clip_id}.mp3",
        ] if u]

        output_dir.mkdir(parents=True, exist_ok=True)
        # 파일명: {prefix}mp3 (QA 패턴 호환: {idx:02d}_*_v{slot}.mp3)
        # prefix가 이미 "01_Title_v1." 형태이면 clip_id 안 붙임
        if prefix.endswith("."):
            dest = output_dir / f"{prefix[:-1]}.mp3"
        else:
            dest = output_dir / f"{prefix}{clip_id}.mp3"

        headers = {
            "User-Agent": self._headers.get("User-Agent", ""),
            "Referer": "https://suno.com/",
            "Cookie": self._cookie_header(),
        }

        async with aiohttp.ClientSession() as session:
            for url in urls_to_try:
                try:
                    async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=120)) as resp:
                        if resp.status == 200:
                            content = await resp.read()
                            if len(content) > 10_000:  # 최소 10KB
                                dest.write_bytes(content)
                                logger.info(f"다운로드 완료: {dest.name} ({len(content) // 1024}KB)")
                                return str(dest)
                except Exception as e:
                    logger.warning(f"다운로드 실패 ({url[:40]}): {e}")
                    continue

        logger.error(f"모든 URL 실패: clip_id={clip_id}")
        return None

    # ━━━ 배치 생성 (병렬) ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    async def batch_create(
        self,
        songs: list[dict],
        output_dir: Path,
        progress_cb=None,
        max_concurrent: int = 3,
    ) -> list[dict]:
        """
        여러 곡 병렬 생성 + 다운로드.

        songs: [{"title": str, "suno_prompt": str, "lyrics": str, "is_instrumental": bool, "index": int}]
        반환: [{"index": int, "title": str, "suno_id": str, "file_path": str, "status": str, "slot": int}]
        """
        results = []
        semaphore = asyncio.Semaphore(max_concurrent)

        async def _process_one(song: dict):
            async with semaphore:
                idx = song.get("index", 0)
                title = song.get("title", f"Track_{idx}")
                prompt = song.get("suno_prompt", "")
                lyrics = song.get("lyrics", "")
                instrumental = song.get("is_instrumental", True)

                try:
                    if progress_cb:
                        progress_cb({"phase": "creating", "current_title": title, "completed": len(results)})

                    # 생성
                    clips = await self.create_song(prompt, title, lyrics, instrumental)

                    # audio_url 대기
                    ready_clips = await self.wait_for_audio(clips, timeout=300)

                    # 다운로드
                    for slot, clip in enumerate(ready_clips[:2], 1):
                        prefix = f"{idx:02d}_{title[:30]}_v{slot}_"
                        file_path = await self.download_clip(clip, output_dir, prefix)
                        results.append({
                            "index": idx,
                            "title": title,
                            "suno_id": clip.get("id", ""),
                            "file_path": file_path,
                            "status": "completed" if file_path else "download_failed",
                            "slot": slot,
                        })

                    # 생성 간 딜레이 (rate limit 방지)
                    await asyncio.sleep(5)

                except Exception as e:
                    logger.error(f"곡 생성 실패 [{title}]: {e}")
                    results.append({
                        "index": idx, "title": title, "suno_id": "",
                        "file_path": None, "status": "failed", "slot": 0,
                        "error": str(e),
                    })

        # 병렬 실행
        tasks = [asyncio.create_task(_process_one(s)) for s in songs]
        await asyncio.gather(*tasks, return_exceptions=True)

        logger.info(f"배치 완료: {len(results)}개 결과, 성공 {sum(1 for r in results if r['status']=='completed')}개")
        return results

    # ━━━ 크레딧 확인 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    async def get_credits(self) -> dict:
        """남은 크레딧 확인."""
        if not self._cookies:
            self.load_session()

        url = f"{BASE_URL}{BILLING_ENDPOINT}"
        headers = {**self._headers, "Cookie": self._cookie_header()}
        auth = await self._get_auth_token()
        if auth:
            headers["Authorization"] = auth

        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        return await resp.json()
            except Exception as e:
                logger.warning(f"크레딧 조회 실패: {e}")
        return {}


# 싱글턴
suno_api = SunoAPIClient()
