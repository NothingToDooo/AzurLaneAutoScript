from datetime import time
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest

import module.adapters.market_mumu12 as adapters
from module.application import AbortToken, DailySchedule
from module.config.config import AzurLaneConfig
from module.device.device import Device
from module.gameplay.market import (
    AwakenAttempt,
    AwakenLevelCap,
    AwakenPlan,
    AwakenReport,
    AwakenRunResult,
    AwakenSettings,
    CoreShopPlan,
    GachaPlan,
    GachaPool,
    GachaReport,
    GachaSettings,
    GeneralShopPlan,
    GuildShopPlan,
    MedalShopPlan,
    MeritShopPlan,
    ShipyardPlan,
    ShipyardPurchasePlan,
    ShipyardReport,
    ShipyardSettings,
    ShopOncePlan,
    ShopOnceReport,
    ShopOnceSettings,
)

if TYPE_CHECKING:
    from module.interaction import CancellationSignal


_SCHEDULE = DailySchedule("Asia/Hong_Kong", (time(12),))


@pytest.fixture
def runtime(monkeypatch: pytest.MonkeyPatch) -> tuple[AzurLaneConfig, Device]:
    config = object.__new__(AzurLaneConfig)
    device = object.__new__(Device)

    def activate(
        _config: AzurLaneConfig,
        _device: Device,
        _task_name: str,
        overlay: dict[str, object],
        cancellation: CancellationSignal,
    ) -> Device:
        cancellation.raise_if_requested()
        vars(config).update(overlay)
        return device

    monkeypatch.setattr(adapters, "_activate", activate)
    return config, device


class _AwakenRunner:
    def __init__(self) -> None:
        self.calls: list[object] = []
        self.results = ["insufficient", "finish"]

    def awaken_run(self, *, use_array: bool = False, favourite: bool = False) -> str:
        self.calls.append(("awaken", use_array, favourite))
        return self.results.pop(0)

    def dock_favourite_set(self, *, wait_loading: bool) -> None:
        self.calls.append(("favourite_reset", wait_loading))

    def dock_filter_set(self, *, wait_loading: bool) -> None:
        self.calls.append(("filter_reset", wait_loading))


