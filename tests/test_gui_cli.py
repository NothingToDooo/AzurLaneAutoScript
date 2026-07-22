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


@pytest.fixture(autouse=True)
def _isolate_process_setup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gui, "chdir", lambda _path: None, raising=False)
    monkeypatch.setattr(
        gui,
        "configure_file_logging",
        lambda root, *, name: Path(root) / "log" / f"{name}.txt",
        raising=False,
    )


def test_main_builds_webui_app_in_fresh_process(tmp_path: Path) -> None:
    script = """
import sys
from pathlib import Path

sys.path.insert(0, sys.argv[1])
import gui


def ignore_server_start(*_args: object, **_kwargs: object) -> None:
    assert Path.cwd() == Path(gui.__file__).resolve().parent


gui.uvicorn.run = ignore_server_start
gui.configure_file_logging = lambda root, name: Path(root) / "log" / f"{name}.txt"
sys.argv = ["gui.py"]
gui.main()
"""

    # 桌面测试宿主没有控制台，Windows 子进程必须隐藏以免弹出 PyWebIO Application 窗口。
    creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    subprocess.run(  # ruff:ignore[subprocess-without-shell-equals-true] - 使用当前测试解释器启动隔离的导入环境。
        [sys.executable, "-c", script, str(Path(__file__).resolve().parents[1])],
        check=True,
        cwd=tmp_path,
        creationflags=creationflags,
    )


def test_main_uses_local_webui_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    application = object()
    calls: list[tuple[object, dict[str, object]]] = []
    auto_run_values: list[bool] = []
    lifecycle: list[tuple[object, ...]] = []

    def build_app(*, auto_run: bool = False) -> object:
        auto_run_values.append(auto_run)
        lifecycle.append(("build_app", auto_run))
        return application

    def run(app: object, **kwargs: object) -> None:
        lifecycle.append(("uvicorn",))
        calls.append((app, kwargs))

    def configure(root: Path, *, name: str) -> Path:
        lifecycle.append(("configure_file_logging", root, name))
        return root / "log" / f"{name}.txt"

    monkeypatch.setattr(sys, "argv", ["gui.py"])
    monkeypatch.setattr(gui, "chdir", lambda root: lifecycle.append(("chdir", root)))
    monkeypatch.setattr(gui, "configure_file_logging", configure)
    monkeypatch.setattr(gui.uvicorn, "run", run)
    monkeypatch.setattr(webui_app, "app", build_app)

    gui.main()

    assert auto_run_values == [False]
    assert lifecycle == [
        ("chdir", gui.PROJECT_ROOT),
        ("configure_file_logging", gui.PROJECT_ROOT, "gui"),
        ("build_app", False),
        ("uvicorn",),
    ]
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
