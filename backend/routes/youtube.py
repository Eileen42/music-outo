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


@router.post("/open-studio/{project_id}", summary="YouTube 업로드 브라우저 열기")
async def open_studio(project_id: str):
    """Edge를 CDP 모드로 열어 YouTube 업로드 페이지 + outputs 폴더."""
    import subprocess, os
    state = state_manager.require(project_id)
    project_dir = state_manager.project_dir(project_id)
    outputs_dir = project_dir / "outputs"

    # OAuth 연결 여부와 관계없이 업로드 페이지 열기
    # youtube.com/upload는 로그인만 되어있으면 바로 업로드 화면
    channel_id = state.get("channel_id", "_default")
    yt_info = youtube_uploader.get_channel_info(channel_id)
    yt_channel_id = yt_info.get("youtube_channel_id", "")
    if yt_channel_id:
        upload_url = f"https://studio.youtube.com/channel/{yt_channel_id}/videos/upload?d=ud"
    else:
        upload_url = "https://www.youtube.com/upload"

    # 기존 Edge CDP 포트 충돌 방지 — CDP 포트가 이미 열려있으면 재사용
    import time
    cdp_alive = False
    try:
        import httpx
        resp = httpx.get("http://localhost:9224/json/version", timeout=2)
        cdp_alive = resp.status_code == 200
    except Exception:
        pass

    if not cdp_alive:
        # Edge를 CDP 모드로 새로 시작
        os.system('taskkill /F /IM msedge.exe >nul 2>&1')
        time.sleep(2)
        subprocess.Popen([
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            "--remote-debugging-port=9224",
            "--restore-last-session",
            upload_url,
        ])
        time.sleep(3)  # Edge 시작 대기
    else:
        # 이미 열린 Edge에서 새 탭으로 업로드 페이지 열기
        try:
            import httpx
            httpx.put(f"http://localhost:9224/json/new?{upload_url}", timeout=3)
        except Exception:
            subprocess.Popen([
                r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                upload_url,
            ])

    # outputs 폴더 열기
    if outputs_dir.exists():
        os.startfile(str(outputs_dir))

    return {"status": "opened", "cdp_port": 9224, "url": upload_url}


@router.post("/fill-metadata/{project_id}", summary="YouTube Studio에 메타데이터 자동 입력")
async def fill_metadata(project_id: str, background_tasks: BackgroundTasks):
    """CDP로 열려있는 YouTube Studio에 제목/설명 자동 입력."""
    state = state_manager.require(project_id)
    background_tasks.add_task(_fill_metadata_browser, project_id)
    return {"status": "filling"}


async def _post_comment_when_ready(project_id: str, comment: str):
    """YouTube에 영상이 처리 완료되면 댓글 자동 작성 (최대 10분 대기)."""
    import asyncio
    state = state_manager.get(project_id)
    channel_id = state.get("channel_id", "_default")

    try:
        creds = youtube_uploader._load_credentials(channel_id)
        from googleapiclient.discovery import build as yt_build
        yt = yt_build("youtube", "v3", credentials=creds)

        # 최신 업로드 영상 찾기 (최대 10분 폴링)
        for attempt in range(60):
            resp = yt.search().list(forMine=True, type="video", part="snippet", maxResults=1, order="date").execute()
            items = resp.get("items", [])
            if items:
                vid = items[0]["id"]["videoId"]
                # 댓글 작성 시도
                try:
                    yt.commentThreads().insert(
                        part="snippet",
                        body={"snippet": {"videoId": vid, "topLevelComment": {"snippet": {"textOriginal": comment}}}},
                    ).execute()
                    import logging
                    logging.getLogger(__name__).info(f"댓글 작성 완료: {vid}")
                    cs = state_manager.get(project_id) or {}
                    state_manager.update(project_id, {"browser_comment_posted": True, "uploaded_set": cs.get("active_suno_set", ""), "youtube": {"video_id": vid, "url": f"https://www.youtube.com/watch?v={vid}"}})
                    return
                except Exception as e:
                    if "processingFailure" in str(e) or "forbidden" in str(e).lower():
                        # 영상 아직 처리 중 — 대기
                        await asyncio.sleep(10)
                        continue
                    raise
            await asyncio.sleep(10)

        import logging
        logging.getLogger(__name__).warning(f"댓글 작성 타임아웃: {project_id}")
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"댓글 작성 실패: {e}")


