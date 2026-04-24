"""Phase 2 E2E QA — Playwright 사용자 브라우저 플로우.

시나리오:
  1. 랜딩 페이지 로드
  2. RegisterForm → 가입 신청
  3. PendingApproval 화면 진입 확인
  4. (별도 탭) AdminPage 로그인 + 사용자 승인
  5. 원 탭 새로고침 → DownloadPage (approved) 전환 확인
  6. 로그아웃 → RegisterForm 로그인 모드 → 가입한 계정으로 재로그인 → DownloadPage

실행 전 요구사항:
  - backend (127.0.0.1:8000) 기동됨
  - frontend (localhost:3000) 기동됨
  - backend/storage/users.json 삭제 (clean state)
"""

import asyncio
import sys
import traceback
from pathlib import Path

from playwright.async_api import Page, async_playwright

# Windows 콘솔 기본 cp949 -> UTF-8 로 전환 (한글/기호 출력)
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE = "http://localhost:3000"
ADMIN_SECRET = "admin1234"
TEST_EMAIL = "e2e@test.com"
TEST_PASSWORD = "pw1234"
TEST_NAME = "E2E테스트"

SCREENSHOT_DIR = Path(__file__).parent / "screenshots"
SCREENSHOT_DIR.mkdir(exist_ok=True)


class QAReport:
    def __init__(self):
        self.steps: list[tuple[str, bool, str]] = []

    def ok(self, name: str):
        self.steps.append((name, True, ""))
        print(f"  [PASS] {name}")

    def fail(self, name: str, err: str):
        self.steps.append((name, False, err))
        print(f"  [FAIL] {name}: {err}")

    def summary(self) -> int:
        passed = sum(1 for _, ok, _ in self.steps if ok)
        total = len(self.steps)
        print("\n" + "=" * 60)
        print(f"QA PHASE 2 - {passed}/{total} passed")
        for name, ok, err in self.steps:
            mark = "OK" if ok else "FAIL"
            print(f"  [{mark}] {name}")
            if err:
                print(f"         {err}")
        print("=" * 60)
        return 0 if passed == total else 1


async def shot(page: Page, name: str):
    try:
        await page.screenshot(path=str(SCREENSHOT_DIR / f"{name}.png"))
    except Exception:
        pass


