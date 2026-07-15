import sys
from ipaddress import IPv4Address
from typing import TYPE_CHECKING, cast

import pytest

import gui
import module.webui.app as webui_app

if TYPE_CHECKING:
    from collections.abc import Callable


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


def test_main_forwards_auto_run_to_the_deferred_webui_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    starts: list[str] = []

    class _Manager:
        @staticmethod
        def start_default() -> None:
            starts.append("alas")

    def build_asgi_app(**kwargs: object) -> object:
        callbacks = kwargs["on_startup"]
        assert isinstance(callbacks, list)
        candidate = callbacks[1]
        assert callable(candidate)
        auto_start = cast("Callable[[], None]", candidate)
        auto_start()
        return object()

    def run(app: str, **kwargs: object) -> None:
        assert app == "module.webui.app:app"
        assert kwargs["factory"] is True
        webui_app.app()

    monkeypatch.setattr(sys, "argv", ["gui.py", "--run"])
    monkeypatch.setattr(gui, "prepare_pywebio_imports", lambda: None)
    monkeypatch.setattr(gui.uvicorn, "run", run)
    monkeypatch.setattr(webui_app.AlasGUI, "set_theme", lambda: None)
    monkeypatch.setattr(webui_app, "atomic_failure_cleanup", lambda _path: None)
    monkeypatch.setattr(webui_app, "asgi_app", build_asgi_app)
    monkeypatch.setattr(webui_app.ProcessManager, "instance", _Manager)

    gui.main()

    assert starts == ["alas"]


@pytest.mark.parametrize(
    "options",
    [
        ["--ssl-key", "key.pem"],
        ["--host", str(IPv4Address(0))],
        ["--run", "alas"],
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
