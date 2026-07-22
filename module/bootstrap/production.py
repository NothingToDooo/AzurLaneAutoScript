import time
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Protocol, override

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
from module.application import (
    AbortToken,
    Faulted,
    OperatorNotificationKind,
    TaskId,
    TaskResult,
)
from module.base.atomic import atomic_write
from module.bootstrap.assembly_source import (
    JsonConfigurationDocumentSource,
)
from module.bootstrap.configuration_compiler import (
    CompiledConfiguration,
    ConfigurationCompileError,
    ConfigurationDocument,
    WebConfigurationCompiler,
)
from module.bootstrap.revisions import RevisionTree, SourceTreeRevisionSource
from module.config.config import AzurLaneConfig, Function
from module.config.deep import deep_set
from module.content.activity_catalog import ActivityCatalog
from module.content.campaign_session_source import CompiledCampaignSessionSource
from module.content.catalog import ContentCatalog
from module.content.errors import (
    ContentValidationError,
    UnknownActivityError,
    UnknownPackError,
    UnknownStageError,
)
from module.content.manifest import load_event_manifests
from module.content.runtime_profile_catalog import compile_campaign_runtime_profile_registry
from module.content.stage_loader import StageSpecLoader
from module.device.device import Device
from module.diagnostics import ErrorBundleContext, ScreenshotHistory, write_error_bundle
from module.gameplay.activity_factories import ActivityFactoryDependencies, build_activity_factories
from module.gameplay.campaign import CAMPAIGN_JOB_KINDS
from module.gameplay.campaign_factories import HardCampaignSessionSource, build_campaign_factories
from module.gameplay.composite_factories import build_composite_factories
from module.gameplay.encounter_factories import build_encounter_factories
from module.gameplay.facility_factories import build_facility_factories
from module.gameplay.market_factories import build_market_factories
from module.gameplay.opsi import WORLD_TASK_DEFINITIONS
from module.gameplay.opsi_factories import build_opsi_factories
from module.logger import get_log_file, logger
from module.maintenance import build_maintenance_factories
from module.notify.configuration import DisabledNotificationConfig, NotificationConfig, SmtpNotificationConfig
from module.notify.direct import send_notification
from module.project_paths import PROJECT_ROOT
from module.runtime.errors import RuntimeCompositionError
from module.runtime.factories import TaskFactory, TaskFactoryRegistry
from module.runtime.runner import CommandOutcome, CommandStatus, RuntimeRunner
from module.state.config_repository import ConfigRepositoryClock, ConfigStateRepository
from module.task_registry import TASK_CATALOG, get_task_definition

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping

    from module.application import CancellationSource, ExternalRequestSignal
    from module.content.runtime_profile import CampaignRuntimeProfileRegistry


_CONTENT_SUFFIXES = frozenset({".json", ".yaml", ".yml"})
_PYTHON_SUFFIXES = frozenset({".py"})
_CONTENTLESS_REVISION = "builtin-content-v1"

_DOMAIN_TASKS: tuple[tuple[str, frozenset[str]], ...] = (
    ("maintenance", frozenset({"restart", "azur_lane_uncensored", "game_manager", "benchmark"})),
    ("facility", frozenset({"research", "commission", "tactical"})),
    ("composite", frozenset({"dorm", "meowfficer", "guild", "reward", "freebies", "private_quarters"})),
    ("market", frozenset({"awaken", "shipyard", "gacha", "shop_frequent", "shop_once"})),
    ("encounter", frozenset({"daily", "hard", "exercise"})),
    ("campaign", frozenset(task_id.value for task_id in CAMPAIGN_JOB_KINDS)),
    ("opsi", frozenset(task_id.value for task_id in WORLD_TASK_DEFINITIONS)),
    (
        "activity",
        frozenset(
            {
                "minigame",
                "event_story",
                "raid_daily",
                "maritime_escort",
                "raid",
                "hospital",
                "coalition",
                "coalition_sp",
                "daemon",
                "opsi_daemon",
            }
        ),
    ),
)
_EVENT_CONTENT_TASKS = frozenset(
    {
        "event_story",
        "raid_daily",
        "maritime_escort",
        "raid",
        "hospital",
        "coalition",
        "coalition_sp",
    }
)
_CAMPAIGN_CONTENT_TASKS = frozenset({"hard", *(task_id.value for task_id in CAMPAIGN_JOB_KINDS)})


