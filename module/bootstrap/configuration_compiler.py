import copy
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path
from typing import TYPE_CHECKING, TypeVar, cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from module.config.json_codec import StrictJsonDecodeError, decode_json
from module.config.server import CN_PACKAGE
from module.device.mumu import MUMU12_SERIAL_EXAMPLE, is_mumu12_serial
from module.notify.configuration import (
    DisabledNotificationConfig,
    NotificationConfig,
    NotificationConfigError,
    SmtpNotificationConfig,
    build_notification_config,
)
from module.runtime.settings import FrozenTaskSettings, JsonValue, freeze_task_settings
from module.task_registry import TASK_CATALOG, config_name_to_command

if TYPE_CHECKING:
    from module.config.deep import DeepValue, MutableDeepData, MutableDeepValue


class ConfigurationCompileError(ValueError):
    pass


type ConfigurationDocument = Mapping[str, object]

_ValueT = TypeVar("_ValueT", bool, int, float, str)
_SENTINEL_DATE = datetime(2020, 1, 1)
_DEFAULT_SCHEMA_PATH = Path(__file__).resolve().parents[1] / "config" / "argument" / "args.json"
_SCHEDULER_INTERVAL_FIELDS = frozenset({"SuccessInterval", "FailureInterval"})


def _error(path: tuple[str, ...], message: str) -> ConfigurationCompileError:
    location = "$" if not path else f"$.{'.'.join(path)}"
    return ConfigurationCompileError(f"{location} {message}")


def _schema_mapping(value: object, *, path: tuple[str, ...]) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise _error(path, "must be an object")
    if any(not isinstance(key, str) for key in value):
        raise _error(path, "must use string field names")
    return cast("Mapping[str, object]", value)


def _require_exact_fields(
    value: Mapping[str, object],
    expected: Mapping[str, object],
    *,
    path: tuple[str, ...],
) -> None:
    unknown = sorted(set(value) - set(expected))
    if unknown:
        raise _error((*path, unknown[0]), "is not part of the current configuration schema")
    missing = sorted(set(expected) - set(value))
    if missing:
        raise _error((*path, missing[0]), "is required by the current configuration schema")


def _matches_option(value: object, option: object) -> bool:
    return type(value) is type(option) and value == option


def _is_finite_number(value: object) -> bool:
    if type(value) not in {int, float}:
        return False
    return math.isfinite(cast("int | float", value))


def _is_scheduler_interval_value(value: object, *, path: tuple[str, ...]) -> bool:
    if len(path) != 3 or path[1] != "Scheduler" or path[2] not in _SCHEDULER_INTERVAL_FIELDS:
        return False
    if type(value) is int:
        return True
    if not isinstance(value, str):
        return False
    lower, separator, upper = value.strip().partition("-")
    return separator == "-" and lower.isascii() and lower.isdecimal() and upper.isascii() and upper.isdecimal()


