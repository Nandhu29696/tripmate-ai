"""Outgoing email for account verification and password reset.

Messages are sent on a background thread, so a slow mail server never delays
an API response (and response time does not reveal whether an address exists).
Without ``SMTP_HOST`` the message is written to the log; that is a development
convenience and must not be relied on in production.
"""

from __future__ import annotations

import logging
import smtplib
import ssl
import threading
from email.message import EmailMessage

import config

logger = logging.getLogger(__name__)

# Tests replace this to capture messages instead of sending them.
_sink = None


def smtp_configured() -> bool:
    return bool(config.SMTP_HOST)


def _deliver(to: str, subject: str, body: str) -> None:
    if _sink is not None:
        _sink(to, subject, body)
        return

    if not config.SMTP_HOST:
        logger.warning("DEV MAIL (SMTP not configured) to=%s subject=%r\n%s", to, subject, body)
        return

    message = EmailMessage()
    message["From"] = config.SMTP_FROM
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)

    try:
        context = ssl.create_default_context()
        if config.SMTP_PORT == 465:
            server = smtplib.SMTP_SSL(config.SMTP_HOST, config.SMTP_PORT, timeout=20, context=context)
        else:
            server = smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=20)
        with server:
            if config.SMTP_PORT != 465 and config.SMTP_STARTTLS:
                server.starttls(context=context)
            if config.SMTP_USER:
                server.login(config.SMTP_USER, config.SMTP_PASSWORD)
            server.send_message(message)
        logger.info("Email sent to a user (subject=%r)", subject)
    except Exception as exc:  # noqa: BLE001
        # Never raise into the request; the user can retry from the UI.
        logger.error("Email delivery failed: %s: %s", type(exc).__name__, exc)


def send_email(to: str, subject: str, body: str) -> None:
    threading.Thread(target=_deliver, args=(to, subject, body), name="mail", daemon=True).start()
