from dataclasses import dataclass, field
from typing import cast

import pytest

import module.bootstrap.process_host as process_host_module
from module.application import (
    AbortToken,
    Cancelled,
    ExecutionMode,
    Faulted,
    RequestAppRestart,
    Succeeded,
    TaskId,
    TaskResult,
)
from module.bootstrap import (
    InstanceProcessExitKind,
    InstanceProcessHost,
    InstanceRuntimeProvider,
    InstanceRuntimeSession,
)
from module.supervisor import InstanceLoopExit, InstanceLoopExitReason


class _StopSignal:
    def __init__(self, *, requested: bool = False) -> None:
        self.requested = requested

    def is_set(self) -> bool:
        return self.requested


class _ConfigurationSignal:
    @staticmethod
    def wait(timeout: float) -> bool:
        del timeout
        return False

    @staticmethod
    def clear() -> None:
        pass


@dataclass(slots=True)
class _Runtime:
    loop_exit: InstanceLoopExit = field(
        default_factory=lambda: InstanceLoopExit(InstanceLoopExitReason.EMPTY, 0),
    )
    task_result: TaskResult = field(default_factory=lambda: TaskResult(Succeeded()))
    run_aborts: list[AbortToken] = field(default_factory=list)
    execute_calls: list[tuple[TaskId, ExecutionMode, AbortToken]] = field(default_factory=list)
    close_calls: int = 0

    def run(self, *, abort: AbortToken | None = None) -> InstanceLoopExit:
        self.run_aborts.append(cast("AbortToken", abort))
        return self.loop_exit

    def execute(
        self,
        task_id: TaskId,
        mode: ExecutionMode,
        *,
        abort: AbortToken | None = None,
    ) -> TaskResult:
        self.execute_calls.append((task_id, mode, cast("AbortToken", abort)))
        return self.task_result

    def close(self) -> None:
        self.close_calls += 1


@dataclass(slots=True)
class _Provider:
    runtime: _Runtime
    opened: list[str] = field(default_factory=list)
    configuration_signals: list[object | None] = field(default_factory=list)

    def open(
        self,
        instance_name: str,
        *,
        configuration_signal: object | None = None,
    ) -> InstanceRuntimeSession:
        self.opened.append(instance_name)
        self.configuration_signals.append(configuration_signal)
        return self.runtime


@dataclass(slots=True)
class _FailureReporter:
    calls: list[tuple[str, str, type[Exception]]] = field(default_factory=list)
    fail: bool = False

    def report(self, instance_name: str, command: str, error: Exception) -> None:
        self.calls.append((instance_name, command, type(error)))
        if self.fail:
            message = "reporter failed"
            raise RuntimeError(message)


@dataclass(slots=True)
class _NotificationResources:
    fail_close: bool = False
    close_calls: int = 0

    def close(self) -> None:
        self.close_calls += 1
        if self.fail_close:
            message = "close failed"
            raise RuntimeError(message)


@pytest.mark.parametrize(
    ("reason", "expected"),
    [
        (InstanceLoopExitReason.EMPTY, InstanceProcessExitKind.FINISHED),
        (InstanceLoopExitReason.CANCELLED, InstanceProcessExitKind.STOPPED),
        (InstanceLoopExitReason.PREEMPTED, InstanceProcessExitKind.STOPPED),
        (InstanceLoopExitReason.RESTART_REQUESTED, InstanceProcessExitKind.RESTART_REQUESTED),
        (InstanceLoopExitReason.FAULTED, InstanceProcessExitKind.FAILED),
    ],
)
def test_scheduler_command_uses_one_runtime_and_maps_loop_exit(
    reason: InstanceLoopExitReason,
    expected: InstanceProcessExitKind,
) -> None:
    runtime = _Runtime(loop_exit=InstanceLoopExit(reason, 0))
    provider = _Provider(runtime)

    exit_ = InstanceProcessHost(provider).execute("alas", "alas")

    assert exit_.kind is expected
    assert exit_.loop_exit is runtime.loop_exit
    assert exit_.task_result is None
    assert provider.opened == ["alas"]
    assert len(runtime.run_aborts) == 1
    assert runtime.close_calls == 1


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        (TaskResult(Succeeded()), InstanceProcessExitKind.FINISHED),
        (TaskResult(Cancelled("stopped")), InstanceProcessExitKind.STOPPED),
        (TaskResult(Faulted(RuntimeError("failed"))), InstanceProcessExitKind.FAILED),
        (
            TaskResult(Succeeded(), effects=(RequestAppRestart("client update"),)),
            InstanceProcessExitKind.RESTART_REQUESTED,
        ),
    ],
)
def test_direct_command_uses_catalog_execution_mode_and_maps_result(
    result: TaskResult,
    expected: InstanceProcessExitKind,
) -> None:
    runtime = _Runtime(task_result=result)

    exit_ = InstanceProcessHost(_Provider(runtime)).execute("alas", "benchmark")

    assert exit_.kind is expected
    assert exit_.task_result is result
    assert runtime.execute_calls[0][0] == TaskId("benchmark")
    assert runtime.execute_calls[0][1] is ExecutionMode.DIRECT_COMMAND
    assert runtime.close_calls == 1


