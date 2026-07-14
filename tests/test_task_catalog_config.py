from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest

from module.application import ExecutionMode
from module.base.filter import Filter
from module.config.config import AzurLaneConfig, Function
from module.config.config_generated import GeneratedConfig
from module.config.config_manual import ManualConfig
from module.config.config_updater import ConfigGenerator
from module.config.utils import LANGUAGES, filepath_args, filepath_i18n, read_file, write_file
from module.task_registry import (
    SCHEDULER_LAUNCHES,
    TASK_CATALOG,
    TOOL_LAUNCHES,
    LaunchSurface,
    TaskDefinition,
    TaskDomain,
    command_to_config_name,
    get_task_definition,
    get_tool_task_command,
)

if TYPE_CHECKING:
    from module.config.deep import MutableDeepValue

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
> EventSp > EventA > EventB > EventC > EventD
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

TOOL_LAUNCH_COMMANDS = {
    "daemon",
    "opsi_daemon",
    "event_story",
    "azur_lane_uncensored",
    "benchmark",
    "game_manager",
}

INTERNAL_SCHEDULED_COMMANDS: set[str] = set()

EXPECTED_CATALOG_COMMANDS = {
    "awaken",
    "azur_lane_uncensored",
    "benchmark",
    "coalition",
    "coalition_sp",
    "commission",
    "daemon",
    "daily",
    "dorm",
    "event",
    "event2",
    "event_a",
    "event_b",
    "event_c",
    "event_d",
    "event_sp",
    "event_story",
    "exercise",
    "freebies",
    "gacha",
    "game_manager",
    "gems_farming",
    "guild",
    "hard",
    "hospital",
    "main",
    "main2",
    "main3",
    "maritime_escort",
    "meowfficer",
    "minigame",
    "opsi_abyssal",
    "opsi_archive",
    "opsi_ash_assist",
    "opsi_ash_beacon",
    "opsi_cross_month",
    "opsi_daemon",
    "opsi_daily",
    "opsi_explore",
    "opsi_hazard1_leveling",
    "opsi_meowfficer_farming",
    "opsi_month_boss",
    "opsi_obscure",
    "opsi_shop",
    "opsi_stronghold",
    "opsi_voucher",
    "private_quarters",
    "raid",
    "raid_daily",
    "research",
    "restart",
    "reward",
    "shipyard",
    "shop_frequent",
    "shop_once",
    "tactical",
    "war_archives",
}

EXPECTED_DOMAIN_COMMANDS = {
    TaskDomain.CAMPAIGN: {
        "main",
        "main2",
        "main3",
        "event",
        "event2",
        "war_archives",
        "gems_farming",
        "hard",
        "event_sp",
        "event_a",
        "event_b",
        "event_c",
        "event_d",
    },
    TaskDomain.ENCOUNTER: {
        "daily",
        "raid",
        "raid_daily",
        "coalition",
        "coalition_sp",
        "maritime_escort",
        "hospital",
    },
    TaskDomain.EXERCISE: {"exercise"},
    TaskDomain.OPSI: {
        "opsi_ash_assist",
        "opsi_ash_beacon",
        "opsi_explore",
        "opsi_shop",
        "opsi_voucher",
        "opsi_daily",
        "opsi_obscure",
        "opsi_month_boss",
        "opsi_abyssal",
        "opsi_archive",
        "opsi_stronghold",
        "opsi_meowfficer_farming",
        "opsi_hazard1_leveling",
        "opsi_cross_month",
    },
    TaskDomain.FACILITY: {"research", "commission", "tactical"},
    TaskDomain.MARKET: {"shop_frequent", "shop_once", "shipyard", "gacha", "awaken"},
    TaskDomain.COMPOSITE_DAILY: {"dorm", "meowfficer", "guild", "reward", "freebies", "private_quarters"},
    TaskDomain.ACTIVITY: {"minigame", "event_story"},
    TaskDomain.ASSIST: {"daemon", "opsi_daemon"},
    TaskDomain.MAINTENANCE: {"restart", "azur_lane_uncensored", "game_manager", "benchmark"},
}

EXPECTED_EXECUTION_COMMANDS = {
    ExecutionMode.SCHEDULED_JOB: EXPECTED_CATALOG_COMMANDS
    - {"daemon", "opsi_daemon", "event_story", "azur_lane_uncensored", "game_manager", "benchmark"},
    ExecutionMode.ASSIST_SESSION: {"daemon", "opsi_daemon"},
    ExecutionMode.DIRECT_COMMAND: {"event_story", "azur_lane_uncensored", "game_manager", "benchmark"},
}

SCOPE_ONLY_NODES = {"Alas", "General", "EventGeneral", "OpsiGeneral"}


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


