import shutil
from pathlib import Path

import pytest

from module.bootstrap import production
from module.runtime.runner import CommandStatus
from module.task_registry import TASK_SPECS


def _project_root(tmp_path: Path) -> Path:
    (tmp_path / "config").mkdir()
    (tmp_path / "content" / "events").mkdir(parents=True)
    (tmp_path / "module").mkdir()
    shutil.copyfile("config/template.json", tmp_path / "config" / "template.json")
    return tmp_path


def test_command_validation_accepts_scheduler_and_every_task() -> None:
    production._validate_command("alas")  # ruff:ignore[private-member-access] - composition boundary contract.
    for command in TASK_SPECS:
        production._validate_command(command)  # ruff:ignore[private-member-access] - composition boundary contract.


@pytest.mark.parametrize("command", ["", " missing", "missing ", "missing"])
def test_command_validation_rejects_malformed_or_unknown_commands(command: str) -> None:
    with pytest.raises(ValueError, match="command"):
        production._validate_command(command)  # ruff:ignore[private-member-access] - composition boundary contract.


def test_unknown_command_fails_before_device_composition(
    tmp_path: Path,
) -> None:
    root = _project_root(tmp_path)
    outcome = production.run_default_command("missing", project_root=root)

    assert outcome.status is CommandStatus.FAILED
    assert outcome.exception_type == "ValueError"
    assert outcome.error_bundle is not None
    assert Path(outcome.error_bundle).is_dir()
    assert not (root / "config" / "alas.json").exists()


def test_initial_configuration_write_failure_returns_failed_outcome(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _ForbiddenBuilder:
        def __init__(self, _root: Path, _command: str) -> None:
            pass

        @staticmethod
        def build(*_args: object, **_kwargs: object) -> None:
            pytest.fail("failed initial write must stop before runtime composition")

    def fail_write(_path: Path, _data: bytes) -> None:
        message = "disk full"
        raise OSError(message)

    monkeypatch.setattr(production, "atomic_write", fail_write)
    monkeypatch.setattr(production, "PersonalRuntimeBuilder", _ForbiddenBuilder)

    outcome = production.run_default_command("benchmark", project_root=_project_root(tmp_path))

    assert outcome.status is CommandStatus.FAILED
    assert outcome.exception_type == "OSError"
    assert outcome.message == "disk full"


def test_system_exit_is_not_converted_to_a_successful_command(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _ExitingBuilder:
        def __init__(self, _root: Path, _command: str) -> None:
            pass

        @staticmethod
        def build(_document: object, *, clock: object) -> None:
            del clock
            raise SystemExit(0)

    monkeypatch.setattr(production, "PersonalRuntimeBuilder", _ExitingBuilder)

    with pytest.raises(SystemExit) as error:
        production.run_default_command("benchmark", project_root=_project_root(tmp_path))

    assert error.value.code == 0
