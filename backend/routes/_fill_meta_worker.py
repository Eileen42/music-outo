"""
메타데이터 자동 입력 워커 — CDP WebSocket 직접 사용 (Playwright 없이).
Edge의 CDP가 Playwright connect_over_cdp와 호환 문제 있어서 순수 CDP 사용.

사용법: python routes/_fill_meta_worker.py <project_id>
"""
import asyncio
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [워커] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


async def cdp_eval(ws, expr, timeout=10):
    """CDP Runtime.evaluate 실행."""
    import random
    msg_id = random.randint(1000, 9999)
    await ws.send(json.dumps({
        "id": msg_id,
        "method": "Runtime.evaluate",
        "params": {"expression": expr, "returnByValue": True, "awaitPromise": True}
    }))
    # 응답 대기
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


async def cdp_set_file(ws, selector, file_path):
    """CDP로 file input에 파일 설정."""
    import random
    # 1. 노드 찾기
    msg_id = random.randint(1000, 9999)
    await ws.send(json.dumps({
        "id": msg_id,
        "method": "Runtime.evaluate",
        "params": {
            "expression": f'document.querySelector("{selector}")',
            "returnByValue": False,
        }
    }))
    raw = await asyncio.wait_for(ws.recv(), timeout=5)
    resp = json.loads(raw)
    obj_id = resp.get("result", {}).get("result", {}).get("objectId")
    if not obj_id:
        return False

    # 2. DOM.describeNode로 backendNodeId 가져오기
    msg_id2 = random.randint(1000, 9999)
    await ws.send(json.dumps({
        "id": msg_id2,
        "method": "DOM.describeNode",
        "params": {"objectId": obj_id}
    }))
    raw2 = await asyncio.wait_for(ws.recv(), timeout=5)
    resp2 = json.loads(raw2)
    backend_id = resp2.get("result", {}).get("node", {}).get("backendNodeId")
    if not backend_id:
        return False

    # 3. DOM.setFileInputFiles
    msg_id3 = random.randint(1000, 9999)
    await ws.send(json.dumps({
        "id": msg_id3,
        "method": "DOM.setFileInputFiles",
        "params": {
            "files": [str(file_path)],
            "backendNodeId": backend_id,
        }
    }))
    raw3 = await asyncio.wait_for(ws.recv(), timeout=5)
    return True


