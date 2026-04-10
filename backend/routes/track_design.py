"""
곡 설계 & Suno 자동화 라우터.

prefix: /api/tracks
기존 /api/projects/{id}/tracks (오디오 업로드)와 별개.
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path

import aiohttp

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from config import settings
from core.benchmark_analyzer import benchmark_analyzer
from core.channel_profile import channel_profile
from core.state_manager import state_manager
from core.track_designer import track_designer

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tracks", tags=["track-design"])

# 프로젝트별 Suno 자동화 진행 상태 (in-memory)
_suno_tasks: dict[str, dict] = {}


# ──────────────────────────── schemas ────────────────────────────

class DesignRequest(BaseModel):
    channel_id: str
    project_id: str
    benchmark_url: str | None = None
    count: int = 20


class BatchCreateRequest(BaseModel):
    channel_id: str


# ──────────────────────────── routes ────────────────────────────

@router.post("/design", summary="AI 곡 설계")
async def design_tracks(body: DesignRequest):
    """
    벤치마크 URL이 있으면 분석 후 곡 설계.
    없으면 채널 히스토리 최신 벤치마크 사용.
    프로젝트 state의 designed_tracks에 저장.
    """
    # 채널 프로필 로드
    try:
        profile = channel_profile.load(body.channel_id)
    except FileNotFoundError:
        raise HTTPException(404, f"채널을 찾을 수 없습니다: {body.channel_id}")

    # 프로젝트 존재 확인
    state_manager.require(body.project_id)

    # 벤치마크 결정
    benchmark = None
    benchmark_used = "none"

    if body.benchmark_url:
        try:
            benchmark = await benchmark_analyzer.analyze(body.benchmark_url)
            channel_profile.add_benchmark(body.channel_id, benchmark)
            benchmark_used = body.benchmark_url
        except Exception as e:
            logger.warning(f"벤치마크 분석 실패, 히스토리 사용 시도: {e}")

    if benchmark is None:
        benchmark = channel_profile.get_latest_benchmark(body.channel_id)
        if benchmark:
            benchmark_used = benchmark.get("url", "history")

    # 곡 설계 (2단계 — concept + tracks)
    result = await track_designer.design_tracks(
        channel_profile=profile,
        benchmark=benchmark,
        count=body.count,
    )
    concept = result.get("concept", {})
    tracks  = result.get("tracks", [])

    # 프로젝트에 저장 (벤치마크 포함 — 이미지/메타데이터 단계에서 참조)
    state_manager.update(body.project_id, {
        "designed_tracks":   tracks,
        "project_concept":   concept,
        "benchmark_url":     benchmark_used,
        "benchmark_data":    benchmark or {},
    })

    return {
        "tracks":         tracks,
        "concept":        concept,
        "benchmark_used": benchmark_used,
        "total":          len(tracks),
    }


@router.get("/{project_id}", summary="프로젝트 곡 목록 (갤러리)")
async def get_designed_tracks(project_id: str):
    """해당 프로젝트의 설계된 곡 목록 + 컨셉."""
    state = state_manager.require(project_id)
    return {
        "tracks":  state.get("designed_tracks", []),
        "concept": state.get("project_concept", {}),
    }


# ── Suno 관련 라우트 (반드시 /{project_id}/{track_index} 보다 먼저 등록) ────
# FastAPI는 라우트를 위에서부터 순서대로 매칭하므로, 리터럴 경로 세그먼트
# (suno-status, suno-tracks)가 있는 라우트를 파라미터 라우트보다 먼저 등록해야
# "Method Not Allowed 405" 오류를 피할 수 있음.


class RegisterSetRequest(BaseModel):
    slot: int  # 1 or 2


@router.post("/{project_id}/register-suno-set", summary="Suno 세트를 프로젝트 트랙으로 등록")
async def register_suno_set(project_id: str, body: RegisterSetRequest):
    """
    특정 slot(1 or 2)의 suno_tracks를 프로젝트 tracks로 변환·등록.
    Suno가 곡당 2곡 생성 → slot 1 = 세트 A, slot 2 = 세트 B.
    """
    import uuid as _uuid
    from core.audio_pipeline import audio_pipeline

    state = state_manager.require(project_id)
    suno_tracks: list[dict] = state.get("suno_tracks", [])

    slot = body.slot
    if slot not in (1, 2):
        raise HTTPException(400, "slot은 1 또는 2여야 합니다")

    # 해당 slot의 completed 트랙만 필터
    slot_tracks = [t for t in suno_tracks if t.get("slot") == slot and t.get("status") == "completed"]

    # slot 없는 이전 데이터 호환: slot==0이면 모든 completed 트랙을 slot 1로 취급
    if not slot_tracks and slot == 1:
        slot_tracks = [t for t in suno_tracks if t.get("slot", 0) == 0 and t.get("status") == "completed"]

    if not slot_tracks:
        raise HTTPException(400, f"세트 {'A' if slot == 1 else 'B'}에 완료된 트랙이 없습니다")

    # index 순으로 정렬
    slot_tracks.sort(key=lambda t: t.get("index", 0))

    # 중복 감지 (같은 suno_id = 같은 음원)
    import hashlib as _hl
    seen_hashes: dict[str, int] = {}  # md5 → first index
    duplicates: list[dict] = []
    for st in slot_tracks:
        fp = st.get("file_path", "")
        if fp and Path(fp).exists():
            h = _hl.md5(Path(fp).read_bytes()).hexdigest()
            first = seen_hashes.get(h)
            if first is not None:
                duplicates.append({"index": st.get("index"), "duplicate_of": first, "suno_id": st.get("suno_id", "")[:8]})
            else:
                seen_hashes[h] = st.get("index", 0)

    # suno_track → Track 변환 (중복 제외)
    dup_indices = {d["index"] for d in duplicates}
    tracks = []
    for order, st in enumerate([s for s in slot_tracks if s.get("index") not in dup_indices]):
        fp = st.get("file_path", "")
        if not fp or not Path(fp).exists():
            continue

        # MP3 메타데이터 읽기
        try:
            info = audio_pipeline._get_info(Path(fp))
        except Exception:
            info = {"duration": 0, "sample_rate": 48000, "channels": 2}

        track_id = str(_uuid.uuid4())
        tracks.append({
            "id": track_id,
            "title": st.get("title", f"Track {order + 1}"),
            "artist": "",
            "order": order,
            "filename": Path(fp).name,
            "stored_path": fp,
            "duration": info.get("duration", 0),
            "sample_rate": info.get("sample_rate", 48000),
            "channels": info.get("channels", 2),
            "waveform_file": None,
            "lyrics": None,
            "lyrics_sync_file": None,
        })

    set_label = "A" if slot == 1 else "B"
    state_manager.update(project_id, {
        "tracks": tracks,
        "active_suno_set": set_label,
    })

    return {
        "set": set_label,
        "slot": slot,
        "tracks_count": len(tracks),
        "tracks": tracks,
        "duplicates": duplicates,
        "unique_count": len(tracks),
        "skipped_duplicates": len(duplicates),
    }


@router.get("/{project_id}/active-set", summary="현재 활성 세트 조회")
async def get_active_set(project_id: str):
    state = state_manager.require(project_id)
    return {
        "active_set": state.get("active_suno_set", None),
        "tracks_count": len(state.get("tracks", [])),
    }


@router.post("/{project_id}/batch-create", summary="Suno 일괄 생성 시작")
async def batch_create(
    project_id: str,
    body: BatchCreateRequest,
    background_tasks: BackgroundTasks,
):
    """
    설계된 곡 전체를 Suno 자동화에 전달.
    20곡 → 10회 생성 (1회 = 2곡).
    """
    state = state_manager.require(project_id)
    tracks: list = state.get("designed_tracks", [])

    if not tracks:
        raise HTTPException(400, "설계된 곡이 없습니다. /design 먼저 실행하세요.")

    # 진행 중일 때만 중복 방지 (failed/completed는 재시작 허용)
    existing = _suno_tasks.get(project_id, {})
    if existing.get("status") == "running":
        raise HTTPException(409, "이미 Suno 생성이 진행 중입니다. 취소하려면 /batch-reset을 호출하세요.")

    try:
        profile = channel_profile.load(body.channel_id)
    except FileNotFoundError:
        raise HTTPException(404, f"채널을 찾을 수 없습니다: {body.channel_id}")

    total_batches = len(tracks)  # 곡별 개별 생성 (1곡 = 1 Suno 호출 → 2 클립)

    _suno_tasks[project_id] = {
        "status":           "running",
        "total_batches":    total_batches,
        "completed":        0,
        "tracks_collected": 0,
        "errors":           [],
    }

    background_tasks.add_task(
        _run_suno_batch,
        project_id=project_id,
        tracks=tracks,
        has_lyrics=profile.get("has_lyrics", False),
    )

    return {
        "status":        "started",
        "total_batches": total_batches,
        "total_tracks":  len(tracks),
    }


@router.post("/{project_id}/batch-reset", summary="Suno 배치 상태 초기화")
async def batch_reset(project_id: str):
    """stuck 된 running 상태를 강제로 초기화."""
    state_manager.require(project_id)
    existing = _suno_tasks.get(project_id, {})
    old_status = existing.get("status", "idle")
    _suno_tasks.pop(project_id, None)
    return {"reset": True, "previous_status": old_status}


@router.get("/{project_id}/suno-status", summary="Suno 자동화 진행 상태")
async def suno_status(project_id: str):
    """Suno 일괄 생성 진행 상태."""
    task = _suno_tasks.get(project_id)
    if not task:
        return {"status": "idle"}
    return task


@router.get("/{project_id}/suno-tracks", summary="완성된 Suno 트랙 목록")
async def get_suno_tracks(project_id: str):
    """
    Suno 자동화로 생성·다운로드된 트랙 목록 반환.
    file_path를 /storage/... URL로 변환해 프론트엔드에서 바로 재생 가능.
    중복 파일 감지: 같은 음원이 다른 트랙에 할당된 경우 duplicate_of 표시.
    """
    import hashlib as _hl

    state = state_manager.require(project_id)
    tracks: list[dict] = state.get("suno_tracks", [])

    storage_root = settings.storage_dir

    # 1차: file_path → audio_url 변환
    entries = []
    for t in tracks:
        fp = t.get("file_path", "")
        audio_url = ""
        if fp:
            try:
                rel = Path(fp).relative_to(storage_root)
                # 캐시 버스팅: 파일 수정시간을 쿼리 파라미터로
                mtime = int(Path(fp).stat().st_mtime) if Path(fp).exists() else 0
                audio_url = f"/storage/{rel.as_posix()}?t={mtime}"
            except (ValueError, OSError):
                audio_url = fp
        entries.append({**t, "audio_url": audio_url, "slot": t.get("slot", 0)})

    # 2차: 중복 감지 — 같은 index 내에서 slot 1,2가 같은 파일인지만 체크
    from collections import defaultdict as _dd
    idx_hashes: dict[int, list[str]] = _dd(list)
    for entry in entries:
        fp = entry.get("file_path", "")
        if entry.get("status") != "completed" or not fp or not Path(fp).exists():
            continue
        try:
            h = _hl.md5(Path(fp).read_bytes()).hexdigest()
        except Exception:
            continue
        idx = entry.get("index", 0)
        if h in idx_hashes[idx]:
            # 같은 곡의 slot 1,2가 동일 파일
            entry["status"] = "duplicate"
            entry["duplicate_of"] = idx
            entry["audio_url"] = ""
        else:
            idx_hashes[idx].append(h)

    return {"tracks": entries, "total": len(entries)}


@router.post("/{project_id}/suno-tracks/retry-download", summary="실패한 Suno 트랙 재다운로드")
async def retry_download(project_id: str, body: dict):
    """
    suno_id가 있는 download_failed 트랙의 재다운로드 시도.
    body: {"suno_id": str} 또는 {"retry_all": true}
    """
    import aiohttp

    state = state_manager.require(project_id)
    tracks: list[dict] = state.get("suno_tracks", [])
    storage_root = settings.storage_dir

    retry_all = body.get("retry_all", False)
    target_suno_id = body.get("suno_id", "")

    retried = 0
    for t in tracks:
        if t.get("status") != "download_failed":
            continue
        if not t.get("suno_id"):
            continue
        if not retry_all and t.get("suno_id") != target_suno_id:
            continue

        clip_id = t["suno_id"]
        safe_title = t.get("title", "unknown").replace("/", "_").replace("\\", "_")
        slot_suffix = f"_v{t.get('slot', 1)}" if t.get("slot") else ""
        prefix = f"{t.get('index', 0):02d}_{safe_title}{slot_suffix}"
        out_dir = storage_root / "projects" / project_id / "tracks"
        out_dir.mkdir(parents=True, exist_ok=True)
        dest = out_dir / f"{prefix}.mp3"

        urls = [
            f"https://cdn1.suno.ai/{clip_id}.mp3",
            f"https://cdn2.suno.ai/{clip_id}.mp3",
        ]
        downloaded = False
        async with aiohttp.ClientSession() as http:
            for url in urls:
                try:
                    async with http.get(url, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                        if resp.status == 200:
                            content = await resp.read()
                            if len(content) > 1000:  # 유효한 MP3인지 최소 크기 체크
                                dest.write_bytes(content)
                                t["file_path"] = str(dest)
                                t["status"] = "completed"
                                downloaded = True
                                retried += 1
                                logger.info(f"재다운로드 성공: {clip_id[:8]} → {dest.name}")
                                break
                except Exception as e:
                    logger.warning(f"재다운로드 실패 ({url[:40]}): {e}")

    state_manager.update(project_id, {"suno_tracks": tracks})

    # audio_url 변환해서 반환
    result = []
    for t in tracks:
        fp = t.get("file_path", "")
        audio_url = ""
        if fp:
            try:
                rel = Path(fp).relative_to(storage_root)
                audio_url = "/storage/" + rel.as_posix()
            except ValueError:
                audio_url = fp
        entry = {**t, "audio_url": audio_url, "slot": t.get("slot", 0)}
        result.append(entry)

    return {"tracks": result, "retried": retried, "total": len(result)}


@router.post("/{project_id}/suno-tracks/scan-siblings", summary="Suno에서 누락곡 제목 검색·다운로드")
async def scan_siblings(project_id: str, background_tasks: BackgroundTasks):
    """
    모든 designed_tracks 제목으로 Suno 검색 → 곡당 최신 2곡 다운로드.
    기존 해당 index의 suno_tracks는 삭제 후 새 2곡으로 교체.
    slot이 정확히 2개가 아닌 곡만 대상.
    """
    state = state_manager.require(project_id)
    suno_tracks: list[dict] = state.get("suno_tracks", [])
    designed: list[dict] = state.get("designed_tracks", [])

    if not designed:
        raise HTTPException(400, "설계된 곡이 없습니다.")

    # slot 1,2가 모두 있는 index만 완료로 판단
    from collections import Counter
    slot_count = Counter()
    for t in suno_tracks:
        if t.get("status") == "completed" and t.get("slot") in (1, 2):
            slot_count[t.get("index")] += 1

    missing_titles = []
    missing_indices = []
    for dt in designed:
        idx = dt.get("index", 0)
        if slot_count.get(idx, 0) != 2:  # 정확히 2개가 아니면 재검색
            missing_titles.append(dt.get("title", ""))
            missing_indices.append(idx)

    missing_titles = [t for t in missing_titles if t]

    if not missing_titles:
        return {"status": "all_complete", "message": "모든 곡이 2개씩 완료됨"}

    background_tasks.add_task(
        _run_sibling_scan,
        project_id=project_id,
        titles=missing_titles,
        missing_indices=missing_indices,
    )

    return {"status": "started", "missing_count": len(missing_titles), "titles": missing_titles[:5]}


async def _run_sibling_scan(project_id: str, titles: list[str], missing_indices: list[int]) -> None:
    """누락곡 제목으로 Suno 검색 + 다운로드. 기존 해당 index 삭제 후 교체."""
    import subprocess as _sp

    backend_dir = Path(__file__).parent.parent
    project_dir = backend_dir / "storage" / "projects" / project_id / "tracks"
    project_dir.mkdir(parents=True, exist_ok=True)

    script = f"""
