import json
from dataclasses import fields
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest

from module.application import AbortRequested, AbortToken
from module.bootstrap import (
    GameRuntimeBundle,
    InstanceProcessHost,
    Mumu12GameRuntimeBundleSource,
    SystemLoopClock,
    WebConfigurationCompiler,
    build_default_instance_process_host,
    build_game_task_registry,
)
from module.device.device import Device
from module.runtime import ConfigurationPublisher, TaskSettingsDocument
from module.state import SettingsSnapshot, SQLiteStateStore

if TYPE_CHECKING:
    from module.config.config import AzurLaneConfig
    from module.content import CampaignRunVariant, CampaignSession, CampaignStageSelection, StageRef


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


class _Clock:
    @staticmethod
    def now() -> datetime:
        return datetime(2026, 7, 13, tzinfo=UTC)


def _template() -> dict[str, object]:
    return cast(
        "dict[str, object]",
        json.loads(Path("config/template.json").read_text(encoding="utf-8")),
    )


def _template_with_resolvable_campaign_placeholders() -> dict[str, object]:
    document = _template()
    for task_name in ("Event2", "EventSp"):
        task = cast("dict[str, object]", document[task_name])
        campaign = cast("dict[str, object]", task["Campaign"])
        campaign["Event"] = "campaign_main"
        campaign["Name"] = "1-1"
    for task_name in ("EventA", "EventB", "EventC", "EventD"):
        task = cast("dict[str, object]", document[task_name])
        campaign = cast("dict[str, object]", task["Campaign"])
        campaign["Event"] = "campaign_main"
        daily = cast("dict[str, object]", task["EventDaily"])
        daily["StageFilter"] = "1-1"
    archive = cast("dict[str, object]", document["WarArchives"])
    archive_campaign = cast("dict[str, object]", archive["Campaign"])
    archive_campaign["Name"] = "t3"
    return document


def test_bundle_source_builds_every_domain_from_one_bound_snapshot_and_device() -> None:
    document = _template()
    compiled = WebConfigurationCompiler().compile(document)
    created: list[AzurLaneConfig] = []

    def device_factory(config: AzurLaneConfig) -> Device:
        created.append(config)
        return object.__new__(Device)

    source = Mumu12GameRuntimeBundleSource(
        Path(),
        device_factory=device_factory,
        sessions_factory=lambda _root, _catalog, _profiles: _Sessions(),
        content_revision=_Revision("content-test"),
        client_ui_revision=_Revision("client-test"),
    )

    bundle = source.build("snapshot-test", document, compiled)

    assert isinstance(bundle, GameRuntimeBundle)
    assert bundle.content_revision == "content-test"
    assert bundle.client_ui_revision == "client-test"
    assert created[0].config_name == "snapshot-test"
    assert created[0].Emulator_Serial == compiled.device_serial
    assert {field.name for field in fields(bundle.tasks)} == {
        "maintenance",
        "facility",
        "composite",
        "market",
        "encounter",
        "campaign",
        "opsi",
        "activity",
    }


def test_activity_profile_validation_precedes_device_construction(monkeypatch: pytest.MonkeyPatch) -> None:
    document = _template()
    compiled = WebConfigurationCompiler().compile(document)
    created: list[AzurLaneConfig] = []

    def reject_profiles(_catalog: object) -> None:
        message = "invalid activity profile"
        raise ValueError(message)

    monkeypatch.setattr(
        "module.bootstrap.production.validate_mumu12_activity_profiles",
        reject_profiles,
    )
    source = Mumu12GameRuntimeBundleSource(
        Path(),
        device_factory=lambda config: created.append(config) or object.__new__(Device),
        content_revision=_Revision("content-test"),
        client_ui_revision=_Revision("client-test"),
    )

    with pytest.raises(ValueError, match="invalid activity profile"):
        source.build("snapshot-test", document, compiled)

    assert created == []


