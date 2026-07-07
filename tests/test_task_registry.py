import importlib
from types import SimpleNamespace

import pytest

from module.task_registry import TASK_REGISTRY, FunctionTaskSpec


@pytest.mark.parametrize("command", sorted(TASK_REGISTRY))
def test_task_registry_target_exists(command: str) -> None:
    spec = TASK_REGISTRY[command]
    module = importlib.import_module(spec.module_name)
    if isinstance(spec, FunctionTaskSpec):
        assert callable(getattr(module, spec.function_name))
        return

    task_class = getattr(module, spec.class_name)

    assert callable(getattr(task_class, spec.method_name))


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
