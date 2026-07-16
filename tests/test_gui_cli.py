import subprocess
import sys
from ipaddress import IPv4Address
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest

import gui
import module.webui.app as webui_app

if TYPE_CHECKING:
    from collections.abc import Callable


def test_main_builds_webui_app_in_fresh_process() -> None:
    script = """
import sys

import gui


def ignore_server_start(*_args: object, **_kwargs: object) -> None:
    pass


gui.uvicorn.run = ignore_server_start
sys.argv = ["gui.py"]
gui.main()
"""

    subprocess.run(  # noqa: S603 - 使用当前测试解释器启动隔离的导入环境。
        [sys.executable, "-c", script],
        check=True,
        cwd=Path(__file__).resolve().parents[1],
    )


def test_main_uses_local_webui_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    application = object()
    calls: list[tuple[object, dict[str, object]]] = []
    auto_run_values: list[bool] = []

    def build_app(*, auto_run: bool = False) -> object:
        auto_run_values.append(auto_run)
        return application

    def run(app: object, **kwargs: object) -> None:
        calls.append((app, kwargs))

    monkeypatch.setattr(sys, "argv", ["gui.py"])
    monkeypatch.setattr(gui.uvicorn, "run", run)
    monkeypatch.setattr(webui_app, "app", build_app)

    gui.main()

    assert auto_run_values == [False]
    assert calls == [
        (
            application,
            {
                "host": "127.0.0.1",
                "port": 22267,
                "log_config": None,
            },
        )
    ]


def test_main_forwards_auto_run_to_the_webui_app(monkeypatch: pytest.MonkeyPatch) -> None:
    application = object()
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
        return application

    def run(app: object, **kwargs: object) -> None:
        assert app is application
        assert "factory" not in kwargs

    monkeypatch.setattr(sys, "argv", ["gui.py", "--run"])
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
        ["-k", "local-password"],
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
