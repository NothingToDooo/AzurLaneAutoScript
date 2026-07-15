from datetime import UTC, datetime
from types import MappingProxyType
from typing import TYPE_CHECKING, cast

import pytest

from module.application import (
    AbortToken,
    ExecutionMode,
    RunMetadata,
    TaskContext,
    TaskId,
)
from module.gameplay.opsi import (
    AbyssalSettings,
    ArchiveSettings,
    AshAssistSettings,
    AshBeaconAttackMode,
    AshBeaconSettings,
    CrossMonthSettings,
    ExploreSettings,
    FleetSettings,
    Hazard1LevelingSettings,
    MeowfficerFarmingSettings,
    MonthBossMode,
    MonthBossSettings,
    ObscureSettings,
    OperationSirenWorkflow,
    OpsiDailySettings,
    OpsiShopPreset,
    ShopSettings,
    StrongholdSettings,
    VoucherSettings,
    WorldGeneralSettings,
    WorldMissionCursor,
    WorldOperation,
    WorldProgress,
    WorldSchedule,
    WorldTaskReport,
    WorldTaskSettings,
    WorldTaskSpec,
    WorldTaskStatus,
)
from module.gameplay.opsi_factories import OpsiWorkflows, build_opsi_factories
from module.gameplay.opsi_progress import WorldMissionEvidenceKind
from module.runtime import (
    FrozenJsonValue,
    SettingsDocumentError,
    TaskBuildContext,
    TaskStateDocument,
    TaskStateDocumentError,
    TaskStateEntry,
)
from module.task_registry import TASK_CATALOG

if TYPE_CHECKING:
    from collections.abc import Mapping

    from module.interaction import CancellationSignal


_OBSERVED_AT = datetime(2026, 7, 13, 12, tzinfo=UTC)
_SERVER_UPDATE_AT = datetime(2026, 7, 14, 4, tzinfo=UTC)
_MONTH_RESET_AT = datetime(2026, 8, 1, tzinfo=UTC)
_ARCHIVE_REFRESH_AT = datetime(2026, 7, 15, tzinfo=UTC)
_SHOP_RETRY_AT = datetime(2026, 7, 13, 12, 30, tzinfo=UTC)

_GENERAL = WorldGeneralSettings(
    use_logger=True,
    buy_action_point_limit=2,
    oil_preserve=1000,
    repair_threshold=0.4,
    random_map_events=True,
    akashi_shop_filter="ActionPoint > PurpleCoins",
)
_FLEET = FleetSettings(fleet_index=2, use_submarine=True)
_FLEET_FILTER = "Fleet-4 > CallSubmarine > Fleet-2 > Fleet-3 > Fleet-1"
_VOUCHER_FILTER = "LoggerAbyssal > LoggerObscure > Book > Coin > Fragment"

_GENERAL_JSON = cast(
    "FrozenJsonValue",
    MappingProxyType(
        {
            "use_logger": True,
            "buy_action_point_limit": 2,
            "oil_preserve": 1000,
            "repair_threshold": 0.4,
            "random_map_events": True,
            "akashi_shop_filter": "ActionPoint > PurpleCoins",
        }
    ),
)
_FLEET_JSON = cast(
    "FrozenJsonValue",
    MappingProxyType({"fleet_index": 2, "use_submarine": True}),
)


def _settings(**values: FrozenJsonValue) -> dict[str, FrozenJsonValue]:
    return {"general": _GENERAL_JSON, **values}