def _index_task_domains() -> Mapping[str, str]:
    domains: dict[str, str] = {}
    duplicates: set[str] = set()
    for domain, task_ids in _DOMAIN_TASKS:
        for task_id in task_ids:
            if task_id in domains:
                duplicates.add(task_id)
            domains[task_id] = domain
    if duplicates:
        message = f"task domains overlap: {sorted(duplicates)}"
        raise RuntimeError(message)
    if set(domains) != set(TASK_CATALOG):
        missing = sorted(set(TASK_CATALOG) - set(domains))
        unknown = sorted(set(domains) - set(TASK_CATALOG))
        message = f"task domain coverage mismatch: missing={missing}, unknown={unknown}"
        raise RuntimeError(message)
    return MappingProxyType(domains)


_TASK_DOMAINS = _index_task_domains()


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


def ensure_personal_configuration(project_root: Path) -> Path:
    """首次运行时从模板创建唯一的 alas.json，之后不再使用双配置来源。"""
    root = _require_project_root(project_root)
    destination = root / "config" / "alas.json"
    if destination.is_file():
        return destination
    template = root / "config" / "template.json"
    atomic_write(destination, template.read_bytes())
    return destination


class PersonalRuntimeConfig(AzurLaneConfig):
    """经唯一 ConfigStateRepository 读取和提交 legacy driver 字段。"""

    def __init__(self, repository: ConfigStateRepository) -> None:
        if not isinstance(repository, ConfigStateRepository):
            message = "repository must be a ConfigStateRepository"
            raise TypeError(message)
        self._personal_repository = repository
        super().__init__("alas")

    @override
    def load(self) -> None:
        self.data = self._personal_repository.runtime_document()
        for path, value in self.modified.items():
            deep_set(self.data, keys=path, value=value)

    @override
    def bind(self, func: Function | str, func_list: Iterable[str] | None = None) -> None:
        # repository 可能在上一任务结束时提交 Scheduler/Storage，绑定下一任务前刷新共享快照。
        self.load()
        super().bind(func, func_list=func_list)

    @override
    def save(self) -> bool:
        if not self.modified:
            return False
        self.data = self._personal_repository.apply_runtime_updates(self.modified)
        self.modified.clear()
        return True


class _ConfigurationValidationConfig(PersonalRuntimeConfig):
    """只读候选配置；若 composition 尝试写盘则立即失败。"""

    @override
    def save(self) -> bool:
        if self.modified:
            message = "configuration validation must not persist runtime changes"
            raise RuntimeError(message)
        return False


class _ConfigurationValidationDevice(Device):
    """只暴露 factory composition 需要的配置，不建立 ADB 或截图连接。"""

    @override
    def __init__(self, config: AzurLaneConfig) -> None:
        self.config = config


def validate_personal_configuration(
    document: ConfigurationDocument,
    *,
    project_root: Path | None = None,
) -> CompiledConfiguration:
    """用真实内容和全部玩法 factory 校验候选配置，但不连接设备或写盘。"""

    root = _require_project_root(
        PROJECT_ROOT if project_root is None else project_root,
    )
    try:
        compiled, registry, _repository, _screenshots = PersonalRuntimeBuilder(
            root,
            "alas",
            config_factory=_ConfigurationValidationConfig,
            device_factory=_ConfigurationValidationDevice,
        ).build(document, clock=SystemLoopClock())
        registry.validate_settings(compiled.tasks, compiled.task_revisions)
    except ConfigurationCompileError:
        raise
    except (
        ContentValidationError,
        RuntimeCompositionError,
        UnknownActivityError,
        UnknownPackError,
        UnknownStageError,
        ValueError,
    ) as error:
        message = f"$ compiled task settings are invalid: {error}"
        raise ConfigurationCompileError(message) from error
    return compiled


def _validate_command(command: str) -> None:
    if not isinstance(command, str) or not command or command != command.strip():
        message = "command must be trimmed and non-empty"
        raise ValueError(message)
    if command != "alas" and get_task_definition(command) is None:
        message = f"unknown task command: {command}"
        raise ValueError(message)


_CAMPAIGN_NOTIFICATION_REASONS = {
    OperatorNotificationKind.CAMPAIGN_RUN_COUNT_LIMIT: "reached run count limit",
    OperatorNotificationKind.CAMPAIGN_REACH_LEVEL_LIMIT: "reached level limit",
    OperatorNotificationKind.CAMPAIGN_NEW_SHIP: "got new ship",
}


