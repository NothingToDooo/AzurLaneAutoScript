import importlib
from types import SimpleNamespace

import pytest

from alas import AzurLaneAutoScript
from module.base.naming import camel_to_snake
from module.config.utils import filepath_argument, read_file
from module.task_registry import TASK_REGISTRY, FunctionTaskSpec


def _scheduler_task_names() -> list[str]:
    raw = read_file(filepath_argument("task"))
    return [
        task_name
        for task_group in raw.values()
        for task_name, groups in task_group.get("tasks", {}).items()
        if "Scheduler" in groups
    ]


@pytest.mark.parametrize("command", sorted(TASK_REGISTRY))
def test_task_registry_target_exists(command: str) -> None:
    spec = TASK_REGISTRY[command]
    module = importlib.import_module(spec.module_name)
    if isinstance(spec, FunctionTaskSpec):
        assert callable(getattr(module, spec.function_name))
        return

    task_class = getattr(module, spec.class_name)

    assert callable(getattr(task_class, spec.method_name))


@pytest.mark.parametrize("task_name", sorted(_scheduler_task_names()))
def test_scheduler_task_name_maps_to_runtime_command(task_name: str) -> None:
    command = camel_to_snake(task_name)
    assert command in TASK_REGISTRY or callable(getattr(AzurLaneAutoScript, command, None))


def test_campaign_args_are_resolved_at_runtime() -> None:
    spec = TASK_REGISTRY["main"]
    runner = SimpleNamespace(
        config=SimpleNamespace(
            Campaign_Name="12-4",
            Campaign_Event="campaign_main",
            Campaign_Mode="normal",
        )
    )

    assert spec.args_factory is not None
    assert spec.args_factory(runner) == (
        (),
        {
            "name": "12-4",
            "folder": "campaign_main",
            "mode": "normal",
        },
    )
