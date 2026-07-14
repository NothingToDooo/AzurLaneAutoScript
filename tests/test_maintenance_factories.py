from pathlib import Path
from types import MappingProxyType
from typing import cast

import pytest

from module.interaction import AppLifecycle, AppStatus, CancellationSignal
from module.maintenance import (
    BenchmarkCategory,
    BenchmarkMeasurement,
    BenchmarkReady,
    BenchmarkReport,
    BenchmarkScene,
    BenchmarkSelection,
    BenchmarkTask,
    GameManagerTask,
    MaintenanceServices,
    RestartTask,
    UncensoredPayload,
    UncensoredTask,
    build_maintenance_factories,
)
from module.runtime import FrozenJsonValue, SettingsDocumentError, TaskBuildContext, TaskStateDocument
from module.task_registry import TASK_CATALOG


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
        measurement = BenchmarkMeasurement(BenchmarkCategory.SCREENSHOT, "test", average_seconds=0.1)
        selection = BenchmarkSelection(BenchmarkCategory.SCREENSHOT, "test")
        return BenchmarkReport((measurement,), (selection,))

    def present(self, report: BenchmarkReport, cancellation: CancellationSignal) -> None:
        cancellation.raise_if_requested()
        self.calls.append(f"present:{len(report.measurements)}")


def _services() -> MaintenanceServices:
    shared = _Services()
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


@pytest.mark.parametrize(
    ("command", "settings", "task_type"),
    [
        (
            "restart",
            {"schedule": {"timezone": "Asia/Hong_Kong", "triggers": ("08:00",)}},
            RestartTask,
        ),
        ("azur_lane_uncensored", {"package_name": "com.bilibili.azurlane"}, UncensoredTask),
        ("game_manager", {"auto_restart": True}, GameManagerTask),
        ("benchmark", {"scene": "screenshot", "safe_stage": "7-2"}, BenchmarkTask),
    ],
)
def test_maintenance_factories_build_typed_tasks(
    command: str,
    settings: dict[str, FrozenJsonValue],
    task_type: type[object],
) -> None:
    factories = build_maintenance_factories(_services())

    task = factories[command].build(_context(command, settings))

    assert isinstance(task, task_type)
    assert set(factories) == {"restart", "azur_lane_uncensored", "game_manager", "benchmark"}


def test_maintenance_factory_rejects_schema_drift() -> None:
    factories = build_maintenance_factories(_services())

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
