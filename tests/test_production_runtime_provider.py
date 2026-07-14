from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, cast

import module.bootstrap.runtime_provider as runtime_provider_module
from module.bootstrap import (
    CompiledConfiguration,
    GameTaskDependencies,
    InstanceAssembly,
    ProductionRuntimeProvider,
)
from module.content import ActivityCatalog
from module.content.manifest import load_event_manifests
from module.gameplay.activity_factories import ActivityFactoryDependencies, ActivityWorkflows
from module.gameplay.campaign_factories import CampaignFactoryDependencies
from module.gameplay.composite_factories import CompositeWorkflows
from module.gameplay.encounter_factories import EncounterWorkflows
from module.gameplay.facility_factories import FacilityWorkflows
from module.gameplay.market_factories import MarketWorkflows
from module.gameplay.opsi_factories import OpsiWorkflows
from module.maintenance import MaintenanceServices
from module.runtime import InstanceRuntimeConfig, TaskFactoryRegistry
from module.state import ConfigurationSourceSnapshot

_ACTIVITY_CATALOG = ActivityCatalog(load_event_manifests(Path("content/events")))

if TYPE_CHECKING:
    import pytest

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
    from module.runtime import InstanceRuntime


class _Port:
    def __getattr__(self, name: str) -> object:
        del name

        def method(*args: object, **kwargs: object) -> None:
            del args, kwargs

        return method


def _dependencies() -> GameTaskDependencies:
    port = _Port()
    return GameTaskDependencies(
        maintenance=MaintenanceServices(
            app=cast("AppLifecycle", port),
            login=cast("LoginFlow", port),
            uncensored_assets=cast("UncensoredAssetBuilder", port),
            uncensored_installer=cast("UncensoredAssetInstaller", port),
            benchmark_environment=cast("BenchmarkEnvironment", port),
            benchmark_engine=cast("BenchmarkEngine", port),
            benchmark_presenter=cast("BenchmarkPresenter", port),
        ),
        facility=FacilityWorkflows(
            research=cast("ResearchWorkflow", port),
            commission=cast("CommissionWorkflow", port),
            tactical=cast("TacticalWorkflow", port),
        ),
        composite=CompositeWorkflows(
            dorm=cast("DormWorkflow", port),
            meowfficer=cast("MeowfficerWorkflow", port),
            guild=cast("GuildWorkflow", port),
            reward=cast("RewardWorkflow", port),
            battle_pass=cast("FreebieCollectionWorkflow", port),
            data_key=cast("DataKeyWorkflow", port),
            mail=cast("MailCollectionWorkflow", port),
            supply_pack=cast("SupplyPackWorkflow", port),
            private_quarters=cast("PrivateQuartersWorkflow", port),
        ),
        market=MarketWorkflows(
            awaken=cast("AwakenWorkflow", port),
            shipyard=cast("ShipyardWorkflow", port),
            gacha=cast("GachaWorkflow", port),
            shop_frequent=cast("ShopFrequentWorkflow", port),
            shop_once=cast("ShopOnceWorkflow", port),
        ),
        encounter=EncounterWorkflows(
            daily=cast("DailyWorkflow", port),
            hard=cast("HardWorkflow", port),
            exercise=cast("ExerciseWorkflow", port),
        ),
        campaign=CampaignFactoryDependencies(
            workflow=cast("CampaignWorkflow", port),
            sessions=cast("CampaignSessionSource", port),
        ),
        opsi=OpsiWorkflows(world=cast("OperationSirenWorkflow", port)),
        activity=ActivityFactoryDependencies(
            ActivityWorkflows(
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
            ),
            _ACTIVITY_CATALOG,
        ),
    )


class _Clock:
    @staticmethod
    def now() -> datetime:
        return datetime(2026, 7, 13, tzinfo=UTC)

    @staticmethod
    def sleep(seconds: float, cancellation: object) -> None:
        del seconds, cancellation


class _Publisher:
    @staticmethod
    def publish(*, topic: str, payload: object, key: str | None, idempotency_key: str) -> None:
        del topic, payload, key, idempotency_key


