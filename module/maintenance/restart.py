from dataclasses import dataclass
from typing import TYPE_CHECKING, override

from module.application import DailySchedule, RescheduleSelf, Succeeded, Task, TaskContext, TaskResult

if TYPE_CHECKING:
    from module.interaction import AppLifecycle
    from module.maintenance.game_manager import LoginFlow


@dataclass(frozen=True, slots=True)
class RestartSettings:
    schedule: DailySchedule

    def __post_init__(self) -> None:
        if not isinstance(self.schedule, DailySchedule):
            message = "schedule must be a DailySchedule"
            raise TypeError(message)


class RestartTask(Task):
    __slots__ = ("_app", "_login", "_settings")

    def __init__(self, app: AppLifecycle, login: LoginFlow, settings: RestartSettings) -> None:
        if not isinstance(settings, RestartSettings):
            message = "settings must be RestartSettings"
            raise TypeError(message)
        self._app = app
        self._login = login
        self._settings = settings

    @override
    def run(self, context: TaskContext) -> TaskResult:
        context.abort.raise_if_requested()
        self._app.stop(context.abort)
        context.abort.raise_if_requested()
        self._app.start(context.abort)
        context.abort.raise_if_requested()
        self._login.ensure_logged_in(context.abort)
        context.abort.raise_if_requested()
        return TaskResult(
            outcome=Succeeded(),
            effects=(RescheduleSelf(self._settings.schedule.next_after(context.started_at)),),
        )
