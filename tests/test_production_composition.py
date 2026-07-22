import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest
import yaml
from config_factory import in_memory_config

import module.bootstrap.production as production_module
import module.config.config as config_module
import module.state.config_repository as state_repository_module
from module.application import (
    AbortRequested,
    AbortToken,
    ExecutionMode,
    Faulted,
    OperatorNotificationKind,
    OperatorNotificationRequest,
    RecoverableFault,
    RescheduleSelf,
    RunMetadata,
    Succeeded,
    TaskId,
    TaskResult,
    WakePolicy,
    WakeTask,
)
from module.application.state_effects import UpsertTaskState
from module.bootstrap.assembly_source import ConfigurationLoadError, JsonConfigurationDocumentSource
from module.bootstrap.configuration_compiler import ConfigurationCompileError, WebConfigurationCompiler
from module.bootstrap.production import (
    PersonalRuntimeBuilder,
    PersonalRuntimeConfig,
    PersonalSchedulerResources,
    SystemLoopClock,
    ensure_personal_configuration,
    validate_personal_configuration,
)
from module.content.manifest import load_default_event_manifests
from module.device.device import Device
from module.diagnostics import ScreenshotHistory
from module.equipment.equipment_code import EquipmentCodeHandler
from module.exception import GameStuckError
from module.notify.configuration import SmtpNotificationConfig, SmtpTransport
from module.runtime.factories import ConfiguredTaskFactory, TaskBinding, validate_task_bindings
from module.runtime.runner import CommandStatus, RuntimeRunner
from module.state.config_repository import ConfigStateError, ConfigStateRepository
from module.task_registry import TASK_SPECS

if TYPE_CHECKING:
    from collections.abc import Callable

    from module.config.config import AzurLaneConfig
    from module.config.config_generated import ConfigValue
    from module.content.campaign_session import CampaignRunVariant, CampaignSession
    from module.content.campaign_session_source import CampaignStageSelection
    from module.content.models import EventPack, StageRef
    from module.device.runtime import DeviceRuntime
    from module.runtime.factories import TaskBuildContext


class _Sessions:
    @staticmethod
    def resolve_hard_stage_ref(stage_id: str) -> StageRef:
        del stage_id
        message = "composition must not resolve a hard stage before task execution"
        raise AssertionError(message)

    @staticmethod
    def select(
        ref: StageRef,
        *,
        remaining_runs: int,
        preferred_ref: StageRef | None = None,
    ) -> CampaignStageSelection:
        del ref, remaining_runs, preferred_ref
        message = "composition must not select a stage before task construction"
        raise AssertionError(message)

    @staticmethod
    def resolve(ref: StageRef, variant: CampaignRunVariant) -> CampaignSession:
        del ref, variant
        message = "composition must not resolve a stage before task construction"
        raise AssertionError(message)


class _Revision:
    def __init__(self, value: str) -> None:
        self.value = value

    def current(self) -> str:
        return self.value


class _ForbiddenRevision:
    @staticmethod
    def current() -> str:
        pytest.fail("benchmark composition must not calculate gameplay content revisions")


class _SuccessfulTask:
    @staticmethod
    def run(_context: object) -> TaskResult:
        return TaskResult(Succeeded())


class _CountingFactory:
    def __init__(self) -> None:
        self.builds = 0

    def build(self, _context: TaskBuildContext) -> _SuccessfulTask:
        self.builds += 1
        return _SuccessfulTask()


def _template() -> dict[str, object]:
    return cast(
        "dict[str, object]",
        json.loads(Path("config/template.json").read_text(encoding="utf-8")),
    )


def _runtime_repository(path: Path, document: dict[str, object]) -> ConfigStateRepository:
    return ConfigStateRepository(
        SystemLoopClock(),
        config_path=path,
        initial_document=document,
        initial_runtime_document=WebConfigurationCompiler().parse_runtime_document(document),
    )


