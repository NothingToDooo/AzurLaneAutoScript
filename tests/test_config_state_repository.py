import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest

from module.application import (
    DelayTask,
    DisableTask,
    ExecutionMode,
    RequestAppRestart,
    RescheduleSelf,
    RescheduleTask,
    RunMetadata,
    Succeeded,
    TaskId,
    TaskResult,
    WakePolicy,
    WakeTask,
)
from module.application.state_effects import DeleteTaskState, UpsertTaskState
from module.state import config_repository
from module.state.config_repository import ConfigStateError, ConfigStateRepository, read_schedule_items
from module.task_registry import TASK_CATALOG

_NOW = datetime(2026, 7, 15, 8, 0, tzinfo=UTC)
_METADATA = RunMetadata(settings_revision=1, content_revision="content")


@dataclass(frozen=True, slots=True)
class _Clock:
    current: datetime = _NOW

    def now(self) -> datetime:
        return self.current


def _document() -> dict[str, object]:
    document = cast(
        "dict[str, object]",
        json.loads(Path("config/template.json").read_text(encoding="utf-8")),
    )
    for definition in TASK_CATALOG.values():
        if definition.priority is None:
            continue
        section = cast("dict[str, object]", document[definition.config_name])
        scheduler = cast("dict[str, object]", section["Scheduler"])
        scheduler["Enable"] = True
        scheduler["NextRun"] = "2026-07-15 16:00:00"
        scheduler["Command"] = definition.config_name
    return document


def _write(path: Path, document: dict[str, object]) -> None:
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")


def _load(path: Path) -> dict[str, object]:
    return cast("dict[str, object]", json.loads(path.read_text(encoding="utf-8")))


def _task_section(document: dict[str, object], task_id: str) -> dict[str, object]:
    config_name = TASK_CATALOG[task_id].config_name
    return cast("dict[str, object]", document[config_name])


def _scheduler(document: dict[str, object], task_id: str) -> dict[str, object]:
    return cast("dict[str, object]", _task_section(document, task_id)["Scheduler"])


def _storage(document: dict[str, object], task_id: str) -> dict[str, object]:
    storage_group = cast("dict[str, object]", _task_section(document, task_id)["Storage"])
    return cast("dict[str, object]", storage_group["Storage"])


def _repository(path: Path) -> ConfigStateRepository:
    return ConfigStateRepository(_Clock(), config_path=path)


def _begin(repository: ConfigStateRepository, task_id: str = "main") -> None:
    assert repository.begin_run(TaskId(task_id), ExecutionMode.SCHEDULED_JOB, _METADATA) == _NOW


def test_schedule_source_reads_every_catalog_schedule_in_priority_order(tmp_path: Path) -> None:
    path = tmp_path / "alas.json"
    document = _document()
    _scheduler(document, "commission")["Enable"] = False
    _write(path, document)

    items = _repository(path).list_items()

    expected_count = sum(definition.priority is not None for definition in TASK_CATALOG.values())
    assert len(items) == expected_count
    assert [item.priority for item in items] == list(range(expected_count))
    assert items[0].task_id == TaskId("restart")
    assert items[0].due_at == _NOW
    commission = next(item for item in items if item.task_id == TaskId("commission"))
    assert not commission.enabled
    assert read_schedule_items(path) == items


def test_repository_accepts_the_compilers_equivalent_iso_datetime_snapshot(tmp_path: Path) -> None:
    path = tmp_path / "alas.json"
    document = _document()
    restart = cast("dict[str, object]", document["Restart"])
    scheduler = cast("dict[str, object]", restart["Scheduler"])
    scheduler["NextRun"] = "2020-01-01T00:00:00"
    _write(path, document)
    parsed = config_repository.WebConfigurationCompiler().parse_runtime_document(document)

    repository = ConfigStateRepository(
        _Clock(),
        config_path=path,
        initial_document=document,
        initial_runtime_document=parsed,
    )

    assert repository.list_items()[0].task_id == TaskId("restart")