class _Runtime:
    def __init__(self, calls: list[tuple[object, ...]], *, source_revision: str | None = None) -> None:
        self._calls = calls
        self._source_revision = source_revision

    def read_configuration_source(self) -> ConfigurationSourceSnapshot | None:
        self._calls.append(("configuration-source",))
        if self._source_revision is None:
            return None
        return ConfigurationSourceSnapshot(
            source_revision=self._source_revision,
            settings_revision=1,
            updated_at=_Clock.now(),
        )

    def read_settings(self) -> None:
        self._calls.append(("settings",))

    def publish_configuration(
        self,
        payload: object,
        schedules: object,
        *,
        source_revision: str,
        expected_revision: int,
    ) -> None:
        self._calls.append(("publish-configuration", payload, schedules, source_revision, expected_revision))

    @staticmethod
    def close() -> None:
        pass


@dataclass(slots=True)
class _Source:
    assembly: InstanceAssembly
    names: list[str] = field(default_factory=list)

    def load(self, instance_name: str) -> InstanceAssembly:
        self.names.append(instance_name)
        return self.assembly


def test_provider_builds_registry_and_runtime_from_one_instance_assembly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[object, ...]] = []
    dependencies = _dependencies()
    configuration = CompiledConfiguration(
        payload={"schema_version": 1, "tasks": {}},
        schedules=(),
        device_serial="127.0.0.1:16384",
        source_revision="sha256:" + "0" * 64,
    )
    assembly = InstanceAssembly(
        runtime=InstanceRuntimeConfig(
            state_path=Path("state/alas.sqlite3"),
            lease_lock_root=Path("state/leases"),
            device_serial="127.0.0.1:16384",
            lease_owner="alas-process",
        ),
        tasks=dependencies,
        configuration=configuration,
        content_revision="content:current",
        client_ui_revision="ui:current",
    )
    source = _Source(assembly)
    registry = cast("TaskFactoryRegistry", object())
    runtime = cast("InstanceRuntime", _Runtime(calls))

    def build_registry(
        tasks: GameTaskDependencies,
        *,
        content_revision: str,
        client_ui_revision: str,
    ) -> TaskFactoryRegistry:
        calls.append(("registry", tasks, content_revision, client_ui_revision))
        return registry

    def build_runtime(*args: object, **kwargs: object) -> InstanceRuntime:
        calls.append(("runtime", *args, kwargs))
        return runtime

    monkeypatch.setattr(runtime_provider_module, "build_game_task_registry", build_registry)
    monkeypatch.setattr(runtime_provider_module, "InstanceRuntime", build_runtime)
    clock = _Clock()
    publisher = _Publisher()

    opened = ProductionRuntimeProvider(source, clock, outbox_publisher=publisher).open("alas")

    assert opened is runtime
    assert source.names == ["alas"]
    assert calls == [
        ("registry", dependencies, "content:current", "ui:current"),
        (
            "runtime",
            assembly.runtime,
            registry,
            clock,
            {"outbox_publisher": publisher},
        ),
        ("configuration-source",),
        ("settings",),
        (
            "publish-configuration",
            configuration.payload,
            configuration.schedules,
            configuration.source_revision,
            0,
        ),
    ]


def test_provider_does_not_publish_or_reset_schedule_when_compiled_revision_is_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configuration = CompiledConfiguration(
        payload={"schema_version": 1, "tasks": {}},
        schedules=(),
        device_serial="127.0.0.1:16384",
        source_revision="sha256:" + "0" * 64,
    )
    calls: list[tuple[object, ...]] = []
    runtime = _Runtime(calls, source_revision=configuration.source_revision)
    assembly = InstanceAssembly(
        runtime=InstanceRuntimeConfig(
            state_path=Path("state/alas.sqlite3"),
            lease_lock_root=Path("state/leases"),
            device_serial=configuration.device_serial,
            lease_owner="alas-process",
        ),
        tasks=_dependencies(),
        configuration=configuration,
        content_revision="content:current",
        client_ui_revision="ui:current",
    )
    registry = cast("TaskFactoryRegistry", object())

    def build_registry(*args: object, **kwargs: object) -> TaskFactoryRegistry:
        del args, kwargs
        return registry

    def build_runtime(*args: object, **kwargs: object) -> InstanceRuntime:
        del args, kwargs
        return cast("InstanceRuntime", runtime)

    monkeypatch.setattr(runtime_provider_module, "build_game_task_registry", build_registry)
    monkeypatch.setattr(runtime_provider_module, "InstanceRuntime", build_runtime)

    opened = ProductionRuntimeProvider(_Source(assembly), _Clock()).open("alas")

    assert opened is runtime
    assert calls == [("configuration-source",)]
