from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from types import MappingProxyType
from typing import TYPE_CHECKING, cast

from module.gameplay.composite import (
    DORM_FURNITURE_CHECK_KEY,
    DORM_FURNITURE_CHECK_SCHEMA_VERSION,
    DataKeyPlan,
    DataKeyWorkflow,
    DormFeedPlan,
    DormFurniturePlan,
    DormSettings,
    DormTask,
    FreebiesSettings,
    FreebiesTask,
    FurnitureBuyOption,
    GuildLogisticsPolicy,
    GuildOperationPolicy,
    GuildSettings,
    GuildTask,
    MailCollectionPolicy,
    MeowfficerSettings,
    MeowfficerTask,
    MeowfficerTrainingMode,
    MeowfficerTrainingSettings,
    PrivateQuartersSettings,
    PrivateQuartersTask,
    RewardSettings,
    RewardTask,
    SupplyPackPlan,
)
from module.runtime import (
    SettingsDecoder,
    SettingsDocumentError,
    TaskBuildContext,
    TaskStateDocumentError,
    TypedTaskFactory,
)

if TYPE_CHECKING:
    from module.gameplay.composite import (
        DormWorkflow,
        FreebieCollectionWorkflow,
        GuildWorkflow,
        MailCollectionWorkflow,
        MeowfficerWorkflow,
        PrivateQuartersWorkflow,
        RewardWorkflow,
        SupplyPackWorkflow,
    )
    from module.runtime import FrozenTaskSettings, TaskFactory


def _require_method(value: object, method: str, *, field_name: str) -> None:
    if isinstance(value, type) or not callable(getattr(value, method, None)):
        message = f"{field_name} must implement {method}()"
        raise TypeError(message)


@dataclass(frozen=True, slots=True)
class CompositeWorkflows:
    dorm: DormWorkflow
    meowfficer: MeowfficerWorkflow
    guild: GuildWorkflow
    reward: RewardWorkflow
    battle_pass: FreebieCollectionWorkflow
    data_key: DataKeyWorkflow
    mail: MailCollectionWorkflow
    supply_pack: SupplyPackWorkflow
    private_quarters: PrivateQuartersWorkflow

    def __post_init__(self) -> None:
        for field_name in ("dorm", "meowfficer", "guild", "reward", "private_quarters"):
            _require_method(getattr(self, field_name), "execute", field_name=field_name)
        for field_name in ("battle_pass", "data_key", "mail", "supply_pack"):
            _require_method(getattr(self, field_name), "collect", field_name=field_name)


def _duration(decoder: SettingsDecoder, name: str) -> timedelta:
    return timedelta(seconds=decoder.integer(name, minimum=1))


def _dorm_settings(decoder: SettingsDecoder) -> DormSettings:
    feed_decoder = decoder.nullable_object("feed")
    feed = None
    if feed_decoder is not None:
        feed = DormFeedPlan(filter=feed_decoder.nullable_string("filter"))
        feed_decoder.finish()
    furniture_decoder = decoder.nullable_object("furniture")
    furniture = None
    if furniture_decoder is not None:
        furniture = DormFurniturePlan(
            buy_option=furniture_decoder.enum("buy_option", FurnitureBuyOption),
            check_interval=_duration(furniture_decoder, "check_interval_seconds"),
        )
        furniture_decoder.finish()
    return DormSettings(
        feed=feed,
        collect_enabled=decoder.boolean("collect_enabled"),
        furniture=furniture,
        fallback_delay=decoder.delay_range("fallback_delay_seconds"),
    )


def _dorm_last_furniture_check(context: TaskBuildContext) -> datetime | None:
    unknown = sorted(set(context.task_state.entries) - {DORM_FURNITURE_CHECK_KEY})
    if unknown:
        message = f"unknown dorm task state keys: {unknown}"
        raise TaskStateDocumentError(message)
    entry = context.task_state.get(DORM_FURNITURE_CHECK_KEY)
    if entry is None:
        return None
    if entry.schema_version != DORM_FURNITURE_CHECK_SCHEMA_VERSION:
        message = (
            f"$.task_state.{DORM_FURNITURE_CHECK_KEY} schema version must be {DORM_FURNITURE_CHECK_SCHEMA_VERSION}"
        )
        raise TaskStateDocumentError(message)
    if not isinstance(entry.payload, Mapping):
        message = f"$.task_state.{DORM_FURNITURE_CHECK_KEY} must be an object"
        raise TaskStateDocumentError(message)
    try:
        decoder = SettingsDecoder(
            cast("FrozenTaskSettings", entry.payload),
            path=f"$.task_state.{DORM_FURNITURE_CHECK_KEY}",
        )
        checked_at = decoder.datetime("checked_at")
        decoder.finish()
    except (SettingsDocumentError, TypeError, ValueError) as error:
        message = f"invalid dorm furniture checkpoint: {error}"
        raise TaskStateDocumentError(message) from error
    return checked_at


def _meowfficer_settings(decoder: SettingsDecoder) -> MeowfficerSettings:
    training_decoder = decoder.nullable_object("training")
    training = None
    if training_decoder is not None:
        training = MeowfficerTrainingSettings(
            mode=training_decoder.enum("mode", MeowfficerTrainingMode),
            check_delay=_duration(training_decoder, "check_delay_seconds"),
        )
        training_decoder.finish()
    return MeowfficerSettings(
        buy_amount=decoder.integer("buy_amount", minimum=0, maximum=15),
        overflow_coin_threshold=decoder.nullable_integer("overflow_coin_threshold", minimum=0),
        fort_chore_enabled=decoder.boolean("fort_chore_enabled"),
        training=training,
        schedule=decoder.daily_schedule("schedule"),
    )


