from pathlib import Path

import pytest

import alas as alas_module
from module.application import Succeeded, TaskResult
from module.bootstrap import InstanceProcessExit, InstanceProcessExitKind


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
        @staticmethod
        def execute(instance: str, command: str, *, stop_signal: object) -> InstanceProcessExit:
            calls.append((instance, command, stop_signal))
            return _exit(kind)

    def build(root: Path) -> _Host:
        calls.append((root.resolve(),))
        return _Host()

    monkeypatch.setattr(alas_module, "build_default_instance_process_host", build)

    result = alas_module.main(
        ["benchmark", "--instance", "port-one", "--project-root", "."],
    )

    assert result == expected
    assert calls[0] == (Path.cwd(),)
    assert calls[1][0:2] == ("port-one", "benchmark")
    assert callable(getattr(calls[1][2], "is_set", None))


def test_cli_source_contains_no_legacy_scheduler_or_dynamic_executor() -> None:
    source = Path("alas.py").read_text(encoding="utf-8")

    assert "AzurLaneAutoScript" not in source
    assert "legacy_task_implementations" not in source
    assert "import_module" not in source
