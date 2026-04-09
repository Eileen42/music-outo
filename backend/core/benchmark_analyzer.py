"""
YouTube 벤치마크 영상 분석 모듈.

YouTube Data API v3 → 메타데이터 수집 → Gemini 텍스트 분석.
"""
from __future__ import annotations

import logging
import re
from datetime import date
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, urlparse

import httpx

from config import settings
from core.gemini_client import gemini_client

logger = logging.getLogger(__name__)


class BenchmarkAnalyzer:
    """YouTube 영상 분석"""

    _YT_API_BASE = "https://www.googleapis.com/youtube/v3"

    def __init__(self) -> None:
        self._thumbnail_dir = settings.storage_dir / "benchmarks" / "thumbnails"
        self._thumbnail_dir.mkdir(parents=True, exist_ok=True)

    # ──────────────────────────── public ────────────────────────────

    async def analyze(self, youtube_url: str) -> dict:
        """
        전체 분석 파이프라인.

        1. URL → video_id
        2. YouTube Data API → 메타데이터 + 통계
        3. 고정 댓글 가져오기
        4. 썸네일 다운로드
        5. Gemini AI 분석
        """
        video_id = self.extract_video_id(youtube_url)
        if not video_id:
            raise ValueError(f"유효하지 않은 YouTube URL: {youtube_url}")

        logger.info(f"벤치마크 분석 시작: {video_id}")

        video_data  = await self._fetch_video_data(video_id)
        pinned      = await self._fetch_pinned_comment(video_id)
        thumb_path  = await self._download_thumbnail(
            video_data.get("thumbnail_url", ""), video_id
        )
        ai_result   = await self._analyze_with_ai(video_data, pinned)

        result = {
            "url":            youtube_url,
            "video_id":       video_id,
            "title":          video_data.get("title", ""),
            "description":    video_data.get("description", ""),
            "tags":           video_data.get("tags", []),
            "pinned_comment": pinned,
            "thumbnail_path": thumb_path,
            "duration":       video_data.get("duration", ""),
            "statistics":     video_data.get("statistics", {}),
            "ai_analysis":    ai_result,
            "analyzed_at":    date.today().isoformat(),
        }
        logger.info(f"벤치마크 분석 완료: {video_id}")
        return result

    def extract_video_id(self, url: str) -> str:
        """
        다양한 YouTube URL 형식에서 video_id 추출.

        지원 형식:
          - youtube.com/watch?v=VIDEO_ID
          - youtu.be/VIDEO_ID
          - youtube.com/shorts/VIDEO_ID
          - youtube.com/embed/VIDEO_ID
          - youtube.com/v/VIDEO_ID
        """
        # 직접 11자리 ID 입력인 경우
        if re.match(r'^[A-Za-z0-9_-]{11}$', url.strip()):
            return url.strip()

        parsed = urlparse(url)

        # youtu.be/VIDEO_ID
        if parsed.netloc in ("youtu.be",):
            return parsed.path.lstrip("/").split("?")[0][:11]

        # /shorts/, /embed/, /v/ 경로
        path_match = re.search(r"/(?:shorts|embed|v)/([A-Za-z0-9_-]{11})", parsed.path)
        if path_match:
            return path_match.group(1)

        # ?v=VIDEO_ID 쿼리
        qs = parse_qs(parsed.query)
        if "v" in qs:
            return qs["v"][0][:11]

        return ""

    # ──────────────────────────── YouTube API ────────────────────────────

    async def _fetch_video_data(self, video_id: str) -> dict:
        """YouTube Data API v3 — snippet + statistics + contentDetails."""
        api_key = settings.youtube_api_key
        if not api_key:
            logger.warning("youtube_api_key 미설정 — 메타데이터를 빈 값으로 반환")
            return {"title": video_id, "description": "", "tags": [],
                    "thumbnail_url": "", "duration": "", "statistics": {}}

        url = f"{self._YT_API_BASE}/videos"
        params = {
            "key":  api_key,
            "id":   video_id,
            "part": "snippet,statistics,contentDetails",
        }

        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()

        items = data.get("items", [])
        if not items:
            raise ValueError(f"YouTube 영상을 찾을 수 없습니다: {video_id}")

        item     = items[0]
        snippet  = item.get("snippet", {})
        stats    = item.get("statistics", {})
        details  = item.get("contentDetails", {})

        # 최고화질 썸네일
        thumbs = snippet.get("thumbnails", {})
        thumb_url = (
            thumbs.get("maxres", {}).get("url")
            or thumbs.get("high", {}).get("url")
            or thumbs.get("default", {}).get("url")
            or ""
        )

        return {
            "title":         snippet.get("title", ""),
            "description":   snippet.get("description", ""),
            "tags":          snippet.get("tags", []),
            "thumbnail_url": thumb_url,
            "duration":      self._iso_duration_to_str(details.get("duration", "")),
            "statistics": {
                "viewCount":    stats.get("viewCount", "0"),
                "likeCount":    stats.get("likeCount", "0"),
                "commentCount": stats.get("commentCount", "0"),
            },
        }

    async def _fetch_pinned_comment(self, video_id: str) -> str:
        """고정 댓글 텍스트 반환. 없거나 API 키 없으면 빈 문자열."""
        api_key = settings.youtube_api_key
        if not api_key:
            return ""

        url = f"{self._YT_API_BASE}/commentThreads"
        params = {
            "key":        api_key,
            "videoId":    video_id,
            "part":       "snippet",
            "order":      "relevance",
            "maxResults": 20,
        }

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(url, params=params)
                if resp.status_code != 200:
                    return ""
                data = resp.json()

            for item in data.get("items", []):
                top = item.get("snippet", {}).get("topLevelComment", {})
                if top.get("snippet", {}).get("authorChannelId"):
                    # 고정 댓글은 별도 필드가 없어서 상위 댓글로 근사
                    text = top["snippet"].get("textDisplay", "")
                    if text:
                        return text
        except Exception as e:
            logger.warning(f"고정 댓글 조회 실패: {e}")

        return ""

    # ──────────────────────────── 썸네일 ────────────────────────────

    async def _download_thumbnail(self, thumbnail_url: str, video_id: str) -> str:
        """썸네일 이미지 다운로드 → 저장 경로 반환. 실패 시 빈 문자열."""
        if not thumbnail_url:
            return ""

        dest = self._thumbnail_dir / f"{video_id}.jpg"
        if dest.exists():
            return str(dest)

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(thumbnail_url)
                resp.raise_for_status()
                dest.write_bytes(resp.content)
            logger.info(f"썸네일 저장: {dest}")
            return str(dest)
        except Exception as e:
            logger.warning(f"썸네일 다운로드 실패: {e}")
            return ""

    # ──────────────────────────── AI 분석 ────────────────────────────

    async def _analyze_with_ai(self, video_data: dict, pinned_comment: str) -> dict:
        """Gemini 텍스트로 영상 분석."""
        prompt = f"""이 YouTube 음악 영상을 분석해줘:

제목: {video_data.get('title', '')}
설명: {video_data.get('description', '')[:1000]}
태그: {', '.join(video_data.get('tags', [])[:20])}
고정댓글: {pinned_comment[:500] if pinned_comment else '없음'}
재생시간: {video_data.get('duration', '')}
조회수: {video_data.get('statistics', {}).get('viewCount', '0')}

다음을 JSON으로 반환:
{{
  "estimated_track_count": 추정 곡 수 (숫자),
  "music_style": "음악 스타일 요약 (1~2문장)",
  "mood": ["분위기 키워드1", "키워드2", "키워드3"],
  "target_audience": "타겟 청취자 설명",
  "content_structure": "영상 구성 방식 설명",
  "seo_keywords": ["발견된", "SEO", "키워드", "목록"]
}}"""

        try:
            result = await gemini_client.generate_json(prompt)
            if isinstance(result, list):
                result = result[0] if result else {}
            return result
        except Exception as e:
            logger.error(f"AI 분석 실패: {e}")
            return {
                "estimated_track_count": 0,
                "music_style": "",
                "mood": [],
                "target_audience": "",
                "content_structure": "",
                "seo_keywords": [],
            }

    # ──────────────────────────── helpers ────────────────────────────

    @staticmethod
    def _iso_duration_to_str(iso: str) -> str:
        """PT1H23M45S → 1:23:45 / PT3M30S → 3:30"""
        if not iso:
            return ""
        m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso)
        if not m:
            return iso
        h, mn, s = (int(v or 0) for v in m.groups())
        if h:
            return f"{h}:{mn:02d}:{s:02d}"
        return f"{mn}:{s:02d}"


# ──────────────────────────── 싱글톤 ────────────────────────────

benchmark_analyzer = BenchmarkAnalyzer()