def _guild_settings(decoder: SettingsDecoder) -> GuildSettings:
    logistics_decoder = decoder.nullable_object("logistics")
    logistics = None
    if logistics_decoder is not None:
        logistics = GuildLogisticsPolicy(
            select_new_mission=logistics_decoder.boolean("select_new_mission"),
            exchange_filter=logistics_decoder.nullable_string("exchange_filter"),
        )
        logistics_decoder.finish()
    operation_decoder = decoder.nullable_object("operation")
    operation = None
    if operation_decoder is not None:
        operation = GuildOperationPolicy(
            select_new_operation=operation_decoder.boolean("select_new_operation"),
            new_operation_max_date=operation_decoder.integer("new_operation_max_date", minimum=1, maximum=31),
            join_threshold=operation_decoder.number("join_threshold", minimum=0, maximum=1),
            attack_boss=operation_decoder.boolean("attack_boss"),
            boss_fleet_recommend=operation_decoder.boolean("boss_fleet_recommend"),
        )
        operation_decoder.finish()
    return GuildSettings(
        logistics=logistics,
        operation=operation,
        failure_retry_delay=decoder.delay_range("failure_retry_seconds"),
        schedule=decoder.daily_schedule("schedule"),
    )


def _reward_settings(decoder: SettingsDecoder) -> RewardSettings:
    return RewardSettings(
        collect_oil=decoder.boolean("collect_oil"),
        collect_coin=decoder.boolean("collect_coin"),
        collect_exp=decoder.boolean("collect_exp"),
        collect_daily_mission=decoder.boolean("collect_daily_mission"),
        collect_weekly_mission=decoder.boolean("collect_weekly_mission"),
        success_delay=decoder.delay_range("success_delay_seconds"),
    )


def _freebies_settings(decoder: SettingsDecoder) -> FreebiesSettings:
    mail = decoder.object("mail")
    supply_pack = decoder.object("supply_pack")
    data_key_decoder = decoder.nullable_object("data_key")
    data_key = None
    if data_key_decoder is not None:
        data_key = DataKeyPlan(force_collect=data_key_decoder.boolean("force_collect"))
        data_key_decoder.finish()
    settings = FreebiesSettings(
        collect_battle_pass=decoder.boolean("collect_battle_pass"),
        data_key=data_key,
        mail=MailCollectionPolicy(
            claim_merit=mail.boolean("claim_merit"),
            claim_maintenance=mail.boolean("claim_maintenance"),
            claim_trade_license=mail.boolean("claim_trade_license"),
            delete_collected=mail.boolean("delete_collected"),
        ),
        supply_pack=SupplyPackPlan(
            collect=supply_pack.boolean("collect"),
            day_of_week=supply_pack.integer("day_of_week", minimum=0, maximum=6),
        ),
        schedule=decoder.daily_schedule("schedule"),
    )
    mail.finish()
    supply_pack.finish()
    return settings


def _private_quarters_settings(decoder: SettingsDecoder) -> PrivateQuartersSettings:
    return PrivateQuartersSettings(
        buy_roses=decoder.boolean("buy_roses"),
        buy_cake=decoder.boolean("buy_cake"),
        target_ship=decoder.nullable_string("target_ship"),
        schedule=decoder.daily_schedule("schedule"),
    )


class _DormTaskFactory:
    __slots__ = ("_workflow",)

    def __init__(self, workflow: DormWorkflow) -> None:
        self._workflow = workflow

    def build(self, context: TaskBuildContext) -> DormTask:
        if not isinstance(context, TaskBuildContext):
            message = "context must be a TaskBuildContext"
            raise TypeError(message)
        if context.definition.command != "dorm":
            message = "dorm factory requires the 'dorm' task definition"
            raise ValueError(message)
        decoder = SettingsDecoder(context.settings, path="$.tasks.dorm")
        settings = _dorm_settings(decoder)
        decoder.finish()
        return DormTask(
            self._workflow,
            settings,
            last_furniture_check_at=_dorm_last_furniture_check(context),
        )


def build_composite_factories(workflows: CompositeWorkflows) -> Mapping[str, TaskFactory]:
    if not isinstance(workflows, CompositeWorkflows):
        message = "workflows must be CompositeWorkflows"
        raise TypeError(message)
    factories: dict[str, TaskFactory] = {
        "dorm": _DormTaskFactory(workflows.dorm),
        "meowfficer": TypedTaskFactory(
            _meowfficer_settings,
            lambda settings: MeowfficerTask(workflows.meowfficer, settings),
        ),
        "guild": TypedTaskFactory(_guild_settings, lambda settings: GuildTask(workflows.guild, settings)),
        "reward": TypedTaskFactory(_reward_settings, lambda settings: RewardTask(workflows.reward, settings)),
        "freebies": TypedTaskFactory(
            _freebies_settings,
            lambda settings: FreebiesTask(
                battle_pass=workflows.battle_pass,
                data_key=workflows.data_key,
                mail=workflows.mail,
                supply_pack=workflows.supply_pack,
                settings=settings,
            ),
        ),
        "private_quarters": TypedTaskFactory(
            _private_quarters_settings,
            lambda settings: PrivateQuartersTask(workflows.private_quarters, settings),
        ),
    }
    return MappingProxyType(factories)
