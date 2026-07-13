from email.message import EmailMessage
from typing import TYPE_CHECKING
from unittest.mock import ANY, MagicMock, call

import module.notify.notify as notify_module
from module.notify import handle_notify

if TYPE_CHECKING:
    import pytest

LOGIN_VALUE = "secret-value"


def _smtp_context() -> tuple[MagicMock, MagicMock]:
    context = MagicMock()
    client = context.__enter__.return_value
    client.send_message.return_value = {}
    return context, client


def test_smtp_port_465_uses_ssl_and_defaults_receiver_to_user(monkeypatch: pytest.MonkeyPatch) -> None:
    context, client = _smtp_context()
    tls_context = MagicMock()
    smtp = MagicMock()
    smtp_ssl = MagicMock(return_value=context)
    monkeypatch.setattr(notify_module.smtplib, "SMTP", smtp)
    monkeypatch.setattr(notify_module.smtplib, "SMTP_SSL", smtp_ssl)
    create_default_context = MagicMock(return_value=tls_context)
    monkeypatch.setattr(notify_module.ssl, "create_default_context", create_default_context)

    sent = handle_notify(
        """
provider: smtp
host: smtp.example.com
user: sender@example.com
password: secret-value
port: 465
""",
        title="Alas crashed",
        content="RequestHumanTakeover",
    )

    assert sent
    smtp.assert_not_called()
    create_default_context.assert_called_once_with()
    smtp_ssl.assert_called_once_with(
        "smtp.example.com",
        465,
        timeout=notify_module.SMTP_TIMEOUT_SECONDS,
        context=tls_context,
    )
    client.starttls.assert_not_called()
    client.login.assert_called_once_with(user="sender@example.com", password=LOGIN_VALUE)
    message = client.send_message.call_args.args[0]
    assert isinstance(message, EmailMessage)
    assert message["Subject"] == "Alas crashed"
    assert message["From"] == "sender@example.com"
    assert message["To"] == "sender@example.com"
    assert message.get_content().rstrip() == "RequestHumanTakeover"


def test_omitted_and_null_ports_keep_smtplib_default_sentinel(monkeypatch: pytest.MonkeyPatch) -> None:
    base_config = """
provider: smtp
host: smtp.example.com
user: sender@example.com
password: secret-value
"""
    context, client = _smtp_context()
    smtp = MagicMock(return_value=context)
    smtp_ssl = MagicMock()
    monkeypatch.setattr(notify_module.smtplib, "SMTP", smtp)
    monkeypatch.setattr(notify_module.smtplib, "SMTP_SSL", smtp_ssl)

    for raw_config in (base_config, f"{base_config}port: null\n"):
        sent = handle_notify(raw_config, title="Alas crashed", content="RequestHumanTakeover")

        assert sent

    assert smtp.call_args_list == [
        call("smtp.example.com", 0, timeout=notify_module.SMTP_TIMEOUT_SECONDS),
        call("smtp.example.com", 0, timeout=notify_module.SMTP_TIMEOUT_SECONDS),
    ]
    smtp_ssl.assert_not_called()
    client.starttls.assert_not_called()


def test_omitted_port_with_ssl_uses_ssl_default_sentinel(monkeypatch: pytest.MonkeyPatch) -> None:
    context, client = _smtp_context()
    smtp = MagicMock()
    smtp_ssl = MagicMock(return_value=context)
    monkeypatch.setattr(notify_module.smtplib, "SMTP", smtp)
    monkeypatch.setattr(notify_module.smtplib, "SMTP_SSL", smtp_ssl)

    sent = handle_notify(
        """
provider: smtp
host: smtp.example.com
user: sender@example.com
password: secret-value
ssl: true
""",
        title="Alas crashed",
        content="RequestHumanTakeover",
    )

    assert sent
    smtp.assert_not_called()
    smtp_ssl.assert_called_once_with(
        "smtp.example.com",
        0,
        timeout=notify_module.SMTP_TIMEOUT_SECONDS,
        context=ANY,
    )
    client.starttls.assert_not_called()