def test_external_stop_signal_is_linked_to_abort_token_before_io() -> None:
    runtime = _Runtime()
    stop = _StopSignal(requested=True)

    InstanceProcessHost(_Provider(runtime)).execute("alas", "alas", stop_signal=stop)

    assert runtime.run_aborts[0].is_requested
    assert runtime.run_aborts[0].reason == "instance process stop requested"


def test_configuration_signal_is_forwarded_to_runtime_provider() -> None:
    runtime = _Runtime()
    provider = _Provider(runtime)
    signal = _ConfigurationSignal()

    InstanceProcessHost(provider).execute("alas", "alas", configuration_signal=signal)

    assert provider.configuration_signals == [signal]


@pytest.mark.parametrize("command", ["missing", "restart"])
def test_invalid_direct_command_is_rejected_before_runtime_open_and_not_reported(command: str) -> None:
    runtime = _Runtime()
    provider = _Provider(runtime)
    reporter = _FailureReporter()
    resources = _NotificationResources()
    host = InstanceProcessHost(
        provider,
        failure_reporter=reporter,
        notification_resources=resources,
    )

    with pytest.raises((LookupError, ValueError)):
        host.execute("alas", command)

    assert provider.opened == []
    assert runtime.close_calls == 0
    assert reporter.calls == []
    assert resources.close_calls == 0


def test_invalid_provider_result_fails_before_execution() -> None:
    class _InvalidProvider:
        @staticmethod
        def open(instance_name: str, *, configuration_signal: object | None = None) -> object:
            del instance_name, configuration_signal
            return object()

    with pytest.raises(TypeError, match="InstanceRuntimeSession"):
        InstanceProcessHost(cast("InstanceRuntimeProvider", _InvalidProvider())).execute("alas", "alas")


def test_unhandled_process_failure_is_reported_and_the_original_error_is_preserved() -> None:
    class _FailingProvider:
        @staticmethod
        def open(instance_name: str, *, configuration_signal: object | None = None) -> object:
            del instance_name, configuration_signal
            message = "bundle initialization failed"
            raise RuntimeError(message)

    reporter = _FailureReporter()

    with pytest.raises(RuntimeError, match="bundle initialization failed"):
        InstanceProcessHost(
            cast("InstanceRuntimeProvider", _FailingProvider()),
            failure_reporter=reporter,
        ).execute("alas", "alas")

    assert reporter.calls == [("alas", "alas", RuntimeError)]


def test_failure_reporter_error_is_logged_and_never_replaces_the_process_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FailingProvider:
        @staticmethod
        def open(instance_name: str, *, configuration_signal: object | None = None) -> object:
            del instance_name, configuration_signal
            message = "original process error"
            raise RuntimeError(message)

    logged: list[Exception] = []
    monkeypatch.setattr(process_host_module.logger, "exception", logged.append)

    with pytest.raises(RuntimeError, match="original process error"):
        InstanceProcessHost(
            cast("InstanceRuntimeProvider", _FailingProvider()),
            failure_reporter=_FailureReporter(fail=True),
        ).execute("alas", "alas")

    assert len(logged) == 1
    assert str(logged[0]) == "reporter failed"


def test_faulted_task_result_is_not_reported_twice_by_the_process_host() -> None:
    reporter = _FailureReporter()
    runtime = _Runtime(task_result=TaskResult(Faulted(RuntimeError("failed"))))

    exit_ = InstanceProcessHost(_Provider(runtime), failure_reporter=reporter).execute("alas", "benchmark")

    assert exit_.kind is InstanceProcessExitKind.FAILED
    assert reporter.calls == []


def test_process_failure_is_enqueued_without_synchronous_notification_maintenance() -> None:
    class _FailingProvider:
        @staticmethod
        def open(instance_name: str, *, configuration_signal: object | None = None) -> object:
            del instance_name, configuration_signal
            message = "bundle initialization failed"
            raise RuntimeError(message)

    reporter = _FailureReporter()
    resources = _NotificationResources()
    host = InstanceProcessHost(
        cast("InstanceRuntimeProvider", _FailingProvider()),
        failure_reporter=reporter,
        notification_resources=resources,
    )

    with pytest.raises(RuntimeError, match="bundle initialization failed"):
        host.execute("alas", "alas")

    assert reporter.calls == [("alas", "alas", RuntimeError)]
    assert resources.close_calls == 0
    host.close()
    assert resources.close_calls == 1


def test_notification_resource_close_failure_is_logged_without_changing_the_process_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resources = _NotificationResources(fail_close=True)
    host = InstanceProcessHost(_Provider(_Runtime()), notification_resources=resources)
    logged: list[Exception] = []
    monkeypatch.setattr(process_host_module.logger, "exception", logged.append)

    exit_ = host.execute("alas", "alas")
    host.close()

    assert exit_.kind is InstanceProcessExitKind.FINISHED
    assert resources.close_calls == 1
    assert len(logged) == 1
    assert str(logged[0]) == "close failed"


def test_process_host_context_closes_notification_resources_once() -> None:
    resources = _NotificationResources()
    host = InstanceProcessHost(_Provider(_Runtime()), notification_resources=resources)

    with host:
        host.execute("alas", "alas")
    host.close()

    assert resources.close_calls == 1
    with pytest.raises(RuntimeError, match="process host is closed"):
        host.execute("alas", "alas")
