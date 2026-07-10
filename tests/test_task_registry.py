import importlib
from types import SimpleNamespace

import pytest

from module.config.utils import filepath_argument, read_file
from module.task_registry import TASK_REGISTRY, ClassTaskExecutor


def _scheduler_task_names() -> list[str]:
    raw = read_file(filepath_argument("task"))
    return [
        task_name
        for task_group in raw.values()
        for task_name, node in task_group.get("tasks", {}).items()
        if "Scheduler" in node["groups"]
    ]


def _task_node(task_name: str) -> dict:
    raw = read_file(filepath_argument("task"))
    return next(
        node for task_group in raw.values() for name, node in task_group.get("tasks", {}).items() if name == task_name
    )


@pytest.mark.parametrize("command", sorted(TASK_REGISTRY))
def test_task_registry_target_exists(command: str) -> None:
    executor = TASK_REGISTRY[command].executor
    if not isinstance(executor, ClassTaskExecutor):
        return

    module = importlib.import_module(executor.module_name)
    task_class = getattr(module, executor.class_name)

    assert callable(getattr(task_class, executor.method_name))


@pytest.mark.parametrize("task_name", sorted(_scheduler_task_names()))
def test_scheduler_task_name_maps_to_runtime_command(task_name: str) -> None:
    node = _task_node(task_name)
    assert node["command"] in TASK_REGISTRY


def test_campaign_args_are_resolved_at_runtime() -> None:
    executor = TASK_REGISTRY["main"].executor
    assert isinstance(executor, ClassTaskExecutor)
    runner = SimpleNamespace(
        config=SimpleNamespace(
            Campaign_Name="12-4",
            Campaign_Event="campaign_main",
            Campaign_Mode="normal",
        )
    )

    assert executor.args_factory is not None
    assert executor.args_factory(runner) == (
        (),
        {
            "name": "12-4",
            "folder": "campaign_main",
            "mode": "normal",
        },
    )
