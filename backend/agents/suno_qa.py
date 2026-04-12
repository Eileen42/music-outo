"""
QA Agent — 전체 검수 담당.

역할:
  1. 프로젝트 폴더에 설계된 곡 기준으로 v1, v2 파일이 있는지 확인
  2. 프론트엔드 state.json에 제대로 연결되어 있는지 검증
  3. 누락된 곡 목록 반환
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from core.state_manager import state_manager

logger = logging.getLogger("suno_qa")


class SunoQAAgent:
    """프로젝트의 곡 파일 완성도를 검수하는 에이전트."""

    def verify(self, project_id: str) -> dict:
        """
        프로젝트 검수 실행.

        Returns:
            {
                "status": "pass" | "partial" | "fail",
                "total_designed": int,
                "total_files": int,
                "tracks": [
                    {
                        "index": 1,
                        "title": "...",
                        "v1_exists": True,
                        "v2_exists": True,
                        "v1_path": "...",
                        "v2_path": "...",
                        "v1_linked": True,  # state.json에 연결됨
                        "v2_linked": True,
                        "status": "complete" | "partial" | "missing"
                    },
                    ...
                ],
                "missing": [{"index": 1, "title": "...", "missing": ["v1", "v2"]}, ...],
                "unlinked": [{"index": 1, "title": "...", "slot": 1}, ...],
            }
        """
        state = state_manager.get(project_id)
        if not state:
            return {"status": "fail", "error": "프로젝트를 찾을 수 없습니다"}

        designed = state.get("designed_tracks") or []
        suno_tracks = state.get("suno_tracks") or []
        tracks_dir = state_manager.project_dir(project_id) / "tracks"

        # suno_tracks에서 index+slot별 파일 매핑
        linked_map: dict[tuple[int, int], dict] = {}
        for st in suno_tracks:
            key = (st.get("index", 0), st.get("slot", 0))
            linked_map[key] = st

        results = []
        missing = []
        unlinked = []
        total_files = 0

        for dt in designed:
            index = dt.get("index", 0)
            title = dt.get("title", f"Track_{index}")
            safe_title = re.sub(r'[\u4E00-\u9FFF\u3400-\u4DBF\\/:*?"<>|]', "_", title)

            # 파일 존재 확인
            v1_pattern = f"{index:02d}_*_v1.mp3"
            v2_pattern = f"{index:02d}_*_v2.mp3"
            v1_files = list(tracks_dir.glob(v1_pattern)) if tracks_dir.exists() else []
            v2_files = list(tracks_dir.glob(v2_pattern)) if tracks_dir.exists() else []

            v1_exists = len(v1_files) > 0
            v2_exists = len(v2_files) > 0

            # state.json 연결 확인
            v1_linked = (index, 1) in linked_map and linked_map[(index, 1)].get("status") == "completed"
            v2_linked = (index, 2) in linked_map and linked_map[(index, 2)].get("status") == "completed"

            if v1_exists:
                total_files += 1
            if v2_exists:
                total_files += 1

            # 상태 판정
            if v1_exists and v2_exists:
                status = "complete"
            elif v1_exists or v2_exists:
                status = "partial"
            else:
                status = "missing"

            track_result = {
                "index": index,
                "title": title,
                "v1_exists": v1_exists,
                "v2_exists": v2_exists,
                "v1_path": str(v1_files[0]) if v1_files else "",
                "v2_path": str(v2_files[0]) if v2_files else "",
                "v1_linked": v1_linked,
                "v2_linked": v2_linked,
                "status": status,
            }
            results.append(track_result)

            # 누락 목록
            missing_slots = []
            if not v1_exists:
                missing_slots.append("v1")
            if not v2_exists:
                missing_slots.append("v2")
            if missing_slots:
                missing.append({"index": index, "title": title, "missing": missing_slots})

            # 연결 안 된 목록
            if v1_exists and not v1_linked:
                unlinked.append({"index": index, "title": title, "slot": 1})
            if v2_exists and not v2_linked:
                unlinked.append({"index": index, "title": title, "slot": 2})

        # 전체 상태
        all_complete = all(t["status"] == "complete" for t in results)
        any_exists = any(t["status"] != "missing" for t in results)

        overall = "pass" if all_complete else ("partial" if any_exists else "fail")

        report = {
            "status": overall,
            "total_designed": len(designed),
            "total_files": total_files,
            "expected_files": len(designed) * 2,
            "tracks": results,
            "missing": missing,
            "unlinked": unlinked,
        }

        logger.info(
            f"QA 검수 완료: {overall} — "
            f"{total_files}/{len(designed)*2} 파일, "
            f"{len(missing)} 누락, {len(unlinked)} 미연결"
        )
        return report

    def fix_links(self, project_id: str) -> dict:
        """
        파일은 있지만 state.json에 연결 안 된 곡들을 자동으로 연결.
        """
        report = self.verify(project_id)
        if not report.get("unlinked"):
            return {"fixed": 0, "message": "연결할 항목 없음"}

        state = state_manager.get(project_id)
        suno_tracks = state.get("suno_tracks") or []
        tracks_dir = state_manager.project_dir(project_id) / "tracks"

        fixed = 0
        for item in report["unlinked"]:
            index = item["index"]
            slot = item["slot"]
            pattern = f"{index:02d}_*_v{slot}.mp3"
            files = list(tracks_dir.glob(pattern))
            if not files:
                continue

            # 이미 있는 항목 업데이트 or 새로 추가
            existing = next(
                (t for t in suno_tracks if t.get("index") == index and t.get("slot") == slot),
                None,
            )
            if existing:
                existing["file_path"] = str(files[0])
                existing["status"] = "completed"
            else:
                suno_tracks.append({
                    "index": index,
                    "title": item["title"],
                    "slot": slot,
                    "suno_id": "",
                    "file_path": str(files[0]),
                    "status": "completed",
                })
            fixed += 1

        if fixed:
            suno_tracks.sort(key=lambda t: (t.get("index", 0), t.get("slot", 0)))
            state_manager.update(project_id, {"suno_tracks": suno_tracks})

        logger.info(f"QA fix_links: {fixed}개 연결 수정")
        return {"fixed": fixed, "message": f"{fixed}개 항목 연결 완료"}


suno_qa_agent = SunoQAAgent()
