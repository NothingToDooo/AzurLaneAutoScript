from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol

from module.application import (
    AbortToken,
    Cancelled,
    ExecutionMode,
    ExternalRequestSignal,
    Faulted,
    RequestAppRestart,
    TaskId,
    TaskResult,
)
from module.supervisor import InstanceLoopExit, InstanceLoopExitReason
from module.task_registry import TASK_CATALOG

if TYPE_CHECKING:
    from module.runtime import ConfigurationChangeSignal


class InstanceProcessExitKind(StrEnum):
    FINISHED = "finished"
    STOPPED = "stopped"
    RESTART_REQUESTED = "restart_requested"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class InstanceProcessExit:
    kind: InstanceProcessExitKind
    loop_exit: InstanceLoopExit | None = None
    task_result: TaskResult | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, InstanceProcessExitKind):
            message = "kind must be an InstanceProcessExitKind"
            raise TypeError(message)
        has_loop = self.loop_exit is not None
        has_task = self.task_result is not None
        if has_loop == has_task:
            message = "process exit must contain exactly one loop_exit or task_result"
            raise ValueError(message)
        if has_loop and not isinstance(self.loop_exit, InstanceLoopExit):
            message = "loop_exit must be an InstanceLoopExit or None"
            raise TypeError(message)
        if has_task and not isinstance(self.task_result, TaskResult):
            message = "task_result must be a TaskResult or None"
            raise TypeError(message)


class InstanceRuntimeSession(Protocol):
    def run(self, *, abort: AbortToken | None = None) -> InstanceLoopExit: ...

    def execute(
        self,
        task_id: TaskId,
        mode: ExecutionMode,
        *,
        abort: AbortToken | None = None,
    ) -> TaskResult: ...

    def close(self) -> None: ...


class InstanceRuntimeProvider(Protocol):
    def open(
        self,
        instance_name: str,
        *,
        configuration_signal: ConfigurationChangeSignal | None = None,
    ) -> InstanceRuntimeSession: ...


def _require_identifier(value: str, *, field_name: str) -> None:
    if not isinstance(value, str):
        message = f"{field_name} must be a string"
        raise TypeError(message)
    if not value or value != value.strip() or any(character.isspace() for character in value):
        message = f"{field_name} must be trimmed, non-empty, and contain no whitespace"
        raise ValueError(message)


def _loop_exit_kind(exit_: InstanceLoopExit) -> InstanceProcessExitKind:
    if exit_.reason is InstanceLoopExitReason.RESTART_REQUESTED:
        return InstanceProcessExitKind.RESTART_REQUESTED
    if exit_.reason in {InstanceLoopExitReason.CANCELLED, InstanceLoopExitReason.PREEMPTED}:
        return InstanceProcessExitKind.STOPPED
    if exit_.reason is InstanceLoopExitReason.FAULTED:
        return InstanceProcessExitKind.FAILED
    return InstanceProcessExitKind.FINISHED


def _task_exit_kind(result: TaskResult) -> InstanceProcessExitKind:
    if any(isinstance(effect, RequestAppRestart) for effect in result.effects):
        return InstanceProcessExitKind.RESTART_REQUESTED
    if isinstance(result.outcome, Cancelled):
        return InstanceProcessExitKind.STOPPED
    if isinstance(result.outcome, Faulted):
        return InstanceProcessExitKind.FAILED
    return InstanceProcessExitKind.FINISHED


class InstanceProcessHost:
    """把一个子进程命令映射为唯一的 InstanceRuntime 会话。"""

    __slots__ = ("_provider",)

    def __init__(self, provider: InstanceRuntimeProvider) -> None:
        if isinstance(provider, type) or not callable(getattr(provider, "open", None)):
            message = "provider must implement open()"
            raise TypeError(message)
        self._provider = provider

    def execute(
        self,
        instance_name: str,
        command: str,
        *,
        stop_signal: ExternalRequestSignal | None = None,
        configuration_signal: ConfigurationChangeSignal | None = None,
    ) -> InstanceProcessExit:
        _require_identifier(instance_name, field_name="instance_name")
        _require_identifier(command, field_name="command")
        abort = AbortToken(
            external_signal=stop_signal,
            external_reason="instance process stop requested",
        )
        runtime = self._provider.open(instance_name, configuration_signal=configuration_signal)
        if isinstance(runtime, type) or not all(
            callable(getattr(runtime, method, None)) for method in ("run", "execute", "close")
        ):
            message = "InstanceRuntimeProvider.open() must return an InstanceRuntimeSession"
            raise TypeError(message)
        try:
            if command == "alas":
                loop_exit = runtime.run(abort=abort)
                if not isinstance(loop_exit, InstanceLoopExit):
                    message = "InstanceRuntimeSession.run() must return an InstanceLoopExit"
                    raise TypeError(message)
                return InstanceProcessExit(_loop_exit_kind(loop_exit), loop_exit=loop_exit)

            definition = TASK_CATALOG.get(command)
            if definition is None:
                message = f"unknown process command: {command}"
                raise LookupError(message)
            if definition.execution_mode is ExecutionMode.SCHEDULED_JOB:
                message = f"scheduled task cannot be launched as a direct process command: {command}"
                raise ValueError(message)
            result = runtime.execute(
                TaskId(command),
                definition.execution_mode,
                abort=abort,
            )
            if not isinstance(result, TaskResult):
                message = "InstanceRuntimeSession.execute() must return a TaskResult"
                raise TypeError(message)
            return InstanceProcessExit(_task_exit_kind(result), task_result=result)
        finally:
            runtime.close()