def _personal_config_factory(
    document: dict[str, object],
) -> tuple[Callable[[ConfigStateRepository], AzurLaneConfig], list[AzurLaneConfig]]:
    created: list[AzurLaneConfig] = []

    def load(_repository: ConfigStateRepository) -> AzurLaneConfig:
        config = in_memory_config("alas", document)
        created.append(config)
        return config

    return load, created


def _test_device(config: AzurLaneConfig) -> Device:
    device = object.__new__(Device)
    device.config = config
    return device


@pytest.fixture(scope="module")
def production_default_event_packs() -> tuple[EventPack, ...]:
    """默认 manifests 不可变，同一模块只需解析和校验一次。"""
    return load_default_event_manifests()


def _reuse_production_default_event_packs(
    monkeypatch: pytest.MonkeyPatch,
    packs: tuple[EventPack, ...],
) -> None:
    expected_root = Path("content/events").resolve()

    def load(path: Path) -> tuple[EventPack, ...]:
        assert path.resolve() == expected_root
        return packs

    monkeypatch.setattr(production_module, "load_event_manifests", load)


def test_equipment_codes_accumulate_through_one_owner_in_the_same_process(tmp_path: Path) -> None:
    document = _template()
    path = tmp_path / "alas.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    config = PersonalRuntimeConfig(_runtime_repository(path, document))
    config.init_task("GemsFarming")
    handler = object.__new__(EquipmentCodeHandler)
    handler.config = config

    handler.set_code("DD", "code-dd")
    handler.set_code("CV", "code-cv")

    live_codes = yaml.safe_load(config.EquipmentCode_Config)
    stored = cast("dict[str, object]", json.loads(path.read_text(encoding="utf-8")))
    gems = cast("dict[str, object]", stored["GemsFarming"])
    equipment = cast("dict[str, object]", gems["EquipmentCode"])
    stored_codes = yaml.safe_load(cast("str", equipment["Config"]))
    assert live_codes["DD"] == "code-dd"
    assert live_codes["CV"] == "code-cv"
    assert stored_codes == live_codes


def _builder(
    *,
    command: str = "alas",
    config_factory: Callable[[ConfigStateRepository], AzurLaneConfig],
    device_factory: Callable[[AzurLaneConfig], Device] = _test_device,
) -> PersonalRuntimeBuilder:
    return PersonalRuntimeBuilder(
        Path(),
        command,
        config_factory=config_factory,
        device_factory=device_factory,
        sessions_factory=lambda _root, _catalog, _profiles: _Sessions(),
        event_revision=_Revision("event-test"),
        campaign_revision=_Revision("campaign-test"),
    )


def test_scheduler_builder_builds_every_domain_from_personal_configuration(
    monkeypatch: pytest.MonkeyPatch,
    production_default_event_packs: tuple[EventPack, ...],
) -> None:
    _reuse_production_default_event_packs(monkeypatch, production_default_event_packs)
    document = _template()
    config_factory, configs = _personal_config_factory(document)

    compiled, bindings, _repository, screenshots, device = _builder(config_factory=config_factory).build(
        document,
        clock=SystemLoopClock(),
    )

    assert bindings[TaskId("event_story")].content_revision == "event-test"
    assert bindings[TaskId("main")].content_revision == "campaign-test"
    assert bindings[TaskId("benchmark")].content_revision == "builtin-content-v1"
    assert isinstance(screenshots, ScreenshotHistory)
    assert device.config is configs[0]
    assert configs[0].config_name == "alas"
    assert configs[0].Emulator_Serial == compiled.device_serial


