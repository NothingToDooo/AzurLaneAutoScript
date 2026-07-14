from pathlib import Path
from typing import TYPE_CHECKING, Self

import pytest

import alas as alas_module
from module.application import Succeeded, TaskResult
from module.bootstrap import InstanceProcessExit, InstanceProcessExitKind

if TYPE_CHECKING:
    from collections.abc import Callable


def _exit(kind: InstanceProcessExitKind) -> InstanceProcessExit:
    return InstanceProcessExit(kind, task_result=TaskResult(Succeeded()))


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        (InstanceProcessExitKind.FINISHED, 0),
        (InstanceProcessExitKind.RESTART_REQUESTED, alas_module.EXIT_RESTART_REQUESTED),
        (InstanceProcessExitKind.STOPPED, alas_module.EXIT_STOPPED),
        (InstanceProcessExitKind.FAILED, 1),
    ],
)
def test_cli_delegates_to_the_typed_process_host(
    monkeypatch: pytest.MonkeyPatch,
    kind: InstanceProcessExitKind,
    expected: int,
) -> None:
    calls: list[tuple[object, ...]] = []

    class _Host:
        def __enter__(self) -> Self:
            calls.append(("host-enter",))
            return self

        def __exit__(self, *args: object) -> None:
            del args
            calls.append(("host-exit",))

        @staticmethod
        def execute(instance: str, command: str, *, stop_signal: object) -> InstanceProcessExit:
            calls.append((instance, command, stop_signal))
            return _exit(kind)

    def build(root: Path) -> _Host:
        calls.append(("host-build", root.resolve()))
        return _Host()

    def build_maintenance(root: Path) -> object:
        calls.append(("maintenance-build", root.resolve()))
        return object()

    class _Pump:
        def __init__(
            self,
            factory: Callable[[], object],
            *,
            instance_name: str | None = None,
        ) -> None:
            calls.append(("pump-init", instance_name))
            self.factory = factory

        def __enter__(self) -> Self:
            self.factory()
            calls.append(("pump-enter",))
            return self

        def __exit__(self, *args: object) -> None:
            del args
            calls.append(("pump-exit",))

    monkeypatch.setattr(alas_module, "build_default_instance_process_host", build)
    monkeypatch.setattr(alas_module, "build_default_notification_maintenance", build_maintenance)
    monkeypatch.setattr(alas_module, "NotificationSpoolPump", _Pump)

    result = alas_module.main(
        ["benchmark", "--instance", "port-one", "--project-root", "."],
    )

    assert result == expected
    assert calls[:5] == [
        ("pump-init", "port-one"),
        ("maintenance-build", Path.cwd()),
        ("pump-enter",),
        ("host-build", Path.cwd()),
        ("host-enter",),
    ]
    assert calls[5][0:2] == ("port-one", "benchmark")
    assert callable(getattr(calls[5][2], "is_set", None))
    assert calls[6:] == [("host-exit",), ("pump-exit",)]


def test_cli_source_contains_no_legacy_scheduler_or_dynamic_executor() -> None:
    source = Path("alas.py").read_text(encoding="utf-8")

    assert "AzurLaneAutoScript" not in source
    assert "legacy_task_implementations" not in source
    assert "import_module" not in source