async def fill_metadata(project_id: str):
    import httpx
    import websockets
    from core.state_manager import state_manager

    state = state_manager.get(project_id)
    if not state:
        log.error(f"프로젝트 없음: {project_id}")
        return

    meta = state.get("metadata", {})
    title = meta.get("title", "")
    desc = meta.get("description", "")
    tags = meta.get("tags", [])
    images = state.get("images", {})
    thumb = images.get("thumbnail", "")

    log.info(f"시작: {title[:30]}...")
    steps_done = []

    # CDP 탭 목록에서 upload 탭 찾기
    try:
        r = httpx.get("http://localhost:9224/json", timeout=3)
        tabs = r.json()
    except Exception as e:
        log.error(f"CDP 연결 실패: {e}")
        return

    ws_url = None
    for t in tabs:
        url = t.get("url", "")
        if "studio.youtube.com" in url:
            ws_url = t["webSocketDebuggerUrl"]
            log.info(f"탭: {url[:60]}")
            break

    if not ws_url:
        log.error("YouTube Studio 탭 없음")
        return

    try:
        async with websockets.connect(ws_url, max_size=10_000_000) as ws:
            # title-textarea 존재 확인
            has_title = await cdp_eval(ws, '!!document.querySelector("#title-textarea [contenteditable]")')
            if not has_title:
                log.error("업로드 편집 페이지가 아닙니다 (제목란 없음)")
                return
            log.info("편집 페이지 확인됨")

            # 오버레이 제거
            await cdp_eval(ws, """
                document.querySelectorAll('tp-yt-iron-overlay-backdrop').forEach(o => o.remove());
            """)

            # ── 1. 제목 ──
            r = await cdp_eval(ws, f"""
                (() => {{
                    document.querySelectorAll('tp-yt-iron-overlay-backdrop').forEach(o => o.remove());
                    const el = document.querySelector('#title-textarea [contenteditable]');
                    if (!el) return false;
                    el.focus();
                    el.textContent = '';
                    document.execCommand('selectAll', false, null);
                    document.execCommand('insertText', false, {json.dumps(title[:100])});
                    el.dispatchEvent(new Event('input', {{ bubbles: true }}));
                    return true;
                }})()
            """)
            if r:
                steps_done.append("제목")
                log.info("✓ 제목")
            await asyncio.sleep(1)

            # ── 2. 설명 ──
            r = await cdp_eval(ws, f"""
                (() => {{
                    document.querySelectorAll('tp-yt-iron-overlay-backdrop').forEach(o => o.remove());
                    const el = document.querySelector('#description-textarea [contenteditable]');
                    if (!el) return false;
                    el.focus();
                    el.textContent = '';
                    document.execCommand('selectAll', false, null);
                    document.execCommand('insertText', false, {json.dumps(desc[:5000])});
                    el.dispatchEvent(new Event('input', {{ bubbles: true }}));
                    return true;
                }})()
            """)
            if r:
                steps_done.append("설명")
                log.info("✓ 설명")
            await asyncio.sleep(1)

            # ── 3. 더보기 + 태그 ──
            await cdp_eval(ws, """
                (() => {
                    document.querySelectorAll('tp-yt-iron-overlay-backdrop').forEach(o => o.remove());
                    const btns = [...document.querySelectorAll('button')];
                    const more = btns.find(b => b.textContent.includes('더보기'));
                    if (more) more.click();
                })()
            """)
            await asyncio.sleep(1)

            if tags:
                for tag in tags[:30]:
                    await cdp_eval(ws, f"""
                        (() => {{
                            const inp = document.querySelector('ytcp-chip-bar #text-input')
                                || document.querySelector("input[aria-label*='태그']");
                            if (!inp) return;
                            inp.focus();
                            inp.value = {json.dumps(tag.strip())};
                            inp.dispatchEvent(new Event('input', {{ bubbles: true }}));
                            inp.dispatchEvent(new KeyboardEvent('keydown', {{ key: 'Enter', keyCode: 13, bubbles: true }}));
                        }})()
                    """)
                    await asyncio.sleep(0.3)
                steps_done.append(f"태그({len(tags[:30])}개)")
                log.info(f"✓ 태그 {len(tags[:30])}개")

            # ── 4. 썸네일 ──
            if thumb and Path(thumb).exists():
                try:
                    ok = await cdp_set_file(ws, "input#file-loader[type='file']", thumb)
                    if ok:
                        steps_done.append("썸네일")
                        log.info("✓ 썸네일")
                        await asyncio.sleep(3)
                except Exception as e:
                    log.warning(f"썸네일 건너뜀: {e}")

            # ── 5. 아동용 아님 ──
            await cdp_eval(ws, """
                (() => {
                    document.querySelectorAll('tp-yt-iron-overlay-backdrop').forEach(o => o.remove());
                    const nfk = document.querySelector("#audience [name='VIDEO_MADE_FOR_KIDS_NOT_MFK']")
                        || document.querySelector("tp-yt-paper-radio-button[name='NOT_MADE_FOR_KIDS']");
                    if (nfk) nfk.click();
                })()
            """)
            await asyncio.sleep(0.5)
            steps_done.append("아동용아님")

            # ── 6. 다음 x3 ──
            for step in range(3):
                await cdp_eval(ws, """
                    (() => {
                        document.querySelectorAll('tp-yt-iron-overlay-backdrop').forEach(o => o.remove());
                        const btn = document.querySelector("#next-button") || document.querySelector("ytcp-button#next-button");
                        if (btn) btn.click();
                    })()
                """)
                await asyncio.sleep(2)
                steps_done.append(f"다음{step + 1}")

            # ── 7. 일부공개 ──
            await cdp_eval(ws, """
                (() => {
                    document.querySelectorAll('tp-yt-iron-overlay-backdrop').forEach(o => o.remove());
                    const ul = document.querySelector("tp-yt-paper-radio-button[name='UNLISTED']");
                    if (ul) ul.click();
                })()
            """)
            await asyncio.sleep(1)
            steps_done.append("일부공개")

            # ── 8. 저장 ──
            await cdp_eval(ws, """
                (() => {
                    document.querySelectorAll('tp-yt-iron-overlay-backdrop').forEach(o => o.remove());
                    const btn = document.querySelector("#done-button") || document.querySelector("ytcp-button#done-button");
                    if (btn) btn.click();
                })()
            """)
            await asyncio.sleep(3)
            steps_done.append("게시")

            state_manager.update(project_id, {"browser_metadata_filled": True})
            log.info(f"완료: {steps_done}")

    except Exception as e:
        log.error(f"실패 (완료: {steps_done}): {e}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python _fill_meta_worker.py <project_id>")
        sys.exit(1)

    asyncio.run(fill_metadata(sys.argv[1]))
