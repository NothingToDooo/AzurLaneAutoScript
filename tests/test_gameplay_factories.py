from types import MappingProxyType
from typing import TYPE_CHECKING, cast

import pytest

from module.gameplay import (
    CompositeWorkflows,
    EncounterWorkflows,
    MarketWorkflows,
    build_composite_factories,
    build_encounter_factories,
    build_market_factories,
)
from module.gameplay.composite import DormTask, FreebiesTask, GuildTask, MeowfficerTask, PrivateQuartersTask, RewardTask
from module.gameplay.encounter import DailyTask, ExerciseTask, HardTask
from module.gameplay.market import AwakenTask, GachaTask, ShipyardTask, ShopFrequentTask, ShopOnceTask
from module.runtime import FrozenJsonValue, SettingsDocumentError, TaskBuildContext, TaskFactory, TaskStateDocument
from module.task_registry import TASK_CATALOG

if TYPE_CHECKING:
    from collections.abc import Mapping

    from module.gameplay.composite import (
        DataKeyWorkflow,
        DormWorkflow,
        FreebieCollectionWorkflow,
        GuildWorkflow,
        MailCollectionWorkflow,
        MeowfficerWorkflow,
        PrivateQuartersWorkflow,
        RewardWorkflow,
        SupplyPackWorkflow,
    )
    from module.gameplay.encounter import DailyWorkflow, ExerciseWorkflow, HardWorkflow
    from module.gameplay.market import (
        AwakenWorkflow,
        GachaWorkflow,
        ShipyardWorkflow,
        ShopFrequentWorkflow,
        ShopOnceWorkflow,
    )

_SERVER_UPDATE = "2026-07-14T00:00:00+08:00"
_DAILY_SCHEDULE: dict[str, FrozenJsonValue] = {
    "timezone": "Asia/Hong_Kong",
    "triggers": ("08:00",),
}
_SERVER_UPDATE_SCHEDULE: dict[str, FrozenJsonValue] = {
    "timezone": "Asia/Hong_Kong",
    "triggers": ("12:00",),
}


class _Port:
    def __init__(self) -> None:
        self.calls = 0

    def execute(self, *args: object) -> object:
        self.calls += 1
        return args

    def collect(self, *args: object) -> object:
        self.calls += 1
        return args


def _composite_factories() -> Mapping[str, TaskFactory]:
    port = _Port()
    workflows = CompositeWorkflows(
        dorm=cast("DormWorkflow", port),
        meowfficer=cast("MeowfficerWorkflow", port),
        guild=cast("GuildWorkflow", port),
        reward=cast("RewardWorkflow", port),
        battle_pass=cast("FreebieCollectionWorkflow", port),
        data_key=cast("DataKeyWorkflow", port),
        mail=cast("MailCollectionWorkflow", port),
        supply_pack=cast("SupplyPackWorkflow", port),
        private_quarters=cast("PrivateQuartersWorkflow", port),
    )
    return build_composite_factories(workflows)


def _market_factories() -> Mapping[str, TaskFactory]:
    port = _Port()
    workflows = MarketWorkflows(
        awaken=cast("AwakenWorkflow", port),
        shipyard=cast("ShipyardWorkflow", port),
        gacha=cast("GachaWorkflow", port),
        shop_frequent=cast("ShopFrequentWorkflow", port),
        shop_once=cast("ShopOnceWorkflow", port),
    )
    return build_market_factories(workflows)


def _encounter_factories() -> Mapping[str, TaskFactory]:
    port = _Port()
    workflows = EncounterWorkflows(
        daily=cast("DailyWorkflow", port),
        hard=cast("HardWorkflow", port),
        exercise=cast("ExerciseWorkflow", port),
    )
    return build_encounter_factories(workflows)


def _context(command: str, settings: dict[str, FrozenJsonValue]) -> TaskBuildContext:
    return TaskBuildContext(
        TASK_CATALOG[command],
        2,
        MappingProxyType(settings),
        TaskStateDocument.empty(command),
    )


@pytest.mark.parametrize(
    ("command", "settings", "task_type"),
    [
        (
            "dorm",
            {
                "feed": {"filter": "20000 > 10000"},
                "collect_enabled": True,
                "furniture": None,
                "fallback_delay_seconds": 600,
            },
            DormTask,
        ),
        (
            "meowfficer",
            {
                "buy_amount": 1,
                "overflow_coin_threshold": None,
                "fort_chore_enabled": False,
                "training": {"mode": "seamlessly", "check_delay_seconds": 9000},
                "schedule": _DAILY_SCHEDULE,
            },
            MeowfficerTask,
        ),
        (
            "guild",
            {
                "logistics": {
                    "select_new_mission": False,
                    "exchange_filter": "Coin > Oil",
                },
                "operation": {
                    "select_new_operation": False,
                    "new_operation_max_date": 15,
                    "join_threshold": 1.0,
                    "attack_boss": True,
                    "boss_fleet_recommend": False,
                },
                "failure_retry_seconds": 600,
                "schedule": _DAILY_SCHEDULE,
            },
            GuildTask,
        ),
        (
            "reward",
            {
                "collect_oil": True,
                "collect_coin": True,
                "collect_exp": True,
                "collect_daily_mission": True,
                "collect_weekly_mission": True,
                "success_delay_seconds": 600,
            },
            RewardTask,
        ),
        (
            "freebies",
            {
                "collect_battle_pass": True,
                "data_key": {"force_collect": False},
                "mail": {
                    "claim_merit": True,
                    "claim_maintenance": False,
                    "claim_trade_license": False,
                    "delete_collected": True,
                },
                "supply_pack": {"collect": True, "day_of_week": 0},
                "schedule": _DAILY_SCHEDULE,
            },
            FreebiesTask,
        ),
        (
            "private_quarters",
            {
                "buy_roses": True,
                "buy_cake": False,
                "target_ship": None,
                "schedule": _DAILY_SCHEDULE,
            },
            PrivateQuartersTask,
        ),
    ],
)
def test_composite_factories_build_all_tasks(
    command: str,
    settings: dict[str, FrozenJsonValue],
    task_type: type[object],
) -> None:
    assert isinstance(_composite_factories()[command].build(_context(command, settings)), task_type)