def test_smtp_port_587_defaults_to_starttls_before_login(monkeypatch: pytest.MonkeyPatch) -> None:
    context, client = _smtp_context()
    smtp = MagicMock(return_value=context)
    smtp_ssl = MagicMock()
    monkeypatch.setattr(notify_module.smtplib, "SMTP", smtp)
    monkeypatch.setattr(notify_module.smtplib, "SMTP_SSL", smtp_ssl)

    sent = handle_notify(
        """
provider: smtp
host: smtp.example.com
user: sender@example.com
password: secret-value
port: 587
""",
        title="Campaign finished",
        content="Reached run count limit",
    )

    assert sent
    smtp.assert_called_once_with("smtp.example.com", 587, timeout=notify_module.SMTP_TIMEOUT_SECONDS)
    smtp_ssl.assert_not_called()
    assert [method_call[0] for method_call in client.method_calls] == ["starttls", "login", "send_message"]
    client.starttls.assert_called_once_with(context=ANY)
    client.login.assert_called_once_with(user="sender@example.com", password=LOGIN_VALUE)


def test_starttls_failure_never_attempts_login(monkeypatch: pytest.MonkeyPatch) -> None:
    context, client = _smtp_context()
    client.starttls.side_effect = notify_module.smtplib.SMTPException("TLS unavailable")
    smtp = MagicMock(return_value=context)
    monkeypatch.setattr(notify_module.smtplib, "SMTP", smtp)

    sent = handle_notify(
        """
provider: smtp
host: smtp.example.com
user: sender@example.com
password: secret-value
port: 587
""",
        title="Ignored",
        content="Ignored",
    )

    assert not sent
    client.starttls.assert_called_once_with(context=ANY)
    client.login.assert_not_called()
    client.send_message.assert_not_called()


def test_nonstandard_port_with_ssl_false_uses_plain_smtp(monkeypatch: pytest.MonkeyPatch) -> None:
    context, client = _smtp_context()
    smtp = MagicMock(return_value=context)
    smtp_ssl = MagicMock()
    monkeypatch.setattr(notify_module.smtplib, "SMTP", smtp)
    monkeypatch.setattr(notify_module.smtplib, "SMTP_SSL", smtp_ssl)

    sent = handle_notify(
        """
provider: SMTP
host: smtp.example.com
user: sender@example.com
password: secret-value
port: 2525
ssl: false
to:
  - first@example.com
  - second@example.com
""",
        title="Campaign finished",
        content="Reached run count limit",
    )

    assert sent
    smtp.assert_called_once_with("smtp.example.com", 2525, timeout=notify_module.SMTP_TIMEOUT_SECONDS)
    smtp_ssl.assert_not_called()
    client.starttls.assert_not_called()
    assert [method_call[0] for method_call in client.method_calls] == ["login", "send_message"]
    message = client.send_message.call_args.args[0]
    assert message["To"] == "first@example.com, second@example.com"


def test_smtp_port_587_with_ssl_false_still_uses_starttls(monkeypatch: pytest.MonkeyPatch) -> None:
    context, client = _smtp_context()
    smtp = MagicMock(return_value=context)
    smtp_ssl = MagicMock()
    monkeypatch.setattr(notify_module.smtplib, "SMTP", smtp)
    monkeypatch.setattr(notify_module.smtplib, "SMTP_SSL", smtp_ssl)

    sent = handle_notify(
        """
provider: smtp
host: smtp.example.com
user: sender@example.com
password: secret-value
port: 587
ssl: false
""",
        title="Campaign finished",
        content="Reached run count limit",
    )

    assert sent
    smtp.assert_called_once_with("smtp.example.com", 587, timeout=notify_module.SMTP_TIMEOUT_SECONDS)
    smtp_ssl.assert_not_called()
    assert [method_call[0] for method_call in client.method_calls] == ["starttls", "login", "send_message"]
    client.starttls.assert_called_once_with(context=ANY)


def test_smtp_port_587_with_ssl_true_uses_starttls(monkeypatch: pytest.MonkeyPatch) -> None:
    context, client = _smtp_context()
    smtp = MagicMock(return_value=context)
    smtp_ssl = MagicMock()
    monkeypatch.setattr(notify_module.smtplib, "SMTP", smtp)
    monkeypatch.setattr(notify_module.smtplib, "SMTP_SSL", smtp_ssl)

    sent = handle_notify(
        """
provider: smtp
host: smtp.example.com
user: sender@example.com
password: secret-value
port: 587
ssl: true
""",
        title="Campaign finished",
        content="Reached run count limit",
    )

    assert sent
    smtp.assert_called_once_with("smtp.example.com", 587, timeout=notify_module.SMTP_TIMEOUT_SECONDS)
    smtp_ssl.assert_not_called()
    assert [method_call[0] for method_call in client.method_calls] == ["starttls", "login", "send_message"]
    client.starttls.assert_called_once_with(context=ANY)


