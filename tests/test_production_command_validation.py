import shutil
from pathlib import Path

import pytest

from module.bootstrap import production
from module.runtime.runner import CommandStatus
from module.task_registry import TASK_CATALOG


def _project_root(tmp_path: Path) -> Path:
    (tmp_path / "config").mkdir()
    (tmp_path / "content" / "events").mkdir(parents=True)
    (tmp_path / "module").mkdir()
    shutil.copyfile("config/template.json", tmp_path / "config" / "template.json")
    return tmp_path


def test_command_validation_accepts_scheduler_and_every_task() -> None:
    production._validate_command("alas")  # noqa: SLF001 - composition boundary contract.
    for command in TASK_CATALOG:
        production._validate_command(command)  # noqa: SLF001 - composition boundary contract.


@pytest.mark.parametrize("command", ["", " missing", "missing ", "missing"])
def test_command_validation_rejects_malformed_or_unknown_commands(command: str) -> None:
    with pytest.raises(ValueError, match="command"):
        production._validate_command(command)  # noqa: SLF001 - composition boundary contract.


def test_unknown_command_fails_before_device_composition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _ForbiddenBundleSource:
        def __init__(self, _root: Path) -> None:
            pytest.fail("invalid command must fail before device composition")

    monkeypatch.setattr(production, "Mumu12GameRuntimeBundleSource", _ForbiddenBundleSource)

    outcome = production.run_default_command("missing", project_root=_project_root(tmp_path))

    assert outcome.status is CommandStatus.FAILED
    assert outcome.exception_type == "ValueError"
    assert outcome.error_bundle is not None
    assert Path(outcome.error_bundle).is_dir()
