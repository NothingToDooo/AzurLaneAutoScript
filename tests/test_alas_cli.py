import signal
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

import alas as alas_module
from module.runtime.runner import CommandOutcome, CommandStatus

if TYPE_CHECKING:
    from module.base.stop_event import StopEvent


@pytest.fixture(autouse=True)
def _isolate_process_setup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        alas_module,
        "configure_file_logging",
        lambda root, *, name: Path(root) / "log" / f"{name}.txt",
        raising=False,
    )


def _outcome(
    status: CommandStatus,
    *,
    command: str = "benchmark",
    message: str | None = None,
    error_bundle: str | None = None,
) -> CommandOutcome:
    return CommandOutcome(
        command=command,
        status=status,
        finished_at=datetime.now(UTC),
        message=message,
        error_bundle=error_bundle,
    )


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (CommandStatus.FINISHED, 0),
        (CommandStatus.RESTART_REQUESTED, alas_module.EXIT_RESTART_REQUESTED),
        (CommandStatus.STOPPED, alas_module.EXIT_STOPPED),
        (CommandStatus.FAILED, 1),
        (CommandStatus.KILLED, 1),
    ],
)
def test_cli_delegates_to_default_command(
    monkeypatch: pytest.MonkeyPatch,
    status: CommandStatus,
    expected: int,
) -> None:
    calls: list[tuple[str, Path, StopEvent]] = []

    def run(command: str, *, project_root: Path, stop_signal: StopEvent) -> CommandOutcome:
        calls.append((command, project_root, stop_signal))
        return _outcome(status, command=command)

    monkeypatch.setattr(alas_module, "run_default_command", run)

    result = alas_module.main(["benchmark"])

    assert result == expected
    assert len(calls) == 1
    command, project_root, stop_signal = calls[0]
    assert command == "benchmark"
    assert project_root == alas_module.PROJECT_ROOT
    assert not stop_signal.is_set()


def test_cli_uses_personal_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def run(command: str, *, project_root: Path, stop_signal: StopEvent) -> CommandOutcome:
        del stop_signal
        assert project_root == alas_module.PROJECT_ROOT
        calls.append(command)
        return _outcome(CommandStatus.FINISHED, command=command)

    monkeypatch.setattr(alas_module, "run_default_command", run)

    assert alas_module.main([]) == 0
    assert calls == ["alas"]


def test_cli_initializes_process_without_changing_cwd(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[tuple[object, ...]] = []
    monkeypatch.chdir(tmp_path)

    def configure(root: Path, *, name: str) -> Path:
        calls.append(("configure_file_logging", root, name))
        return root / "log" / f"{name}.txt"

    def run(command: str, *, project_root: Path, stop_signal: StopEvent) -> CommandOutcome:
        del stop_signal
        calls.append(("run_default_command", command, project_root, Path.cwd()))
        return _outcome(CommandStatus.FINISHED, command=command)

    monkeypatch.setattr(alas_module, "configure_file_logging", configure)
    monkeypatch.setattr(alas_module, "run_default_command", run)

    assert alas_module.main(["benchmark"]) == 0
    assert calls == [
        ("configure_file_logging", alas_module.PROJECT_ROOT, "alas"),
        ("run_default_command", "benchmark", alas_module.PROJECT_ROOT, tmp_path),
    ]
    assert Path.cwd() == tmp_path


def test_cli_restores_signal_handlers_when_runner_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    error = RuntimeError("runner failed")

    def run(command: str, *, project_root: Path, stop_signal: StopEvent) -> CommandOutcome:
        del command, project_root, stop_signal
        raise error

    monkeypatch.setattr(alas_module, "run_default_command", run)
    previous = signal.getsignal(signal.SIGINT)

    with pytest.raises(RuntimeError) as raised:
        alas_module.main(["benchmark"])

    assert raised.value is error
    assert signal.getsignal(signal.SIGINT) == previous


def test_cli_logs_failed_command_and_error_bundle(monkeypatch: pytest.MonkeyPatch) -> None:
    errors: list[str] = []

    def run(command: str, *, project_root: Path, stop_signal: StopEvent) -> CommandOutcome:
        del project_root, stop_signal
        return _outcome(
            CommandStatus.FAILED,
            command=command,
            message="boom",
            error_bundle="log/error/benchmark.zip",
        )

    monkeypatch.setattr(alas_module, "run_default_command", run)
    monkeypatch.setattr(alas_module.logger, "error", errors.append)

    assert alas_module.main(["benchmark"]) == 1
    assert errors == [
        "Command 'benchmark' failed: boom",
        "Error bundle: log/error/benchmark.zip",
    ]


def test_cli_rejects_removed_instance_option() -> None:
    with pytest.raises(SystemExit, match="2"):
        alas_module.main(["--instance", "port-one"])


def test_cli_rejects_removed_project_root_option() -> None:
    with pytest.raises(SystemExit, match="2"):
        alas_module.main(["--project-root", "."])
