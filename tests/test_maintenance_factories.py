from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType
from typing import cast

import pytest

from module.application import AbortToken, ExecutionMode, RunMetadata, TaskContext, TaskId
from module.interaction import AppLifecycle, AppStatus, CancellationSignal
from module.maintenance import (
    BenchmarkMeasurement,
    BenchmarkReady,
    BenchmarkReport,
    BenchmarkScene,
    BenchmarkSelection,
    MaintenanceServices,
    UncensoredPayload,
    build_maintenance_factories,
)
from module.runtime import FrozenJsonValue, SettingsDocumentError, TaskBuildContext, TaskStateDocument
from module.task_registry import TASK_CATALOG

_STARTED_AT = datetime(2026, 7, 15, 8, tzinfo=UTC)


class _Services:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def status(self, cancellation: CancellationSignal) -> AppStatus:
        cancellation.raise_if_requested()
        self.calls.append("status")
        return AppStatus.STOPPED

    def start(self, cancellation: CancellationSignal) -> None:
        cancellation.raise_if_requested()
        self.calls.append("start")

    def stop(self, cancellation: CancellationSignal) -> None:
        cancellation.raise_if_requested()
        self.calls.append("stop")

    def ensure_logged_in(self, cancellation: CancellationSignal) -> None:
        cancellation.raise_if_requested()
        self.calls.append("login")

    def build(self, cancellation: CancellationSignal) -> UncensoredPayload:
        cancellation.raise_if_requested()
        self.calls.append("build")
        return UncensoredPayload(Path.cwd().resolve())

    def install(
        self,
        payload: UncensoredPayload,
        package_name: str,
        cancellation: CancellationSignal,
    ) -> None:
        cancellation.raise_if_requested()
        self.calls.append(f"install:{payload.source}:{package_name}")

    def prepare(self, safe_stage: str, cancellation: CancellationSignal) -> BenchmarkReady:
        cancellation.raise_if_requested()
        self.calls.append(f"prepare:{safe_stage}")
        return BenchmarkReady()

    def measure(self, scene: BenchmarkScene, cancellation: CancellationSignal) -> BenchmarkReport:
        cancellation.raise_if_requested()
        self.calls.append(f"measure:{scene.value}")
        category = next(iter(scene.categories))
        measurement = BenchmarkMeasurement(category, "recorded", average_seconds=0.1)
        selection = BenchmarkSelection(category, "recorded")
        return BenchmarkReport((measurement,), (selection,))

    def present(self, report: BenchmarkReport, cancellation: CancellationSignal) -> None:
        cancellation.raise_if_requested()
        self.calls.append(f"present:{len(report.measurements)}")


def _services(shared: _Services) -> MaintenanceServices:
    return MaintenanceServices(
        app=shared,
        login=shared,
        uncensored_assets=shared,
        uncensored_installer=shared,
        benchmark_environment=shared,
        benchmark_engine=shared,
        benchmark_presenter=shared,
    )


def _context(command: str, settings: dict[str, FrozenJsonValue]) -> TaskBuildContext:
    return TaskBuildContext(
        definition=TASK_CATALOG[command],
        settings_revision=5,
        settings=MappingProxyType(settings),
        task_state=TaskStateDocument.empty(command),
    )


def _task_context(command: str) -> TaskContext:
    return TaskContext(
        task_id=TaskId(command),
        started_at=_STARTED_AT,
        mode=ExecutionMode.SCHEDULED_JOB,
        metadata=RunMetadata(settings_revision=5, content_revision="content-1"),
        abort=AbortToken(),
    )


def test_benchmark_factory_passes_decoded_scene_and_safe_stage_to_services() -> None:
    shared = _Services()
    task = build_maintenance_factories(_services(shared))["benchmark"].build(
        _context("benchmark", {"scene": "click", "safe_stage": "13-4"})
    )

    task.run(_task_context("benchmark"))

    assert shared.calls == ["prepare:13-4", "measure:click", "present:1"]


def test_maintenance_factory_rejects_schema_drift() -> None:
    factories = build_maintenance_factories(_services(_Services()))

    with pytest.raises(SettingsDocumentError, match="unknown settings"):
        factories["game_manager"].build(_context("game_manager", {"auto_restart": True, "obsolete": False}))


def test_maintenance_services_fail_fast_for_missing_ports() -> None:
    shared = _Services()
    with pytest.raises(TypeError, match=r"app must implement status\(\)"):
        MaintenanceServices(
            app=cast("AppLifecycle", object()),
            login=shared,
            uncensored_assets=shared,
            uncensored_installer=shared,
            benchmark_environment=shared,
            benchmark_engine=shared,
            benchmark_presenter=shared,
        )
