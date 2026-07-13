import smtplib
import ssl
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from email.message import EmailMessage
from enum import Enum, auto
from typing import Final

import yaml

from module.logger import logger

SMTP_TIMEOUT_SECONDS: Final = 15
SMTP_STARTTLS_PORT: Final = 587


class _EmailConfigError(ValueError):
    pass


class _EmailTransport(Enum):
    PLAIN = auto()
    IMPLICIT_TLS = auto()
    STARTTLS = auto()


@dataclass(frozen=True, slots=True)
class _EmailConfig:
    host: str
    user: str
    password: str = field(repr=False)
    recipients: tuple[str, ...]
    port: int
    transport: _EmailTransport


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
    """0 由 smtplib 按传输模式解析为 25 或 465，与旧 OnePush 语义一致。"""
    value = config.get("port", 0)
    if value is None:
        return 0
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 65535:
        message = "SMTP port must be an integer from 0 to 65535"
        raise _EmailConfigError(message)
    return value


def _load_optional_bool(config: Mapping[str, object], key: str) -> bool | None:
    value = config.get(key)
    if value is None:
        return None
    if not isinstance(value, bool):
        message = f"SMTP {key} must be a boolean"
        raise _EmailConfigError(message)
    return value


def _load_transport(config: Mapping[str, object], port: int) -> _EmailTransport:
    """把旧 OnePush 的 ssl/starttls 组合归一化为唯一传输模式。"""
    use_ssl = _load_optional_bool(config, "ssl")
    use_starttls = _load_optional_bool(config, "starttls")

    # 旧 ALAS 文档把 587 与 ssl:true 搭配使用；按端口语义恢复为 STARTTLS。
    if port == SMTP_STARTTLS_PORT:
        return _EmailTransport.STARTTLS
    if use_ssl and use_starttls:
        message = "SMTP ssl and starttls cannot both be true"
        raise _EmailConfigError(message)
    if use_starttls:
        return _EmailTransport.STARTTLS
    if use_ssl is None:
        use_ssl = port == smtplib.SMTP_SSL_PORT
    if use_ssl:
        return _EmailTransport.IMPLICIT_TLS
    return _EmailTransport.PLAIN


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
        transport=_load_transport(config, port),
    )


def _build_message(config: _EmailConfig, *, title: str, content: str) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = title
    message["From"] = config.user
    message["To"] = ", ".join(config.recipients)
    message.set_content(content)
    return message


def _send_email(config: _EmailConfig, message: EmailMessage) -> None:
    if config.transport is _EmailTransport.IMPLICIT_TLS:
        client = smtplib.SMTP_SSL(
            config.host,
            config.port,
            timeout=SMTP_TIMEOUT_SECONDS,
            context=ssl.create_default_context(),
        )
    else:
        client = smtplib.SMTP(config.host, config.port, timeout=SMTP_TIMEOUT_SECONDS)

    with client as connected_client:
        if config.transport is _EmailTransport.STARTTLS:
            connected_client.starttls(context=ssl.create_default_context())
        connected_client.login(user=config.user, password=config.password)
        refused = connected_client.send_message(message)
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
