from types import MappingProxyType
from typing import TYPE_CHECKING, cast, override

from module.adapters.mumu12 import CancellationAwareMumu12Device
from module.awaken.awaken import Awaken
from module.base.decorator import del_cached_property
from module.config.config import AzurLaneConfig, name_to_function
from module.device.device import Device
from module.gacha.gacha_reward import RewardGacha
from module.gameplay.market import (
    AwakenAttempt,
    AwakenLevelCap,
    AwakenReport,
    AwakenRunResult,
    AwakenSettings,
    AwakenWorkflow,
    CoreShopPlan,
    GachaReport,
    GachaSettings,
    GachaWorkflow,
    GuildShopPlan,
    MedalShopPlan,
    MeritShopPlan,
    ShipyardReport,
    ShipyardSettings,
    ShipyardWorkflow,
    ShopFrequentReport,
    ShopFrequentSettings,
    ShopFrequentWorkflow,
    ShopOnceReport,
    ShopOnceSettings,
    ShopOnceWorkflow,
)
from module.gameplay.market_factories import MarketWorkflows
from module.shipyard.shipyard_reward import RewardShipyard
from module.shop.shop_core import CoreShop250814
from module.shop.shop_general import GeneralShop250814
from module.shop.shop_guild import GuildShop250814
from module.shop.shop_medal import MEDAL_SHOP_SCROLL_250814, MedalShop2V250814
from module.shop.shop_merit import MeritShop250814
from module.shop.shop_reward import RewardShop

if TYPE_CHECKING:
    from collections.abc import Mapping

    from module.config.config_generated import ConfigOverrides
    from module.interaction import CancellationSignal


def _activate(
    config: AzurLaneConfig,
    device: Device,
    task_name: str,
    overlay: ConfigOverrides,
    cancellation: CancellationSignal,
) -> Device:
    cancellation.raise_if_requested()
    config.replace_runtime_overlay()
    task = name_to_function(task_name)
    config.task = task
    config.bind(task)
    config.apply_runtime_overlay(**overlay)
    device.config = config
    return cast("Device", CancellationAwareMumu12Device(device, cancellation))


def project_gacha_settings(settings: GachaSettings) -> Mapping[str, object]:
    if not isinstance(settings, GachaSettings):
        message = "settings must be GachaSettings"
        raise TypeError(message)
    plan = settings.plan
    return MappingProxyType(
        {
            "Gacha_Pool": plan.pool.value,
            "Gacha_Amount": plan.amount,
            "Gacha_UseTicket": plan.use_ticket,
            "Gacha_UseDrill": plan.use_drill,
        }
    )


def project_shop_frequent_settings(settings: ShopFrequentSettings) -> Mapping[str, object]:
    if not isinstance(settings, ShopFrequentSettings):
        message = "settings must be ShopFrequentSettings"
        raise TypeError(message)
    plan = settings.plan
    return MappingProxyType(
        {
            "GeneralShop_Filter": plan.filter or "",
            "GeneralShop_Refresh": plan.refresh,
            "GeneralShop_UseGems": plan.use_gems,
            "GeneralShop_ConsumeCoins": plan.consume_coins,
            "GeneralShop_BuySkinBox": plan.buy_skin_box,
        }
    )


def _project_merit(plan: MeritShopPlan) -> dict[str, object]:
    return {
        "MeritShop_Filter": plan.filter or "",
        "MeritShop_Refresh": plan.refresh,
    }


def _project_guild(plan: GuildShopPlan) -> dict[str, object]:
    return {
        "GuildShop_Filter": plan.filter or "",
        "GuildShop_Refresh": plan.refresh,
        "GuildShop_BOX_T3": plan.box_t3,
        "GuildShop_BOX_T4": plan.box_t4,
        "GuildShop_BOOK_T2": plan.book_t2,
        "GuildShop_BOOK_T3": plan.book_t3,
        "GuildShop_RETROFIT_T2": plan.retrofit_t2,
        "GuildShop_RETROFIT_T3": plan.retrofit_t3,
        "GuildShop_PLATE_T2": plan.plate_t2,
        "GuildShop_PLATE_T3": plan.plate_t3,
        "GuildShop_PLATE_T4": plan.plate_t4,
        "GuildShop_PR1": plan.pr1,
        "GuildShop_PR2": plan.pr2,
        "GuildShop_PR3": plan.pr3,
    }


def _project_core(plan: CoreShopPlan) -> dict[str, object]:
    return {"CoreShop_Filter": plan.filter or ""}


def _project_medal(plan: MedalShopPlan) -> dict[str, object]:
    return {
        "MedalShop2_Filter": plan.filter or "",
        "MedalShop2_RETROFIT_T1": plan.retrofit_t1,
        "MedalShop2_RETROFIT_T2": plan.retrofit_t2,
        "MedalShop2_RETROFIT_T3": plan.retrofit_t3,
        "MedalShop2_PLATE_T1": plan.plate_t1,
        "MedalShop2_PLATE_T2": plan.plate_t2,
        "MedalShop2_PLATE_T3": plan.plate_t3,
    }


