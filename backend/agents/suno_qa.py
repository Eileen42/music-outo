"""
QA Agent — 전체 검수 + 데이터 정합성 보장.

역할:
  1. verify: 파일 존재 + state.json 연결 확인
  2. fix_links: 파일 있지만 미연결된 곡 자동 연결
  3. cleanup: 중복/고아 데이터 제거, 파일 무결성 검증
  4. final_check: 생성/재생성 완료 후 최종 검수 (verify + fix + cleanup 통합)
"""
from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path

from core.state_manager import state_manager

logger = logging.getLogger("suno_qa")


class SunoQAAgent:
    """프로젝트의 곡 파일 완성도를 검수하는 에이전트."""

    def verify(self, project_id: str) -> dict:
        """파일 존재 + state.json 연결 확인."""
        state = state_manager.get(project_id)
        if not state:
            return {"status": "fail", "error": "프로젝트를 찾을 수 없습니다"}

        designed = state.get("designed_tracks") or []
        suno_tracks = state.get("suno_tracks") or []
        tracks_dir = state_manager.project_dir(project_id) / "tracks"

        linked_map: dict[tuple[int, int], dict] = {}
        for st in suno_tracks:
            key = (st.get("index", 0), st.get("slot", 0))
            linked_map[key] = st

        results, missing, unlinked = [], [], []
        total_files = 0

        for dt in designed:
            index = dt.get("index", 0)
            title = dt.get("title", f"Track_{index}")

            # `_v1.mp3`(클린) + `_v1_<uuid>.mp3`(쿠키 런너) 양쪽 매칭
            if tracks_dir.exists():
                v1_files = list(tracks_dir.glob(f"{index:02d}_*_v1.mp3")) + list(tracks_dir.glob(f"{index:02d}_*_v1_*.mp3"))
                v2_files = list(tracks_dir.glob(f"{index:02d}_*_v2.mp3")) + list(tracks_dir.glob(f"{index:02d}_*_v2_*.mp3"))
            else:
                v1_files, v2_files = [], []
            v1_exists = len(v1_files) > 0 and v1_files[0].stat().st_size > 10_000
            v2_exists = len(v2_files) > 0 and v2_files[0].stat().st_size > 10_000

            v1_linked = (index, 1) in linked_map and linked_map[(index, 1)].get("status") == "completed"
            v2_linked = (index, 2) in linked_map and linked_map[(index, 2)].get("status") == "completed"

            if v1_exists: total_files += 1
            if v2_exists: total_files += 1

            status = "complete" if (v1_exists and v2_exists) else ("partial" if (v1_exists or v2_exists) else "missing")

            results.append({
                "index": index, "title": title,
                "v1_exists": v1_exists, "v2_exists": v2_exists,
                "v1_path": str(v1_files[0]) if v1_files else "",
                "v2_path": str(v2_files[0]) if v2_files else "",
                "v1_linked": v1_linked, "v2_linked": v2_linked,
                "status": status,
            })

            ms = []
            if not v1_exists: ms.append("v1")
            if not v2_exists: ms.append("v2")
            if ms: missing.append({"index": index, "title": title, "missing": ms})

            if v1_exists and not v1_linked: unlinked.append({"index": index, "title": title, "slot": 1})
            if v2_exists and not v2_linked: unlinked.append({"index": index, "title": title, "slot": 2})

        all_ok = all(t["status"] == "complete" for t in results)
        any_ok = any(t["status"] != "missing" for t in results)
        overall = "pass" if all_ok else ("partial" if any_ok else "fail")

        return {
            "status": overall, "total_designed": len(designed),
            "total_files": total_files, "expected_files": len(designed) * 2,
            "tracks": results, "missing": missing, "unlinked": unlinked,
        }

    def fix_links(self, project_id: str) -> dict:
        """파일 있지만 미연결된 곡 자동 연결."""
        report = self.verify(project_id)
        if not report.get("unlinked"):
            return {"fixed": 0}

        state = state_manager.get(project_id)
        suno_tracks = state.get("suno_tracks") or []
        tracks_dir = state_manager.project_dir(project_id) / "tracks"
        fixed = 0

        for item in report["unlinked"]:
            index, slot = item["index"], item["slot"]
            files = (
                list(tracks_dir.glob(f"{index:02d}_*_v{slot}.mp3"))
                + list(tracks_dir.glob(f"{index:02d}_*_v{slot}_*.mp3"))
            )
            if not files:
                continue

            existing = next((t for t in suno_tracks if t.get("index") == index and t.get("slot") == slot), None)
            if existing:
                existing["file_path"] = str(files[0])
                existing["status"] = "completed"
            else:
                suno_tracks.append({
                    "index": index, "title": item["title"], "slot": slot,
                    "suno_id": "", "file_path": str(files[0]), "status": "completed",
                })
            fixed += 1

        if fixed:
            suno_tracks.sort(key=lambda t: (t.get("index", 0), t.get("slot", 0)))
            state_manager.update(project_id, {"suno_tracks": suno_tracks})

        return {"fixed": fixed}

    def cleanup(self, project_id: str) -> dict:
        """
        데이터 정합성 검증 + 정리.
        1. suno_tracks에서 index/slot 없는 항목 제거
        2. (index, slot) 중복 제거 (완료 상태 우선)
        3. 빈 파일(10KB 미만) 삭제
        4. 동일 음원(해시 중복) 감지
        5. designed_tracks에 없는 index의 suno_tracks 제거
        """
        state = state_manager.get(project_id)
        if not state:
            return {"error": "프로젝트 없음"}

        designed = state.get("designed_tracks") or []
        suno_tracks = state.get("suno_tracks") or []
        tracks_dir = state_manager.project_dir(project_id) / "tracks"
        valid_indices = {dt.get("index", i+1) for i, dt in enumerate(designed)}

        removed_invalid = 0
        removed_dupes = 0
        removed_orphans = 0
        removed_empty = 0
        hash_dupes = []

        # 1. index/slot 없는 항목 제거
        valid = [t for t in suno_tracks if t.get("index") and t.get("slot")]
        removed_invalid = len(suno_tracks) - len(valid)

        # 2. designed에 없는 index 제거
        before = len(valid)
        valid = [t for t in valid if t["index"] in valid_indices]
        removed_orphans = before - len(valid)

        # 3. (index, slot) 중복 제거 — completed 우선
        deduped: dict[tuple, dict] = {}
        for t in valid:
            key = (t["index"], t["slot"])
            if key not in deduped:
                deduped[key] = t
            elif t.get("status") == "completed" and deduped[key].get("status") != "completed":
                deduped[key] = t
        removed_dupes = len(valid) - len(deduped)
        clean_tracks = sorted(deduped.values(), key=lambda t: (t["index"], t["slot"]))

        # 4. 빈 파일(10KB 미만) 삭제
        if tracks_dir.exists():
            for f in tracks_dir.glob("*.mp3"):
                if f.stat().st_size < 10_000:
                    logger.warning(f"빈 파일 삭제: {f.name} ({f.stat().st_size}B)")
                    f.unlink()
                    removed_empty += 1

        # 5. 동일 음원(해시 중복) 감지
        if tracks_dir.exists():
            hash_map: dict[str, list[str]] = {}
            for f in sorted(tracks_dir.glob("*.mp3")):
                if f.stat().st_size < 10_000:
                    continue
                h = hashlib.md5(f.read_bytes()).hexdigest()
                hash_map.setdefault(h, []).append(f.name)
            for h, files in hash_map.items():
                if len(files) > 1:
                    hash_dupes.append(files)

        # 저장
        state_manager.update(project_id, {"suno_tracks": clean_tracks})

        result = {
            "removed_invalid": removed_invalid,
            "removed_dupes": removed_dupes,
            "removed_orphans": removed_orphans,
            "removed_empty_files": removed_empty,
            "hash_duplicates": hash_dupes,
            "final_count": len(clean_tracks),
        }
        logger.info(f"QA cleanup: {result}")
        return result

    def final_check(self, project_id: str) -> dict:
        """
        생성/재생성 완료 후 최종 검수.
        cleanup → fix_links → verify 순서로 실행.
        """
        cleanup = self.cleanup(project_id)
        fix = self.fix_links(project_id)
        report = self.verify(project_id)

        report["cleanup"] = cleanup
        report["fix"] = fix
        logger.info(
            f"QA final: {report['status']} — "
            f"{report['total_files']}/{report['expected_files']} 파일, "
            f"cleanup {cleanup}, fix {fix['fixed']}개"
        )
        return report


suno_qa_agent = SunoQAAgent()