def test_awaken_level125_runs_fallback_and_restores_filters(
    runtime: tuple[AzurLaneConfig, Device],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, device = runtime
    runner = _AwakenRunner()
    monkeypatch.setattr(adapters, "Awaken", lambda *_args, **_kwargs: runner)
    settings = AwakenSettings(AwakenPlan(AwakenLevelCap.LEVEL_125, favourite_only=True), _SCHEDULE)

    report = adapters.Mumu12AwakenWorkflow(config, device).execute(settings, AbortToken())

    assert report == AwakenReport(
        (
            AwakenAttempt(AwakenLevelCap.LEVEL_125, AwakenRunResult.INSUFFICIENT),
            AwakenAttempt(AwakenLevelCap.LEVEL_120, AwakenRunResult.FINISHED),
        )
    )
    assert runner.calls == [
        ("awaken", True, True),
        ("awaken", False, True),
        ("favourite_reset", False),
        ("filter_reset", False),
    ]


class _ShipyardRunner:
    def __init__(self) -> None:
        self.calls: list[object] = []

    def shipyard_run(self, series: int, index: int, count: int, *, rarity: str) -> bool:
        self.calls.append((rarity, series, index, count))
        return rarity == "DR"


def test_shipyard_processes_dr_then_pr_from_typed_plan(
    runtime: tuple[AzurLaneConfig, Device],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, device = runtime
    runner = _ShipyardRunner()
    monkeypatch.setattr(adapters, "RewardShipyard", lambda *_args, **_kwargs: runner)
    settings = ShipyardSettings(
        ShipyardPlan(
            pr=ShipyardPurchasePlan(1, 2, 3),
            dr=ShipyardPurchasePlan(4, 5, 6),
        ),
        _SCHEDULE,
    )

    report = adapters.Mumu12ShipyardWorkflow(config, device).execute(settings, AbortToken())

    assert report == ShipyardReport(pr_processed=False, dr_processed=True)
    assert runner.calls == [("DR", 4, 5, 6), ("PR", 1, 2, 3)]


class _GachaRunner:
    def __init__(self) -> None:
        self.calls = 0

    def gacha_run(self) -> bool:
        self.calls += 1
        return True


def test_gacha_applies_typed_plan_before_invoking_primitive(
    runtime: tuple[AzurLaneConfig, Device],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, device = runtime
    runner = _GachaRunner()
    monkeypatch.setattr(adapters, "RewardGacha", lambda *_args, **_kwargs: runner)
    settings = GachaSettings(GachaPlan(GachaPool.EVENT, 10, use_ticket=True, use_drill=True), _SCHEDULE)

    report = adapters.Mumu12GachaWorkflow(config, device).execute(settings, AbortToken())

    assert report == GachaReport(submitted=True)
    assert runner.calls == 1
    assert config.Gacha_Pool == "event"
    assert config.Gacha_Amount == 10
    assert config.Gacha_UseTicket is True
    assert config.Gacha_UseDrill is True


class _Control:
    def __init__(self, name: str, calls: list[object]) -> None:
        self._name = name
        self._calls = calls

    def set(self, value: str, *, main: object) -> None:
        self._calls.append((self._name, value, main))


class _ShopDevice:
    def __init__(self, calls: list[object]) -> None:
        self._calls = calls

    def click_record_clear(self) -> None:
        self._calls.append("clear")


class _ShopRunner:
    def __init__(self) -> None:
        self.calls: list[object] = []
        self.device = _ShopDevice(self.calls)
        self.shop_nav_250814 = _Control("nav", self.calls)
        self.shop_tab_250814 = _Control("tab", self.calls)

    def ui_goto_shop(self) -> None:
        self.calls.append("goto")


def _shop_once_settings() -> ShopOnceSettings:
    return ShopOnceSettings(
        plan=ShopOncePlan(
            merit=MeritShopPlan(filter="Cube", refresh=False),
            guild=GuildShopPlan(
                filter="PlateT4",
                refresh=True,
                box_t3="ironblood",
                box_t4="royal",
                book_t2="red",
                book_t3="yellow",
                retrofit_t2="cl",
                retrofit_t3="bb",
                plate_t2="general",
                plate_t3="antiair",
                plate_t4="gun",
                pr1="neptune",
                pr2="seattle",
                pr3="cheshire",
            ),
            core=CoreShopPlan(filter="Array"),
            medal=MedalShopPlan(
                filter="DR > PR",
                retrofit_t1="dd",
                retrofit_t2="cl",
                retrofit_t3="bb",
                plate_t1="general",
                plate_t2="torpedo",
                plate_t3="plane",
            ),
        ),
        schedule=_SCHEDULE,
    )


def test_shop_once_uses_explicit_tab_sequence_without_legacy_run(
    runtime: tuple[AzurLaneConfig, Device],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, device = runtime
    runner = _ShopRunner()
    child_calls: list[str] = []
    monkeypatch.setattr(adapters, "RewardShop", lambda *_args, **_kwargs: runner)
    monkeypatch.setattr(adapters, "MeritShop250814", lambda *_args, **_kwargs: "merit")
    monkeypatch.setattr(adapters, "GuildShop250814", lambda *_args, **_kwargs: "guild")
    monkeypatch.setattr(adapters, "CoreShop250814", lambda *_args, **_kwargs: "core")
    monkeypatch.setattr(adapters, "MedalShop2V250814", lambda *_args, **_kwargs: "medal")
    monkeypatch.setattr(
        adapters.Mumu12ShopOnceWorkflow,
        "_merit",
        staticmethod(lambda shop, **_kwargs: child_calls.append(cast("str", shop))),
    )
    monkeypatch.setattr(
        adapters.Mumu12ShopOnceWorkflow,
        "_guild",
        staticmethod(lambda shop, **_kwargs: child_calls.append(cast("str", shop))),
    )
    monkeypatch.setattr(
        adapters.Mumu12ShopOnceWorkflow,
        "_core",
        staticmethod(lambda shop, _cancellation: child_calls.append(cast("str", shop))),
    )
    monkeypatch.setattr(
        adapters.Mumu12ShopOnceWorkflow,
        "_medal",
        staticmethod(lambda shop, _cancellation: child_calls.append(cast("str", shop))),
    )

    report = adapters.Mumu12ShopOnceWorkflow(config, device).execute(_shop_once_settings(), AbortToken())

    assert report == ShopOnceReport()
    assert child_calls == ["merit", "guild", "core", "medal"]
    assert [(call[0], call[1]) for call in runner.calls if isinstance(call, tuple)] == [
        ("nav", "general"),
        ("tab", "merit"),
        ("nav", "general"),
        ("tab", "guild"),
        ("nav", "monthly"),
        ("tab", "core_monthly"),
        ("nav", "monthly"),
        ("tab", "medal"),
    ]
    assert config.GuildShop_BOX_T4 == "royal"
    assert config.MedalShop2_PLATE_T3 == "plane"


def test_shop_frequent_projection_contains_every_general_shop_policy() -> None:
    settings = adapters.ShopFrequentSettings(
        plan=GeneralShopPlan(
            filter="Cube > FoodT6",
            refresh=True,
            use_gems=False,
            consume_coins=True,
            buy_skin_box=True,
        ),
        schedule=_SCHEDULE,
    )

    assert dict(adapters.project_shop_frequent_settings(settings)) == {
        "GeneralShop_Filter": "Cube > FoodT6",
        "GeneralShop_Refresh": True,
        "GeneralShop_UseGems": False,
        "GeneralShop_ConsumeCoins": True,
        "GeneralShop_BuySkinBox": True,
    }


def test_disabled_shop_filter_projects_to_empty_legacy_primitive() -> None:
    settings = adapters.ShopFrequentSettings(
        plan=GeneralShopPlan(
            filter=None,
            refresh=False,
            use_gems=False,
            consume_coins=False,
            buy_skin_box=False,
        ),
        schedule=_SCHEDULE,
    )

    assert adapters.project_shop_frequent_settings(settings)["GeneralShop_Filter"] == ""


def test_market_production_builder_returns_all_five_capabilities(
    runtime: tuple[AzurLaneConfig, Device],
) -> None:
    config, device = runtime

    workflows = adapters.build_mumu12_market_workflows(config, device)

    assert isinstance(workflows.awaken, adapters.Mumu12AwakenWorkflow)
    assert isinstance(workflows.shipyard, adapters.Mumu12ShipyardWorkflow)
    assert isinstance(workflows.gacha, adapters.Mumu12GachaWorkflow)
    assert isinstance(workflows.shop_frequent, adapters.Mumu12ShopFrequentWorkflow)
    assert isinstance(workflows.shop_once, adapters.Mumu12ShopOnceWorkflow)


def test_market_adapter_has_no_legacy_scheduler_or_run_dispatch() -> None:
    source = Path(adapters.__file__).read_text(encoding="utf-8")

    for forbidden in (".run(", "task_delay(", "task_stop(", "task_call(", "import_module("):
        assert forbidden not in source
