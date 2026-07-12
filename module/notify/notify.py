import smtplib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from email.message import EmailMessage
from typing import Final

import yaml

from module.logger import logger

SMTP_TIMEOUT_SECONDS: Final = 15


class _EmailConfigError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class _EmailConfig:
    host: str
    user: str
    password: str = field(repr=False)
    recipients: tuple[str, ...]
    port: int
    use_ssl: bool


def _load_mapping(raw_config: str) -> dict[str, object]:
    if not isinstance(raw_config, str):
        message = "SMTP config must be text"
        raise _EmailConfigError(message)

    config: dict[str, object] = {}
    for document in yaml.safe_load_all(raw_config):
        if document is None:
            continue
        if not isinstance(document, Mapping):
            message = "SMTP config document must be a mapping"
            raise _EmailConfigError(message)
        if any(not isinstance(key, str) for key in document):
            message = "SMTP config keys must be text"
            raise _EmailConfigError(message)
        config.update(document)
    return config


def _required_text(config: Mapping[str, object], key: str, *, strip: bool = True) -> str:
    value = config.get(key)
    if not isinstance(value, str) or not value.strip():
        message = f"SMTP field {key} must be non-empty text"
        raise _EmailConfigError(message)
    return value.strip() if strip else value


def _load_recipients(config: Mapping[str, object], user: str) -> tuple[str, ...]:
    value = config.get("receiver", config.get("to", config.get("To", user)))
    if isinstance(value, str):
        recipients = (value.strip(),)
    elif isinstance(value, Sequence):
        recipients = tuple(item.strip() for item in value if isinstance(item, str) and item.strip())
        if len(recipients) != len(value):
            message = "SMTP recipients must be non-empty text"
            raise _EmailConfigError(message)
    else:
        message = "SMTP recipients must be text or a sequence of text"
        raise _EmailConfigError(message)
    if not recipients or any(not recipient for recipient in recipients):
        message = "SMTP recipients must be non-empty text"
        raise _EmailConfigError(message)
    return recipients


def _load_port(config: Mapping[str, object]) -> int:
    value = config.get("port", 0)
    if value is None:
        return 0
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 65535:
        message = "SMTP port must be an integer from 0 to 65535"
        raise _EmailConfigError(message)
    return value


def _load_ssl(config: Mapping[str, object], port: int) -> bool:
    value = config.get("ssl")
    if value is None:
        return port == smtplib.SMTP_SSL_PORT
    if not isinstance(value, bool):
        message = "SMTP ssl must be a boolean"
        raise _EmailConfigError(message)
    return value


def _load_email_config(raw_config: str) -> _EmailConfig | None:
    config = _load_mapping(raw_config)
    provider = config.get("provider")
    if provider is None:
        return None
    if not isinstance(provider, str) or provider.casefold() != "smtp":
        message = "Only the SMTP notification provider is supported"
        raise _EmailConfigError(message)

    user = _required_text(config, "user")
    port = _load_port(config)
    return _EmailConfig(
        host=_required_text(config, "host"),
        user=user,
        password=_required_text(config, "password", strip=False),
        recipients=_load_recipients(config, user),
        port=port,
        use_ssl=_load_ssl(config, port),
    )


def _build_message(config: _EmailConfig, *, title: str, content: str) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = title
    message["From"] = config.user
    message["To"] = ", ".join(config.recipients)
    message.set_content(content)
    return message


def _send_email(config: _EmailConfig, message: EmailMessage) -> None:
    client_class = smtplib.SMTP_SSL if config.use_ssl else smtplib.SMTP
    with client_class(config.host, config.port, timeout=SMTP_TIMEOUT_SECONDS) as client:
        client.login(user=config.user, password=config.password)
        refused = client.send_message(message)
    if refused:
        raise smtplib.SMTPRecipientsRefused(refused)


def handle_notify(raw_config: str, *, title: str, content: str) -> bool:
    """发送 SMTP 邮件；配置或网络失败时只记录安全摘要。"""
    try:
        config = _load_email_config(raw_config)
        if config is None:
            logger.info("No SMTP provider configured, skip sending")
            return False
        message = _build_message(config, title=title, content=content)
        _send_email(config, message)
    except (yaml.YAMLError, _EmailConfigError) as error:
        logger.error(f"Failed to load SMTP notify config ({type(error).__name__}), skip sending")
        return False
    except Exception as error:  # noqa: BLE001
        # SMTP 异常可能包含服务端返回内容，只记录类型以避免泄露凭据。
        logger.error(f"SMTP notify failed ({type(error).__name__})")
        return False

    logger.info("SMTP notify success")
    return True
