from dataclasses import dataclass
from typing import override

import pytest

from module.application import Succeeded, Task, TaskContext, TaskResult
from module.runtime import ConfiguredTaskFactory, TaskBuildContext, TaskStateDocument, require_task_settings
from module.task_registry import TASK_SPECS


@dataclass(frozen=True, slots=True)
class _Settings:
    value: int


class _Task(Task):
    def __init__(self, settings: _Settings) -> None:
        self.settings = settings

    @override
    def run(self, context: TaskContext) -> TaskResult:
        del context
        return TaskResult(outcome=Succeeded())


def _context(settings: object) -> TaskBuildContext:
    return TaskBuildContext(
        spec=TASK_SPECS["restart"],
        settings_revision=1,
        content_revision="content:1",
        settings=settings,
        task_state=TaskStateDocument.empty("restart"),
    )


def test_configured_task_factory_passes_existing_typed_settings_without_decoding() -> None:
    settings = _Settings(3)
    factory = ConfiguredTaskFactory(_Settings, _Task)

    task = factory.build(_context(settings))

    assert isinstance(task, _Task)
    assert task.settings is settings


def test_require_task_settings_reports_command_and_expected_type() -> None:
    with pytest.raises(TypeError, match="restart settings must be _Settings"):
        require_task_settings(_context(object()), _Settings)