def test_direct_benchmark_skips_campaign_content_and_builds_its_factory_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = _template()
    config_factory, _configs = _personal_config_factory(document)
    factory = _CountingFactory()

    def reject_content(*_args: object, **_kwargs: object) -> None:
        pytest.fail("benchmark composition must not load or validate campaign content")

    monkeypatch.setattr(production_module, "load_event_manifests", reject_content)
    monkeypatch.setattr(production_module, "compile_campaign_runtime_profile_registry", reject_content)
    monkeypatch.setattr(production_module, "validate_mumu12_campaign_runtime_profiles", reject_content)
    monkeypatch.setattr(
        production_module,
        "build_maintenance_factories",
        lambda _services: {"benchmark": factory},
    )

    _compiled, bindings, repository, _screenshots, _device = PersonalRuntimeBuilder(
        Path(),
        "benchmark",
        config_factory=config_factory,
        device_factory=_test_device,
        event_revision=_ForbiddenRevision(),
        campaign_revision=_ForbiddenRevision(),
    ).build(document, clock=SystemLoopClock())
    runner = RuntimeRunner(
        bindings=bindings,
        repository=repository,
        clock=SystemLoopClock(),
    )

    outcome = runner.run("benchmark")

    assert outcome.status is CommandStatus.FINISHED
    assert outcome.last_task == "benchmark"
    assert tuple(bindings) == (TaskId("benchmark"),)
    assert factory.builds == 1


@pytest.mark.parametrize(
    ("validator_name", "message"),
    [
        ("validate_mumu12_activity_profiles", "invalid activity profile"),
        ("validate_mumu12_war_archives_profiles", "invalid war archives profile"),
        ("validate_mumu12_campaign_runtime_profiles", "invalid campaign profile"),
    ],
)
def test_content_validation_precedes_device_construction(
    monkeypatch: pytest.MonkeyPatch,
    production_default_event_packs: tuple[EventPack, ...],
    validator_name: str,
    message: str,
) -> None:
    _reuse_production_default_event_packs(monkeypatch, production_default_event_packs)
    document = _template()
    config_factory, _configs = _personal_config_factory(document)
    created: list[AzurLaneConfig] = []

    def reject_profiles(*_args: object) -> None:
        raise ValueError(message)

    monkeypatch.setattr(production_module, validator_name, reject_profiles)

    with pytest.raises(ValueError, match=message):
        _builder(
            config_factory=config_factory,
            device_factory=lambda config: created.append(config) or _test_device(config),
        ).build(document, clock=SystemLoopClock())

    assert created == []


def test_complete_configuration_builds_the_exact_task_catalog(
    monkeypatch: pytest.MonkeyPatch,
    production_default_event_packs: tuple[EventPack, ...],
) -> None:
    _reuse_production_default_event_packs(monkeypatch, production_default_event_packs)
    document = _template()
    config_factory, _configs = _personal_config_factory(document)
    builder = PersonalRuntimeBuilder(
        Path(),
        "alas",
        config_factory=config_factory,
        device_factory=_test_device,
        event_revision=_Revision("event-test"),
        campaign_revision=_Revision("campaign-test"),
    )
    _compiled, bindings, _repository, _screenshots, _device = builder.build(document, clock=SystemLoopClock())

    validate_task_bindings(bindings)
    assert tuple(task_id.value for task_id in bindings) == tuple(TASK_SPECS)


