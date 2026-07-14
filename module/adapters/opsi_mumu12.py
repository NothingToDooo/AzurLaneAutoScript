from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import singledispatch
from typing import TYPE_CHECKING, Protocol, cast, override

import numpy as np

from module.adapters.mumu12 import CancellationAwareMumu12Device
from module.adapters.opsi_live import (
    LiveOperationSirenWorkflow,
    LiveOpsiStep,
    OpsiLiveStepDriver,
    OpsiWorldScheduleSource,
)
from module.base.timer import Timer
from module.config.config import AzurLaneConfig, name_to_function
from module.config.utils import (
    get_nearest_weekday_date,
    get_os_next_reset,
    get_os_reset_remain,
    get_server_next_update,
)
from module.device.device import Device
from module.gameplay.opsi import (
    AbyssalSettings,
    ArchiveSettings,
    AshAssistSettings,
    AshBeaconSettings,
    CrossMonthSettings,
    ExploreSettings,
    Hazard1LevelingSettings,
    MeowfficerFarmingSettings,
    MonthBossMode,
    MonthBossSettings,
    ObscureSettings,
    OpsiDailySettings,
    ShopSettings,
    StrongholdSettings,
    VoucherSettings,
    WorldGeneralSettings,
    WorldOperation,
    WorldSchedule,
    WorldTaskSpec,
    WorldTaskStatus,
)
from module.gameplay.opsi_factories import OpsiWorkflows
from module.gameplay.opsi_progress import (
    WorldBossCursor,
    WorldBossPhase,
    WorldMissionCursor,
    WorldMissionEvidenceKind,
    WorldProgress,
    WorldZoneCursor,
)
from module.meta_reward.meta_reward import MetaReward
from module.os.config import OSConfig
from module.os.operation_siren import OperationSiren
from module.os_ash import assets as ash_assets
from module.os_ash.meta import AshBeaconAssist, MetaState, OpsiAshBeacon
from module.os_handler.action_point import ActionPointLimit
from module.os_handler.assets import OS_MONTHBOSS_HARD, OS_MONTHBOSS_NORMAL
from module.os_shop.assets import OS_SHOP_CHECK
from module.shop.shop_voucher import VoucherShop
from module.task_registry import command_to_config_name
from module.ui.page import page_reward

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from module.config.config_generated import ConfigOverrides
    from module.interaction import CancellationSignal
    from module.os.map import RescanMode


_ASH_ASSIST_RETRY = timedelta(minutes=15)
_ASH_BEACON_ONE_HIT_RETRY = timedelta(minutes=30)
_ASH_BEACON_AUTO_RETRY = timedelta(minutes=15)
_MISSION_RETRY = timedelta(minutes=1)
_CROSS_MONTH_LEAD = timedelta(minutes=10)


