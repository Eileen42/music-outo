"""관리자 엔드포인트 — AdminPage 가 'Authorization: Bearer {admin_secret}' 헤더로 호출."""
from typing import Optional

from fastapi import APIRouter, Depends, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from config import settings
from core.auth import generate_temp_password, user_store
from core.auth.security import hash_password

router = APIRouter(prefix="/api/admin", tags=["관리자"])


# ─── 인증 의존성 ─────────────────────────────────────────────────────────────

def require_admin(authorization: Optional[str] = Header(None)) -> None:
    """Authorization: Bearer <ADMIN_SECRET> 검증."""
    expected = (settings.admin_secret or "").strip()
    if not expected:
        # 운영 시 실수 방지 — 빈 비번은 항상 거부
        raise _forbidden()
    if not authorization or not authorization.lower().startswith("bearer "):
        raise _forbidden()
    token = authorization.split(" ", 1)[1].strip()
    if token != expected:
        raise _forbidden()


def _forbidden():
    from fastapi import HTTPException
    return HTTPException(status_code=403, detail="forbidden")


# ─── 요청 스키마 ─────────────────────────────────────────────────────────────

class StatusPatch(BaseModel):
    status: str = Field(pattern="^(pending|approved|rejected|blocked)$")


class ResetPwBody(BaseModel):
    user_id: int


# ─── 핸들러 ──────────────────────────────────────────────────────────────────

@router.get("/users", dependencies=[Depends(require_admin)])
def list_users(status: str = ""):
    """AdminPage 가 기대하는 {users: [...]} 형태."""
    users = user_store.list(status=status or None)
    return {"users": users}


@router.patch("/users/{user_id}", dependencies=[Depends(require_admin)])
def patch_user(user_id: int, body: StatusPatch):
    user = user_store.update_status(user_id, body.status)
    if not user:
        return JSONResponse(status_code=404, content={"error": "사용자를 찾을 수 없습니다."})
    return {"user": user_store._public_view(user)}


@router.post("/reset-password", dependencies=[Depends(require_admin)])
def admin_reset_password(body: ResetPwBody):
    """관리자가 임시 비번을 강제로 발급. AdminPage 가 이 값을 화면에 한 번 보여준다."""
    user = user_store.get_by_id(body.user_id)
    if not user:
        return JSONResponse(status_code=404, content={"error": "사용자를 찾을 수 없습니다."})

    temp = generate_temp_password()
    # 직접 해싱해서 저장 (set_password 는 reset_code 만 지우고 token 은 유지 — 기존 세션도 만료시키자)
    updated = user_store.set_password(user["id"], temp)
    if updated:
        # 기존 세션 로그아웃
        user_store.clear_token(user["id"])
    return {
        "name": user["name"],
        "email": user["email"],
        "temporary_password": temp,
    }