async def _fill_metadata_browser(project_id: str):
    """CDP로 YouTube Studio 메타데이터 입력 — 각 단계를 확인하고 미완료분만 실행."""
    import asyncio
    import logging
    log = logging.getLogger(__name__)

    state = state_manager.get(project_id)
    meta = state.get("metadata", {})
    title = meta.get("title", "")
    desc = meta.get("description", "")
    tags = meta.get("tags", [])
    comment = meta.get("comment", "")
    images = state.get("images", {})
    thumb = images.get("thumbnail", "")

    steps_done = []

    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser = await p.chromium.connect_over_cdp("http://localhost:9224")
            context = browser.contexts[0]

            # 업로드 편집 페이지 찾기 — 여러 탭 중 studio/upload 탭 선택
            page = None
            for pg in context.pages:
                if "studio.youtube.com" in pg.url or "youtube.com/upload" in pg.url:
                    page = pg
                    break
            if not page:
                page = context.pages[-1]  # fallback: 마지막 탭

            await page.wait_for_timeout(2000)

            # 업로드 편집 페이지 대기 (최대 30초 — 파일 드래그 후 페이지 전환 대기)
            title_el_check = None
            for _wait in range(15):
                title_el_check = await page.query_selector("#title-textarea [contenteditable]")
                if title_el_check:
                    break
                await page.wait_for_timeout(2000)

            if not title_el_check:
                log.error(f"업로드 편집 페이지가 아닙니다. URL: {page.url}")
                log.error("파일을 YouTube Studio에 먼저 드래그해주세요.")
                await browser.close()
                return

            # 헬퍼: 오버레이 팝업 닫기 (YouTube 소셜 제안 등)
            async def dismiss_overlays():
                await page.evaluate("""
                    document.querySelectorAll('tp-yt-iron-overlay-backdrop.opened').forEach(el => {
                        el.style.display = 'none';
                    });
                """)
                await page.wait_for_timeout(300)

            # 헬퍼: JS로 직접 텍스트 입력 (오버레이 우회)
            async def paste_text(selector, text):
                await dismiss_overlays()
                success = await page.evaluate(
                    """([sel, txt]) => {
                        document.querySelectorAll('tp-yt-iron-overlay-backdrop').forEach(o => o.remove());
                        const el = document.querySelector(sel);
                        if (!el) return false;
                        el.focus();
                        el.textContent = '';
                        document.execCommand('selectAll', false, null);
                        document.execCommand('insertText', false, txt);
                        el.dispatchEvent(new Event('input', { bubbles: true }));
                        return true;
                    }""",
                    [selector, text]
                )
                await page.wait_for_timeout(800)
                return success

            # 헬퍼: 요소 텍스트 읽기
            async def get_text(selector):
                el = await page.query_selector(selector)
                if el:
                    return (await el.inner_text()).strip()
                return ""

            # ── 1. 제목 ──
            current_title = await get_text("#title-textarea [contenteditable]")
            if not current_title or len(current_title) < 3:
                if await paste_text("#title-textarea [contenteditable]", title[:100]):
                    steps_done.append("제목")
                    log.info("✓ 제목 입력")
            else:
                steps_done.append("제목(이미 입력됨)")

            # ── 2. 설명 ──
            current_desc = await get_text("#description-textarea [contenteditable]")
            if not current_desc or len(current_desc) < 10:
                if await paste_text("#description-textarea [contenteditable]", desc[:5000]):
                    steps_done.append("설명")
                    log.info("✓ 설명 입력")
            else:
                steps_done.append("설명(이미 입력됨)")

            # ── 3. 더보기 + 태그 ──
            await dismiss_overlays()
            more_btn = await page.query_selector("button:has-text('더보기')")
            if more_btn:
                await page.evaluate("document.querySelector(\"button:has-text('더보기')\")?.click()")
                await page.wait_for_timeout(1000)

            if tags:
                await dismiss_overlays()
                # 태그를 하나씩 입력 (YouTube는 Enter로 태그 구분)
                for tag in tags[:30]:
                    await page.evaluate(
                        """(tag) => {
                            document.querySelectorAll('tp-yt-iron-overlay-backdrop').forEach(o => o.remove());
                            const inp = document.querySelector('ytcp-chip-bar #text-input')
                                || document.querySelector("input[aria-label*='태그']")
                                || document.querySelector('#tags-container input');
                            if (!inp) return;
                            inp.focus();
                            inp.value = tag;
                            inp.dispatchEvent(new Event('input', { bubbles: true }));
                            inp.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', keyCode: 13, bubbles: true }));
                        }""",
                        tag.strip()
                    )
                    await page.wait_for_timeout(300)
                steps_done.append(f"태그({len(tags[:30])}개)")
                log.info(f"✓ 태그 {len(tags[:30])}개 입력")

            # ── 4. 썸네일 ──
            if thumb and Path(thumb).exists():
                try:
                    await dismiss_overlays()
                    # hidden file input에 직접 파일 설정 (버튼 클릭 우회)
                    fi = await page.query_selector("input#file-loader[type='file']")
                    if not fi:
                        fi = await page.query_selector("input[accept*='image'][type='file']")
                    if fi:
                        await fi.set_input_files(thumb)
                        await page.wait_for_timeout(3000)
                        steps_done.append("썸네일")
                        log.info("✓ 썸네일 업로드")
                    else:
                        steps_done.append("썸네일(input 못 찾음)")
                except Exception as e:
                    log.warning(f"썸네일 건너뜀: {e}")
                    steps_done.append("썸네일(실패-건너뜀)")

            # ── 5. 아동용 아님 ──
            await dismiss_overlays()
            await page.evaluate("""() => {
                const nfk = document.querySelector("#audience [name='VIDEO_MADE_FOR_KIDS_NOT_MFK']")
                    || document.querySelector("tp-yt-paper-radio-button[name='NOT_MADE_FOR_KIDS']");
                if (nfk) nfk.click();
            }""")
            await page.wait_for_timeout(500)
            steps_done.append("아동용아님")

            # ── 6. 다음 버튼 (현재 페이지 확인 후 필요한 만큼만 클릭) ──
            for step in range(3):
                await dismiss_overlays()
                clicked = await page.evaluate("""() => {
                    const btn = document.querySelector("#next-button") || document.querySelector("ytcp-button#next-button");
                    if (btn) { btn.click(); return true; }
                    return false;
                }""")
                if clicked:
                    await page.wait_for_timeout(2000)
                    steps_done.append(f"다음{step+1}")

            # ── 7. 공개 설정 ──
            await dismiss_overlays()
            await page.evaluate("""() => {
                const ul = document.querySelector("tp-yt-paper-radio-button[name='UNLISTED']");
                if (ul) ul.click();
            }""")
            await page.wait_for_timeout(1000)
            steps_done.append("일부공개")

            # ── 8. 저장/게시 ──
            await dismiss_overlays()
            clicked = await page.evaluate("""() => {
                const btn = document.querySelector("#done-button") || document.querySelector("ytcp-button#done-button");
                if (btn) { btn.click(); return true; }
                return false;
            }""")
            if clicked:
                await page.wait_for_timeout(3000)
                steps_done.append("게시")

            state_manager.update(project_id, {"browser_metadata_filled": True})
            log.info(f"메타데이터 입력 완료: {steps_done}")
            await browser.close()

            # 댓글 자동 작성
            if comment:
                await _post_comment_when_ready(project_id, comment)

    except Exception as e:
        log.error(f"메타데이터 입력 실패 (완료: {steps_done}): {e}")


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
        current_state = state_manager.get(project_id) or {}
        uploaded_set = current_state.get("active_suno_set", "")
        state_manager.update(
            project_id,
            {
                "status": "uploaded",
                "youtube": {
                    "video_id": result["video_id"],
                    "url": result["url"],
                    "uploaded_at": datetime.utcnow().isoformat(),
                },
                "uploaded_set": uploaded_set,
            },
        )
    except Exception as e:
        import logging, traceback
        err = f"{type(e).__name__}: {e}"
        logging.getLogger(__name__).error(f"YouTube 업로드 실패: {err}\n{traceback.format_exc()[-300:]}")
        state_manager.update(project_id, {"status": "ready", "upload_error": err})