def _task_nodes() -> list[tuple[str, str, dict[str, MutableDeepValue]]]:
    raw = read_file("module/config/argument/task.yaml")
    nodes: list[tuple[str, str, dict[str, MutableDeepValue]]] = []
    for task_group, group_value in raw.items():
        group_data = _deep_dict(group_value)
        tasks = _deep_dict(group_data.get("tasks", {}))
        for task_name, node_value in tasks.items():
            nodes.append((task_group, task_name, _deep_dict(node_value)))
    return nodes


def _legacy_priority_order() -> list[str]:
    names = [command_to_config_name(command) for command in TASK_CATALOG]
    functions = []
    for name in names:
        function = Function({})
        function.command = name
        functions.append(function)
    priority_filter = Filter(regex=r"(.*)", attr=["command"])
    priority_filter.load(LEGACY_SCHEDULER_PRIORITY)
    prioritized = priority_filter.apply(functions)
    assert all(isinstance(function, Function) for function in prioritized)
    return [function.command for function in prioritized if isinstance(function, Function)]


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


def _schema_generator(task: dict, *argument_groups: str) -> ConfigGenerator:
    generator = object.__new__(ConfigGenerator)
    generator.task = task
    generator.argument = {group: {} for group in (*argument_groups, "Storage")}
    generator.default = {}
    generator.override = {}
    return generator


def _task_group(nodes: dict, *, page: str = "setting") -> dict:
    return {
        "Section": {
            "menu": "collapse",
            "page": page,
            "tasks": nodes,
        }
    }


def test_task_definition_is_frozen_slotted_and_compatibility_is_derived() -> None:
    definition = TASK_CATALOG["main"]

    assert isinstance(definition, TaskDefinition)
    assert get_task_definition("main") is definition
    assert get_task_definition("missing") is None
    assert not hasattr(definition, "__dict__")
    assert not hasattr(definition, "executor")
    assert not hasattr(definition, "execute")
    with pytest.raises(FrozenInstanceError):
        definition.priority = 999  # type: ignore[misc]


def test_sos_is_removed_without_changing_other_commands() -> None:
    assert set(TASK_CATALOG) == EXPECTED_CATALOG_COMMANDS
    assert get_task_definition("sos") is None
    assert all(task_name != "Sos" for _group, task_name, _node in _task_nodes())
    assert "Sos" not in ConfigGenerator().argument
    assert not hasattr(GeneratedConfig, "Sos_Chapter")
    for lang in LANGUAGES:
        assert "Sos" not in read_file(filepath_i18n(lang))


@pytest.mark.parametrize(
    "command",
    ["bad space", "bad-name", "bad.name", "123", "_main", "main_", "main__two", "Main"],
)
def test_task_definition_rejects_non_ascii_snake_case_commands(command: str) -> None:
    with pytest.raises(ValueError, match="invalid task command"):
        TaskDefinition(
            command=command,
            config_scopes=(),
            priority=0,
            domain=TaskDomain.MAINTENANCE,
            execution_mode=ExecutionMode.SCHEDULED_JOB,
            allowed_launches=SCHEDULER_LAUNCHES,
        )


@pytest.mark.parametrize(
    "config_scopes",
    [["General"], ("",), ("General", "General"), ("General", 1)],
)
def test_task_definition_rejects_invalid_config_scopes(config_scopes: object) -> None:
    with pytest.raises((TypeError, ValueError), match="config scopes"):
        TaskDefinition(
            command="main",
            config_scopes=cast("tuple[str, ...]", config_scopes),
            priority=0,
            domain=TaskDomain.CAMPAIGN,
            execution_mode=ExecutionMode.SCHEDULED_JOB,
            allowed_launches=SCHEDULER_LAUNCHES,
        )


@pytest.mark.parametrize(
    ("priority", "error"),
    [(True, TypeError), (1.0, TypeError), ("1", TypeError), (-1, ValueError)],
)
def test_task_definition_rejects_invalid_priority(priority: object, error: type[Exception]) -> None:
    with pytest.raises(error, match="task priority"):
        TaskDefinition(
            command="main",
            config_scopes=(),
            priority=cast("int | None", priority),
            domain=TaskDomain.CAMPAIGN,
            execution_mode=ExecutionMode.SCHEDULED_JOB,
            allowed_launches=SCHEDULER_LAUNCHES,
        )


def test_task_definition_rejects_untyped_domain() -> None:
    with pytest.raises(TypeError, match="task domain"):
        TaskDefinition(
            command="main",
            config_scopes=(),
            priority=0,
            domain=cast("TaskDomain", "campaign"),
            execution_mode=ExecutionMode.SCHEDULED_JOB,
            allowed_launches=SCHEDULER_LAUNCHES,
        )


