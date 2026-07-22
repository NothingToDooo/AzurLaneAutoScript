from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest

from module.application import ExecutionMode
from module.base.filter import Filter
from module.config.config import Function
from module.config.config_generated import GeneratedConfig
from module.config.config_manual import ManualConfig
from module.config.config_updater import ConfigGenerator
from module.config.resolved import task_bind_chain
from module.config.utils import LANGUAGES, filepath_args, filepath_i18n, read_file, write_file
from module.task_registry import (
    TASK_SPECS,
    ContentRevisionPolicy,
    TaskDomain,
    TaskSpec,
    command_to_config_name,
    get_task_by_config_name,
    get_task_spec,
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

NON_SCHEDULED_COMMANDS = {
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

EXPECTED_EXECUTION_COMMANDS = {
    ExecutionMode.SCHEDULED_JOB: EXPECTED_CATALOG_COMMANDS - NON_SCHEDULED_COMMANDS,
    ExecutionMode.ASSIST_SESSION: {"daemon", "opsi_daemon"},
    ExecutionMode.DIRECT_COMMAND: {"event_story", "azur_lane_uncensored", "game_manager", "benchmark"},
}

EXPECTED_DOMAINS = {
    TaskDomain.MAINTENANCE: {"restart", "azur_lane_uncensored", "game_manager", "benchmark"},
    TaskDomain.FACILITY: {"research", "commission", "tactical"},
    TaskDomain.COMPOSITE: {"dorm", "meowfficer", "guild", "reward", "freebies", "private_quarters"},
    TaskDomain.MARKET: {"awaken", "shipyard", "gacha", "shop_frequent", "shop_once"},
    TaskDomain.ENCOUNTER: {"daily", "hard", "exercise"},
    TaskDomain.CAMPAIGN: {
        "main",
        "main2",
        "main3",
        "event",
        "event2",
        "event_sp",
        "event_a",
        "event_b",
        "event_c",
        "event_d",
        "war_archives",
        "gems_farming",
    },
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
    TaskDomain.ACTIVITY: {
        "minigame",
        "event_story",
        "raid_daily",
        "maritime_escort",
        "raid",
        "hospital",
        "coalition",
        "coalition_sp",
        "daemon",
        "opsi_daemon",
    },
}

EXPECTED_CONTENT_POLICIES = {
    ContentRevisionPolicy.EVENT: {
        "event_story",
        "raid_daily",
        "maritime_escort",
        "raid",
        "hospital",
        "coalition",
        "coalition_sp",
    },
    ContentRevisionPolicy.CAMPAIGN: {
        "hard",
        "main",
        "main2",
        "main3",
        "event",
        "event2",
        "event_sp",
        "event_a",
        "event_b",
        "event_c",
        "event_d",
        "war_archives",
        "gems_farming",
    },
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


def _task_command_pairs() -> list[tuple[str, str]]:
    pairs = []
    for _group, task_name, _node in _task_nodes():
        spec = get_task_by_config_name(task_name)
        if spec is not None:
            pairs.append((task_name, spec.command))
    return pairs


def _legacy_priority_order() -> list[str]:
    names = [command_to_config_name(command) for command in TASK_SPECS]
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


def test_task_spec_lookup_is_immutable() -> None:
    spec = TASK_SPECS["main"]

    assert isinstance(spec, TaskSpec)
    assert get_task_spec("main") is spec
    assert get_task_spec("missing") is None
    priority_field = "priority"
    with pytest.raises(FrozenInstanceError):
        setattr(spec, priority_field, 999)


def test_sos_is_removed_without_changing_other_commands() -> None:
    assert set(TASK_SPECS) == EXPECTED_CATALOG_COMMANDS
    assert get_task_spec("sos") is None
    assert all(task_name != "Sos" for _group, task_name, _node in _task_nodes())
    assert "Sos" not in ConfigGenerator().argument
    assert not hasattr(GeneratedConfig, "Sos_Chapter")
    for lang in LANGUAGES:
        assert "Sos" not in read_file(filepath_i18n(lang))


@pytest.mark.parametrize(
    "command",
    ["bad space", "bad-name", "bad.name", "123", "_main", "main_", "main__two", "Main"],
)
def test_task_spec_rejects_non_ascii_snake_case_commands(command: str) -> None:
    with pytest.raises(ValueError, match="invalid task command"):
        TaskSpec(
            command=command,
            config_scopes=(),
            priority=0,
            execution_mode=ExecutionMode.SCHEDULED_JOB,
            domain=TaskDomain.CAMPAIGN,
            content_revision_policy=ContentRevisionPolicy.CAMPAIGN,
        )


@pytest.mark.parametrize(
    "config_scopes",
    [["General"], ("",), ("General", "General"), ("General", 1)],
)
def test_task_spec_rejects_invalid_config_scopes(config_scopes: object) -> None:
    with pytest.raises((TypeError, ValueError), match="config scopes"):
        TaskSpec(
            command="main",
            config_scopes=cast("tuple[str, ...]", config_scopes),
            priority=0,
            execution_mode=ExecutionMode.SCHEDULED_JOB,
            domain=TaskDomain.CAMPAIGN,
            content_revision_policy=ContentRevisionPolicy.CAMPAIGN,
        )


@pytest.mark.parametrize(
    ("priority", "error"),
    [(True, TypeError), (1.0, TypeError), ("1", TypeError), (-1, ValueError)],
)
def test_task_spec_rejects_invalid_priority(priority: object, error: type[Exception]) -> None:
    with pytest.raises(error, match="task priority"):
        TaskSpec(
            command="main",
            config_scopes=(),
            priority=cast("int | None", priority),
            execution_mode=ExecutionMode.SCHEDULED_JOB,
            domain=TaskDomain.CAMPAIGN,
            content_revision_policy=ContentRevisionPolicy.CAMPAIGN,
        )


def test_task_spec_rejects_untyped_execution_mode() -> None:
    with pytest.raises(TypeError, match="execution mode"):
        TaskSpec(
            command="main",
            config_scopes=(),
            priority=0,
            execution_mode=cast("ExecutionMode", "scheduled_job"),
            domain=TaskDomain.CAMPAIGN,
            content_revision_policy=ContentRevisionPolicy.CAMPAIGN,
        )


@pytest.mark.parametrize(
    ("mode", "priority", "error", "message"),
    [
        (ExecutionMode.SCHEDULED_JOB, None, TypeError, "scheduled task priority"),
        (ExecutionMode.ASSIST_SESSION, 0, ValueError, "non-scheduled task priority"),
        (ExecutionMode.DIRECT_COMMAND, 0, ValueError, "non-scheduled task priority"),
    ],
)
def test_task_spec_rejects_priority_that_conflicts_with_execution_mode(
    mode: ExecutionMode,
    priority: int | None,
    error: type[Exception],
    message: str,
) -> None:
    with pytest.raises(error, match=message):
        TaskSpec(
            command="main",
            config_scopes=(),
            priority=priority,
            execution_mode=mode,
            domain=TaskDomain.CAMPAIGN,
            content_revision_policy=ContentRevisionPolicy.CAMPAIGN,
        )


def test_task_yaml_nodes_resolve_unique_specs_with_matching_modes() -> None:
    command_nodes: dict[str, tuple[str, str, tuple[str, ...]]] = {}
    scope_nodes = set()

    for task_group, task_name, node in _task_nodes():
        assert set(node) <= {"groups"}
        groups = tuple(_deep_string_list(node.get("groups", [])))
        spec = get_task_by_config_name(task_name)
        if spec is None:
            scope_nodes.add(task_name)
            continue
        command = spec.command

        assert command not in command_nodes
        assert command in TASK_SPECS
        assert command_to_config_name(command) == task_name
        command_nodes[command] = (task_group, task_name, groups)
        execution_mode = spec.execution_mode
        if "Scheduler" in groups:
            assert execution_mode is ExecutionMode.SCHEDULED_JOB
        else:
            assert task_group == "Tool"
            assert execution_mode is not ExecutionMode.SCHEDULED_JOB

    assert scope_nodes == SCOPE_ONLY_NODES
    assert set(TASK_SPECS) - set(command_nodes) == INTERNAL_SCHEDULED_COMMANDS
    assert set(command_nodes) - set(TASK_SPECS) == set()


def test_task_spec_scopes_are_complete() -> None:
    assert {
        command: spec.config_scopes for command, spec in TASK_SPECS.items() if spec.config_scopes
    } == EXPECTED_SCOPES


def test_task_spec_execution_modes_are_exact_and_complete() -> None:
    classified_commands = [command for commands in EXPECTED_EXECUTION_COMMANDS.values() for command in commands]

    assert set(EXPECTED_EXECUTION_COMMANDS) == set(ExecutionMode)
    assert set(classified_commands) == EXPECTED_CATALOG_COMMANDS
    assert len(classified_commands) == len(set(classified_commands))
    assert {command: spec.execution_mode for command, spec in TASK_SPECS.items()} == {
        command: mode for mode, commands in EXPECTED_EXECUTION_COMMANDS.items() for command in commands
    }


def test_task_specs_are_the_only_domain_and_content_revision_classification() -> None:
    assert {
        domain: {command for command, spec in TASK_SPECS.items() if spec.domain is domain} for domain in TaskDomain
    } == EXPECTED_DOMAINS
    for policy, expected in EXPECTED_CONTENT_POLICIES.items():
        assert {command for command, spec in TASK_SPECS.items() if spec.content_revision_policy is policy} == expected
    classified = set().union(*EXPECTED_CONTENT_POLICIES.values())
    assert {
        command for command, spec in TASK_SPECS.items() if spec.content_revision_policy is ContentRevisionPolicy.BUILTIN
    } == EXPECTED_CATALOG_COMMANDS - classified


def test_execution_mode_is_the_only_launch_rule_and_determines_priority_shape() -> None:
    assert TASK_SPECS["daemon"].execution_mode is ExecutionMode.ASSIST_SESSION
    assert TASK_SPECS["benchmark"].execution_mode is ExecutionMode.DIRECT_COMMAND
    assert TASK_SPECS["restart"].execution_mode is ExecutionMode.SCHEDULED_JOB
    assert {
        command for command, spec in TASK_SPECS.items() if spec.execution_mode is not ExecutionMode.SCHEDULED_JOB
    } == NON_SCHEDULED_COMMANDS
    assert all(
        (spec.priority is not None) is (spec.execution_mode is ExecutionMode.SCHEDULED_JOB)
        for spec in TASK_SPECS.values()
    )


@pytest.mark.parametrize(
    ("task_name", "command"),
    _task_command_pairs(),
)
def test_all_config_commands_keep_legacy_bind_chain(task_name: str, command: str) -> None:
    extra_scope = "CallerScope"

    assert task_bind_chain(task_name, [extra_scope]) == [
        "General",
        "Alas",
        *EXPECTED_SCOPES.get(command, ()),
        task_name,
        extra_scope,
    ]


def test_task_yaml_scheduler_command_remains_pascal_case_node_name() -> None:
    args = ConfigGenerator().args

    for _task_group, task_name, node in _task_nodes():
        if get_task_by_config_name(task_name) is not None and "Scheduler" in _deep_string_list(node["groups"]):
            task_args = _deep_dict(args[task_name])
            scheduler = _deep_dict(task_args["Scheduler"])
            command = _deep_dict(scheduler["Command"])
            assert command["value"] == task_name


def test_config_generator_rejects_unknown_task_name() -> None:
    unknown = object.__new__(ConfigGenerator)
    unknown.task = {
        "Tool": {"tasks": {"Missing": {"groups": []}}},
    }
    with pytest.raises(ValueError, match="unknown scope-only task"):
        _ = unknown.menu


@pytest.mark.parametrize(
    ("task", "page", "message"),
    [
        ({"Ghost": {"groups": ["Scheduler"]}}, "setting", "scope-only task"),
        ({"General": {"groups": ["Scheduler"]}}, "setting", "scope-only task.*Scheduler"),
        ({"General": {"groups": ["Emulator"]}}, "tool", "scope-only task.*tool"),
        (
            {"Benchmark": {"groups": ["Scheduler"]}},
            "setting",
            "execution mode",
        ),
        ({"Main": {"groups": []}}, "tool", "execution mode"),
        (
            {"Main": {"groups": ["Campaign"]}},
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
        _task_group({"Main": {"groups": groups}}),
        "Scheduler",
    )

    with pytest.raises((TypeError, ValueError), match=message):
        _ = generator.args


def test_priority_matches_legacy_filter_first_match_order() -> None:
    legacy_order = _legacy_priority_order()
    prioritized = sorted(
        (spec for spec in TASK_SPECS.values() if spec.priority is not None),
        key=lambda spec: cast("int", spec.priority),
    )

    assert [spec.priority for spec in prioritized] == list(range(51))
    assert [command_to_config_name(spec.command) for spec in prioritized] == legacy_order
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
        for command in NON_SCHEDULED_COMMANDS
    } == {command_to_config_name(command): command for command in NON_SCHEDULED_COMMANDS}
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
