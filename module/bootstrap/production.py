import time
from datetime import UTC, datetime
from pathlib import Path
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
    GameRuntimeBundle,
    JsonConfigurationDocumentSource,
)
from module.bootstrap.configuration_compiler import (
    CompiledConfiguration,
    ConfigurationCompileError,
    ConfigurationDocument,
    WebConfigurationCompiler,
)
from module.bootstrap.revisions import RevisionTree, SourceTreeRevisionSource
from module.bootstrap.task_factories import GameTaskDependencies, build_game_task_registry
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
from module.gameplay.activity_factories import ActivityFactoryDependencies
from module.gameplay.campaign_factories import HardCampaignSessionSource
from module.logger import get_log_file, logger
from module.notify.configuration import DisabledNotificationConfig, NotificationConfig, SmtpNotificationConfig
from module.notify.direct import send_notification
from module.runtime.errors import RuntimeCompositionError
from module.runtime.runner import CommandOutcome, CommandStatus, RuntimeRunner
from module.runtime.settings import TaskSettingsDocument
from module.state.config_repository import ConfigRepositoryClock, ConfigStateRepository
from module.task_registry import get_task_definition

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from module.application import ExternalRequestSignal
    from module.content.runtime_profile import CampaignRuntimeProfileRegistry
    from module.interaction import CancellationSignal


_CONTENT_SUFFIXES = frozenset({".json", ".yaml", ".yml"})
_PYTHON_SUFFIXES = frozenset({".py"})


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


def _settings_revision(source_revision: str) -> int:
    """把配置摘要稳定映射为 checkpoint 可比较的正整数。"""
    prefix = "sha256:"
    if not source_revision.startswith(prefix):
        message = "source_revision must be a sha256 revision"
        raise ValueError(message)
    return int(source_revision.removeprefix(prefix)[:15], 16) + 1


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
        Path(__file__).resolve().parents[2] if project_root is None else project_root,
    )
    try:
        compiled, bundle, _repository = Mumu12GameRuntimeBundleSource(
            root,
            config_factory=_ConfigurationValidationConfig,
            device_factory=_ConfigurationValidationDevice,
        ).build(document, clock=SystemLoopClock())
        registry = build_game_task_registry(
            bundle.tasks,
            content_revision=bundle.content_revision,
        )
        settings = TaskSettingsDocument.from_payload(
            compiled.payload,
            revision=_settings_revision(compiled.source_revision),
            updated_at=datetime.now(tz=UTC),
            task_ids=registry.task_ids,
        )
        registry.validate_settings(settings)
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
    except Exception as bundle_error:  # noqa: BLE001 - 诊断旁路不能改写原始错误。
        logger.exception(bundle_error)
        return None
    logger.error(f"Error bundle saved to {bundle}")
    return str(bundle)