def test_fault_observer_saves_diagnostics_and_sends_all_production_notifications(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error = RuntimeError("device disconnected")
    screenshots = ScreenshotHistory(max_frames=1)
    saved: list[tuple[Path, str, str | None, BaseException, ScreenshotHistory]] = []
    sent: list[tuple[SmtpNotificationConfig, str, str]] = []
    smtp = SmtpNotificationConfig(
        host="smtp.example.com",
        user="sender@example.com",
        password=tmp_path.name,
        recipients=("operator@example.com",),
        port=587,
        transport=SmtpTransport.STARTTLS,
    )

    def save_error_bundle(
        *,
        root: Path,
        command: str,
        task_id: str | None,
        error: BaseException,
        screenshots: ScreenshotHistory,
    ) -> str:
        saved.append((root, command, task_id, error, screenshots))
        return "log/error/bundle"

    def send_notification(
        config: SmtpNotificationConfig,
        *,
        title: str,
        content: str,
    ) -> bool:
        sent.append((config, title, content))
        return True

    monkeypatch.setattr(production_module, "_save_error_bundle", save_error_bundle)
    monkeypatch.setattr(production_module, "send_notification", send_notification)

    bundle = production_module._observe_result(  # ruff:ignore[private-member-access] - 验证生产结果观察器的完整编排。
        TaskId("main"),
        TaskResult(
            outcome=Faulted(error),
            notifications=(
                OperatorNotificationRequest(
                    OperatorNotificationKind.CAMPAIGN_RUN_COUNT_LIMIT,
                    resource="campaign_main/12-4",
                ),
            ),
        ),
        root=tmp_path,
        command="alas",
        screenshots=screenshots,
        notification=smtp,
    )

    assert bundle == "log/error/bundle"
    assert saved == [(tmp_path, "alas", "main", error, screenshots)]
    assert sent == [
        (
            smtp,
            "Alas crashed",
            "<main> RuntimeError: device disconnected\nError bundle: log/error/bundle",
        ),
        (
            smtp,
            "Alas campaign finished",
            "<main> campaign_main/12-4 reached run count limit",
        ),
    ]


def test_recoverable_fault_observer_saves_diagnostics_without_crash_notification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error = GameStuckError("stuck")
    screenshots = ScreenshotHistory(max_frames=1)
    saved: list[BaseException] = []
    sent: list[tuple[str, str]] = []
    retry_at = datetime(2026, 7, 22, 4, 0, 10, tzinfo=UTC)
    smtp = SmtpNotificationConfig(
        host="smtp.example.com",
        user="sender@example.com",
        password=tmp_path.name,
        recipients=("operator@example.com",),
        port=587,
        transport=SmtpTransport.STARTTLS,
    )

    def save_error_bundle(**kwargs: object) -> str:
        saved.append(cast("BaseException", kwargs["error"]))
        return "log/error/recoverable"

    def send_notification(
        _config: SmtpNotificationConfig,
        *,
        title: str,
        content: str,
    ) -> bool:
        sent.append((title, content))
        return True

    monkeypatch.setattr(production_module, "_save_error_bundle", save_error_bundle)
    monkeypatch.setattr(production_module, "send_notification", send_notification)

    bundle = production_module._observe_result(  # ruff:ignore[private-member-access] - 验证恢复诊断不会误报进程崩溃。
        TaskId("research"),
        TaskResult(
            RecoverableFault(error),
            effects=(
                RescheduleSelf(retry_at),
                WakeTask(TaskId("restart"), retry_at - timedelta(seconds=10), WakePolicy.FORCE_ENABLE),
            ),
        ),
        root=tmp_path,
        command="alas",
        screenshots=screenshots,
        notification=smtp,
    )

    assert bundle == "log/error/recoverable"
    assert saved == [error]
    assert sent == []


def test_personal_scheduler_resources_release_assets_and_the_same_device(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str | None]] = []

    class _Runtime:
        @staticmethod
        def release_serial() -> None:
            calls.append(("device", None))

    def release_resources(next_task: str = "") -> None:
        calls.append(("assets", next_task or None))

    monkeypatch.setattr(production_module, "release_resources", release_resources)
    device = object.__new__(Device)
    device._runtime = cast("DeviceRuntime", _Runtime())  # ruff:ignore[private-member-access] - 注入真实 Device runtime owner。
    lifecycle = PersonalSchedulerResources(device)

    lifecycle.before_task(TaskId("research"))
    lifecycle.before_wait()

    assert calls == [
        ("assets", "research"),
        ("assets", None),
        ("device", None),
    ]


