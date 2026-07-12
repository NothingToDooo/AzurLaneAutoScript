import importlib
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

from module.config.utils import filepath_argument, read_file
from module.task_registry import TASK_REGISTRY, ClassTaskExecutor

if TYPE_CHECKING:
    from module.config.deep import MutableDeepValue


def _deep_dict(value: MutableDeepValue) -> dict[str, MutableDeepValue]:
    assert isinstance(value, dict)
    return value


def _deep_string(value: MutableDeepValue) -> str:
    assert isinstance(value, str)
    return value


def _deep_string_list(value: MutableDeepValue) -> list[str]:
    assert isinstance(value, list)
    assert all(isinstance(item, str) for item in value)
    return [item for item in value if isinstance(item, str)]


def _scheduler_task_names() -> list[str]:
    raw = read_file(filepath_argument("task"))
    names: list[str] = []
    for task_group_value in raw.values():
        task_group = _deep_dict(task_group_value)
        tasks = _deep_dict(task_group.get("tasks", {}))
        for task_name, node_value in tasks.items():
            node = _deep_dict(node_value)
            if "Scheduler" in _deep_string_list(node["groups"]):
                names.append(task_name)
    return names


def _task_node(task_name: str) -> dict[str, MutableDeepValue]:
    raw = read_file(filepath_argument("task"))
    for task_group_value in raw.values():
        task_group = _deep_dict(task_group_value)
        tasks = _deep_dict(task_group.get("tasks", {}))
        for name, node_value in tasks.items():
            if name == task_name:
                return _deep_dict(node_value)
    raise KeyError(task_name)


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
    assert _deep_string(node["command"]) in TASK_REGISTRY


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