def _notify(config: NotificationConfig, *, title: str, content: str) -> None:
    if isinstance(config, DisabledNotificationConfig):
        return
    if not isinstance(config, SmtpNotificationConfig):
        message = "unsupported notification configuration"
        raise TypeError(message)
    send_notification(config, title=title, content=content)


def _log_path() -> Path | None:
    try:
        return Path(get_log_file())
    except RuntimeError:
        return None


def _save_error_bundle(
    *,
    root: Path,
    command: str,
    task_id: str | None,
    error: BaseException,
    screenshots: ScreenshotHistory | None,
) -> str | None:
    try:
        bundle = write_error_bundle(
            ErrorBundleContext(
                command=command,
                task_id=task_id,
                occurred_at=datetime.now().astimezone(),
            ),
            error,
            () if screenshots is None else screenshots.snapshot(),
            log_file=_log_path(),
            root=root / "log" / "error",
        )
    except Exception as bundle_error:  # ruff:ignore[blind-except] - 诊断旁路不能改写原始错误。
        logger.exception(bundle_error)
        return None
    logger.error(f"Error bundle saved to {bundle}")
    return str(bundle)


def _observe_result(  # ruff:ignore[too-many-arguments] - 结果边界需要运行命令、诊断和通知上下文。
    task_id: TaskId,
    result: TaskResult,
    *,
    root: Path,
    command: str,
    screenshots: ScreenshotHistory,
    notification: NotificationConfig,
) -> str | None:
    bundle: str | None = None
    if isinstance(result.outcome, Faulted):
        error = result.outcome.error
        bundle = _save_error_bundle(
            root=root,
            command=command,
            task_id=task_id.value,
            error=error,
            screenshots=screenshots,
        )
        summary = f"<{task_id.value}> {type(error).__name__}: {error}"
        if bundle is not None:
            summary = f"{summary}\nError bundle: {bundle}"
        _notify(notification, title="Alas crashed", content=summary)

    for request in result.notifications:
        reason = _CAMPAIGN_NOTIFICATION_REASONS.get(request.kind)
        if reason is None:
            message = f"unsupported task notification: {request.kind.value}"
            raise ValueError(message)
        _notify(
            notification,
            title="Alas campaign finished",
            content=f"<{task_id.value}> {request.resource} {reason}",
        )
    return bundle


