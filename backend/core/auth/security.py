"""비밀번호 해싱, 토큰/임시비번 생성."""
import secrets
import string

import bcrypt


def hash_password(password: str) -> str:
    """bcrypt 해시 생성. 결과는 utf-8 문자열."""
    if not password:
        raise ValueError("password is empty")
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """bcrypt 검증. 해시가 비어 있거나 잘못된 형식이면 False."""
    if not password or not password_hash:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def generate_token() -> str:
    """로그인 세션 토큰. URL-safe, 충돌 가능성 무시 가능."""
    return secrets.token_urlsafe(32)


def generate_temp_password(length: int = 10) -> str:
    """사람이 읽고 입력하기 쉬운 임시 비밀번호. 헷갈리는 글자(0/O, 1/l) 제외."""
    alphabet = (
        "abcdefghijkmnpqrstuvwxyz"   # l, o 제외
        "ABCDEFGHJKLMNPQRSTUVWXYZ"   # I, O 제외
        "23456789"                    # 0, 1 제외
    )
    return "".join(secrets.choice(alphabet) for _ in range(length))


def generate_verification_code() -> str:
    """비밀번호 찾기용 6자리 숫자."""
    return "".join(secrets.choice(string.digits) for _ in range(6))
