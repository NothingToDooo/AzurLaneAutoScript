import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

from module.config.utils import filepath_argument, read_file
from module.task_registry import TASK_CATALOG

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


@pytest.mark.parametrize("task_name", sorted(_scheduler_task_names()))
def test_scheduler_task_name_maps_to_runtime_command(task_name: str) -> None:
    node = _task_node(task_name)
    assert _deep_string(node["command"]) in TASK_CATALOG


def test_catalog_import_does_not_load_production_device_graph() -> None:
    script = "import sys; import module.task_registry; assert 'module.device.device' not in sys.modules"
    subprocess.run([sys.executable, "-c", script], check=True)  # noqa: S603