def project_shop_once_settings(settings: ShopOnceSettings) -> Mapping[str, object]:
    if not isinstance(settings, ShopOnceSettings):
        message = "settings must be ShopOnceSettings"
        raise TypeError(message)
    plan = settings.plan
    projected: dict[str, object] = {}
    projected.update(_project_merit(plan.merit))
    projected.update(_project_guild(plan.guild))
    projected.update(_project_core(plan.core))
    projected.update(_project_medal(plan.medal))
    return MappingProxyType(projected)


def _overlay(projected: Mapping[str, object]) -> ConfigOverrides:
    return cast("ConfigOverrides", dict(projected))


class _Mumu12MarketAdapter:
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

    def _device_for(
        self,
        task_name: str,
        cancellation: CancellationSignal,
        overlay: ConfigOverrides | None = None,
    ) -> Device:
        selected_overlay: ConfigOverrides = {} if overlay is None else overlay
        return _activate(self._config, self._device, task_name, selected_overlay, cancellation)


class Mumu12AwakenWorkflow(_Mumu12MarketAdapter, AwakenWorkflow):
    __slots__ = ()

    @override
    def execute(self, settings: AwakenSettings, cancellation: CancellationSignal) -> AwakenReport:
        if not isinstance(settings, AwakenSettings):
            message = "settings must be AwakenSettings"
            raise TypeError(message)
        runner = Awaken(self._config, device=self._device_for("Awaken", cancellation))
        attempts: list[AwakenAttempt] = []

        try:
            if settings.plan.level_cap is AwakenLevelCap.LEVEL_125:
                cancellation.raise_if_requested()
                first = AwakenRunResult(runner.awaken_run(use_array=True, favourite=settings.plan.favourite_only))
                attempts.append(AwakenAttempt(AwakenLevelCap.LEVEL_125, first))
                if first is not AwakenRunResult.TIMED_OUT:
                    cancellation.raise_if_requested()
                    second = AwakenRunResult(runner.awaken_run(favourite=settings.plan.favourite_only))
                    attempts.append(AwakenAttempt(AwakenLevelCap.LEVEL_120, second))
            else:
                cancellation.raise_if_requested()
                result = AwakenRunResult(runner.awaken_run(favourite=settings.plan.favourite_only))
                attempts.append(AwakenAttempt(AwakenLevelCap.LEVEL_120, result))
        finally:
            if settings.plan.favourite_only:
                cancellation.raise_if_requested()
                runner.dock_favourite_set(wait_loading=False)
            cancellation.raise_if_requested()
            runner.dock_filter_set(wait_loading=False)

        return AwakenReport(attempts=tuple(attempts))


class Mumu12ShipyardWorkflow(_Mumu12MarketAdapter, ShipyardWorkflow):
    __slots__ = ()

    @override
    def execute(self, settings: ShipyardSettings, cancellation: CancellationSignal) -> ShipyardReport:
        if not isinstance(settings, ShipyardSettings):
            message = "settings must be ShipyardSettings"
            raise TypeError(message)
        runner = RewardShipyard(self._config, device=self._device_for("Shipyard", cancellation))

        dr_processed = False
        if settings.plan.dr.buy_amount > 0:
            cancellation.raise_if_requested()
            dr_processed = runner.shipyard_run(
                series=settings.plan.dr.research_series,
                index=settings.plan.dr.ship_index,
                count=settings.plan.dr.buy_amount,
                rarity="DR",
            )

        pr_processed = False
        if settings.plan.pr.buy_amount > 0:
            cancellation.raise_if_requested()
            pr_processed = runner.shipyard_run(
                series=settings.plan.pr.research_series,
                index=settings.plan.pr.ship_index,
                count=settings.plan.pr.buy_amount,
                rarity="PR",
            )

        return ShipyardReport(pr_processed=pr_processed, dr_processed=dr_processed)


class Mumu12GachaWorkflow(_Mumu12MarketAdapter, GachaWorkflow):
    __slots__ = ()

    @override
    def execute(self, settings: GachaSettings, cancellation: CancellationSignal) -> GachaReport:
        if not isinstance(settings, GachaSettings):
            message = "settings must be GachaSettings"
            raise TypeError(message)
        runner = RewardGacha(
            self._config,
            device=self._device_for("Gacha", cancellation, _overlay(project_gacha_settings(settings))),
        )

        cancellation.raise_if_requested()
        submitted = runner.gacha_run()
        return GachaReport(submitted=submitted)


