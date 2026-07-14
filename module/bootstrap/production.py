import time
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from module.adapters import (
    build_mumu12_activity_workflows,
    build_mumu12_composite_workflows,
    build_mumu12_encounter_workflows,
    build_mumu12_facility_workflows,
    build_mumu12_maintenance_services,
    build_mumu12_market_workflows,
    build_mumu12_opsi_workflows,
)
from module.adapters.activity_profiles import validate_mumu12_activity_profiles
from module.adapters.campaign_mumu12 import (
    Mumu12HardCampaignPort,
    build_mumu12_campaign_dependencies,
)
from module.adapters.campaign_profiles import validate_mumu12_campaign_runtime_profiles
from module.adapters.war_archives_profiles import validate_mumu12_war_archives_profiles
from module.bootstrap.assembly_source import (
    FilesystemInstanceAssemblySource,
    GameRuntimeBundle,
    InstanceAssemblyLayout,
    JsonConfigurationDocumentSource,
)
from module.bootstrap.configuration_compiler import CompiledConfiguration, ConfigurationDocument
from module.bootstrap.process_host import InstanceProcessHost
from module.bootstrap.revisions import RevisionTree, SourceTreeRevisionSource
from module.bootstrap.runtime_provider import ProductionRuntimeProvider
from module.bootstrap.task_factories import GameTaskDependencies
from module.config.config import AzurLaneConfig
from module.content.activity_catalog import ActivityCatalog
from module.content.campaign_session_source import CompiledCampaignSessionSource
from module.content.catalog import ContentCatalog
from module.content.manifest import load_event_manifests
from module.content.runtime_profile_catalog import compile_campaign_runtime_profile_registry
from module.content.stage_loader import StageSpecLoader
from module.device.device import Device
from module.gameplay.activity_factories import ActivityFactoryDependencies
from module.gameplay.campaign_factories import HardCampaignSessionSource

if TYPE_CHECKING:
    from collections.abc import Callable

    from module.content.runtime_profile import CampaignRuntimeProfileRegistry
    from module.interaction import CancellationSignal
    from module.supervisor import LoopWakeSignal


_CONTENT_SUFFIXES = frozenset({".json", ".yaml", ".yml"})
_PYTHON_SUFFIXES = frozenset({".py"})
_ASSET_SUFFIXES = frozenset({".gif", ".jpeg", ".jpg", ".json", ".png", ".webp"})


class RevisionSource(Protocol):
    def current(self) -> str: ...


def _require_project_root(value: Path) -> Path:
    if not isinstance(value, Path):
        message = "project_root must be a Path"
        raise TypeError(message)
    root = value.resolve(strict=True)
    required = (root / "config" / "template.json", root / "content" / "events", root / "module")
    if not all(path.exists() for path in required):
        message = f"project_root is not an ALAS source tree: {root}"
        raise ValueError(message)
    return root


def _default_sessions(
    project_root: Path,
    catalog: ContentCatalog,
    profiles: CampaignRuntimeProfileRegistry,
) -> CompiledCampaignSessionSource:
    content_root = project_root / "content" / "events"
    return CompiledCampaignSessionSource(
        catalog,
        StageSpecLoader(content_root, runtime_profile_registry=profiles),
    )


class SystemLoopClock:
    """UTC wall clock + monotonic, cancellation-aware waiting for the process loop."""

    @staticmethod
    def now() -> datetime:
        return datetime.now(tz=UTC)

    @staticmethod
    def sleep(
        seconds: float,
        cancellation: CancellationSignal,
        wake_signal: LoopWakeSignal | None = None,
    ) -> None:
        if type(seconds) not in {int, float} or seconds < 0:
            message = "sleep seconds must be a non-negative number"
            raise ValueError(message)
        deadline = time.monotonic() + seconds
        while True:
            cancellation.raise_if_requested()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            interval = min(remaining, 0.25)
            if wake_signal is not None and wake_signal.wait(interval):
                cancellation.raise_if_requested()
                return
            if wake_signal is None:
                time.sleep(interval)


