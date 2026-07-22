from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType
from typing import cast, override

import pytest

from module.application import ExecutionMode, Succeeded, Task, TaskContext, TaskResult
from module.runtime import (
    FrozenJsonValue,
    SettingsDecoder,
    SettingsDocumentError,
    TaskBuildContext,
    TaskStateDocument,
    TypedTaskFactory,
)
from module.task_registry import ContentRevisionPolicy, TaskDomain, TaskSpec


class _Mode(StrEnum):
    SAFE = "safe"
    FAST = "fast"


@dataclass(frozen=True, slots=True)
class _Settings:
    enabled: bool
    retries: int
    threshold: float
    name: str
    labels: tuple[str, ...]
    weights: tuple[int, ...]
    due_at: datetime
    mode: _Mode
    nested_value: str


class _Task(Task):
    def __init__(self, settings: _Settings) -> None:
        self.settings = settings

    @override
    def run(self, context: TaskContext) -> TaskResult:
        del context
        return TaskResult(Succeeded())


def _context(settings: dict[str, FrozenJsonValue]) -> TaskBuildContext:
    spec = TaskSpec(
        command="restart",
        config_scopes=(),
        priority=0,
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        domain=TaskDomain.MAINTENANCE,
        content_revision_policy=ContentRevisionPolicy.BUILTIN,
    )
    return TaskBuildContext(
        spec=spec,
        settings_revision=3,
        content_revision="content-1",
        settings=MappingProxyType(settings),
        task_state=TaskStateDocument.empty("restart"),
    )


def _decode(decoder: SettingsDecoder) -> _Settings:
    nested = decoder.object("nested")
    nested_value = nested.string("value")
    nested.finish()
    return _Settings(
        enabled=decoder.boolean("enabled"),
        retries=decoder.integer("retries", minimum=0, maximum=10),
        threshold=decoder.number("threshold", minimum=0.0, maximum=1.0),
        name=decoder.string("name"),
        labels=decoder.string_tuple("labels", allow_empty=False),
        weights=decoder.integer_tuple("weights", length=3, minimum=1),
        due_at=decoder.datetime("due_at"),
        mode=decoder.enum("mode", _Mode),
        nested_value=nested_value,
    )


def _valid_settings() -> dict[str, FrozenJsonValue]:
    return {
        "enabled": True,
        "retries": 2,
        "threshold": 0.75,
        "name": "primary",
        "labels": ("one", "two"),
        "weights": (1_000, 900, 800),
        "due_at": "2026-07-13T16:00:00+08:00",
        "mode": "safe",
        "nested": MappingProxyType({"value": "nested"}),
    }


def test_typed_factory_decodes_all_fields_and_normalizes_datetime() -> None:
    factory = TypedTaskFactory(_decode, _Task)

    task = cast("_Task", factory.build(_context(_valid_settings())))

    assert task.settings == _Settings(
        enabled=True,
        retries=2,
        threshold=0.75,
        name="primary",
        labels=("one", "two"),
        weights=(1_000, 900, 800),
        due_at=datetime(2026, 7, 13, 8, tzinfo=UTC),
        mode=_Mode.SAFE,
        nested_value="nested",
    )


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("enabled", 1, "must be a boolean"),
        ("retries", -1, "at least 0"),
        ("threshold", 1, "must be a float"),
        ("name", " padded ", "trimmed non-empty"),
        ("labels", (), "must not be empty"),
        ("weights", (1_000, 900), "exactly 3"),
        ("weights", (1_000, 0, 800), "at least 1"),
        ("weights", (1_000, "900", 800), "must be an integer"),
        ("due_at", "2026-07-13T08:00:00", "timezone-aware"),
        ("mode", "removed", "must be one of"),
    ],
)
def test_decoder_rejects_invalid_typed_fields(field: str, value: FrozenJsonValue, match: str) -> None:
    settings = _valid_settings()
    settings[field] = value

    with pytest.raises(SettingsDocumentError, match=match):
        TypedTaskFactory(_decode, _Task).build(_context(settings))


def test_decoder_rejects_missing_unknown_and_double_consumption() -> None:
    missing = _valid_settings()
    del missing["name"]
    with pytest.raises(SettingsDocumentError, match="missing required setting"):
        TypedTaskFactory(_decode, _Task).build(_context(missing))

    unknown = _valid_settings()
    unknown["obsolete"] = True
    with pytest.raises(SettingsDocumentError, match="unknown settings"):
        TypedTaskFactory(_decode, _Task).build(_context(unknown))

    decoder = SettingsDecoder(MappingProxyType({"name": "value"}), path="$.task")
    assert decoder.string("name") == "value"
    with pytest.raises(RuntimeError, match="decoded more than once"):
        decoder.string("name")


def test_typed_factory_rejects_invalid_task_builder_result() -> None:
    def invalid_builder(settings: _Settings) -> Task:
        del settings
        return cast("Task", object())

    with pytest.raises(TypeError, match="must return a Task"):
        TypedTaskFactory(_decode, invalid_builder).build(_context(_valid_settings()))