class _Mumu12ShopWorkflow(_Mumu12MarketAdapter):
    __slots__ = ()

    @staticmethod
    def _prepare_tab(
        runner: RewardShop,
        *,
        navigation: str,
        tab: str,
        cancellation: CancellationSignal,
    ) -> None:
        cancellation.raise_if_requested()
        runner.device.click_record_clear()
        cancellation.raise_if_requested()
        runner.shop_nav_250814.set(navigation, main=runner)
        cancellation.raise_if_requested()
        runner.shop_tab_250814.set(tab, main=runner)

    @staticmethod
    def _general(shop: GeneralShop250814, *, refresh: bool, cancellation: CancellationSignal) -> None:
        if not shop.shop_filter:
            return
        for _ in range(2):
            cancellation.raise_if_requested()
            success = shop.shop_buy()
            if not success:
                return
            if refresh:
                cancellation.raise_if_requested()
                if shop.shop_refresh():
                    continue
            return

    @staticmethod
    def _merit(shop: MeritShop250814, *, refresh: bool, cancellation: CancellationSignal) -> None:
        if not shop.shop_filter:
            return
        for _ in range(2):
            cancellation.raise_if_requested()
            success = shop.shop_buy()
            if not success:
                return
            if refresh:
                cancellation.raise_if_requested()
                if shop.shop_refresh():
                    continue
            return

    @staticmethod
    def _guild(shop: GuildShop250814, *, refresh: bool, cancellation: CancellationSignal) -> None:
        if not shop.shop_filter:
            return
        for _ in range(2):
            cancellation.raise_if_requested()
            success = shop.shop_buy()
            if not success:
                return
            if refresh and shop.current_currency >= 110:
                cancellation.raise_if_requested()
                if shop.shop_refresh():
                    continue
            return

    @staticmethod
    def _core(shop: CoreShop250814, cancellation: CancellationSignal) -> None:
        if not shop.shop_filter:
            return
        cancellation.raise_if_requested()
        shop.shop_buy()

    @staticmethod
    def _medal(shop: MedalShop2V250814, cancellation: CancellationSignal) -> None:
        if not shop.shop_filter:
            return
        cancellation.raise_if_requested()
        MEDAL_SHOP_SCROLL_250814.set_top(main=shop)
        cancellation.raise_if_requested()
        shop.device.sleep(0.5)
        while True:
            cancellation.raise_if_requested()
            if shop.shop_items().get_soldout_count(shop.device.image):
                return
            cancellation.raise_if_requested()
            shop.shop_buy()
            cancellation.raise_if_requested()
            if MEDAL_SHOP_SCROLL_250814.at_bottom(main=shop):
                return
            cancellation.raise_if_requested()
            MEDAL_SHOP_SCROLL_250814.next_page(main=shop, page=0.66)
            del_cached_property(shop, "shop_grid")
            del_cached_property(shop, "shop_medal_items")


class Mumu12ShopFrequentWorkflow(_Mumu12ShopWorkflow, ShopFrequentWorkflow):
    __slots__ = ()

    @override
    def execute(
        self,
        settings: ShopFrequentSettings,
        cancellation: CancellationSignal,
    ) -> ShopFrequentReport:
        if not isinstance(settings, ShopFrequentSettings):
            message = "settings must be ShopFrequentSettings"
            raise TypeError(message)
        device = self._device_for(
            "ShopFrequent",
            cancellation,
            _overlay(project_shop_frequent_settings(settings)),
        )
        runner = RewardShop(self._config, device=device)

        cancellation.raise_if_requested()
        runner.ui_goto_shop()
        self._prepare_tab(runner, navigation="general", tab="general", cancellation=cancellation)
        self._general(
            GeneralShop250814(self._config, device=device),
            refresh=settings.plan.refresh,
            cancellation=cancellation,
        )
        return ShopFrequentReport()


class Mumu12ShopOnceWorkflow(_Mumu12ShopWorkflow, ShopOnceWorkflow):
    __slots__ = ()

    @override
    def execute(self, settings: ShopOnceSettings, cancellation: CancellationSignal) -> ShopOnceReport:
        if not isinstance(settings, ShopOnceSettings):
            message = "settings must be ShopOnceSettings"
            raise TypeError(message)
        device = self._device_for(
            "ShopOnce",
            cancellation,
            _overlay(project_shop_once_settings(settings)),
        )
        runner = RewardShop(self._config, device=device)

        cancellation.raise_if_requested()
        runner.ui_goto_shop()

        self._prepare_tab(runner, navigation="general", tab="merit", cancellation=cancellation)
        self._merit(
            MeritShop250814(self._config, device=device),
            refresh=settings.plan.merit.refresh,
            cancellation=cancellation,
        )

        self._prepare_tab(runner, navigation="general", tab="guild", cancellation=cancellation)
        self._guild(
            GuildShop250814(self._config, device=device),
            refresh=settings.plan.guild.refresh,
            cancellation=cancellation,
        )

        self._prepare_tab(runner, navigation="monthly", tab="core_monthly", cancellation=cancellation)
        self._core(CoreShop250814(self._config, device=device), cancellation)

        self._prepare_tab(runner, navigation="monthly", tab="medal", cancellation=cancellation)
        self._medal(MedalShop2V250814(self._config, device=device), cancellation)
        return ShopOnceReport()


def build_mumu12_market_workflows(config: AzurLaneConfig, device: Device) -> MarketWorkflows:
    """构造唤醒、船坞、建造和商店的 production workflow bundle。"""

    return MarketWorkflows(
        awaken=Mumu12AwakenWorkflow(config, device),
        shipyard=Mumu12ShipyardWorkflow(config, device),
        gacha=Mumu12GachaWorkflow(config, device),
        shop_frequent=Mumu12ShopFrequentWorkflow(config, device),
        shop_once=Mumu12ShopOnceWorkflow(config, device),
    )