def test_personal_scheduler_resources_preserve_both_idle_cleanup_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    asset_error = ValueError("asset cleanup failed")
    device_error = OSError("device cleanup failed")

    class _Runtime:
        @staticmethod
        def release_serial() -> None:
            calls.append("device")
            raise device_error

    def release_resources() -> None:
        calls.append("assets")
        raise asset_error

    monkeypatch.setattr(production_module, "release_resources", release_resources)
    device = object.__new__(Device)
    device._runtime = cast("DeviceRuntime", _Runtime())  # ruff:ignore[private-member-access] - 注入真实 Device runtime owner。
    resources = PersonalSchedulerResources(device)

    with pytest.raises(ExceptionGroup) as raised:
        resources.before_wait()

    assert calls == ["assets", "device"]
    assert raised.value.exceptions == (asset_error, device_error)


def test_personal_configuration_validation_is_pure_and_skips_runtime_composition(
    monkeypatch: pytest.MonkeyPatch,
    production_default_event_packs: tuple[EventPack, ...],
) -> None:
    _reuse_production_default_event_packs(monkeypatch, production_default_event_packs)
    document = _template()

    def reject_runtime_composition(*_args: object, **_kwargs: object) -> None:
        pytest.fail("configuration validation must not compose runtime objects")

    monkeypatch.setattr(PersonalRuntimeBuilder, "build", reject_runtime_composition)
    monkeypatch.setattr(PersonalRuntimeConfig, "__init__", reject_runtime_composition)
    monkeypatch.setattr(ConfigStateRepository, "__init__", reject_runtime_composition)
    monkeypatch.setattr(Device, "__init__", reject_runtime_composition)
    monkeypatch.setattr(TaskBinding, "build", reject_runtime_composition)
    monkeypatch.setattr(ConfiguredTaskFactory, "build", reject_runtime_composition)
    monkeypatch.setattr(production_module, "bind_tasks", reject_runtime_composition)
    for factory_builder in (
        "build_activity_factories",
        "build_campaign_factories",
        "build_composite_factories",
        "build_encounter_factories",
        "build_facility_factories",
        "build_market_factories",
        "build_opsi_factories",
        "build_maintenance_factories",
    ):
        monkeypatch.setattr(production_module, factory_builder, reject_runtime_composition)
    for adapter_builder in (
        "build_mumu12_activity_workflows",
        "build_mumu12_campaign_dependencies",
        "build_mumu12_composite_workflows",
        "build_mumu12_encounter_workflows",
        "build_mumu12_facility_workflows",
        "build_mumu12_maintenance_services",
        "build_mumu12_market_workflows",
        "build_mumu12_opsi_workflows",
    ):
        monkeypatch.setattr(production_module, adapter_builder, reject_runtime_composition)
    monkeypatch.setattr(
        production_module,
        "atomic_write",
        lambda *_args, **_kwargs: pytest.fail("configuration validation must not write files"),
    )

    compiled = validate_personal_configuration(document, project_root=Path())

    assert set(compiled.tasks) == set(TASK_SPECS)


def test_personal_configuration_validation_rejects_unknown_hard_stage(
    monkeypatch: pytest.MonkeyPatch,
    production_default_event_packs: tuple[EventPack, ...],
) -> None:
    _reuse_production_default_event_packs(monkeypatch, production_default_event_packs)
    document = _template()
    hard = cast("dict[str, object]", document["Hard"])
    settings = cast("dict[str, object]", hard["Hard"])
    settings["HardStage"] = "missing-hard-stage"

    with pytest.raises(ConfigurationCompileError, match=r"\$\.tasks\.hard\.stage.*missing-hard-stage"):
        validate_personal_configuration(document, project_root=Path())


def test_personal_configuration_validation_wraps_unknown_content_reference(
    monkeypatch: pytest.MonkeyPatch,
    production_default_event_packs: tuple[EventPack, ...],
) -> None:
    _reuse_production_default_event_packs(monkeypatch, production_default_event_packs)
    document = _template()
    event = cast("dict[str, object]", document["Event"])
    campaign = cast("dict[str, object]", event["Campaign"])
    campaign["Name"] = "missing-stage"

    with pytest.raises(ConfigurationCompileError, match=r"\$\.tasks\.event\.stage_refs.*missing-stage"):
        validate_personal_configuration(document, project_root=Path())


