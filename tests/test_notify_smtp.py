import smtplib
from typing import Self, cast

import pytest

import module.notify.notify as notify_module
from module.notify.configuration import SmtpNotificationConfig, SmtpTransport
from module.notify.notify import SmtpNotificationSender


class _Client:
    def __init__(self, *, refused: dict[str, tuple[int, bytes]] | None = None) -> None:
        self.refused = {} if refused is None else refused
        self.starttls_calls = 0
        self.login_args: tuple[str, str] | None = None
        self.messages: list[object] = []

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def starttls(self, *, context: object) -> None:
        assert context is not None
        self.starttls_calls += 1

    def login(self, *, user: str, password: str) -> None:
        self.login_args = (user, password)

    def send_message(self, message: object) -> dict[str, tuple[int, bytes]]:
        self.messages.append(message)
        return self.refused


def _config(transport: SmtpTransport, *, port: int) -> SmtpNotificationConfig:
    credential = "test-credential"
    return SmtpNotificationConfig(
        host="smtp.example.com",
        user="sender@example.com",
        password=credential,
        recipients=("receiver@example.com",),
        port=port,
        transport=transport,
    )


def _send(config: SmtpNotificationConfig) -> None:
    SmtpNotificationSender(config).send(
        recipient="receiver@example.com",
        title="Alas failed",
        content="boom",
        idempotency_key="run-1",
    )


def test_sender_uses_implicit_tls(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _Client()
    calls: list[tuple[str, int, int, object]] = []

    def factory(host: str, port: int, *, timeout: int, context: object) -> _Client:
        calls.append((host, port, timeout, context))
        return client

    monkeypatch.setattr(notify_module.smtplib, "SMTP_SSL", factory)
    _send(_config(SmtpTransport.IMPLICIT_TLS, port=465))

    assert calls[0][:3] == ("smtp.example.com", 465, notify_module.SMTP_TIMEOUT_SECONDS)
    assert calls[0][3] is not None
    assert client.starttls_calls == 0
    assert client.login_args == ("sender@example.com", "test-credential")
    message = cast("dict[str, str]", client.messages[0])
    assert message["To"] == "receiver@example.com"
    assert message["Message-ID"].startswith("<alas-")


def test_sender_uses_starttls(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _Client()
    calls: list[tuple[str, int, int]] = []

    def factory(host: str, port: int, *, timeout: int) -> _Client:
        calls.append((host, port, timeout))
        return client

    monkeypatch.setattr(notify_module.smtplib, "SMTP", factory)
    _send(_config(SmtpTransport.STARTTLS, port=587))

    assert calls == [("smtp.example.com", 587, notify_module.SMTP_TIMEOUT_SECONDS)]
    assert client.starttls_calls == 1


def test_sender_surfaces_recipient_refusal(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _Client(refused={"receiver@example.com": (550, b"rejected")})
    monkeypatch.setattr(notify_module.smtplib, "SMTP_SSL", lambda *_args, **_kwargs: client)

    with pytest.raises(smtplib.SMTPRecipientsRefused):
        _send(_config(SmtpTransport.IMPLICIT_TLS, port=465))
