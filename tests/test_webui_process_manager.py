import queue
import threading
from datetime import UTC, datetime
from multiprocessing.reduction import ForkingPickler
from typing import TYPE_CHECKING, Protocol, cast, override

import pytest
from rich.text import Text

import module.webui.process_manager as process_manager_module
from module.runtime.runner import CommandOutcome, CommandStatus
from module.webui.process_manager import (
    KILL_JOIN_SECONDS,
    ProcessManager,
    RenderableQueueItem,
    _ProcessRequest,  # ruff:ignore[import-private-name] - 子进程序列化契约需要直接验证。
    _ProcessRun,  # ruff:ignore[import-private-name] - 进程生命周期状态需要直接构造。
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from multiprocessing import Process
    from multiprocessing.queues import Queue as ProcessQueue

    from module.base.stop_event import StopEvent


class _StopEventLike(Protocol):
    def set(self) -> None: ...

    def is_set(self) -> bool: ...


class _StopEvent:
    def __init__(self, *, is_set: bool = False) -> None:
        self.set_calls = int(is_set)

    def set(self) -> None:
        self.set_calls += 1

    def is_set(self) -> bool:
        return self.set_calls > 0


class _FailingStopEvent(_StopEvent):
    @override
    def set(self) -> None:
        message = "stop signal failed"
        raise RuntimeError(message)


class _Process:
    def __init__(
        self,
        *,
        exits_on_join: bool = False,
        exits_on_kill: bool = True,
        alive: bool = True,
        exitcode: int | None = 0,
    ) -> None:
        self._alive = alive
        self.exitcode = exitcode
        self.exits_on_join = exits_on_join
        self.exits_on_kill = exits_on_kill
        self.join_calls: list[float | None] = []
        self.kill_calls = 0

    @staticmethod
    def start() -> None:
        return None

    def is_alive(self) -> bool:
        return self._alive

    def join(self, timeout: float | None = None) -> None:
        self.join_calls.append(timeout)
        if self.exits_on_join:
            self._alive = False

    def kill(self) -> None:
        self.kill_calls += 1
        if self.exits_on_kill:
            self._alive = False


class _BlockingProcess(_Process):
    def __init__(self) -> None:
        super().__init__()
        self.blocking_join_started = threading.Event()
        self.killed = threading.Event()

    def join(self, timeout: float | None = None) -> None:
        self.join_calls.append(timeout)
        if timeout is None:
            self.blocking_join_started.set()
            if not self.killed.wait(timeout=2):
                message = "test process was not released"
                raise TimeoutError(message)
        self._alive = not self.killed.is_set()

    def kill(self) -> None:
        self.kill_calls += 1
        self.killed.set()
        self._alive = False


class _ExitBeforeWaitCompletesProcess(_Process):
    def __init__(self) -> None:
        super().__init__()
        self.exited = threading.Event()
        self.release_waiter = threading.Event()

    def join(self, timeout: float | None = None) -> None:
        self.join_calls.append(timeout)
        self._alive = False
        self.exited.set()
        if not self.release_waiter.wait(timeout=2):
            message = "test stop waiter was not released"
            raise TimeoutError(message)


class _JoinFailureProcess(_Process):
    def join(self, timeout: float | None = None) -> None:
        self.join_calls.append(timeout)
        message = "join failed"
        raise RuntimeError(message)


def _outcome(
    status: CommandStatus,
    *,
    command: str = "alas",
    exception_type: str | None = None,
    message: str | None = None,
) -> CommandOutcome:
    return CommandOutcome(
        command=command,
        status=status,
        finished_at=datetime.now(UTC),
        exception_type=exception_type,
        message=message,
    )


def _request(command: str) -> _ProcessRequest:
    return _ProcessRequest(command)


@pytest.fixture(autouse=True)
def _reset_process_manager_singleton() -> None:
    ProcessManager._singleton = None  # ruff:ignore[private-member-access] - 每个测试需要隔离唯一进程管理器。


def _attach_run(
    manager: ProcessManager,
    process: _Process,
    *,
    stop_event: _StopEventLike | None = None,
    outcome: CommandOutcome | None = None,
) -> _ProcessRun:
    renderable_queue: queue.Queue[RenderableQueueItem] = queue.Queue()
    outcome_queue: queue.Queue[CommandOutcome] = queue.Queue()
    if outcome is not None:
        outcome_queue.put(outcome)
    run = _ProcessRun(
        command="alas",
        process=cast("Process", process),
        renderable_queue=cast("ProcessQueue[RenderableQueueItem]", renderable_queue),
        outcome_queue=cast("ProcessQueue[CommandOutcome]", outcome_queue),
        stop_event=_StopEvent() if stop_event is None else stop_event,
    )
    vars(manager).update(
        {
            "_run": run,
        },
    )
    return run


def _patch_process_boundary(monkeypatch: pytest.MonkeyPatch, calls: list[tuple[object, ...]]) -> None:
    class _Logger:
        @staticmethod
        def critical(message: object) -> None:
            calls.append(("critical", message))

        @staticmethod
        def exception(error: BaseException) -> None:
            calls.append(("exception", str(error)))

        @staticmethod
        def info(message: object) -> None:
            calls.append(("info", message))

        @staticmethod
        def warning(message: object) -> None:
            calls.append(("warning", message))

        @staticmethod
        def hr(message: object) -> None:
            calls.append(("hr", message))

    monkeypatch.setattr(
        process_manager_module,
        "chdir",
        lambda root: calls.append(("chdir", root)),
        raising=False,
    )
    monkeypatch.setattr(
        process_manager_module,
        "configure_file_logging",
        lambda root, *, name: calls.append(("configure_file_logging", root, name)),
        raising=False,
    )
    monkeypatch.setattr(
        process_manager_module,
        "set_func_logger",
        lambda *, func: calls.append(("set_func_logger", func)),
    )
    monkeypatch.setattr(process_manager_module, "logger", _Logger())


def test_command_outcome_and_request_cross_spawn_boundary() -> None:
    request = _request("Benchmark")
    outcome = _outcome(CommandStatus.FINISHED, command="benchmark")

    assert ForkingPickler.loads(ForkingPickler.dumps(request)) == request
    assert ForkingPickler.loads(ForkingPickler.dumps(outcome)) == outcome


@pytest.mark.parametrize(
    ("ui_command", "runtime_command"),
    [
        ("alas", "alas"),
        ("Benchmark", "benchmark"),
        ("GameManager", "game_manager"),
    ],
)
def test_execute_process_delegates_to_default_command(
    monkeypatch: pytest.MonkeyPatch,
    ui_command: str,
    runtime_command: str,
) -> None:
    calls: list[tuple[str, object | None]] = []
    stop_event = _StopEvent()
    expected = _outcome(CommandStatus.FINISHED, command=runtime_command)

    def run(
        command: str,
        *,
        project_root: object | None = None,
        stop_signal: object | None = None,
    ) -> CommandOutcome:
        assert project_root is None
        calls.append((command, stop_signal))
        return expected

    monkeypatch.setattr("module.bootstrap.production.run_default_command", run)

    actual = process_manager_module._execute_process(  # ruff:ignore[private-member-access] - 验证命令解析边界。
        _request(ui_command),
        cast("StopEvent", stop_event),
    )

    assert actual is expected
    assert calls == [(runtime_command, stop_event)]


def test_execute_process_rejects_unknown_ui_command(monkeypatch: pytest.MonkeyPatch) -> None:
    critical: list[str] = []
    monkeypatch.setattr(process_manager_module.logger, "critical", critical.append)

    outcome = process_manager_module._execute_process(  # ruff:ignore[private-member-access] - 验证命令解析边界。
        _request("Main"),
        None,
    )

    assert outcome.status is CommandStatus.FAILED
    assert outcome.exception_type == "LookupError"
    assert outcome.message == "No function matched: Main"
    assert critical == ["No function matched: Main"]


def test_run_process_publishes_default_command_outcome(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[object, ...]] = []
    expected = _outcome(CommandStatus.FINISHED)
    renderable_queue: queue.Queue[RenderableQueueItem] = queue.Queue()
    outcome_queue: queue.Queue[CommandOutcome] = queue.Queue()
    _patch_process_boundary(monkeypatch, calls)

    def execute(request: _ProcessRequest, stop_event: StopEvent | None) -> CommandOutcome:
        del request, stop_event
        calls.append(("execute",))
        return expected

    monkeypatch.setattr(process_manager_module, "_execute_process", execute)

    ProcessManager.run_process(_request("alas"), renderable_queue, outcome_queue)

    assert outcome_queue.get_nowait() is expected
    assert renderable_queue.get_nowait() is None
    assert calls[:4] == [
        ("chdir", process_manager_module.PROJECT_ROOT),
        ("configure_file_logging", process_manager_module.PROJECT_ROOT, "alas"),
        ("set_func_logger", renderable_queue.put),
        ("execute",),
    ]
    assert ("info", "[alas] exited. Reason: finished\n") in calls


def test_run_process_converts_unexpected_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[object, ...]] = []
    renderable_queue: queue.Queue[RenderableQueueItem] = queue.Queue()
    outcome_queue: queue.Queue[CommandOutcome] = queue.Queue()
    _patch_process_boundary(monkeypatch, calls)

    def fail(request: _ProcessRequest, stop_event: StopEvent | None) -> CommandOutcome:
        del request, stop_event
        message = "first line\nsecond line"
        raise ValueError(message)

    monkeypatch.setattr(process_manager_module, "_execute_process", fail)

    ProcessManager.run_process(_request("alas"), renderable_queue, outcome_queue)

    outcome = outcome_queue.get_nowait()
    assert outcome.status is CommandStatus.FAILED
    assert outcome.exception_type == "ValueError"
    assert outcome.message == "first line second line"
    assert ("exception", "first line\nsecond line") in calls
    assert renderable_queue.get_nowait() is None