def test_json_configuration_source_reads_only_its_bound_path(tmp_path: Path) -> None:
    path = tmp_path / "alas.json"
    path.write_text('{"version": 1}', encoding="utf-8")
    source = JsonConfigurationDocumentSource(path)

    assert source.load() == {"version": 1}

    path.write_text('{"version": 1, "version": 2}', encoding="utf-8")
    with pytest.raises(ConfigurationLoadError, match="duplicate configuration field: version"):
        source.load()


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_json_configuration_source_rejects_non_finite_numbers(
    constant: str,
    tmp_path: Path,
) -> None:
    path = tmp_path / "alas.json"
    path.write_text(f'{{"value": {constant}}}', encoding="utf-8")
    source = JsonConfigurationDocumentSource(path)

    with pytest.raises(ConfigurationLoadError, match="non-finite JSON number"):
        source.load()


def test_personal_runtime_config_reads_only_its_bound_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    path = tmp_path / "alas.json"
    original = Path("config/template.json").read_bytes()
    path.write_bytes(original)
    document = _template()

    def reject_read(*_args: object, **_kwargs: object) -> None:
        message = "generic config reader must not run"
        raise AssertionError(message)

    monkeypatch.setattr(config_module, "read_config_file", reject_read)

    config = PersonalRuntimeConfig(_runtime_repository(path, document))

    assert config.Emulator_Serial == "127.0.0.1:16384"
    assert path.read_bytes() == original


