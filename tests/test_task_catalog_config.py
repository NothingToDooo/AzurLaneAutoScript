import importlib
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import SimpleNamespace

import pytest

from alas import AzurLaneAutoScript
from module.base.filter import Filter
from module.config.config import AzurLaneConfig, Function
from module.config.config_manual import ManualConfig
from module.config.config_updater import ConfigGenerator
from module.config.utils import LANGUAGES, filepath_args, filepath_i18n, read_file, write_file
from module.daemon import benchmark as benchmark_module
from module.task_registry import (
    TASK_CATALOG,
    TASK_REGISTRY,
    ClassTaskExecutor,
    FunctionTaskExecutor,
    RunnerMethodExecutor,
    TaskDefinition,
    TaskSpec,
    command_to_config_name,
    get_direct_task_command,
    get_task_spec,
)

LEGACY_SCHEDULER_PRIORITY = """
Restart
> OpsiCrossMonth
> Commission > Tactical > Research
> Exercise
> Dorm > Meowfficer > Guild > Gacha
> Reward
> ShopFrequent > ShopOnce > Shipyard > Freebies
> PrivateQuarters
> OpsiExplore
> Minigame > Awaken
> OpsiAshBeacon
> OpsiDaily > OpsiShop > OpsiVoucher
> OpsiAbyssal > OpsiStronghold > OpsiObscure > OpsiArchive
> Daily > Hard > OpsiAshBeacon > OpsiAshAssist > OpsiMonthBoss
> Sos > EventSp > EventA > EventB > EventC > EventD
> RaidDaily > CoalitionSp > WarArchives > MaritimeEscort
> Event > Event2 > Raid > Hospital > Coalition > Main > Main2 > Main3
> OpsiMeowfficerFarming
> GemsFarming
> OpsiHazard1Leveling
"""

EXPECTED_SCOPES = {
    "event": ("TaskBalancer", "EventGeneral"),
    "event2": ("TaskBalancer", "EventGeneral"),
    "event_a": ("TaskBalancer", "EventGeneral"),
    "event_b": ("TaskBalancer", "EventGeneral"),
    "event_c": ("TaskBalancer", "EventGeneral"),
    "event_d": ("TaskBalancer", "EventGeneral"),
    "event_sp": ("TaskBalancer", "EventGeneral"),
    "event_story": ("TaskBalancer", "EventGeneral"),
    "raid": ("TaskBalancer", "EventGeneral"),
    "raid_daily": ("TaskBalancer", "EventGeneral"),
    "coalition": ("TaskBalancer", "EventGeneral"),
    "coalition_sp": ("TaskBalancer", "EventGeneral"),
    "maritime_escort": ("TaskBalancer", "EventGeneral"),
    "gems_farming": ("TaskBalancer", "EventGeneral"),
    "opsi_ash_assist": ("OpsiGeneral",),
    "opsi_ash_beacon": ("OpsiGeneral",),
    "opsi_explore": ("OpsiGeneral",),
    "opsi_shop": ("OpsiGeneral",),
    "opsi_voucher": ("OpsiGeneral",),
    "opsi_daily": ("OpsiGeneral",),
    "opsi_obscure": ("OpsiGeneral",),
    "opsi_month_boss": ("OpsiGeneral",),
    "opsi_abyssal": ("OpsiGeneral",),
    "opsi_archive": ("OpsiGeneral",),
    "opsi_stronghold": ("OpsiGeneral",),
    "opsi_meowfficer_farming": ("OpsiGeneral",),
    "opsi_hazard1_leveling": ("OpsiGeneral",),
    "opsi_cross_month": ("OpsiGeneral",),
    "opsi_daemon": ("OpsiGeneral",),
}

DIRECT_COMMANDS = {
    "daemon",
    "opsi_daemon",
    "event_story",
    "azur_lane_uncensored",
    "benchmark",
    "game_manager",
}

INTERNAL_SCHEDULED_COMMANDS = {
    "sos",
    "c72_mystery_farming",
    "c122_medium_leveling",
    "c124_large_leveling",
}

