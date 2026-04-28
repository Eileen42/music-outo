"""사용자 저장소 — storage/users.json 을 원자적으로 읽고 쓴다.

스키마:
{
  "next_id": 1,
  "users": [
    {
      "id": 1,
      "name": "...",
      "email": "...",
      "phone": "" | "...",
      "referral_source": "" | "...",
      "password_hash": "bcrypt...",
      "status": "pending" | "approved" | "rejected" | "blocked",
      "created_at": "2026-04-24T..Z",
      "approved_at": null | "2026-04-24T..Z",
      "token": "..." | null,
      "reset_code": null | { "code": "123456", "expires_at": "..." }
    }
  ]
}
"""
import json
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from config import settings

from .security import generate_token, hash_password, generate_verification_code


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class UserStore:
    """users.json CRUD. Thread-safe (파일 I/O 전역 락)."""

    def __init__(self, path: Optional[Path] = None):
        self._path = path or (settings.storage_dir / "users.json")
        self._lock = threading.RLock()
        # 스토리지 폴더는 있지만 파일이 없을 수 있음
        self._path.parent.mkdir(parents=True, exist_ok=True)

    # ---------- 내부 ----------
    def _read(self) -> dict:
        if not self._path.exists():
            return {"next_id": 1, "users": []}
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            # 파일이 손상된 경우 백업하고 새로 시작
            backup = self._path.with_suffix(".corrupt.json")
            self._path.rename(backup)
            return {"next_id": 1, "users": []}

    def _write(self, data: dict) -> None:
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self._path)

    # ---------- 조회 ----------
    def list(self, status: Optional[str] = None) -> list[dict]:
        with self._lock:
            users = self._read()["users"]
        result = [self._public_view(u) for u in users]
        if status:
            result = [u for u in result if u["status"] == status]
        # 최신 가입이 위에 오도록
        result.sort(key=lambda u: u.get("created_at") or "", reverse=True)
        return result

    def get_by_id(self, user_id: int) -> Optional[dict]:
        with self._lock:
            for u in self._read()["users"]:
                if u["id"] == user_id:
                    return u
        return None

    def get_by_email(self, email: str) -> Optional[dict]:
        email = (email or "").strip().lower()
        if not email:
            return None
        with self._lock:
            for u in self._read()["users"]:
                if u["email"].lower() == email:
                    return u
        return None

    def get_by_token(self, token: str) -> Optional[dict]:
        if not token:
            return None
        with self._lock:
            for u in self._read()["users"]:
                if u.get("token") == token:
                    return u
        return None

    # ---------- 생성 ----------
    def create(
        self,
        name: str,
        email: str,
        password: str,
        phone: str = "",
        referral_source: str = "",
    ) -> dict:
        email = (email or "").strip().lower()
        if self.get_by_email(email):
            raise ValueError("email_exists")
        token = generate_token()
        with self._lock:
            data = self._read()
            user = {
                "id": data["next_id"],
                "name": name.strip(),
                "email": email,
                "phone": (phone or "").strip(),
                "referral_source": (referral_source or "").strip(),
                "password_hash": hash_password(password),
                "status": "pending",
                "created_at": _utcnow_iso(),
                "approved_at": None,
                "token": token,
                "reset_code": None,
            }
            data["users"].append(user)
            data["next_id"] += 1
            self._write(data)
        return user

    # ---------- 수정 ----------
    def update_status(self, user_id: int, status: str) -> Optional[dict]:
        if status not in ("pending", "approved", "rejected", "blocked"):
            raise ValueError(f"invalid status: {status}")
        with self._lock:
            data = self._read()
            for u in data["users"]:
                if u["id"] == user_id:
                    u["status"] = status
                    if status == "approved" and not u.get("approved_at"):
                        u["approved_at"] = _utcnow_iso()
                    self._write(data)
                    return u
        return None

    def set_token(self, user_id: int, token: str) -> Optional[dict]:
        with self._lock:
            data = self._read()
            for u in data["users"]:
                if u["id"] == user_id:
                    u["token"] = token
                    self._write(data)
                    return u
        return None

    def clear_token(self, user_id: int) -> None:
        with self._lock:
            data = self._read()
            for u in data["users"]:
                if u["id"] == user_id:
                    u["token"] = None
                    self._write(data)
                    return

    def set_password(self, user_id: int, new_password: str) -> Optional[dict]:
        with self._lock:
            data = self._read()
            for u in data["users"]:
                if u["id"] == user_id:
                    u["password_hash"] = hash_password(new_password)
                    u["reset_code"] = None
                    self._write(data)
                    return u
        return None

    # ---------- 비번 찾기 ----------
    def issue_reset_code(self, email: str, ttl_minutes: int = 10) -> Optional[tuple[dict, str]]:
        """이메일로 인증번호 발급. 계정이 있으면 (user, code), 없으면 None."""
        user = self.get_by_email(email)
        if not user:
            return None
        code = generate_verification_code()
        expires_at = (
            datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes)
        ).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        with self._lock:
            data = self._read()
            for u in data["users"]:
                if u["id"] == user["id"]:
                    u["reset_code"] = {"code": code, "expires_at": expires_at}
                    self._write(data)
                    user = u
                    break
        return user, code

    def verify_reset_code(self, email: str, code: str) -> Optional[dict]:
        """코드가 맞고 만료되지 않았으면 user 반환. 아니면 None."""
        user = self.get_by_email(email)
        if not user or not user.get("reset_code"):
            return None
        rc = user["reset_code"]
        if rc.get("code") != code:
            return None
        try:
            expires = datetime.fromisoformat(rc["expires_at"].replace("Z", "+00:00"))
            if expires < datetime.now(timezone.utc):
                return None
        except (KeyError, ValueError):
            return None
        return user

    # ---------- 공개 표현 ----------
    @staticmethod
    def _public_view(user: dict) -> dict:
        """AdminPage / PendingApproval 이 기대하는 형태. 민감 필드 제거."""
        return {
            "id": user["id"],
            "name": user["name"],
            "email": user["email"],
            "phone": user.get("phone") or None,
            "referral_source": user.get("referral_source") or None,
            "status": user["status"],
            "created_at": user.get("created_at"),
            "approved_at": user.get("approved_at"),
        }


user_store = UserStore()
