import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, override

from module.application import Succeeded, Task, TaskContext, TaskResult

if TYPE_CHECKING:
    from module.interaction import AppLifecycle, CancellationSignal
    from module.maintenance.game_manager import LoginFlow


_PACKAGE_NAME_PATTERN = re.compile(
    r"[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+",
    flags=re.ASCII,
)


@dataclass(frozen=True, slots=True)
class UncensoredSettings:
    package_name: str

    def __post_init__(self) -> None:
        if not isinstance(self.package_name, str):
            message = "package_name must be a string"
            raise TypeError(message)
        if _PACKAGE_NAME_PATTERN.fullmatch(self.package_name) is None:
            message = f"invalid Android package name: {self.package_name!r}"
            raise ValueError(message)


@dataclass(frozen=True, slots=True)
class UncensoredPayload:
    source: Path

    def __post_init__(self) -> None:
        if not isinstance(self.source, Path):
            message = "source must be a Path"
            raise TypeError(message)
        if not self.source.is_absolute():
            message = "source must be an absolute path"
            raise ValueError(message)


class UncensoredAssetBuilder(Protocol):
    def build(self, cancellation: CancellationSignal) -> UncensoredPayload: ...


class UncensoredAssetInstaller(Protocol):
    def install(
        self,
        payload: UncensoredPayload,
        package_name: str,
        cancellation: CancellationSignal,
    ) -> None: ...


class UncensoredTask(Task):
    __slots__ = ("_app", "_assets", "_installer", "_login", "_settings")

    def __init__(
        self,
        assets: UncensoredAssetBuilder,
        installer: UncensoredAssetInstaller,
        app: AppLifecycle,
        login: LoginFlow,
        settings: UncensoredSettings,
    ) -> None:
        if not isinstance(settings, UncensoredSettings):
            message = "settings must be UncensoredSettings"
            raise TypeError(message)
        self._assets = assets
        self._installer = installer
        self._app = app
        self._login = login
        self._settings = settings

    @override
    def run(self, context: TaskContext) -> TaskResult:
        context.abort.raise_if_requested()
        payload = self._assets.build(context.abort)
        if not isinstance(payload, UncensoredPayload):
            message = "UncensoredAssetBuilder.build() must return an UncensoredPayload"
            raise TypeError(message)

        context.abort.raise_if_requested()
        self._installer.install(payload, self._settings.package_name, context.abort)
        context.abort.raise_if_requested()
        self._app.stop(context.abort)
        context.abort.raise_if_requested()
        self._app.start(context.abort)
        context.abort.raise_if_requested()
        self._login.ensure_logged_in(context.abort)
        context.abort.raise_if_requested()
        return TaskResult(outcome=Succeeded())