def test_war_archives_profile_validation_precedes_device_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = _template()
    compiled = WebConfigurationCompiler().compile(document)
    created: list[AzurLaneConfig] = []

    def reject_profiles(_catalog: object) -> None:
        message = "invalid war archives profile"
        raise ValueError(message)

    monkeypatch.setattr(
        "module.bootstrap.production.validate_mumu12_war_archives_profiles",
        reject_profiles,
    )
    source = Mumu12GameRuntimeBundleSource(
        Path(),
        device_factory=lambda config: created.append(config) or object.__new__(Device),
        content_revision=_Revision("content-test"),
        client_ui_revision=_Revision("client-test"),
    )

    with pytest.raises(ValueError, match="invalid war archives profile"):
        source.build("snapshot-test", document, compiled)

    assert created == []


def test_campaign_profile_validation_precedes_device_construction(monkeypatch: pytest.MonkeyPatch) -> None:
    document = _template()
    compiled = WebConfigurationCompiler().compile(document)
    created: list[AzurLaneConfig] = []

    def reject_profiles(_stages: object, _profiles: object) -> None:
        message = "invalid campaign profile"
        raise ValueError(message)

    monkeypatch.setattr(
        "module.bootstrap.production.validate_mumu12_campaign_runtime_profiles",
        reject_profiles,
    )
    source = Mumu12GameRuntimeBundleSource(
        Path(),
        device_factory=lambda config: created.append(config) or object.__new__(Device),
        content_revision=_Revision("content-test"),
        client_ui_revision=_Revision("client-test"),
    )

    with pytest.raises(ValueError, match="invalid campaign profile"):
        source.build("snapshot-test", document, compiled)

    assert created == []


def test_complete_resolvable_configuration_builds_all_real_tasks_against_one_content_snapshot() -> None:
    document = _template_with_resolvable_campaign_placeholders()
    compiled = WebConfigurationCompiler().compile(document)
    source = Mumu12GameRuntimeBundleSource(
        Path(),
        device_factory=lambda _config: object.__new__(Device),
        content_revision=_Revision("content-test"),
        client_ui_revision=_Revision("client-test"),
    )

    bundle = source.build("snapshot-test", document, compiled)
    registry = build_game_task_registry(
        bundle.tasks,
        content_revision=bundle.content_revision,
        client_ui_revision=bundle.client_ui_revision,
    )
    settings = TaskSettingsDocument.from_snapshot(
        SettingsSnapshot(
            revision=1,
            payload=compiled.payload,
            updated_at=datetime(2026, 7, 13, tzinfo=UTC),
        ),
        task_ids=registry.task_ids,
    )

    registry.validate_settings(settings)
    assert len(registry.task_ids) == 57


def test_default_template_can_be_published_with_disabled_placeholder_campaigns(tmp_path: Path) -> None:
    document = _template()
    compiled = WebConfigurationCompiler().compile(document)
    source = Mumu12GameRuntimeBundleSource(
        Path(),
        device_factory=lambda _config: object.__new__(Device),
        content_revision=_Revision("content-test"),
        client_ui_revision=_Revision("client-test"),
    )
    bundle = source.build("snapshot-test", document, compiled)
    registry = build_game_task_registry(
        bundle.tasks,
        content_revision=bundle.content_revision,
        client_ui_revision=bundle.client_ui_revision,
    )

    with SQLiteStateStore(tmp_path / "state.sqlite3") as store:
        published = ConfigurationPublisher(store=store, factories=registry, clock=_Clock()).publish(
            compiled.payload,
            compiled.schedules,
            source_revision=compiled.source_revision,
            expected_revision=0,
        )

    assert published.revision == 1
    assert len(registry.task_ids) == 57


def test_system_loop_clock_wait_is_cancellation_aware() -> None:
    abort = AbortToken()
    abort.request("test stop")

    with pytest.raises(AbortRequested, match="test stop"):
        SystemLoopClock.sleep(30, abort)


def test_default_process_host_can_be_constructed_without_opening_a_device(tmp_path: Path) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "template.json").write_text("{}", encoding="utf-8")
    (tmp_path / "content" / "events").mkdir(parents=True)
    (tmp_path / "module").mkdir()

    with build_default_instance_process_host(tmp_path) as host:
        assert isinstance(host, InstanceProcessHost)

    assert (tmp_path / ".alas-runtime" / "notification-spool.sqlite3").is_file()
