"""
메타데이터 자동 입력 워커 — DOM-first + CDP WebSocket.

원칙:
- DOM 구조를 한번 캡처하면 그대로 사용 (변수 발생 시만 AI/fallback)
- 셀렉터 우선순위: name/id 속성 > aria-label > 구조 > 텍스트
- 실패 시 DOM 스냅샷 저장 → 디버깅

사용법: python routes/_fill_meta_worker.py <project_id>
"""
import asyncio
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# uvicorn에서 import할 때 루트 로거 설정을 덮어쓰지 않도록 가드
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [워커] %(message)s",
        datefmt="%H:%M:%S",
    )
log = logging.getLogger(__name__)

# ━━━ DOM 스냅샷 디렉토리 ━━━
SNAPSHOT_DIR = Path(__file__).parent.parent / "storage" / "dom_snapshots"
SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)


# ━━━ CDP 유틸 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def cdp_eval(ws, expr, timeout=10):
    """CDP Runtime.evaluate — 결과값 반환."""
    import random
    msg_id = random.randint(10000, 99999)
    await ws.send(json.dumps({
        "id": msg_id,
        "method": "Runtime.evaluate",
        "params": {"expression": expr, "returnByValue": True, "awaitPromise": True}
    }))
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
            resp = json.loads(raw)
            if resp.get("id") == msg_id:
                result = resp.get("result", {}).get("result", {})
                return result.get("value", result.get("description", None))
        except asyncio.TimeoutError:
            break
    return None


async def safe_eval(ws, expr, description, retries=3, timeout=10):
    """안전한 CDP 실행 — 실패 시 재시도 + DOM 스냅샷."""
    for attempt in range(retries):
        result = await cdp_eval(ws, expr, timeout)
        if result is not None and result is not False:
            log.info(f"✅ {description}")
            return result
        if attempt < retries - 1:
            log.warning(f"⚠ {description} 재시도 ({attempt + 2}/{retries})")
            await asyncio.sleep(2)

    # 최종 실패 → DOM 스냅샷 저장
    log.error(f"❌ {description} 실패")
    await save_dom_snapshot(ws, description)
    return None


async def save_dom_snapshot(ws, name):
    """현재 페이지 DOM을 HTML로 저장."""
    try:
        html = await cdp_eval(ws, "document.documentElement.outerHTML", timeout=5)
        if html:
            safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
            ts = datetime.now().strftime("%H%M%S")
            path = SNAPSHOT_DIR / f"{safe_name}_{ts}.html"
            path.write_text(html, encoding="utf-8")
            log.info(f"📸 DOM 스냅샷 저장: {path.name}")
    except Exception as e:
        log.warning(f"스냅샷 저장 실패: {e}")


async def dismiss_overlays(ws):
    """YouTube Studio 오버레이 팝업 제거."""
    await cdp_eval(ws, """
        document.querySelectorAll('tp-yt-iron-overlay-backdrop').forEach(o => o.remove());
        document.querySelectorAll('.overlay').forEach(o => {
            if (o.style.display !== 'none') o.style.display = 'none';
        });
    """, timeout=3)
    await asyncio.sleep(0.3)


async def _cdp_send_and_wait(ws, method: str, params: dict, timeout: float = 5.0) -> dict:
    """CDP 메시지를 보내고 id 매칭되는 응답만 받을 때까지 대기.

    웹소켓에는 page event 같은 비요청 메시지가 섞여 들어오므로 id가 안 맞는
    프레임은 버려야 한다. 안 그러면 엉뚱한 이벤트에서 objectId 뽑으려다 실패.
    """
    import random
    msg_id = random.randint(10000, 99999)
    await ws.send(json.dumps({"id": msg_id, "method": method, "params": params}))
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
            resp = json.loads(raw)
            if resp.get("id") == msg_id:
                return resp
        except asyncio.TimeoutError:
            break
    return {}


