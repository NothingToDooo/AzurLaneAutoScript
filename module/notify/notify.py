import smtplib
import ssl
from email.message import EmailMessage
from typing import Final

from module.notify.configuration import (
    SmtpNotificationConfig,
    SmtpTransport,
)

SMTP_TIMEOUT_SECONDS: Final = 5


def _build_message(
    config: SmtpNotificationConfig,
    *,
    title: str,
    content: str,
    recipient: str | None = None,
) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = title
    message["From"] = config.user
    if recipient is not None and (
        not isinstance(recipient, str)
        or not recipient
        or recipient != recipient.strip()
        or "\r" in recipient
        or "\n" in recipient
    ):
        error_message = "recipient must be trimmed, non-empty, single-line text or None"
        raise ValueError(error_message)
    message["To"] = recipient if recipient is not None else ", ".join(config.recipients)
    message.set_content(content)
    return message


def _send_email(config: SmtpNotificationConfig, message: EmailMessage) -> None:
    if config.transport is SmtpTransport.IMPLICIT_TLS:
        client = smtplib.SMTP_SSL(
            config.host,
            config.port,
            timeout=SMTP_TIMEOUT_SECONDS,
            context=ssl.create_default_context(),
        )
    else:
        client = smtplib.SMTP(config.host, config.port, timeout=SMTP_TIMEOUT_SECONDS)

    with client as connected_client:
        if config.transport is SmtpTransport.STARTTLS:
            connected_client.starttls(context=ssl.create_default_context())
        connected_client.login(user=config.user, password=config.password)
        refused = connected_client.send_message(message)
    if refused:
        raise smtplib.SMTPRecipientsRefused(refused)


class SmtpNotificationSender:
    """严格 SMTP sender；投递异常由同步调用边界记录。"""

    __slots__ = ("_config",)

    def __init__(self, config: SmtpNotificationConfig) -> None:
        if not isinstance(config, SmtpNotificationConfig):
            message = "config must be an SmtpNotificationConfig"
            raise TypeError(message)
        self._config = config

    def send(self, *, recipient: str, title: str, content: str) -> None:
        message = _build_message(
            self._config,
            title=title,
            content=content,
            recipient=recipient,
        )
        _send_email(self._config, message)