SCOPE_ONLY_NODES = {"Alas", "General", "EventGeneral", "OpsiGeneral"}


def _task_nodes() -> list[tuple[str, str, dict]]:
    raw = read_file("module/config/argument/task.yaml")
    return [
        (task_group, task_name, node)
        for task_group, group_data in raw.items()
        for task_name, node in group_data.get("tasks", {}).items()
    ]


def _legacy_priority_order() -> list[str]:
    names = [command_to_config_name(command) for command in TASK_CATALOG]
    functions = []
    for name in names:
        function = Function({})
        function.command = name
        functions.append(function)
    priority_filter = Filter(regex=r"(.*)", attr=["command"])
    priority_filter.load(LEGACY_SCHEDULER_PRIORITY)
    return [function.command for function in priority_filter.apply(functions)]


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


def test_task_definition_is_frozen_slotted_and_compatibility_is_derived() -> None:
    definition = TASK_CATALOG["main"]

    assert isinstance(definition, TaskDefinition)
    assert TaskSpec is TaskDefinition
    assert TASK_REGISTRY is TASK_CATALOG
    assert get_task_spec("main") is definition
    assert get_task_spec("missing") is None
    assert not hasattr(definition, "__dict__")
    with pytest.raises(FrozenInstanceError):
        definition.priority = 999  # type: ignore[misc]


def test_task_yaml_commands_are_unique_catalog_entries_with_matching_modes() -> None:
    command_nodes: dict[str, tuple[str, str, tuple[str, ...]]] = {}
    scope_nodes = set()

    for task_group, task_name, node in _task_nodes():
        assert isinstance(node, dict)
        assert set(node) <= {"command", "groups"}
        assert isinstance(node.get("groups"), list)
        command = node.get("command")
        if command is None:
            scope_nodes.add(task_name)
            continue

        assert command not in command_nodes
        assert command in TASK_CATALOG
        assert command_to_config_name(command) == task_name
        groups = tuple(node["groups"])
        command_nodes[command] = (task_group, task_name, groups)
        launch_mode = TASK_CATALOG[command].launch_mode
        if "Scheduler" in groups:
            assert launch_mode in {"scheduled", "both"}
        else:
            assert task_group == "Tool"
            assert launch_mode in {"direct", "both"}

    assert scope_nodes == SCOPE_ONLY_NODES
    assert set(TASK_CATALOG) - set(command_nodes) == INTERNAL_SCHEDULED_COMMANDS
    assert set(command_nodes) - set(TASK_CATALOG) == set()


def test_task_catalog_scopes_and_launch_modes_are_complete() -> None:
    assert {
        command: definition.config_scopes for command, definition in TASK_CATALOG.items() if definition.config_scopes
    } == EXPECTED_SCOPES
    assert {
        command for command, definition in TASK_CATALOG.items() if definition.launch_mode == "direct"
    } == DIRECT_COMMANDS
    assert not any(definition.launch_mode == "both" for definition in TASK_CATALOG.values())
    assert all(
        definition.launch_mode == "scheduled"
        for command, definition in TASK_CATALOG.items()
        if command not in DIRECT_COMMANDS
    )


@pytest.mark.parametrize(
    ("task_name", "command"),
    [(task_name, node["command"]) for _group, task_name, node in _task_nodes() if "command" in node],
)
def test_all_config_commands_keep_legacy_bind_chain(task_name: str, command: str) -> None:
    extra_scope = "CallerScope"

    assert AzurLaneConfig.task_bind_chain(task_name, [extra_scope]) == [
        "General",
        "Alas",
        *EXPECTED_SCOPES.get(command, ()),
        task_name,
        extra_scope,
    ]


def test_task_yaml_scheduler_command_remains_pascal_case_node_name() -> None:
    args = ConfigGenerator().args

    for _task_group, task_name, node in _task_nodes():
        if "command" in node and "Scheduler" in node["groups"]:
            assert args[task_name]["Scheduler"]["Command"]["value"] == task_name