@pytest.mark.parametrize(
    ("code", "stopped", "status"),
    [
        (0, False, CommandStatus.FINISHED),
        (7, False, CommandStatus.FAILED),
        (7, True, CommandStatus.STOPPED),
    ],
)
def test_run_process_publishes_outcome_before_reraising_system_exit(
    monkeypatch: pytest.MonkeyPatch,
    code: int,
    status: CommandStatus,
    *,
    stopped: bool,
) -> None:
    calls: list[tuple[object, ...]] = []
    renderable_queue: queue.Queue[RenderableQueueItem] = queue.Queue()
    outcome_queue: queue.Queue[CommandOutcome] = queue.Queue()
    stop_event = _StopEvent(is_set=stopped)
    _patch_process_boundary(monkeypatch, calls)

    def exit_process(request: _ProcessRequest, event: StopEvent | None) -> CommandOutcome:
        del request, event
        raise SystemExit(code)

    monkeypatch.setattr(process_manager_module, "_execute_process", exit_process)

    with pytest.raises(SystemExit, match=str(code)):
        ProcessManager.run_process(
            _request("alas"),
            renderable_queue,
            outcome_queue,
            cast("StopEvent", stop_event),
        )

    assert outcome_queue.get_nowait().status is status
    assert renderable_queue.get_nowait() is None