_CASES: tuple[tuple[str, dict[str, FrozenJsonValue], WorldTaskSettings], ...] = (
    ("opsi_ash_assist", {"minimum_tier": 15}, AshAssistSettings(15)),
    (
        "opsi_ash_beacon",
        {
            "attack_mode": "current_dossier",
            "one_hit_mode": True,
            "dossier_auto_attack": False,
            "request_assist": True,
            "ensure_fully_collected": True,
        },
        AshBeaconSettings(
            attack_mode=AshBeaconAttackMode.CURRENT_DOSSIER,
            one_hit_mode=True,
            dossier_auto_attack=False,
            request_assist=True,
            ensure_fully_collected=True,
        ),
    ),
    (
        "opsi_explore",
        _settings(fleet=_FLEET_JSON, special_radar=True, force_run=False, last_zone=44),
        ExploreSettings(
            general=_GENERAL,
            fleet=_FLEET,
            special_radar=True,
            force_run=False,
            last_zone=44,
        ),
    ),
    (
        "opsi_shop",
        _settings(preset="custom", custom_filter="LoggerAbyssalT6 > ActionPoint"),
        ShopSettings(_GENERAL, OpsiShopPreset.CUSTOM, "LoggerAbyssalT6 > ActionPoint"),
    ),
    (
        "opsi_voucher",
        _settings(filter=_VOUCHER_FILTER),
        VoucherSettings(_GENERAL, _VOUCHER_FILTER),
    ),
    (
        "opsi_daily",
        _settings(fleet=_FLEET_JSON, do_missions=True, use_tuning_samples=False),
        OpsiDailySettings(
            general=_GENERAL,
            fleet=_FLEET,
            do_missions=True,
            use_tuning_samples=False,
        ),
    ),
    (
        "opsi_obscure",
        _settings(fleet=_FLEET_JSON, force_run=True),
        ObscureSettings(general=_GENERAL, fleet=_FLEET, force_run=True),
    ),
    (
        "opsi_month_boss",
        _settings(
            fleet_filter=_FLEET_FILTER,
            mode="normal_hard",
            check_adaptability=True,
            force_run=False,
        ),
        MonthBossSettings(
            general=_GENERAL,
            fleet_filter=_FLEET_FILTER,
            mode=MonthBossMode.NORMAL_HARD,
            check_adaptability=True,
            force_run=False,
        ),
    ),
    (
        "opsi_abyssal",
        _settings(fleet_filter=_FLEET_FILTER, force_run=True),
        AbyssalSettings(general=_GENERAL, fleet_filter=_FLEET_FILTER, force_run=True),
    ),
    (
        "opsi_archive",
        _settings(fleet=_FLEET_JSON, voucher_filter=_VOUCHER_FILTER),
        ArchiveSettings(_GENERAL, _FLEET, _VOUCHER_FILTER),
    ),
    (
        "opsi_stronghold",
        _settings(fleet_filter=_FLEET_FILTER, force_run=False),
        StrongholdSettings(
            general=_GENERAL,
            fleet_filter=_FLEET_FILTER,
            force_run=False,
        ),
    ),
    (
        "opsi_meowfficer_farming",
        _settings(
            fleet=_FLEET_JSON,
            action_point_preserve=1000,
            hazard_level=5,
            target_zone=0,
            ensure_ash_fully_collected=True,
        ),
        MeowfficerFarmingSettings(
            general=_GENERAL,
            fleet=_FLEET,
            action_point_preserve=1000,
            hazard_level=5,
            target_zone=0,
            ensure_ash_fully_collected=True,
        ),
    ),
    (
        "opsi_hazard1_leveling",
        _settings(fleet=_FLEET_JSON, target_zone=44, ensure_ash_fully_collected=True),
        Hazard1LevelingSettings(
            general=_GENERAL,
            fleet=_FLEET,
            target_zone=44,
            ensure_ash_fully_collected=True,
        ),
    ),
    (
        "opsi_cross_month",
        _settings(
            daily_fleet_index=1,
            obscure_fleet_index=2,
            abyssal_fleet_filter=_FLEET_FILTER,
            meowfficer_fleet_index=3,
        ),
        CrossMonthSettings(
            _GENERAL,
            FleetSettings(fleet_index=1, use_submarine=False),
            FleetSettings(fleet_index=2, use_submarine=False),
            _FLEET_FILTER,
            FleetSettings(fleet_index=3, use_submarine=False),
        ),
    ),
)


class _Workflow:
    def __init__(self) -> None:
        self.received_spec: WorldTaskSpec | None = None
        self.received_progress: WorldProgress | None = None

    def execute(
        self,
        spec: WorldTaskSpec,
        progress: WorldProgress | None,
        cancellation: CancellationSignal,
    ) -> WorldTaskReport:
        cancellation.raise_if_requested()
        self.received_spec = spec
        self.received_progress = progress
        retry_at = _SHOP_RETRY_AT if spec.operation is WorldOperation.SHOP else None
        return WorldTaskReport(
            observed_at=_OBSERVED_AT,
            status=WorldTaskStatus.COMPLETED,
            schedule=WorldSchedule(_SERVER_UPDATE_AT, _MONTH_RESET_AT, _ARCHIVE_REFRESH_AT),
            retry_at=retry_at,
        )


