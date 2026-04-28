"""사용자 인증 엔드포인트.

프론트(RegisterForm, PendingApproval, ForgotPasswordModal, App.tsx)가 기대하는 계약:
- POST /api/auth/register         {name, email, password, phone, referral_source} -> {token}
- POST /api/auth/login            {email, password}                                 -> {token}
- GET  /api/auth/status?token=..                                                    -> {name, status}
- POST /api/auth/forgot-password  {email}                                           -> {message}
- POST /api/auth/reset-password   {email, code, new_password}                       -> {}

에러 응답은 JSON {"error": "..."} 형태. 프론트가 data.error 또는 data.message 를 화면에 띄운다.
"""
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr, Field

from core.auth import (
    generate_token,
    send_verification_code,
    user_store,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["인증"])


# ─── 요청 스키마 ──────────────────────────────────────────────────────────────

class RegisterBody(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    email: EmailStr
    password: str = Field(min_length=4, max_length=100)
    phone: str = ""
    referral_source: str = ""


class LoginBody(BaseModel):
    email: EmailStr
    password: str


class ForgotBody(BaseModel):
    email: EmailStr


class ResetBody(BaseModel):
    email: EmailStr
    code: str = Field(min_length=6, max_length=6)
    new_password: str = Field(min_length=4, max_length=100)


# ─── 핸들러 ──────────────────────────────────────────────────────────────────

def _error(status_code: int, message: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"error": message})


@router.post("/register")
def register(body: RegisterBody):
    try:
        user = user_store.create(
            name=body.name,
            email=body.email,
            password=body.password,
            phone=body.phone,
            referral_source=body.referral_source,
        )
    except ValueError as e:
        if str(e) == "email_exists":
            return _error(409, "이미 가입된 이메일입니다.")
        return _error(400, "입력값을 확인해주세요.")
    return {"token": user["token"]}


@router.post("/login")
def login(body: LoginBody):
    user = user_store.get_by_email(body.email)
    if not user or not verify_password(body.password, user["password_hash"]):
        return _error(401, "이메일 또는 비밀번호가 올바르지 않습니다.")

    # 로그인마다 새 토큰 발급 (기존 세션 무효화)
    new_token = generate_token()
    user_store.set_token(user["id"], new_token)
    return {"token": new_token}


@router.get("/status")
def status(token: str = ""):
    """PendingApproval 과 App.tsx 가 주기적으로 폴링.

    실패 시에도 200 을 내면서 status='invalid' 로 알려주는 게 프론트 구현과 맞음
    (프론트가 res.ok 체크 없이 data.status 만 본다).
    """
    user = user_store.get_by_token(token) if token else None
    if not user:
        return {"status": "invalid", "name": None}
    return {"status": user["status"], "name": user["name"]}


@router.post("/forgot-password")
def forgot_password(body: ForgotBody):
    result = user_store.issue_reset_code(body.email)
    if result is None:
        # 존재하지 않는 이메일이라도 같은 응답 (계정 존재 여부 유출 방지)
        return {"message": "인증번호가 발송되었습니다. 이메일을 확인해주세요."}

    user, code = result
    try:
        send_verification_code(user["email"], code)
    except Exception as e:
        return _error(500, f"메일 발송에 실패했습니다: {e}")
    return {"message": "인증번호가 발송되었습니다. 이메일을 확인해주세요."}


@router.post("/reset-password")
def reset_password(body: ResetBody):
    user = user_store.verify_reset_code(body.email, body.code)
    if not user:
        return _error(400, "인증번호가 올바르지 않거나 만료되었습니다.")
    user_store.set_password(user["id"], body.new_password)
    return {"status": "ok"}
