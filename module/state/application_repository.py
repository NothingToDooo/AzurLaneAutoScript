import uuid
from collections.abc import Mapping
from typing import TYPE_CHECKING, Final, Protocol, cast, override

from module.application import (
    Blocked,
    Cancelled,
    Deferred,
    DeleteTaskState,
    DisableTask,
    ExecutionMode,
    Faulted,
    RequestAppRestart,
    RescheduleSelf,
    RescheduleTask,
    Retryable,
    RunId,
    RunMetadata,
    RunRepository,
    RunStart,
    StaleRunMetadataError,
    Succeeded,
    TaskId,
    TaskResult,
    UpsertTaskState,
    WakePolicy,
    WakeTask,
)
from module.state.errors import InterruptedRunError, RevisionConflictError, RunStateError
from module.state.models import (
    DeleteTaskStateMutation,
    OutboxMessage,
    RunEvent,
    RunFinalization,
    RunMode,
    RunStatus,
    ScheduleMutation,
    TaskStateMutation,
    UpsertTaskStateMutation,
)
from module.state.store import SQLiteStateStore

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime

    from module.application import RunOutcome, ScheduleEffect, StateEffect
    from module.state.models import JsonValue

_EXECUTION_MODE_TO_RUN_MODE: Final = {
    ExecutionMode.SCHEDULED_JOB: RunMode.SCHEDULED_JOB,
    ExecutionMode.ASSIST_SESSION: RunMode.ASSIST_SESSION,
    ExecutionMode.DIRECT_COMMAND: RunMode.DIRECT_COMMAND,
}
_RUN_FINISHED_TOPIC: Final = "run.finished"
_APP_RESTART_TOPIC: Final = "app.restart.requested"


class RunRepositoryClock(Protocol):
    """运行仓储只依赖墙钟时间。"""

    def now(self) -> datetime: ...


def new_uuid7_run_id() -> RunId:
    return RunId(str(uuid.uuid7()))


def _project_outcome(outcome: RunOutcome) -> tuple[RunStatus, JsonValue, str | None]:
    if isinstance(outcome, Succeeded):
        return RunStatus.SUCCEEDED, None, None
    if isinstance(outcome, Deferred):
        return RunStatus.DEFERRED, {"reason": outcome.reason}, None
    if isinstance(outcome, Retryable):
        return RunStatus.RETRYABLE, {"reason": outcome.reason}, None
    if isinstance(outcome, Blocked):
        return RunStatus.BLOCKED, {"reason": outcome.reason}, None
    if isinstance(outcome, Cancelled):
        return RunStatus.CANCELLED, {"reason": outcome.reason}, None
    if isinstance(outcome, Faulted):
        error_type = type(outcome.error).__name__
        error_message = str(outcome.error)
        error = error_type if not error_message else f"{error_type}: {error_message}"
        return RunStatus.FAULTED, {"error_type": error_type, "message": error_message}, error
    message = f"unsupported run outcome: {type(outcome).__name__}"
    raise TypeError(message)


def _thaw_state_payload(value: object, *, path: str = "$") -> JsonValue:
    if value is None:
        return None
    if type(value) in {bool, int, float, str}:
        return cast("bool | int | float | str", value)
    if type(value) is tuple:
        return [_thaw_state_payload(item, path=f"{path}[{index}]") for index, item in enumerate(value)]
    if isinstance(value, Mapping):
        thawed: dict[str, JsonValue] = {}
        for key, item in value.items():
            if type(key) is not str:
                message = f"state payload object key at {path} must be a string"
                raise TypeError(message)
            thawed[key] = _thaw_state_payload(item, path=f"{path}.{key}")
        return thawed
    message = f"unsupported immutable state payload at {path}: {type(value).__name__}"
    raise TypeError(message)


