---
name: image-generator
description: 채널 설정의 카테고리 기반으로 배경/썸네일 이미지를 AI 생성하거나 업로드 이미지를 분류·리사이즈한다.
---

# 이미지 생성 스킬

## 입력
- `channel_concept`: 채널 설정 dict (`bg_category`, `bg_sub_category` 포함)
- `project_id`: 결과 저장 경로용
- `reference_image_path` (선택): 사용자 업로드 참조 이미지 경로

## 출력
- `storage/projects/{project_id}/images/candidate_{1~5}.png` (배경 후보 5장, 1920×1080)
- `storage/projects/{project_id}/images/thumbnail_candidate_{1~5}.png` (썸네일 후보 5장, 1280×720)

## 실행 방법

### 방법 1: 카테고리 기반 AI 생성 (기본)

```python
import asyncio, json
from pathlib import Path
from core.gemini_client import gemini_client
from core.visual_generator import visual_generator

CATEGORIES_PATH = Path("backend/templates/prompts/image_categories.json")

async def run(channel_concept: dict, project_id: str):
    categories = json.loads(CATEGORIES_PATH.read_text(encoding="utf-8"))

    cat_id = channel_concept.get("bg_category", "nature")
    sub_id = channel_concept.get("bg_sub_category", "forest")

    cat = categories["categories"][cat_id]
    sub = next((s for s in cat["sub_categories"] if s["id"] == sub_id), cat["sub_categories"][0])

    template = categories["prompt_template"]
    candidates = []

    for i in range(5):
        # 각 후보마다 다른 modifier 조합
        prompt = template.format(
            base_prompt=sub["base_prompt"],
            mood_modifier=sub["mood_modifiers"][i % len(sub["mood_modifiers"])],
            time_modifier=sub["time_modifiers"][i % len(sub["time_modifiers"])],
            weather_modifier=sub["weather_modifiers"][i % len(sub["weather_modifiers"])],
            color_modifier=sub["color_modifiers"][i % len(sub["color_modifiers"])],
            variation_suffix=sub["variation_suffixes"][i % len(sub["variation_suffixes"])],
        )
        image_bytes_list = await gemini_client.generate_images(prompt, count=1, aspect_ratio="16:9")
        candidates.append(image_bytes_list[0])

    out_dir = Path(f"storage/projects/{project_id}/images")
    out_dir.mkdir(parents=True, exist_ok=True)

    for i, img_bytes in enumerate(candidates, 1):
        # 배경 (1920×1080)
        bg_path = out_dir / f"candidate_{i}.png"
        bg_path.write_bytes(img_bytes)
        await visual_generator.resize_for_youtube(bg_path, bg_path, target="background")

        # 썸네일 (1280×720)
        thumb_path = out_dir / f"thumbnail_candidate_{i}.png"
        await visual_generator.resize_for_youtube(bg_path, thumb_path, target="thumbnail")

    print(f"✅ 이미지 후보 {len(candidates)}장 생성 완료 → {out_dir}")
    return [str(out_dir / f"candidate_{i}.png") for i in range(1, 6)]

asyncio.run(run(channel_concept, project_id))
```

### 방법 2: 참조 이미지 분류 + 리사이즈 (사용자 업로드 시)

```python
import asyncio
from pathlib import Path
from core.visual_generator import visual_generator

async def run(reference_image_path: str, project_id: str):
    ref = Path(reference_image_path)
    out_dir = Path(f"storage/projects/{project_id}/images")

    # 이미지 분류
    classification = await visual_generator.classify_image(ref)
    category = classification.get("category", "background")  # thumbnail | background | additional

    # 리사이즈
    if category == "thumbnail":
        out = out_dir / "thumbnail_candidate_1.png"
        await visual_generator.resize_for_youtube(ref, out, target="thumbnail")
    else:
        out = out_dir / "candidate_1.png"
        await visual_generator.resize_for_youtube(ref, out, target="background")

    print(f"✅ 참조 이미지 처리 완료: {category} → {out}")
    return str(out)

asyncio.run(run(reference_image_path, project_id))
```

## 카테고리 구조 (`image_categories.json`)
```
categories/
  nature → forest, mountain_lake, coastal_sunset, ...
  indoor_cozy → cafe_window, library_shelf, ...
  city_night → neon_street, rooftop_view, ...
  city_day → park_fountain, busy_street, ...
  animation → studio_ghibli_field, cyberpunk_city, ...
  abstract → flowing_particles, geometric_gradient, ...
```

각 sub_category: `base_prompt` + 5종 modifier (`mood/time/weather/color/variation`)

## 주의사항
- `gemini_client.generate_images()` 는 `list[bytes]` 반환
- 배경: 1920×1080 (`target="background"`), 썸네일: 1280×720 (`target="thumbnail"`)
- 후보 5장 생성 후 반드시 사용자가 선택 (`localhost:3000` 이미지 선택 화면)
- 선택된 이미지 경로를 `project_state["images"]["background"]`, `["thumbnail"]`에 저장
