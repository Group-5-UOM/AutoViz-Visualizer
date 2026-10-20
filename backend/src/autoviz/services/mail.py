"""Outbound mail — always logged; sent over SMTP when configured.

Local demos work without a mailer: the message is written to the observability
log, the same way forgot-password has always exposed its reset URL. Production
sets ``AUTOVIZ_SMTP_HOST`` (and friends) to deliver for real.
"""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from autoviz.core.config import settings

_log = logging.getLogger("autoviz.observability")


def send_mail(*, to: str, subject: str, body: str) -> bool:
    """Deliver ``body`` to ``to``. Returns True if SMTP accepted the message.

    Always logs. When SMTP is not configured, returns False after logging so
    callers can still expose a verify URL under ``AUTOVIZ_EXPOSE_RESET_TOKENS``.
    """
    to = to.strip()
    _log.info("mail to=%s subject=%r\n%s", to, subject, body)

    host = (settings.AUTOVIZ_SMTP_HOST or "").strip()
    if not host:
        return False

    from_addr = (settings.AUTOVIZ_SMTP_FROM or "").strip() or settings.AUTOVIZ_SMTP_USER
    if not from_addr:
        _log.warning("SMTP host set but AUTOVIZ_SMTP_FROM / AUTOVIZ_SMTP_USER missing; not sending")
        return False

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to
    msg.set_content(body)

    port = int(settings.AUTOVIZ_SMTP_PORT or 587)
    user = (settings.AUTOVIZ_SMTP_USER or "").strip()
    password = settings.AUTOVIZ_SMTP_PASSWORD or ""
    use_tls = bool(settings.AUTOVIZ_SMTP_TLS)

    try:
        if use_tls:
            with smtplib.SMTP(host, port, timeout=30) as smtp:
                smtp.starttls()
                if user:
                    smtp.login(user, password)
                smtp.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=30) as smtp:
                if user:
                    smtp.login(user, password)
                smtp.send_message(msg)
        return True
    except Exception:
        _log.exception("SMTP send failed to=%s", to)
        return False


def send_email_change_verification(*, to: str, verify_url: str) -> bool:
    subject = "Confirm your new AutoViz email"
    body = (
        "You asked to change the email on your AutoViz account.\n\n"
        f"Confirm the new address by opening this link:\n{verify_url}\n\n"
        "If you did not request this, you can ignore this message. "
        "The link expires in 24 hours.\n"
    )
    return send_mail(to=to, subject=subject, body=body)
