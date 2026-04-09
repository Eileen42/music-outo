"""
QA 자동화 테스트 — 7단계 워크플로우 검증
실행: python qa/test_workflow.py [--base-url http://localhost:8000]
"""
import argparse
import json
import os
import sys
import time
import tempfile
import struct
import wave
from pathlib import Path
from typing import Any

try:
    import requests
except ImportError:
    print("ERROR: requests 미설치. pip install requests")
    sys.exit(1)

BASE_URL = "http://localhost:8000"
PASS = "✅ PASS"
FAIL = "❌ FAIL"
SKIP = "⏭  SKIP"

results: list[dict] = []


def check(name: str, condition: bool, detail: str = "") -> bool:
    status = PASS if condition else FAIL
    results.append({"name": name, "status": status, "detail": detail})
    print(f"  {status} {name}" + (f" — {detail}" if detail else ""))
    return condition


CORS_HEADERS = {"Origin": "http://localhost:3000"}


def req(method: str, path: str, **kwargs) -> requests.Response | None:
    try:
        headers = {**CORS_HEADERS, **kwargs.pop("headers", {})}
        timeout = kwargs.pop("timeout", 30)
        r = requests.request(method, f"{BASE_URL}{path}", timeout=timeout, headers=headers, **kwargs)
        return r
    except requests.ConnectionError:
        return None


