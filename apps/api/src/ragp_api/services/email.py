"""Transactional email service.

When RAGP_SMTP_HOST is empty (default) messages are written to the
application log so that local / test environments work without a real SMTP
server.  In production set RAGP_SMTP_HOST together with the other SMTP_*
env vars to deliver real email.
"""

from __future__ import annotations

import logging

from ragp_api.settings import settings

logger = logging.getLogger(__name__)


async def send_password_reset_email(to: str, link: str) -> None:
    """Send a password-reset link to *to*.

    Falls back to a log message when ``settings.smtp_host`` is empty.
    """
    if not settings.smtp_host:
        logger.info("password reset link for %s: %s", to, link)
        return

    try:
        from email.mime.multipart import MIMEMultipart  # noqa: PLC0415
        from email.mime.text import MIMEText  # noqa: PLC0415

        import aiosmtplib  # noqa: PLC0415, E402

        msg = MIMEMultipart("alternative")
        msg["Subject"] = "Сброс пароля"
        msg["From"] = settings.smtp_from or settings.smtp_user
        msg["To"] = to

        text_body = f"Перейдите по ссылке для сброса пароля:\n{link}\n\nСсылка действительна 1 час."
        html_body = (
            f"<p>Перейдите по ссылке для сброса пароля:</p>"
            f'<p><a href="{link}">{link}</a></p>'
            f"<p>Ссылка действительна 1 час.</p>"
        )

        msg.attach(MIMEText(text_body, "plain", "utf-8"))
        msg.attach(MIMEText(html_body, "html", "utf-8"))

        await aiosmtplib.send(
            msg,
            hostname=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_user or None,
            password=settings.smtp_password or None,
            use_tls=settings.smtp_use_tls,
        )
    except Exception:
        logger.exception("Failed to send password reset email to %s", to)