def test_task_definition_rejects_untyped_execution_mode() -> None:
    with pytest.raises(TypeError, match="execution mode"):
        TaskDefinition(
            command="main",
            config_scopes=(),
            priority=0,
            domain=TaskDomain.CAMPAIGN,
            execution_mode=cast("ExecutionMode", "scheduled_job"),
            allowed_launches=SCHEDULER_LAUNCHES,
        )


@pytest.mark.parametrize(
    ("allowed_launches", "error"),
    [
        ({LaunchSurface.SCHEDULER}, TypeError),
        (frozenset(), ValueError),
        (frozenset({"scheduler"}), TypeError),
    ],
)
def test_task_definition_rejects_invalid_allowed_launches(allowed_launches: object, error: type[Exception]) -> None:
    with pytest.raises(error, match="allowed launches"):
        TaskDefinition(
            command="main",
            config_scopes=(),
            priority=0,
            domain=TaskDomain.CAMPAIGN,
            execution_mode=ExecutionMode.SCHEDULED_JOB,
            allowed_launches=cast("frozenset[LaunchSurface]", allowed_launches),
        )


def test_task_yaml_commands_are_unique_catalog_entries_with_matching_modes() -> None:
    command_nodes: dict[str, tuple[str, str, tuple[str, ...]]] = {}
    scope_nodes = set()

    for task_group, task_name, node in _task_nodes():
        assert set(node) <= {"command", "groups"}
        groups = tuple(_deep_string_list(node.get("groups", [])))
        command_value = node.get("command")
        if command_value is None:
            scope_nodes.add(task_name)
            continue
        command = _deep_string(command_value)

        assert command not in command_nodes
        assert command in TASK_CATALOG
        assert command_to_config_name(command) == task_name
        command_nodes[command] = (task_group, task_name, groups)
        allowed_launches = TASK_CATALOG[command].allowed_launches
        if "Scheduler" in groups:
            assert LaunchSurface.SCHEDULER in allowed_launches
        else:
            assert task_group == "Tool"
            assert LaunchSurface.TOOL in allowed_launches

    assert scope_nodes == SCOPE_ONLY_NODES
    assert set(TASK_CATALOG) - set(command_nodes) == INTERNAL_SCHEDULED_COMMANDS
    assert set(command_nodes) - set(TASK_CATALOG) == set()


def test_task_catalog_scopes_and_allowed_launches_are_complete() -> None:
    assert {
        command: definition.config_scopes for command, definition in TASK_CATALOG.items() if definition.config_scopes
    } == EXPECTED_SCOPES
    assert {
        command for command, definition in TASK_CATALOG.items() if definition.allowed_launches == TOOL_LAUNCHES
    } == TOOL_LAUNCH_COMMANDS
    assert all(
        definition.allowed_launches == SCHEDULER_LAUNCHES
        for command, definition in TASK_CATALOG.items()
        if command not in TOOL_LAUNCH_COMMANDS
    )


def test_task_catalog_domains_are_exact_and_complete() -> None:
    classified_commands = [command for commands in EXPECTED_DOMAIN_COMMANDS.values() for command in commands]

    assert set(EXPECTED_DOMAIN_COMMANDS) == set(TaskDomain)
    assert set(classified_commands) == EXPECTED_CATALOG_COMMANDS
    assert len(classified_commands) == len(set(classified_commands))
    assert {command: definition.domain for command, definition in TASK_CATALOG.items()} == {
        command: domain for domain, commands in EXPECTED_DOMAIN_COMMANDS.items() for command in commands
    }


def test_task_catalog_execution_modes_are_exact_and_complete() -> None:
    classified_commands = [command for commands in EXPECTED_EXECUTION_COMMANDS.values() for command in commands]

    assert set(EXPECTED_EXECUTION_COMMANDS) == set(ExecutionMode)
    assert set(classified_commands) == EXPECTED_CATALOG_COMMANDS
    assert len(classified_commands) == len(set(classified_commands))
    assert {command: definition.execution_mode for command, definition in TASK_CATALOG.items()} == {
        command: mode for mode, commands in EXPECTED_EXECUTION_COMMANDS.items() for command in commands
    }


def test_launch_surface_and_execution_mode_are_orthogonal() -> None:
    assert TASK_CATALOG["daemon"].allowed_launches == TASK_CATALOG["benchmark"].allowed_launches == TOOL_LAUNCHES
    assert TASK_CATALOG["daemon"].execution_mode is ExecutionMode.ASSIST_SESSION
    assert TASK_CATALOG["benchmark"].execution_mode is ExecutionMode.DIRECT_COMMAND
    assert TASK_CATALOG["restart"].execution_mode is ExecutionMode.SCHEDULED_JOB
    assert all(isinstance(definition.allowed_launches, frozenset) for definition in TASK_CATALOG.values())


