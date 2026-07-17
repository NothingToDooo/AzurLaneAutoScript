from dataclasses import dataclass
from email.errors import HeaderParseError
from email.headerregistry import Address
from email.utils import getaddresses
from enum import StrEnum


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
    password: str
    recipients: tuple[str, ...]
    port: int
    transport: SmtpTransport

    def __post_init__(self) -> None:
        _require_text(self.host, field_name="host", allow_whitespace=False)
        _require_mailbox(self.user, field_name="user")
        if not isinstance(self.password, str) or not self.password:
            message = "SMTP password must be non-empty text"
            raise ValueError(message)
        if not isinstance(self.recipients, tuple) or not self.recipients:
            message = "SMTP recipients must be a non-empty tuple"
            raise ValueError(message)
        for recipient in self.recipients:
            _require_mailbox(recipient, field_name="recipient")
        if len(set(self.recipients)) != len(self.recipients):
            message = "SMTP recipients must not contain duplicates"
            raise ValueError(message)
        if isinstance(self.port, bool) or not isinstance(self.port, int) or not 1 <= self.port <= 65535:
            message = "SMTP port must be an integer from 1 to 65535"
            raise ValueError(message)
        if not isinstance(self.transport, SmtpTransport):
            message = "SMTP transport must be a SmtpTransport"
            raise TypeError(message)


type NotificationConfig = DisabledNotificationConfig | SmtpNotificationConfig


def _require_text(value: str, *, field_name: str, allow_whitespace: bool = True) -> None:
    if not isinstance(value, str) or not value or value != value.strip():
        message = f"SMTP {field_name} must be trimmed and non-empty"
        raise ValueError(message)
    if "\r" in value or "\n" in value:
        message = f"SMTP {field_name} must be a single line"
        raise ValueError(message)
    if not allow_whitespace and any(character.isspace() for character in value):
        message = f"SMTP {field_name} must not contain whitespace"
        raise ValueError(message)


def _mailboxes(value: str, *, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, str):
        message = f"SMTP {field_name} must be text"
        raise NotificationConfigError(message)
    candidates = tuple(line.strip() for line in value.splitlines() if line.strip())
    if not candidates:
        message = f"SMTP {field_name} must not be empty"
        raise NotificationConfigError(message)
    parsed = getaddresses(candidates, strict=True)
    if not parsed or any(not mailbox for _display_name, mailbox in parsed):
        message = f"SMTP {field_name} must contain valid mailbox addresses"
        raise NotificationConfigError(message)

    result: list[str] = []
    for _display_name, mailbox in parsed:
        try:
            canonical = Address(addr_spec=mailbox).addr_spec
        except (HeaderParseError, ValueError) as error:
            message = f"SMTP {field_name} must contain valid mailbox addresses: {error}"
            raise NotificationConfigError(message) from error
        if canonical not in result:
            result.append(canonical)
    return tuple(result)


def _require_mailbox(value: str, *, field_name: str) -> None:
    try:
        parsed = _mailboxes(value, field_name=field_name)
    except NotificationConfigError as error:
        raise ValueError(str(error)) from error
    if parsed != (value,):
        message = f"SMTP {field_name} must be one canonical mailbox address"
        raise ValueError(message)


def _single_mailbox(value: str, *, field_name: str) -> str:
    mailboxes = _mailboxes(value, field_name=field_name)
    if len(mailboxes) != 1:
        message = f"SMTP {field_name} must contain exactly one mailbox address"
        raise NotificationConfigError(message)
    return mailboxes[0]


def build_notification_config(  # ruff:ignore[too-many-arguments] - 这些字段就是 alas.json 的完整 SMTP 契约。
    *,
    enabled: bool,
    host: str,
    port: int,
    transport: str,
    user: str,
    password: str,
    recipients: str,
) -> NotificationConfig:
    """把 alas.json 中的显式 SMTP 字段编译为进程配置。"""
    if type(enabled) is not bool:
        message = "SMTP enabled must be a bool"
        raise NotificationConfigError(message)
    if not enabled:
        return DisabledNotificationConfig()
    try:
        sender = _single_mailbox(user, field_name="user")
        selected_recipients = (sender,) if not recipients.strip() else _mailboxes(recipients, field_name="recipients")
        return SmtpNotificationConfig(
            host=host,
            user=sender,
            password=password,
            recipients=selected_recipients,
            port=port,
            transport=SmtpTransport(transport),
        )
    except NotificationConfigError:
        raise
    except (TypeError, ValueError) as error:
        raise NotificationConfigError(str(error)) from error
