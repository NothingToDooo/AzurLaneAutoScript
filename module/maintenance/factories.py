from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING

from module.maintenance.benchmark import BenchmarkSettings, BenchmarkTask
from module.maintenance.game_manager import GameManagerSettings, GameManagerTask
from module.maintenance.restart import RestartSettings, RestartTask
from module.maintenance.uncensored import UncensoredSettings, UncensoredTask
from module.runtime import ConfiguredTaskFactory

if TYPE_CHECKING:
    from collections.abc import Mapping

    from module.maintenance.benchmark import BenchmarkEngine, BenchmarkEnvironment, BenchmarkPresenter
    from module.maintenance.game_manager import AppLifecycle, LoginFlow
    from module.maintenance.uncensored import UncensoredAssetBuilder, UncensoredAssetInstaller
    from module.runtime import TaskFactory


def _require_method(value: object, method: str, *, field_name: str) -> None:
    if isinstance(value, type) or not callable(getattr(value, method, None)):
        message = f"{field_name} must implement {method}()"
        raise TypeError(message)


@dataclass(frozen=True, slots=True)
class MaintenanceServices:
    app: AppLifecycle
    login: LoginFlow
    uncensored_assets: UncensoredAssetBuilder
    uncensored_installer: UncensoredAssetInstaller
    benchmark_environment: BenchmarkEnvironment
    benchmark_engine: BenchmarkEngine
    benchmark_presenter: BenchmarkPresenter

    def __post_init__(self) -> None:
        dependencies = (
            (self.app, "start", "app"),
            (self.app, "stop", "app"),
            (self.login, "ensure_logged_in", "login"),
            (self.uncensored_assets, "build", "uncensored_assets"),
            (self.uncensored_installer, "install", "uncensored_installer"),
            (self.benchmark_environment, "prepare", "benchmark_environment"),
            (self.benchmark_engine, "measure", "benchmark_engine"),
            (self.benchmark_presenter, "present", "benchmark_presenter"),
        )
        for dependency, method, field_name in dependencies:
            _require_method(dependency, method, field_name=field_name)


def build_maintenance_factories(services: MaintenanceServices) -> Mapping[str, TaskFactory]:
    if not isinstance(services, MaintenanceServices):
        message = "services must be MaintenanceServices"
        raise TypeError(message)
    factories: dict[str, TaskFactory] = {
        "restart": ConfiguredTaskFactory(
            RestartSettings,
            lambda settings: RestartTask(services.app, services.login, settings),
        ),
        "azur_lane_uncensored": ConfiguredTaskFactory(
            UncensoredSettings,
            lambda settings: UncensoredTask(
                services.uncensored_assets,
                services.uncensored_installer,
                services.app,
                services.login,
                settings,
            ),
        ),
        "game_manager": ConfiguredTaskFactory(
            GameManagerSettings,
            lambda settings: GameManagerTask(services.app, services.login, settings),
        ),
        "benchmark": ConfiguredTaskFactory(
            BenchmarkSettings,
            lambda settings: BenchmarkTask(
                services.benchmark_environment,
                services.benchmark_engine,
                services.benchmark_presenter,
                settings,
            ),
        ),
    }
    return MappingProxyType(factories)
