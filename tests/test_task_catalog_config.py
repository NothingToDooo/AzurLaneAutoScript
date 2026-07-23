from pathlib import Path
from typing import TYPE_CHECKING

from module.application import ExecutionMode
from module.config.config_updater import ConfigGenerator
from module.config.utils import LANGUAGES, filepath_args, filepath_i18n, read_file, write_file
from module.task_registry import TASK_SPECS, get_task_by_config_name

if TYPE_CHECKING:
    from module.config.deep import MutableDeepValue


def _deep_dict(value: MutableDeepValue) -> dict[str, MutableDeepValue]:
    assert isinstance(value, dict)
    return value


def _deep_string_list(value: MutableDeepValue) -> list[str]:
    assert isinstance(value, list)
    assert all(isinstance(item, str) for item in value)
    return [item for item in value if isinstance(item, str)]


def _task_nodes() -> list[tuple[str, str, dict[str, MutableDeepValue]]]:
    raw = read_file("module/config/argument/task.yaml")
    nodes: list[tuple[str, str, dict[str, MutableDeepValue]]] = []
    for task_group, group_value in raw.items():
        group_data = _deep_dict(group_value)
        tasks = _deep_dict(group_data.get("tasks", {}))
        for task_name, node_value in tasks.items():
            nodes.append((task_group, task_name, _deep_dict(node_value)))
    return nodes


def _render_generated_config_files(folder: Path) -> dict[str, bytes]:
    folder.mkdir()
    generator = ConfigGenerator()
    _ = generator.args
    _ = generator.menu
    generator.insert_event()

    outputs: dict[str, bytes] = {}
    generated_files = {
        "args": (folder / "args.json", generator.args),
        "menu": (folder / "menu.json", generator.menu),
    }
    for name, (path, data) in generated_files.items():
        write_file(path.as_posix(), data)
        outputs[name] = path.read_bytes()

    for lang in LANGUAGES:
        path = folder / f"{lang}.json"
        old = read_file(filepath_i18n(lang))
        write_file(path.as_posix(), generator.generate_i18n_data(old))
        outputs[lang] = path.read_bytes()
    return outputs


def test_task_yaml_resolves_every_runtime_command_exactly_once() -> None:
    resolved: dict[str, str] = {}
    task_names: set[str] = set()

    for _task_group, task_name, _node in _task_nodes():
        assert task_name not in task_names
        task_names.add(task_name)
        spec = get_task_by_config_name(task_name)
        if spec is None:
            continue
        assert spec.command not in resolved
        resolved[spec.command] = task_name

    assert set(resolved) == set(TASK_SPECS)


def test_real_task_nodes_match_runtime_execution_and_priority_contract() -> None:
    for task_group, task_name, node in _task_nodes():
        spec = get_task_by_config_name(task_name)
        if spec is None:
            continue
        groups = _deep_string_list(node.get("groups", []))
        is_scheduled = "Scheduler" in groups

        assert (spec.execution_mode is ExecutionMode.SCHEDULED_JOB) is is_scheduled
        assert (spec.priority is not None) is is_scheduled
        if not is_scheduled:
            assert task_group == "Tool"


def test_task_yaml_generation_matches_tracked_outputs(tmp_path: Path) -> None:
    generated = _render_generated_config_files(tmp_path / "generated")
    tracked = {
        "args": Path(filepath_args()).read_bytes(),
        "menu": Path(filepath_args("menu")).read_bytes(),
        **{lang: Path(filepath_i18n(lang)).read_bytes() for lang in LANGUAGES},
    }

    assert generated == tracked