@pytest.mark.parametrize(
    ("task_name", "command"),
    [(task_name, _deep_string(node["command"])) for _group, task_name, node in _task_nodes() if "command" in node],
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
        if "command" in node and "Scheduler" in _deep_string_list(node["groups"]):
            task_args = _deep_dict(args[task_name])
            scheduler = _deep_dict(task_args["Scheduler"])
            command = _deep_dict(scheduler["Command"])
            assert command["value"] == task_name


def test_config_generator_rejects_unknown_and_duplicate_commands() -> None:
    unknown = object.__new__(ConfigGenerator)
    unknown.task = {
        "Tool": {"tasks": {"Missing": {"command": "missing", "groups": []}}},
    }
    with pytest.raises(ValueError, match="unknown task command"):
        _ = unknown.menu

    duplicate = object.__new__(ConfigGenerator)
    duplicate.task = {
        "One": {"tasks": {"Main": {"command": "main", "groups": ["Scheduler"]}}},
        "Two": {"tasks": {"Main": {"command": "main", "groups": ["Scheduler"]}}},
    }
    with pytest.raises(ValueError, match="duplicate task command"):
        _ = duplicate.menu


@pytest.mark.parametrize(
    ("task", "page", "message"),
    [
        ({"Ghost": {"groups": ["Scheduler"]}}, "setting", "scope-only task"),
        ({"General": {"groups": ["Scheduler"]}}, "setting", "scope-only task.*Scheduler"),
        ({"General": {"groups": ["Emulator"]}}, "tool", "scope-only task.*tool"),
        (
            {"Benchmark": {"command": "benchmark", "groups": ["Scheduler"]}},
            "setting",
            "allowed launches",
        ),
        ({"Main": {"command": "main", "groups": []}}, "tool", "allowed launches"),
        (
            {"Main": {"command": "main", "groups": ["Campaign"]}},
            "setting",
            "must be scheduled or tool",
        ),
    ],
)
def test_config_generator_rejects_invalid_task_placement(task: dict, page: str, message: str) -> None:
    generator = _schema_generator(
        _task_group(task, page=page),
        "Scheduler",
        "Emulator",
        "Campaign",
    )

    with pytest.raises(ValueError, match=message):
        _ = generator.menu


def test_config_generator_rejects_duplicate_task_name_across_groups() -> None:
    generator = _schema_generator(
        {
            "One": {"page": "setting", "tasks": {"General": {"groups": ["Emulator"]}}},
            "Two": {"page": "setting", "tasks": {"General": {"groups": ["Emulator"]}}},
        },
        "Emulator",
    )

    with pytest.raises(ValueError, match="duplicate task name"):
        _ = generator.menu


@pytest.mark.parametrize(
    ("groups", "message"),
    [
        ([""], "non-empty strings"),
        (["Scheduler", "Scheduler"], "duplicate task group"),
        (["Schedulre"], "unknown task group"),
        (["Storage"], "must not declare Storage"),
    ],
)
def test_config_generator_rejects_invalid_argument_groups(groups: list[str], message: str) -> None:
    generator = _schema_generator(
        _task_group({"Main": {"command": "main", "groups": groups}}),
        "Scheduler",
    )

    with pytest.raises((TypeError, ValueError), match=message):
        _ = generator.args


def test_priority_matches_legacy_filter_first_match_order() -> None:
    legacy_order = _legacy_priority_order()
    prioritized = sorted(
        (definition for definition in TASK_CATALOG.values() if definition.priority is not None),
        key=lambda definition: definition.priority,
    )

    assert [definition.priority for definition in prioritized] == list(range(51))
    assert [command_to_config_name(definition.command) for definition in prioritized] == legacy_order
    assert legacy_order.count("OpsiAshBeacon") == 1

    derived_filter = Filter(regex=r"(.*)", attr=["command"])
    derived_filter.load(ManualConfig.SCHEDULER_PRIORITY)
    functions = []
    for name in legacy_order:
        function = Function({})
        function.command = name
        functions.append(function)
    filtered = derived_filter.apply(functions)
    assert all(isinstance(function, Function) for function in filtered)
    assert [function.command for function in filtered if isinstance(function, Function)] == legacy_order


def test_only_tool_commands_resolve_for_webui_launch() -> None:
    assert {
        command_to_config_name(command): get_tool_task_command(command_to_config_name(command))
        for command in TOOL_LAUNCH_COMMANDS
    } == {command_to_config_name(command): command for command in TOOL_LAUNCH_COMMANDS}
    assert get_tool_task_command("Main") is None
    assert get_tool_task_command("Missing") is None


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