def test_run_process_publishes_base_exception_group_before_reraising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[object, ...]] = []
    renderable_queue: queue.Queue[RenderableQueueItem] = queue.Queue()
    outcome_queue: queue.Queue[CommandOutcome] = queue.Queue()
    error = BaseExceptionGroup("exit and cleanup failed", (SystemExit(7), OSError("cleanup")))
    _patch_process_boundary(monkeypatch, calls)

    def fail(request: _ProcessRequest, stop_event: StopEvent | None) -> CommandOutcome:
        del request, stop_event
        raise error

    monkeypatch.setattr(process_manager_module, "_execute_process", fail)

    with pytest.raises(BaseExceptionGroup) as raised:
        ProcessManager.run_process(_request("alas"), renderable_queue, outcome_queue)

    assert raised.value is error
    outcome = outcome_queue.get_nowait()
    assert outcome.status is CommandStatus.FAILED
    assert outcome.exception_type == "BaseExceptionGroup"
    assert renderable_queue.get_nowait() is None


def test_start_uses_fresh_ipc_resources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created_events: list[_StopEvent] = []
    process_targets: list[Callable[..., None]] = []
    process_args: list[tuple[object, ...]] = []
    monitor_runs: list[_ProcessRun | None] = []

    class _StartedProcess:
        exitcode = 0

        def __init__(self, target: Callable[..., None], args: tuple[object, ...]) -> None:
            process_targets.append(target)
            process_args.append(args)

        @staticmethod
        def start() -> None:
            return None

        @staticmethod
        def is_alive() -> bool:
            return False

    def create_event() -> _StopEvent:
        event = _StopEvent()
        created_events.append(event)
        return event

    class _ProcessContext:
        Queue = staticmethod(queue.Queue)
        Event = staticmethod(create_event)
        Process = _StartedProcess

    def capture_monitor(manager: ProcessManager, run: _ProcessRun | None = None) -> None:
        del manager
        monitor_runs.append(run)

    monkeypatch.setattr(
        process_manager_module.multiprocessing,
        "get_context",
        lambda method: _ProcessContext() if method == "spawn" else pytest.fail(f"Unexpected context: {method}"),
    )
    monkeypatch.setattr(ProcessManager, "start_log_queue_handler", capture_monitor)
    manager = ProcessManager()

    manager.start_default()
    manager.start("Benchmark")

    assert process_targets == [ProcessManager.run_process, ProcessManager.run_process]
    assert len(process_args) == 2
    assert process_args[0][0] == _request("alas")
    assert process_args[1][0] == _request("Benchmark")
    assert process_args[0][1] is not process_args[1][1]
    assert process_args[0][2] is not process_args[1][2]
    assert process_args[0][3] is created_events[0]
    assert process_args[1][3] is created_events[1]
    assert all(len(args) == 4 for args in process_args)
    assert monitor_runs[0] is not monitor_runs[1]


