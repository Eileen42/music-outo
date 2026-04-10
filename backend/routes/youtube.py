import json
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import RedirectResponse

from core.state_manager import state_manager
from core.youtube_uploader import youtube_uploader
from models.schemas import YouTubeUploadRequest

router = APIRouter(prefix="/api/youtube", tags=["YouTube"])


@router.get("/status", summary="YouTube 인증 상태 확인")
async def get_auth_status(request: Request):
    channel_id = request.query_params.get("channel_id", "_default")
    info = youtube_uploader.get_channel_info(channel_id)
    return info


@router.get("/auth", summary="YouTube OAuth 인증 시작")
async def start_auth(channel_id: str = "_default"):
    """채널별 OAuth. channel_id는 우리 앱의 채널 ID."""
    url = youtube_uploader.get_auth_url(channel_id=channel_id)
    return {"auth_url": url}


@router.get("/callback", summary="OAuth 콜백 (자동 호출)")
async def oauth_callback(request: Request, code: str, state: str = "_default"):
    try:
        result = youtube_uploader.handle_callback(code, channel_id=state)
        origin = request.headers.get("referer", "").split("?")[0].rstrip("/")
        if not origin:
            origin = "http://localhost:3000"
        return RedirectResponse(url=f"{origin}/?youtube_auth=success&channel={state}")
    except Exception as e:
        raise HTTPException(500, f"OAuth 실패: {e}")


@router.get("/channels", summary="관리 채널 목록")
async def list_channels():
    """인증된 계정의 채널 목록 반환."""
    if not youtube_uploader.is_authorized():
        raise HTTPException(401, "인증 필요")
    creds = youtube_uploader._load_credentials()
    from googleapiclient.discovery import build as yt_build
    yt = yt_build("youtube", "v3", credentials=creds)
    resp = yt.channels().list(mine=True, part="snippet", maxResults=50).execute()
    return [
        {"id": ch["id"], "title": ch["snippet"]["title"], "thumbnail": ch["snippet"]["thumbnails"]["default"]["url"]}
        for ch in resp.get("items", [])
    ]


@router.post("/revoke", summary="YouTube 인증 해제")
async def revoke_auth():
    youtube_uploader.revoke()
    return {"status": "인증 해제됨"}


@router.post("/upload/{project_id}", summary="YouTube 업로드")
async def upload_video(
    project_id: str,
    body: YouTubeUploadRequest,
    background_tasks: BackgroundTasks,
):
    """빌드된 MP4를 YouTube에 업로드합니다. privacy_status: private / unlisted / public"""
    state = state_manager.require(project_id)

    # 중복 업로드 방지
    if state.get("status") == "uploading":
        raise HTTPException(409, "이미 업로드 진행 중입니다.")

    channel_id = state.get("channel_id", "_default")
    youtube_uploader.set_channel(channel_id)

    if not youtube_uploader.is_authorized(channel_id):
        raise HTTPException(401, "YouTube 채널이 연결되지 않았습니다. 채널 설정에서 먼저 연결하세요.")
    build = state.get("build", {})

    # output_file이 없으면 outputs/ 폴더에서 MP4 자동 탐색
    output_file = build.get("output_file")
    if not output_file or not Path(output_file).exists():
        project_dir = state_manager.project_dir(project_id)
        outputs_dir = project_dir / "outputs"
        mp4s = sorted(outputs_dir.glob("*.mp4"), key=lambda f: f.stat().st_mtime, reverse=True) if outputs_dir.exists() else []
        if mp4s:
            output_file = str(mp4s[0])
            state_manager.update(project_id, {"build": {**build, "output_file": output_file}})
        else:
            raise HTTPException(400, f"영상 파일이 없습니다. outputs 폴더에 MP4를 넣어주세요: {outputs_dir}")

    state_manager.update(project_id, {"status": "uploading"})
    background_tasks.add_task(_run_upload, project_id, body.privacy_status)
    return {"status": "업로드 시작됨"}


