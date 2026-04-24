"""이메일 발송. 개발 모드(email_mode=console)는 로그에만 출력."""
import logging
import smtplib
from email.message import EmailMessage

from config import settings

logger = logging.getLogger(__name__)


def send_verification_code(email: str, code: str) -> None:
    """비밀번호 재설정 인증번호 발송.

    settings.email_mode == 'console': 로그로만 출력 (개발용).
    settings.email_mode == 'smtp'   : 실제 SMTP 발송.
    """
    mode = (settings.email_mode or "console").strip().lower()

    if mode == "console":
        # ASCII 전용 라인을 함께 찍어 Windows 콘솔/로그 grep 에서도 안정적으로 잡힘
        logger.info("=" * 50)
        logger.info(f"[EMAIL:CONSOLE] to={email} code={code} ttl=10min")
        logger.info("=" * 50)
        return

    if mode == "smtp":
        if not settings.smtp_host or not settings.smtp_user:
            raise RuntimeError("SMTP 설정이 부족합니다 (smtp_host / smtp_user)")

        msg = EmailMessage()
        msg["Subject"] = "[Music Outo] 비밀번호 재설정 인증번호"
        msg["From"] = settings.smtp_from or settings.smtp_user
        msg["To"] = email
        msg.set_content(
            f"아래 6자리 인증번호를 10분 내에 입력해주세요.\n\n"
            f"인증번호: {code}\n\n"
            f"본인이 요청하지 않았다면 이 메일을 무시해주세요."
        )

        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
            server.starttls()
            server.login(settings.smtp_user, settings.smtp_pass)
            server.send_message(msg)
        logger.info(f"[EMAIL:SMTP] sent to {email}")
        return

    raise RuntimeError(f"지원하지 않는 email_mode: {mode}")