import asyncio, sys, json
sys.path.insert(0, r'{backend_dir}')
asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

async def main():
    from browser.suno_automation import SunoAutomation
    from core.state_manager import state_manager

    titles = {json.dumps(titles, ensure_ascii=False)}
    missing_indices = {json.dumps(missing_indices)}

    # title → index 매핑
    title_to_index = {{}}
    for dt in designed:
        title_to_index[dt.get('title', '')] = dt.get('index', 0)

    async with SunoAutomation(max_concurrent=1, headless=False) as suno:
        results = await suno.find_siblings_by_search(
            titles=titles,
            known_ids=set(),
            output_dir=r'{project_dir}',
            title_to_index=title_to_index,
        )

    if not results:
        print("검색 결과 없음", file=sys.stderr)
        return

    state = state_manager.get('{project_id}') or {{}}
    old_tracks = state.get('suno_tracks') or []
    designed = state.get('designed_tracks') or []

    # 제목 → index 매핑
    title_to_index = {{}}
    for dt in designed:
        title_to_index[dt.get('title', '')] = dt.get('index', 0)

    # 검색된 index의 기존 항목 삭제
    indices_to_replace = set(missing_indices)
    old_tracks = [t for t in old_tracks if t.get('index') not in indices_to_replace]

    # 새 결과 추가
    for r in results:
        idx = title_to_index.get(r.get('title', ''), 0)
        old_tracks.append({{
            'index': idx,
            'title': r.get('title', ''),
            'suno_id': r['suno_id'],
            'file_path': r.get('file_path', ''),
            'status': r.get('status', 'failed'),
            'slot': r.get('slot', 1),
        }})

    old_tracks.sort(key=lambda t: (t.get('index', 0), t.get('slot', 0)))
    state_manager.update('{project_id}', {{'suno_tracks': old_tracks}})
    print(f"{{len(results)}}곡 다운로드, {{len(indices_to_replace)}}곡 교체", file=sys.stderr)

