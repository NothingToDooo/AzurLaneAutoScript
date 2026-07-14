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


class _LifecycleHost:
    def __init__(self, events: list[str], result: InstanceProcessExit | Exception) -> None:
        self._events = events
        self._result = result

    def __enter__(self) -> Self:
        self._events.append("host-enter")
        return self

    def __exit__(self, *args: object) -> None:
        del args
        self._events.append("host-exit")

    def execute(self, instance: str, command: str, *, stop_signal: object) -> InstanceProcessExit:
        del instance, command, stop_signal
        self._events.append("host-execute")
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


class _LifecyclePump:
    def __init__(
        self,
        factory: Callable[[], object],
        events: list[str],
        *,
        instance_name: str | None = None,
        stopped: bool = True,
    ) -> None:
        del instance_name
        self._factory = factory
        self._events = events
        self._stopped = stopped

    def start(self) -> None:
        self._events.append("pump-start")

    def stop(self) -> bool:
        self._events.append("pump-stop")
        return self._stopped

    def run_once(self) -> None:
        self._events.append("pump-run-once")
        self._factory()


def _install_lifecycle(
    monkeypatch: pytest.MonkeyPatch,
    events: list[str],
    result: InstanceProcessExit | Exception,
    *,
    pump_stopped: bool = True,
) -> None:
    def build_maintenance(root: Path) -> object:
        del root
        events.append("maintenance-build")
        return object()

    def build_host(root: Path) -> _LifecycleHost:
        del root
        return _LifecycleHost(events, result)

    def build_pump(
        factory: Callable[[], object],
        *,
        instance_name: str | None = None,
    ) -> _LifecyclePump:
        return _LifecyclePump(factory, events, instance_name=instance_name, stopped=pump_stopped)

    monkeypatch.setattr(alas_module, "build_default_instance_process_host", build_host)
    monkeypatch.setattr(alas_module, "build_default_notification_maintenance", build_maintenance)
    monkeypatch.setattr(alas_module, "NotificationSpoolPump", build_pump)


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

        @staticmethod
        def start() -> None:
            calls.append(("pump-start",))

        @staticmethod
        def stop() -> bool:
            calls.append(("pump-stop",))
            return True

        def run_once(self) -> None:
            self.factory()
            calls.append(("pump-run-once",))

    monkeypatch.setattr(alas_module, "build_default_instance_process_host", build)
    monkeypatch.setattr(alas_module, "build_default_notification_maintenance", build_maintenance)
    monkeypatch.setattr(alas_module, "NotificationSpoolPump", _Pump)

    result = alas_module.main(
        ["benchmark", "--instance", "port-one", "--project-root", "."],
    )

    assert result == expected
    assert calls[:4] == [
        ("pump-init", "port-one"),
        ("pump-start",),
        ("host-build", Path.cwd()),
        ("host-enter",),
    ]
    assert calls[4][0:2] == ("port-one", "benchmark")
    assert callable(getattr(calls[4][2], "is_set", None))
    assert calls[5:] == [
        ("host-exit",),
        ("pump-stop",),
        ("maintenance-build", Path.cwd()),
        ("pump-run-once",),
    ]


def test_cli_performs_final_notification_flush_after_host_close(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[str] = []
    _install_lifecycle(monkeypatch, events, _exit(InstanceProcessExitKind.FINISHED))

    result = alas_module.main(["benchmark", "--project-root", "."])

    assert result == 0
    assert events == [
        "pump-start",
        "host-enter",
        "host-execute",
        "host-exit",
        "pump-stop",
        "pump-run-once",
        "maintenance-build",
    ]


def test_cli_performs_final_notification_flush_after_process_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[str] = []
    process_error = RuntimeError("process failed")
    _install_lifecycle(monkeypatch, events, process_error)

    with pytest.raises(RuntimeError) as caught:
        alas_module.main(["benchmark", "--project-root", "."])

    assert caught.value is process_error
    assert events == [
        "pump-start",
        "host-enter",
        "host-execute",
        "host-exit",
        "pump-stop",
        "pump-run-once",
        "maintenance-build",
    ]


def test_cli_skips_concurrent_final_flush_when_background_pump_does_not_stop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    _install_lifecycle(
        monkeypatch,
        events,
        _exit(InstanceProcessExitKind.FINISHED),
        pump_stopped=False,
    )

    result = alas_module.main(["benchmark", "--project-root", "."])

    assert result == 0
    assert events == [
        "pump-start",
        "host-enter",
        "host-execute",
        "host-exit",
        "pump-stop",
    ]


def test_cli_source_contains_no_legacy_scheduler_or_dynamic_executor() -> None:
    source = Path("alas.py").read_text(encoding="utf-8")

    assert "AzurLaneAutoScript" not in source
    assert "legacy_task_implementations" not in source
    assert "import_module" not in source