def _aware_local(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.astimezone()
    return value


@dataclass(frozen=True, slots=True)
class Mumu12OpsiWorldScheduleSource(OpsiWorldScheduleSource):
    config: AzurLaneConfig

    def __post_init__(self) -> None:
        if not isinstance(self.config, AzurLaneConfig):
            message = "config must be an AzurLaneConfig"
            raise TypeError(message)

    @override
    def snapshot(self, observed_at: datetime) -> WorldSchedule:
        server_update = _aware_local(get_server_next_update(self.config.Scheduler_ServerUpdate))
        while server_update <= observed_at:
            server_update += timedelta(days=1)
        month_reset = _aware_local(get_os_next_reset())
        archive_refresh = _aware_local(get_nearest_weekday_date(target=2))
        return WorldSchedule(
            next_server_update_at=server_update,
            next_month_reset_at=month_reset,
            next_archive_refresh_at=archive_refresh,
        )


class OpsiUiStepExecutor(Protocol):
    def execute(
        self,
        spec: WorldTaskSpec,
        progress: WorldProgress | None,
        cancellation: CancellationSignal,
    ) -> LiveOpsiStep: ...


class Mumu12OperationSirenStepDriver(OpsiLiveStepDriver):
    __slots__ = ("_executor",)

    def __init__(self, executor: OpsiUiStepExecutor) -> None:
        if isinstance(executor, type) or not callable(getattr(executor, "execute", None)):
            message = "executor must implement execute()"
            raise TypeError(message)
        self._executor = executor

    @override
    def execute_step(
        self,
        spec: WorldTaskSpec,
        progress: WorldProgress | None,
        cancellation: CancellationSignal,
    ) -> LiveOpsiStep:
        return self._executor.execute(spec, progress, cancellation)


def _general_overrides(settings: WorldGeneralSettings) -> dict[str, object]:
    return {
        "OpsiGeneral_UseLogger": settings.use_logger,
        "OpsiGeneral_BuyActionPointLimit": settings.buy_action_point_limit,
        "OpsiGeneral_OilLimit": settings.oil_preserve,
        "OpsiGeneral_RepairThreshold": settings.repair_threshold,
        "OpsiGeneral_DoRandomMapEvent": settings.random_map_events,
        "OpsiGeneral_AkashiShopFilter": settings.akashi_shop_filter,
    }


def _fleet_overrides(fleet_index: int, *, use_submarine: bool) -> dict[str, object]:
    return {
        "OpsiFleet_Fleet": fleet_index,
        "OpsiFleet_Submarine": use_submarine,
    }


@singledispatch
def _specific_settings_overrides(settings: object, _progress: WorldProgress | None) -> dict[str, object]:
    message = f"unsupported Operation Siren settings: {type(settings).__name__}"
    raise TypeError(message)


@_specific_settings_overrides.register
def _(settings: AshAssistSettings, _progress: WorldProgress | None) -> dict[str, object]:
    return {"OpsiAshAssist_Tier": settings.minimum_tier}


@_specific_settings_overrides.register
def _(settings: AshBeaconSettings, _progress: WorldProgress | None) -> dict[str, object]:
    return {
        "OpsiAshBeacon_AttackMode": settings.attack_mode.value,
        "OpsiAshBeacon_OneHitMode": settings.one_hit_mode,
        "OpsiAshBeacon_DossierAutoAttackMode": settings.dossier_auto_attack,
        "OpsiAshBeacon_RequestAssist": settings.request_assist,
        "OpsiAshBeacon_EnsureFullyCollected": settings.ensure_fully_collected,
    }


@_specific_settings_overrides.register
def _(settings: ExploreSettings, progress: WorldProgress | None) -> dict[str, object]:
    last_zone = settings.last_zone
    if progress is not None and isinstance(progress.cursor, WorldZoneCursor):
        last_zone = progress.cursor.zone_id
    return {
        **_fleet_overrides(settings.fleet.fleet_index, use_submarine=settings.fleet.use_submarine),
        "OpsiExplore_SpecialRadar": settings.special_radar,
        "OpsiExplore_ForceRun": settings.force_run,
        "OpsiExplore_LastZone": last_zone,
    }


@_specific_settings_overrides.register
def _(settings: ShopSettings, _progress: WorldProgress | None) -> dict[str, object]:
    return {
        "OpsiShop_PresetFilter": settings.preset.value,
        "OpsiShop_CustomFilter": settings.custom_filter,
    }


@_specific_settings_overrides.register
def _(settings: VoucherSettings, _progress: WorldProgress | None) -> dict[str, object]:
    return {"OpsiVoucher_Filter": settings.filter}


@_specific_settings_overrides.register
def _(settings: OpsiDailySettings, _progress: WorldProgress | None) -> dict[str, object]:
    return {
        **_fleet_overrides(settings.fleet.fleet_index, use_submarine=settings.fleet.use_submarine),
        "OpsiDaily_DoMission": settings.do_missions,
        "OpsiDaily_UseTuningSample": settings.use_tuning_samples,
    }


@_specific_settings_overrides.register
def _(settings: ObscureSettings, _progress: WorldProgress | None) -> dict[str, object]:
    return {
        **_fleet_overrides(settings.fleet.fleet_index, use_submarine=settings.fleet.use_submarine),
        "OpsiObscure_ForceRun": settings.force_run,
    }


@_specific_settings_overrides.register
def _(settings: AbyssalSettings, _progress: WorldProgress | None) -> dict[str, object]:
    return {
        "OpsiFleetFilter_Filter": settings.fleet_filter,
        "OpsiAbyssal_ForceRun": settings.force_run,
    }


@_specific_settings_overrides.register
def _(settings: ArchiveSettings, _progress: WorldProgress | None) -> dict[str, object]:
    return {
        **_fleet_overrides(settings.fleet.fleet_index, use_submarine=settings.fleet.use_submarine),
        "OpsiVoucher_Filter": settings.voucher_filter,
    }


@_specific_settings_overrides.register
def _(settings: StrongholdSettings, _progress: WorldProgress | None) -> dict[str, object]:
    return {
        "OpsiFleetFilter_Filter": settings.fleet_filter,
        "OpsiStronghold_ForceRun": settings.force_run,
    }


@_specific_settings_overrides.register
def _(settings: MonthBossSettings, _progress: WorldProgress | None) -> dict[str, object]:
    return {
        "OpsiFleetFilter_Filter": settings.fleet_filter,
        "OpsiMonthBoss_Mode": settings.mode.value,
        "OpsiMonthBoss_CheckAdaptability": settings.check_adaptability,
        "OpsiMonthBoss_ForceRun": settings.force_run,
    }


@_specific_settings_overrides.register
def _(settings: MeowfficerFarmingSettings, _progress: WorldProgress | None) -> dict[str, object]:
    return {
        **_fleet_overrides(settings.fleet.fleet_index, use_submarine=settings.fleet.use_submarine),
        "OpsiMeowfficerFarming_ActionPointPreserve": settings.action_point_preserve,
        "OpsiMeowfficerFarming_HazardLevel": settings.hazard_level,
        "OpsiMeowfficerFarming_TargetZone": settings.target_zone,
        "OpsiAshBeacon_EnsureFullyCollected": settings.ensure_ash_fully_collected,
    }


@_specific_settings_overrides.register
def _(settings: Hazard1LevelingSettings, _progress: WorldProgress | None) -> dict[str, object]:
    return {
        **_fleet_overrides(settings.fleet.fleet_index, use_submarine=settings.fleet.use_submarine),
        "OpsiHazard1Leveling_TargetZone": settings.target_zone,
        "OpsiAshBeacon_EnsureFullyCollected": settings.ensure_ash_fully_collected,
    }


@_specific_settings_overrides.register
def _(_settings: CrossMonthSettings, _progress: WorldProgress | None) -> dict[str, object]:
    # 各阶段的 fleet 由 step runner 直接读取 typed settings，不从其他任务配置反查。
    return {}


def _settings_overrides(spec: WorldTaskSpec, progress: WorldProgress | None) -> Mapping[str, object]:
    settings = spec.settings
    overrides = _specific_settings_overrides(settings, progress)
    general = getattr(settings, "general", None)
    if isinstance(general, WorldGeneralSettings):
        return {**_general_overrides(general), **overrides}
    return overrides


def apply_world_task_spec(
    config: AzurLaneConfig,
    spec: WorldTaskSpec,
    progress: WorldProgress | None,
) -> None:
    """把当前 typed snapshot 投影为仅本次 UI session 可见的运行覆盖。"""

    overrides = cast("ConfigOverrides", dict(_settings_overrides(spec, progress)))
    config.apply_runtime_overlay(**overrides)


def _step(  # noqa: PLR0913 - 单一构造点保持 UI evidence 到闭合 report 字段的一一映射。
    operation: WorldOperation,
    status: WorldTaskStatus,
    *,
    completed_units: int = 0,
    cursor: WorldZoneCursor | WorldMissionCursor | WorldBossCursor | None = None,
    retry_at: datetime | None = None,
    retry_after: timedelta | None = None,
    has_surplus_yellow_coins: bool = False,
    exploration_in_progress: bool = False,
) -> LiveOpsiStep:
    return LiveOpsiStep(
        operation=operation,
        status=status,
        completed_units=completed_units,
        cursor=cursor,
        retry_at=retry_at,
        retry_after=retry_after,
        has_surplus_yellow_coins=has_surplus_yellow_coins,
        exploration_in_progress=exploration_in_progress,
    )


class Mumu12OperationSirenSession(OperationSiren):
    _live_cross_settings: CrossMonthSettings | None = None

    def prepare_live_step(self) -> None:
        """只恢复页面和区域事实；不隐式启动 auto-search。"""

        self.config.apply_runtime_overlay(Submarine_Fleet=1, Submarine_Mode="every_combat", STORY_ALLOW_SKIP=False)
        self._os_init_ensure_page()
        self._os_init_prepare_current_zone()

    def execute_live_step(self, spec: WorldTaskSpec) -> LiveOpsiStep:
        operation = spec.operation
        if operation is WorldOperation.CROSS_MONTH:
            self._live_cross_settings = cast("CrossMonthSettings", spec.settings)
        handlers: Mapping[WorldOperation, Callable[[], LiveOpsiStep]] = {
            WorldOperation.EXPLORE: self._live_explore_step,
            WorldOperation.DAILY: lambda: self._live_daily_step(cast("OpsiDailySettings", spec.settings)),
            WorldOperation.OBSCURE: lambda: self._live_obscure_step(cast("ObscureSettings", spec.settings)),
            WorldOperation.ABYSSAL: self._live_abyssal_step,
            WorldOperation.ARCHIVE: self._live_archive_step,
            WorldOperation.STRONGHOLD: self._live_stronghold_step,
            WorldOperation.MONTH_BOSS: lambda: self._live_month_boss_step(cast("MonthBossSettings", spec.settings)),
            WorldOperation.MEOWFFICER_FARMING: self._live_meowfficer_step,
            WorldOperation.HAZARD1_LEVELING: self._live_hazard1_step,
            WorldOperation.SHOP: self._live_shop_one_shot,
            WorldOperation.VOUCHER: self._live_voucher_one_shot,
            WorldOperation.CROSS_MONTH: self._live_cross_month_one_shot,
        }
        try:
            handler = handlers[operation]
        except KeyError as exc:
            message = f"unsupported world Operation Siren step: {operation.value}"
            raise ValueError(message) from exc
        return handler()

    def _live_explore_step(self) -> LiveOpsiStep:
        order = self._os_explore_order()
        if not order:
            return _step(WorldOperation.EXPLORE, WorldTaskStatus.COMPLETED)
        zone_id = order[0]
        if self._skip_cleared_os_explore_zone(zone_id):
            return _step(
                WorldOperation.EXPLORE,
                WorldTaskStatus.IN_PROGRESS,
                completed_units=1,
                cursor=WorldZoneCursor(zone_id),
            )
        self._os_explore_failed_zone = []
        self._run_os_explore_zone(zone_id)
        return _step(
            WorldOperation.EXPLORE,
            WorldTaskStatus.IN_PROGRESS,
            completed_units=1,
            cursor=WorldZoneCursor(zone_id),
        )

    def _finish_one_mission(
        self,
        *,
        question: bool,
        rescan: RescanMode | bool | None,
    ) -> WorldMissionCursor | None:
        checkout = self.os_get_next_mission()
        if not checkout:
            return None
        if checkout != "pinned_at_archive_zone":
            self.zone_init()
        if checkout == "already_at_mission_zone":
            self.globe_goto(self.zone, refresh=True)
        self.fleet_set(self.config.OpsiFleet_Fleet)
        self.os_order_execute(
            recon_scan=False,
            submarine_call=self.config.OpsiFleet_Submarine and checkout != "pinned_at_archive_zone",
        )
        self.run_auto_search(question=question, rescan=rescan)
        self.handle_after_auto_search()
        if checkout == "pinned_at_archive_zone":
            return WorldMissionCursor(WorldMissionEvidenceKind.ARCHIVE_ZONE)
        zone_id = getattr(self.zone, "zone_id", 0)
        evidence_kind = (
            WorldMissionEvidenceKind.CURRENT_ZONE
            if checkout == "already_at_mission_zone"
            else WorldMissionEvidenceKind.PINNED_ZONE
        )
        return WorldMissionCursor(evidence_kind, zone_id)

    def _live_daily_step(self, settings: OpsiDailySettings) -> LiveOpsiStep:
        if settings.use_tuning_samples:
            self.tuning_sample_use()
        if not settings.do_missions:
            return _step(WorldOperation.DAILY, WorldTaskStatus.COMPLETED)
        if self.is_in_opsi_explore():
            return _step(WorldOperation.DAILY, WorldTaskStatus.EXPLORE_IN_PROGRESS)
        accepted_all = self.os_mission_overview_accept()
        self.zone_init()
        mission = self._finish_one_mission(question=True, rescan=None)
        if mission is not None:
            return _step(
                WorldOperation.DAILY,
                WorldTaskStatus.IN_PROGRESS,
                completed_units=1,
                cursor=mission,
            )
        if accepted_all:
            return _step(WorldOperation.DAILY, WorldTaskStatus.COMPLETED)
        return _step(WorldOperation.DAILY, WorldTaskStatus.FAILED, retry_after=_MISSION_RETRY)

    def _live_obscure_step(self, settings: ObscureSettings) -> LiveOpsiStep:
        self.cl1_ap_preserve()
        found = self.storage_get_next_item("OBSCURE", use_logger=self.config.OpsiGeneral_UseLogger)
        if not found:
            return _step(WorldOperation.OBSCURE, WorldTaskStatus.EMPTY)
        self.config.apply_runtime_overlay(OpsiGeneral_DoRandomMapEvent=False, HOMO_EDGE_DETECT=False, STORY_OPTION=0)
        self.zone_init()
        zone_id = self.zone.zone_id
        self.fleet_set(self.config.OpsiFleet_Fleet)
        self.os_order_execute(recon_scan=True, submarine_call=self.config.OpsiFleet_Submarine)
        self.run_auto_search(rescan="current")
        self.map_exit()
        self.handle_after_auto_search()
        if not settings.force_run:
            return _step(WorldOperation.OBSCURE, WorldTaskStatus.COMPLETED, completed_units=1)
        return _step(
            WorldOperation.OBSCURE,
            WorldTaskStatus.IN_PROGRESS,
            completed_units=1,
            cursor=WorldZoneCursor(zone_id),
        )

    def _live_abyssal_step(self) -> LiveOpsiStep:
        self.cl1_ap_preserve()
        with self.config.temporary(STORY_ALLOW_SKIP=False):
            found = self.storage_get_next_item("ABYSSAL", use_logger=self.config.OpsiGeneral_UseLogger)
        if not found:
            return _step(WorldOperation.ABYSSAL, WorldTaskStatus.EMPTY)
        self.config.apply_runtime_overlay(OpsiGeneral_DoRandomMapEvent=False, HOMO_EDGE_DETECT=False, STORY_OPTION=0)
        self.zone_init()
        zone_id = self.zone.zone_id
        if not self.run_abyssal():
            return _step(WorldOperation.ABYSSAL, WorldTaskStatus.FAILED)
        self.fleet_repair(revert=False)
        return _step(
            WorldOperation.ABYSSAL,
            WorldTaskStatus.IN_PROGRESS,
            completed_units=1,
            cursor=WorldZoneCursor(zone_id),
        )

    def _live_archive_step(self) -> LiveOpsiStep:
        if self.is_in_opsi_explore():
            return _step(WorldOperation.ARCHIVE, WorldTaskStatus.EXPLORE_IN_PROGRESS)
        mission = self._finish_one_mission(question=False, rescan=False)
        if mission is not None:
            return _step(
                WorldOperation.ARCHIVE,
                WorldTaskStatus.IN_PROGRESS,
                completed_units=1,
                cursor=mission,
            )
        shop = VoucherShop(self.config, self.device)
        self._os_voucher_enter()
        bought = shop.run_once()
        self._os_voucher_exit()
        if not bought:
            return _step(WorldOperation.ARCHIVE, WorldTaskStatus.COMPLETED)
        return _step(
            WorldOperation.ARCHIVE,
            WorldTaskStatus.IN_PROGRESS,
            completed_units=1,
            cursor=WorldMissionCursor(WorldMissionEvidenceKind.LOGGER_PURCHASE),
        )

    def _live_stronghold_step(self) -> LiveOpsiStep:
        self.cl1_ap_preserve()
        self.os_map_goto_globe()
        self.globe_update()
        zone = self.find_siren_stronghold()
        if zone is None:
            return _step(WorldOperation.STRONGHOLD, WorldTaskStatus.EMPTY)
        zone_id = zone.zone_id
        self.globe_enter(zone)
        self.zone_init()
        self.os_order_execute(recon_scan=True, submarine_call=False)
        if not self.run_stronghold():
            return _step(WorldOperation.STRONGHOLD, WorldTaskStatus.FAILED)
        self.fleet_repair(revert=False)
        self.handle_fleet_resolve(revert=False)
        return _step(
            WorldOperation.STRONGHOLD,
            WorldTaskStatus.IN_PROGRESS,
            completed_units=1,
            cursor=WorldZoneCursor(zone_id),
        )

    def _live_month_boss_step(  # noqa: PLR0911 - 每个 return 对应一种真实观测终态。
        self,
        settings: MonthBossSettings,
    ) -> LiveOpsiStep:
        if self.is_in_opsi_explore():
            return _step(WorldOperation.MONTH_BOSS, WorldTaskStatus.EXPLORE_IN_PROGRESS)
        self.os_mission_enter()
        if self.appear(OS_MONTHBOSS_NORMAL, offset=(20, 20)):
            phase = WorldBossPhase.NORMAL
            is_normal = True
        elif self.appear(OS_MONTHBOSS_HARD, offset=(20, 20)):
            phase = WorldBossPhase.HARD
            is_normal = False
        else:
            self.os_mission_quit()
            return _step(WorldOperation.MONTH_BOSS, WorldTaskStatus.EMPTY)
        self.os_mission_quit()
        if not is_normal and settings.mode is MonthBossMode.NORMAL:
            return _step(WorldOperation.MONTH_BOSS, WorldTaskStatus.COMPLETED)
        if settings.check_adaptability:
            self.os_map_goto_globe(unpin=False)
            adaptability = self.get_adaptability()
            if (np.array(adaptability) < (203, 203, 156)).any():
                return _step(WorldOperation.MONTH_BOSS, WorldTaskStatus.RESOURCE_LIMIT)
        self.globe_goto(154)
        self.go_month_boss_room(is_normal=is_normal)
        cleared = self.boss_clear(has_fleet_step=True, is_month=True)
        self.fleet_repair(revert=False)
        self.handle_fleet_resolve(revert=False)
        if not cleared:
            return _step(WorldOperation.MONTH_BOSS, WorldTaskStatus.FAILED)
        if is_normal and settings.mode is MonthBossMode.NORMAL_HARD:
            return _step(
                WorldOperation.MONTH_BOSS,
                WorldTaskStatus.IN_PROGRESS,
                completed_units=1,
                cursor=WorldBossCursor(phase),
            )
        return _step(WorldOperation.MONTH_BOSS, WorldTaskStatus.COMPLETED, completed_units=1)

    def _live_meowfficer_step(self) -> LiveOpsiStep:
        if self.is_in_opsi_explore():
            return _step(WorldOperation.MEOWFFICER_FARMING, WorldTaskStatus.EXPLORE_IN_PROGRESS)
        preserve = min(
            self.get_action_point_limit(),
            self.config.OpsiMeowfficerFarming_ActionPointPreserve,
            2000,
        )
        if self.is_cl1_enabled and preserve < 1000:
            preserve = 1000
        if preserve == 0:
            self.config.apply_runtime_overlay(OpsiFleet_Submarine=False)
        if self.is_cl1_enabled:
            self.config.apply_runtime_overlay(
                OpsiGeneral_DoRandomMapEvent=True,
                OpsiGeneral_AkashiShopFilter="ActionPoint",
                OpsiFleet_Submarine=False,
            )
            cooling = self.nearest_task_cooling_down
            if cooling is not None and get_os_reset_remain() > 0 and isinstance(cooling.next_run, datetime):
                return _step(
                    WorldOperation.MEOWFFICER_FARMING,
                    WorldTaskStatus.COOLDOWN,
                    retry_at=_aware_local(cooling.next_run),
                )
        self._apply_meowfficer_action_point_preserve(preserve)
        self._check_meowfficer_action_points()
        zone, refresh = self._next_meowfficer_farming_zone()
        zone_id = zone.zone_id
        self._run_meowfficer_farming_zone(zone, refresh=refresh)
        return _step(
            WorldOperation.MEOWFFICER_FARMING,
            WorldTaskStatus.IN_PROGRESS,
            completed_units=1,
            cursor=WorldZoneCursor(zone_id),
        )

    def _live_hazard1_step(self) -> LiveOpsiStep:
        self.config.apply_runtime_overlay(
            OpsiGeneral_DoRandomMapEvent=True,
            OpsiGeneral_AkashiShopFilter="ActionPoint",
        )
        self.config.OS_ACTION_POINT_PRESERVE = 200
        if (
            self.config.is_task_enabled("OpsiAshBeacon")
            and not self._ash_fully_collected
            and self.config.OpsiAshBeacon_EnsureFullyCollected
        ):
            self.config.OS_ACTION_POINT_PRESERVE = 0
        if self.get_yellow_coins() < self.config.OS_CL1_YELLOW_COINS_PRESERVE:
            return _step(
                WorldOperation.HAZARD1_LEVELING,
                WorldTaskStatus.RESOURCE_LIMIT,
                exploration_in_progress=self.is_in_opsi_explore(),
            )
        self.get_current_zone()
        keep_current_ap = self.config.OpsiGeneral_BuyActionPointLimit <= 0
        self.action_point_set(cost=70, keep_current_ap=keep_current_ap, check_rest_ap=True)
        if self._action_point_total >= 3000:
            return _step(
                WorldOperation.HAZARD1_LEVELING,
                WorldTaskStatus.RESOURCE_LIMIT,
                exploration_in_progress=self.is_in_opsi_explore(),
            )
        zone_id = self.config.OpsiHazard1Leveling_TargetZone or 22
        if self.zone.zone_id != zone_id or not self.is_zone_name_hidden:
            self.globe_goto(self.name_to_zone(zone_id), types=("SAFE",), refresh=True)
        self.fleet_set(self.config.OpsiFleet_Fleet)
        self.run_strategic_search()
        self.handle_after_auto_search()
        return _step(
            WorldOperation.HAZARD1_LEVELING,
            WorldTaskStatus.IN_PROGRESS,
            completed_units=1,
            cursor=WorldZoneCursor(zone_id),
        )

    def _live_shop_one_shot(self) -> LiveOpsiStep:
        if not self.zone.is_azur_port:
            self.globe_goto(self.zone_nearest_azur_port(self.zone))
        self.port_enter()
        self.port_shop_enter()
        if self.appear(OS_SHOP_CHECK):
            not_empty = self.handle_port_supply_buy()
            retry_at = self._os_shop_delay(not_empty=not_empty)
            status = WorldTaskStatus.COMPLETED
        else:
            retry_at = get_os_next_reset()
            status = WorldTaskStatus.EMPTY
        self.port_shop_quit()
        self.port_quit()
        return _step(WorldOperation.SHOP, status, retry_at=_aware_local(retry_at))

    def _live_voucher_one_shot(self) -> LiveOpsiStep:
        self._os_voucher_enter()
        VoucherShop(self.config, self.device).run()
        self._os_voucher_exit()
        return _step(WorldOperation.VOUCHER, WorldTaskStatus.COMPLETED)

    def _cross_config_int(self, path: str) -> int:
        settings = self._live_cross_settings
        if settings is None:
            message = "cross-month typed settings were not installed"
            raise RuntimeError(message)
        values = {
            "OpsiDaily.OpsiFleet.Fleet": settings.daily_fleet.fleet_index,
            "OpsiObscure.OpsiFleet.Fleet": settings.obscure_fleet.fleet_index,
            "OpsiMeowfficerFarming.OpsiFleet.Fleet": settings.meowfficer_fleet.fleet_index,
        }
        try:
            return values[path]
        except KeyError as exc:
            message = f"unsupported typed cross-month integer setting: {path}"
            raise ValueError(message) from exc

    def _cross_config_str(self, path: str) -> str:
        settings = self._live_cross_settings
        if settings is None:
            message = "cross-month typed settings were not installed"
            raise RuntimeError(message)
        if path == "OpsiAbyssal.OpsiFleetFilter.Filter":
            return settings.abyssal_fleet_filter
        message = f"unsupported typed cross-month string setting: {path}"
        raise ValueError(message)

    def _live_cross_month_one_shot(self) -> LiveOpsiStep:
        next_reset = get_os_next_reset()
        now = datetime.now()
        if next_reset < now:
            message = f"invalid Operation Siren reset: {next_reset} < {now}"
            raise RuntimeError(message)
        if next_reset - now > _CROSS_MONTH_LEAD:
            return _step(
                WorldOperation.CROSS_MONTH,
                WorldTaskStatus.EMPTY,
                retry_at=_aware_local(next_reset - _CROSS_MONTH_LEAD),
            )
        self._wait_until_opsi_reset(next_reset)
        try:
            self._live_clear_daily_after_reset()
            self._clear_opsi_monthly_items()
            self._run_opsi_meowfficer_farming_after_reset()
        except ActionPointLimit:
            return _step(WorldOperation.CROSS_MONTH, WorldTaskStatus.COMPLETED)
        message = "cross-month farming returned without reaching its action-point boundary"
        raise RuntimeError(message)

    def _live_clear_daily_after_reset(self) -> None:
        """执行跨月日常策略，但不读取 scheduler switch。"""

        self.config.apply_runtime_overlay(
            OpsiGeneral_DoRandomMapEvent=True,
            OpsiFleet_Fleet=self._cross_config_int("OpsiDaily.OpsiFleet.Fleet"),
            OpsiFleet_Submarine=False,
        )
        completed = 0
        empty_trials = 0
        while empty_trials < 5:
            accepted_all = self.os_mission_overview_accept()
            self.zone_init()
            mission = self._finish_one_mission(question=True, rescan=None)
            if mission is not None:
                completed += 1
                continue
            if completed and accepted_all:
                return
            empty_trials += 1
            self.device.sleep(60)


class _AshAssistStepRunner(AshBeaconAssist):
    def execute_live_step(self) -> LiveOpsiStep:
        self.ui_ensure(page_reward)
        self._ensure_meta_assist_page()
        timeout = Timer(3, count=9).start()
        skip_first_screenshot = True
        while True:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()
            if self.handle_map_event():
                continue
            if self.appear(ash_assets.ASH_START, offset=(20, 20)):
                remain_times = self.digit_ocr_point_and_check(ash_assets.BEACON_REMAIN, 1)
                if not remain_times:
                    MetaReward(self.config, self.device).run()
                    return _step(WorldOperation.ASH_ASSIST, WorldTaskStatus.COMPLETED)
                self._ensure_meta_level()
                self._make_an_attack()
                return _step(
                    WorldOperation.ASH_ASSIST,
                    WorldTaskStatus.IN_PROGRESS,
                    completed_units=1,
                )
            if timeout.reached():
                return _step(
                    WorldOperation.ASH_ASSIST,
                    WorldTaskStatus.EMPTY,
                    retry_after=_ASH_ASSIST_RETRY,
                )


class _AshBeaconStepRunner(OpsiAshBeacon):
    def execute_live_step(self) -> LiveOpsiStep:
        self.ui_ensure(page_reward)
        self._ensure_meta_page()
        skip_first_screenshot = True
        while True:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()
            if self.handle_map_event():
                continue
            state = self._get_state()
            if state is MetaState.UNDEFINED:
                continue
            if state is MetaState.INIT:
                if not self._begin_meta():
                    return _step(WorldOperation.ASH_BEACON, WorldTaskStatus.EMPTY)
                continue
            if state is MetaState.COMPLETE:
                return self._complete_meta_reward_step()
            result = self._attacking_meta_step()
            if result is not None:
                return result

    def _complete_meta_reward_step(self) -> LiveOpsiStep:
        self._set_completed_meta_category()
        category = self._meta_category
        self._handle_ash_beacon_reward()
        if category != "undefined":
            MetaReward(self.config, self.device).run(category=category)
        return _step(
            WorldOperation.ASH_BEACON,
            WorldTaskStatus.IN_PROGRESS,
            completed_units=1,
        )

    def _attacking_meta_step(self) -> LiveOpsiStep | None:
        is_beacon = self.appear(ash_assets.BEACON_LIST, offset=(20, 20))
        if is_beacon and self.config.OpsiAshBeacon_OneHitMode and self._get_meta_damage() > 0:
            return _step(
                WorldOperation.ASH_BEACON,
                WorldTaskStatus.COOLDOWN,
                retry_after=_ASH_BEACON_ONE_HIT_RETRY,
            )
        is_dossier = self.appear(ash_assets.DOSSIER_LIST, offset=(20, 20))
        if is_dossier and self.appear(ash_assets.META_AUTO_ATTACKING, offset=(20, 20)):
            return _step(
                WorldOperation.ASH_BEACON,
                WorldTaskStatus.COOLDOWN,
                retry_after=_ASH_BEACON_AUTO_RETRY,
            )
        if not self._pre_attack():
            return None
        if is_dossier and self.appear(ash_assets.META_AUTO_ATTACKING, offset=(20, 20)):
            return _step(
                WorldOperation.ASH_BEACON,
                WorldTaskStatus.IN_PROGRESS,
                completed_units=1,
            )
        self._make_an_attack()
        return _step(
            WorldOperation.ASH_BEACON,
            WorldTaskStatus.IN_PROGRESS,
            completed_units=1,
        )


class _Mumu12OpsiExecutor(OpsiUiStepExecutor):
    __slots__ = ("_config", "_device")

    def __init__(self, config: AzurLaneConfig, device: Device) -> None:
        if not isinstance(config, AzurLaneConfig):
            message = "config must be an AzurLaneConfig"
            raise TypeError(message)
        if not isinstance(device, Device):
            message = "device must be a Device"
            raise TypeError(message)
        self._config = config
        self._device = device

    @override
    def execute(
        self,
        spec: WorldTaskSpec,
        progress: WorldProgress | None,
        cancellation: CancellationSignal,
    ) -> LiveOpsiStep:
        cancellation.raise_if_requested()
        self._config.replace_runtime_overlay()
        task = name_to_function(command_to_config_name(spec.task_id.value))
        self._config.task = task
        self._config.bind(task)
        self._config.merge(OSConfig())
        apply_world_task_spec(self._config, spec, progress)
        checked_device = cast("Device", CancellationAwareMumu12Device(self._device, cancellation))
        if spec.operation is WorldOperation.ASH_ASSIST:
            runner = _AshAssistStepRunner(self._config, checked_device)
            return runner.execute_live_step()
        if spec.operation is WorldOperation.ASH_BEACON:
            runner = _AshBeaconStepRunner(self._config, checked_device)
            return runner.execute_live_step()

        runner = Mumu12OperationSirenSession(self._config, checked_device)
        runner.prepare_live_step()
        try:
            return runner.execute_live_step(spec)
        except ActionPointLimit:
            surplus = False
            if spec.operation is WorldOperation.MEOWFFICER_FARMING:
                surplus = runner.get_yellow_coins() > runner.config.OS_CL1_YELLOW_COINS_PRESERVE
            return _step(
                spec.operation,
                WorldTaskStatus.ACTION_POINT_LIMIT,
                has_surplus_yellow_coins=surplus,
            )


def build_mumu12_operation_siren_workflow(
    config: AzurLaneConfig,
    device: Device,
) -> LiveOperationSirenWorkflow:
    """构造 MuMu12 UI driver 的 production OperationSirenWorkflow。"""

    executor = _Mumu12OpsiExecutor(config, device)
    driver = Mumu12OperationSirenStepDriver(executor)
    return LiveOperationSirenWorkflow(driver, Mumu12OpsiWorldScheduleSource(config))


def build_mumu12_opsi_workflows(config: AzurLaneConfig, device: Device) -> OpsiWorkflows:
    """供游戏 composition root 直接注入的 production OpSi 依赖。"""

    return OpsiWorkflows(world=build_mumu12_operation_siren_workflow(config, device))
