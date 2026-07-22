import json
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest
import yaml
from config_factory import in_memory_config

import module.bootstrap.production as production_module
import module.state.config_repository as state_repository_module
from module.application import (
    ExecutionMode,
    Faulted,
    OperatorNotificationKind,
    OperatorNotificationRequest,
    RunMetadata,
    Succeeded,
    TaskId,
    TaskResult,
)
from module.application.state_effects import UpsertTaskState
from module.bootstrap.configuration_compiler import WebConfigurationCompiler
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
from module.notify.configuration import SmtpNotificationConfig, SmtpTransport
from module.runtime.runner import CommandStatus, RuntimeRunner
from module.state.config_repository import ConfigStateRepository
from module.task_registry import TASK_SPECS

if TYPE_CHECKING:
    from collections.abc import Callable

    from module.config.config import AzurLaneConfig
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


def test_direct_benchmark_runs_without_campaign_content(
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


def test_content_validation_precedes_device_construction(
    monkeypatch: pytest.MonkeyPatch,
    production_default_event_packs: tuple[EventPack, ...],
) -> None:
    _reuse_production_default_event_packs(monkeypatch, production_default_event_packs)
    document = _template()
    config_factory, _configs = _personal_config_factory(document)
    created: list[AzurLaneConfig] = []

    def reject_profiles(*_args: object) -> None:
        message = "invalid campaign profile"
        raise ValueError(message)

    monkeypatch.setattr(production_module, "validate_mumu12_campaign_runtime_profiles", reject_profiles)

    with pytest.raises(ValueError, match="invalid campaign profile"):
        _builder(
            config_factory=config_factory,
            device_factory=lambda config: created.append(config) or _test_device(config),
        ).build(document, clock=SystemLoopClock())

    assert created == []


def test_fault_observer_saves_diagnostics_and_sends_expected_notifications(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task_id = TaskId("main")
    outcome = Faulted(RuntimeError("device disconnected"))
    notifications = (
        OperatorNotificationRequest(
            OperatorNotificationKind.CAMPAIGN_RUN_COUNT_LIMIT,
            resource="campaign_main/12-4",
        ),
    )
    screenshots = ScreenshotHistory(max_frames=1)
    saved: list[tuple[Path, str, str | None, BaseException, ScreenshotHistory]] = []
    sent: list[tuple[str, str]] = []
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
        _config: SmtpNotificationConfig,
        *,
        title: str,
        content: str,
    ) -> bool:
        sent.append((title, content))
        return True

    monkeypatch.setattr(production_module, "_save_error_bundle", save_error_bundle)
    monkeypatch.setattr(production_module, "send_notification", send_notification)

    bundle = production_module._observe_result(  # ruff:ignore[private-member-access] - 验证生产结果观察器的对外行为。
        task_id,
        TaskResult(outcome=outcome, notifications=notifications),
        root=tmp_path,
        command="alas",
        screenshots=screenshots,
        notification=smtp,
    )

    assert bundle == "log/error/bundle"
    assert saved == [(tmp_path, "alas", task_id.value, outcome.error, screenshots)]
    assert sent == [
        ("Alas crashed", "<main> RuntimeError: device disconnected\nError bundle: log/error/bundle"),
        ("Alas campaign finished", "<main> campaign_main/12-4 reached run count limit"),
    ]


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


def test_personal_configuration_validation_does_not_construct_device_or_write(
    monkeypatch: pytest.MonkeyPatch,
    production_default_event_packs: tuple[EventPack, ...],
) -> None:
    _reuse_production_default_event_packs(monkeypatch, production_default_event_packs)
    document = _template()

    def reject_runtime_composition(*_args: object, **_kwargs: object) -> None:
        pytest.fail("configuration validation must not compose runtime objects")

    monkeypatch.setattr(Device, "__init__", reject_runtime_composition)
    monkeypatch.setattr(
        production_module,
        "atomic_write",
        lambda *_args, **_kwargs: pytest.fail("configuration validation must not write files"),
    )

    compiled = validate_personal_configuration(document, project_root=Path())

    assert set(compiled.tasks) == set(TASK_SPECS)


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
