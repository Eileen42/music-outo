---
name: audio-pipeline
description: Suno 생성 MP3 파일들을 병합·정규화하고, 파형 PNG와 가사 SRT를 생성한다.
---

# 오디오 파이프라인 스킬

## 입력
- `project_id`: 트랙 파일 경로용
- 트랙 파일들: `storage/projects/{project_id}/tracks/*.mp3`

## 출력
- `storage/projects/{project_id}/audio/merged.mp3` — 병합 + 정규화 (-14 LUFS)
- `storage/projects/{project_id}/audio/waveform.png` — 파형 이미지 (1920×200, 투명 배경)
- `storage/projects/{project_id}/audio/waveform.json` — 파형 데이터 (200 샘플)
- `storage/projects/{project_id}/audio/{project_id}.srt` — 가사 자막

## 실행 방법

```python
import asyncio, json
from pathlib import Path
from core.audio_pipeline import audio_pipeline
from core.waveform_generator import waveform_generator
from core.lyrics_sync import lyrics_sync

async def run(project_id: str):
    tracks_dir = Path(f"storage/projects/{project_id}/tracks")
    audio_dir = Path(f"storage/projects/{project_id}/audio")
    audio_dir.mkdir(parents=True, exist_ok=True)

    # 1. 트랙 목록 (results.json 순서 유지, 없으면 glob 정렬)
    results_file = tracks_dir / "results.json"
    if results_file.exists():
        results = json.loads(results_file.read_text(encoding="utf-8"))
        track_paths = [
            Path(r["file_path"]) for r in results
            if r["status"] == "completed" and r.get("file_path")
        ]
    else:
        track_paths = sorted(tracks_dir.glob("*.mp3"))

    if not track_paths:
        raise FileNotFoundError(f"트랙 없음: {tracks_dir}")

    # 2. 병합 (크로스페이드 2초)
    merged_raw = audio_dir / "merged_raw.mp3"
    await audio_pipeline.merge_tracks(track_paths, merged_raw, crossfade_ms=2000)
    print(f"✅ 병합 완료: {len(track_paths)}곡 → {merged_raw}")

    # 3. 정규화 (-14 LUFS / -14.0 dBFS)
    merged = audio_dir / "merged.mp3"
    await audio_pipeline.normalize(merged_raw, merged, target_dbfs=-14.0)
    merged_raw.unlink(missing_ok=True)
    print(f"✅ 정규화 완료 → {merged}")

    # 4. 파형 생성
    waveform_png = audio_dir / "waveform.png"
    await waveform_generator.generate_image(
        audio_path=merged,
        output_png=waveform_png,
        width=1920,
        height=200,
        color="#FFFFFF",
        style="bar",
    )
    print(f"✅ 파형 생성 완료 → {waveform_png}")

    # 5. 가사 추출 + SRT 저장 (faster-whisper)
    transcription = await lyrics_sync.transcribe(merged, use_stable=True)
    srt_path = audio_dir / f"{project_id}.srt"
    await lyrics_sync.save_sync_file(transcription, srt_path, format="srt")
    print(f"✅ 가사 동기화 완료 → {srt_path}")

    return {
        "merged": str(merged),
        "waveform_png": str(waveform_png),
        "srt": str(srt_path),
        "duration": transcription.get("duration"),
        "language": transcription.get("language"),
    }

asyncio.run(run(project_id))
```

## 각 모듈 역할

### `audio_pipeline` (`core/audio_pipeline.py`)
- `merge_tracks(paths, output, crossfade_ms=2000)` — pydub crossfade 병합, 320k MP3 출력
- `normalize(input, output, target_dbfs=-14.0)` — 볼륨 정규화
- `convert_to_wav(input, output)` — WAV 변환 (필요 시)
- `trim_silence(input, output)` — 무음 제거

### `waveform_generator` (`core/waveform_generator.py`)
- `generate_image(audio, output_png, width, height, color, style)` — PNG 생성
  - `style`: `"bar"` (기본) | `"line"`
  - RGBA 투명 배경 → CapCut 레이어 오버레이 가능
- `generate_data(audio, output_json)` — 200샘플 peak 데이터 JSON

### `lyrics_sync` (`core/lyrics_sync.py`)
- `transcribe(audio, language=None, use_stable=True)` — faster-whisper + stable-ts
  - `use_stable=True`: 단어 레벨 정확도 향상
  - `language` 미지정 시 자동 감지
- `save_sync_file(transcription, path, format)` — 저장 형식: `json` | `srt` | `lrc`
- 첫 호출 시 모델 지연 로딩 (약 1~2분 소요)

## 주의사항
- faster-whisper 첫 실행 시 모델 다운로드 (base 모델: ~150MB)
- CPU 환경에서 1시간 오디오 → SRT 생성 약 10~20분 소요
- `merged_raw.mp3` 는 정규화 후 자동 삭제
- 파형 스타일 `"circle"` 은 미구현 (bar/line만 사용)
