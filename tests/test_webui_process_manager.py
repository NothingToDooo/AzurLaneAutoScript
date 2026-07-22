import queue
import threading
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol, cast

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
