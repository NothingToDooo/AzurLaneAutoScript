from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from email.errors import HeaderParseError
from email.headerregistry import Address
from email.utils import getaddresses
from enum import StrEnum
from typing import Final

import yaml

SMTP_IMPLICIT_TLS_PORT: Final = 465
SMTP_STARTTLS_PORT: Final = 587

_PROVIDER_FIELD: Final = "provider"
_RECIPIENT_FIELDS: Final = ("receiver", "to", "To")
_SMTP_FIELDS: Final = frozenset(
    {
        _PROVIDER_FIELD,
        "host",
        "user",
        "password",
        *_RECIPIENT_FIELDS,
        "port",
        "ssl",
        "starttls",
    }
)


class NotificationConfigError(ValueError):
    pass


class SmtpTransport(StrEnum):
    IMPLICIT_TLS = "implicit_tls"
    STARTTLS = "starttls"


@dataclass(frozen=True, slots=True)
class DisabledNotificationConfig:
    pass


@dataclass(frozen=True, slots=True)
class SmtpNotificationConfig:
    host: str
    user: str
    password: str = field(repr=False)
    recipients: tuple[str, ...]
    port: int
    transport: SmtpTransport

    def __post_init__(self) -> None:
        _validate_canonical_text(self.host, field_name="host", allow_spaces=False)
        _validate_canonical_mailbox(self.user, field_name="user")
        if not isinstance(self.password, str):
            message = "SMTP password must be text"
            raise TypeError(message)
        if not self.password.strip():
            message = "SMTP password must not be empty"
            raise ValueError(message)
        if not isinstance(self.recipients, tuple):
            message = "SMTP recipients must be a tuple"
            raise TypeError(message)
        if not self.recipients:
            message = "SMTP recipients must not be empty"
            raise ValueError(message)
        for recipient in self.recipients:
            _validate_canonical_mailbox(recipient, field_name="recipient")
        if len(set(self.recipients)) != len(self.recipients):
            message = "SMTP recipients must not contain duplicates"
            raise ValueError(message)
        if isinstance(self.port, bool) or not isinstance(self.port, int):
            message = "SMTP port must be an integer"
            raise TypeError(message)
        if not 0 <= self.port <= 65535:
            message = "SMTP port must be from 0 to 65535"
            raise ValueError(message)
        if not isinstance(self.transport, SmtpTransport):
            message = "SMTP transport must be a SmtpTransport"
            raise TypeError(message)


type NotificationConfig = DisabledNotificationConfig | SmtpNotificationConfig


def _validate_canonical_text(value: str, *, field_name: str, allow_spaces: bool = True) -> None:
    if not isinstance(value, str):
        message = f"SMTP {field_name} must be text"
        raise TypeError(message)
    if not value or value != value.strip():
        message = f"SMTP {field_name} must be trimmed and non-empty"
        raise ValueError(message)
    if "\r" in value or "\n" in value:
        message = f"SMTP {field_name} must be a single line"
        raise ValueError(message)
    if not allow_spaces and any(character.isspace() for character in value):
        message = f"SMTP {field_name} must not contain whitespace"
        raise ValueError(message)


def _load_mailboxes(values: Sequence[str], *, field_name: str) -> tuple[str, ...]:
    for value in values:
        _validate_canonical_text(value, field_name=field_name)
    parsed = getaddresses(values, strict=True)
    if not parsed or any(not mailbox for _display_name, mailbox in parsed):
        message = f"SMTP {field_name} must contain valid mailbox addresses"
        raise NotificationConfigError(message)

    canonical: list[str] = []
    for _display_name, mailbox in parsed:
        try:
            addr_spec = Address(addr_spec=mailbox).addr_spec
        except HeaderParseError, ValueError:
            message = f"SMTP {field_name} must contain valid mailbox addresses"
            raise NotificationConfigError(message) from None
        canonical.append(addr_spec)
    return tuple(dict.fromkeys(canonical))


def _validate_canonical_mailbox(value: str, *, field_name: str) -> None:
    mailboxes = _load_mailboxes((value,), field_name=field_name)
    if mailboxes != (value,):
        message = f"SMTP {field_name} must be one canonical mailbox address"
        raise ValueError(message)


def _load_mapping(raw_config: str) -> dict[str, object]:
    if not isinstance(raw_config, str):
        message = "SMTP config must be text"
        raise TypeError(message)
    try:
        documents = tuple(document for document in yaml.safe_load_all(raw_config) if document is not None)
    except yaml.YAMLError:
        message = "SMTP config must be valid YAML"
        raise NotificationConfigError(message) from None
    if len(documents) != 1:
        message = "SMTP config must contain exactly one mapping document"
        raise NotificationConfigError(message)
    document = documents[0]
    if not isinstance(document, Mapping):
        message = "SMTP config document must be a mapping"
        raise NotificationConfigError(message)
    if any(not isinstance(key, str) for key in document):
        message = "SMTP config keys must be text"
        raise NotificationConfigError(message)
    return dict(document)


