from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest

from module.runtime import CompiledTaskSettings, SettingsDocumentError, compile_task_settings


@dataclass(frozen=True, slots=True)
class _NestedSettings:
    values: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class _Settings:
    name: str
    nested: _NestedSettings
    deadline: datetime | None = None
    retry_delay: timedelta = timedelta(minutes=5)


def _tasks(*, restart_values: tuple[int, ...] = (1, 2)) -> dict[str, object]:
    return {
        "restart": _Settings("restart", _NestedSettings(restart_values)),
        "benchmark": _Settings(
            "benchmark",
            _NestedSettings((3,)),
            deadline=datetime(2026, 7, 22, 8, tzinfo=UTC),
        ),
    }


def test_compile_task_settings_returns_one_immutable_snapshot_map() -> None:
    compiled = compile_task_settings(_tasks(), task_ids=("restart", "benchmark"))

    assert set(compiled) == {"restart", "benchmark"}
    restart = compiled["restart"]
    assert isinstance(restart, CompiledTaskSettings)
    assert restart.settings == _Settings("restart", _NestedSettings((1, 2)))
    assert restart.revision > 0
    with pytest.raises(TypeError):
        cast("dict[str, object]", compiled)["restart"] = object()


def test_typed_settings_revision_is_deterministic_and_task_local() -> None:
    original = compile_task_settings(_tasks(), task_ids=("restart", "benchmark"))
    repeated = compile_task_settings(_tasks(), task_ids=("restart", "benchmark"))
    changed = compile_task_settings(_tasks(restart_values=(1, 2, 3)), task_ids=("restart", "benchmark"))

    assert repeated == original
    assert changed["restart"].revision != original["restart"].revision
    assert changed["benchmark"].revision == original["benchmark"].revision


@pytest.mark.parametrize(
    "tasks",
    [
        {"restart": _Settings("restart", _NestedSettings((1,)))},
        {
            "restart": _Settings("restart", _NestedSettings((1,))),
            "benchmark": _Settings("benchmark", _NestedSettings((2,))),
            "removed": _Settings("removed", _NestedSettings((3,))),
        },
    ],
)
def test_compile_task_settings_requires_exact_coverage(tasks: dict[str, object]) -> None:
    with pytest.raises(SettingsDocumentError, match="coverage mismatch"):
        compile_task_settings(tasks, task_ids=("restart", "benchmark"))


def test_compile_task_settings_rejects_opaque_or_mutable_values() -> None:
    with pytest.raises(SettingsDocumentError, match="immutable typed values"):
        compile_task_settings(
            {"restart": object(), "benchmark": _Settings("benchmark", _NestedSettings((2,)))},
            task_ids=("restart", "benchmark"),
        )

    with pytest.raises(SettingsDocumentError, match="immutable typed values"):
        compile_task_settings(
            {"restart": [1, 2], "benchmark": _Settings("benchmark", _NestedSettings((2,)))},
            task_ids=("restart", "benchmark"),
        )