def test_request_stop_is_non_blocking_and_never_kills() -> None:
    stop_event = _StopEvent()
    process = _Process()
    manager = ProcessManager()
    run = _attach_run(manager, process, stop_event=stop_event)

    manager.request_stop()
    manager.request_stop()

    assert stop_event.set_calls == 1
    assert process.join_calls == []
    assert process.kill_calls == 0
    assert run.stop_requested
    assert not run.forced


def test_stop_and_wait_reports_stopped_when_process_exits_gracefully() -> None:
    stop_event = _StopEvent()
    process = _Process(exits_on_join=True)
    manager = ProcessManager()
    _attach_run(
        manager,
        process,
        stop_event=stop_event,
        outcome=_outcome(CommandStatus.FINISHED),
    )

    manager.stop_and_wait()

    assert stop_event.set_calls == 1
    assert process.join_calls == [None]
    assert process.kill_calls == 0
    assert manager.outcome is not None
    assert manager.outcome.status is CommandStatus.STOPPED


def test_stop_and_wait_preserves_child_failure() -> None:
    process = _Process(exits_on_join=True)
    manager = ProcessManager()
    _attach_run(
        manager,
        process,
        outcome=_outcome(CommandStatus.FAILED, exception_type="RuntimeError", message="checkpoint failed"),
    )

    manager.stop_and_wait()

    assert manager.outcome is not None
    assert manager.outcome.status is CommandStatus.FAILED
    assert manager.outcome.message == "checkpoint failed"


def test_force_stop_reports_killed() -> None:
    stop_event = _StopEvent()
    process = _Process()
    manager = ProcessManager()
    run = _attach_run(manager, process, stop_event=stop_event)

    manager.force_stop()

    assert stop_event.set_calls == 1
    assert process.join_calls == [KILL_JOIN_SECONDS]
    assert process.kill_calls == 1
    assert run.stop_requested
    assert run.forced
    assert manager.outcome is not None
    assert manager.outcome.status is CommandStatus.KILLED


def test_force_stop_fails_when_process_remains_alive_after_kill() -> None:
    process = _Process(exits_on_kill=False)
    manager = ProcessManager()
    _attach_run(manager, process)

    with pytest.raises(RuntimeError, match="still alive after kill"):
        manager.force_stop()

    assert process.join_calls == [KILL_JOIN_SECONDS]
    assert process.kill_calls == 1
    assert process.is_alive()