def _build_context(
    command: str,
    settings: dict[str, FrozenJsonValue],
    *,
    task_state: TaskStateDocument | None = None,
) -> TaskBuildContext:
    return TaskBuildContext(
        definition=TASK_CATALOG[command],
        settings_revision=7,
        content_revision="content-1",
        settings=MappingProxyType(settings),
        task_state=TaskStateDocument.empty(command) if task_state is None else task_state,
    )


def _progress_state(
    command: str,
    *,
    schema_version: int = 1,
    key: str = "world_progress",
    payload: object | None = None,
) -> TaskStateDocument:
    progress = WorldProgress(
        task_id=TaskId(command),
        operation=WorldOperation(command),
        completed_units=3,
        cycle_anchor=_SERVER_UPDATE_AT,
        settings_revision=7,
        content_revision="content-1",
        cursor=WorldMissionCursor(WorldMissionEvidenceKind.PINNED_ZONE, 4),
    )
    return TaskStateDocument(
        namespace=command,
        entries={
            key: TaskStateEntry(
                schema_version=schema_version,
                payload=cast("FrozenJsonValue", progress.to_payload() if payload is None else payload),
                updated_at=_OBSERVED_AT,
            )
        },
    )


def _run_context(command: str) -> TaskContext:
    return TaskContext(
        task_id=TaskId(command),
        started_at=datetime(2026, 7, 13, tzinfo=UTC),
        mode=ExecutionMode.SCHEDULED_JOB,
        metadata=RunMetadata(settings_revision=7, content_revision="content-1"),
        abort=AbortToken(),
    )


@pytest.mark.parametrize(("command", "settings", "expected"), _CASES)
def test_opsi_factories_decode_all_fourteen_commands_into_complete_specs(
    command: str,
    settings: dict[str, FrozenJsonValue],
    expected: WorldTaskSettings,
) -> None:
    workflow = _Workflow()
    factories = build_opsi_factories(OpsiWorkflows(workflow))

    task = factories[command].build(_build_context(command, settings))
    task.run(_run_context(command))

    assert workflow.received_spec is not None
    assert workflow.received_spec.task_id == TaskId(command)
    assert workflow.received_spec.operation.value == command
    assert workflow.received_spec.settings == expected
    assert set(factories) == {case[0] for case in _CASES}


def test_cross_month_spec_owns_former_cross_task_configuration() -> None:
    command, settings, _expected = _CASES[-1]
    workflow = _Workflow()
    task = build_opsi_factories(OpsiWorkflows(workflow))[command].build(_build_context(command, settings))

    task.run(_run_context(command))

    assert workflow.received_spec is not None
    cross_month = cast("CrossMonthSettings", workflow.received_spec.settings)
    assert cross_month.daily_fleet == FleetSettings(fleet_index=1, use_submarine=False)
    assert cross_month.obscure_fleet == FleetSettings(fleet_index=2, use_submarine=False)
    assert cross_month.abyssal_fleet_filter == _FLEET_FILTER
    assert cross_month.meowfficer_fleet == FleetSettings(fleet_index=3, use_submarine=False)


def test_opsi_factories_reject_missing_unknown_and_nested_unknown_fields() -> None:
    factories = build_opsi_factories(OpsiWorkflows(_Workflow()))
    with pytest.raises(SettingsDocumentError, match="missing required setting"):
        factories["opsi_ash_beacon"].build(
            _build_context(
                "opsi_ash_beacon",
                {
                    "attack_mode": "current",
                    "one_hit_mode": True,
                    "dossier_auto_attack": False,
                    "request_assist": True,
                },
            )
        )
    with pytest.raises(SettingsDocumentError, match="unknown settings"):
        factories["opsi_ash_assist"].build(_build_context("opsi_ash_assist", {"minimum_tier": 15, "legacy": True}))

    nested_general = dict(cast("Mapping[str, FrozenJsonValue]", _GENERAL_JSON))
    nested_general["legacy"] = True
    explore = dict(_CASES[2][1])
    explore["general"] = cast("FrozenJsonValue", MappingProxyType(nested_general))
    with pytest.raises(SettingsDocumentError, match=r"unknown settings at .*general"):
        factories["opsi_explore"].build(_build_context("opsi_explore", explore))