def test_explicit_starttls_on_custom_port_upgrades_before_login(monkeypatch: pytest.MonkeyPatch) -> None:
    context, client = _smtp_context()
    smtp = MagicMock(return_value=context)
    smtp_ssl = MagicMock()
    monkeypatch.setattr(notify_module.smtplib, "SMTP", smtp)
    monkeypatch.setattr(notify_module.smtplib, "SMTP_SSL", smtp_ssl)

    sent = handle_notify(
        """
provider: smtp
host: smtp.example.com
user: sender@example.com
password: secret-value
port: 2525
starttls: true
""",
        title="Campaign finished",
        content="Reached run count limit",
    )

    assert sent
    smtp.assert_called_once_with("smtp.example.com", 2525, timeout=notify_module.SMTP_TIMEOUT_SECONDS)
    smtp_ssl.assert_not_called()
    assert [method_call[0] for method_call in client.method_calls] == ["starttls", "login", "send_message"]
    client.starttls.assert_called_once_with(context=ANY)


def test_explicit_ssl_and_starttls_are_rejected_without_connecting(monkeypatch: pytest.MonkeyPatch) -> None:
    errors: list[str] = []
    smtp = MagicMock()
    smtp_ssl = MagicMock()
    monkeypatch.setattr(notify_module.smtplib, "SMTP", smtp)
    monkeypatch.setattr(notify_module.smtplib, "SMTP_SSL", smtp_ssl)
    monkeypatch.setattr(notify_module.logger, "error", errors.append)

    sent = handle_notify(
        """
provider: smtp
host: smtp.example.com
user: sender@example.com
password: secret-value
port: 2525
ssl: true
starttls: true
""",
        title="Ignored",
        content="Ignored",
    )

    assert not sent
    smtp.assert_not_called()
    smtp_ssl.assert_not_called()
    assert errors == ["Failed to load SMTP notify config (_EmailConfigError), skip sending"]


def test_smtp_failure_does_not_log_password_or_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    credential = "password-must-not-leak"
    context, client = _smtp_context()
    client.login.side_effect = RuntimeError(credential)
    errors: list[str] = []
    monkeypatch.setattr(notify_module.smtplib, "SMTP_SSL", MagicMock(return_value=context))
    monkeypatch.setattr(notify_module.logger, "error", errors.append)

    sent = handle_notify(
        f"""
provider: smtp
host: smtp.example.com
user: sender@example.com
password: {credential}
port: 465
""",
        title="Alas crashed",
        content="Exception occurred",
    )

    assert not sent
    assert errors == ["SMTP notify failed (RuntimeError)"]
    assert credential not in "".join(errors)


def test_invalid_yaml_does_not_log_password_or_connect(monkeypatch: pytest.MonkeyPatch) -> None:
    credential = "yaml-password-must-not-leak"
    errors: list[str] = []
    smtp = MagicMock()
    smtp_ssl = MagicMock()
    monkeypatch.setattr(notify_module.smtplib, "SMTP", smtp)
    monkeypatch.setattr(notify_module.smtplib, "SMTP_SSL", smtp_ssl)
    monkeypatch.setattr(notify_module.logger, "error", errors.append)

    sent = handle_notify(
        f"""
provider: smtp
password: {credential}
receiver: [
""",
        title="Alas crashed",
        content="Invalid config",
    )

    assert not sent
    smtp.assert_not_called()
    smtp_ssl.assert_not_called()
    assert len(errors) == 1
    assert credential not in errors[0]


def test_non_smtp_provider_is_rejected_without_connecting(monkeypatch: pytest.MonkeyPatch) -> None:
    errors: list[str] = []
    smtp = MagicMock()
    smtp_ssl = MagicMock()
    monkeypatch.setattr(notify_module.smtplib, "SMTP", smtp)
    monkeypatch.setattr(notify_module.smtplib, "SMTP_SSL", smtp_ssl)
    monkeypatch.setattr(notify_module.logger, "error", errors.append)

    assert not handle_notify("provider: discord", title="Ignored", content="Ignored")
    smtp.assert_not_called()
    smtp_ssl.assert_not_called()
    assert errors == ["Failed to load SMTP notify config (_EmailConfigError), skip sending"]


def test_null_provider_keeps_notification_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    smtp = MagicMock()
    smtp_ssl = MagicMock()
    monkeypatch.setattr(notify_module.smtplib, "SMTP", smtp)
    monkeypatch.setattr(notify_module.smtplib, "SMTP_SSL", smtp_ssl)

    assert not handle_notify("provider: null", title="Ignored", content="Ignored")
    smtp.assert_not_called()
    smtp_ssl.assert_not_called()
