from __future__ import annotations

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.config import Settings, get_settings


def send_email(
    subject: str,
    html_body: str,
    text_body: str | None = None,
    settings: Settings | None = None,
) -> dict:
    settings = settings or get_settings()
    if not settings.email_configured:
        return {
            "ok": False,
            "skipped": True,
            "reason": "이메일 설정이 없습니다. .env의 SMTP/EMAIL_TO를 확인하세요.",
        }

    sender = settings.email_from or settings.smtp_user
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = ", ".join(settings.email_recipients)
    msg.attach(MIMEText(text_body or html_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as server:
        server.starttls()
        server.login(settings.smtp_user, settings.smtp_password)
        server.sendmail(sender, settings.email_recipients, msg.as_string())

    return {
        "ok": True,
        "skipped": False,
        "recipients": settings.email_recipients,
    }
