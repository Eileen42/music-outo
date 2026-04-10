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

# OAuth 토큰 저장 경로
TOKEN_FILE = settings.storage_dir / "youtube_token.json"
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]


class YouTubeUploader:
    def get_auth_url(self) -> str:
        """OAuth 인증 URL 반환."""
        from google_auth_oauthlib.flow import Flow

        flow = self._create_flow()
        auth_url, _ = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
        )
        return auth_url

    def handle_callback(self, code: str) -> dict:
        """OAuth 콜백 처리 + 토큰 저장."""
        from google_auth_oauthlib.flow import Flow

        flow = self._create_flow()
        flow.fetch_token(code=code)
        creds = flow.credentials

        token_data = {
            "token": creds.token,
            "refresh_token": creds.refresh_token,
            "token_uri": creds.token_uri,
            "client_id": creds.client_id,
            "client_secret": creds.client_secret,
            "scopes": list(creds.scopes or []),
        }
        TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        TOKEN_FILE.write_text(json.dumps(token_data, indent=2))
        return {"status": "authorized"}

    def is_authorized(self) -> bool:
        return TOKEN_FILE.exists()

    def revoke(self) -> None:
        if TOKEN_FILE.exists():
            TOKEN_FILE.unlink()

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

        # 댓글 고정
        if pinned_comment:
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
            comment_id = comment_resp["id"]
            youtube.comments().setModerationStatus(
                id=comment_id,
                moderationStatus="published",
            ).execute()

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

    def _load_credentials(self):
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request

        if not TOKEN_FILE.exists():
            raise RuntimeError("YouTube not authorized. Call /api/youtube/auth first.")

        data = json.loads(TOKEN_FILE.read_text())
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
            TOKEN_FILE.write_text(json.dumps(data, indent=2))

        return creds


youtube_uploader = YouTubeUploader()
