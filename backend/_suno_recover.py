"""
Suno 곡 복구 스크립트 — Suno에서 생성된 곡을 검색하여 다운로드.
기존 파일이 없는 곡만 Suno 라이브러리에서 찾아 다운받는다.

사용: python _suno_recover.py <project_id>
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import sys
from pathlib import Path

_DIR = Path(__file__).parent
sys.path.insert(0, str(_DIR))

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

logging.basicConfig(level=logging.INFO, stream=sys.stderr)
logger = logging.getLogger("suno_recover")


async def main(project_id: str) -> None:
    from core.state_manager import state_manager
    from browser.suno_automation import SunoAutomation

    state = state_manager.get(project_id)
    if not state:
        logger.error("프로젝트 없음")
        return

    tracks = state.get("designed_tracks") or []
    project_dir = _DIR / "storage" / "projects" / project_id / "tracks"
    project_dir.mkdir(parents=True, exist_ok=True)

    # 이미 존재하는 파일 확인
    existing_files = list(project_dir.glob("*.mp3"))
    logger.info(f"기존 파일: {len(existing_files)}개")
    for f in existing_files:
        logger.info(f"  {f.name}")

    # 파일이 없거나 불완전한 곡 찾기
    missing_titles = []
    title_to_index = {}
    for t in tracks:
        idx = t.get("index", 0)
        title = t.get("title", "")
        safe_title = re.sub(r'[\u4E00-\u9FFF\u3400-\u4DBF\\/:*?"<>|]', "_", title)

        v1_exists = any(f.name.startswith(f"{idx:02d}_") and "_v1.mp3" in f.name for f in existing_files)
        v2_exists = any(f.name.startswith(f"{idx:02d}_") and "_v2.mp3" in f.name for f in existing_files)

        if not v1_exists or not v2_exists:
            missing_titles.append(title)
            title_to_index[title] = idx
            logger.info(f"  미완료: [{idx:02d}] {title} (v1={'OK' if v1_exists else 'MISSING'}, v2={'OK' if v2_exists else 'MISSING'})")

    if not missing_titles:
        logger.info("모든 곡 파일 완료!")
        return

    logger.info(f"\n{len(missing_titles)}곡 Suno에서 검색하여 다운로드 시작...")

    # Suno에서 검색 후 다운로드
    known_ids: set[str] = set()
    # 기존 suno_tracks에서 known_ids 수집
    for st in state.get("suno_tracks", []):
        if st.get("suno_id"):
            known_ids.add(st["suno_id"])

    async with SunoAutomation(max_concurrent=1, headless=False) as suno:
        results = await suno.find_siblings_by_search(
            titles=missing_titles,
            known_ids=known_ids,
            output_dir=str(project_dir),
            title_to_index=title_to_index,
        )

    # state.json에 저장
    old_suno = state.get("suno_tracks") or []
    new_keys = {(r.get("index"), r.get("slot")) for r in results if r.get("index") and r.get("slot")}
    merged = [t for t in old_suno if (t.get("index"), t.get("slot")) not in new_keys]
    merged.extend(results)
    merged.sort(key=lambda t: (t.get("index", 0), t.get("slot", 0)))
    state_manager.update(project_id, {"suno_tracks": merged})

    completed = len([r for r in results if r["status"] == "completed"])
    logger.info(f"\n복구 완료: {completed}/{len(results)}개 다운로드 성공")

    # 최종 파일 확인
    final_files = list(project_dir.glob("*.mp3"))
    logger.info(f"최종 파일: {len(final_files)}개")
    for f in sorted(final_files, key=lambda x: x.name):
        logger.info(f"  {f.name} ({f.stat().st_size // 1024}KB)")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python _suno_recover.py <project_id>", file=sys.stderr)
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