def test_personal_runtime_temporary_bound_field_never_persists(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    document = _template()
    main = cast("dict[str, object]", document["Main"])
    campaign = cast("dict[str, object]", main["Campaign"])
    campaign["UseAutoSearch"] = False
    path = tmp_path / "alas.json"
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    config = PersonalRuntimeConfig(_runtime_repository(path, document))
    config.init_task("Main")
    original = path.read_bytes()

    assert config.bound["Campaign_UseAutoSearch"] == "Main.Campaign.UseAutoSearch"
    monkeypatch.setattr(
        state_repository_module,
        "atomic_write",
        lambda *_args: pytest.fail("temporary overlay must not write alas.json"),
    )

    with config.temporary(Campaign_UseAutoSearch=True):
        assert config.Campaign_UseAutoSearch is True
        assert config.modified == {}
        assert path.read_bytes() == original

    assert config.Campaign_UseAutoSearch is False
    assert config.modified == {}
    assert path.read_bytes() == original


def test_personal_runtime_config_rejects_invalid_option_without_rewriting(tmp_path: Path) -> None:
    document = _template()
    path = tmp_path / "alas.json"
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    original = path.read_bytes()
    config = PersonalRuntimeConfig(_runtime_repository(path, document))
    config.modified["Research.Research.UseCube"] = "removed-option"

    with pytest.raises(ConfigStateError, match=r"Research\.Research\.UseCube must be one of"):
        config.save()

    assert path.read_bytes() == original


def test_personal_runtime_config_saves_datetime_with_current_json_format(tmp_path: Path) -> None:
    path = tmp_path / "alas.json"
    path.write_bytes(Path("config/template.json").read_bytes())
    document = _template()
    config = PersonalRuntimeConfig(_runtime_repository(path, document))
    next_run = datetime(2026, 7, 16, 9, 30, 45)
    config.modified["Restart.Scheduler.NextRun"] = next_run

    assert config.save() is True

    stored = cast("dict[str, object]", json.loads(path.read_text(encoding="utf-8")))
    restart = cast("dict[str, object]", stored["Restart"])
    scheduler = cast("dict[str, object]", restart["Scheduler"])
    assert scheduler["NextRun"] == "2026-07-16 09:30:45"


def test_personal_runtime_config_refreshes_shared_owner_before_binding_next_task(tmp_path: Path) -> None:
    path = tmp_path / "alas.json"
    path.write_bytes(Path("config/template.json").read_bytes())
    document = _template()
    repository = _runtime_repository(path, document)
    config = PersonalRuntimeConfig(repository)

    repository.apply_runtime_updates({"Research.Scheduler.Enable": False})
    config.bind("Research")

    assert config.Scheduler_Enable is False


def test_personal_runtime_config_save_preserves_state_committed_after_its_last_snapshot(tmp_path: Path) -> None:
    path = tmp_path / "alas.json"
    path.write_bytes(Path("config/template.json").read_bytes())
    document = _template()
    repository = _runtime_repository(path, document)
    config = PersonalRuntimeConfig(repository)

    repository.begin_run(
        TaskId("main"),
        ExecutionMode.SCHEDULED_JOB,
        RunMetadata(settings_revision=1, content_revision="content-test"),
    )
    repository.finalize_run(
        TaskResult(
            outcome=Succeeded(),
            state_effects=(UpsertTaskState("main", "progress", 1, {"wave": 3}),),
        )
    )
    config.modified["Research.Research.UseCube"] = "always_use"
    assert config.save() is True

    stored = cast("dict[str, object]", json.loads(path.read_text(encoding="utf-8")))
    main = cast("dict[str, object]", stored["Main"])
    storage_group = cast("dict[str, object]", main["Storage"])
    storage = cast("dict[str, object]", storage_group["Storage"])
    research = cast("dict[str, object]", stored["Research"])
    research_settings = cast("dict[str, object]", research["Research"])
    assert cast("dict[str, object]", storage["progress"])["payload"] == {"wave": 3}
    assert research_settings["UseCube"] == "always_use"


def test_personal_runtime_config_rejects_unknown_object_without_rewriting(tmp_path: Path) -> None:
    path = tmp_path / "alas.json"
    path.write_bytes(Path("config/template.json").read_bytes())
    original = path.read_bytes()
    document = _template()
    config = PersonalRuntimeConfig(_runtime_repository(path, document))
    invalid_value = cast("ConfigValue", object())
    config.modified["Restart.Scheduler.NextRun"] = invalid_value

    with pytest.raises(ConfigStateError, match="cannot be persisted as JSON"):
        config.save()

    assert path.read_bytes() == original
    assert config.modified == {"Restart.Scheduler.NextRun": invalid_value}


def test_multi_set_restores_auto_update_after_shared_owner_write_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "alas.json"
    path.write_bytes(Path("config/template.json").read_bytes())
    document = _template()
    config = PersonalRuntimeConfig(_runtime_repository(path, document))
    config.bind("Main")

    def fail_write(_target: Path, _content: str) -> None:
        message = "disk full"
        raise OSError(message)

    monkeypatch.setattr(state_repository_module, "atomic_write", fail_write)

    with pytest.raises(OSError, match="disk full"):
        config.set_record(Emotion_Fleet1Value=100)

    assert config.auto_update is True
    assert config.modified["Main.Emotion.Fleet1Value"] == 100
    assert isinstance(config.modified["Main.Emotion.Fleet1Record"], datetime)


def test_system_loop_clock_wait_is_cancellation_aware() -> None:
    abort = AbortToken()
    abort.request("test stop")

    with pytest.raises(AbortRequested, match="test stop"):
        SystemLoopClock.sleep(30, abort)


def test_personal_configuration_is_created_once_from_template(tmp_path: Path) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "content" / "events").mkdir(parents=True)
    (tmp_path / "module").mkdir()
    template = tmp_path / "config" / "template.json"
    template.write_text('{"version": 1}', encoding="utf-8")

    path = ensure_personal_configuration(tmp_path)
    template.write_text('{"version": 2}', encoding="utf-8")
    same_path = ensure_personal_configuration(tmp_path)

    assert same_path == path
    assert path.read_text(encoding="utf-8") == '{"version": 1}'
