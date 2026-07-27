"""Email delivery.

An abstract :class:`EmailSender` keeps the service layer decoupled from the
transport. ``console`` logs messages (development), ``smtp`` sends real mail,
and tests substitute an in-memory implementation.
"""

from __future__ import annotations

import smtplib
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from email.message import EmailMessage

from app.core.config import Settings, settings
from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass(slots=True)
class OutgoingEmail:
    to: str
    subject: str
    text_body: str
    html_body: str | None = None


class EmailSender(ABC):
    """Transport-agnostic email interface."""

    @abstractmethod
    def send(self, message: OutgoingEmail) -> None:  # pragma: no cover - interface
        ...


class ConsoleEmailSender(EmailSender):
    """Development backend: writes the message to the application log."""

    def send(self, message: OutgoingEmail) -> None:
        logger.info(
            "email.sent",
            backend="console",
            to=message.to,
            subject=message.subject,
            body=message.text_body,
        )


class SMTPEmailSender(EmailSender):
    """Production backend using SMTP with optional STARTTLS."""

    def __init__(self, config: Settings) -> None:
        self.config = config

    def send(self, message: OutgoingEmail) -> None:
        cfg = self.config
        email = EmailMessage()
        email["From"] = f"{cfg.EMAILS_FROM_NAME} <{cfg.EMAILS_FROM_EMAIL}>"
        email["To"] = message.to
        email["Subject"] = message.subject
        email.set_content(message.text_body)
        if message.html_body:
            email.add_alternative(message.html_body, subtype="html")

        with smtplib.SMTP(cfg.SMTP_HOST, cfg.SMTP_PORT, timeout=10) as client:
            if cfg.SMTP_TLS:
                client.starttls()
            if cfg.SMTP_USER and cfg.SMTP_PASSWORD:
                client.login(cfg.SMTP_USER, cfg.SMTP_PASSWORD)
            client.send_message(email)
        logger.info("email.sent", backend="smtp", to=message.to, subject=message.subject)


@dataclass(slots=True)
class InMemoryEmailSender(EmailSender):
    """Test double that records everything it was asked to send."""

    outbox: list[OutgoingEmail] = field(default_factory=list)

    def send(self, message: OutgoingEmail) -> None:
        self.outbox.append(message)


def get_email_sender(config: Settings | None = None) -> EmailSender:
    """Factory selecting the backend configured by ``EMAIL_BACKEND``."""
    cfg = config or settings
    if cfg.EMAIL_BACKEND == "smtp":
        return SMTPEmailSender(cfg)
    return ConsoleEmailSender()


def build_password_reset_email(*, to: str, token: str, config: Settings) -> OutgoingEmail:
    """Compose the password-reset message, including the frontend deep link."""
    reset_url = f"{str(config.FRONTEND_URL).rstrip('/')}/reset-password?token={token}"
    minutes = config.PASSWORD_RESET_TOKEN_EXPIRE_MINUTES
    text = (
        "You requested a password reset for your BlackBox account.\n\n"
        f"Open this link to choose a new password (valid for {minutes} minutes):\n"
        f"{reset_url}\n\n"
        "If you did not request this, you can safely ignore this email."
    )
    html = (
        "<p>You requested a password reset for your <strong>BlackBox</strong> account.</p>"
        f'<p><a href="{reset_url}">Choose a new password</a> '
        f"(valid for {minutes} minutes).</p>"
        "<p>If you did not request this, you can safely ignore this email.</p>"
    )
    return OutgoingEmail(
        to=to,
        subject="Reset your BlackBox password",
        text_body=text,
        html_body=html,
    )
