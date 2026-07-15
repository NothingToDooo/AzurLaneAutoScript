import pytest

from module.notify.configuration import SmtpNotificationConfig, SmtpTransport
from module.notify.direct import send_notification
from module.notify.notify import SmtpNotificationSender


def _config(*recipients: str) -> SmtpNotificationConfig:
    return SmtpNotificationConfig(
        host="smtp.example.com",
        user="sender@example.com",
        password=f"credential-{id(recipients)}",
        recipients=recipients,
        port=465,
        transport=SmtpTransport.IMPLICIT_TLS,
    )


def test_direct_notification_sends_each_recipient_once(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str, str]] = []

    def capture(
        _sender: SmtpNotificationSender,
        *,
        recipient: str,
        title: str,
        content: str,
    ) -> None:
        calls.append((recipient, title, content))

    monkeypatch.setattr(SmtpNotificationSender, "send", capture)

    result = send_notification(
        _config("one@example.com", "two@example.com"),
        title="Alas completed",
        content="Task completed",
    )

    assert result is True
    assert calls == [
        ("one@example.com", "Alas completed", "Task completed"),
        ("two@example.com", "Alas completed", "Task completed"),
    ]


def test_direct_notification_does_not_retry_a_failed_recipient(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts: list[str] = []

    def fail(
        _sender: SmtpNotificationSender,
        *,
        recipient: str,
        title: str,
        content: str,
    ) -> None:
        del title, content
        attempts.append(recipient)
        message = "SMTP failure"
        raise OSError(message)

    monkeypatch.setattr(SmtpNotificationSender, "send", fail)

    assert send_notification(_config("one@example.com"), title="Title", content="Body") is False
    assert attempts == ["one@example.com"]


def test_direct_notification_returns_false_and_continues_other_recipients(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts: list[str] = []

    def fail_first_recipient(
        _sender: SmtpNotificationSender,
        *,
        recipient: str,
        title: str,
        content: str,
    ) -> None:
        del title, content
        attempts.append(recipient)
        if recipient == "broken@example.com":
            message = "permanent SMTP failure"
            raise OSError(message)

    monkeypatch.setattr(SmtpNotificationSender, "send", fail_first_recipient)

    result = send_notification(
        _config("broken@example.com", "working@example.com"),
        title="Title",
        content="Body",
    )

    assert result is False
    assert attempts == ["broken@example.com", "working@example.com"]


@pytest.mark.parametrize(
    ("field", "value"),
    [("config", object()), ("title", object()), ("content", object())],
)
def test_direct_notification_rejects_invalid_arguments(
    field: str,
    value: object,
) -> None:
    arguments: dict[str, object] = {
        "config": _config("one@example.com"),
        "title": "Title",
        "content": "Body",
    }
    arguments[field] = value

    call = send_notification
    with pytest.raises(TypeError):
        call(**arguments)  # type: ignore[arg-type]