class CurrentConfigurationSchema:
    """校验并解析唯一受支持的当前 alas.json 结构。"""

    __slots__ = ("_definition",)

    def __init__(self, definition_path: Path = _DEFAULT_SCHEMA_PATH) -> None:
        if not isinstance(definition_path, Path):
            message = "definition_path must be a Path"
            raise TypeError(message)
        try:
            decoded = decode_json(definition_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, StrictJsonDecodeError) as error:
            message = f"failed to load current configuration schema {definition_path}: {error}"
            raise RuntimeError(message) from error
        self._definition = _schema_mapping(decoded, path=())

    def validate(self, document: ConfigurationDocument) -> None:
        self.parse(document)

    def parse(self, document: ConfigurationDocument) -> MutableDeepData:
        root = _schema_mapping(document, path=())
        _require_exact_fields(root, self._definition, path=())
        parsed: MutableDeepData = {}
        for task_name, raw_groups in self._definition.items():
            task_path = (task_name,)
            groups = _schema_mapping(raw_groups, path=task_path)
            task = _schema_mapping(root[task_name], path=task_path)
            _require_exact_fields(task, groups, path=task_path)
            parsed_groups: MutableDeepData = {}
            for group_name, raw_fields in groups.items():
                group_path = (*task_path, group_name)
                fields = _schema_mapping(raw_fields, path=group_path)
                group = _schema_mapping(task[group_name], path=group_path)
                _require_exact_fields(group, fields, path=group_path)
                parsed_fields: MutableDeepData = {}
                for field_name, raw_descriptor in fields.items():
                    field_path = (*group_path, field_name)
                    descriptor = _schema_mapping(raw_descriptor, path=field_path)
                    parsed_fields[field_name] = self._parse_field(
                        group[field_name],
                        descriptor,
                        path=field_path,
                    )
                parsed_groups[group_name] = parsed_fields
            parsed[task_name] = parsed_groups
        return parsed

    @staticmethod
    def _parse_field(
        value: object,
        descriptor: Mapping[str, object],
        *,
        path: tuple[str, ...],
    ) -> MutableDeepValue:
        if "value" not in descriptor:
            raise _error(path, "has no current default definition")
        default_value = descriptor["value"]
        CurrentConfigurationSchema._validate_raw_type(value, default_value, path=path)
        options = descriptor.get("option")
        if options is not None:
            if not isinstance(options, list):
                raise _error(path, "has an invalid internal option definition")
            if not any(_matches_option(value, option) for option in options):
                raise _error(path, f"must be one of {options!r}")
        parsed = CurrentConfigurationSchema._parse_typed_value(value, descriptor, path=path)
        default = CurrentConfigurationSchema._parse_typed_value(default_value, descriptor, path=path)
        CurrentConfigurationSchema._validate_parsed_type(parsed, default, path=path)
        return cast("MutableDeepValue", parsed)

    @staticmethod
    def _parse_typed_value(
        value: object,
        descriptor: Mapping[str, object],
        *,
        path: tuple[str, ...],
    ) -> DeepValue:
        # JSON 已携带 bool/数字类型；只有 schema 明确声明的 datetime 需要转换。
        if type(descriptor.get("value")) is float and type(value) is int:
            return float(value)
        if descriptor.get("type") != "datetime":
            return cast("DeepValue", value)
        if not isinstance(value, str):
            raise _error(path, "must be an ISO datetime")
        try:
            return datetime.fromisoformat(value)
        except ValueError as error:
            raise _error(path, "must be an ISO datetime") from error

    @staticmethod
    def _validate_raw_type(value: object, default: object, *, path: tuple[str, ...]) -> None:
        if _is_scheduler_interval_value(value, path=path):
            return
        if default is None:
            if value is not None and not isinstance(value, str):
                raise _error(path, "must be text or null")
            return
        if type(default) is float:
            if not _is_finite_number(value):
                raise _error(path, "must be a finite number")
            return
        if isinstance(default, Mapping):
            _schema_mapping(value, path=path)
            return
        if type(value) is not type(default):
            raise _error(path, f"must be a {type(default).__name__}")

    @staticmethod
    def _validate_parsed_type(value: DeepValue, default: DeepValue, *, path: tuple[str, ...]) -> None:
        if _is_scheduler_interval_value(value, path=path):
            return
        if default is None:
            if value is not None and not isinstance(value, str):
                raise _error(path, "must be text or null")
            return
        if type(default) is float:
            if not _is_finite_number(value):
                raise _error(path, "must be a finite number")
            return
        if isinstance(default, Mapping):
            _schema_mapping(value, path=path)
            return
        if type(value) is not type(default):
            if isinstance(default, datetime):
                raise _error(path, "must be an ISO datetime")
            raise _error(path, f"must be a {type(default).__name__}")


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
            if not _is_finite_number(value):
                raise _error(path, "must be a float")
            return cast("_ValueT", float(cast("int | float", value)))
        else:
            valid = isinstance(value, expected)
        if not valid:
            raise _error(path, f"must be a {expected.__name__}")
        return cast("_ValueT", value)


@dataclass(frozen=True, slots=True, init=False)
class CompiledConfiguration:
    _runtime_document: MutableDeepData = field(repr=False)
    _tasks: Mapping[str, FrozenTaskSettings] = field(repr=False)
    _task_revisions: Mapping[str, int] = field(repr=False)
    notification: NotificationConfig
    device_serial: str

    def __init__(
        self,
        *,
        runtime_document: MutableDeepData,
        tasks: Mapping[str, JsonValue],
        notification: NotificationConfig,
        device_serial: str,
    ) -> None:
        if not isinstance(runtime_document, dict):
            message = "runtime_document must be a parsed configuration object"
            raise TypeError(message)
        if not isinstance(notification, DisabledNotificationConfig | SmtpNotificationConfig):
            message = "notification must be a NotificationConfig"
            raise TypeError(message)
        if not isinstance(device_serial, str) or not device_serial.strip():
            message = "device_serial must be a non-empty string"
            raise ValueError(message)
        frozen_tasks, task_revisions = freeze_task_settings(tasks, task_ids=TASK_CATALOG)
        object.__setattr__(self, "_runtime_document", copy.deepcopy(runtime_document))
        object.__setattr__(self, "_tasks", frozen_tasks)
        object.__setattr__(self, "_task_revisions", task_revisions)
        object.__setattr__(self, "notification", notification)
        object.__setattr__(self, "device_serial", device_serial)

    @property
    def runtime_document(self) -> MutableDeepData:
        """返回 legacy driver 使用的独立解析快照。"""

        return copy.deepcopy(self._runtime_document)

    @property
    def tasks(self) -> Mapping[str, FrozenTaskSettings]:
        return self._tasks

    @property
    def task_revisions(self) -> Mapping[str, int]:
        return self._task_revisions


