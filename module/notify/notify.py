import smtplib
import ssl
from email.message import EmailMessage
from hashlib import sha256
from typing import Final

from module.logger import logger
from module.notify.configuration import (
    DisabledNotificationConfig,
    NotificationConfigError,
    SmtpNotificationConfig,
    SmtpTransport,
    parse_notification_config,
)

SMTP_TIMEOUT_SECONDS: Final = 15


def _build_message(
    config: SmtpNotificationConfig,
    *,
    title: str,
    content: str,
    idempotency_key: str | None = None,
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
    if idempotency_key is not None:
        if not isinstance(idempotency_key, str) or not idempotency_key:
            error_message = "idempotency_key must be a non-empty string or None"
            raise ValueError(error_message)
        digest = sha256(idempotency_key.encode()).hexdigest()
        message["Message-ID"] = f"<alas-{digest}@alas.local>"
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
    """严格 SMTP sender；投递异常交给 outbox 决定是否重试。"""

    __slots__ = ("_config",)

    def __init__(self, config: SmtpNotificationConfig) -> None:
        if not isinstance(config, SmtpNotificationConfig):
            message = "config must be an SmtpNotificationConfig"
            raise TypeError(message)
        self._config = config

    def send(self, *, recipient: str, title: str, content: str, idempotency_key: str) -> None:
        message = _build_message(
            self._config,
            title=title,
            content=content,
            idempotency_key=idempotency_key,
            recipient=recipient,
        )
        _send_email(self._config, message)


def handle_notify(raw_config: str, *, title: str, content: str) -> bool:
    """发送 SMTP 邮件；配置或网络失败时记录完整异常并返回失败。"""
    try:
        config = parse_notification_config(raw_config)
        if isinstance(config, DisabledNotificationConfig):
            logger.info("No SMTP provider configured, skip sending")
            return False
        message = _build_message(config, title=title, content=content)
        _send_email(config, message)
    except NotificationConfigError as error:
        logger.exception(error)
        return False
    except Exception as error:  # noqa: BLE001
        logger.exception(error)
        return False

    logger.info("SMTP notify success")
    return True
