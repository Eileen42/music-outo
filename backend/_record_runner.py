"""레시피 녹화 실행 스크립트 (폴링 방식, input() 없음)"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

LOG = os.path.join(os.path.dirname(__file__), "_record_log.txt")

def log(msg):
    print(msg, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(msg + "\n")

async def main():
    open(LOG, "w").close()  # 로그 초기화
    log("=== Suno 레시피 녹화 시작 ===")

    from browser.suno_recorder import start_recording, get_status, stop_recording

    try:
        r = await start_recording()
        log(f"브라우저 열림: {r}")
    except Exception as e:
        log(f"ERROR 브라우저 열기 실패: {e}")
        return

    log("-> 브라우저에서 가사->스타일->제목->Create 순으로 시연하세요")
    log("-> 오버레이 [녹화 완료] 버튼을 누르면 자동 저장됩니다 (최대 10분 대기)")

    for i in range(300):  # 최대 10분
        await asyncio.sleep(2)
        try:
            s = await get_status()
            log(f"[{i*2}s] 동작수={s['action_count']} auto_done={s['auto_done']} status={s['status']}")
            if s["auto_done"]:
                log("오버레이 완료 감지! 저장 중...")
                res = await stop_recording()
                log(f"[DONE] 레시피 저장 완료: {res['action_count']}개 동작")
                log(f"파일: {res}")
                return
        except Exception as e:
            log(f"폴링 오류: {e}")
            await asyncio.sleep(3)

    log("TIMEOUT: 10분 내에 녹화 완료가 감지되지 않았습니다.")

asyncio.run(main())