@router.post("/open-studio/{project_id}", summary="YouTube Studio 브라우저 열기")
async def open_studio(project_id: str):
    """Edge를 CDP 모드로 열어 YouTube Studio 업로드 페이지 + outputs 폴더."""
    import subprocess, os
    state = state_manager.require(project_id)
    metadata = state.get("metadata", {})
    project_dir = state_manager.project_dir(project_id)
    outputs_dir = project_dir / "outputs"

    # 연결된 YouTube 채널 ID로 Studio URL 생성
    channel_id = state.get("channel_id", "_default")
    yt_info = youtube_uploader.get_channel_info(channel_id)
    yt_channel_id = yt_info.get("youtube_channel_id", "")
    studio_url = f"https://studio.youtube.com/channel/{yt_channel_id}/videos/upload?d=ud" if yt_channel_id else "https://studio.youtube.com"

    # 기존 Edge 종료 후 CDP 포트로 재시작
    os.system('taskkill /F /IM msedge.exe >nul 2>&1')
    import time; time.sleep(2)

    subprocess.Popen([
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        "--remote-debugging-port=9224",
        "--restore-last-session",
        studio_url,
    ])

    # outputs 폴더 열기
    if outputs_dir.exists():
        os.startfile(str(outputs_dir))

    return {"status": "opened", "cdp_port": 9224}


@router.post("/fill-metadata/{project_id}", summary="YouTube Studio에 메타데이터 자동 입력")
async def fill_metadata(project_id: str, background_tasks: BackgroundTasks):
    """CDP로 열려있는 YouTube Studio에 제목/설명 자동 입력."""
    state = state_manager.require(project_id)
    background_tasks.add_task(_fill_metadata_browser, project_id)
    return {"status": "filling"}