def test_force_stop_remains_available_while_cooperative_wait_is_blocked() -> None:
    process = _BlockingProcess()
    manager = ProcessManager()
    _attach_run(manager, process)
    waiter = threading.Thread(target=manager.stop_and_wait)

    waiter.start()
    assert process.blocking_join_started.wait(timeout=1)

    manager.force_stop()
    waiter.join(timeout=1)

    assert not waiter.is_alive()
    assert process.kill_calls == 1
    assert process.join_calls == [None, KILL_JOIN_SECONDS]
    assert manager.outcome is not None
    assert manager.outcome.status is CommandStatus.KILLED


def test_start_waits_until_blocking_stop_releases_the_previous_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = _ExitBeforeWaitCompletesProcess()
    manager = ProcessManager()
    old_run = _attach_run(manager, process, outcome=_outcome(CommandStatus.FINISHED))
    context_calls: list[str] = []
    process_args: list[tuple[object, ...]] = []

    class _StartedProcess:
        exitcode = 0

        def __init__(self, target: Callable[..., None], args: tuple[object, ...]) -> None:
            del target
            process_args.append(args)

        @staticmethod
        def start() -> None:
            return None

        @staticmethod
        def is_alive() -> bool:
            return False

    class _ProcessContext:
        Queue = staticmethod(queue.Queue)
        Event = staticmethod(_StopEvent)
        Process = _StartedProcess

    def process_context(method: str) -> _ProcessContext:
        context_calls.append(method)
        return _ProcessContext()

    monkeypatch.setattr(process_manager_module.multiprocessing, "get_context", process_context)
    monkeypatch.setattr(ProcessManager, "start_log_queue_handler", lambda *_args: None)
    waiter_errors: list[BaseException] = []

    def wait_for_stop() -> None:
        try:
            manager.stop_and_wait()
        except BaseException as error:  # ruff:ignore[blind-except] - 线程异常必须回传主测试。
            waiter_errors.append(error)

    waiter = threading.Thread(target=wait_for_stop)
    waiter.start()
    assert process.exited.wait(timeout=1)

    manager.start("Benchmark")

    assert context_calls == []
    assert vars(manager)["_run"] is old_run

    process.release_waiter.set()
    waiter.join(timeout=2)
    assert not waiter.is_alive()
    assert waiter_errors == []

    manager.start("Benchmark")

    assert context_calls == ["spawn"]
    assert process_args[0][0] == _request("Benchmark")
    assert vars(manager)["_run"] is not old_run


def test_blocking_stop_waiter_is_released_when_join_fails() -> None:
    manager = ProcessManager()
    _attach_run(manager, _JoinFailureProcess())

    with pytest.raises(RuntimeError, match="join failed"):
        manager.stop_and_wait()

    assert vars(manager)["_start_inhibitors"] == 0


def test_stop_and_wait_releases_nested_start_holds_when_stop_signal_fails() -> None:
    manager = ProcessManager()
    run = _attach_run(manager, _Process(), stop_event=_FailingStopEvent())

    with manager.hold_start():
        with pytest.raises(RuntimeError, match="stop signal failed"):
            manager.stop_and_wait()
        assert vars(manager)["_start_inhibitors"] == 1
        assert not run.stop_requested

    assert vars(manager)["_start_inhibitors"] == 0


def test_hold_start_inhibits_start_until_the_state_update_finishes() -> None:
    manager = ProcessManager()

    with manager.hold_start():
        manager.start("Benchmark")
        assert vars(manager)["_run"] is None
        assert vars(manager)["_start_inhibitors"] == 1

    assert vars(manager)["_start_inhibitors"] == 0


def test_parent_stop_intent_wins_over_late_child_success() -> None:
    stop_event = _StopEvent()
    process = _Process(exits_on_join=True)
    manager = ProcessManager()
    _attach_run(
        manager,
        process,
        stop_event=stop_event,
        outcome=_outcome(CommandStatus.FINISHED),
    )

    manager.stop_and_wait()

    assert manager.outcome is not None
    assert manager.outcome.status is CommandStatus.STOPPED


