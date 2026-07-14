import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TypeVar, cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from module.config.server import CN_PACKAGE
from module.notify.configuration import (
    DisabledNotificationConfig,
    NotificationConfig,
    NotificationConfigError,
    SmtpNotificationConfig,
    parse_notification_config,
)
from module.state import JsonValue, ScheduleMutation
from module.task_registry import TASK_CATALOG, config_name_to_command


class ConfigurationCompileError(ValueError):
    pass


type ConfigurationDocument = Mapping[str, object]

_ValueT = TypeVar("_ValueT", bool, int, float, str)
_SENTINEL_DATE = datetime(2020, 1, 1)


def _error(path: tuple[str, ...], message: str) -> ConfigurationCompileError:
    return ConfigurationCompileError(f"$.{'.'.join(path)} {message}")


class _ConfigView:
    __slots__ = ("_root",)

    def __init__(self, document: ConfigurationDocument) -> None:
        if not isinstance(document, Mapping):
            message = "configuration document must be an object"
            raise TypeError(message)
        self._root = document

    def mapping(self, *path: str) -> Mapping[str, object]:
        value: object = self._root
        traversed: list[str] = []
        for key in path:
            traversed.append(key)
            if not isinstance(value, Mapping):
                raise _error(tuple(traversed[:-1]), "must be an object")
            mapping = cast("Mapping[str, object]", value)
            try:
                value = mapping[key]
            except KeyError:
                raise _error(tuple(traversed), "is required") from None
        if not isinstance(value, Mapping):
            raise _error(path, "must be an object")
        if any(not isinstance(key, str) for key in value):
            raise _error(path, "must use string field names")
        return cast("Mapping[str, object]", value)

    def value(self, *path: str, expected: type[_ValueT]) -> _ValueT:
        owner = self.mapping(*path[:-1])
        try:
            value = owner[path[-1]]
        except KeyError:
            raise _error(path, "is required") from None
        if expected is bool:
            valid = type(value) is bool
        elif expected is int:
            valid = type(value) is int
        elif expected is float:
            valid = type(value) is float
        else:
            valid = isinstance(value, expected)
        if not valid:
            raise _error(path, f"must be a {expected.__name__}")
        return cast("_ValueT", value)


@dataclass(frozen=True, slots=True)
class CompiledConfiguration:
    payload: JsonValue
    schedules: tuple[ScheduleMutation, ...]
    notification: NotificationConfig
    device_serial: str
    source_revision: str
    assembly_revision: str

    def __post_init__(self) -> None:
        if not isinstance(self.payload, dict):
            message = "payload must be an object"
            raise TypeError(message)
        if not isinstance(self.schedules, tuple) or any(
            not isinstance(schedule, ScheduleMutation) for schedule in self.schedules
        ):
            message = "schedules must be a tuple of ScheduleMutation values"
            raise TypeError(message)
        if not isinstance(self.notification, DisabledNotificationConfig | SmtpNotificationConfig):
            message = "notification must be a NotificationConfig"
            raise TypeError(message)
        if not isinstance(self.device_serial, str) or not self.device_serial.strip():
            message = "device_serial must be a non-empty string"
            raise ValueError(message)
        for field_name, revision in (
            ("source_revision", self.source_revision),
            ("assembly_revision", self.assembly_revision),
        ):
            if not isinstance(revision, str):
                message = f"{field_name} must be a string"
                raise TypeError(message)
            if re.fullmatch(r"sha256:[0-9a-f]{64}", revision) is None:
                message = f"{field_name} must be a canonical sha256 revision"
                raise ValueError(message)