async def cdp_set_file(ws, selector, file_path):
    """CDP로 file input에 파일 설정. 안정화된 버전:
    - JS 문자열 이스케이프 보장 (selector에 "가 있어도 안전)
    - DOM이 준비될 때까지 scrollIntoView 후 querySelector
    - id 매칭 루프로 CDP race 방지
    """
    # selector를 JS 문자열 리터럴로 안전 인코딩 (json.dumps는 "로 감싸고 내부 " 이스케이프)
    sel_js = json.dumps(selector)
    # 요소를 찾고 view로 스크롤 후 참조 반환
    expr = f"""
    (() => {{
        const el = document.querySelector({sel_js});
        if (!el) return null;
        try {{ el.scrollIntoView({{block: 'center'}}); }} catch(e) {{}}
        return el;
    }})()
    """
    resp = await _cdp_send_and_wait(
        ws, "Runtime.evaluate",
        {"expression": expr, "returnByValue": False},
    )
    obj_id = resp.get("result", {}).get("result", {}).get("objectId")
    if not obj_id:
        log.warning(f"썸네일 querySelector 실패: selector={selector}")
        return False

    resp2 = await _cdp_send_and_wait(ws, "DOM.describeNode", {"objectId": obj_id})
    backend_id = resp2.get("result", {}).get("node", {}).get("backendNodeId")
    if not backend_id:
        log.warning("썸네일 describeNode 실패 — backendNodeId 없음")
        return False

    resp3 = await _cdp_send_and_wait(
        ws, "DOM.setFileInputFiles",
        {"files": [str(file_path)], "backendNodeId": backend_id},
    )
    if resp3.get("error"):
        log.warning(f"썸네일 setFileInputFiles 실패: {resp3['error']}")
        return False
    return True


# ━━━ 셀렉터 맵 (DOM-first: name/id 기반, 텍스트 최후순위) ━━━━━━━━━

SELECTORS = {
    "title": '#title-textarea [contenteditable]',
    "desc": '#description-textarea [contenteditable]',
    "tag_input": 'ytcp-chip-bar #text-input',
    "tag_fallback": 'input[aria-label*="tag" i], input[aria-label*="태그"]',
    "thumbnail": 'input#file-loader[type="file"]',
    "thumbnail_fallback": 'input[accept*="image"][type="file"]',
    "not_for_kids": '#audience [name="VIDEO_MADE_FOR_KIDS_NOT_MFK"]',
    "not_for_kids_fallback": 'tp-yt-paper-radio-button[name="NOT_MADE_FOR_KIDS"]',
    "next_button": '#next-button',
    "next_fallback": 'ytcp-button#next-button',
    "unlisted": 'tp-yt-paper-radio-button[name="UNLISTED"]',
    "done_button": '#done-button',
    "done_fallback": 'ytcp-button#done-button',
    "more_toggle": '#toggle-button',  # "더보기" — ID 기반 (텍스트 의존 제거)
}