class Mumu12GameRuntimeBundleSource:
    """把一个不可变配置快照组装成唯一的 MuMu12 production dependency graph。"""

    __slots__ = (
        "_client_ui_revision",
        "_content_revision",
        "_device_factory",
        "_project_root",
        "_sessions_factory",
    )

    def __init__(
        self,
        project_root: Path,
        *,
        device_factory: Callable[[AzurLaneConfig], Device] = Device,
        sessions_factory: Callable[
            [Path, ContentCatalog, CampaignRuntimeProfileRegistry],
            HardCampaignSessionSource,
        ] = _default_sessions,
        content_revision: RevisionSource | None = None,
        client_ui_revision: RevisionSource | None = None,
    ) -> None:
        root = _require_project_root(project_root)
        if isinstance(device_factory, type) and not issubclass(device_factory, Device):
            message = "device_factory must build Device"
            raise TypeError(message)
        if not callable(device_factory):
            message = "device_factory must be callable"
            raise TypeError(message)
        if not callable(sessions_factory):
            message = "sessions_factory must be callable"
            raise TypeError(message)
        default_content_revision = SourceTreeRevisionSource(
            "content-v1",
            (
                RevisionTree(root / "content", _CONTENT_SUFFIXES),
                RevisionTree(root / "module" / "content", _PYTHON_SUFFIXES),
            ),
        )
        default_client_revision = SourceTreeRevisionSource(
            "client-ui-v1",
            (
                RevisionTree(root / "module", _PYTHON_SUFFIXES),
                RevisionTree(root / "assets", _ASSET_SUFFIXES),
            ),
        )
        selected_content = default_content_revision if content_revision is None else content_revision
        selected_client = default_client_revision if client_ui_revision is None else client_ui_revision
        for field_name, source in (
            ("content_revision", selected_content),
            ("client_ui_revision", selected_client),
        ):
            if isinstance(source, type) or not callable(getattr(source, "current", None)):
                message = f"{field_name} must implement current()"
                raise TypeError(message)
        self._project_root = root
        self._device_factory = device_factory
        self._sessions_factory = sessions_factory
        self._content_revision = selected_content
        self._client_ui_revision = selected_client

    def build(
        self,
        instance_name: str,
        document: ConfigurationDocument,
        configuration: CompiledConfiguration,
    ) -> GameRuntimeBundle:
        if not isinstance(configuration, CompiledConfiguration):
            message = "configuration must be a CompiledConfiguration"
            raise TypeError(message)
        config = AzurLaneConfig.from_snapshot(instance_name, document)
        if config.Emulator_Serial != configuration.device_serial:
            message = "compiled device serial does not match the bound configuration snapshot"
            raise ValueError(message)
        packs = load_event_manifests(self._project_root / "content" / "events")
        content_catalog = ContentCatalog(packs)
        validate_mumu12_war_archives_profiles(content_catalog)
        activities = ActivityCatalog(content_catalog.packs)
        validate_mumu12_activity_profiles(activities)
        runtime_profiles = compile_campaign_runtime_profile_registry(
            self._project_root / "content" / "campaign-runtime-profiles.json"
        )
        validate_mumu12_campaign_runtime_profiles(content_catalog.stages, runtime_profiles)
        sessions = self._sessions_factory(self._project_root, content_catalog, runtime_profiles)
        if not isinstance(sessions, HardCampaignSessionSource):
            message = "sessions_factory must return a HardCampaignSessionSource"
            raise TypeError(message)
        device = self._device_factory(config)
        if not isinstance(device, Device):
            message = "device_factory must return a Device"
            raise TypeError(message)
        device.config = config

        hard_campaign = Mumu12HardCampaignPort(config, device, sessions)
        dependencies = GameTaskDependencies(
            maintenance=build_mumu12_maintenance_services(config, device),
            facility=build_mumu12_facility_workflows(config, device),
            composite=build_mumu12_composite_workflows(config, device),
            market=build_mumu12_market_workflows(config, device),
            encounter=build_mumu12_encounter_workflows(
                config,
                device,
                hard_campaign=hard_campaign,
            ),
            campaign=build_mumu12_campaign_dependencies(config, device, sessions),
            opsi=build_mumu12_opsi_workflows(config, device),
            activity=ActivityFactoryDependencies(
                workflows=build_mumu12_activity_workflows(config, device),
                catalog=activities,
            ),
        )
        return GameRuntimeBundle(
            tasks=dependencies,
            content_revision=self._content_revision.current(),
            client_ui_revision=self._client_ui_revision.current(),
        )


def build_default_instance_process_host(project_root: Path | None = None) -> InstanceProcessHost:
    """构造 WebUI/CLI/scheduler 共用的 production process host。"""

    root = _require_project_root(
        Path(__file__).resolve().parents[2] if project_root is None else project_root,
    )
    runtime_root = root / ".alas-runtime"
    source = FilesystemInstanceAssemblySource(
        JsonConfigurationDocumentSource(root / "config", root / "config" / "template.json"),
        Mumu12GameRuntimeBundleSource(root),
        InstanceAssemblyLayout(
            state_root=runtime_root / "state",
            lease_lock_root=runtime_root / "device-leases",
        ),
    )
    return InstanceProcessHost(ProductionRuntimeProvider(source, SystemLoopClock()))
