from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol, Self

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
from module.logger import logger
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


class ProcessFailureReporter(Protocol):
    def report(self, instance_name: str, command: str, error: Exception) -> None: ...


class ProcessNotificationResources(Protocol):
    def close(self) -> None: ...


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


def _command_execution_mode(command: str) -> ExecutionMode | None:
    if command == "alas":
        return None
    definition = TASK_CATALOG.get(command)
    if definition is None:
        message = f"unknown process command: {command}"
        raise LookupError(message)
    if definition.execution_mode is ExecutionMode.SCHEDULED_JOB:
        message = f"scheduled task cannot be launched as a direct process command: {command}"
        raise ValueError(message)
    return definition.execution_mode


class InstanceProcessHost:
    """把一个子进程命令映射为唯一的 InstanceRuntime 会话。"""

    __slots__ = ("_closed", "_failure_reporter", "_notification_resources", "_provider")

    def __init__(
        self,
        provider: InstanceRuntimeProvider,
        *,
        failure_reporter: ProcessFailureReporter | None = None,
        notification_resources: ProcessNotificationResources | None = None,
    ) -> None:
        if isinstance(provider, type) or not callable(getattr(provider, "open", None)):
            message = "provider must implement open()"
            raise TypeError(message)
        if failure_reporter is not None and (
            isinstance(failure_reporter, type) or not callable(getattr(failure_reporter, "report", None))
        ):
            message = "failure_reporter must implement report() or be None"
            raise TypeError(message)
        if notification_resources is not None and (
            isinstance(notification_resources, type) or not callable(getattr(notification_resources, "close", None))
        ):
            message = "notification_resources must implement close() or be None"
            raise TypeError(message)
        self._provider = provider
        self._failure_reporter = failure_reporter
        self._notification_resources = notification_resources
        self._closed = False

    def __enter__(self) -> Self:
        self._require_open()
        return self

    def __exit__(self, *args: object) -> None:
        del args
        self.close()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._notification_resources is None:
            return
        try:
            self._notification_resources.close()
        except Exception as close_error:  # noqa: BLE001 - 通知资源清理不能改写进程结果。
            logger.error(f"Notification spool close failed ({type(close_error).__name__})")

    def execute(
        self,
        instance_name: str,
        command: str,
        *,
        stop_signal: ExternalRequestSignal | None = None,
        configuration_signal: ConfigurationChangeSignal | None = None,
    ) -> InstanceProcessExit:
        self._require_open()
        _require_identifier(instance_name, field_name="instance_name")
        _require_identifier(command, field_name="command")
        execution_mode = _command_execution_mode(command)
        abort = AbortToken(
            external_signal=stop_signal,
            external_reason="instance process stop requested",
        )
        try:
            result = self._execute_validated(
                instance_name,
                command,
                execution_mode,
                abort,
                configuration_signal,
            )
        except Exception as error:
            self._report_failure(instance_name, command, error)
            raise
        return result

    def _execute_validated(
        self,
        instance_name: str,
        command: str,
        execution_mode: ExecutionMode | None,
        abort: AbortToken,
        configuration_signal: ConfigurationChangeSignal | None,
    ) -> InstanceProcessExit:
        runtime = self._provider.open(instance_name, configuration_signal=configuration_signal)
        if isinstance(runtime, type) or not all(
            callable(getattr(runtime, method, None)) for method in ("run", "execute", "close")
        ):
            message = "InstanceRuntimeProvider.open() must return an InstanceRuntimeSession"
            raise TypeError(message)
        try:
            return self._execute_open_runtime(runtime, command, execution_mode, abort)
        finally:
            runtime.close()

    @staticmethod
    def _execute_open_runtime(
        runtime: InstanceRuntimeSession,
        command: str,
        execution_mode: ExecutionMode | None,
        abort: AbortToken,
    ) -> InstanceProcessExit:
        if execution_mode is None:
            loop_exit = runtime.run(abort=abort)
            if not isinstance(loop_exit, InstanceLoopExit):
                message = "InstanceRuntimeSession.run() must return an InstanceLoopExit"
                raise TypeError(message)
            return InstanceProcessExit(_loop_exit_kind(loop_exit), loop_exit=loop_exit)

        result = runtime.execute(
            TaskId(command),
            execution_mode,
            abort=abort,
        )
        if not isinstance(result, TaskResult):
            message = "InstanceRuntimeSession.execute() must return a TaskResult"
            raise TypeError(message)
        return InstanceProcessExit(_task_exit_kind(result), task_result=result)

    def _report_failure(self, instance_name: str, command: str, error: Exception) -> None:
        if self._failure_reporter is None:
            return
        try:
            self._failure_reporter.report(instance_name, command, error)
        except Exception as reporter_error:  # noqa: BLE001 - 旁路 reporter 不能替换原始进程异常。
            logger.error(f"Process failure reporter failed ({type(reporter_error).__name__})")

    def _require_open(self) -> None:
        if self._closed:
            message = "instance process host is closed"
            raise RuntimeError(message)