def _observe_result(  # noqa: PLR0913 - 结果边界需要运行命令、诊断和通知上下文。
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
        cancellation: CancellationSignal,
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


class Mumu12GameRuntimeBundleSource:
    """把当前个人配置组装成唯一的 MuMu12 游戏依赖图。"""

    __slots__ = (
        "_config_factory",
        "_content_revision",
        "_device_factory",
        "_project_root",
        "_sessions_factory",
    )

    def __init__(
        self,
        project_root: Path,
        *,
        config_factory: Callable[[ConfigStateRepository], AzurLaneConfig] = PersonalRuntimeConfig,
        device_factory: Callable[[AzurLaneConfig], Device] = Device,
        sessions_factory: Callable[
            [Path, ContentCatalog, CampaignRuntimeProfileRegistry],
            HardCampaignSessionSource,
        ] = _default_sessions,
        content_revision: RevisionSource | None = None,
    ) -> None:
        root = _require_project_root(project_root)
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
        default_content_revision = SourceTreeRevisionSource(
            "content-v1",
            (
                RevisionTree(root / "content", _CONTENT_SUFFIXES),
                RevisionTree(root / "module" / "content", _PYTHON_SUFFIXES),
            ),
        )
        selected_content = default_content_revision if content_revision is None else content_revision
        if isinstance(selected_content, type) or not callable(getattr(selected_content, "current", None)):
            message = "content_revision must implement current()"
            raise TypeError(message)
        self._project_root = root
        self._config_factory = config_factory
        self._device_factory = device_factory
        self._sessions_factory = sessions_factory
        self._content_revision = selected_content

    def build(
        self,
        document: ConfigurationDocument,
        *,
        clock: ConfigRepositoryClock,
    ) -> tuple[CompiledConfiguration, GameRuntimeBundle, ConfigStateRepository]:
        """从同一候选文档编译并绑定 runtime，禁止 settings 与驱动配置错配。"""

        configuration, runtime_document = WebConfigurationCompiler().compile_runtime_document(document)
        repository = ConfigStateRepository(
            clock,
            config_path=self._project_root / "config" / "alas.json",
            initial_document=document,
            initial_runtime_document=runtime_document,
        )
        config = self._config_factory(repository)
        if not isinstance(config, AzurLaneConfig):
            message = "config_factory must return an AzurLaneConfig"
            raise TypeError(message)
        return configuration, self._build_from_config(config, configuration), repository

    def _build_from_config(
        self,
        config: AzurLaneConfig,
        configuration: CompiledConfiguration,
    ) -> GameRuntimeBundle:
        if config.Emulator_Serial != configuration.device_serial:
            message = "compiled device serial does not match the bound configuration"
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
            screenshots=device.error_screenshots,
            content_revision=self._content_revision.current(),
        )


def run_default_command(
    command: str = "alas",
    *,
    project_root: Path | None = None,
    stop_signal: ExternalRequestSignal | None = None,
) -> CommandOutcome:
    """构造一次个人运行时并执行 scheduler 或单个调试命令。"""
    root = _require_project_root(
        Path(__file__).resolve().parents[2] if project_root is None else project_root,
    )
    config_path = ensure_personal_configuration(root)
    configuration_source = JsonConfigurationDocumentSource(config_path)
    screenshots: ScreenshotHistory | None = None
    notification: NotificationConfig = DisabledNotificationConfig()
    try:
        document = configuration_source.load()
        _validate_command(command)
        clock = SystemLoopClock()
        compiled, bundle, repository = Mumu12GameRuntimeBundleSource(root).build(document, clock=clock)
        notification = compiled.notification
        screenshots = bundle.screenshots
        registry = build_game_task_registry(
            bundle.tasks,
            content_revision=bundle.content_revision,
        )
        settings = TaskSettingsDocument.from_payload(
            compiled.payload,
            revision=_settings_revision(compiled.source_revision),
            updated_at=datetime.now(tz=UTC),
            task_ids=registry.task_ids,
        )
        runner = RuntimeRunner(
            factories=registry,
            settings=settings,
            repository=repository,
            clock=clock,
            observer=lambda task_id, result: _observe_result(
                task_id,
                result,
                root=root,
                command=command,
                screenshots=bundle.screenshots,
                notification=notification,
            ),
        )
        abort = AbortToken(
            external_signal=stop_signal,
            external_reason="personal runtime stop requested",
        )
        return runner.run(command, abort=abort)
    except SystemExit as error:
        if error.code in {None, 0}:
            return CommandOutcome(
                command=command,
                status=CommandStatus.FINISHED,
                finished_at=datetime.now(tz=UTC),
            )
        logger.exception(error)
        bundle_path = _save_error_bundle(
            root=root,
            command=command,
            task_id=None,
            error=error,
            screenshots=screenshots,
        )
        _notify(notification, title="Alas process failed", content=f"{type(error).__name__}: {error}")
        return _failed_outcome(command, error, bundle=bundle_path)
    except Exception as error:  # noqa: BLE001 - 唯一进程边界必须返回可序列化结果。
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
