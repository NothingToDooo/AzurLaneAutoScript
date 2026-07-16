from dataclasses import dataclass
from typing import Protocol, override

from module.application import CancellationSource, Succeeded, Task, TaskContext, TaskResult


class AppLifecycle(Protocol):
    def start(self, cancellation: CancellationSource) -> None: ...

    def stop(self, cancellation: CancellationSource) -> None: ...


class LoginFlow(Protocol):
    def ensure_logged_in(self, cancellation: CancellationSource) -> None: ...


@dataclass(frozen=True, slots=True)
class GameManagerSettings:
    auto_restart: bool

    def __post_init__(self) -> None:
        if type(self.auto_restart) is not bool:
            message = "auto_restart must be a bool"
            raise TypeError(message)


class GameManagerTask(Task):
    __slots__ = ("_app", "_login", "_settings")

    def __init__(self, app: AppLifecycle, login: LoginFlow, settings: GameManagerSettings) -> None:
        if not isinstance(settings, GameManagerSettings):
            message = "settings must be GameManagerSettings"
            raise TypeError(message)
        self._app = app
        self._login = login
        self._settings = settings

    @override
    def run(self, context: TaskContext) -> TaskResult:
        context.abort.raise_if_requested()
        self._app.stop(context.abort)
        if self._settings.auto_restart:
            context.abort.raise_if_requested()
            self._app.start(context.abort)
            context.abort.raise_if_requested()
            self._login.ensure_logged_in(context.abort)
        return TaskResult(outcome=Succeeded())
