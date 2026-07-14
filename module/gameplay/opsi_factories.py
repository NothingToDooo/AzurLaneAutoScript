from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING

from module.application import TaskId
from module.gameplay.opsi import (
    WORLD_TASK_DEFINITIONS,
    AbyssalSettings,
    ArchiveSettings,
    AshAssistSettings,
    AshBeaconAttackMode,
    AshBeaconSettings,
    CrossMonthSettings,
    ExploreSettings,
    FleetSettings,
    Hazard1LevelingSettings,
    MeowfficerFarmingSettings,
    MonthBossMode,
    MonthBossSettings,
    ObscureSettings,
    OperationSirenTask,
    OperationSirenWorkflow,
    OpsiDailySettings,
    OpsiShopPreset,
    ShopSettings,
    StrongholdSettings,
    VoucherSettings,
    WorldCheckpointMode,
    WorldGeneralSettings,
    WorldOperation,
    WorldProgress,
    WorldTaskSettings,
    create_operation_siren_task,
)
from module.gameplay.opsi_progress import hydrate_world_progress
from module.runtime import (
    FactoryCoverageError,
    SettingsDecoder,
    SettingsDocumentError,
    TaskBuildContext,
    TaskStateDocumentError,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from module.runtime import TaskFactory


def _require_execute(value: object, *, field_name: str) -> None:
    if isinstance(value, type) or not callable(getattr(value, "execute", None)):
        message = f"{field_name} must implement execute()"
        raise TypeError(message)


@dataclass(frozen=True, slots=True)
class OpsiWorkflows:
    world: OperationSirenWorkflow

    def __post_init__(self) -> None:
        _require_execute(self.world, field_name="world")


def _general(decoder: SettingsDecoder) -> WorldGeneralSettings:
    general = decoder.object("general")
    settings = WorldGeneralSettings(
        use_logger=general.boolean("use_logger"),
        buy_action_point_limit=general.integer("buy_action_point_limit", minimum=0, maximum=5),
        oil_preserve=general.integer("oil_preserve", minimum=0),
        repair_threshold=general.number("repair_threshold", minimum=-1.0, maximum=1.0),
        random_map_events=general.boolean("random_map_events"),
        akashi_shop_filter=general.string("akashi_shop_filter"),
    )
    general.finish()
    return settings


def _fleet(decoder: SettingsDecoder, name: str = "fleet") -> FleetSettings:
    fleet = decoder.object(name)
    settings = FleetSettings(
        fleet_index=fleet.integer("fleet_index", minimum=1, maximum=4),
        use_submarine=fleet.boolean("use_submarine"),
    )
    fleet.finish()
    return settings


def _integer_choice(
    decoder: SettingsDecoder,
    name: str,
    allowed: tuple[int, ...],
    *,
    task_id: str,
) -> int:
    value = decoder.integer(name)
    if value not in allowed:
        message = f"$.tasks.{task_id}.{name} must be one of {list(allowed)}"
        raise SettingsDocumentError(message)
    return value


def _ash_assist_settings(decoder: SettingsDecoder) -> AshAssistSettings:
    return AshAssistSettings(minimum_tier=decoder.integer("minimum_tier", minimum=1))


def _ash_beacon_settings(decoder: SettingsDecoder) -> AshBeaconSettings:
    return AshBeaconSettings(
        attack_mode=decoder.enum("attack_mode", AshBeaconAttackMode),
        one_hit_mode=decoder.boolean("one_hit_mode"),
        dossier_auto_attack=decoder.boolean("dossier_auto_attack"),
        request_assist=decoder.boolean("request_assist"),
        ensure_fully_collected=decoder.boolean("ensure_fully_collected"),
    )


def _explore_settings(decoder: SettingsDecoder) -> ExploreSettings:
    return ExploreSettings(
        general=_general(decoder),
        fleet=_fleet(decoder),
        special_radar=decoder.boolean("special_radar"),
        force_run=decoder.boolean("force_run"),
        last_zone=decoder.integer("last_zone", minimum=0),
    )


def _shop_settings(decoder: SettingsDecoder) -> ShopSettings:
    return ShopSettings(
        general=_general(decoder),
        preset=decoder.enum("preset", OpsiShopPreset),
        custom_filter=decoder.string("custom_filter"),
    )


def _voucher_settings(decoder: SettingsDecoder) -> VoucherSettings:
    return VoucherSettings(
        general=_general(decoder),
        filter=decoder.string("filter"),
    )


def _daily_settings(decoder: SettingsDecoder) -> OpsiDailySettings:
    return OpsiDailySettings(
        general=_general(decoder),
        fleet=_fleet(decoder),
        do_missions=decoder.boolean("do_missions"),
        use_tuning_samples=decoder.boolean("use_tuning_samples"),
    )


def _obscure_settings(decoder: SettingsDecoder) -> ObscureSettings:
    return ObscureSettings(
        general=_general(decoder),
        fleet=_fleet(decoder),
        force_run=decoder.boolean("force_run"),
    )


def _abyssal_settings(decoder: SettingsDecoder) -> AbyssalSettings:
    return AbyssalSettings(
        general=_general(decoder),
        fleet_filter=decoder.string("fleet_filter"),
        force_run=decoder.boolean("force_run"),
    )


def _archive_settings(decoder: SettingsDecoder) -> ArchiveSettings:
    return ArchiveSettings(
        general=_general(decoder),
        fleet=_fleet(decoder),
        voucher_filter=decoder.string("voucher_filter"),
    )


def _stronghold_settings(decoder: SettingsDecoder) -> StrongholdSettings:
    return StrongholdSettings(
        general=_general(decoder),
        fleet_filter=decoder.string("fleet_filter"),
        force_run=decoder.boolean("force_run"),
    )


def _month_boss_settings(decoder: SettingsDecoder) -> MonthBossSettings:
    return MonthBossSettings(
        general=_general(decoder),
        fleet_filter=decoder.string("fleet_filter"),
        mode=decoder.enum("mode", MonthBossMode),
        check_adaptability=decoder.boolean("check_adaptability"),
        force_run=decoder.boolean("force_run"),
    )


def _meowfficer_settings(decoder: SettingsDecoder) -> MeowfficerFarmingSettings:
    return MeowfficerFarmingSettings(
        general=_general(decoder),
        fleet=_fleet(decoder),
        action_point_preserve=decoder.integer("action_point_preserve", minimum=0, maximum=2000),
        hazard_level=_integer_choice(
            decoder,
            "hazard_level",
            (3, 4, 5, 6, 10),
            task_id="opsi_meowfficer_farming",
        ),
        target_zone=decoder.integer("target_zone", minimum=0),
        ensure_ash_fully_collected=decoder.boolean("ensure_ash_fully_collected"),
    )


def _hazard1_settings(decoder: SettingsDecoder) -> Hazard1LevelingSettings:
    return Hazard1LevelingSettings(
        general=_general(decoder),
        fleet=_fleet(decoder),
        target_zone=_integer_choice(
            decoder,
            "target_zone",
            (0, 22, 44),
            task_id="opsi_hazard1_leveling",
        ),
        ensure_ash_fully_collected=decoder.boolean("ensure_ash_fully_collected"),
    )


def _cross_month_settings(decoder: SettingsDecoder) -> CrossMonthSettings:
    return CrossMonthSettings(
        general=_general(decoder),
        daily_fleet=FleetSettings(
            fleet_index=decoder.integer("daily_fleet_index", minimum=1, maximum=4),
            use_submarine=False,
        ),
        obscure_fleet=FleetSettings(
            fleet_index=decoder.integer("obscure_fleet_index", minimum=1, maximum=4),
            use_submarine=False,
        ),
        abyssal_fleet_filter=decoder.string("abyssal_fleet_filter"),
        meowfficer_fleet=FleetSettings(
            fleet_index=decoder.integer("meowfficer_fleet_index", minimum=1, maximum=4),
            use_submarine=False,
        ),
    )


def _task(
    task_id: str,
    workflow: OperationSirenWorkflow,
    settings: WorldTaskSettings,
    progress: WorldProgress | None,
) -> OperationSirenTask:
    return create_operation_siren_task(TaskId(task_id), workflow, settings, progress)


class _OpsiTaskFactory:
    __slots__ = ("_decode", "_operation", "_workflow")

    def __init__(
        self,
        operation: WorldOperation,
        workflow: OperationSirenWorkflow,
        decode: Callable[[SettingsDecoder], WorldTaskSettings],
    ) -> None:
        self._operation = operation
        self._workflow = workflow
        self._decode = decode

    def build(self, context: TaskBuildContext) -> OperationSirenTask:
        if not isinstance(context, TaskBuildContext):
            message = "context must be a TaskBuildContext"
            raise TypeError(message)
        if context.definition.command != self._operation.value:
            message = "TaskBuildContext definition does not match Operation Siren factory"
            raise ValueError(message)
        decoder = SettingsDecoder(context.settings, path=f"$.tasks.{self._operation.value}")
        settings = self._decode(decoder)
        decoder.finish()

        definition = WORLD_TASK_DEFINITIONS[TaskId(self._operation.value)]
        if definition.checkpoint_mode is WorldCheckpointMode.ONE_SHOT:
            if context.task_state.entries:
                message = f"one-shot operation must not contain task state: {self._operation.value}"
                raise TaskStateDocumentError(message)
            progress = None
        else:
            progress = hydrate_world_progress(self._operation, context.task_state)
        return _task(self._operation.value, self._workflow, settings, progress)


def _factory(
    operation: WorldOperation,
    workflow: OperationSirenWorkflow,
    decode: Callable[[SettingsDecoder], WorldTaskSettings],
) -> _OpsiTaskFactory:
    return _OpsiTaskFactory(operation, workflow, decode)


def build_opsi_factories(workflows: OpsiWorkflows) -> Mapping[str, TaskFactory]:
    if not isinstance(workflows, OpsiWorkflows):
        message = "workflows must be OpsiWorkflows"
        raise TypeError(message)
    factories: dict[str, TaskFactory] = {
        "opsi_ash_assist": _factory(WorldOperation.ASH_ASSIST, workflows.world, _ash_assist_settings),
        "opsi_ash_beacon": _factory(WorldOperation.ASH_BEACON, workflows.world, _ash_beacon_settings),
        "opsi_explore": _factory(WorldOperation.EXPLORE, workflows.world, _explore_settings),
        "opsi_shop": _factory(WorldOperation.SHOP, workflows.world, _shop_settings),
        "opsi_voucher": _factory(WorldOperation.VOUCHER, workflows.world, _voucher_settings),
        "opsi_daily": _factory(WorldOperation.DAILY, workflows.world, _daily_settings),
        "opsi_obscure": _factory(WorldOperation.OBSCURE, workflows.world, _obscure_settings),
        "opsi_month_boss": _factory(WorldOperation.MONTH_BOSS, workflows.world, _month_boss_settings),
        "opsi_abyssal": _factory(WorldOperation.ABYSSAL, workflows.world, _abyssal_settings),
        "opsi_archive": _factory(WorldOperation.ARCHIVE, workflows.world, _archive_settings),
        "opsi_stronghold": _factory(WorldOperation.STRONGHOLD, workflows.world, _stronghold_settings),
        "opsi_meowfficer_farming": _factory(
            WorldOperation.MEOWFFICER_FARMING,
            workflows.world,
            _meowfficer_settings,
        ),
        "opsi_hazard1_leveling": _factory(
            WorldOperation.HAZARD1_LEVELING,
            workflows.world,
            _hazard1_settings,
        ),
        "opsi_cross_month": _factory(WorldOperation.CROSS_MONTH, workflows.world, _cross_month_settings),
    }
    expected = {task_id.value for task_id in WORLD_TASK_DEFINITIONS}
    if set(factories) != expected:
        missing = sorted(expected - set(factories))
        unknown = sorted(set(factories) - expected)
        message = f"OpSi factory coverage mismatch: missing={missing}, unknown={unknown}"
        raise FactoryCoverageError(message)
    return MappingProxyType(factories)
