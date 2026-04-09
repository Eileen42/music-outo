"""
Suno 자동화 레시피 녹화기.

사용자가 직접 suno.com/create 에서 조작하면 클릭/입력을 JS로 캡처해
suno_recipe.json 에 저장한다. 이후 일괄 생성 시 이 레시피를 재생한다.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path

from playwright.async_api import async_playwright, BrowserContext, Page, Playwright

from config import settings

logger = logging.getLogger("suno_recorder")

_EDGE_EXES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
]


def _find_exe() -> str | None:
    for p in _EDGE_EXES:
        if Path(p).exists():
            return p
    return None


def recipe_path() -> Path:
    return settings.browser_sessions_dir / "suno_recipe.json"


def _session_path() -> Path:
    return settings.browser_sessions_dir / "suno_context.json"


# ── 전역 상태 ────────────────────────────────────────────────────────────────
_state: dict = {
    "status":     "idle",   # idle | recording | done | error
    "message":    "",
    "playwright": None,
    "browser":    None,
    "context":    None,
    "page":       None,
}

# ── 브라우저 내 녹화 JS ──────────────────────────────────────────────────────
_RECORDER_JS = r"""
(function() {
    if (window.__sunoRecorderActive) return;
    window.__sunoRecorderActive = true;
    window.__recordedActions = [];
    window.__recordingDone   = false;

    /* ── 셀렉터 계산 ─────────────────────────────────────────────────── */
    function computeSelector(el) {
        if (!el || el === document.body) return 'body';
        const tid = el.getAttribute('data-testid');
        if (tid) return '[data-testid="' + tid + '"]';
        const ph = el.placeholder;
        if (ph) return el.tagName.toLowerCase() + '[placeholder="' + ph.replace(/"/g, '\\"') + '"]';
        const al = el.getAttribute('aria-label');
        if (al) return '[aria-label="' + al.replace(/"/g, '\\"') + '"]';
        if (el.id) return '#' + el.id;
        const siblings = Array.from((el.parentElement || document.body).children);
        const idx = siblings.indexOf(el) + 1;
        return computeSelector(el.parentElement) + '>' + el.tagName.toLowerCase() + ':nth-child(' + idx + ')';
    }

    /* ── 역할 자동 감지 ─────────────────────────────────────────────── */
    function detectRole(el, type) {
        if (type === 'click') {
            const txt = (el.innerText || '').trim().toLowerCase();
            if (txt === 'create' || txt === 'create song') return 'create';
            return null;   // null → 무시
        }
        const ph  = (el.placeholder || '').toLowerCase();
        const tid = (el.getAttribute('data-testid') || '').toLowerCase();
        if (tid.includes('lyrics') || ph.includes('lyric') || ph.includes('가사')) return 'lyrics';
        if (ph.includes('sound') || ph.includes('describe') || ph.includes('style') ||
            ph.includes('genre') || ph.includes('prompt'))  return 'style';
        if (ph.includes('title') || ph.includes('optional') || tid.includes('title')) return 'title';
        return 'other';
    }

    /* ── 오버레이 패널 ──────────────────────────────────────────────── */
    const panel = document.createElement('div');
    panel.id = '__suno_rec';
    panel.style.cssText =
        'position:fixed;top:16px;right:16px;z-index:2147483647;' +
        'background:#12121f;color:#e0e0e0;border:2px solid #e94560;' +
        'border-radius:12px;padding:14px 16px;width:270px;font:13px/1.5 monospace;' +
        'box-shadow:0 8px 32px rgba(0,0,0,.6);cursor:move;user-select:none;';
    panel.innerHTML =
        '<div style="font-weight:700;color:#e94560;margin-bottom:6px">🔴 녹화 중</div>' +
        '<div id="__rec_cnt" style="color:#aaa;font-size:12px;margin-bottom:6px">기록: 0개</div>' +
        '<div id="__rec_list" style="max-height:150px;overflow-y:auto;font-size:11px;' +
             'border-top:1px solid #333;padding-top:6px;margin-bottom:10px"></div>' +
        '<button id="__rec_ok" style="width:100%;padding:7px;background:#e94560;color:#fff;' +
             'border:none;border-radius:6px;cursor:pointer;font:700 13px monospace">' +
             '✅ 녹화 완료</button>' +
        '<div style="font-size:10px;color:#555;margin-top:5px">' +
             '가사 → 스타일 → 제목 → Create 순서로 진행하세요</div>';
    document.body.appendChild(panel);

    /* 드래그 */
    let drag=false,ox=0,oy=0;
    panel.addEventListener('mousedown',e=>{if(e.target.id==='__rec_ok')return;drag=true;ox=e.clientX-panel.offsetLeft;oy=e.clientY-panel.offsetTop;});
    document.addEventListener('mousemove',e=>{if(!drag)return;panel.style.left=(e.clientX-ox)+'px';panel.style.top=(e.clientY-oy)+'px';panel.style.right='auto';});
    document.addEventListener('mouseup',()=>drag=false);

    const ROLE_COLOR = {lyrics:'#4fc3f7',style:'#81c784',title:'#fff176',create:'#e94560',other:'#888'};

    function refresh() {
        document.getElementById('__rec_cnt').textContent = '기록: ' + window.__recordedActions.length + '개';
        const list = document.getElementById('__rec_list');
        list.innerHTML = window.__recordedActions.slice(-8).map(a => {
            const c = ROLE_COLOR[a.role] || '#ccc';
            const label = a.type==='fill'
                ? '✏️ [' + a.role + '] ' + (a.value||'').slice(0,22)
                : '👆 [' + a.role + '] ' + (a.text||'').slice(0,22);
            return '<div style="color:'+c+';white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin:2px 0">'+label+'</div>';
        }).join('');
    }

    /* input 이벤트: 같은 셀렉터면 value 업데이트 */
    document.addEventListener('input', e => {
        const el = e.target;
        if (!['INPUT','TEXTAREA'].includes(el.tagName)) return;
        if (el.closest('#__suno_rec')) return;
        const sel  = computeSelector(el);
        const role = detectRole(el, 'fill');
        const existing = window.__recordedActions.find(a => a.selector===sel && a.type==='fill');
        if (existing) { existing.value = el.value; }
        else { window.__recordedActions.push({type:'fill', selector:sel, role, value:el.value, placeholder:el.placeholder||''}); }
        refresh();
    }, true);

    /* click 이벤트: 의미 있는 것만 */
    document.addEventListener('click', e => {
        if (e.target.closest('#__suno_rec')) return;
        const el   = e.target.closest('button,[role="button"]') || e.target;
        const role = detectRole(el, 'click');
        if (!role) return;
        const sel  = computeSelector(el);
        const last = window.__recordedActions[window.__recordedActions.length-1];
        if (last && last.selector===sel && last.type==='click') return;
        window.__recordedActions.push({type:'click', selector:sel, role, text:(el.innerText||'').trim().slice(0,40)});
        refresh();
    }, true);

    /* 완료 버튼 */
    document.getElementById('__rec_ok').addEventListener('click', () => {
        window.__recordingDone = true;
        panel.style.borderColor = '#81c784';
        document.getElementById('__rec_ok').textContent = '✅ 완료됨 — 창을 닫지 마세요';
    });
})();
"""


# ── Public API ───────────────────────────────────────────────────────────────

async def start_recording() -> dict:
    """저장된 Suno 세션으로 브라우저를 열고 녹화를 시작한다."""
    global _state

    sp = _session_path()
    if not sp.exists():
        raise RuntimeError("저장된 Suno 세션이 없습니다. 먼저 로그인해주세요.")

    await _cleanup()

    exe = _find_exe()
    pw  = await async_playwright().start()
    _state["playwright"] = pw

    browser = await pw.chromium.launch(
        executable_path=exe,
        headless=False,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-first-run",
            "--disable-infobars",
        ],
    )
    _state["browser"] = browser

    context: BrowserContext = await browser.new_context(
        storage_state=str(sp),
        viewport={"width": 1280, "height": 900},
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/136.0.0.0 Safari/537.36 Edg/136.0.0.0"
        ),
    )
    _state["context"] = context

    page: Page = await context.new_page()
    _state["page"] = page

    await page.goto("https://suno.com/create", wait_until="domcontentloaded", timeout=30_000)
    await page.wait_for_timeout(3_000)
    await page.evaluate(_RECORDER_JS)

    _state.update({"status": "recording", "message": "녹화 중: 가사→스타일→제목→Create 순서로 시연하세요"})
    logger.info("Suno 레시피 녹화 시작")
    return {"status": "recording", "message": _state["message"]}


async def get_status() -> dict:
    """현재 녹화 상태와 기록된 동작 수를 반환한다."""
    page: Page | None = _state.get("page")
    action_count = 0
    auto_done    = False

    if page and _state["status"] == "recording":
        try:
            action_count = await page.evaluate("() => (window.__recordedActions||[]).length")
            auto_done    = await page.evaluate("() => window.__recordingDone === true")
        except Exception:
            pass

    return {
        "status":       _state["status"],
        "message":      _state["message"],
        "action_count": action_count,
        "auto_done":    auto_done,
    }


async def stop_recording() -> dict:
    """기록된 동작을 가져와 레시피로 저장하고 브라우저를 닫는다."""
    global _state

    if _state["status"] != "recording":
        raise RuntimeError(f"녹화 중이 아닙니다. (상태: {_state['status']})")

    page: Page | None = _state.get("page")
    if not page:
        raise RuntimeError("페이지가 없습니다.")

    actions: list[dict] = await page.evaluate("() => window.__recordedActions || []")

    if not actions:
        raise RuntimeError("기록된 동작이 없습니다. 가사/스타일/제목 입력 후 Create를 클릭하고 녹화 완료를 눌러주세요.")

    recipe = {
        "version":     1,
        "recorded_at": datetime.now().isoformat(),
        "actions":     actions,
    }
    rp = recipe_path()
    rp.parent.mkdir(parents=True, exist_ok=True)
    rp.write_text(json.dumps(recipe, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(f"레시피 저장: {rp} ({len(actions)}개 동작)")

    await _cleanup()
    _state["status"] = "done"

    return {
        "status":       "done",
        "action_count": len(actions),
        "actions":      actions,
    }


async def cancel_recording() -> None:
    """녹화를 취소하고 브라우저를 닫는다."""
    await _cleanup()
    _state["status"] = "idle"


def get_recipe() -> dict | None:
    """저장된 레시피를 반환한다. 없으면 None."""
    rp = recipe_path()
    if not rp.exists():
        return None
    try:
        return json.loads(rp.read_text(encoding="utf-8"))
    except Exception:
        return None


# ── 내부 정리 ─────────────────────────────────────────────────────────────────

async def _cleanup() -> None:
    for key in ("page", "context", "browser"):
        obj = _state.get(key)
        if obj:
            try:
                await obj.close()
            except Exception:
                pass
            _state[key] = None

    pw = _state.get("playwright")
    if pw:
        try:
            await pw.stop()
        except Exception:
            pass
        _state["playwright"] = None

    _state.update({"status": "idle", "message": ""})
