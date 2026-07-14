import pytest

from module.notify import (
    DisabledNotificationConfig,
    NotificationConfigError,
    SmtpNotificationConfig,
    SmtpTransport,
    parse_notification_config,
)


def _config(*lines: str) -> str:
    return "\n".join(lines)


def test_explicit_null_provider_compiles_to_immutable_disabled_config() -> None:
    config = parse_notification_config("provider: null")

    assert config == DisabledNotificationConfig()
    assert not hasattr(config, "__dict__")


def test_legacy_empty_mapping_is_migrated_to_disabled_config() -> None:
    assert parse_notification_config("{}") == DisabledNotificationConfig()


def test_smtp_config_is_canonical_and_keeps_password_in_repr() -> None:
    credential = " local-smtp-password "

    config = parse_notification_config(
        f"""
provider: SMTP
host: smtp.example.com
user: sender@example.com
password: {credential!r}
port: 587
ssl: true
to:
  - first@example.com
  - second@example.com
"""
    )

    assert config == SmtpNotificationConfig(
        host="smtp.example.com",
        user="sender@example.com",
        password=credential,
        recipients=("first@example.com", "second@example.com"),
        port=587,
        transport=SmtpTransport.STARTTLS,
    )
    assert credential in repr(config)
    assert not hasattr(config, "__dict__")


def test_smtp_config_defaults_recipient_and_transport_from_user_and_port() -> None:
    config = parse_notification_config(
        """
provider: smtp
host: smtp.example.com
user: sender@example.com
password: secret
port: 465
"""
    )

    assert isinstance(config, SmtpNotificationConfig)
    assert config.recipients == ("sender@example.com",)
    assert config.transport is SmtpTransport.IMPLICIT_TLS


def test_scalar_recipient_header_is_split_into_independent_canonical_mailboxes() -> None:
    config = parse_notification_config(
        """
provider: smtp
host: smtp.example.com
user: sender@example.com
password: secret
port: 465
to: First <first@example.com>, second@example.com
"""
    )

    assert isinstance(config, SmtpNotificationConfig)
    assert config.recipients == ("first@example.com", "second@example.com")


@pytest.mark.parametrize(
    "raw_config",
    [
        _config(
            "provider: smtp",
            "host: smtp.example.com",
            "user: sender@example.com",
            "password: secret",
            "port: 465",
            "ssl: true",
            "starttls: false",
        ),
        _config(
            "provider: smtp",
            "host: smtp.example.com",
            "user: sender@example.com",
            "password: secret",
            "port: 465",
            "starttls: false",
        ),
    ],
)
def test_explicitly_disabling_starttls_on_implicit_tls_port_is_valid(raw_config: str) -> None:
    config = parse_notification_config(raw_config)

    assert isinstance(config, SmtpNotificationConfig)
    assert config.transport is SmtpTransport.IMPLICIT_TLS


@pytest.mark.parametrize(
    ("raw_config", "match"),
    [
        ("", "exactly one mapping"),
        ("provider: discord", "only the SMTP"),
        ("provider: null\nhost: smtp.example.com", "only provider: null"),
        ("provider: smtp\nuser: sender@example.com\npassword: secret", "field host"),
        (
            "provider: smtp\nhost: smtp.example.com\nuser: sender@example.com\npassword: secret\nport: true",
            "port must be an integer",
        ),
        (
            _config(
                "provider: smtp",
                "host: smtp.example.com",
                "user: sender@example.com",
                "password: secret",
                "receiver: first@example.com",
                "to: second@example.com",
            ),
            "only one recipient field",
        ),
        (
            "provider: smtp\nhost: smtp.example.com\nuser: sender@example.com\npassword: secret\nunknown: true",
            "unsupported fields",
        ),
        (
            _config(
                "provider: smtp",
                "host: smtp.example.com",
                "user: sender@example.com",
                "password: secret",
                "port: 2525",
                "ssl: true",
                "starttls: true",
            ),
            "cannot both be true",
        ),
        (
            _config(
                "provider: smtp",
                "host: smtp.example.com",
                "user: sender@example.com",
                "password: secret",
                "port: 2525",
                "ssl: false",
                "starttls: false",
            ),
            "requires TLS",
        ),
        (
            "provider: smtp\nhost: smtp.example.com\nuser: not-an-email\npassword: secret\nport: 465",
            "valid mailbox",
        ),
        (
            _config(
                "provider: smtp",
                "host: smtp.example.com",
                "user: sender@example.com",
                "password: secret",
                "port: 465",
                "receiver: not-an-email",
            ),
            "valid mailbox",
        ),
        ("provider: null\n---\nprovider: null", "exactly one mapping"),
    ],
)
def test_invalid_notification_config_is_rejected(raw_config: str, match: str) -> None:
    with pytest.raises(NotificationConfigError, match=match):
        parse_notification_config(raw_config)


def test_invalid_yaml_error_preserves_parser_detail_and_cause() -> None:
    credential = "local-smtp-password"
    raw_config = f"provider: smtp\npassword: {credential}\nreceiver: ["

    with pytest.raises(NotificationConfigError) as caught:
        parse_notification_config(raw_config)

    assert str(caught.value).startswith("SMTP config must be valid YAML:")
    assert caught.value.__cause__ is not None
    assert str(caught.value.__cause__) in str(caught.value)