@pytest.mark.parametrize(
    ("command", "settings", "task_type"),
    [
        (
            "awaken",
            {
                "plan": {"level_cap": "level120", "favourite_only": False},
                "schedule": _DAILY_SCHEDULE,
            },
            AwakenTask,
        ),
        (
            "shipyard",
            {
                "plan": {
                    "pr": {"research_series": 1, "ship_index": 0, "buy_amount": 1},
                    "dr": {"research_series": 1, "ship_index": 0, "buy_amount": 0},
                },
                "schedule": _DAILY_SCHEDULE,
            },
            ShipyardTask,
        ),
        (
            "gacha",
            {
                "plan": {"pool": "light", "amount": 1, "use_ticket": True, "use_drill": False},
                "schedule": _DAILY_SCHEDULE,
            },
            GachaTask,
        ),
        (
            "shop_frequent",
            {
                "plan": {
                    "filter": "Cube",
                    "refresh": False,
                    "use_gems": False,
                    "consume_coins": False,
                    "buy_skin_box": False,
                },
                "schedule": _DAILY_SCHEDULE,
            },
            ShopFrequentTask,
        ),
        (
            "shop_once",
            {
                "plan": {
                    "merit": {"filter": "Cube", "refresh": False},
                    "guild": {
                        "filter": "PlateT4",
                        "refresh": True,
                        "box_t3": "ironblood",
                        "box_t4": "ironblood",
                        "book_t2": "red",
                        "book_t3": "red",
                        "retrofit_t2": "cl",
                        "retrofit_t3": "cl",
                        "plate_t2": "general",
                        "plate_t3": "general",
                        "plate_t4": "gun",
                        "pr1": "neptune",
                        "pr2": "seattle",
                        "pr3": "cheshire",
                    },
                    "core": {"filter": "Array"},
                    "medal": {
                        "filter": "DR > PR",
                        "retrofit_t1": "cl",
                        "retrofit_t2": "cl",
                        "retrofit_t3": "cl",
                        "plate_t1": "general",
                        "plate_t2": "general",
                        "plate_t3": "general",
                    },
                },
                "schedule": _DAILY_SCHEDULE,
            },
            ShopOnceTask,
        ),
    ],
)
def test_market_factories_build_all_tasks(
    command: str,
    settings: dict[str, FrozenJsonValue],
    task_type: type[object],
) -> None:
    assert isinstance(_market_factories()[command].build(_context(command, settings)), task_type)


@pytest.mark.parametrize(
    ("command", "settings", "task_type"),
    [
        (
            "daily",
            {
                "schedule": _SERVER_UPDATE_SCHEDULE,
                "use_daily_skip": True,
                "missions": {
                    "escort": {"stage": "first", "fleet": 1},
                    "advance": {"stage": "first", "fleet": 1},
                    "fierce_assault": {"stage": "first", "fleet": 1},
                    "tactical_training": {"stage": "second", "fleet": 1},
                    "supply_line_disruption": {"stage": "second", "fleet": None},
                    "module_development": {"stage": "first", "fleet": 1},
                    "emergency_module_development": {"stage": "first", "fleet": 1},
                },
            },
            DailyTask,
        ),
        (
            "hard",
            {
                "schedule": _SERVER_UPDATE_SCHEDULE,
                "failure_retry_seconds": 600,
                "resource_retry_seconds": 1800,
                "stage": "11-4",
                "fleet": 1,
            },
            HardTask,
        ),
        (
            "exercise",
            {
                "schedule": _SERVER_UPDATE_SCHEDULE,
                "failure_retry_seconds": 600,
                "opponent_refresh_limit": 5,
                "opponent_mode": "max_exp",
                "opponent_trials": 1,
                "strategy": "aggressive",
                "low_hp_threshold": 0.4,
                "low_hp_confirm_wait_seconds": 0.1,
            },
            ExerciseTask,
        ),
    ],
)
def test_encounter_factories_build_all_tasks(
    command: str,
    settings: dict[str, FrozenJsonValue],
    task_type: type[object],
) -> None:
    assert isinstance(_encounter_factories()[command].build(_context(command, settings)), task_type)


def test_encounter_factories_reject_legacy_absolute_deadlines() -> None:
    settings: dict[str, FrozenJsonValue] = {"next_server_update_at": _SERVER_UPDATE}

    with pytest.raises(SettingsDocumentError, match=r"missing required setting.*schedule"):
        _encounter_factories()["daily"].build(_context("daily", settings))


def test_nested_factory_settings_reject_unknown_fields() -> None:
    settings: dict[str, FrozenJsonValue] = {
        "plan": {"level_cap": "level120", "favourite_only": False, "obsolete": True},
        "schedule": _DAILY_SCHEDULE,
    }
    with pytest.raises(SettingsDocumentError, match="unknown settings"):
        _market_factories()["awaken"].build(_context("awaken", settings))