async def _fill_metadata_browser(project_id: str):
    """CDP로 YouTube Studio 메타데이터 입력."""
    import asyncio
    state = state_manager.get(project_id)
    meta = state.get("metadata", {})
    title = meta.get("title", "")
    desc = meta.get("description", "")
    tags = meta.get("tags", [])
    comment = meta.get("comment", "")

    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser = await p.chromium.connect_over_cdp("http://localhost:9224")
            context = browser.contexts[0]
            page = context.pages[0]

            await page.wait_for_timeout(3000)

            # 클립보드 붙여넣기로 입력 (빠름)
            async def paste_text(selector, text):
                el = await page.query_selector(selector)
                if el:
                    await el.click()
                    await page.keyboard.press("Control+a")
                    await page.evaluate(f"navigator.clipboard.writeText({json.dumps(text)})")
                    await page.keyboard.press("Control+v")
                    await page.wait_for_timeout(500)
                    return True
                return False

            # 제목
            await paste_text("#title-textarea [contenteditable]", title[:100])
            # 설명
            await paste_text("#description-textarea [contenteditable]", desc[:5000])

            # 태그 (더보기 → 태그)
            more_btn = await page.query_selector("button:has-text('더보기')")
            if more_btn:
                await more_btn.click()
                await page.wait_for_timeout(1000)

            tag_input = await page.query_selector("input[aria-label*='태그'], #tags-container input")
            if tag_input and tags:
                await tag_input.click()
                await page.evaluate(f"navigator.clipboard.writeText({json.dumps(', '.join(tags))})")
                await page.keyboard.press("Control+v")

            await page.wait_for_timeout(1000)

            # 아동용 아님 선택
            not_for_kids = await page.query_selector("#audience [name='VIDEO_MADE_FOR_KIDS_NOT_MFK']")
            if not not_for_kids:
                not_for_kids = await page.query_selector("tp-yt-paper-radio-button[name='NOT_MADE_FOR_KIDS']")
            if not_for_kids:
                await not_for_kids.click()
                await page.wait_for_timeout(500)

            # 다음 버튼 3번 클릭 (세부정보 → 동영상 요소 → 확인 → 공개 설정)
            for step in range(3):
                next_btn = await page.query_selector("#next-button") or await page.query_selector("ytcp-button#next-button")
                if next_btn:
                    await next_btn.click()
                    await page.wait_for_timeout(2000)

            # 일부공개 선택
            unlisted = await page.query_selector("tp-yt-paper-radio-button[name='UNLISTED']")
            if not unlisted:
                # 라디오 버튼 텍스트로 찾기
                unlisted = await page.query_selector("tp-yt-paper-radio-button:has-text('일부공개')")
            if unlisted:
                await unlisted.click()
                await page.wait_for_timeout(1000)

            # 저장/게시 버튼
            save_btn = await page.query_selector("#done-button") or await page.query_selector("ytcp-button#done-button")
            if save_btn:
                await save_btn.click()
                await page.wait_for_timeout(3000)

            # 업로드 완료 대기 (진행 바가 사라질 때까지)
            for _ in range(60):  # 최대 5분
                progress = await page.query_selector(".progress-bar.uploading, [class*='uploading']")
                if not progress:
                    break
                await page.wait_for_timeout(5000)

            # 댓글 작성 (영상 페이지로 이동)
            # 게시 후 나오는 영상 링크에서 video ID 추출
            video_link = await page.query_selector("a.style-scope.ytcp-video-info[href*='youtu']")
            if video_link:
                href = await video_link.get_attribute("href") or ""
                if "watch?v=" in href:
                    vid = href.split("watch?v=")[-1].split("&")[0]
                    # API로 댓글 작성
                    if comment and vid:
                        try:
                            channel_id = state.get("channel_id", "_default")
                            creds = youtube_uploader._load_credentials(channel_id)
                            from googleapiclient.discovery import build as yt_build
                            yt = yt_build("youtube", "v3", credentials=creds)
                            yt.commentThreads().insert(
                                part="snippet",
                                body={"snippet": {"videoId": vid, "topLevelComment": {"snippet": {"textOriginal": comment}}}},
                            ).execute()
                        except Exception:
                            pass

            state_manager.update(project_id, {"browser_upload_done": True})
            await browser.close()

    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"메타데이터 입력 실패: {e}")


@router.get("/upload/{project_id}/status", summary="업로드 상태 확인")
async def get_upload_status(project_id: str):
    state = state_manager.require(project_id)
    return {
        "status": state.get("status"),
        "youtube": state.get("youtube", {}),
        "upload_progress": state.get("upload_progress", 0),
    }


# ─── background task ─────────────────────────────────────────────────────────

async def _run_upload(project_id: str, privacy_status: str):
    state = state_manager.get(project_id)
    if not state:
        return

    build = state.get("build", {})
    metadata = state.get("metadata", {})
    images = state.get("images", {})

    video_path = Path(build["output_file"])
    thumbnail_path = images.get("thumbnail")

    def on_progress(pct: int):
        state_manager.update(project_id, {"upload_progress": pct})

    try:
        result = await youtube_uploader.upload(
            video_path=video_path,
            title=metadata.get("title") or state.get("name", ""),
            description=metadata.get("description") or "",
            tags=metadata.get("tags") or [],
            privacy_status=privacy_status,
            thumbnail_path=Path(thumbnail_path) if thumbnail_path else None,
            pinned_comment=metadata.get("comment"),
            progress_cb=on_progress,
        )

        from datetime import datetime
        state_manager.update(
            project_id,
            {
                "status": "uploaded",
                "youtube": {
                    "video_id": result["video_id"],
                    "url": result["url"],
                    "uploaded_at": datetime.utcnow().isoformat(),
                },
            },
        )
    except Exception as e:
        import logging, traceback
        err = f"{type(e).__name__}: {e}"
        logging.getLogger(__name__).error(f"YouTube 업로드 실패: {err}\n{traceback.format_exc()[-300:]}")
        state_manager.update(project_id, {"status": "ready", "upload_error": err})