async def run(report: QAReport):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)

        # ── 사용자 브라우저 ────────────────────────────────────────────────
        user_ctx = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            locale="ko-KR",
        )
        user_page = await user_ctx.new_page()

        # --- [1] 랜딩 페이지 로드 ---
        try:
            await user_page.goto(f"{BASE}/?auth=force", wait_until="networkidle")
            await user_page.wait_for_selector("text=시작하기", timeout=10_000)
            await shot(user_page, "01_landing")
            report.ok("[1] 랜딩 페이지 로드 (?auth=force)")
        except Exception as e:
            await shot(user_page, "01_landing_FAIL")
            report.fail("[1] 랜딩 페이지 로드", str(e))
            return

        # --- [2] RegisterForm 진입 ---
        try:
            await user_page.click("text=시작하기")
            # 로그인 폼이 기본
            await user_page.wait_for_selector("text=계정이 없으신가요?", timeout=5000)
            await shot(user_page, "02_register_form_login")
            report.ok("[2] RegisterForm 로그인 모드")
        except Exception as e:
            await shot(user_page, "02_login_mode_FAIL")
            report.fail("[2] RegisterForm 진입", str(e))
            return

        # --- [3] 가입 신청 모드 전환 ---
        try:
            await user_page.click("text=가입 신청")
            await user_page.wait_for_selector('input[placeholder="홍길동"]', timeout=5000)
            report.ok("[3] 가입 신청 모드 전환")
        except Exception as e:
            await shot(user_page, "03_signup_mode_FAIL")
            report.fail("[3] 가입 모드 전환", str(e))
            return

        # --- [4] 폼 입력 + 제출 ---
        try:
            await user_page.fill('input[placeholder="홍길동"]', TEST_NAME)
            await user_page.fill('input[type="email"]', TEST_EMAIL)
            await user_page.fill('input[type="password"]', TEST_PASSWORD)
            await user_page.fill('input[type="tel"]', "010-9999-0000")
            await user_page.select_option("select", "SNS")
            await shot(user_page, "04_form_filled")

            await user_page.click('button[type="submit"]:has-text("가입 신청")')
            await user_page.wait_for_selector("text=승인 대기", timeout=10_000)
            await shot(user_page, "05_pending")
            report.ok("[4] 가입 완료 + PendingApproval 진입")
        except Exception as e:
            await shot(user_page, "04_signup_FAIL")
            report.fail("[4] 가입/대기화면", str(e))
            return

        # ── 관리자 브라우저 (별 컨텍스트 = 로그인 분리) ──────────────────
        admin_ctx = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            locale="ko-KR",
        )
        admin_page = await admin_ctx.new_page()

        # --- [5] 관리자 로그인 ---
        # AdminPage 의 secret onChange + useEffect(fetchUsers) 구조상
        # 비번 입력 순간 자동으로 fetchUsers 발동 -> 성공이면 폼 자체가 unmount.
        # 따라서 Enter/버튼 누를 필요 없이 입력만 하고 다음 화면을 기다린다.
        # (사전에 localStorage 에 세팅해 두면 더 확실)
        try:
            await admin_ctx.add_init_script(
                f"window.localStorage.setItem('admin_secret', '{ADMIN_SECRET}')"
            )
            await admin_page.goto(f"{BASE}/?admin=true", wait_until="networkidle")
            await admin_page.wait_for_selector("text=사용자 관리", timeout=10_000)
            await admin_page.wait_for_selector(f"text={TEST_EMAIL}", timeout=10_000)
            await shot(admin_page, "06_admin_list")
            report.ok("[5] Admin 로그인 + 사용자 목록 확인")
        except Exception as e:
            await shot(admin_page, "06_admin_FAIL")
            report.fail("[5] Admin 로그인", str(e))
            return

        # --- [6] 관리자 승인 ---
        try:
            row = admin_page.locator(f'tr:has-text("{TEST_EMAIL}")')
            await row.locator('button:has-text("승인")').click()
            # 테이블 새로고침 후 상태 뱃지가 "승인" 으로 바뀌는지
            await admin_page.wait_for_timeout(500)
            row_after = admin_page.locator(f'tr:has-text("{TEST_EMAIL}")')
            status_txt = (await row_after.locator('span.text-xs').first.inner_text()).strip()
            await shot(admin_page, "07_admin_approved")
            if status_txt == "승인":
                report.ok("[6] 관리자 승인 클릭 + 상태=승인")
            else:
                report.fail("[6] 관리자 승인", f"상태 뱃지='{status_txt}' (expected 승인)")
        except Exception as e:
            await shot(admin_page, "07_approve_FAIL")
            report.fail("[6] 관리자 승인", str(e))
            return

        # --- [7] 사용자 탭 reload → DownloadPage ---
        try:
            await user_page.reload()
            await user_page.wait_for_selector("text=가입 승인 완료", timeout=15_000)
            await user_page.wait_for_selector(f"text={TEST_NAME} 님", timeout=5000)
            await shot(user_page, "08_download_page")
            report.ok("[7] 사용자 approved 전환 + DownloadPage")
        except Exception as e:
            await shot(user_page, "08_download_FAIL")
            report.fail("[7] 승인 반영", str(e))
            return

        # --- [8] 로그아웃 -> LandingPage 로 이동
        # (handleLogout 의 setAuthState('register') 는 authToken='' 로 인한
        #  useEffect 의 setAuthState('landing') 에 즉시 덮어써진다 = 정상 동작)
        try:
            await user_page.click('button:has-text("로그아웃")')
            await user_page.wait_for_selector("text=시작하기", timeout=5000)
            await shot(user_page, "09_after_logout_landing")
            report.ok("[8] 로그아웃 → LandingPage")
        except Exception as e:
            await shot(user_page, "09_logout_FAIL")
            report.fail("[8] 로그아웃", str(e))
            return

        # --- [9] 재로그인 (Landing → 로그인 → 승인된 계정 복귀) ---
        try:
            await user_page.click("text=로그인 / 가입")
            await user_page.wait_for_selector("text=계정이 없으신가요?", timeout=5000)
            await user_page.fill('input[type="email"]', TEST_EMAIL)
            await user_page.fill('input[type="password"]', TEST_PASSWORD)
            await user_page.click('button[type="submit"]:has-text("로그인")')
            await user_page.wait_for_selector("text=가입 승인 완료", timeout=10_000)
            await shot(user_page, "10_relogin_download")
            report.ok("[9] 재로그인 → DownloadPage")
        except Exception as e:
            await shot(user_page, "10_relogin_FAIL")
            report.fail("[9] 재로그인", str(e))
            return

        await browser.close()


async def main():
    report = QAReport()
    try:
        await run(report)
    except Exception as e:
        print("예외:", e)
        traceback.print_exc()
        report.fail("TOP-LEVEL", repr(e))
    return report.summary()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