class SQLiteRunRepository(RunRepository):
    """把 application 运行契约显式翻译为 SQLite 状态事实。"""

    __slots__ = ("_clock", "_run_id_factory", "_schedule_priorities", "_store")

    def __init__(
        self,
        store: SQLiteStateStore,
        schedule_priorities: Mapping[str, int],
        clock: RunRepositoryClock,
        run_id_factory: Callable[[], RunId] = new_uuid7_run_id,
    ) -> None:
        if not isinstance(store, SQLiteStateStore):
            message = "store must be a SQLiteStateStore"
            raise TypeError(message)
        if not callable(run_id_factory):
            message = "run_id_factory must be callable"
            raise TypeError(message)

        priorities: dict[str, int] = {}
        for task_id, priority in schedule_priorities.items():
            normalized_task_id = str(TaskId(task_id))
            if type(priority) is not int:
                message = f"schedule priority must be an integer: {normalized_task_id}"
                raise TypeError(message)
            if priority < 0:
                message = f"schedule priority must not be negative: {normalized_task_id}"
                raise ValueError(message)
            priorities[normalized_task_id] = priority

        self._store = store
        self._schedule_priorities = priorities
        self._clock = clock
        self._run_id_factory = run_id_factory

    @override
    def begin_run(self, task_id: TaskId, mode: ExecutionMode, metadata: RunMetadata) -> RunStart:
        if not isinstance(task_id, TaskId):
            message = "task_id must be a TaskId"
            raise TypeError(message)
        if not isinstance(mode, ExecutionMode):
            message = "mode must be an ExecutionMode"
            raise TypeError(message)
        if not isinstance(metadata, RunMetadata):
            message = "metadata must be a RunMetadata"
            raise TypeError(message)

        run_id = self._run_id_factory()
        if not isinstance(run_id, RunId):
            message = "run_id_factory must return a RunId"
            raise TypeError(message)
        started_at = self._clock.now()
        try:
            self._store.start_run(
                run_id.value,
                task_id.value,
                mode=_EXECUTION_MODE_TO_RUN_MODE[mode],
                settings_revision=metadata.settings_revision,
                content_revision=metadata.content_revision,
                client_ui_revision=metadata.client_ui_revision,
                started_at=started_at,
            )
        except RevisionConflictError as error:
            raise StaleRunMetadataError(
                expected_revision=error.expected_revision,
                actual_revision=error.actual_revision,
            ) from error
        return RunStart(run_id=run_id, started_at=started_at)

    @override
    def finalize_run(self, run_id: RunId, result: TaskResult) -> None:
        if not isinstance(run_id, RunId):
            message = "run_id must be a RunId"
            raise TypeError(message)
        if not isinstance(result, TaskResult):
            message = "result must be a TaskResult"
            raise TypeError(message)

        run = self._store.get_run(run_id.value)
        if run is None:
            message = f"unknown run: {run_id.value}"
            raise RunStateError(message)
        if run.status is not RunStatus.RUNNING:
            message = f"cannot finalize run in {run.status.value} state: {run_id.value}"
            raise RunStateError(message)

        status, result_payload, error = _project_outcome(result.outcome)
        schedule_mutations = self._schedule_mutations(run.task_id, result.effects)
        task_state_mutations = self._task_state_mutations(result.state_effects)
        finished_at = self._clock.now()
        finished_payload: dict[str, JsonValue] = {
            "run_id": run.run_id,
            "task_id": run.task_id,
            "status": status.value,
            "result": result_payload,
        }
        outbox_messages = (
            OutboxMessage(
                message_id=f"{run.run_id}:{_RUN_FINISHED_TOPIC}",
                topic=_RUN_FINISHED_TOPIC,
                key=run.task_id,
                payload=finished_payload,
            ),
            *self._restart_messages(run.run_id, run.task_id, result.effects),
        )
        finalization = RunFinalization(
            status=status,
            finished_at=finished_at,
            result_payload=result_payload,
            error=error,
            schedule_mutations=schedule_mutations,
            task_state_mutations=task_state_mutations,
            events=(RunEvent(kind=_RUN_FINISHED_TOPIC, payload=finished_payload, occurred_at=finished_at),),
            outbox_messages=outbox_messages,
        )
        self._store.finalize_run(run.run_id, finalization)

    @staticmethod
    def _task_state_mutations(effects: tuple[StateEffect, ...]) -> tuple[TaskStateMutation, ...]:
        mutations: list[TaskStateMutation] = []
        for effect in effects:
            if isinstance(effect, UpsertTaskState):
                mutations.append(
                    UpsertTaskStateMutation(
                        namespace=effect.namespace,
                        key=effect.key,
                        schema_version=effect.schema_version,
                        payload=_thaw_state_payload(effect.payload),
                    )
                )
            elif isinstance(effect, DeleteTaskState):
                mutations.append(DeleteTaskStateMutation(namespace=effect.namespace, key=effect.key))
            else:
                message = f"unsupported state effect: {type(effect).__name__}"
                raise TypeError(message)
        return tuple(mutations)

    def recover_interrupted_runs(self, reason: str) -> tuple[RunId, ...]:
        """把上次进程退出遗留的 RUNNING run 收敛为带审计事实的 FAULTED。"""
        if not isinstance(reason, str):
            message = "reason must be a string"
            raise TypeError(message)
        normalized_reason = reason.strip()
        if not normalized_reason:
            message = "reason must not be empty or whitespace"
            raise ValueError(message)

        recovered: list[RunId] = []
        for run in self._store.list_runs(status=RunStatus.RUNNING):
            run_id = RunId(run.run_id)
            self.finalize_run(
                run_id,
                TaskResult(outcome=Faulted(InterruptedRunError(normalized_reason))),
            )
            recovered.append(run_id)
        return tuple(recovered)

    def _schedule_mutations(
        self,
        current_task_id: str,
        effects: tuple[ScheduleEffect, ...],
    ) -> tuple[ScheduleMutation, ...]:
        mutations: list[ScheduleMutation] = []
        for effect in effects:
            mutation: ScheduleMutation | None
            if isinstance(effect, RescheduleSelf):
                mutation = self._reschedule(current_task_id, effect.due_at)
            elif isinstance(effect, RescheduleTask):
                mutation = self._reschedule_existing(effect.task_id.value, effect.due_at)
            elif isinstance(effect, WakeTask):
                mutation = self._wake(effect)
            elif isinstance(effect, DisableTask):
                mutation = self._disable(effect.task_id.value)
            elif isinstance(effect, RequestAppRestart):
                continue
            else:
                message = f"unsupported schedule effect: {type(effect).__name__}"
                raise TypeError(message)
            if mutation is not None:
                mutations.append(mutation)
        return tuple(mutations)

    def _reschedule(self, task_id: str, due_at: datetime) -> ScheduleMutation:
        current = self._store.get_schedule(task_id)
        if current is None:
            return ScheduleMutation(
                task_id=task_id,
                enabled=True,
                due_at=due_at,
                priority=self._priority_for_new_schedule(task_id),
            )
        return ScheduleMutation(
            task_id=task_id,
            enabled=current.enabled,
            due_at=due_at,
            priority=current.priority,
        )

    def _reschedule_existing(self, task_id: str, due_at: datetime) -> ScheduleMutation:
        current = self._store.get_schedule(task_id)
        if current is None:
            message = f"cannot preserve enabled state for missing schedule: {task_id}"
            raise RunStateError(message)
        return ScheduleMutation(
            task_id=task_id,
            enabled=current.enabled,
            due_at=due_at,
            priority=current.priority,
        )

    def _wake(self, effect: WakeTask) -> ScheduleMutation | None:
        task_id = effect.task_id.value
        current = self._store.get_schedule(task_id)
        if effect.enable_policy is WakePolicy.RESPECT_DISABLED and (current is None or not current.enabled):
            return None
        priority = self._priority_for_new_schedule(task_id) if current is None else current.priority
        return ScheduleMutation(task_id=task_id, enabled=True, due_at=effect.due_at, priority=priority)

    def _disable(self, task_id: str) -> ScheduleMutation:
        current = self._store.get_schedule(task_id)
        if current is None:
            return ScheduleMutation(
                task_id=task_id,
                enabled=False,
                due_at=None,
                priority=self._priority_for_new_schedule(task_id),
            )
        return ScheduleMutation(
            task_id=task_id,
            enabled=False,
            due_at=current.due_at,
            priority=current.priority,
        )

    def _priority_for_new_schedule(self, task_id: str) -> int:
        try:
            return self._schedule_priorities[task_id]
        except KeyError as error:
            message = f"missing schedule priority for task: {task_id}"
            raise KeyError(message) from error

    @staticmethod
    def _restart_messages(
        run_id: str,
        task_id: str,
        effects: tuple[ScheduleEffect, ...],
    ) -> tuple[OutboxMessage, ...]:
        return tuple(
            OutboxMessage(
                message_id=f"{run_id}:{_APP_RESTART_TOPIC}",
                topic=_APP_RESTART_TOPIC,
                key=task_id,
                payload={"run_id": run_id, "reason": effect.reason},
            )
            for effect in effects
            if isinstance(effect, RequestAppRestart)
        )