def make_test_wav() -> bytes:
    """테스트용 1초짜리 WAV 파일 생성 (ffmpeg 불필요)."""
    sample_rate = 44100
    num_samples = sample_rate  # 1초
    buf = struct.pack("<" + "h" * num_samples, *([0] * num_samples))

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        tmp_path = f.name

    with wave.open(tmp_path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(buf)

    data = Path(tmp_path).read_bytes()
    os.unlink(tmp_path)
    return data


def make_test_png() -> bytes:
    """테스트용 최소 PNG (1×1 흰색 픽셀)."""
    return bytes([
        0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A,  # PNG signature
        0x00, 0x00, 0x00, 0x0D, 0x49, 0x48, 0x44, 0x52,  # IHDR chunk
        0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x01,
        0x08, 0x02, 0x00, 0x00, 0x00, 0x90, 0x77, 0x53,
        0xDE, 0x00, 0x00, 0x00, 0x0C, 0x49, 0x44, 0x41,  # IDAT chunk
        0x54, 0x08, 0xD7, 0x63, 0xF8, 0xFF, 0xFF, 0x3F,
        0x00, 0x05, 0xFE, 0x02, 0xFE, 0xDC, 0xCC, 0x59,
        0xE7, 0x00, 0x00, 0x00, 0x00, 0x49, 0x45, 0x4E,  # IEND chunk
        0x44, 0xAE, 0x42, 0x60, 0x82,
    ])


# ─────────────────────────────────────────────────────────────
# 테스트 단계
# ─────────────────────────────────────────────────────────────

def test_0_server():
    print("\n[0] 서버 연결 확인")
    r = req("GET", "/health")
    ok = check("백엔드 서버 응답", r is not None and r.status_code == 200,
               f"status={r.status_code if r else 'no response'}")
    if not ok:
        print("  → 백엔드 서버를 먼저 시작하세요: start.bat")
        sys.exit(1)

    # CORS 헤더 확인
    headers = r.headers if r else {}
    check("CORS 헤더 존재",
          "access-control-allow-origin" in {k.lower() for k in headers},
          str(dict(headers)))


def test_1_project() -> str:
    print("\n[1] 프로젝트 생성 (Step 1)")
    r = req("POST", "/api/projects", json={
        "name": "QA 테스트 프로젝트",
        "playlist_title": "QA Test Playlist"
    })
    ok = check("프로젝트 생성 POST /api/projects", r is not None and r.status_code == 200)
    if not ok:
        return ""

    data = r.json()
    pid = data.get("id", "")
    check("프로젝트 ID 반환", bool(pid), f"id={pid}")
    check("repeat 필드 존재", "repeat" in data, str(data.get("repeat")))
    check("tracks 빈 배열", data.get("tracks") == [], str(data.get("tracks")))

    # 목록 조회
    r2 = req("GET", "/api/projects")
    check("프로젝트 목록 조회", r2 is not None and r2.status_code == 200)

    # 반복 설정 업데이트
    r3 = req("PATCH", f"/api/projects/{pid}", json={
        "repeat": {"mode": "count", "count": 3, "target_minutes": 60}
    })
    check("반복 설정 PATCH", r3 is not None and r3.status_code == 200)
    if r3 and r3.status_code == 200:
        check("반복 횟수 저장", r3.json().get("repeat", {}).get("count") == 3)

    return pid


def test_2_tracks(pid: str) -> str:
    print("\n[2] 트랙 업로드 (Step 2)")
    if not pid:
        print(f"  {SKIP} 프로젝트 없음")
        return ""

    wav_bytes = make_test_wav()
    r = req("POST", f"/api/projects/{pid}/tracks",
            files={"file": ("test_track.wav", wav_bytes, "audio/wav")},
            data={"title": "QA 테스트 트랙", "lyrics": "첫 번째 줄\n두 번째 줄"})
    ok = check("트랙 업로드 POST (WAV)", r is not None and r.status_code == 200,
               f"status={r.status_code if r else 'no response'}, body={r.text[:100] if r else ''}")

    track_id = ""
    if ok and r:
        data = r.json()
        track_id = data.get("id", "")
        check("트랙 ID 반환", bool(track_id))
        check("재생시간 > 0", data.get("duration", 0) > 0, f"duration={data.get('duration')}")
        check("가사 저장됨", data.get("lyrics") == "첫 번째 줄\n두 번째 줄")

    # 트랙 목록 조회
    r2 = req("GET", f"/api/projects/{pid}/tracks")
    check("트랙 목록 조회", r2 is not None and r2.status_code == 200)

    # 가사 수정
    if track_id:
        r3 = req("PATCH", f"/api/projects/{pid}/tracks/{track_id}",
                 json={"lyrics": "수정된 가사"})
        check("가사 수정 PATCH", r3 is not None and r3.status_code == 200)

    return track_id


def test_3_images(pid: str):
    print("\n[3] 이미지 업로드 (Step 3)")
    if not pid:
        print(f"  {SKIP} 프로젝트 없음")
        return

    png_bytes = make_test_png()
    r = req("POST", f"/api/projects/{pid}/images",
            files={"file": ("thumbnail.png", png_bytes, "image/png")},
            data={"category": "thumbnail"})
    check("썸네일 업로드", r is not None and r.status_code == 200,
          f"status={r.status_code if r else 'no response'}")

    r2 = req("POST", f"/api/projects/{pid}/images",
             files={"file": ("bg.png", png_bytes, "image/png")},
             data={"category": "background"})
    check("배경 이미지 업로드", r2 is not None and r2.status_code == 200)

    # AI 분위기 분석 (Gemini Vision) — API 키 없으면 SKIP
    print("\n[3-AI] 이미지 AI 기능 (Gemini Vision / Imagen 3)")
    r3 = req("POST", f"/api/projects/{pid}/images/analyze",
             files={"file": ("ref.png", png_bytes, "image/png")},
             timeout=60)
    if r3 is None:
        results.append({"name": "AI 분위기 분석 /analyze", "status": SKIP, "detail": "서버 응답 없음"})
        print(f"  {SKIP} AI 분위기 분석 — 서버 응답 없음")
    elif r3.status_code == 500 and ("API" in r3.text or "key" in r3.text.lower() or "gemini" in r3.text.lower()):
        results.append({"name": "AI 분위기 분석 /analyze", "status": SKIP, "detail": "Gemini API 키 미설정"})
        print(f"  {SKIP} AI 분위기 분석 — Gemini API 키 미설정")
    else:
        ok3 = check("AI 분위기 분석 /analyze", r3.status_code == 200,
                    f"status={r3.status_code}, body={r3.text[:120]}")
        if ok3:
            mood = r3.json()
            check("mood 필드 존재", "mood" in mood, str(list(mood.keys())[:5]))
            check("image_prompt 필드 존재", "image_prompt" in mood)
            check("colors 필드 존재", "colors" in mood)

            # AI 이미지 생성 (Imagen 3)
            r4 = req("POST", f"/api/projects/{pid}/images/generate",
                     json={"mood": mood, "target": "background", "count": 1},
                     timeout=120)
            if r4 is None:
                results.append({"name": "AI 이미지 생성 /generate", "status": SKIP, "detail": "서버 응답 없음"})
                print(f"  {SKIP} AI 이미지 생성 — 서버 응답 없음")
            elif r4.status_code == 500 and ("imagen" in r4.text.lower() or "quota" in r4.text.lower() or "API" in r4.text):
                results.append({"name": "AI 이미지 생성 /generate", "status": SKIP, "detail": "Imagen API 한도/키 문제"})
                print(f"  {SKIP} AI 이미지 생성 — Imagen API 한도/키 문제")
            else:
                ok4 = check("AI 이미지 생성 /generate", r4.status_code == 200,
                            f"status={r4.status_code}, body={r4.text[:120]}")
                if ok4:
                    gen = r4.json()
                    check("generated 배열 존재", "generated" in gen)
                    check("count 필드 존재", "count" in gen)
        else:
            # analyze 실패 시 generate도 SKIP
            results.append({"name": "AI 이미지 생성 /generate", "status": SKIP, "detail": "analyze 실패로 건너뜀"})
            print(f"  {SKIP} AI 이미지 생성 — analyze 실패로 건너뜀")


def test_4_metadata(pid: str):
    print("\n[4] 메타데이터 수동 저장 (Step 4)")
    if not pid:
        print(f"  {SKIP} 프로젝트 없음")
        return

    r = req("PUT", f"/api/projects/{pid}/metadata", json={
        "title": "QA 테스트 영상 제목",
        "description": "테스트 설명입니다.",
        "tags": ["QA", "테스트", "자동화"],
        "comment": None
    })
    check("메타데이터 저장 PUT", r is not None and r.status_code == 200,
          f"status={r.status_code if r else 'no response'}")
    if r and r.status_code == 200:
        data = r.json()
        check("제목 저장", data.get("title") == "QA 테스트 영상 제목")
        check("태그 저장", len(data.get("tags", [])) == 3)


def test_5_layers(pid: str):
    print("\n[5] 레이어 설정 (Step 5)")
    if not pid:
        print(f"  {SKIP} 프로젝트 없음")
        return

    r = req("PUT", f"/api/projects/{pid}/layers", json={
        "layers": {
            "background_video": None,
            "waveform_layer": {
                "enabled": True, "style": "bar",
                "color": "#FFFFFF", "opacity": 0.8, "position_y": 0.5
            },
            "text_layers": []
        }
    })
    check("레이어 설정 PUT", r is not None and r.status_code == 200,
          f"status={r.status_code if r else 'no response'}")


def test_6_build(pid: str):
    print("\n[6] 빌드 상태 조회 (Step 6 — 실제 빌드는 ffmpeg 필요로 SKIP)")
    if not pid:
        print(f"  {SKIP} 프로젝트 없음")
        return

    r = req("GET", f"/api/projects/{pid}/build/status")
    check("빌드 상태 조회", r is not None and r.status_code == 200,
          f"status={r.status_code if r else 'no response'}")


def test_7_cleanup(pid: str):
    print("\n[7] 정리 — 테스트 프로젝트 삭제")
    if not pid:
        return
    r = req("DELETE", f"/api/projects/{pid}")
    check("프로젝트 삭제", r is not None and r.status_code == 200)


def print_summary():
    print("\n" + "=" * 50)
    print("QA 결과 요약")
    print("=" * 50)
    passed = sum(1 for r in results if r["status"] == PASS)
    failed = sum(1 for r in results if r["status"] == FAIL)
    skipped = sum(1 for r in results if r["status"] == SKIP)
    total = len(results)

    print(f"  통과: {passed}/{total}  실패: {failed}  건너뜀: {skipped}")
    if failed > 0:
        print("\n실패 항목:")
        for r in results:
            if r["status"] == FAIL:
                print(f"  {FAIL} {r['name']}" + (f" — {r['detail']}" if r['detail'] else ""))
    print("=" * 50)
    return failed == 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="YPA 워크플로우 QA 테스트")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--keep", action="store_true", help="테스트 프로젝트 삭제 안 함")
    args = parser.parse_args()
    BASE_URL = args.base_url

    print("=" * 50)
    print("YouTube Playlist Automator — QA 테스트")
    print(f"대상: {BASE_URL}")
    print("=" * 50)

    test_0_server()
    pid = test_1_project()
    test_2_tracks(pid)
    test_3_images(pid)
    test_4_metadata(pid)
    test_5_layers(pid)
    test_6_build(pid)
    if not args.keep:
        test_7_cleanup(pid)

    ok = print_summary()
    sys.exit(0 if ok else 1)
