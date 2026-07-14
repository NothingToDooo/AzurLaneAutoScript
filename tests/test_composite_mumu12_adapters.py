from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

import module.adapters.composite_mumu12 as adapters
from module.application import AbortToken, DailySchedule
from module.config.config import AzurLaneConfig
from module.device.device import Device
from module.gameplay.composite import (
    DataKeyPlan,
    DormFeedPlan,
    DormFurniturePlan,
    DormReport,
    DormRunRequest,
    DormSettings,
    FreebieCollectionReport,
    FreebiesSettings,
    FurnitureBuyOption,
    MailCollectionPolicy,
    MeowfficerSettings,
    MeowfficerTrainingMode,
    MeowfficerTrainingSettings,
    PrivateQuartersInteractionStatus,
    PrivateQuartersReport,
    PrivateQuartersSettings,
    SupplyPackPlan,
)

if TYPE_CHECKING:
    from module.interaction import CancellationSignal


_NOW = datetime(2026, 7, 13, 12, tzinfo=UTC)
_SCHEDULE = DailySchedule("Asia/Hong_Kong", (time(12),))


class _Clock:
    @staticmethod
    def now() -> datetime:
        return _NOW


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


class _DormRunner:
    def __init__(self) -> None:
        self.calls: list[object] = []

    def dorm_run(self, *, feed: bool, collect: bool, buy_furniture: bool) -> None:
        self.calls.append(("dorm_run", feed, collect, buy_furniture))

    def get_dorm_ship_amount(self) -> int:
        self.calls.append("ships")
        return 4