def _failed_outcome(command: str, error: BaseException, *, bundle: str | None) -> CommandOutcome:
    return CommandOutcome(
        command=command,
        status=CommandStatus.FAILED,
        finished_at=datetime.now(tz=UTC),
        exception_type=type(error).__name__,
        message=str(error),
        error_bundle=bundle,
    )


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
    """为个人调度循环提供 UTC 时钟和可取消等待。"""

    @staticmethod
    def now() -> datetime:
        return datetime.now(tz=UTC)

    @staticmethod
    def sleep(
        seconds: float,
        cancellation: CancellationSource,
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
            time.sleep(interval)


class PersonalRuntimeBuilder:
    """按命令组装一次个人 MuMu12 runtime。"""

    __slots__ = (
        "_campaign_revision",
        "_command",
        "_config_factory",
        "_device_factory",
        "_event_revision",
        "_project_root",
        "_sessions_factory",
    )

    def __init__(  # ruff:ignore[too-many-arguments] - 唯一 composition root 显式接收可替换的边界依赖。
        self,
        project_root: Path,
        command: str,
        *,
        config_factory: Callable[[ConfigStateRepository], AzurLaneConfig] = PersonalRuntimeConfig,
        device_factory: Callable[[AzurLaneConfig], Device] = Device,
        sessions_factory: Callable[
            [Path, ContentCatalog, CampaignRuntimeProfileRegistry],
            HardCampaignSessionSource,
        ] = _default_sessions,
        event_revision: RevisionSource | None = None,
        campaign_revision: RevisionSource | None = None,
    ) -> None:
        root = _require_project_root(project_root)
        _validate_command(command)
        if not callable(config_factory):
            message = "config_factory must be callable"
            raise TypeError(message)
        if isinstance(device_factory, type) and not issubclass(device_factory, Device):
            message = "device_factory must build Device"
            raise TypeError(message)
        if not callable(device_factory):
            message = "device_factory must be callable"
            raise TypeError(message)
        if not callable(sessions_factory):
            message = "sessions_factory must be callable"
            raise TypeError(message)

        selected_event_revision = (
            SourceTreeRevisionSource(
                "event-content-v1",
                (
                    RevisionTree(root / "content" / "events", _CONTENT_SUFFIXES),
                    RevisionTree(root / "module" / "content", _PYTHON_SUFFIXES),
                ),
            )
            if event_revision is None
            else event_revision
        )
        selected_campaign_revision = (
            SourceTreeRevisionSource(
                "campaign-content-v1",
                (
                    RevisionTree(root / "content", _CONTENT_SUFFIXES),
                    RevisionTree(root / "module" / "content", _PYTHON_SUFFIXES),
                ),
            )
            if campaign_revision is None
            else campaign_revision
        )
        for field_name, source in (
            ("event_revision", selected_event_revision),
            ("campaign_revision", selected_campaign_revision),
        ):
            if isinstance(source, type) or not callable(getattr(source, "current", None)):
                message = f"{field_name} must implement current()"
                raise TypeError(message)

        self._project_root = root
        self._command = command
        self._config_factory = config_factory
        self._device_factory = device_factory
        self._sessions_factory = sessions_factory
        self._event_revision = selected_event_revision
        self._campaign_revision = selected_campaign_revision

    def build(
        self,
        document: ConfigurationDocument,
        *,
        clock: ConfigRepositoryClock,
    ) -> tuple[CompiledConfiguration, TaskFactoryRegistry, ConfigStateRepository, ScreenshotHistory]:
        """编译候选配置，并只组装当前命令需要的领域。"""

        configuration = WebConfigurationCompiler().compile(document)
        repository = ConfigStateRepository(
            clock,
            config_path=self._project_root / "config" / "alas.json",
            initial_document=document,
            initial_runtime_document=configuration.runtime_document,
        )
        config = self._config_factory(repository)
        if not isinstance(config, AzurLaneConfig):
            message = "config_factory must return an AzurLaneConfig"
            raise TypeError(message)
        if config.Emulator_Serial != configuration.device_serial:
            message = "compiled device serial does not match the bound configuration"
            raise ValueError(message)

        domains = self._selected_domains()
        activities, sessions = self._prepare_content(domains)
        device = self._device_factory(config)
        if not isinstance(device, Device):
            message = "device_factory must return a Device"
            raise TypeError(message)
        device.config = config

        factories: dict[str, TaskFactory] = {}
        for domain in domains:
            group = self._build_domain_factories(
                domain,
                config=config,
                device=device,
                activities=activities,
                sessions=sessions,
            )
            duplicate = set(factories) & set(group)
            if duplicate:
                message = f"duplicate task factories: {sorted(duplicate)}"
                raise RuntimeCompositionError(message)
            factories.update(group)

        catalog = TASK_CATALOG if self._command == "alas" else {self._command: TASK_CATALOG[self._command]}
        selected_factories = {task_id: factories[task_id] for task_id in catalog if task_id in factories}
        registry = TaskFactoryRegistry(
            catalog=catalog,
            factories=selected_factories,
            content_revisions=self._content_revisions(tuple(catalog)),
        )
        return configuration, registry, repository, device.error_screenshots

    def _selected_domains(self) -> tuple[str, ...]:
        if self._command == "alas":
            return tuple(domain for domain, _task_ids in _DOMAIN_TASKS)
        return (_TASK_DOMAINS[self._command],)

    def _prepare_content(
        self,
        domains: tuple[str, ...],
    ) -> tuple[ActivityCatalog | None, HardCampaignSessionSource | None]:
        needs_activity = "activity" in domains
        needs_campaign = "campaign" in domains or "encounter" in domains
        if not needs_activity and not needs_campaign:
            return None, None

        packs = load_event_manifests(self._project_root / "content" / "events")
        content_catalog = ContentCatalog(packs)
        if needs_campaign:
            validate_mumu12_war_archives_profiles(content_catalog)
        activities = None
        if needs_activity:
            activities = ActivityCatalog(content_catalog.packs)
            validate_mumu12_activity_profiles(activities)
        if not needs_campaign:
            return activities, None

        runtime_profiles = compile_campaign_runtime_profile_registry(
            self._project_root / "content" / "campaign-runtime-profiles.json"
        )
        validate_mumu12_campaign_runtime_profiles(content_catalog.stages, runtime_profiles)
        sessions = self._sessions_factory(self._project_root, content_catalog, runtime_profiles)
        if not isinstance(sessions, HardCampaignSessionSource):
            message = "sessions_factory must return a HardCampaignSessionSource"
            raise TypeError(message)
        return activities, sessions

    def _build_domain_factories(  # ruff:ignore[complex-structure, too-many-return-statements] - 直接分支比第二套领域注册表更清楚。
        self,
        domain: str,
        *,
        config: AzurLaneConfig,
        device: Device,
        activities: ActivityCatalog | None,
        sessions: HardCampaignSessionSource | None,
    ) -> Mapping[str, TaskFactory]:
        if domain == "maintenance":
            return build_maintenance_factories(
                build_mumu12_maintenance_services(
                    config,
                    device,
                    uncensored_toolkit_root=self._project_root / "toolkit" / "AzurLaneUncensored",
                )
            )
        if domain == "facility":
            return build_facility_factories(build_mumu12_facility_workflows(config, device))
        if domain == "composite":
            return build_composite_factories(build_mumu12_composite_workflows(config, device))
        if domain == "market":
            return build_market_factories(build_mumu12_market_workflows(config, device))
        if domain == "opsi":
            return build_opsi_factories(build_mumu12_opsi_workflows(config, device))
        if domain == "activity":
            if activities is None:
                message = "activity composition requires an activity catalog"
                raise RuntimeError(message)
            return build_activity_factories(
                ActivityFactoryDependencies(
                    workflows=build_mumu12_activity_workflows(config, device),
                    catalog=activities,
                )
            )
        if sessions is None:
            message = f"{domain} composition requires campaign content"
            raise RuntimeError(message)
        if domain == "campaign":
            return build_campaign_factories(build_mumu12_campaign_dependencies(config, device, sessions))
        if domain == "encounter":
            hard_campaign = Mumu12HardCampaignPort(config, device, sessions)
            return build_encounter_factories(
                build_mumu12_encounter_workflows(
                    config,
                    device,
                    hard_campaign=hard_campaign,
                )
            )
        message = f"unknown task domain: {domain}"
        raise RuntimeError(message)

    def _content_revisions(self, task_ids: tuple[str, ...]) -> Mapping[str, str]:
        revisions = dict.fromkeys(task_ids, _CONTENTLESS_REVISION)
        event_tasks = _EVENT_CONTENT_TASKS.intersection(task_ids)
        if event_tasks:
            event_revision = self._event_revision.current()
            revisions.update(dict.fromkeys(event_tasks, event_revision))
        campaign_tasks = _CAMPAIGN_CONTENT_TASKS.intersection(task_ids)
        if campaign_tasks:
            campaign_revision = self._campaign_revision.current()
            revisions.update(dict.fromkeys(campaign_tasks, campaign_revision))
        return revisions


def run_default_command(
    command: str = "alas",
    *,
    project_root: Path | None = None,
    stop_signal: ExternalRequestSignal | None = None,
) -> CommandOutcome:
    """构造一次个人运行时并执行 scheduler 或单个调试命令。"""
    root = _require_project_root(
        PROJECT_ROOT if project_root is None else project_root,
    )
    screenshots: ScreenshotHistory | None = None
    notification: NotificationConfig = DisabledNotificationConfig()
    try:
        builder = PersonalRuntimeBuilder(root, command)
        config_path = ensure_personal_configuration(root)
        document = JsonConfigurationDocumentSource(config_path).load()
        clock = SystemLoopClock()
        compiled, registry, repository, screenshots = builder.build(document, clock=clock)
        notification = compiled.notification
        runner = RuntimeRunner(
            factories=registry,
            settings=compiled.tasks,
            settings_revisions=compiled.task_revisions,
            repository=repository,
            clock=clock,
            observer=lambda task_id, result: _observe_result(
                task_id,
                result,
                root=root,
                command=command,
                screenshots=screenshots,
                notification=notification,
            ),
        )
        abort = AbortToken(
            external_signal=stop_signal,
            external_reason="personal runtime stop requested",
        )
        return runner.run(command, abort=abort)
    except Exception as error:  # ruff:ignore[blind-except] - 唯一进程边界必须返回可序列化结果。
        logger.exception(error)
        bundle_path = _save_error_bundle(
            root=root,
            command=command,
            task_id=None,
            error=error,
            screenshots=screenshots,
        )
        content = f"{type(error).__name__}: {error}"
        if bundle_path is not None:
            content = f"{content}\nError bundle: {bundle_path}"
        _notify(notification, title="Alas process failed", content=content)
        return _failed_outcome(command, error, bundle=bundle_path)