def _required_text(config: Mapping[str, object], key: str, *, strip: bool = True) -> str:
    value = config.get(key)
    if not isinstance(value, str) or not value.strip():
        message = f"SMTP field {key} must be non-empty text"
        raise NotificationConfigError(message)
    return value.strip() if strip else value


def _load_user(config: Mapping[str, object]) -> str:
    raw_user = _required_text(config, "user")
    users = _load_mailboxes((raw_user,), field_name="user")
    if len(users) != 1:
        message = "SMTP user must contain exactly one mailbox address"
        raise NotificationConfigError(message)
    return users[0]


def _load_recipients(config: Mapping[str, object], user: str) -> tuple[str, ...]:
    present_fields = tuple(field_name for field_name in _RECIPIENT_FIELDS if field_name in config)
    if len(present_fields) > 1:
        message = "SMTP config must use only one recipient field"
        raise NotificationConfigError(message)
    value = user if not present_fields else config[present_fields[0]]
    if isinstance(value, str):
        raw_recipients = (value.strip(),)
    elif isinstance(value, Sequence):
        raw_recipients = tuple(item.strip() for item in value if isinstance(item, str) and item.strip())
        if len(raw_recipients) != len(value):
            message = "SMTP recipients must be non-empty text"
            raise NotificationConfigError(message)
    else:
        message = "SMTP recipients must be text or a sequence of text"
        raise NotificationConfigError(message)
    if not raw_recipients:
        message = "SMTP recipients must be non-empty text"
        raise NotificationConfigError(message)
    return _load_mailboxes(raw_recipients, field_name="recipients")


def _load_port(config: Mapping[str, object]) -> int:
    """0 由 smtplib 按传输模式解析为 25 或 465，与旧 OnePush 语义一致。"""
    value = config.get("port", 0)
    if value is None:
        return 0
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 65535:
        message = "SMTP port must be an integer from 0 to 65535"
        raise NotificationConfigError(message)
    return value


def _load_optional_bool(config: Mapping[str, object], key: str) -> bool | None:
    value = config.get(key)
    if value is None:
        return None
    if not isinstance(value, bool):
        message = f"SMTP {key} must be a boolean"
        raise NotificationConfigError(message)
    return value


def _load_transport(config: Mapping[str, object], port: int) -> SmtpTransport:
    """把旧 OnePush 的 ssl/starttls 组合归一化为唯一传输模式。"""
    use_ssl = _load_optional_bool(config, "ssl")
    use_starttls = _load_optional_bool(config, "starttls")

    if use_ssl and use_starttls:
        message = "SMTP ssl and starttls cannot both be true"
        raise NotificationConfigError(message)
    # 旧 ALAS 文档把 587 与 ssl:true 搭配使用；按端口语义恢复为 STARTTLS。
    if port == SMTP_STARTTLS_PORT:
        if use_starttls is False:
            message = "authenticated SMTP requires TLS"
            raise NotificationConfigError(message)
        return SmtpTransport.STARTTLS
    if use_starttls:
        return SmtpTransport.STARTTLS
    if use_ssl:
        return SmtpTransport.IMPLICIT_TLS
    if port == SMTP_IMPLICIT_TLS_PORT:
        if use_ssl is False:
            message = "SMTP port 465 requires implicit TLS"
            raise NotificationConfigError(message)
        return SmtpTransport.IMPLICIT_TLS
    if use_starttls is False:
        message = "authenticated SMTP requires TLS"
        raise NotificationConfigError(message)
    # 未显式启用隐式 TLS 时默认 STARTTLS；握手失败必须发生在 login 之前。
    return SmtpTransport.STARTTLS


def parse_notification_config(raw_config: str) -> NotificationConfig:
    config = _load_mapping(raw_config)
    # 历史版本把 OnePushConfig: "{}" 作为禁用 sentinel；集中在解码边界迁移。
    if not config:
        return DisabledNotificationConfig()
    if _PROVIDER_FIELD not in config:
        message = "notification provider is required; use provider: null to disable notifications"
        raise NotificationConfigError(message)

    provider = config[_PROVIDER_FIELD]
    if provider is None:
        if set(config) != {_PROVIDER_FIELD}:
            message = "disabled notification config must contain only provider: null"
            raise NotificationConfigError(message)
        return DisabledNotificationConfig()
    if not isinstance(provider, str) or provider != provider.strip() or provider.casefold() != "smtp":
        message = "only the SMTP notification provider is supported"
        raise NotificationConfigError(message)
    if not set(config).issubset(_SMTP_FIELDS):
        message = "SMTP config contains unsupported fields"
        raise NotificationConfigError(message)

    user = _load_user(config)
    port = _load_port(config)
    try:
        return SmtpNotificationConfig(
            host=_required_text(config, "host"),
            user=user,
            password=_required_text(config, "password", strip=False),
            recipients=_load_recipients(config, user),
            port=port,
            transport=_load_transport(config, port),
        )
    except (TypeError, ValueError) as error:
        raise NotificationConfigError(str(error)) from None