def test_dorm_maps_typed_flags_and_confirmed_ship_count_to_report(
    runtime: tuple[AzurLaneConfig, Device],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, device = runtime
    runner = _DormRunner()
    monkeypatch.setattr(adapters, "RewardDorm", lambda *_args, **_kwargs: runner)
    settings = DormSettings(
        feed=DormFeedPlan("20000 > 10000"),
        collect_enabled=False,
        furniture=DormFurniturePlan(FurnitureBuyOption.ALL, timedelta(days=6)),
        fallback_delay=timedelta(hours=1),
    )
    request = DormRunRequest(settings, furniture_due=True)

    report = adapters.Mumu12DormWorkflow(config, device, _Clock()).execute(request, AbortToken())

    assert report == DormReport(observed_at=_NOW, ships_in_dorm=4, furniture_checked=True)
    assert config.Dorm_FeedFilter == "20000 > 10000"
    assert config.BuyFurniture_BuyOption == "all"
    assert runner.calls == [("dorm_run", True, False, True), "ships"]


class _MeowRunner:
    def __init__(self) -> None:
        self.calls: list[object] = []

    def ui_ensure(self, _page: object) -> None:
        self.calls.append("ensure")

    def wait_meowfficer_buttons(self) -> None:
        self.calls.append("wait")

    def meow_get_buy_count(self, buy_amount: int, overflow_threshold: int) -> int:
        self.calls.append(("buy_count", buy_amount, overflow_threshold))
        return 2

    def meow_choose(self, count: int) -> None:
        self.calls.append(("choose", count))

    def meow_confirm(self) -> None:
        self.calls.append("confirm")

    def meow_fort(self) -> bool:
        self.calls.append("fort")
        return True

    def meow_train(self) -> bool:
        self.calls.append("train")
        return True

    def meow_is_sunday(self) -> bool:
        self.calls.append("sunday")
        return False

    def meow_enhance(self) -> None:
        self.calls.append("enhance")


def test_meowfficer_uses_typed_purchase_and_training_plan_without_legacy_run(
    runtime: tuple[AzurLaneConfig, Device],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, device = runtime
    runner = _MeowRunner()
    monkeypatch.setattr(adapters, "RewardMeowfficer", lambda *_args, **_kwargs: runner)
    settings = MeowfficerSettings(
        buy_amount=3,
        overflow_coin_threshold=100_000,
        fort_chore_enabled=True,
        training=MeowfficerTrainingSettings(MeowfficerTrainingMode.SEAMLESSLY, timedelta(minutes=180)),
        schedule=_SCHEDULE,
    )

    report = adapters.Mumu12MeowfficerWorkflow(config, device, _Clock()).execute(settings, AbortToken())

    assert report.observed_at == _NOW
    assert config.MeowfficerTrain_Mode == "seamlessly"
    assert runner.calls == [
        "ensure",
        "wait",
        ("buy_count", 3, 100_000),
        ("choose", 2),
        "confirm",
        "fort",
        "train",
        "enhance",
    ]


class _Setting:
    def __init__(self, calls: list[object], name: str) -> None:
        self._calls = calls
        self._name = name

    def set(self, *, contains: list[str]) -> None:
        self._calls.append((self._name, tuple(contains)))


class _MailRunner:
    def __init__(self) -> None:
        self.calls: list[object] = []
        self.mail_select_setting = _Setting(self.calls, "select")
        self.mail_select_all_setting = _Setting(self.calls, "all")

    def ui_ensure(self, _page: object) -> None:
        self.calls.append("ensure")

    def mail_enter(self) -> bool:
        self.calls.append("enter")
        return True

    def mail_claim_execute(self) -> bool:
        self.calls.append("claim")
        return True

    def mail_delete(self) -> bool:
        self.calls.append("delete")
        return True

    def mail_quit(self) -> None:
        self.calls.append("quit")


def _freebies_settings() -> FreebiesSettings:
    return FreebiesSettings(
        collect_battle_pass=True,
        data_key=DataKeyPlan(force_collect=True),
        mail=MailCollectionPolicy(
            claim_merit=True,
            claim_maintenance=True,
            claim_trade_license=True,
            delete_collected=True,
        ),
        supply_pack=SupplyPackPlan(collect=True, day_of_week=2),
        schedule=_SCHEDULE,
    )


def test_mail_exposes_actual_change_and_explicit_claim_sequence(
    runtime: tuple[AzurLaneConfig, Device],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, device = runtime
    runner = _MailRunner()
    monkeypatch.setattr(adapters, "MailWhite", lambda *_args, **_kwargs: runner)

    report = adapters.Mumu12MailWorkflow(config, device, _Clock()).collect(_freebies_settings().mail, AbortToken())

    assert report == FreebieCollectionReport(changed=True, observed_at=_NOW)
    assert runner.calls == [
        "ensure",
        "enter",
        ("select", ("merit",)),
        "claim",
        "enter",
        ("select", ("coins", "oil")),
        "claim",
        "enter",
        ("select", ("coins", "oil", "gems")),
        "claim",
        "enter",
        ("select", ("coins", "oil", "cube")),
        "claim",
        "enter",
        ("all", ("all",)),
        "delete",
        "quit",
    ]


class _PrivateQuartersRunner:
    not_supported_ships: tuple[str, ...] = ()
    available_targets = ("anchorage",)

    def __init__(self) -> None:
        self.calls: list[object] = []

    def ui_ensure(self, _page: object) -> None:
        self.calls.append("ensure")

    def ui_goto(self, _page: object, *, get_ship: bool) -> None:
        self.calls.append(("goto", get_ship))

    def handle_info_bar(self) -> None:
        self.calls.append("info")

    def pq_shop_weekly_items(self) -> None:
        self.calls.append("shop")

    def pq_get_daily_count(self, retry: int) -> int:
        self.calls.append(("count", retry))
        return 1

    def pq_goto_room(self, target_ship: str, retry: int) -> bool:
        self.calls.append(("room", target_ship, retry))
        return True

    def pq_interact(self) -> None:
        self.calls.append("interact")


def test_private_quarters_reports_confirmed_interaction_status(
    runtime: tuple[AzurLaneConfig, Device],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, device = runtime
    runner = _PrivateQuartersRunner()
    monkeypatch.setattr(adapters, "PrivateQuarters", lambda *_args, **_kwargs: runner)
    settings = PrivateQuartersSettings(
        buy_roses=True,
        buy_cake=False,
        target_ship="anchorage",
        schedule=_SCHEDULE,
    )

    report = adapters.Mumu12PrivateQuartersWorkflow(config, device, _Clock()).execute(settings, AbortToken())

    assert report == PrivateQuartersReport(
        observed_at=_NOW,
        shop_attempted=True,
        interaction_status=PrivateQuartersInteractionStatus.COMPLETED,
    )
    assert config.PrivateQuarters_BuyRoses is True
    assert config.PrivateQuarters_BuyCake is False
    assert runner.calls == [
        "ensure",
        ("goto", False),
        "info",
        "shop",
        ("count", 3),
        ("room", "anchorage", 3),
        "interact",
    ]


def test_composite_production_builder_returns_all_nine_capabilities(
    runtime: tuple[AzurLaneConfig, Device],
) -> None:
    config, device = runtime

    workflows = adapters.build_mumu12_composite_workflows(config, device, clock=_Clock())

    assert isinstance(workflows.dorm, adapters.Mumu12DormWorkflow)
    assert isinstance(workflows.meowfficer, adapters.Mumu12MeowfficerWorkflow)
    assert isinstance(workflows.guild, adapters.Mumu12GuildWorkflow)
    assert isinstance(workflows.reward, adapters.Mumu12RewardWorkflow)
    assert isinstance(workflows.battle_pass, adapters.Mumu12BattlePassWorkflow)
    assert isinstance(workflows.data_key, adapters.Mumu12DataKeyWorkflow)
    assert isinstance(workflows.mail, adapters.Mumu12MailWorkflow)
    assert isinstance(workflows.supply_pack, adapters.Mumu12SupplyPackWorkflow)
    assert isinstance(workflows.private_quarters, adapters.Mumu12PrivateQuartersWorkflow)


def test_composite_adapter_has_no_legacy_scheduler_or_run_dispatch() -> None:
    source = Path(adapters.__file__).read_text(encoding="utf-8")

    for forbidden in (".run(", "task_delay(", "task_stop(", "task_call(", "import_module("):
        assert forbidden not in source
