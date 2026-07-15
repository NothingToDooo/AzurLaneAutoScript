from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest

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
from module.notify import DisabledNotificationConfig
from module.runtime import (
    InstanceRuntimeConfig,
    OutboxDelivery,
    OutboxFailureFact,
    RuntimeConfigurationSnapshot,
    TaskFactoryRegistry,
)

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
    from module.runtime import InstanceRuntime


def test_outbox_failure_log_includes_the_original_message(monkeypatch: pytest.MonkeyPatch) -> None:
    logs: list[str] = []
    monkeypatch.setattr(runtime_provider_module.logger, "error", logs.append)
    failure = OutboxFailureFact(
        message_id="message-1",
        topic="operator.notification.requested",
        error_type="RuntimeError",
        error_message="SMTP server rejected local credentials",
        attempt_count=1,
        available_at=datetime(2026, 7, 14, tzinfo=UTC),
        discarded_at=None,
    )

    runtime_provider_module._report_outbox_failure(failure)  # noqa: SLF001

    assert len(logs) == 1
    assert "error_message='SMTP server rejected local credentials'" in logs[0]


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
    def sleep(seconds: float, cancellation: object, wake_signal: object | None = None) -> None:
        del seconds, cancellation, wake_signal


class _Publisher:
    @staticmethod
    def publish(*, topic: str, payload: object, key: str | None, idempotency_key: str) -> None:
        del topic, payload, key, idempotency_key


class _Runtime:
    @staticmethod
    def close() -> None:
        pass


class _Signal:
    @staticmethod
    def wait(timeout: float) -> bool:
        del timeout
        return False

    @staticmethod
    def clear() -> None:
        pass


class _Control:
    closed = False

    def close(self) -> None:
        self.closed = True


@dataclass(slots=True)
class _Source:
    assembly: InstanceAssembly
    events: list[tuple[object, ...]] = field(default_factory=list)
    signal: _Signal = field(default_factory=_Signal)

    def load(self, instance_name: str) -> InstanceAssembly:
        self.events.append(("load", instance_name))
        return self.assembly

    def load_configuration(self, instance_name: str) -> CompiledConfiguration:
        self.events.append(("load-configuration", instance_name))
        return self.assembly.configuration

    def configuration_signal(self, instance_name: str, external: object | None = None) -> _Signal:
        self.events.append(("configuration-signal", instance_name, external))
        return self.signal


def test_provider_builds_registry_and_runtime_from_one_instance_assembly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[object, ...]] = []
    dependencies = _dependencies()
    configuration = CompiledConfiguration(
        payload={"schema_version": 1, "tasks": {}},
        schedules=(),
        notification=DisabledNotificationConfig(),
        device_serial="127.0.0.1:16384",
        source_revision="sha256:" + "0" * 64,
        assembly_revision="sha256:" + "1" * 64,
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
    runtime = cast("InstanceRuntime", _Runtime())
    control = _Control()

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

    def build_control(**kwargs: object) -> _Control:
        calls.append(("control", kwargs))
        return control

    def build_outbox(instance_name: str) -> _Publisher:
        calls.append(("outbox", instance_name))
        return publisher

    monkeypatch.setattr(runtime_provider_module, "build_game_task_registry", build_registry)
    monkeypatch.setattr(runtime_provider_module, "InstanceRuntime", build_runtime)
    monkeypatch.setattr(runtime_provider_module, "RuntimeConfigurationControl", build_control)
    clock = _Clock()
    publisher = _Publisher()
    external_signal = _Signal()

    opened = ProductionRuntimeProvider(source, clock, outbox_publisher_factory=build_outbox).open(
        "alas",
        configuration_signal=external_signal,
    )

    assert opened is runtime
    assert source.events == [
        ("configuration-signal", "alas", external_signal),
        ("load", "alas"),
    ]
    assert calls[0] == ("registry", dependencies, "content:current", "ui:current")
    assert calls[1][0] == "control"
    control_arguments = cast("dict[str, object]", calls[1][1])
    assert control_arguments["state_path"] == assembly.runtime.state_path
    assert control_arguments["factories"] is registry
    assert control_arguments["clock"] is clock
    assert control_arguments["signal"] is source.signal
    assert control_arguments["initial"] == RuntimeConfigurationSnapshot(
        payload=configuration.payload,
        schedules=configuration.schedules,
        source_revision=configuration.source_revision,
        assembly_revision=configuration.assembly_revision,
        device_serial=configuration.device_serial,
    )
    assert callable(control_arguments["error_reporter"])
    assert calls[2] == ("outbox", "alas")
    assert calls[3][0:4] == ("runtime", assembly.runtime, registry, clock)
    runtime_arguments = cast("dict[str, object]", calls[3][4])
    assert runtime_arguments["configuration_control"] is control
    outbox = runtime_arguments["outbox"]
    assert isinstance(outbox, OutboxDelivery)
    assert outbox.publisher is publisher
    assert callable(outbox.failure_reporter)


def test_provider_closes_configuration_control_when_runtime_construction_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configuration = CompiledConfiguration(
        payload={"schema_version": 1, "tasks": {}},
        schedules=(),
        notification=DisabledNotificationConfig(),
        device_serial="127.0.0.1:16384",
        source_revision="sha256:" + "0" * 64,
        assembly_revision="sha256:" + "1" * 64,
    )
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
    control = _Control()

    def build_registry(*args: object, **kwargs: object) -> TaskFactoryRegistry:
        del args, kwargs
        return registry

    def build_runtime(*args: object, **kwargs: object) -> InstanceRuntime:
        del args, kwargs
        message = "runtime failed"
        raise RuntimeError(message)

    monkeypatch.setattr(runtime_provider_module, "build_game_task_registry", build_registry)
    monkeypatch.setattr(runtime_provider_module, "InstanceRuntime", build_runtime)
    monkeypatch.setattr(runtime_provider_module, "RuntimeConfigurationControl", lambda **_kwargs: control)

    with pytest.raises(RuntimeError, match="runtime failed"):
        ProductionRuntimeProvider(
            _Source(assembly),
            _Clock(),
            outbox_publisher_factory=lambda _instance_name: _Publisher(),
        ).open("alas")

    assert control.closed is True


def test_provider_closes_configuration_control_when_outbox_factory_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configuration = CompiledConfiguration(
        payload={"schema_version": 1, "tasks": {}},
        schedules=(),
        notification=DisabledNotificationConfig(),
        device_serial="127.0.0.1:16384",
        source_revision="sha256:" + "0" * 64,
        assembly_revision="sha256:" + "1" * 64,
    )
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
    control = _Control()
    monkeypatch.setattr(runtime_provider_module, "build_game_task_registry", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(runtime_provider_module, "RuntimeConfigurationControl", lambda **_kwargs: control)

    def fail_outbox(_instance_name: str) -> _Publisher:
        message = "outbox failed"
        raise RuntimeError(message)

    with pytest.raises(RuntimeError, match="outbox failed"):
        ProductionRuntimeProvider(
            _Source(assembly),
            _Clock(),
            outbox_publisher_factory=fail_outbox,
        ).open("alas")

    assert control.closed is True
