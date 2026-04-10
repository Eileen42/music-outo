"""
YouTube Data API v3를 사용한 직접 업로드.
OAuth 2.0 플로우 + 영상 업로드 + 댓글 고정.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Callable, Optional

from config import settings

# OAuth 토큰 저장 경로 (채널별)
TOKEN_DIR = settings.storage_dir / "youtube_tokens"
SCOPES = [
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]


def _token_path(channel_id: str = "_default") -> Path:
    return TOKEN_DIR / f"youtube_token_{channel_id}.json"


class YouTubeUploader:
    def __init__(self):
        self._active_channel_id: str = "_default"

    def set_channel(self, channel_id: str):
        """업로드할 채널 설정."""
        self._active_channel_id = channel_id or "_default"

    def get_auth_url(self, channel_id: str = "_default") -> str:
        """OAuth 인증 URL 반환. state에 channel_id 포함."""
        self._active_channel_id = channel_id
        flow = self._create_flow()
        auth_url, _ = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
            state=channel_id,  # 콜백에서 어느 채널인지 식별
        )
        return auth_url

    def handle_callback(self, code: str, channel_id: str = "_default") -> dict:
        """OAuth 콜백 처리 + 채널별 토큰 저장."""
        flow = self._create_flow()
        flow.fetch_token(code=code)
        creds = flow.credentials

        # YouTube 채널 정보 조회
        from googleapiclient.discovery import build as yt_build
        yt = yt_build("youtube", "v3", credentials=creds)
        ch_resp = yt.channels().list(mine=True, part="snippet").execute()
        yt_channel = ch_resp["items"][0] if ch_resp.get("items") else {}

        token_data = {
            "token": creds.token,
            "refresh_token": creds.refresh_token,
            "token_uri": creds.token_uri,
            "client_id": creds.client_id,
            "client_secret": creds.client_secret,
            "scopes": list(creds.scopes or []),
            "youtube_channel_id": yt_channel.get("id", ""),
            "youtube_channel_title": yt_channel.get("snippet", {}).get("title", ""),
        }
        tp = _token_path(channel_id)
        tp.parent.mkdir(parents=True, exist_ok=True)
        tp.write_text(json.dumps(token_data, indent=2))
        return {
            "status": "authorized",
            "youtube_channel": yt_channel.get("snippet", {}).get("title", ""),
            "youtube_channel_id": yt_channel.get("id", ""),
        }

    def is_authorized(self, channel_id: str = "_default") -> bool:
        return _token_path(channel_id).exists()

    def get_channel_info(self, channel_id: str = "_default") -> dict:
        """저장된 토큰에서 YouTube 채널 정보 반환."""
        tp = _token_path(channel_id)
        if not tp.exists():
            return {"authorized": False}
        data = json.loads(tp.read_text())
        return {
            "authorized": True,
            "youtube_channel_id": data.get("youtube_channel_id", ""),
            "youtube_channel_title": data.get("youtube_channel_title", ""),
        }

    def revoke(self, channel_id: str = "_default") -> None:
        tp = _token_path(channel_id)
        if tp.exists():
            tp.unlink()

    async def upload(
        self,
        video_path: Path,
        title: str,
        description: str,
        tags: list[str],
        privacy_status: str = "private",
        thumbnail_path: Optional[Path] = None,
        pinned_comment: Optional[str] = None,
        progress_cb: Optional[Callable] = None,
    ) -> dict:
        """영상 업로드 후 video_id와 URL 반환."""
        self._progress_cb = progress_cb
        import asyncio
        return await asyncio.to_thread(
            self._upload_sync,
            video_path, title, description, tags,
            privacy_status, thumbnail_path, pinned_comment,
        )

    def _upload_sync(
        self,
        video_path: Path,
        title: str,
        description: str,
        tags: list[str],
        privacy_status: str,
        thumbnail_path: Optional[Path],
        pinned_comment: Optional[str],
    ) -> dict:
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload

        creds = self._load_credentials()
        youtube = build("youtube", "v3", credentials=creds)

        body = {
            "snippet": {
                "title": title[:100],
                "description": description[:5000],
                "tags": tags[:30],
                "categoryId": "10",  # Music
            },
            "status": {"privacyStatus": privacy_status},
        }

        media = MediaFileUpload(
            str(video_path),
            mimetype="video/*",
            resumable=True,
            chunksize=1024 * 1024 * 100,  # 100MB chunks (업로드 속도 개선)
        )

        request = youtube.videos().insert(
            part="snippet,status",
            body=body,
            media_body=media,
        )

        response = None
        while response is None:
            status, response = request.next_chunk()
            if status and self._progress_cb:
                self._progress_cb(int(status.progress() * 100))

        video_id = response["id"]
        url = f"https://www.youtube.com/watch?v={video_id}"

        # 썸네일 업로드
        if thumbnail_path and thumbnail_path.exists():
            youtube.thumbnails().set(
                videoId=video_id,
                media_body=MediaFileUpload(str(thumbnail_path)),
            ).execute()

        # 댓글 작성 (일부공개/공개일 때만 가능)
        if pinned_comment and privacy_status != "private":
            try:
                comment_resp = youtube.commentThreads().insert(
                    part="snippet",
                    body={
                        "snippet": {
                            "videoId": video_id,
                            "topLevelComment": {
                                "snippet": {"textOriginal": pinned_comment}
                            },
                        }
                    },
                ).execute()
                # 댓글 고정은 YouTube Studio에서 수동으로 해야 함
                # API로는 고정 불가 (YouTube Data API 제한)
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(f"댓글 작성 실패 (영상 처리 중일 수 있음): {e}")

        return {"video_id": video_id, "url": url}

    def _create_flow(self):
        from google_auth_oauthlib.flow import Flow

        client_config = {
            "web": {
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uris": [settings.google_redirect_uri],
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        }
        return Flow.from_client_config(
            client_config,
            scopes=SCOPES,
            redirect_uri=settings.google_redirect_uri,
        )

    def _load_credentials(self, channel_id: str = None):
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request

        cid = channel_id or self._active_channel_id
        tp = _token_path(cid)
        if not tp.exists():
            raise RuntimeError(f"YouTube 인증 필요 (채널: {cid})")

        data = json.loads(tp.read_text())
        creds = Credentials(
            token=data.get("token"),
            refresh_token=data.get("refresh_token"),
            token_uri=data.get("token_uri"),
            client_id=data.get("client_id"),
            client_secret=data.get("client_secret"),
            scopes=data.get("scopes"),
        )

        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            data["token"] = creds.token
            tp.write_text(json.dumps(data, indent=2))

        return creds


youtube_uploader = YouTubeUploader()
