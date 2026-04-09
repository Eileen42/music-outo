from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from core.state_manager import state_manager
from core.visual_generator import visual_generator

router = APIRouter(prefix="/api/projects/{project_id}/images", tags=["이미지"])

VALID_CATEGORIES = {"thumbnail", "background", "additional"}


@router.get("", summary="이미지 목록 조회")
async def get_images(project_id: str):
    state = state_manager.require(project_id)
    return state.get("images", {})


@router.post("", summary="이미지 업로드")
async def upload_image(
    project_id: str,
    file: UploadFile = File(...),
    category: str = Form("additional"),
):
    if category not in VALID_CATEGORIES:
        raise HTTPException(400, f"category는 {VALID_CATEGORIES} 중 하나")

    state = state_manager.require(project_id)
    project_dir = state_manager.project_dir(project_id)

    file_bytes = await file.read()
    info = await visual_generator.process_upload(file_bytes, file.filename, project_dir, category)

    images = state.get("images", {"thumbnail": None, "background": None, "additional": []})
    if category in ("thumbnail", "background"):
        images[category] = info["stored_path"]
    else:
        images.setdefault("additional", [])
        images["additional"].append(info["stored_path"])

    state_manager.update(project_id, {"images": images})
    return {"category": category, **info}


@router.post("/analyze", summary="레퍼런스 이미지 분위기 분석 (Gemini Vision)")
async def analyze_image_mood(
    project_id: str,
    file: UploadFile = File(...),
):
    """
    업로드된 이미지를 Gemini Vision으로 분석하여 분위기 JSON 반환.
    분석 결과는 프로젝트 state의 image_mood에 저장됨.
    """
    state_manager.require(project_id)

    file_bytes = await file.read()
    try:
        mood = await visual_generator.analyze_mood(file_bytes, file.filename)
    except Exception as e:
        raise HTTPException(500, f"이미지 분석 실패: {str(e)}")

    # 분석 결과 저장
    state_manager.update(project_id, {"image_mood": mood})
    return mood


@router.post("/generate", summary="AI 이미지 생성 (Imagen 3)")
async def generate_images(project_id: str, body: dict):
    """
    분위기 JSON(mood)을 바탕으로 Imagen 3으로 새 이미지 생성.
    body: {
      "mood": {...},           # analyze 결과 또는 수동 수정본
      "target": "background" | "thumbnail" | "both",
      "count": 1~2,
      "save_as": "background" | "thumbnail" | null  # 자동 저장 카테고리
    }
    """
    state = state_manager.require(project_id)
    project_dir = state_manager.project_dir(project_id)

    mood = body.get("mood")
    if not mood:
        # 저장된 mood 사용
        mood = state.get("image_mood")

    custom_prompt = body.get("custom_prompt", "").strip() if body.get("custom_prompt") else ""

    if not custom_prompt and not mood:
        raise HTTPException(400, "이미지 설명을 입력하거나 먼저 레퍼런스 이미지를 분석하세요.")

    target = body.get("target", "background")
    count = min(int(body.get("count", 1)), 2)  # 무료 한도 절약

    try:
        generated = await visual_generator.generate_from_mood(
            mood=mood,
            target=target,
            count=count,
            project_dir=project_dir,
            custom_prompt=custom_prompt or None,
        )
    except Exception as e:
        raise HTTPException(500, f"이미지 생성 실패: {str(e)}")

    # 에러 없는 결과를 state에 자동 저장
    save_as = body.get("save_as")
    if save_as and save_as in ("thumbnail", "background"):
        images = state.get("images", {"thumbnail": None, "background": None, "additional": []})
        for item in generated:
            if item.get("stored_path") and not item.get("error"):
                images[save_as] = item["stored_path"]
                break
        state_manager.update(project_id, {"images": images})

    return {"generated": generated, "count": len(generated)}


@router.put("/assign", summary="이미지 카테고리 재배정")
async def assign_image(project_id: str, body: dict):
    state = state_manager.require(project_id)
    path = body.get("path")
    category = body.get("category")

    if not path or category not in VALID_CATEGORIES:
        raise HTTPException(400, "path와 유효한 category가 필요합니다")

    images = state.get("images", {"thumbnail": None, "background": None, "additional": []})
    if category in ("thumbnail", "background"):
        images[category] = path
    else:
        images.setdefault("additional", [])
        if path not in images["additional"]:
            images["additional"].append(path)

    state_manager.update(project_id, {"images": images})
    return images


@router.delete("", summary="이미지 제거")
async def remove_image(project_id: str, body: dict):
    state = state_manager.require(project_id)
    path = body.get("path")
    category = body.get("category")

    images = state.get("images", {"thumbnail": None, "background": None, "additional": []})
    if category in ("thumbnail", "background"):
        images[category] = None
    elif category == "additional":
        images["additional"] = [p for p in images.get("additional", []) if p != path]

    state_manager.update(project_id, {"images": images})
    return images