# ━━━ 메인 로직 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def fill_metadata(project_id: str):
    import httpx
    import websockets
    from core.state_manager import state_manager

    # ──────── 진행 상황 실시간 기록 헬퍼 ────────
    TOTAL_STEPS = 10  # 시작 + 연결 + 페이지확인 + 제목 + 설명 + 태그 + 썸네일 + 아동용 + 다음(3) + 공개 + 게시
    # (실제 개별 단계를 TOTAL로 나타냄 — 표시용)

    def _write_progress(step: str, current: int, done: bool, error: str) -> None:
        try:
            state_manager.update(project_id, {
                "browser_fill_progress": {
                    "step": step,
                    "current": current,
                    "total": TOTAL_STEPS,
                    "done": done,
                    "error": error,
                    "updated_at": datetime.now().isoformat(),
                }
            })
        except Exception as e:
            log.warning(f"진행상황 기록 실패: {e}")

    def report(step: str, current: int, done: bool = False, error: str = "") -> None:
        """동기 호출 가능 버전 — 파일 I/O는 스레드 풀에서 실행해 이벤트 루프 블로킹 방지."""
        try:
            asyncio.get_running_loop().run_in_executor(None, _write_progress, step, current, done, error)
        except RuntimeError:
            _write_progress(step, current, done, error)

    report("시작 중", 0)

    state = state_manager.get(project_id)
    if not state:
        log.error(f"프로젝트 없음: {project_id}")
        report("프로젝트 없음", 0, done=True, error="프로젝트를 찾을 수 없습니다")
        return

    meta = state.get("metadata", {})
    title = meta.get("title", "")
    desc = meta.get("description", "")
    tags = meta.get("tags", [])
    images = state.get("images", {})
    thumb = images.get("thumbnail", "")

    log.info(f"시작: {title[:30]}...")
    steps_done = []

    # CDP 연결 — async httpx로 이벤트 루프 블로킹 방지
    report("브라우저 연결 중", 1)
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            r = await client.get("http://localhost:9224/json")
        tabs = r.json()
    except Exception as e:
        log.error(f"CDP 연결 실패: {e}")
        report("브라우저 연결 실패 — '브라우저 업로드 열기'를 먼저 눌러주세요", 1, done=True, error=str(e)[:100])
        return

    ws_url = None
    for t in tabs:
        if "studio.youtube.com" in t.get("url", ""):
            ws_url = t["webSocketDebuggerUrl"]
            break

    if not ws_url:
        log.error("YouTube Studio 탭 없음")
        report("YouTube Studio 탭 없음 — 먼저 '브라우저 업로드 열기'를 눌러주세요", 1, done=True, error="no_studio_tab")
        return

    try:
        async with websockets.connect(ws_url, max_size=10_000_000) as ws:
            # 초기 DOM 스냅샷은 실패 시에만 저장 (정상 흐름에서는 latency 감소)
            # 편집 페이지 확인 (제목란 존재)
            report("YouTube Studio 페이지 확인 중", 2)
            has_title = await safe_eval(ws,
                f'!!document.querySelector("{SELECTORS["title"]}")',
                "편집 페이지 확인", retries=5, timeout=5)
            if not has_title:
                log.error("업로드 편집 페이지 아님 — 영상을 먼저 드래그하세요")
                report("영상을 먼저 드래그하세요", 2, done=True, error="no_upload_form")
                return

            # ── 1. 제목 (항상 덮어쓰기) ──
            report("제목 입력 중", 3)
            await dismiss_overlays(ws)
            r = await safe_eval(ws, f"""
                (() => {{
                    document.querySelectorAll('tp-yt-iron-overlay-backdrop').forEach(o => o.remove());
                    const el = document.querySelector('{SELECTORS["title"]}');
                    if (!el) return false;
                    el.focus();
                    el.textContent = '';
                    document.execCommand('selectAll', false, null);
                    document.execCommand('insertText', false, {json.dumps(title[:100])});
                    el.dispatchEvent(new Event('input', {{ bubbles: true }}));
                    return true;
                }})()
            """, "제목 입력")
            if r: steps_done.append("제목")
            await asyncio.sleep(1)

            # ── 2. 설명 ──
            report("설명 입력 중", 4)
            await dismiss_overlays(ws)
            r = await safe_eval(ws, f"""
                (() => {{
                    document.querySelectorAll('tp-yt-iron-overlay-backdrop').forEach(o => o.remove());
                    const el = document.querySelector('{SELECTORS["desc"]}');
                    if (!el) return false;
                    el.focus();
                    el.textContent = '';
                    document.execCommand('selectAll', false, null);
                    document.execCommand('insertText', false, {json.dumps(desc[:5000])});
                    el.dispatchEvent(new Event('input', {{ bubbles: true }}));
                    return true;
                }})()
            """, "설명 입력")
            if r: steps_done.append("설명")
            await asyncio.sleep(1)

            # ── 3. 더보기 (ID 기반 셀렉터) ──
            await dismiss_overlays(ws)
            await safe_eval(ws, f"""
                (() => {{
                    document.querySelectorAll('tp-yt-iron-overlay-backdrop').forEach(o => o.remove());
                    // 1순위: #toggle-button (ID)
                    let btn = document.querySelector('{SELECTORS["more_toggle"]}');
                    // 2순위: aria-expanded 속성
                    if (!btn) btn = document.querySelector('[aria-expanded="false"]');
                    // 3순위: 텍스트 (최후)
                    if (!btn) {{
                        const all = [...document.querySelectorAll('button')];
                        btn = all.find(b => /더보기|Show more|More/i.test(b.textContent));
                    }}
                    if (btn) btn.click();
                    return !!btn;
                }})()
            """, "더보기 클릭")
            await asyncio.sleep(1)

            # ── 4. 태그 ──
            if tags:
                report(f"태그 {len(tags[:30])}개 입력 중", 5)
                for tag in tags[:30]:
                    await cdp_eval(ws, f"""
                        (() => {{
                            const inp = document.querySelector('{SELECTORS["tag_input"]}')
                                || document.querySelector('{SELECTORS["tag_fallback"]}');
                            if (!inp) return;
                            inp.focus();
                            inp.value = {json.dumps(tag.strip())};
                            inp.dispatchEvent(new Event('input', {{ bubbles: true }}));
                            inp.dispatchEvent(new KeyboardEvent('keydown', {{ key: 'Enter', keyCode: 13, bubbles: true }}));
                        }})()
                    """, timeout=5)
                    await asyncio.sleep(0.3)
                steps_done.append(f"태그({len(tags[:30])}개)")
                log.info(f"✅ 태그 {len(tags[:30])}개")

            # ── 5. 썸네일 ──
            if thumb and Path(thumb).exists():
                report("썸네일 업로드 중", 6)
                try:
                    await dismiss_overlays(ws)
                    # 최대 3번 재시도 (DOM 전환·overlay 깔림 대비)
                    ok = False
                    for attempt in range(3):
                        ok = await cdp_set_file(ws, SELECTORS["thumbnail"], thumb)
                        if not ok:
                            ok = await cdp_set_file(ws, SELECTORS["thumbnail_fallback"], thumb)
                        if ok:
                            break
                        if attempt < 2:
                            log.warning(f"⚠ 썸네일 재시도 {attempt + 2}/3")
                            await dismiss_overlays(ws)
                            await asyncio.sleep(1)
                    if ok:
                        steps_done.append("썸네일")
                        log.info("✅ 썸네일")
                        await asyncio.sleep(2)  # 업로드 반영 대기 (기존 3초 → 2초)
                    else:
                        log.warning("⚠ 썸네일 input 못 찾음 (3회 재시도 실패)")
                        await save_dom_snapshot(ws, "thumbnail_fail")
                except Exception as e:
                    log.warning(f"⚠ 썸네일 건너뜀: {e}")

            # ── 6. 아동용 아님 ──
            report("시청자층 설정 중", 7)
            await dismiss_overlays(ws)
            await safe_eval(ws, f"""
                (() => {{
                    const nfk = document.querySelector('{SELECTORS["not_for_kids"]}')
                        || document.querySelector('{SELECTORS["not_for_kids_fallback"]}');
                    if (nfk) nfk.click();
                    return !!nfk;
                }})()
            """, "아동용 아님")
            await asyncio.sleep(0.5)
            steps_done.append("아동용아님")

            # ── 7. 다음 x3 ──
            for step in range(3):
                report(f"다음 페이지로 이동 ({step + 1}/3)", 8)
                await dismiss_overlays(ws)
                await safe_eval(ws, f"""
                    (() => {{
                        const btn = document.querySelector('{SELECTORS["next_button"]}')
                            || document.querySelector('{SELECTORS["next_fallback"]}');
                        if (btn) btn.click();
                        return !!btn;
                    }})()
                """, f"다음 {step+1}")
                await asyncio.sleep(2)
                steps_done.append(f"다음{step + 1}")

            # ── 8. 일부공개 ──
            report("공개 범위 설정 중", 9)
            await dismiss_overlays(ws)
            await safe_eval(ws, f"""
                (() => {{
                    const ul = document.querySelector('{SELECTORS["unlisted"]}');
                    if (ul) ul.click();
                    return !!ul;
                }})()
            """, "일부공개 설정")
            await asyncio.sleep(1)
            steps_done.append("일부공개")

            # ── 9. 저장/게시 ──
            report("게시하는 중", 10)
            await dismiss_overlays(ws)
            await safe_eval(ws, f"""
                (() => {{
                    const btn = document.querySelector('{SELECTORS["done_button"]}')
                        || document.querySelector('{SELECTORS["done_fallback"]}');
                    if (btn) btn.click();
                    return !!btn;
                }})()
            """, "게시")
            await asyncio.sleep(3)
            steps_done.append("게시")

            # 완료 스냅샷
            await save_dom_snapshot(ws, "completed")
            state_manager.update(project_id, {"browser_metadata_filled": True})
            report("게시 완료!", TOTAL_STEPS, done=True)
            log.info(f"🎉 완료: {steps_done}")

    except Exception as e:
        log.error(f"실패 (완료: {steps_done}): {e}")
        report(f"실패 — {type(e).__name__}", 0, done=True, error=str(e)[:200])


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python _fill_meta_worker.py <project_id>")
        sys.exit(1)
    asyncio.run(fill_metadata(sys.argv[1]))