def test_config_generator_rejects_unknown_and_duplicate_commands() -> None:
    unknown = object.__new__(ConfigGenerator)
    unknown.task = {
        "Tool": {"tasks": {"Missing": {"command": "missing", "groups": []}}},
    }
    with pytest.raises(ValueError, match="unknown task command"):
        _ = unknown.menu

    duplicate = object.__new__(ConfigGenerator)
    duplicate.task = {
        "One": {"tasks": {"Main": {"command": "main", "groups": []}}},
        "Two": {"tasks": {"Main": {"command": "main", "groups": []}}},
    }
    with pytest.raises(ValueError, match="duplicate task command"):
        _ = duplicate.menu


def test_priority_matches_legacy_filter_first_match_order() -> None:
    legacy_order = _legacy_priority_order()
    prioritized = sorted(
        (definition for definition in TASK_CATALOG.values() if definition.priority is not None),
        key=lambda definition: definition.priority,
    )

    assert [definition.priority for definition in prioritized] == list(range(52))
    assert [command_to_config_name(definition.command) for definition in prioritized] == legacy_order
    assert legacy_order.count("OpsiAshBeacon") == 1

    derived_filter = Filter(regex=r"(.*)", attr=["command"])
    derived_filter.load(ManualConfig.SCHEDULER_PRIORITY)
    functions = []
    for name in legacy_order:
        function = Function({})
        function.command = name
        functions.append(function)
    assert [function.command for function in derived_filter.apply(functions)] == legacy_order


def test_only_direct_commands_resolve_for_webui_launch() -> None:
    assert {
        command_to_config_name(command): get_direct_task_command(command_to_config_name(command))
        for command in DIRECT_COMMANDS
    } == {command_to_config_name(command): command for command in DIRECT_COMMANDS}
    assert get_direct_task_command("Main") is None
    assert get_direct_task_command("Missing") is None


def test_restart_uses_runner_method_without_importing_executor() -> None:
    calls: list[str] = []
    runner = SimpleNamespace(restart=lambda: calls.append("restart"))
    definition = TASK_CATALOG["restart"]

    assert isinstance(definition.executor, RunnerMethodExecutor)
    definition.execute(runner)

    assert calls == ["restart"]


def test_benchmark_keeps_function_execution_and_task_binding(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[object, str]] = []

    class _Benchmark:
        def __init__(self, config, task):
            calls.append((config, task))

        def run(self) -> None:
            calls.append(("run", "Benchmark"))

    monkeypatch.setattr(benchmark_module, "Benchmark", _Benchmark)
    config = SimpleNamespace()
    definition = TASK_CATALOG["benchmark"]

    assert isinstance(definition.executor, FunctionTaskExecutor)
    definition.execute(SimpleNamespace(config=config))

    assert calls == [(config, "Benchmark"), ("run", "Benchmark")]


def test_all_catalog_execution_targets_exist() -> None:
    for definition in TASK_CATALOG.values():
        executor = definition.executor
        if isinstance(executor, ClassTaskExecutor):
            module = importlib.import_module(executor.module_name)
            task_class = getattr(module, executor.class_name)
            assert callable(getattr(task_class, executor.method_name))
        elif isinstance(executor, FunctionTaskExecutor):
            module = importlib.import_module(executor.module_name)
            assert callable(getattr(module, executor.function_name))
        else:
            assert isinstance(executor, RunnerMethodExecutor)
            assert callable(getattr(AzurLaneAutoScript, executor.method_name))


def test_task_yaml_migration_keeps_generated_bytes_stable(tmp_path: Path) -> None:
    first = _render_generated_config_files(tmp_path / "first")
    second = _render_generated_config_files(tmp_path / "second")
    tracked = {
        "args": Path(filepath_args()).read_bytes(),
        "menu": Path(filepath_args("menu")).read_bytes(),
        **{lang: Path(filepath_i18n(lang)).read_bytes() for lang in LANGUAGES},
    }

    assert first == tracked
    assert second == first
