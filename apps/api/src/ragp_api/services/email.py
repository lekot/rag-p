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


async def _send(*, to: str, subject: str, text_body: str, html_body: str) -> None:
    """Internal SMTP delivery helper.

    Builds a multipart/alternative message and ships it via aiosmtplib.
    Caller must have already short-circuited on ``settings.smtp_host == ""``.
    """
    from email.mime.multipart import MIMEMultipart  # noqa: PLC0415
    from email.mime.text import MIMEText  # noqa: PLC0415

    import aiosmtplib  # noqa: PLC0415

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.smtp_from or settings.smtp_user
    msg["To"] = to
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


async def send_password_reset_email(to: str, link: str) -> None:
    """Send a password-reset link to *to*.

    Falls back to a log message when ``settings.smtp_host`` is empty.
    """
    if not settings.smtp_host:
        logger.info("password reset link for %s: %s", to, link)
        return

    try:
        text_body = f"Перейдите по ссылке для сброса пароля:\n{link}\n\nСсылка действительна 1 час."
        html_body = (
            f"<p>Перейдите по ссылке для сброса пароля:</p>"
            f'<p><a href="{link}">{link}</a></p>'
            f"<p>Ссылка действительна 1 час.</p>"
        )
        await _send(to=to, subject="Сброс пароля", text_body=text_body, html_body=html_body)
    except Exception:
        logger.exception("Failed to send password reset email to %s", to)


async def send_payment_received_email(to: str, amount_rub: float, plan_name: str) -> None:
    """Confirm successful payment for *plan_name* of *amount_rub* RUB."""
    if not settings.smtp_host:
        logger.info(
            "payment received email for %s: %.2f RUB, plan=%s",
            to,
            amount_rub,
            plan_name,
        )
        return

    try:
        amount_str = f"{amount_rub:.2f}"
        text_body = (
            f"Спасибо! Мы получили оплату {amount_str} ₽ за тариф «{plan_name}».\n\n"
            "Подписка активирована, средства зачислены."
        )
        html_body = (
            f"<p>Спасибо! Мы получили оплату <b>{amount_str} ₽</b> "
            f"за тариф «{plan_name}».</p>"
            "<p>Подписка активирована, средства зачислены.</p>"
        )
        await _send(
            to=to,
            subject="Платёж получен",
            text_body=text_body,
            html_body=html_body,
        )
    except Exception:
        logger.exception("Failed to send payment received email to %s", to)


async def send_subscription_activated_email(to: str, plan_name: str, expires_at: str) -> None:
    """Confirm that subscription *plan_name* is active until *expires_at*."""
    if not settings.smtp_host:
        logger.info(
            "subscription activated email for %s: plan=%s, expires_at=%s",
            to,
            plan_name,
            expires_at,
        )
        return

    try:
        text_body = (
            f"Тариф «{plan_name}» активирован.\n"
            f"Действует до: {expires_at}.\n\n"
            "Спасибо, что выбрали нас!"
        )
        html_body = (
            f"<p>Тариф <b>«{plan_name}»</b> активирован.</p>"
            f"<p>Действует до: <b>{expires_at}</b>.</p>"
            "<p>Спасибо, что выбрали нас!</p>"
        )
        await _send(
            to=to,
            subject="Тариф активирован",
            text_body=text_body,
            html_body=html_body,
        )
    except Exception:
        logger.exception("Failed to send subscription activated email to %s", to)


async def send_subscription_expiring_email(
    to: str, plan_name: str, expires_at: str, days_left: int
) -> None:
    """Warn the user that subscription *plan_name* expires in *days_left* days."""
    if not settings.smtp_host:
        logger.info(
            "subscription expiring email for %s: plan=%s, expires_at=%s, days_left=%d",
            to,
            plan_name,
            expires_at,
            days_left,
        )
        return

    try:
        text_body = (
            f"Тариф «{plan_name}» истекает {expires_at} (через {days_left} дн.).\n\n"
            "Чтобы избежать перерыва в работе, продлите подписку в личном кабинете."
        )
        html_body = (
            f"<p>Тариф <b>«{plan_name}»</b> истекает <b>{expires_at}</b> "
            f"(через {days_left} дн.).</p>"
            "<p>Чтобы избежать перерыва в работе, продлите подписку в личном кабинете.</p>"
        )
        await _send(
            to=to,
            subject="Тариф скоро закончится",
            text_body=text_body,
            html_body=html_body,
        )
    except Exception:
        logger.exception("Failed to send subscription expiring email to %s", to)


async def send_subscription_expired_email(to: str, plan_name: str) -> None:
    """Notify the user that subscription *plan_name* has expired."""
    if not settings.smtp_host:
        logger.info(
            "subscription expired email for %s: plan=%s",
            to,
            plan_name,
        )
        return

    try:
        text_body = (
            f"Тариф «{plan_name}» закончился. Доступ к API временно ограничен "
            "(ответ 402 Payment Required).\n\n"
            "Чтобы возобновить работу, продлите подписку в личном кабинете."
        )
        html_body = (
            f"<p>Тариф <b>«{plan_name}»</b> закончился. "
            "Доступ к API временно ограничен (ответ <code>402 Payment Required</code>).</p>"
            "<p>Чтобы возобновить работу, продлите подписку в личном кабинете.</p>"
        )
        await _send(
            to=to,
            subject="Тариф закончился",
            text_body=text_body,
            html_body=html_body,
        )
    except Exception:
        logger.exception("Failed to send subscription expired email to %s", to)
