"""
Email service — thin wrapper around smtplib.

Local dev: start MailHog (docker run -p 1025:1025 -p 8025:8025 mailhog/mailhog)
  → outgoing SMTP on :1025, web inbox on http://localhost:8025
Production: set SMTP_HOST/PORT/USER/PASS in env to point at SES, Postmark, etc.

All public send_* functions use keyword-only args so mock.call_args.kwargs["token"]
works in tests without fragile positional-index unpacking.
"""

import hashlib
import secrets
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.config import settings
from app.logger import get_logger

log = get_logger("email")


def generate_token() -> tuple[str, str]:
    """Return (raw_token, token_hash).  Store the hash; send the raw token in the URL."""
    raw = secrets.token_urlsafe(32)
    hashed = hashlib.sha256(raw.encode()).hexdigest()
    return raw, hashed


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _send_email(*, to: str, subject: str, body: str) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.EMAIL_FROM
    msg["To"] = to
    msg.attach(MIMEText(body, "plain"))
    try:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=5) as smtp:
            if settings.SMTP_USER and settings.SMTP_PASS:
                smtp.starttls()
                smtp.login(settings.SMTP_USER, settings.SMTP_PASS)
            smtp.send_message(msg)
        log.info("EMAIL SENT  to=%s  subject=%r", to, subject)
    except Exception as exc:
        # Non-fatal — caller logs the reason.  User can re-request the email.
        log.error("EMAIL FAILED  to=%s  err=%s", to, exc)


def send_verification_email(*, to: str, token: str) -> None:
    url = f"{settings.APP_BASE_URL}/api/auth/verify?token={token}"
    _send_email(
        to=to,
        subject="Verify your CloudNotes email address",
        body=(
            f"Welcome to CloudNotes!\n\n"
            f"Click the link below to verify your email:\n\n"
            f"  {url}\n\n"
            f"This link expires in 24 hours.  If you didn't register, ignore this email."
        ),
    )


def send_password_reset_email(*, to: str, token: str) -> None:
    # The frontend page at this URL collects the new password and POSTs it to
    # POST /api/auth/reset-password {token, new_password} — token never lands in a URL.
    url = f"{settings.APP_BASE_URL}/reset-password?token={token}"
    _send_email(
        to=to,
        subject="Reset your CloudNotes password",
        body=(
            f"You requested a password reset for your CloudNotes account.\n\n"
            f"Click the link below to choose a new password:\n\n"
            f"  {url}\n\n"
            f"This link expires in 1 hour.  If you didn't request this, you can safely ignore this email."
        ),
    )
