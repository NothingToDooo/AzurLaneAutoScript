import shutil
from pathlib import Path
from typing import TYPE_CHECKING, cast

from module.adapters.mumu12 import CancellationAwareMumu12Device
from module.base.utils import random_rectangle_point
from module.config.config import AzurLaneConfig, name_to_function
from module.daemon.benchmark import Benchmark, BenchmarkResult
from module.device.device import Device
from module.exception import RequestHumanTakeover
from module.handler.login import LoginHandler
from module.logger import logger
from module.maintenance import (
    BenchmarkCategory,
    BenchmarkMeasurement,
    BenchmarkPreparation,
    BenchmarkReady,
    BenchmarkReport,
    BenchmarkScene,
    BenchmarkSelection,
    BenchmarkUnavailable,
    MaintenanceServices,
    UncensoredPayload,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from module.application import CancellationSource


_LOCALIZATION_TEXT = "Localization = true\nLocalization_skin = true\n"
_BENCHMARK_CLICK_AREA = (124, 4, 649, 106)


def _activate(
    config: AzurLaneConfig,
    device: Device,
    task_name: str,
    cancellation: CancellationSource,
) -> Device:
    cancellation.raise_if_requested()
    task = name_to_function(task_name)
    config.task = task
    config.bind("Alas")
    device.config = config
    return cast("Device", CancellationAwareMumu12Device(device, cancellation))


class Mumu12DeviceAppLifecycle:
    __slots__ = ("_device",)

    def __init__(self, device: Device) -> None:
        if not isinstance(device, Device):
            message = "device must be a Device"
            raise TypeError(message)
        self._device = device

    def start(self, cancellation: CancellationSource) -> None:
        cancellation.raise_if_requested()
        self._device.app_controller.start()
        self._device.stuck_record_clear()
        self._device.click_record_clear()

    def stop(self, cancellation: CancellationSource) -> None:
        cancellation.raise_if_requested()
        self._device.app_controller.stop()
        self._device.stuck_record_clear()
        self._device.click_record_clear()


class Mumu12LoginFlow:
    __slots__ = ("_config", "_device")

    def __init__(self, config: AzurLaneConfig, device: Device) -> None:
        if not isinstance(config, AzurLaneConfig):
            message = "config must be an AzurLaneConfig"
            raise TypeError(message)
        if not isinstance(device, Device):
            message = "device must be a Device"
            raise TypeError(message)
        self._config = config
        self._device = device

    def ensure_logged_in(self, cancellation: CancellationSource) -> None:
        device = _activate(self._config, self._device, "Alas", cancellation)
        LoginHandler(self._config, device=device).handle_app_login()


class LocalUncensoredAssetBuilder:
    __slots__ = ("_output",)

    def __init__(self, toolkit_root: Path) -> None:
        if not isinstance(toolkit_root, Path):
            message = "toolkit_root must be a Path"
            raise TypeError(message)
        self._output = (toolkit_root.resolve() / "files").resolve()

    def build(self, cancellation: CancellationSource) -> UncensoredPayload:
        cancellation.raise_if_requested()
        if self._output.exists():
            shutil.rmtree(self._output)
        cancellation.raise_if_requested()
        self._output.mkdir(parents=True)
        cancellation.raise_if_requested()
        (self._output / "localization.txt").write_text(_LOCALIZATION_TEXT, encoding="utf-8")
        return UncensoredPayload(self._output)


class Mumu12UncensoredAssetInstaller:
    __slots__ = ("_config", "_device")

    def __init__(self, config: AzurLaneConfig, device: Device) -> None:
        if not isinstance(config, AzurLaneConfig):
            message = "config must be an AzurLaneConfig"
            raise TypeError(message)
        if not isinstance(device, Device):
            message = "device must be a Device"
            raise TypeError(message)
        self._config = config
        self._device = device

    def install(
        self,
        payload: UncensoredPayload,
        package_name: str,
        cancellation: CancellationSource,
    ) -> None:
        if not isinstance(payload, UncensoredPayload):
            message = "payload must be an UncensoredPayload"
            raise TypeError(message)
        device = _activate(self._config, self._device, "AzurLaneUncensored", cancellation)
        remote = f"/sdcard/Android/data/{package_name}"
        device.adb_push(str(payload.source), remote)


class Mumu12BenchmarkAdapter:
    __slots__ = ("_config", "_device", "_runner")

    def __init__(self, config: AzurLaneConfig, device: Device) -> None:
        if not isinstance(config, AzurLaneConfig):
            message = "config must be an AzurLaneConfig"
            raise TypeError(message)
        if not isinstance(device, Device):
            message = "device must be a Device"
            raise TypeError(message)
        self._config = config
        self._device = device
        self._runner: Benchmark | None = None

    def prepare(self, safe_stage: str, cancellation: CancellationSource) -> BenchmarkPreparation:
        device = _activate(self._config, self._device, "Benchmark", cancellation)
        runner = Benchmark(self._config, device=device)
        try:
            cancellation.raise_if_requested()
            runner.ensure_campaign_ui(safe_stage, mode="normal")
        except RequestHumanTakeover:
            self._runner = None
            return BenchmarkUnavailable("campaign scene unavailable")
        self._runner = runner
        return BenchmarkReady()

    def measure(self, scene: BenchmarkScene, cancellation: CancellationSource) -> BenchmarkReport:
        runner = self._prepared_runner()
        measurements: list[BenchmarkMeasurement] = []
        if BenchmarkCategory.SCREENSHOT in scene.categories:
            measurements.append(
                self._measure(
                    runner,
                    BenchmarkCategory.SCREENSHOT,
                    "nemu_ipc",
                    runner.device.screenshot_nemu_ipc,
                    cancellation,
                )
            )
        if BenchmarkCategory.CLICK in scene.categories:
            x, y = random_rectangle_point(_BENCHMARK_CLICK_AREA)
            measurements.append(
                self._measure(
                    runner,
                    BenchmarkCategory.CLICK,
                    "minitouch",
                    lambda: runner.device.click_minitouch(x, y),
                    cancellation,
                )
            )
        return BenchmarkReport(
            measurements=tuple(measurements),
            selections=tuple(
                BenchmarkSelection(measurement.category, measurement.method) for measurement in measurements
            ),
        )

    @staticmethod
    def _measure(
        runner: Benchmark,
        category: BenchmarkCategory,
        method: str,
        operation: Callable[[], object],
        cancellation: CancellationSource,
    ) -> BenchmarkMeasurement:
        cancellation.raise_if_requested()
        result = runner.benchmark_test(operation)
        if isinstance(result, int | float):
            return BenchmarkMeasurement(category, method, average_seconds=float(result))
        return BenchmarkMeasurement(category, method, failure_reason=str(result))

    def present(self, report: BenchmarkReport, cancellation: CancellationSource) -> None:
        runner = self._prepared_runner()
        for category in BenchmarkCategory:
            rows = tuple(
                (measurement.method, self._benchmark_result(measurement))
                for measurement in report.measurements
                if measurement.category is category
            )
            if not rows:
                continue
            cancellation.raise_if_requested()
            if category is BenchmarkCategory.SCREENSHOT:
                runner.show("Screenshot", rows, runner.evaluate_screenshot)
            else:
                runner.show("Control", rows, runner.evaluate_click)
        for selection in report.selections:
            logger.info(f"Selected {selection.category.value} method: {selection.method}")

    def _prepared_runner(self) -> Benchmark:
        if self._runner is None:
            message = "benchmark environment must be prepared before measurement or presentation"
            raise RuntimeError(message)
        return self._runner

    @staticmethod
    def _benchmark_result(measurement: BenchmarkMeasurement) -> BenchmarkResult:
        if measurement.average_seconds is not None:
            return measurement.average_seconds
        return cast("str", measurement.failure_reason)


def build_mumu12_maintenance_services(
    config: AzurLaneConfig,
    device: Device,
    *,
    uncensored_toolkit_root: Path | None = None,
) -> MaintenanceServices:
    """构造四个 maintenance task 共用的 production 依赖。"""

    toolkit_root = (
        Path.cwd() / "toolkit" / "AzurLaneUncensored" if uncensored_toolkit_root is None else uncensored_toolkit_root
    )
    app = Mumu12DeviceAppLifecycle(device)
    login = Mumu12LoginFlow(config, device)
    benchmark = Mumu12BenchmarkAdapter(config, device)
    return MaintenanceServices(
        app=app,
        login=login,
        uncensored_assets=LocalUncensoredAssetBuilder(toolkit_root),
        uncensored_installer=Mumu12UncensoredAssetInstaller(config, device),
        benchmark_environment=benchmark,
        benchmark_engine=benchmark,
        benchmark_presenter=benchmark,
    )
