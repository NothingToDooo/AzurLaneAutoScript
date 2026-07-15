import pytest

from module.notify.configuration import (
    DisabledNotificationConfig,
    NotificationConfigError,
    SmtpNotificationConfig,
    SmtpTransport,
    build_notification_config,
)


def test_disabled_notification_ignores_blank_smtp_fields() -> None:
    assert (
        build_notification_config(
            enabled=False,
            host="",
            port=465,
            transport="implicit_tls",
            user="",
            password="",
            recipients="",
        )
        == DisabledNotificationConfig()
    )


def test_enabled_notification_compiles_explicit_smtp_fields() -> None:
    credential = "test-credential"
    config = build_notification_config(
        enabled=True,
        host="smtp.example.com",
        port=587,
        transport="starttls",
        user="sender@example.com",
        password=credential,
        recipients="first@example.com, second@example.com\nfirst@example.com",
    )

    assert config == SmtpNotificationConfig(
        host="smtp.example.com",
        user="sender@example.com",
        password=credential,
        recipients=("first@example.com", "second@example.com"),
        port=587,
        transport=SmtpTransport.STARTTLS,
    )


def test_blank_recipients_use_sender() -> None:
    credential = "test-credential"
    config = build_notification_config(
        enabled=True,
        host="smtp.example.com",
        port=465,
        transport="implicit_tls",
        user="sender@example.com",
        password=credential,
        recipients="",
    )

    assert isinstance(config, SmtpNotificationConfig)
    assert config.recipients == ("sender@example.com",)


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"host": ""}, "host"),
        ({"port": 0}, "port"),
        ({"transport": "plain"}, "plain"),
        ({"user": "not-an-address"}, "user"),
        ({"password": ""}, "password"),
        ({"recipients": "not-an-address"}, "recipients"),
    ],
)
def test_enabled_notification_rejects_invalid_fields(overrides: dict[str, object], match: str) -> None:
    fields: dict[str, object] = {
        "enabled": True,
        "host": "smtp.example.com",
        "port": 465,
        "transport": "implicit_tls",
        "user": "sender@example.com",
        "password": "secret",
        "recipients": "receiver@example.com",
    }
    fields.update(overrides)

    with pytest.raises(NotificationConfigError, match=match):
        build_notification_config(**fields)  # type: ignore[arg-type]
