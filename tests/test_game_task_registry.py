from pathlib import Path
from typing import TYPE_CHECKING, cast

from module.bootstrap.task_factories import GameTaskDependencies, build_game_task_registry
from module.content.activity_catalog import ActivityCatalog
from module.content.manifest import load_event_manifests
from module.gameplay.activity_factories import ActivityFactoryDependencies, ActivityWorkflows
from module.gameplay.campaign_factories import CampaignFactoryDependencies
from module.gameplay.composite_factories import CompositeWorkflows
from module.gameplay.encounter_factories import EncounterWorkflows
from module.gameplay.facility_factories import FacilityWorkflows
from module.gameplay.market_factories import MarketWorkflows
from module.gameplay.opsi_factories import OpsiWorkflows
from module.maintenance import MaintenanceServices
from module.task_registry import TASK_CATALOG

_ACTIVITY_CATALOG = ActivityCatalog(load_event_manifests(Path("content/events")))

if TYPE_CHECKING:
    from module.gameplay.activity import ActivityWorkflow, AssistSessionWorkflow, EncounterWorkflow
    from module.gameplay.campaign import CampaignWorkflow
    from module.gameplay.campaign_factories import CampaignSessionSource
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
    from module.gameplay.facility import CommissionWorkflow, ResearchWorkflow, TacticalWorkflow
    from module.gameplay.market import (
        AwakenWorkflow,
        GachaWorkflow,
        ShipyardWorkflow,
        ShopFrequentWorkflow,
        ShopOnceWorkflow,
    )
    from module.gameplay.opsi import OperationSirenWorkflow
    from module.interaction import AppLifecycle
    from module.maintenance.benchmark import BenchmarkEngine, BenchmarkEnvironment, BenchmarkPresenter
    from module.maintenance.game_manager import LoginFlow
    from module.maintenance.uncensored import UncensoredAssetBuilder, UncensoredAssetInstaller


class _Port:
    @staticmethod
    def status(*args: object) -> None:
        del args

    @staticmethod
    def start(*args: object) -> None:
        del args

    @staticmethod
    def stop(*args: object) -> None:
        del args

    @staticmethod
    def ensure_logged_in(*args: object) -> None:
        del args

    @staticmethod
    def build(*args: object) -> None:
        del args

    @staticmethod
    def install(*args: object) -> None:
        del args

    @staticmethod
    def prepare(*args: object) -> None:
        del args

    @staticmethod
    def measure(*args: object) -> None:
        del args

    @staticmethod
    def present(*args: object) -> None:
        del args

    @staticmethod
    def execute(*args: object) -> None:
        del args

    @staticmethod
    def discard_checkpoint() -> None:
        pass

    @staticmethod
    def collect(*args: object) -> None:
        del args

    @staticmethod
    def resolve(*args: object) -> None:
        del args

    @staticmethod
    def select(*args: object, **kwargs: object) -> None:
        del args, kwargs

    @staticmethod
    def advance_to_safe_point(*args: object) -> None:
        del args


def _dependencies() -> GameTaskDependencies:
    port = _Port()
    maintenance = MaintenanceServices(
        app=cast("AppLifecycle", port),
        login=cast("LoginFlow", port),
        uncensored_assets=cast("UncensoredAssetBuilder", port),
        uncensored_installer=cast("UncensoredAssetInstaller", port),
        benchmark_environment=cast("BenchmarkEnvironment", port),
        benchmark_engine=cast("BenchmarkEngine", port),
        benchmark_presenter=cast("BenchmarkPresenter", port),
    )
    facility = FacilityWorkflows(
        research=cast("ResearchWorkflow", port),
        commission=cast("CommissionWorkflow", port),
        tactical=cast("TacticalWorkflow", port),
    )
    composite = CompositeWorkflows(
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
    market = MarketWorkflows(
        awaken=cast("AwakenWorkflow", port),
        shipyard=cast("ShipyardWorkflow", port),
        gacha=cast("GachaWorkflow", port),
        shop_frequent=cast("ShopFrequentWorkflow", port),
        shop_once=cast("ShopOnceWorkflow", port),
    )
    encounter = EncounterWorkflows(
        daily=cast("DailyWorkflow", port),
        hard=cast("HardWorkflow", port),
        exercise=cast("ExerciseWorkflow", port),
    )
    campaign = CampaignFactoryDependencies(
        workflow=cast("CampaignWorkflow", port),
        sessions=cast("CampaignSessionSource", port),
    )
    opsi = OpsiWorkflows(world=cast("OperationSirenWorkflow", port))
    activity = ActivityWorkflows(
        minigame=cast("ActivityWorkflow", port),
        event_story=cast("ActivityWorkflow", port),
        raid_daily=cast("EncounterWorkflow", port),
        maritime_escort=cast("EncounterWorkflow", port),
        raid=cast("EncounterWorkflow", port),
        hospital=cast("EncounterWorkflow", port),
        coalition=cast("EncounterWorkflow", port),
        coalition_sp=cast("EncounterWorkflow", port),
        daemon=cast("AssistSessionWorkflow", port),
        opsi_daemon=cast("AssistSessionWorkflow", port),
    )
    return GameTaskDependencies(
        maintenance=maintenance,
        facility=facility,
        composite=composite,
        market=market,
        encounter=encounter,
        campaign=campaign,
        opsi=opsi,
        activity=ActivityFactoryDependencies(activity, _ACTIVITY_CATALOG),
    )


def test_game_registry_has_exactly_one_factory_for_every_catalog_task() -> None:
    registry = build_game_task_registry(
        _dependencies(),
        content_revision="content:current",
    )

    assert registry.task_ids == tuple(TASK_CATALOG)
    assert len(registry.task_ids) == 57
    assert all(registry.factory(task_id) is not None for task_id in registry.task_ids)