def _split_triggers(value: str, *, path: tuple[str, ...]) -> list[JsonValue]:
    triggers = [part.strip() for part in value.split(",")]
    if not triggers or any(re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", trigger) is None for trigger in triggers):
        raise _error(path, "must be a comma-separated HH:MM list")
    if any(left >= right for left, right in pairwise(triggers)):
        raise _error(path, "must be strictly increasing without duplicates")
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
    if lower_minutes <= 0 or upper_minutes <= 0:
        raise _error(path, "must be positive")
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

    __slots__ = ("_schema", "_timezone", "_timezone_name")

    def __init__(self, *, timezone_name: str = "Asia/Shanghai") -> None:
        if not isinstance(timezone_name, str) or not timezone_name or timezone_name != timezone_name.strip():
            message = "timezone_name must be a trimmed non-empty string"
            raise ValueError(message)
        try:
            timezone = ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError as error:
            message = f"unknown IANA timezone: {timezone_name}"
            raise ValueError(message) from error
        self._schema = CurrentConfigurationSchema()
        self._timezone = timezone
        self._timezone_name = timezone_name

    def compile(self, document: ConfigurationDocument) -> CompiledConfiguration:
        """一次校验同时产出 typed settings 与旧游戏驱动需要的解析文档。"""

        runtime_document = self._schema.parse(document)
        view = _ConfigView(document)
        notification = self._notification(view)
        device_serial = self._validate_device_settings(view)
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
        return CompiledConfiguration(
            runtime_document=runtime_document,
            tasks=tasks,
            notification=notification,
            device_serial=device_serial,
        )

    def parse_runtime_document(self, document: ConfigurationDocument) -> MutableDeepData:
        """完整校验后，把 JSON 字段解析为旧 UI driver 需要的运行时类型。"""

        return self.compile(document).runtime_document

    @staticmethod
    def _validate_device_settings(view: _ConfigView) -> str:
        serial_path = ("Alas", "Emulator", "Serial")
        serial = view.value(*serial_path, expected=str)
        if not is_mumu12_serial(serial):
            raise _error(serial_path, f'must be a MuMu12 TCP serial such as "{MUMU12_SERIAL_EXAMPLE}"')

        screenshot_length_path = ("Alas", "Error", "ScreenshotLength")
        screenshot_length = view.value(*screenshot_length_path, expected=int)
        if not 1 <= screenshot_length <= 300:
            raise _error(screenshot_length_path, "must be between 1 and 300")

        for field_name, lower, upper in (
            ("ScreenshotInterval", 0.1, 0.3),
            ("CombatScreenshotInterval", 0.3, 1.0),
        ):
            path = ("Alas", "Optimization", field_name)
            interval = view.value(*path, expected=float)
            if not lower <= interval <= upper:
                raise _error(path, f"must be between {lower} and {upper} seconds")
        return serial

    @staticmethod
    def _notification(view: _ConfigView) -> NotificationConfig:
        path = ("Alas", "Error")
        fields = view.mapping(*path)

        def text(name: str) -> str:
            value = fields.get(name)
            if value is None:
                return ""
            if not isinstance(value, str):
                raise _error((*path, name), "must be text or null")
            return value

        try:
            return build_notification_config(
                enabled=view.value(*path, "SmtpEnabled", expected=bool),
                host=text("SmtpHost"),
                port=view.value(*path, "SmtpPort", expected=int),
                transport=view.value(*path, "SmtpTransport", expected=str),
                user=text("SmtpUser"),
                password=text("SmtpPassword"),
                recipients=text("SmtpRecipients"),
            )
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
