import sys
from ipaddress import IPv4Address

import pytest

import gui


def test_main_uses_local_webui_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    def run(app: str, **kwargs: object) -> None:
        calls.append((app, kwargs))

    monkeypatch.setattr(sys, "argv", ["gui.py"])
    monkeypatch.setattr(gui, "prepare_pywebio_imports", lambda: None)
    monkeypatch.setattr(gui.uvicorn, "run", run)

    gui.main()

    assert calls == [
        (
            "module.webui.app:app",
            {
                "host": "127.0.0.1",
                "port": 22267,
                "factory": True,
                "log_config": None,
            },
        )
    ]


@pytest.mark.parametrize(
    "options",
    [
        ["--ssl-key", "key.pem"],
        ["--host", str(IPv4Address(0))],
    ],
)
def test_main_rejects_removed_remote_options(
    monkeypatch: pytest.MonkeyPatch,
    options: list[str],
) -> None:
    def fail_if_started(*_args: object, **_kwargs: object) -> None:
        message = "WebUI must not start after an invalid option"
        raise AssertionError(message)

    monkeypatch.setattr(sys, "argv", ["gui.py", *options])
    monkeypatch.setattr(gui.uvicorn, "run", fail_if_started)

    with pytest.raises(SystemExit) as error:
        gui.main()

    assert error.value.code == 2