def test_runtime_repository_reads_its_startup_snapshot_without_reopening_or_recompiling(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "alas.json"
    _write(path, _document())
    repository = _repository(path)

    monkeypatch.setattr(
        config_repository,
        "_read_document",
        lambda _path: pytest.fail("runtime repository must not reopen alas.json"),
    )
    monkeypatch.setattr(
        config_repository,
        "WebConfigurationCompiler",
        lambda *_args, **_kwargs: pytest.fail("read-only runtime access must not recompile alas.json"),
    )

    assert repository.list_items()
    assert repository.task_state(TaskId("main")).namespace == "main"


def test_legacy_updates_and_result_effects_share_one_document_owner(tmp_path: Path) -> None:
    path = tmp_path / "alas.json"
    _write(path, _document())
    repository = _repository(path)

    repository.apply_runtime_updates(
        {
            "Research.Scheduler.Enable": False,
            "Research.Research.UseCube": "always_use",
        }
    )
    _begin(repository)
    repository.finalize_run(
        TaskResult(
            outcome=Succeeded(),
            effects=(RescheduleSelf(datetime(2026, 7, 16, 1, 0, tzinfo=UTC)),),
        )
    )

    stored = _load(path)
    research = _task_section(stored, "research")
    assert _scheduler(stored, "research")["Enable"] is False
    assert cast("dict[str, object]", research["Research"])["UseCube"] == "always_use"
    assert _scheduler(stored, "main")["NextRun"] == "2026-07-16 09:00:00"


def test_schedule_source_rejects_duplicate_json_fields(tmp_path: Path) -> None:
    path = tmp_path / "alas.json"
    path.write_text('{"Main": {}, "Main": {}}', encoding="utf-8")

    with pytest.raises(ConfigStateError, match="duplicate field: Main"):
        _repository(path).list_items()


def test_schedule_source_rejects_non_finite_json_numbers(tmp_path: Path) -> None:
    path = tmp_path / "alas.json"
    path.write_text('{"Main": NaN}', encoding="utf-8")

    with pytest.raises(ConfigStateError, match="non-finite JSON number: NaN"):
        _repository(path).list_items()


def test_finalize_applies_all_persistent_effects_with_one_atomic_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "alas.json"
    document = _document()
    _scheduler(document, "commission")["Enable"] = False
    _scheduler(document, "guild")["Enable"] = False
    _storage(document, "main")["reset"] = {
        "schema_version": 1,
        "payload": {"old": True},
        "updated_at": "2026-07-14T08:00:00Z",
    }
    _write(path, document)
    repository = _repository(path)
    _begin(repository)
    writes: list[str] = []
    real_atomic_write = config_repository.atomic_write

    def record_write(target: Path, content: str) -> None:
        writes.append(content)
        real_atomic_write(target, content)

    monkeypatch.setattr(config_repository, "atomic_write", record_write)
    repository.finalize_run(
        TaskResult(
            outcome=Succeeded(),
            effects=(
                RescheduleSelf(datetime(2026, 7, 16, 1, 0, tzinfo=UTC)),
                RescheduleTask(TaskId("research"), datetime(2026, 7, 16, 2, 0, tzinfo=UTC)),
                WakeTask(
                    TaskId("commission"),
                    datetime(2026, 7, 16, 3, 0, tzinfo=UTC),
                    WakePolicy.RESPECT_DISABLED,
                ),
                WakeTask(
                    TaskId("guild"),
                    datetime(2026, 7, 16, 4, 0, tzinfo=UTC),
                    WakePolicy.FORCE_ENABLE,
                ),
                DisableTask(TaskId("reward")),
                RequestAppRestart("apply update"),
            ),
            state_effects=(
                UpsertTaskState("main", "progress", 3, {"wave": 2, "fleets": [1, 2]}),
                DeleteTaskState("main", "reset"),
            ),
        ),
    )

    assert len(writes) == 1
    stored = _load(path)
    assert _scheduler(stored, "main")["NextRun"] == "2026-07-16 09:00:00"
    assert _scheduler(stored, "research")["NextRun"] == "2026-07-16 10:00:00"
    assert _scheduler(stored, "commission") == _scheduler(document, "commission")
    assert _scheduler(stored, "guild")["Enable"] is True
    assert _scheduler(stored, "guild")["NextRun"] == "2026-07-16 12:00:00"
    assert _scheduler(stored, "reward")["Enable"] is False
    assert _scheduler(stored, "reward")["NextRun"] == "2026-07-15 16:00:00"
    storage = _storage(stored, "main")
    assert "reset" not in storage
    assert storage["progress"] == {
        "schema_version": 3,
        "payload": {"wave": 2, "fleets": [1, 2]},
        "updated_at": "2026-07-15T08:00:00Z",
    }


@pytest.mark.parametrize(("enabled", "expected_due"), [(True, "2026-07-16 09:00:00"), (False, None)])
def test_wake_respect_disabled_obeys_the_stored_enable_flag(
    tmp_path: Path,
    *,
    enabled: bool,
    expected_due: str | None,
) -> None:
    path = tmp_path / "alas.json"
    document = _document()
    scheduler = _scheduler(document, "research")
    scheduler["Enable"] = enabled
    original_due = cast("str", scheduler["NextRun"])
    _write(path, document)
    repository = _repository(path)

    _begin(repository)
    repository.finalize_run(
        TaskResult(
            outcome=Succeeded(),
            effects=(
                WakeTask(
                    TaskId("research"),
                    datetime(2026, 7, 16, 1, 0, tzinfo=UTC),
                    WakePolicy.RESPECT_DISABLED,
                ),
            ),
        ),
    )

    stored_due = cast("str", _scheduler(_load(path), "research")["NextRun"])
    assert stored_due == (original_due if expected_due is None else expected_due)


@pytest.mark.parametrize(
    ("requested_due", "expected_due"),
    [
        (datetime(2026, 7, 15, 7, 0, tzinfo=UTC), "2026-07-15 16:00:00"),
        (datetime(2026, 7, 15, 9, 0, tzinfo=UTC), "2026-07-15 17:00:00"),
    ],
)
def test_delay_task_only_pushes_existing_due_time_later_and_preserves_enable(
    tmp_path: Path,
    *,
    requested_due: datetime,
    expected_due: str,
) -> None:
    path = tmp_path / "alas.json"
    document = _document()
    _scheduler(document, "research")["Enable"] = False
    _write(path, document)
    repository = _repository(path)

    _begin(repository)
    repository.finalize_run(
        TaskResult(
            outcome=Succeeded(),
            effects=(DelayTask(TaskId("research"), requested_due),),
        ),
    )

    stored = _scheduler(_load(path), "research")
    assert stored["Enable"] is False
    assert stored["NextRun"] == expected_due


def test_restart_only_result_does_not_rewrite_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "alas.json"
    _write(path, _document())
    repository = _repository(path)

    def unexpected_write(_target: Path, _content: str) -> None:
        pytest.fail("RequestAppRestart must not rewrite config state")

    monkeypatch.setattr(config_repository, "atomic_write", unexpected_write)
    _begin(repository)
    repository.finalize_run(
        TaskResult(outcome=Succeeded(), effects=(RequestAppRestart("restart"),)),
    )


def test_atomic_write_failure_preserves_the_original_document_and_clears_active_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "alas.json"
    _write(path, _document())
    original = path.read_bytes()
    repository = _repository(path)

    def fail_write(_target: Path, _content: str) -> None:
        message = "disk full"
        raise OSError(message)

    monkeypatch.setattr(config_repository, "atomic_write", fail_write)
    _begin(repository)

    with pytest.raises(OSError, match="disk full"):
        repository.finalize_run(
            TaskResult(
                outcome=Succeeded(),
                effects=(RescheduleSelf(datetime(2026, 7, 16, 1, 0, tzinfo=UTC)),),
                state_effects=(UpsertTaskState("main", "progress", 1, {"wave": 1}),),
            ),
        )

    assert path.read_bytes() == original
    # 写失败后允许同一调试进程再次启动任务，不把 repository 永久卡死。
    _begin(repository)


def test_legacy_update_write_failure_keeps_owner_snapshot_and_disk_unchanged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "alas.json"
    _write(path, _document())
    repository = _repository(path)
    original_bytes = path.read_bytes()
    original_runtime = repository.runtime_document()

    def fail_write(_target: Path, _content: str) -> None:
        message = "disk full"
        raise OSError(message)

    monkeypatch.setattr(config_repository, "atomic_write", fail_write)

    with pytest.raises(OSError, match="disk full"):
        repository.apply_runtime_updates({"Research.Scheduler.Enable": False})

    assert path.read_bytes() == original_bytes
    assert repository.runtime_document() == original_runtime


def test_repository_rejects_an_invalid_full_document_at_startup_without_writing(tmp_path: Path) -> None:
    path = tmp_path / "alas.json"
    document = _document()
    document["LegacyTask"] = {}
    _write(path, document)
    original = path.read_bytes()
    with pytest.raises(ConfigStateError, match="current configuration contract"):
        _repository(path)

    assert path.read_bytes() == original


def test_task_state_hydrates_a_deeply_read_only_checkpoint(tmp_path: Path) -> None:
    path = tmp_path / "alas.json"
    _write(path, _document())
    repository = _repository(path)
    _begin(repository)
    repository.finalize_run(
        TaskResult(
            outcome=Succeeded(),
            state_effects=(UpsertTaskState("main", "progress", 4, {"waves": [1, 2], "done": False}),),
        ),
    )

    state = repository.task_state(TaskId("main"))
    checkpoint = state.get("progress")

    assert checkpoint is not None
    assert checkpoint.schema_version == 4
    assert checkpoint.updated_at == _NOW
    assert checkpoint.payload == {"waves": (1, 2), "done": False}
    with pytest.raises(TypeError):
        cast("dict[str, object]", checkpoint.payload)["done"] = True


@pytest.mark.parametrize(
    ("checkpoint", "message"),
    [
        ({"schema_version": 1, "payload": {}, "updated_at": "2026-07-15 08:00:00"}, "timezone-aware"),
        (
            {"schema_version": 1, "payload": {}, "updated_at": "2026-07-15T08:00:00Z", "extra": True},
            "fields mismatch",
        ),
    ],
)
def test_task_state_rejects_corrupt_checkpoint_documents(
    tmp_path: Path,
    checkpoint: dict[str, object],
    message: str,
) -> None:
    path = tmp_path / "alas.json"
    document = _document()
    _storage(document, "main")["progress"] = checkpoint
    _write(path, document)

    with pytest.raises(ConfigStateError, match=message):
        _repository(path).task_state(TaskId("main"))


def test_foreign_checkpoint_namespace_fails_without_writing(tmp_path: Path) -> None:
    path = tmp_path / "alas.json"
    _write(path, _document())
    original = path.read_bytes()
    repository = _repository(path)

    _begin(repository)
    with pytest.raises(ConfigStateError, match="another task state namespace"):
        repository.finalize_run(
            TaskResult(
                outcome=Succeeded(),
                state_effects=(UpsertTaskState("research", "progress", 1, {}),),
            ),
        )

    assert path.read_bytes() == original