def _source_revision(payload: JsonValue, schedules: tuple[ScheduleMutation, ...]) -> str:
    canonical_schedules = [
        {
            "task_id": schedule.task_id,
            "enabled": schedule.enabled,
            "due_at": None if schedule.due_at is None else schedule.due_at.astimezone(UTC).isoformat(),
            "priority": schedule.priority,
        }
        for schedule in sorted(schedules, key=lambda item: item.task_id)
    ]
    encoded = json.dumps(
        {
            "format": "alas-runtime-configuration-v1",
            "payload": payload,
            "schedules": canonical_schedules,
        },
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _assembly_revision(view: _ConfigView) -> str:
    """只摘要进程组装时绑定、不能在任务安全点替换的配置平面。"""

    projection = {
        "Alas": dict(view.mapping("Alas")),
        "General": dict(view.mapping("General")),
    }
    try:
        encoded = json.dumps(
            {
                "format": "alas-instance-assembly-v1",
                "configuration": projection,
            },
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    except (TypeError, ValueError) as error:
        message = "$.Alas and $.General must contain canonical JSON values"
        raise ConfigurationCompileError(message) from error
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _split_triggers(value: str, *, path: tuple[str, ...]) -> list[JsonValue]:
    triggers = [part.strip() for part in value.split(",")]
    if not triggers or any(re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", trigger) is None for trigger in triggers):
        raise _error(path, "must be a comma-separated HH:MM list")
    return [cast("JsonValue", trigger) for trigger in triggers]


def _local_datetime(value: str, timezone: ZoneInfo, *, path: tuple[str, ...]) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise _error(path, "must be an ISO datetime") from error
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone)
    return parsed.astimezone(UTC)


def _interval_seconds(
    value: object,
    *,
    path: tuple[str, ...],
    default_minutes: int = 30,
) -> dict[str, JsonValue]:
    if type(value) is int:
        lower_minutes = value
        upper_minutes = value
    elif isinstance(value, str):
        match = re.fullmatch(r"(\d+)(?:-(\d+))?", value.strip())
        if match is None:
            raise _error(path, "must be minutes or a minute range")
        lower_minutes = int(match.group(1))
        upper_minutes = int(match.group(2)) if match.group(2) is not None else lower_minutes
    else:
        raise _error(path, "must be minutes or a minute range")
    if lower_minutes <= 0:
        lower_minutes = default_minutes
    if upper_minutes <= 0:
        upper_minutes = default_minutes
    if lower_minutes > upper_minutes:
        raise _error(path, "lower bound must not exceed upper bound")
    return {
        "lower_seconds": lower_minutes * 60,
        "upper_seconds": upper_minutes * 60,
    }


def _positive_integer_triplet(value: str, *, path: tuple[str, ...]) -> list[JsonValue]:
    parts = [part.strip() for part in value.replace("，", ",").split(",")]
    if len(parts) != 3 or any(re.fullmatch(r"[1-9]\d*", part) is None for part in parts):
        raise _error(path, "must contain exactly three comma-separated positive integers")
    return [int(part) for part in parts]


class WebConfigurationCompiler:
    """把 WebUI 文档严格投影为当前 runtime schema；旧字段不会越过此边界。"""

    __slots__ = ("_timezone", "_timezone_name")

    def __init__(self, *, timezone_name: str = "Asia/Shanghai") -> None:
        if not isinstance(timezone_name, str) or not timezone_name or timezone_name != timezone_name.strip():
            message = "timezone_name must be a trimmed non-empty string"
            raise ValueError(message)
        try:
            timezone = ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError as error:
            message = f"unknown IANA timezone: {timezone_name}"
            raise ValueError(message) from error
        self._timezone = timezone
        self._timezone_name = timezone_name

    def compile(self, document: ConfigurationDocument) -> CompiledConfiguration:
        view = _ConfigView(document)
        notification = self.compile_notification(document)
        tasks: dict[str, JsonValue] = {}
        tasks.update(self._maintenance(view))
        tasks.update(self._facility(view))
        tasks.update(self._composite(view))
        tasks.update(self._market(view))
        tasks.update(self._encounter(view))
        tasks.update(self._activity(view))
        tasks.update(self._campaign(view))
        tasks.update(self._opsi(view))
        expected = set(TASK_CATALOG)
        if set(tasks) != expected:
            missing = sorted(expected - set(tasks))
            unknown = sorted(set(tasks) - expected)
            message = f"compiled task coverage mismatch: missing={missing}, unknown={unknown}"
            raise ConfigurationCompileError(message)
        payload: JsonValue = {"schema_version": 1, "tasks": tasks}
        schedules = self._schedules(view)
        return CompiledConfiguration(
            payload=payload,
            schedules=schedules,
            notification=notification,
            device_serial=view.value("Alas", "Emulator", "Serial", expected=str),
            source_revision=_source_revision(payload, schedules),
            assembly_revision=_assembly_revision(view),
        )

    def compile_notification(self, document: ConfigurationDocument) -> NotificationConfig:
        """独立编译进程级通知配置，供完整 runtime 尚未建成时报告失败。"""

        return self._notification(_ConfigView(document))

    @staticmethod
    def _notification(view: _ConfigView) -> NotificationConfig:
        path = ("Alas", "Error", "OnePushConfig")
        raw_config = view.value(*path, expected=str)
        try:
            return parse_notification_config(raw_config)
        except NotificationConfigError as error:
            raise _error(path, str(error)) from error

    def _schedule(self, view: _ConfigView, config_name: str) -> dict[str, JsonValue]:
        raw = view.value(config_name, "Scheduler", "ServerUpdate", expected=str)
        return {
            "timezone": self._timezone_name,
            "triggers": _split_triggers(raw, path=(config_name, "Scheduler", "ServerUpdate")),
        }

    @staticmethod
    def _retry_seconds(view: _ConfigView, config_name: str) -> dict[str, JsonValue]:
        scheduler = view.mapping(config_name, "Scheduler")
        return _interval_seconds(
            scheduler.get("FailureInterval"),
            path=(config_name, "Scheduler", "FailureInterval"),
        )

    @staticmethod
    def _success_seconds(view: _ConfigView, config_name: str) -> dict[str, JsonValue]:
        scheduler = view.mapping(config_name, "Scheduler")
        return _interval_seconds(
            scheduler.get("SuccessInterval"),
            path=(config_name, "Scheduler", "SuccessInterval"),
        )

    def _schedules(self, view: _ConfigView) -> tuple[ScheduleMutation, ...]:
        schedules: list[ScheduleMutation] = []
        for task_id, definition in TASK_CATALOG.items():
            if definition.priority is None:
                continue
            config_name = definition.config_name
            enabled = view.value(config_name, "Scheduler", "Enable", expected=bool)
            next_run = view.value(config_name, "Scheduler", "NextRun", expected=str)
            schedules.append(
                ScheduleMutation(
                    task_id=task_id,
                    enabled=enabled,
                    due_at=_local_datetime(
                        next_run,
                        self._timezone,
                        path=(config_name, "Scheduler", "NextRun"),
                    ),
                    priority=definition.priority,
                )
            )
        return tuple(schedules)

    def _maintenance(self, view: _ConfigView) -> dict[str, JsonValue]:
        return {
            "restart": {"schedule": self._schedule(view, "Restart")},
            "azur_lane_uncensored": {"package_name": CN_PACKAGE},
            "game_manager": {"auto_restart": view.value("GameManager", "GameManager", "AutoRestart", expected=bool)},
            "benchmark": {
                "scene": view.value("Benchmark", "Benchmark", "TestScene", expected=str),
                "safe_stage": "7-2",
            },
        }

    def _facility(self, view: _ConfigView) -> dict[str, JsonValue]:
        return {
            "research": {
                "schedule": self._schedule(view, "Research"),
                "selection": {
                    "use_cube": view.value("Research", "Research", "UseCube", expected=str),
                    "use_coin": view.value("Research", "Research", "UseCoin", expected=str),
                    "use_part": view.value("Research", "Research", "UsePart", expected=str),
                    "allow_delay": view.value("Research", "Research", "AllowDelay", expected=bool),
                    "preset_filter": view.value("Research", "Research", "PresetFilter", expected=str),
                    "custom_filter": view.value("Research", "Research", "CustomFilter", expected=str),
                },
            },
            "commission": {
                "failure_retry_seconds": self._retry_seconds(view, "Commission"),
                "commission_limit_enabled": view.value("GemsFarming", "GemsFarming", "CommissionLimit", expected=bool),
                "selection": {
                    "preset_filter": view.value(
                        "Commission",
                        "Commission",
                        "PresetFilter",
                        expected=str,
                    ),
                    "custom_filter": view.value(
                        "Commission",
                        "Commission",
                        "CustomFilter",
                        expected=str,
                    ),
                    "do_major_commission": view.value(
                        "Commission",
                        "Commission",
                        "DoMajorCommission",
                        expected=bool,
                    ),
                },
                "gems_farming_deferral_seconds": 7_200,
            },
            "tactical": {
                "failure_retry_seconds": self._retry_seconds(view, "Tactical"),
                "server_update_schedule": self._schedule(view, "Tactical"),
                "tactical_filter": view.value("Tactical", "Tactical", "TacticalFilter", expected=str),
                "rapid_training_slot": view.value(
                    "Tactical",
                    "Tactical",
                    "RapidTrainingSlot",
                    expected=str,
                ),
                "experience_overflow": {
                    "enabled": view.value("Tactical", "ControlExpOverflow", "Enable", expected=bool),
                    "t1_allow": view.value("Tactical", "ControlExpOverflow", "T1Allow", expected=int),
                    "t2_allow": view.value("Tactical", "ControlExpOverflow", "T2Allow", expected=int),
                    "t3_allow": view.value("Tactical", "ControlExpOverflow", "T3Allow", expected=int),
                    "t4_allow": view.value("Tactical", "ControlExpOverflow", "T4Allow", expected=int),
                },
                "student": {
                    "enabled": view.value("Tactical", "AddNewStudent", "Enable", expected=bool),
                    "favorite": view.value("Tactical", "AddNewStudent", "Favorite", expected=bool),
                    "minimum_level": view.value("Tactical", "AddNewStudent", "MinLevel", expected=int),
                },
            },
        }

    def _composite(self, view: _ConfigView) -> dict[str, JsonValue]:
        overflow = view.value("Meowfficer", "Meowfficer", "OverflowCoins", expected=int)
        training_enabled = view.value("Meowfficer", "MeowfficerTrain", "Enable", expected=bool)
        training: JsonValue = None
        if training_enabled:
            training = {
                "mode": view.value("Meowfficer", "MeowfficerTrain", "Mode", expected=str),
                "check_delay_seconds": 180 * 60,
            }
        target_ship: JsonValue = None
        if view.value("PrivateQuarters", "PrivateQuarters", "TargetInteract", expected=bool):
            target_ship = view.value("PrivateQuarters", "PrivateQuarters", "TargetShip", expected=str)
        dorm_feed: JsonValue = None
        if view.value("Dorm", "Dorm", "Feed", expected=bool):
            dorm_feed = {
                "filter": view.value("Dorm", "Dorm", "FeedFilter", expected=str),
            }
        dorm_furniture: JsonValue = None
        if view.value("Dorm", "BuyFurniture", "Enable", expected=bool):
            dorm_furniture = {
                "buy_option": view.value("Dorm", "BuyFurniture", "BuyOption", expected=str),
                "check_interval_seconds": 6 * 24 * 60 * 60,
            }
        guild_logistics: JsonValue = None
        if view.value("Guild", "GuildLogistics", "Enable", expected=bool):
            guild_logistics = {
                "select_new_mission": view.value(
                    "Guild",
                    "GuildLogistics",
                    "SelectNewMission",
                    expected=bool,
                ),
                "exchange_filter": view.value(
                    "Guild",
                    "GuildLogistics",
                    "ExchangeFilter",
                    expected=str,
                ),
            }
        guild_operation: JsonValue = None
        if view.value("Guild", "GuildOperation", "Enable", expected=bool):
            guild_operation = {
                "select_new_operation": view.value(
                    "Guild",
                    "GuildOperation",
                    "SelectNewOperation",
                    expected=bool,
                ),
                "new_operation_max_date": view.value(
                    "Guild",
                    "GuildOperation",
                    "NewOperationMaxDate",
                    expected=int,
                ),
                "join_threshold": float(
                    view.value(
                        "Guild",
                        "GuildOperation",
                        "JoinThreshold",
                        expected=int,
                    )
                ),
                "attack_boss": view.value("Guild", "GuildOperation", "AttackBoss", expected=bool),
                "boss_fleet_recommend": view.value(
                    "Guild",
                    "GuildOperation",
                    "BossFleetRecommend",
                    expected=bool,
                ),
            }
        data_key: JsonValue = None
        if view.value("Freebies", "DataKey", "Collect", expected=bool):
            data_key = {
                "force_collect": view.value("Freebies", "DataKey", "ForceCollect", expected=bool),
            }
        return {
            "dorm": {
                "feed": dorm_feed,
                "collect_enabled": view.value("Dorm", "Dorm", "Collect", expected=bool),
                "furniture": dorm_furniture,
                "fallback_delay_seconds": self._success_seconds(view, "Dorm"),
            },
            "meowfficer": {
                "buy_amount": view.value("Meowfficer", "Meowfficer", "BuyAmount", expected=int),
                "overflow_coin_threshold": None if overflow < 0 else overflow,
                "fort_chore_enabled": view.value("Meowfficer", "Meowfficer", "FortChoreMeowfficer", expected=bool),
                "training": training,
                "schedule": self._schedule(view, "Meowfficer"),
            },
            "guild": {
                "logistics": guild_logistics,
                "operation": guild_operation,
                "failure_retry_seconds": self._retry_seconds(view, "Guild"),
                "schedule": self._schedule(view, "Guild"),
            },
            "reward": {
                "collect_oil": view.value("Reward", "Reward", "CollectOil", expected=bool),
                "collect_coin": view.value("Reward", "Reward", "CollectCoin", expected=bool),
                "collect_exp": view.value("Reward", "Reward", "CollectExp", expected=bool),
                "collect_daily_mission": view.value("Reward", "Reward", "CollectMission", expected=bool),
                "collect_weekly_mission": view.value("Reward", "Reward", "CollectWeeklyMission", expected=bool),
                "success_delay_seconds": self._success_seconds(view, "Reward"),
            },
            "freebies": {
                "collect_battle_pass": view.value("Freebies", "BattlePass", "Collect", expected=bool),
                "data_key": data_key,
                "mail": {
                    "claim_merit": view.value("Freebies", "Mail", "ClaimMerit", expected=bool),
                    "claim_maintenance": view.value(
                        "Freebies",
                        "Mail",
                        "ClaimMaintenance",
                        expected=bool,
                    ),
                    "claim_trade_license": view.value(
                        "Freebies",
                        "Mail",
                        "ClaimTradeLicense",
                        expected=bool,
                    ),
                    "delete_collected": view.value(
                        "Freebies",
                        "Mail",
                        "DeleteCollected",
                        expected=bool,
                    ),
                },
                "supply_pack": {
                    "collect": view.value("Freebies", "SupplyPack", "Collect", expected=bool),
                    "day_of_week": view.value("Freebies", "SupplyPack", "DayOfWeek", expected=int),
                },
                "schedule": self._schedule(view, "Freebies"),
            },
            "private_quarters": {
                "buy_roses": view.value("PrivateQuarters", "PrivateQuarters", "BuyRoses", expected=bool),
                "buy_cake": view.value("PrivateQuarters", "PrivateQuarters", "BuyCake", expected=bool),
                "target_ship": target_ship,
                "schedule": self._schedule(view, "PrivateQuarters"),
            },
        }

    def _market(self, view: _ConfigView) -> dict[str, JsonValue]:
        def nullable_filter(config_name: str, group: str) -> JsonValue:
            value = view.value(config_name, group, "Filter", expected=str).strip()
            return value or None

        def purchase(group: str) -> dict[str, JsonValue]:
            return {
                "research_series": view.value("Shipyard", group, "ResearchSeries", expected=int),
                "ship_index": view.value("Shipyard", group, "ShipIndex", expected=int),
                "buy_amount": view.value("Shipyard", group, "BuyAmount", expected=int),
            }

        return {
            "awaken": {
                "plan": {
                    "level_cap": view.value("Awaken", "Awaken", "LevelCap", expected=str),
                    "favourite_only": view.value("Awaken", "Awaken", "Favourite", expected=bool),
                },
                "schedule": self._schedule(view, "Awaken"),
            },
            "shipyard": {
                "plan": {"pr": purchase("Shipyard"), "dr": purchase("ShipyardDr")},
                "schedule": self._schedule(view, "Shipyard"),
            },
            "gacha": {
                "plan": {
                    "pool": view.value("Gacha", "Gacha", "Pool", expected=str),
                    "amount": view.value("Gacha", "Gacha", "Amount", expected=int),
                    "use_ticket": view.value("Gacha", "Gacha", "UseTicket", expected=bool),
                    "use_drill": view.value("Gacha", "Gacha", "UseDrill", expected=bool),
                },
                "schedule": self._schedule(view, "Gacha"),
            },
            "shop_frequent": {
                "plan": {
                    "filter": nullable_filter("ShopFrequent", "GeneralShop"),
                    "refresh": view.value("ShopFrequent", "GeneralShop", "Refresh", expected=bool),
                    "use_gems": view.value("ShopFrequent", "GeneralShop", "UseGems", expected=bool),
                    "consume_coins": view.value(
                        "ShopFrequent",
                        "GeneralShop",
                        "ConsumeCoins",
                        expected=bool,
                    ),
                    "buy_skin_box": view.value(
                        "ShopFrequent",
                        "GeneralShop",
                        "BuySkinBox",
                        expected=bool,
                    ),
                },
                "schedule": self._schedule(view, "ShopFrequent"),
            },
            "shop_once": {
                "plan": {
                    "merit": {
                        "filter": nullable_filter("ShopOnce", "MeritShop"),
                        "refresh": view.value("ShopOnce", "MeritShop", "Refresh", expected=bool),
                    },
                    "guild": {
                        "filter": nullable_filter("ShopOnce", "GuildShop"),
                        "refresh": view.value("ShopOnce", "GuildShop", "Refresh", expected=bool),
                        "box_t3": view.value("ShopOnce", "GuildShop", "BOX_T3", expected=str),
                        "box_t4": view.value("ShopOnce", "GuildShop", "BOX_T4", expected=str),
                        "book_t2": view.value("ShopOnce", "GuildShop", "BOOK_T2", expected=str),
                        "book_t3": view.value("ShopOnce", "GuildShop", "BOOK_T3", expected=str),
                        "retrofit_t2": view.value(
                            "ShopOnce",
                            "GuildShop",
                            "RETROFIT_T2",
                            expected=str,
                        ),
                        "retrofit_t3": view.value(
                            "ShopOnce",
                            "GuildShop",
                            "RETROFIT_T3",
                            expected=str,
                        ),
                        "plate_t2": view.value("ShopOnce", "GuildShop", "PLATE_T2", expected=str),
                        "plate_t3": view.value("ShopOnce", "GuildShop", "PLATE_T3", expected=str),
                        "plate_t4": view.value("ShopOnce", "GuildShop", "PLATE_T4", expected=str),
                        "pr1": view.value("ShopOnce", "GuildShop", "PR1", expected=str),
                        "pr2": view.value("ShopOnce", "GuildShop", "PR2", expected=str),
                        "pr3": view.value("ShopOnce", "GuildShop", "PR3", expected=str),
                    },
                    "core": {"filter": nullable_filter("ShopOnce", "CoreShop")},
                    "medal": {
                        "filter": nullable_filter("ShopOnce", "MedalShop2"),
                        "retrofit_t1": view.value(
                            "ShopOnce",
                            "MedalShop2",
                            "RETROFIT_T1",
                            expected=str,
                        ),
                        "retrofit_t2": view.value(
                            "ShopOnce",
                            "MedalShop2",
                            "RETROFIT_T2",
                            expected=str,
                        ),
                        "retrofit_t3": view.value(
                            "ShopOnce",
                            "MedalShop2",
                            "RETROFIT_T3",
                            expected=str,
                        ),
                        "plate_t1": view.value("ShopOnce", "MedalShop2", "PLATE_T1", expected=str),
                        "plate_t2": view.value("ShopOnce", "MedalShop2", "PLATE_T2", expected=str),
                        "plate_t3": view.value("ShopOnce", "MedalShop2", "PLATE_T3", expected=str),
                    },
                },
                "schedule": self._schedule(view, "ShopOnce"),
            },
        }

    def _encounter(self, view: _ConfigView) -> dict[str, JsonValue]:
        def daily_mission(
            source_name: str,
            *,
            fleet_source_name: str | None,
        ) -> dict[str, JsonValue]:
            fleet: JsonValue = None
            if fleet_source_name is not None:
                fleet = view.value("Daily", "Daily", fleet_source_name, expected=int)
            return {
                "stage": view.value("Daily", "Daily", source_name, expected=str),
                "fleet": fleet,
            }

        return {
            "daily": {
                "schedule": self._schedule(view, "Daily"),
                "use_daily_skip": view.value("Daily", "Daily", "UseDailySkip", expected=bool),
                "missions": {
                    "escort": daily_mission("EscortMission", fleet_source_name="EscortMissionFleet"),
                    "advance": daily_mission("AdvanceMission", fleet_source_name="AdvanceMissionFleet"),
                    "fierce_assault": daily_mission(
                        "FierceAssault",
                        fleet_source_name="FierceAssaultFleet",
                    ),
                    "tactical_training": daily_mission(
                        "TacticalTraining",
                        fleet_source_name="TacticalTrainingFleet",
                    ),
                    "supply_line_disruption": daily_mission(
                        "SupplyLineDisruption",
                        fleet_source_name=None,
                    ),
                    "module_development": daily_mission(
                        "ModuleDevelopment",
                        fleet_source_name="ModuleDevelopmentFleet",
                    ),
                    "emergency_module_development": daily_mission(
                        "EmergencyModuleDevelopment",
                        fleet_source_name="EmergencyModuleDevelopmentFleet",
                    ),
                },
            },
            "hard": {
                "schedule": self._schedule(view, "Hard"),
                "failure_retry_seconds": self._retry_seconds(view, "Hard"),
                "resource_retry_seconds": 7_200,
                "stage": view.value("Hard", "Hard", "HardStage", expected=str),
                "fleet": view.value("Hard", "Hard", "HardFleet", expected=int),
            },
            "exercise": {
                "schedule": self._schedule(view, "Exercise"),
                "failure_retry_seconds": self._retry_seconds(view, "Exercise"),
                "opponent_refresh_limit": 5,
                "opponent_mode": view.value("Exercise", "Exercise", "OpponentChooseMode", expected=str),
                "opponent_trials": view.value("Exercise", "Exercise", "OpponentTrial", expected=int),
                "strategy": view.value("Exercise", "Exercise", "ExerciseStrategy", expected=str),
                "low_hp_threshold": view.value("Exercise", "Exercise", "LowHpThreshold", expected=float),
                "low_hp_confirm_wait_seconds": view.value(
                    "Exercise",
                    "Exercise",
                    "LowHpConfirmWait",
                    expected=float,
                ),
            },
        }

    def _activity_event_deadline(self, view: _ConfigView) -> JsonValue:
        raw = view.value("EventGeneral", "EventGeneral", "TimeLimit", expected=str)
        deadline = datetime.fromisoformat(raw)
        if deadline.replace(tzinfo=None) <= _SENTINEL_DATE:
            return None
        return {
            "at": _local_datetime(
                raw,
                self._timezone,
                path=("EventGeneral", "EventGeneral", "TimeLimit"),
            ).isoformat()
        }

    @staticmethod
    def _activity_fleet_emotion(
        view: _ConfigView,
        config_name: str,
        fleet: int,
    ) -> dict[str, JsonValue]:
        return {
            "control": view.value(config_name, "Emotion", f"Fleet{fleet}Control", expected=str),
            "recover": view.value(config_name, "Emotion", f"Fleet{fleet}Recover", expected=str),
            "oath": view.value(config_name, "Emotion", f"Fleet{fleet}Oath", expected=bool),
        }

    def _activity_emotion(self, view: _ConfigView, config_name: str) -> dict[str, JsonValue]:
        return {
            "mode": view.value(config_name, "Emotion", "Mode", expected=str),
            "fleet1": self._activity_fleet_emotion(view, config_name, 1),
            "fleet2": self._activity_fleet_emotion(view, config_name, 2),
        }

    def _activity_policy(
        self,
        view: _ConfigView,
        config_name: str,
        *,
        combat: bool,
    ) -> dict[str, JsonValue]:
        oil_limit = 0
        use_2x_book = False
        emotion_policy: JsonValue = None
        if combat:
            oil_limit = view.value(config_name, "StopCondition", "OilLimit", expected=int)
            emotion_policy = self._activity_emotion(view, config_name)
            if "Campaign" in view.mapping(config_name):
                use_2x_book = view.value(config_name, "Campaign", "Use2xBook", expected=bool)
        return {
            "failure_retry_seconds": self._retry_seconds(view, config_name),
            "resource_retry_seconds": 7_200,
            "oil_limit": oil_limit,
            "event_point_limit": view.value("EventGeneral", "EventGeneral", "PtLimit", expected=int),
            "event_deadline": self._activity_event_deadline(view),
            "use_2x_book": use_2x_book,
            "emotion": emotion_policy,
        }

    def _activity_continuous(self, view: _ConfigView, config_name: str) -> dict[str, JsonValue]:
        run_count = view.value(config_name, "StopCondition", "RunCount", expected=int)
        balancer = self._balancer(view)
        return {
            "run_limit": run_count or None,
            "balancer": None if balancer is None else {**balancer, "retry_seconds": 300},
        }

    def _activity(self, view: _ConfigView) -> dict[str, JsonValue]:

        raid_daily_filter = view.value("RaidDaily", "RaidDaily", "StageFilter", expected=str)
        raid_daily_stages = [
            cast("JsonValue", item.strip().lower()) for item in raid_daily_filter.split(">") if item.strip()
        ]

        return {
            "minigame": {
                "game": "new_year_challenge",
                "operation_limit": 10,
                "schedule": self._schedule(view, "Minigame"),
            },
            "event_story": {
                "event": view.value("Event", "Campaign", "Event", expected=str),
                "skip_battle": view.value("EventStory", "EventStory", "SkipBattle", expected=bool),
            },
            "raid_daily": {
                "event": view.value("RaidDaily", "Campaign", "Event", expected=str),
                "stages": raid_daily_stages,
                "use_ticket": False,
                "collect_daily_mission": view.value("Reward", "Reward", "CollectMission", expected=bool),
                "policy": self._activity_policy(view, "RaidDaily", combat=True),
                "schedule": self._schedule(view, "RaidDaily"),
            },
            "maritime_escort": {
                "policy": self._activity_policy(view, "MaritimeEscort", combat=False),
                "schedule": self._schedule(view, "MaritimeEscort"),
            },
            "raid": {
                "event": view.value("Raid", "Campaign", "Event", expected=str),
                "mode": view.value("Raid", "Raid", "Mode", expected=str),
                "use_ticket": view.value("Raid", "Raid", "UseTicket", expected=bool),
                "policy": self._activity_policy(view, "Raid", combat=True),
                **self._activity_continuous(view, "Raid"),
            },
            "hospital": {
                "use_recommended_fleet": view.value("Hospital", "Hospital", "UseRecommendFleet", expected=bool),
                "policy": self._activity_policy(view, "Hospital", combat=True),
                "schedule": self._schedule(view, "Hospital"),
            },
            "coalition": {
                "event": view.value("Coalition", "Campaign", "Event", expected=str),
                "stage": view.value("Coalition", "Coalition", "Mode", expected=str),
                "fleet": view.value("Coalition", "Coalition", "Fleet", expected=str),
                "policy": self._activity_policy(view, "Coalition", combat=True),
                **self._activity_continuous(view, "Coalition"),
            },
            "coalition_sp": {
                "event": view.value("CoalitionSp", "Campaign", "Event", expected=str),
                "stage": view.value("CoalitionSp", "Coalition", "Mode", expected=str),
                # 游戏规则固定要求 SP 使用多舰队；旧配置中的单舰队值从未实际生效。
                "fleet": "multi",
                "policy": self._activity_policy(view, "CoalitionSp", combat=True),
                "schedule": self._schedule(view, "CoalitionSp"),
            },
            "daemon": {"enter_map": view.value("Daemon", "Daemon", "EnterMap", expected=bool)},
            "opsi_daemon": {
                "repair_ship": view.value("OpsiDaemon", "OpsiDaemon", "RepairShip", expected=bool),
                "select_enemy": view.value("OpsiDaemon", "OpsiDaemon", "SelectEnemy", expected=bool),
            },
        }

    @staticmethod
    def _balancer(view: _ConfigView) -> dict[str, JsonValue] | None:
        if not view.value("EventGeneral", "TaskBalancer", "Enable", expected=bool):
            return None
        target = view.value("EventGeneral", "TaskBalancer", "TaskCall", expected=str)
        return {
            "target_task_id": config_name_to_command(target),
            "coin_limit": view.value("EventGeneral", "TaskBalancer", "CoinLimit", expected=int),
        }

    def _campaign_execution(self, view: _ConfigView, name: str) -> dict[str, JsonValue]:
        def fleet_emotion(index: int) -> dict[str, JsonValue]:
            prefix = f"Fleet{index}"
            record_path = (name, "Emotion", f"{prefix}Record")
            recorded_at = _local_datetime(
                view.value(*record_path, expected=str),
                self._timezone,
                path=record_path,
            )
            return {
                "value": view.value(name, "Emotion", f"{prefix}Value", expected=int),
                "recorded_at": recorded_at.isoformat(),
                "control": view.value(name, "Emotion", f"{prefix}Control", expected=str),
                "recover": view.value(name, "Emotion", f"{prefix}Recover", expected=str),
                "oath": view.value(name, "Emotion", f"{prefix}Oath", expected=bool),
            }

        # GemsFarming 的旧 UI 没有暴露这两组，旧引擎实际使用 GeneratedConfig 的同一组默认策略。
        if name == "GemsFarming":
            hp_control: dict[str, JsonValue] = {
                "use_hp_balance": False,
                "use_emergency_repair": False,
                "use_low_hp_retreat": False,
                "hp_balance_threshold": 0.2,
                "hp_balance_weight": [1_000, 1_000, 1_000],
                "repair_use_single_threshold": 0.3,
                "repair_use_multi_threshold": 0.6,
                "low_hp_retreat_threshold": 0.3,
            }
            enemy_priority: dict[str, JsonValue] = {"scale_balance_weight": "default_mode"}
        else:
            weight_path = (name, "HpControl", "HpBalanceWeight")
            hp_control = {
                "use_hp_balance": view.value(name, "HpControl", "UseHpBalance", expected=bool),
                "use_emergency_repair": view.value(name, "HpControl", "UseEmergencyRepair", expected=bool),
                "use_low_hp_retreat": view.value(name, "HpControl", "UseLowHpRetreat", expected=bool),
                "hp_balance_threshold": view.value(name, "HpControl", "HpBalanceThreshold", expected=float),
                "hp_balance_weight": _positive_integer_triplet(
                    view.value(*weight_path, expected=str),
                    path=weight_path,
                ),
                "repair_use_single_threshold": view.value(
                    name,
                    "HpControl",
                    "RepairUseSingleThreshold",
                    expected=float,
                ),
                "repair_use_multi_threshold": view.value(
                    name,
                    "HpControl",
                    "RepairUseMultiThreshold",
                    expected=float,
                ),
                "low_hp_retreat_threshold": view.value(
                    name,
                    "HpControl",
                    "LowHpRetreatThreshold",
                    expected=float,
                ),
            }
            enemy_priority = {
                "scale_balance_weight": view.value(
                    name,
                    "EnemyPriority",
                    "EnemyScaleBalanceWeight",
                    expected=str,
                )
            }

        return {
            "automation": {
                "ambush_evade": view.value(name, "Campaign", "AmbushEvade", expected=bool),
                "use_2x_book": view.value(name, "Campaign", "Use2xBook", expected=bool),
                "use_auto_search": view.value(name, "Campaign", "UseAutoSearch", expected=bool),
                "use_clear_mode": view.value(name, "Campaign", "UseClearMode", expected=bool),
                "use_fleet_lock": view.value(name, "Campaign", "UseFleetLock", expected=bool),
            },
            "fleets": {
                "fleet1": view.value(name, "Fleet", "Fleet1", expected=int),
                "fleet1_mode": view.value(name, "Fleet", "Fleet1Mode", expected=str),
                "fleet1_step": view.value(name, "Fleet", "Fleet1Step", expected=int),
                "fleet2": view.value(name, "Fleet", "Fleet2", expected=int),
                "fleet2_mode": view.value(name, "Fleet", "Fleet2Mode", expected=str),
                "fleet2_step": view.value(name, "Fleet", "Fleet2Step", expected=int),
                "order": view.value(name, "Fleet", "FleetOrder", expected=str),
            },
            "submarine": {
                "fleet": view.value(name, "Submarine", "Fleet", expected=int),
                "mode": view.value(name, "Submarine", "Mode", expected=str),
                "auto_search_mode": view.value(name, "Submarine", "AutoSearchMode", expected=str),
                "distance_to_boss": view.value(name, "Submarine", "DistanceToBoss", expected=str),
            },
            "emotion": {
                "mode": view.value(name, "Emotion", "Mode", expected=str),
                "fleet1": fleet_emotion(1),
                "fleet2": fleet_emotion(2),
            },
            "hp_control": hp_control,
            "enemy_priority": enemy_priority,
        }

    def _campaign(self, view: _ConfigView) -> dict[str, JsonValue]:
        commands = (
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
        )
        tasks: dict[str, JsonValue] = {}
        for command in commands:
            definition = TASK_CATALOG[command]
            name = definition.config_name
            pack_id = view.value(name, "Campaign", "Event", expected=str)
            stage_name = view.value(name, "Campaign", "Name", expected=str).lower()
            if command in {"event_a", "event_b", "event_c", "event_d"}:
                stage_filter = view.value(name, "EventDaily", "StageFilter", expected=str)
                stage_ids: list[JsonValue] = [item.strip().lower() for item in stage_filter.split(">") if item.strip()]
            else:
                stage_ids = [stage_name]
            mode = view.value(name, "Campaign", "Mode", expected=str)
            if mode not in {"normal", "hard"}:
                raise _error((name, "Campaign", "Mode"), "must be normal or hard")
            stop = view.mapping(name, "StopCondition")
            event_limit = 0
            event_deadline: JsonValue = None
            if definition.config_scopes:
                event_limit = view.value("EventGeneral", "EventGeneral", "PtLimit", expected=int)
                raw_deadline = view.value("EventGeneral", "EventGeneral", "TimeLimit", expected=str)
                deadline = datetime.fromisoformat(raw_deadline)
                if deadline.replace(tzinfo=None) > _SENTINEL_DATE:
                    event_deadline = {
                        "at": _local_datetime(
                            raw_deadline,
                            self._timezone,
                            path=("EventGeneral", "EventGeneral", "TimeLimit"),
                        ).isoformat()
                    }
            limits: dict[str, JsonValue] = {
                "run_count": cast("int", stop["RunCount"]),
                "reach_level": cast("int", stop["ReachLevel"]),
                "oil": cast("int", stop["OilLimit"]),
                "stop_on_new_ship": cast("bool", stop["GetNewShip"]),
                "event_points": event_limit,
                "event_deadline": event_deadline,
                "map_achievement": cast("str", stop["MapAchievement"]),
                "stage_increase": cast("bool", stop["StageIncrease"]),
            }
            task: dict[str, JsonValue] = {
                "pack_id": pack_id,
                "stage_ids": stage_ids,
                "difficulty": mode,
                "execution": self._campaign_execution(view, name),
                "schedule": self._schedule(view, name),
                "failure_retry_seconds": self._retry_seconds(view, name),
                "resource_retry_seconds": 7_200,
                "limits": limits,
                "task_balancer": self._balancer(view) if definition.config_scopes else None,
            }
            if command == "gems_farming":
                task["gems_farming"] = {
                    "fallback": {
                        "pack_id": "campaign_main",
                        "stage_id": "2-4",
                    },
                    "flagship_change": view.value("GemsFarming", "GemsFarming", "ChangeFlagship", expected=str),
                    "common_carrier": view.value("GemsFarming", "GemsFarming", "CommonCV", expected=str),
                    "vanguard_change": view.value("GemsFarming", "GemsFarming", "ChangeVanguard", expected=str),
                    "common_destroyer": view.value("GemsFarming", "GemsFarming", "CommonDD", expected=str),
                    "equipment_code_config": view.value("GemsFarming", "EquipmentCode", "Config", expected=str),
                    "replacement_retry_seconds": 1_800,
                }
            tasks[command] = task
        return tasks

    @staticmethod
    def _opsi_general(view: _ConfigView) -> dict[str, JsonValue]:
        return {
            "use_logger": view.value("OpsiGeneral", "OpsiGeneral", "UseLogger", expected=bool),
            "buy_action_point_limit": view.value("OpsiGeneral", "OpsiGeneral", "BuyActionPointLimit", expected=int),
            "oil_preserve": view.value("OpsiGeneral", "OpsiGeneral", "OilLimit", expected=int),
            "repair_threshold": view.value("OpsiGeneral", "OpsiGeneral", "RepairThreshold", expected=float),
            "random_map_events": view.value("OpsiGeneral", "OpsiGeneral", "DoRandomMapEvent", expected=bool),
            "akashi_shop_filter": view.value("OpsiGeneral", "OpsiGeneral", "AkashiShopFilter", expected=str),
        }

    @staticmethod
    def _fleet(view: _ConfigView, name: str) -> dict[str, JsonValue]:
        return {
            "fleet_index": view.value(name, "OpsiFleet", "Fleet", expected=int),
            "use_submarine": view.value(name, "OpsiFleet", "Submarine", expected=bool),
        }

    def _opsi(self, view: _ConfigView) -> dict[str, JsonValue]:
        def general() -> dict[str, JsonValue]:
            return self._opsi_general(view)

        ensure_ash = view.value("OpsiAshBeacon", "OpsiAshBeacon", "EnsureFullyCollected", expected=bool)
        fleet_filter = view.value("OpsiAbyssal", "OpsiFleetFilter", "Filter", expected=str)
        voucher_filter = view.value("OpsiVoucher", "OpsiVoucher", "Filter", expected=str)
        return {
            "opsi_ash_assist": {"minimum_tier": view.value("OpsiAshAssist", "OpsiAshAssist", "Tier", expected=int)},
            "opsi_ash_beacon": {
                "attack_mode": view.value("OpsiAshBeacon", "OpsiAshBeacon", "AttackMode", expected=str),
                "one_hit_mode": view.value("OpsiAshBeacon", "OpsiAshBeacon", "OneHitMode", expected=bool),
                "dossier_auto_attack": view.value(
                    "OpsiAshBeacon", "OpsiAshBeacon", "DossierAutoAttackMode", expected=bool
                ),
                "request_assist": view.value("OpsiAshBeacon", "OpsiAshBeacon", "RequestAssist", expected=bool),
                "ensure_fully_collected": ensure_ash,
            },
            "opsi_explore": {
                "general": general(),
                "fleet": self._fleet(view, "OpsiExplore"),
                "special_radar": view.value("OpsiExplore", "OpsiExplore", "SpecialRadar", expected=bool),
                "force_run": view.value("OpsiExplore", "OpsiExplore", "ForceRun", expected=bool),
                "last_zone": view.value("OpsiExplore", "OpsiExplore", "LastZone", expected=int),
            },
            "opsi_shop": {
                "general": general(),
                "preset": view.value("OpsiShop", "OpsiShop", "PresetFilter", expected=str),
                "custom_filter": view.value("OpsiShop", "OpsiShop", "CustomFilter", expected=str),
            },
            "opsi_voucher": {"general": general(), "filter": voucher_filter},
            "opsi_daily": {
                "general": general(),
                "fleet": self._fleet(view, "OpsiDaily"),
                "do_missions": view.value("OpsiDaily", "OpsiDaily", "DoMission", expected=bool),
                "use_tuning_samples": view.value("OpsiDaily", "OpsiDaily", "UseTuningSample", expected=bool),
            },
            "opsi_obscure": {
                "general": general(),
                "fleet": self._fleet(view, "OpsiObscure"),
                "force_run": view.value("OpsiObscure", "OpsiObscure", "ForceRun", expected=bool),
            },
            "opsi_month_boss": {
                "general": general(),
                "fleet_filter": view.value("OpsiMonthBoss", "OpsiFleetFilter", "Filter", expected=str),
                "mode": view.value("OpsiMonthBoss", "OpsiMonthBoss", "Mode", expected=str),
                "check_adaptability": view.value("OpsiMonthBoss", "OpsiMonthBoss", "CheckAdaptability", expected=bool),
                "force_run": view.value("OpsiMonthBoss", "OpsiMonthBoss", "ForceRun", expected=bool),
            },
            "opsi_abyssal": {
                "general": general(),
                "fleet_filter": fleet_filter,
                "force_run": view.value("OpsiAbyssal", "OpsiAbyssal", "ForceRun", expected=bool),
            },
            "opsi_archive": {
                "general": general(),
                "fleet": self._fleet(view, "OpsiArchive"),
                "voucher_filter": voucher_filter,
            },
            "opsi_stronghold": {
                "general": general(),
                "fleet_filter": view.value("OpsiStronghold", "OpsiFleetFilter", "Filter", expected=str),
                "force_run": view.value("OpsiStronghold", "OpsiStronghold", "ForceRun", expected=bool),
            },
            "opsi_meowfficer_farming": {
                "general": general(),
                "fleet": self._fleet(view, "OpsiMeowfficerFarming"),
                "action_point_preserve": view.value(
                    "OpsiMeowfficerFarming",
                    "OpsiMeowfficerFarming",
                    "ActionPointPreserve",
                    expected=int,
                ),
                "hazard_level": view.value(
                    "OpsiMeowfficerFarming", "OpsiMeowfficerFarming", "HazardLevel", expected=int
                ),
                "target_zone": view.value("OpsiMeowfficerFarming", "OpsiMeowfficerFarming", "TargetZone", expected=int),
                "ensure_ash_fully_collected": ensure_ash,
            },
            "opsi_hazard1_leveling": {
                "general": general(),
                "fleet": self._fleet(view, "OpsiHazard1Leveling"),
                "target_zone": view.value("OpsiHazard1Leveling", "OpsiHazard1Leveling", "TargetZone", expected=int),
                "ensure_ash_fully_collected": ensure_ash,
            },
            "opsi_cross_month": {
                "general": general(),
                "daily_fleet_index": view.value("OpsiDaily", "OpsiFleet", "Fleet", expected=int),
                "obscure_fleet_index": view.value("OpsiObscure", "OpsiFleet", "Fleet", expected=int),
                "abyssal_fleet_filter": fleet_filter,
                "meowfficer_fleet_index": view.value("OpsiMeowfficerFarming", "OpsiFleet", "Fleet", expected=int),
            },
        }