def test_process_manager_is_singleton() -> None:
    manager = ProcessManager.instance()

    assert ProcessManager.instance() is manager
    assert ProcessManager() is manager


def test_force_stop_instance_does_not_create_a_manager(monkeypatch: pytest.MonkeyPatch) -> None:
    ProcessManager.force_stop_instance()
    assert ProcessManager._singleton is None  # ruff:ignore[private-member-access] - shutdown 不创建新实例。

    manager = ProcessManager.instance()
    force_calls: list[None] = []
    monkeypatch.setattr(manager, "force_stop", lambda: force_calls.append(None))

    ProcessManager.force_stop_instance()

    assert force_calls == [None]


def test_monitor_drains_tail_logs_and_publishes_outcome() -> None:
    process = _Process(alive=False)
    manager = ProcessManager()
    run = _attach_run(manager, process, outcome=_outcome(CommandStatus.FINISHED))
    tail = Text("tail traceback")
    run.renderable_queue.put(tail)
    run.renderable_queue.put(None)

    manager.start_log_queue_handler(run)
    monitor = manager.thd_log_queue_handler
    assert monitor is not None
    monitor.join(timeout=2)

    assert not monitor.is_alive()
    assert manager.renderables == [tail]
    assert manager.outcome is not None
    assert manager.outcome.status is CommandStatus.FINISHED


def test_monitor_reports_missing_child_outcome(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(process_manager_module, "QUEUE_DRAIN_SECONDS", 0)
    process = _Process(alive=False, exitcode=9)
    manager = ProcessManager()
    run = _attach_run(manager, process)
    run.renderable_queue.put(None)

    manager.start_log_queue_handler(run)
    monitor = manager.thd_log_queue_handler
    assert monitor is not None
    monitor.join(timeout=2)

    assert manager.outcome is not None
    assert manager.outcome.status is CommandStatus.FAILED
    assert manager.outcome.exception_type == "MissingProcessOutcome"
    assert manager.outcome.message == "Process exited without an outcome (exitcode=9)"


def test_old_monitor_cannot_overwrite_current_run_outcome() -> None:
    manager = ProcessManager()
    old_outcome = _outcome(CommandStatus.FAILED)
    old_run = _attach_run(manager, _Process(alive=False), outcome=old_outcome)
    old_run.renderable_queue.put(None)

    current_outcome = _outcome(CommandStatus.FINISHED)
    current_run = _attach_run(manager, _Process(alive=False), outcome=current_outcome)
    assert manager.outcome is current_outcome

    manager.start_log_queue_handler(old_run)
    old_monitor = old_run.monitor
    assert old_monitor is not None
    old_monitor.join(timeout=2)

    assert not old_monitor.is_alive()
    assert vars(manager)["_run"] is current_run
    assert manager.outcome is current_outcome


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (CommandStatus.FINISHED, 2),
        (CommandStatus.STOPPED, 2),
        (CommandStatus.RESTART_REQUESTED, 2),
        (CommandStatus.FAILED, 3),
        (CommandStatus.KILLED, 3),
    ],
)
def test_state_uses_command_outcome(status: CommandStatus, expected: int) -> None:
    manager = ProcessManager()
    _attach_run(manager, _Process(alive=False))
    manager.renderables.append("misleading final log: Finish")
    vars(manager)["_outcome"] = _outcome(status)

    assert manager.state == expected


def test_stop_after_completion_preserves_child_outcome() -> None:
    process = _Process(alive=False)
    manager = ProcessManager()
    _attach_run(manager, process, outcome=_outcome(CommandStatus.FINISHED))

    manager.stop_and_wait()

    assert manager.outcome is not None
    assert manager.outcome.status is CommandStatus.FINISHED


def test_force_stop_after_completion_preserves_child_outcome() -> None:
    process = _Process(alive=False)
    manager = ProcessManager()
    _attach_run(manager, process, outcome=_outcome(CommandStatus.FAILED, message="child failed"))

    manager.force_stop()

    assert process.kill_calls == 0
    assert manager.outcome is not None
    assert manager.outcome.status is CommandStatus.FAILED
    assert manager.outcome.message == "child failed"