asyncio.run(main())
"""
    try:
        proc = _sp.Popen(
            [sys.executable, "-c", script],
            stdout=_sp.PIPE, stderr=_sp.PIPE,
        )
        logger.info(f"누락곡 검색 시작: PID={proc.pid}, {len(titles)}곡")

        while proc.poll() is None:
            await asyncio.sleep(2)

        stderr = proc.stderr.read().decode("utf-8", errors="replace") if proc.stderr else ""
        logger.info(f"누락곡 검색 완료: {stderr.strip()}")

    except Exception as e:
        logger.error(f"누락곡 검색 실패: {e}")


@router.put("/{project_id}/suno-tracks/reorder", summary="Suno 트랙 순서 변경")
async def reorder_suno_tracks(project_id: str, body: dict):
    """body: {"order": [0, 2, 1, ...]}  — 새 순서의 인덱스 배열"""
    state = state_manager.require(project_id)
    tracks: list[dict] = state.get("suno_tracks", [])
    order: list[int] = body.get("order", [])

    if len(order) != len(tracks):
        raise HTTPException(400, f"order 길이({len(order)}) ≠ 트랙 수({len(tracks)})")
    if set(order) != set(range(len(tracks))):
        raise HTTPException(400, "order에 중복 또는 범위 초과 인덱스가 있습니다.")

    reordered = [tracks[i] for i in order]
    state_manager.update(project_id, {"suno_tracks": reordered})
    return {"tracks": reordered}


@router.delete("/{project_id}/suno-tracks/{track_index}", summary="Suno 트랙 삭제")
async def delete_suno_track(project_id: str, track_index: int):
    """인덱스 기반 Suno 트랙 삭제 (파일은 유지, 목록에서만 제거)."""
    state = state_manager.require(project_id)
    tracks: list[dict] = state.get("suno_tracks", [])

    if track_index < 0 or track_index >= len(tracks):
        raise HTTPException(404, f"트랙 인덱스 범위 초과: {track_index}")

    removed = tracks.pop(track_index)
    state_manager.update(project_id, {"suno_tracks": tracks})
    return {"deleted": removed}


@router.post("/{project_id}/regenerate/{track_index}", summary="개별 곡 재생성")
async def regenerate_track(project_id: str, track_index: int, body: dict):
    """
    갤러리에서 개별 곡 재생성 요청.
    body: {"channel_id": str}
    """
    channel_id = body.get("channel_id", "")
    if not channel_id:
        raise HTTPException(400, "channel_id가 필요합니다")

    try:
        profile = channel_profile.load(channel_id)
    except FileNotFoundError:
        raise HTTPException(404, f"채널을 찾을 수 없습니다: {channel_id}")

    state = state_manager.require(project_id)
    tracks: list  = state.get("designed_tracks", [])
    concept: dict = state.get("project_concept", {})

    if track_index < 0 or track_index >= len(tracks):
        raise HTTPException(404, f"트랙 인덱스 범위 초과: {track_index}")

    new_track = await track_designer.regenerate_single(
        track=tracks[track_index],
        channel_profile=profile,
        concept=concept or None,
    )
    tracks[track_index] = new_track
    state_manager.update(project_id, {"designed_tracks": tracks})
    return new_track


# ── 개별 곡 수정/삭제 (파라미터 라우트 — 반드시 마지막에) ──────────────────

@router.put("/{project_id}/{track_index}", summary="개별 곡 수정")
async def update_track(project_id: str, track_index: int, body: dict):
    """인덱스 기반 곡 수정."""
    state = state_manager.require(project_id)
    tracks: list = state.get("designed_tracks", [])

    if track_index < 0 or track_index >= len(tracks):
        raise HTTPException(404, f"트랙 인덱스 범위 초과: {track_index}")

    allowed = {"title", "title_ko", "suno_prompt", "lyrics", "mood", "duration_hint", "category"}
    for k, v in body.items():
        if k in allowed:
            tracks[track_index][k] = v

    state_manager.update(project_id, {"designed_tracks": tracks})
    return tracks[track_index]


@router.delete("/{project_id}/{track_index}", summary="곡 삭제")
async def delete_track(project_id: str, track_index: int):
    """인덱스 기반 곡 삭제 + suno_tracks 동기화."""
    state = state_manager.require(project_id)
    tracks: list = state.get("designed_tracks", [])

    if track_index < 0 or track_index >= len(tracks):
        raise HTTPException(404, f"트랙 인덱스 범위 초과: {track_index}")

    removed = tracks.pop(track_index)
    removed_title = removed.get("title", "")

    # index 재정렬
    for i, t in enumerate(tracks):
        t["index"] = i + 1

    # suno_tracks도 동기화: 삭제된 곡 제거 + index 재매핑 (title 기준)
    suno_tracks: list = state.get("suno_tracks", [])
    title_to_new_idx = {t["title"]: t["index"] for t in tracks}
    new_suno = []
    for st in suno_tracks:
        new_idx = title_to_new_idx.get(st.get("title"))
        if new_idx is None:
            continue  # 삭제된 곡
        st["index"] = new_idx
        new_suno.append(st)
    new_suno.sort(key=lambda t: (t.get("index", 0), t.get("slot", 0)))

    state_manager.update(project_id, {"designed_tracks": tracks, "suno_tracks": new_suno})
    return {"deleted": removed}


# ──────────────────────────── background ────────────────────────────

async def _run_suno_batch(
    project_id: str,
    tracks: list[dict],
    has_lyrics: bool,
) -> None:
    """
    Suno 일괄 생성 백그라운드 작업.

    Windows uvicorn의 SelectorEventLoop에서는 Playwright subprocess를 실행할 수 없으므로
    _suno_batch_runner.py 를 별도 Python 프로세스로 띄워 완전히 격리한다.
    진행 상황은 _suno_progress.json 을 폴링해 task dict에 반영한다.
    """
    task = _suno_tasks.get(project_id)
    if not task:
        return

    import subprocess as _sp
    backend_dir  = Path(__file__).parent.parent  # routes/ → backend/
    progress_path = backend_dir / "storage" / "projects" / project_id / "_suno_progress.json"
    runner        = backend_dir / "_suno_batch_runner.py"

    try:
        proc = _sp.Popen(
            [sys.executable, str(runner), project_id],
            stdout=_sp.PIPE, stderr=_sp.PIPE,
        )
        logger.info(f"Suno runner 프로세스 시작: PID={proc.pid}, project={project_id}")

        # progress.json 폴링 (2초 간격)
        while proc.poll() is None:
            await asyncio.sleep(2)
            if progress_path.exists():
                try:
                    data = json.loads(progress_path.read_text(encoding="utf-8"))
                    task["completed_batches"] = data.get("completed_batches", 0)
                    task["tracks_collected"]  = data.get("tracks_collected", 0)
                    if data.get("errors"):
                        task["errors"] = data["errors"]
                except Exception:
                    pass

        # 프로세스 종료 후 최종 결과 읽기
        if progress_path.exists():
            final = json.loads(progress_path.read_text(encoding="utf-8"))
            task.update({
                "status":           final.get("status", "failed"),
                "completed_batches": final.get("completed_batches", 0),
                "tracks_collected": final.get("tracks_collected", 0),
                "errors":           final.get("errors", []),
                "traceback":        final.get("traceback", ""),
            })
            if final.get("results"):
                task["results"] = final["results"]
        else:
            rc = proc.returncode
            stderr = proc.stderr.read().decode("utf-8", errors="replace") if proc.stderr else ""
            task["status"] = "failed"
            task["errors"].append(f"runner 종료 (code={rc}): {stderr[-500:]}")

        logger.info(f"Suno 배치 완료: {project_id}, status={task['status']}, {task['tracks_collected']}곡")

    except Exception as e:
        import traceback as _tb
        task["status"] = "failed"
        task["errors"].append(f"[{type(e).__name__}] {e}")
        task["traceback"] = _tb.format_exc()
        logger.error(f"Suno 배치 실패: {e}")