@pytest.mark.parametrize(
    ("command", "field", "invalid", "message"),
    [
        ("opsi_ash_assist", "minimum_tier", 0, "must be at least 1"),
        ("opsi_ash_beacon", "attack_mode", "all", "must be one of"),
        ("opsi_meowfficer_farming", "hazard_level", 7, "must be one of"),
        ("opsi_hazard1_leveling", "target_zone", 33, "must be one of"),
        ("opsi_cross_month", "daily_fleet_index", 5, "must be at most 4"),
    ],
)
def test_opsi_factories_reject_invalid_domain_values(
    command: str,
    field: str,
    invalid: FrozenJsonValue,
    message: str,
) -> None:
    raw = dict(next(settings for candidate, settings, _expected in _CASES if candidate == command))
    raw[field] = invalid
    factory = build_opsi_factories(OpsiWorkflows(_Workflow()))[command]

    with pytest.raises(SettingsDocumentError, match=message):
        factory.build(_build_context(command, raw))


def test_opsi_workflows_fail_fast_for_missing_execute_port() -> None:
    with pytest.raises(TypeError, match=r"world must implement execute\(\)"):
        OpsiWorkflows(cast("OperationSirenWorkflow", object()))


def test_factory_hydrates_typed_progress_and_passes_it_to_workflow() -> None:
    command = "opsi_daily"
    settings = dict(next(raw for candidate, raw, _expected in _CASES if candidate == command))
    task_state = _progress_state(command)
    workflow = _Workflow()

    task = build_opsi_factories(OpsiWorkflows(workflow))[command].build(
        _build_context(command, settings, task_state=task_state)
    )
    task.run(_run_context(command))

    assert workflow.received_progress == WorldProgress(
        task_id=TaskId(command),
        operation=WorldOperation.DAILY,
        completed_units=3,
        cycle_anchor=_SERVER_UPDATE_AT,
        settings_revision=7,
        content_revision="content-1",
        cursor=WorldMissionCursor(WorldMissionEvidenceKind.PINNED_ZONE, 4),
    )


def test_factory_rejects_unknown_schema_malformed_and_mismatched_progress() -> None:
    command = "opsi_daily"
    settings = dict(next(raw for candidate, raw, _expected in _CASES if candidate == command))
    factory = build_opsi_factories(OpsiWorkflows(_Workflow()))[command]
    valid_payload = WorldProgress(
        task_id=TaskId(command),
        operation=WorldOperation.DAILY,
        completed_units=3,
        cycle_anchor=_SERVER_UPDATE_AT,
        settings_revision=7,
        content_revision="content-1",
        cursor=WorldMissionCursor(WorldMissionEvidenceKind.PINNED_ZONE, 4),
    ).to_payload()
    extra_field = dict(valid_payload)
    extra_field["legacy"] = True
    wrong_type = dict(valid_payload)
    wrong_type["completed_units"] = True
    wrong_identity = dict(valid_payload)
    wrong_identity["task_id"] = "opsi_archive"
    unknown_cursor = dict(valid_payload)
    unknown_cursor["cursor"] = {"kind": "offset", "value": 4}

    invalid_states = (
        (_progress_state(command, key="legacy"), "unknown Operation Siren task state keys"),
        (_progress_state(command, schema_version=2), "unsupported world_progress schema version"),
        (_progress_state(command, payload=extra_field), "fields mismatch"),
        (_progress_state(command, payload=wrong_type), "completed_units must be an integer"),
        (_progress_state(command, payload=wrong_identity), "task_id must match operation"),
        (_progress_state(command, payload=unknown_cursor), "cursor.kind has unknown value"),
    )
    for task_state, message in invalid_states:
        with pytest.raises(TaskStateDocumentError, match=message):
            factory.build(_build_context(command, settings, task_state=task_state))


@pytest.mark.parametrize("command", ["opsi_shop", "opsi_voucher", "opsi_cross_month"])
def test_one_shot_factory_rejects_persisted_progress(command: str) -> None:
    settings = dict(next(raw for candidate, raw, _expected in _CASES if candidate == command))
    task_state = TaskStateDocument(
        namespace=command,
        entries={
            "world_progress": TaskStateEntry(
                schema_version=1,
                payload={"unexpected": True},
                updated_at=_OBSERVED_AT,
            )
        },
    )
    factory = build_opsi_factories(OpsiWorkflows(_Workflow()))[command]

    with pytest.raises(TaskStateDocumentError, match="one-shot operation must not contain task state"):
        factory.build(_build_context(command, settings, task_state=task_state))
