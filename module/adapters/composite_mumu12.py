from calendar import day_name
from datetime import UTC, datetime
from types import MappingProxyType
from typing import TYPE_CHECKING, Protocol, cast, override

from module.adapters.mumu12 import CancellationAwareMumu12Device
from module.config.config import AzurLaneConfig, name_to_function
from module.config.utils import get_server_weekday
from module.device.device import Device
from module.dorm.dorm import RewardDorm
from module.freebies.assets import FREE_SUPPLY_PACK
from module.freebies.battle_pass import BattlePass
from module.freebies.data_key import DataKey
from module.freebies.mail_white import MailWhite
from module.freebies.supply_pack import SupplyPack250814
from module.gameplay.composite import (
    DataKeyPlan,
    DataKeyWorkflow,
    DormReport,
    DormRunRequest,
    DormWorkflow,
    FreebieCollectionReport,
    FreebieCollectionWorkflow,
    GuildReport,
    GuildSettings,
    GuildWorkflow,
    MailCollectionPolicy,
    MailCollectionWorkflow,
    MeowfficerReport,
    MeowfficerSettings,
    MeowfficerTrainingMode,
    MeowfficerWorkflow,
    PrivateQuartersInteractionStatus,
    PrivateQuartersReport,
    PrivateQuartersSettings,
    PrivateQuartersWorkflow,
    RewardReport,
    RewardSettings,
    RewardWorkflow,
    SupplyPackPlan,
    SupplyPackWorkflow,
)
from module.gameplay.composite_factories import CompositeWorkflows
from module.guild.guild_reward import RewardGuild
from module.logger import logger
from module.meowfficer.meowfficer import RewardMeowfficer
from module.private_quarters.private_quarters import PrivateQuarters
from module.reward.reward import Reward
from module.ui.page import (
    page_archives,
    page_campaign_menu,
    page_dormmenu,
    page_guild,
    page_main,
    page_meowfficer,
    page_private_quarters,
    page_reward,
    page_shop,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from module.application import CancellationSource
    from module.config.config_generated import ConfigOverrides


class CompositeLiveClock(Protocol):
    def now(self) -> datetime: ...


class SystemCompositeLiveClock:
    @staticmethod
    def now() -> datetime:
        return datetime.now(tz=UTC)


def _activate(
    config: AzurLaneConfig,
    device: Device,
    task_name: str,
    overlay: ConfigOverrides,
    cancellation: CancellationSource,
) -> Device:
    cancellation.raise_if_requested()
    config.replace_runtime_overlay()
    task = name_to_function(task_name)
    config.task = task
    config.bind(task)
    config.apply_runtime_overlay(**overlay)
    device.config = config
    return cast("Device", CancellationAwareMumu12Device(device, cancellation))


def project_meowfficer_settings(settings: MeowfficerSettings) -> Mapping[str, object]:
    if not isinstance(settings, MeowfficerSettings):
        message = "settings must be MeowfficerSettings"
        raise TypeError(message)
    training = settings.training
    projected: dict[str, object] = {}
    if training is not None:
        projected["MeowfficerTrain_Mode"] = training.mode.value
    return MappingProxyType(projected)


def project_guild_settings(settings: GuildSettings) -> Mapping[str, object]:
    if not isinstance(settings, GuildSettings):
        message = "settings must be GuildSettings"
        raise TypeError(message)
    logistics = settings.logistics
    operation = settings.operation
    projected: dict[str, object] = {
        "GuildLogistics_Enable": logistics is not None,
        "GuildOperation_Enable": operation is not None,
    }
    if logistics is not None:
        projected["GuildLogistics_SelectNewMission"] = logistics.select_new_mission
        if logistics.exchange_filter is not None:
            projected["GuildLogistics_ExchangeFilter"] = logistics.exchange_filter
    if operation is not None:
        projected.update(
            {
                "GuildOperation_SelectNewOperation": operation.select_new_operation,
                "GuildOperation_NewOperationMaxDate": operation.new_operation_max_date,
                "GuildOperation_JoinThreshold": operation.join_threshold,
                "GuildOperation_AttackBoss": operation.attack_boss,
                "GuildOperation_BossFleetRecommend": operation.boss_fleet_recommend,
            }
        )
    return MappingProxyType(projected)


def project_private_quarters_settings(settings: PrivateQuartersSettings) -> Mapping[str, object]:
    if not isinstance(settings, PrivateQuartersSettings):
        message = "settings must be PrivateQuartersSettings"
        raise TypeError(message)
    return MappingProxyType(
        {
            "PrivateQuarters_BuyRoses": settings.buy_roses,
            "PrivateQuarters_BuyCake": settings.buy_cake,
        }
    )


def _overlay(projected: Mapping[str, object]) -> ConfigOverrides:
    return cast("ConfigOverrides", dict(projected))


def _require_clock(clock: CompositeLiveClock) -> None:
    if isinstance(clock, type) or not callable(getattr(clock, "now", None)):
        message = "clock must implement now()"
        raise TypeError(message)


def _observed_at(clock: CompositeLiveClock) -> datetime:
    value = clock.now()
    if not isinstance(value, datetime):
        message = "composite live clock must return a datetime"
        raise TypeError(message)
    if value.tzinfo is None or value.utcoffset() is None:
        message = "composite live clock must return a timezone-aware datetime"
        raise ValueError(message)
    return value


class _Mumu12CompositeAdapter:
    __slots__ = ("_clock", "_config", "_device")

    def __init__(
        self,
        config: AzurLaneConfig,
        device: Device,
        clock: CompositeLiveClock | None = None,
    ) -> None:
        if not isinstance(config, AzurLaneConfig):
            message = "config must be an AzurLaneConfig"
            raise TypeError(message)
        if not isinstance(device, Device):
            message = "device must be a Device"
            raise TypeError(message)
        selected_clock = SystemCompositeLiveClock() if clock is None else clock
        _require_clock(selected_clock)
        self._config = config
        self._device = device
        self._clock = selected_clock

    def _device_for(
        self,
        task_name: str,
        cancellation: CancellationSource,
        overlay: ConfigOverrides | None = None,
    ) -> Device:
        selected_overlay: ConfigOverrides = {} if overlay is None else overlay
        return _activate(self._config, self._device, task_name, selected_overlay, cancellation)

    def _now(self) -> datetime:
        return _observed_at(self._clock)


class Mumu12DormWorkflow(_Mumu12CompositeAdapter, DormWorkflow):
    __slots__ = ()

    @override
    def execute(self, request: DormRunRequest, cancellation: CancellationSource) -> DormReport:
        if not isinstance(request, DormRunRequest):
            message = "request must be a DormRunRequest"
            raise TypeError(message)
        settings = request.settings
        overlay: dict[str, object] = {}
        if settings.feed is not None and settings.feed.filter is not None:
            overlay["Dorm_FeedFilter"] = settings.feed.filter
        if settings.furniture is not None:
            overlay["BuyFurniture_BuyOption"] = settings.furniture.buy_option.value
        runner = RewardDorm(
            self._config,
            device=self._device_for("Dorm", cancellation, _overlay(overlay)),
        )

        cancellation.raise_if_requested()
        runner.dorm_run(
            feed=settings.feed is not None,
            collect=settings.collect_enabled,
            buy_furniture=request.furniture_due,
        )
        cancellation.raise_if_requested()
        ships = runner.get_dorm_ship_amount()
        ships_in_dorm = ships if 1 <= ships <= 6 else None
        return DormReport(
            observed_at=self._now(),
            ships_in_dorm=ships_in_dorm,
            furniture_checked=request.furniture_due,
        )


class Mumu12MeowfficerWorkflow(_Mumu12CompositeAdapter, MeowfficerWorkflow):
    __slots__ = ()

    @override
    def execute(self, settings: MeowfficerSettings, cancellation: CancellationSource) -> MeowfficerReport:
        if not isinstance(settings, MeowfficerSettings):
            message = "settings must be MeowfficerSettings"
            raise TypeError(message)
        device = self._device_for(
            "Meowfficer",
            cancellation,
            _overlay(project_meowfficer_settings(settings)),
        )
        training = settings.training if self._config.MeowfficerTrain_Enable else None
        if not settings.has_non_training_work and training is None:
            return MeowfficerReport(observed_at=self._now(), training_active=False)

        runner = RewardMeowfficer(self._config, device=device)

        cancellation.raise_if_requested()
        runner.ui_ensure(page_meowfficer)
        cancellation.raise_if_requested()
        runner.wait_meowfficer_buttons()

        if settings.buy_amount > 0 or settings.overflow_coin_threshold is not None:
            overflow_threshold = -1 if settings.overflow_coin_threshold is None else settings.overflow_coin_threshold
            cancellation.raise_if_requested()
            count = runner.meow_get_buy_count(settings.buy_amount, overflow_threshold)
            if count > 0:
                cancellation.raise_if_requested()
                runner.meow_choose(count)
                cancellation.raise_if_requested()
                runner.meow_confirm()

        if settings.fort_chore_enabled:
            cancellation.raise_if_requested()
            runner.meow_fort()

        if training is not None:
            cancellation.raise_if_requested()
            runner.meow_train()
            if training.mode is MeowfficerTrainingMode.SEAMLESSLY or runner.meow_is_sunday():
                cancellation.raise_if_requested()
                runner.meow_enhance()

        return MeowfficerReport(
            observed_at=self._now(),
            training_active=training is not None and self._config.MeowfficerTrain_Enable,
        )


class Mumu12GuildWorkflow(_Mumu12CompositeAdapter, GuildWorkflow):
    __slots__ = ()

    @override
    def execute(self, settings: GuildSettings, cancellation: CancellationSource) -> GuildReport:
        if not isinstance(settings, GuildSettings):
            message = "settings must be GuildSettings"
            raise TypeError(message)
        runner = RewardGuild(
            self._config,
            device=self._device_for(
                "Guild",
                cancellation,
                _overlay(project_guild_settings(settings)),
            ),
        )

        cancellation.raise_if_requested()
        runner.ui_ensure(page_guild)
        cancellation.raise_if_requested()
        runner.guild_lobby()

        logistics_succeeded = None
        if settings.logistics is not None:
            cancellation.raise_if_requested()
            logistics_succeeded = runner.guild_logistics()

        operation_succeeded = None
        if settings.operation is not None:
            cancellation.raise_if_requested()
            operation_succeeded = runner.guild_operations()

        cancellation.raise_if_requested()
        runner.ui_goto(page_main)
        return GuildReport(
            observed_at=self._now(),
            logistics_succeeded=logistics_succeeded,
            operation_succeeded=operation_succeeded,
        )


class Mumu12RewardWorkflow(_Mumu12CompositeAdapter, RewardWorkflow):
    __slots__ = ()

    @override
    def execute(self, settings: RewardSettings, cancellation: CancellationSource) -> RewardReport:
        if not isinstance(settings, RewardSettings):
            message = "settings must be RewardSettings"
            raise TypeError(message)
        runner = Reward(self._config, device=self._device_for("Reward", cancellation))

        cancellation.raise_if_requested()
        runner.ui_ensure(page_reward)
        cancellation.raise_if_requested()
        runner.reward_receive(
            oil=settings.collect_oil,
            coin=settings.collect_coin,
            exp=settings.collect_exp,
        )
        cancellation.raise_if_requested()
        runner.ui_goto(page_main)
        cancellation.raise_if_requested()
        runner.reward_mission(
            daily=settings.collect_daily_mission,
            weekly=settings.collect_weekly_mission,
        )
        return RewardReport(observed_at=self._now())


class Mumu12BattlePassWorkflow(_Mumu12CompositeAdapter, FreebieCollectionWorkflow):
    __slots__ = ()

    @override
    def collect(self, cancellation: CancellationSource) -> FreebieCollectionReport:
        runner = BattlePass(self._config, device=self._device_for("Freebies", cancellation))

        cancellation.raise_if_requested()
        runner.ui_ensure(page_reward)
        cancellation.raise_if_requested()
        available = runner.battle_pass_red_dot_appear()
        changed = False
        if available:
            cancellation.raise_if_requested()
            runner.battle_pass_enter()
            cancellation.raise_if_requested()
            changed = runner.battle_pass_receive()
        return FreebieCollectionReport(changed=changed, observed_at=self._now())


class Mumu12DataKeyWorkflow(_Mumu12CompositeAdapter, DataKeyWorkflow):
    __slots__ = ()

    @override
    def collect(
        self,
        plan: DataKeyPlan,
        cancellation: CancellationSource,
    ) -> FreebieCollectionReport:
        if not isinstance(plan, DataKeyPlan):
            message = "plan must be a DataKeyPlan"
            raise TypeError(message)
        runner = DataKey(
            self._config,
            device=self._device_for(
                "Freebies",
                cancellation,
                _overlay({"DataKey_ForceCollect": plan.force_collect}),
            ),
        )

        cancellation.raise_if_requested()
        runner.ui_ensure(page_archives)
        cancellation.raise_if_requested()
        changed = runner.data_key_collect()
        cancellation.raise_if_requested()
        runner.interval_clear([page_archives.check_button, page_campaign_menu.check_button])
        return FreebieCollectionReport(changed=changed, observed_at=self._now())


class Mumu12MailWorkflow(_Mumu12CompositeAdapter, MailCollectionWorkflow):
    __slots__ = ()

    @override
    def collect(
        self,
        policy: MailCollectionPolicy,
        cancellation: CancellationSource,
    ) -> FreebieCollectionReport:
        if not isinstance(policy, MailCollectionPolicy):
            message = "policy must be a MailCollectionPolicy"
            raise TypeError(message)
        runner = MailWhite(self._config, device=self._device_for("Freebies", cancellation))
        if not policy.has_claim_work:
            logger.warning("Nothing to claim")
            return FreebieCollectionReport(changed=False, observed_at=self._now())

        cancellation.raise_if_requested()
        runner.ui_ensure(page_main)
        cancellation.raise_if_requested()
        if not runner.mail_enter():
            return FreebieCollectionReport(changed=False, observed_at=self._now())

        changed = False
        if policy.claim_merit:
            cancellation.raise_if_requested()
            runner.mail_select_setting.set(contains=["merit"])
            cancellation.raise_if_requested()
            changed = runner.mail_claim_execute() or changed
        if policy.claim_maintenance:
            cancellation.raise_if_requested()
            runner.mail_enter()
            cancellation.raise_if_requested()
            runner.mail_select_setting.set(contains=["coins", "oil"])
            cancellation.raise_if_requested()
            changed = runner.mail_claim_execute() or changed
            cancellation.raise_if_requested()
            runner.mail_enter()
            cancellation.raise_if_requested()
            runner.mail_select_setting.set(contains=["coins", "oil", "gems"])
            cancellation.raise_if_requested()
            changed = runner.mail_claim_execute() or changed
        if policy.claim_trade_license:
            cancellation.raise_if_requested()
            runner.mail_enter()
            cancellation.raise_if_requested()
            runner.mail_select_setting.set(contains=["coins", "oil", "cube"])
            cancellation.raise_if_requested()
            changed = runner.mail_claim_execute() or changed
        if policy.delete_collected:
            cancellation.raise_if_requested()
            runner.mail_enter()
            cancellation.raise_if_requested()
            runner.mail_select_all_setting.set(contains=["all"])
            cancellation.raise_if_requested()
            changed = runner.mail_delete() or changed

        cancellation.raise_if_requested()
        runner.mail_quit()
        return FreebieCollectionReport(changed=changed, observed_at=self._now())


class Mumu12SupplyPackWorkflow(_Mumu12CompositeAdapter, SupplyPackWorkflow):
    __slots__ = ()

    @override
    def collect(
        self,
        plan: SupplyPackPlan,
        cancellation: CancellationSource,
    ) -> FreebieCollectionReport:
        if not isinstance(plan, SupplyPackPlan):
            message = "plan must be a SupplyPackPlan"
            raise TypeError(message)
        runner = SupplyPack250814(self._config, device=self._device_for("Freebies", cancellation))

        cancellation.raise_if_requested()
        runner.ui_ensure(page_shop)
        cancellation.raise_if_requested()
        runner.goto_supply_pack()
        cancellation.raise_if_requested()
        oil = runner.get_oil()

        changed = False
        if oil < 21000:
            server_today = get_server_weekday()
            target = plan.day_of_week
            if server_today >= target:
                cancellation.raise_if_requested()
                changed = runner.supply_pack_buy(FREE_SUPPLY_PACK)
            else:
                logger.info(f"Delaying free week supply pack to {day_name[target]}")
        else:
            logger.info("Oil > 21000, unable to buy free weekly supply pack")
        return FreebieCollectionReport(changed=changed, observed_at=self._now())


class Mumu12PrivateQuartersWorkflow(_Mumu12CompositeAdapter, PrivateQuartersWorkflow):
    __slots__ = ()

    @override
    def execute(
        self,
        settings: PrivateQuartersSettings,
        cancellation: CancellationSource,
    ) -> PrivateQuartersReport:
        if not isinstance(settings, PrivateQuartersSettings):
            message = "settings must be PrivateQuartersSettings"
            raise TypeError(message)
        cancellation.raise_if_requested()
        if not settings.has_shop_work and settings.target_ship is None:
            return PrivateQuartersReport(
                observed_at=self._now(),
                shop_attempted=False,
                interaction_status=PrivateQuartersInteractionStatus.NOT_REQUESTED,
            )

        runner = PrivateQuarters(
            self._config,
            device=self._device_for(
                "PrivateQuarters",
                cancellation,
                _overlay(project_private_quarters_settings(settings)),
            ),
        )

        cancellation.raise_if_requested()
        runner.ui_ensure(page_dormmenu)
        cancellation.raise_if_requested()
        runner.ui_goto(page_private_quarters, get_ship=False)
        cancellation.raise_if_requested()
        runner.handle_info_bar()

        if settings.has_shop_work:
            cancellation.raise_if_requested()
            runner.pq_shop_weekly_items()

        status = PrivateQuartersInteractionStatus.NOT_REQUESTED
        target_ship = settings.target_ship
        if target_ship is not None:
            if target_ship in runner.not_supported_ships or target_ship not in runner.available_targets:
                status = PrivateQuartersInteractionStatus.UNSUPPORTED
            else:
                cancellation.raise_if_requested()
                daily_count = runner.pq_get_daily_count(retry=3)
                if daily_count == 0:
                    status = PrivateQuartersInteractionStatus.EXHAUSTED
                else:
                    cancellation.raise_if_requested()
                    entered = runner.pq_goto_room(target_ship, retry=3)
                    if not entered:
                        status = PrivateQuartersInteractionStatus.ROOM_UNAVAILABLE
                    else:
                        cancellation.raise_if_requested()
                        runner.pq_interact()
                        status = PrivateQuartersInteractionStatus.COMPLETED

        return PrivateQuartersReport(
            observed_at=self._now(),
            shop_attempted=settings.has_shop_work,
            interaction_status=status,
        )


def build_mumu12_composite_workflows(
    config: AzurLaneConfig,
    device: Device,
    *,
    clock: CompositeLiveClock | None = None,
) -> CompositeWorkflows:
    """构造宿舍、奖励、免费领取和私宅的 production workflow bundle。"""

    return CompositeWorkflows(
        dorm=Mumu12DormWorkflow(config, device, clock),
        meowfficer=Mumu12MeowfficerWorkflow(config, device, clock),
        guild=Mumu12GuildWorkflow(config, device, clock),
        reward=Mumu12RewardWorkflow(config, device, clock),
        battle_pass=Mumu12BattlePassWorkflow(config, device, clock),
        data_key=Mumu12DataKeyWorkflow(config, device, clock),
        mail=Mumu12MailWorkflow(config, device, clock),
        supply_pack=Mumu12SupplyPackWorkflow(config, device, clock),
        private_quarters=Mumu12PrivateQuartersWorkflow(config, device, clock),
    )
