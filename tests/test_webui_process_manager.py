import inspect
import json
import queue
from datetime import UTC, datetime
from multiprocessing.reduction import ForkingPickler
from types import SimpleNamespace
from typing import TYPE_CHECKING, Protocol

import pytest
from rich.text import Text

import module.webui.process_manager as process_manager_module
from module.application import Faulted, Succeeded, TaskResult
from module.bootstrap.process_host import InstanceProcessExit, InstanceProcessExitKind
from module.webui.process_manager import (
    KILL_JOIN_SECONDS,
    STOP_GRACE_SECONDS,
    ProcessManager,
    RenderableQueueItem,
)
from module.webui.process_outcome import ProcessOutcome, ProcessOutcomeStatus

if TYPE_CHECKING:
    from collections.abc import Callable


def _patch_process_boundary(monkeypatch: pytest.MonkeyPatch, calls: list[tuple[object, ...]]) -> None:
    class _Logger:
        @staticmethod
        def critical(message: str) -> None:
            calls.append(("critical", message))

        @staticmethod
        def info(message: str) -> None:
            calls.append(("info", message))

        @staticmethod
        def exception(error: BaseException) -> None:
            calls.append(("exception", str(error)))

    monkeypatch.setattr(process_manager_module, "set_file_logger", lambda name: calls.append(("file_logger", name)))
    monkeypatch.setattr(process_manager_module, "set_func_logger", lambda func: calls.append(("func_logger", func)))
    monkeypatch.setattr(process_manager_module, "remove_fake_pil_module", lambda: calls.append(("remove_fake_pil",)))
    monkeypatch.setattr(process_manager_module, "logger", _Logger())


class _StopEvent:
    def __init__(self, *, is_set: bool = False) -> None:
        self.set_calls = int(is_set)

    def set(self) -> None:
        self.set_calls += 1

    def is_set(self) -> bool:
        return self.set_calls > 0

    def clear(self) -> None:
        self.set_calls = 0

    def wait(self, timeout: float) -> bool:
        del timeout
        return self.is_set()


class _Process:
    def __init__(self, *, exits_on_join: bool = False, alive: bool = True, exitcode: int | None = 0) -> None:
        self._alive = alive
        self.exitcode = exitcode
        self.exits_on_join = exits_on_join
        self.join_calls: list[float | None] = []
        self.kill_calls = 0

    def is_alive(self) -> bool:
        return self._alive

    def join(self, timeout: float | None = None) -> None:
        self.join_calls.append(timeout)
        if self.exits_on_join:
            self._alive = False

    def kill(self) -> None:
        self.kill_calls += 1
        self._alive = False


class _ProcessLike(Protocol):
    exitcode: int | None

    def is_alive(self) -> bool: ...

    def join(self, timeout: float | None = None) -> None: ...

    def kill(self) -> None: ...


class _StopEventLike(Protocol):
    def set(self) -> None: ...

    def is_set(self) -> bool: ...


class _ConfigurationEventLike(_StopEventLike, Protocol):
    def clear(self) -> None: ...

    def wait(self, timeout: float) -> bool: ...


def _outcome(status: ProcessOutcomeStatus, *, command: str = "alas") -> ProcessOutcome:
    return ProcessOutcome(
        status=status,
        config_name="alas",
        command=command,
        exception_type=None,
        message=None,
        finished_at=datetime.now(UTC),
    )


def _make_run(
    process: _ProcessLike,
    *,
    command: str = "alas",
    outcome: ProcessOutcome | None = None,
    configuration_event: _ConfigurationEventLike | None = None,
) -> SimpleNamespace:
    renderable_queue: queue.Queue[RenderableQueueItem] = queue.Queue()
    outcome_queue: queue.Queue[ProcessOutcome] = queue.Queue()
    if outcome is not None:
        outcome_queue.put(outcome)
    return SimpleNamespace(
        command=command,
        process=process,
        renderable_queue=renderable_queue,
        outcome_queue=outcome_queue,
        configuration_event=_StopEvent() if configuration_event is None else configuration_event,
        stop_status=None,
        monitor=None,
    )


def _attach_run(
    manager: ProcessManager,
    process: _ProcessLike,
    *,
    stop_event: _StopEventLike | None = None,
    outcome: ProcessOutcome | None = None,
) -> SimpleNamespace:
    run = _make_run(process, outcome=outcome)
    vars(manager).update({"_run": run, "_stop_event": stop_event})
    return run


def _run_process(
    monkeypatch: pytest.MonkeyPatch,
    func: str,
    *,
    stop_event: _StopEventLike | None = None,
    configuration_event: _ConfigurationEventLike | None = None,
) -> tuple[ProcessOutcome, queue.Queue[RenderableQueueItem], list[tuple[object, ...]]]:
    calls: list[tuple[object, ...]] = []
    renderable_queue: queue.Queue[RenderableQueueItem] = queue.Queue()
    outcome_queue: queue.Queue[ProcessOutcome] = queue.Queue()
    _patch_process_boundary(monkeypatch, calls)
    ProcessManager.run_process(
        "alas",
        func,
        renderable_queue,
        outcome_queue,
        stop_event,
        configuration_event,
    )
    return outcome_queue.get_nowait(), renderable_queue, calls


def _host_exit(
    kind: InstanceProcessExitKind,
    error: Exception | None = None,
) -> InstanceProcessExit:
    outcome = Succeeded() if error is None else Faulted(error)
    return InstanceProcessExit(kind, task_result=TaskResult(outcome))


def _install_host(
    monkeypatch: pytest.MonkeyPatch,
    calls: list[tuple[object, ...]],
    *,
    exit_: InstanceProcessExit | None = None,
    error: BaseException | None = None,
) -> None:
    class _Host:
        @staticmethod
        def execute(
            instance_name: str,
            command: str,
            *,
            stop_signal: object | None = None,
            configuration_signal: object | None = None,
        ) -> InstanceProcessExit:
            calls.append(("host_execute", instance_name, command, stop_signal, configuration_signal))
            if error is not None:
                raise error
            assert exit_ is not None
            return exit_

    monkeypatch.setattr(process_manager_module, "build_default_instance_process_host", _Host)


def test_process_outcome_is_serializable_and_json_ready() -> None:
    outcome = _outcome(ProcessOutcomeStatus.FINISHED)

    assert ForkingPickler.dumps(outcome)
    assert json.loads(json.dumps(outcome.to_dict())) == outcome.to_dict()
    assert outcome.finished_at.tzinfo is UTC
    assert hash(outcome)


def test_run_process_runs_alas_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[object, ...]] = []
    _patch_process_boundary(monkeypatch, calls)
    _install_host(monkeypatch, calls, exit_=_host_exit(InstanceProcessExitKind.FINISHED))
    renderable_queue: queue.Queue[RenderableQueueItem] = queue.Queue()
    outcome_queue: queue.Queue[ProcessOutcome] = queue.Queue()

    ProcessManager.run_process("alas", "alas", renderable_queue, outcome_queue)

    assert outcome_queue.get_nowait().status is ProcessOutcomeStatus.FINISHED
    assert renderable_queue.get_nowait() is None
    assert ("host_execute", "alas", "alas", None, None) in calls
    assert ("info", "[alas] exited. Reason: finished\n") in calls


def test_run_process_reports_stop_event(monkeypatch: pytest.MonkeyPatch) -> None:
    stop_event = _StopEvent(is_set=True)
    calls: list[tuple[object, ...]] = []
    _patch_process_boundary(monkeypatch, calls)
    _install_host(monkeypatch, calls, exit_=_host_exit(InstanceProcessExitKind.STOPPED))
    outcome, renderable_queue, _ = _run_process(monkeypatch, "alas", stop_event=stop_event)

    assert outcome.status is ProcessOutcomeStatus.MANUAL_STOP
    assert renderable_queue.get_nowait() is None
    assert ("host_execute", "alas", "alas", stop_event, None) in calls


def test_run_process_forwards_configuration_event(monkeypatch: pytest.MonkeyPatch) -> None:
    stop_event = _StopEvent()
    configuration_event = _StopEvent()
    calls: list[tuple[object, ...]] = []
    _patch_process_boundary(monkeypatch, calls)
    _install_host(monkeypatch, calls, exit_=_host_exit(InstanceProcessExitKind.FINISHED))

    outcome, _, _ = _run_process(
        monkeypatch,
        "alas",
        stop_event=stop_event,
        configuration_event=configuration_event,
    )

    assert outcome.status is ProcessOutcomeStatus.FINISHED
    assert ("host_execute", "alas", "alas", stop_event, configuration_event) in calls


@pytest.mark.parametrize(
    ("config_name", "command"),
    [
        ("Daemon", "daemon"),
        ("OpsiDaemon", "opsi_daemon"),
        ("EventStory", "event_story"),
        ("AzurLaneUncensored", "azur_lane_uncensored"),
        ("Benchmark", "benchmark"),
        ("GameManager", "game_manager"),
    ],
)
def test_run_process_runs_direct_catalog_task(
    monkeypatch: pytest.MonkeyPatch,
    config_name: str,
    command: str,
) -> None:
    calls: list[tuple[object, ...]] = []
    _patch_process_boundary(monkeypatch, calls)
    _install_host(monkeypatch, calls, exit_=_host_exit(InstanceProcessExitKind.FINISHED))
    outcome, _, _ = _run_process(monkeypatch, config_name)

    assert outcome.status is ProcessOutcomeStatus.FINISHED
    assert ("host_execute", "alas", command, None, None) in calls


@pytest.mark.parametrize("func", ["Main", "MissingMod"])
def test_run_process_rejects_non_direct_task(monkeypatch: pytest.MonkeyPatch, func: str) -> None:
    outcome, _, calls = _run_process(monkeypatch, func)

    assert outcome.status is ProcessOutcomeStatus.FAILED
    assert outcome.exception_type == "LookupError"
    assert outcome.message == f"No function matched: {func}"
    assert ("critical", outcome.message) in calls


def test_run_process_reports_typed_task_fault(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[object, ...]] = []
    _install_host(
        monkeypatch,
        calls,
        exit_=_host_exit(InstanceProcessExitKind.FAILED, ValueError("first line\nsecond line")),
    )
    monkeypatch.setattr(process_manager_module, "get_tool_task_command", lambda func: func)
    outcome, _, _ = _run_process(monkeypatch, "direct")

    assert outcome.status is ProcessOutcomeStatus.FAILED
    assert outcome.exception_type == "ValueError"
    assert outcome.message == "first line second line"


def test_run_process_reports_exception_without_losing_traceback(monkeypatch: pytest.MonkeyPatch) -> None:
    host_calls: list[tuple[object, ...]] = []
    _install_host(monkeypatch, host_calls, error=ValueError("first line\nsecond line"))
    outcome, renderable_queue, calls = _run_process(monkeypatch, "alas")

    assert outcome.status is ProcessOutcomeStatus.FAILED
    assert outcome.exception_type == "ValueError"
    assert outcome.message == "first line second line"
    assert ("exception", "first line\nsecond line") in calls
    assert renderable_queue.get_nowait() is None


def test_run_process_queues_outcome_before_reraising_system_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[object, ...]] = []
    _patch_process_boundary(monkeypatch, calls)
    _install_host(monkeypatch, calls, error=SystemExit(7))
    renderable_queue: queue.Queue[RenderableQueueItem] = queue.Queue()
    outcome_queue: queue.Queue[ProcessOutcome] = queue.Queue()

    with pytest.raises(SystemExit, match="7"):
        ProcessManager.run_process("alas", "alas", renderable_queue, outcome_queue)

    outcome = outcome_queue.get_nowait()
    assert outcome.status is ProcessOutcomeStatus.FAILED
    assert outcome.exception_type == "SystemExit"
    assert renderable_queue.get_nowait() is None


def test_run_process_preserves_restart_request_as_a_distinct_outcome(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[object, ...]] = []
    _install_host(monkeypatch, calls, exit_=_host_exit(InstanceProcessExitKind.RESTART_REQUESTED))

    outcome, _, _ = _run_process(monkeypatch, "alas")

    assert outcome.status is ProcessOutcomeStatus.RESTART_REQUESTED


def test_process_manager_source_has_no_direct_task_allowlist() -> None:
    source = inspect.getsource(process_manager_module)
    assert "_AVAILABLE_WEBUI_TASKS" not in source


def test_start_uses_fresh_queues_for_each_run(monkeypatch: pytest.MonkeyPatch) -> None:
    created_events: list[_StopEvent] = []
    process_args: list[tuple[object, ...]] = []
    monitor_runs: list[object] = []
    warnings: list[str] = []

    class _DrainingMonitor:
        def __init__(self) -> None:
            self.join_calls: list[float | None] = []

        @staticmethod
        def is_alive() -> bool:
            return True

        def join(self, timeout: float | None = None) -> None:
            self.join_calls.append(timeout)

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

    def capture_monitor(manager: ProcessManager, run: object | None = None) -> None:
        del manager
        monitor_runs.append(run)

    def create_event() -> _StopEvent:
        event = _StopEvent()
        created_events.append(event)
        return event

    monkeypatch.setattr(process_manager_module, "Event", create_event)
    monkeypatch.setattr(process_manager_module, "Process", _StartedProcess)
    queue_factory = SimpleNamespace(Queue=queue.Queue)
    monkeypatch.setattr(process_manager_module.State, "manager", queue_factory)
    monkeypatch.setattr(ProcessManager, "start_log_queue_handler", capture_monitor)
    monkeypatch.setattr(process_manager_module, "logger", SimpleNamespace(warning=warnings.append))
    manager = ProcessManager()
    draining_monitor = _DrainingMonitor()
    vars(manager)["thd_log_queue_handler"] = draining_monitor

    manager.start(None)
    manager.start("Benchmark")

    assert len(process_args) == 2
    assert process_args[0][0:2] == ("alas", "alas")
    assert process_args[1][0:2] == ("alas", "Benchmark")
    assert process_args[0][2] is not process_args[1][2]
    assert process_args[0][3] is not process_args[1][3]
    assert len(created_events) == 4
    assert process_args[0][4:6] == (created_events[0], created_events[1])
    assert process_args[1][4:6] == (created_events[2], created_events[3])
    assert len(monitor_runs) == 2
    assert draining_monitor.join_calls == [process_manager_module.MONITOR_JOIN_SECONDS] * 2
    assert warnings == ["Process monitor is still draining its queue"] * 2


def test_stop_reports_manual_stop_when_process_exits_gracefully() -> None:
    stop_event = _StopEvent()
    process = _Process(exits_on_join=True)
    manager = ProcessManager()
    run = _attach_run(manager, process, stop_event=stop_event)

    manager.stop()

    assert stop_event.set_calls == 1
    assert run.configuration_event.set_calls == 1
    assert process.join_calls == [STOP_GRACE_SECONDS]
    assert process.kill_calls == 0
    assert manager.outcome is not None
    assert manager.outcome.status is ProcessOutcomeStatus.MANUAL_STOP


def test_stop_reports_killed_after_grace_timeout() -> None:
    stop_event = _StopEvent()
    process = _Process()
    manager = ProcessManager()
    run = _attach_run(manager, process, stop_event=stop_event)

    manager.stop()

    assert stop_event.set_calls == 1
    assert run.configuration_event.set_calls == 1
    assert process.join_calls == [STOP_GRACE_SECONDS, KILL_JOIN_SECONDS]
    assert process.kill_calls == 1
    assert run.renderable_queue.empty()
    assert manager.outcome is not None
    assert manager.outcome.status is ProcessOutcomeStatus.KILLED


def test_parent_stop_intent_wins_over_late_child_success() -> None:
    stop_event = _StopEvent()
    process = _Process(exits_on_join=True)
    manager = ProcessManager()
    _attach_run(manager, process, stop_event=stop_event, outcome=_outcome(ProcessOutcomeStatus.FINISHED))

    manager.stop()

    assert manager.outcome is not None
    assert manager.outcome.status is ProcessOutcomeStatus.MANUAL_STOP


def test_configuration_notification_wakes_only_a_live_run() -> None:
    process = _Process(alive=True)
    manager = ProcessManager()
    run = _attach_run(manager, process)

    manager.notify_configuration_changed()

    assert run.configuration_event.set_calls == 1


def test_monitor_drains_tail_logs_and_publishes_outcome() -> None:
    process = _Process(alive=False)
    manager = ProcessManager()
    run = _attach_run(manager, process, outcome=_outcome(ProcessOutcomeStatus.FINISHED))
    tail = Text("tail traceback")
    run.renderable_queue.put(tail)
    run.renderable_queue.put(None)

    manager.start_log_queue_handler()
    monitor = manager.thd_log_queue_handler
    assert monitor is not None
    monitor.join(timeout=2)

    assert not monitor.is_alive()
    assert manager.renderables == [tail]
    assert manager.outcome is not None
    assert manager.outcome.status is ProcessOutcomeStatus.FINISHED


def test_monitor_drains_killed_process_tail_without_child_sentinel() -> None:
    process = _Process(alive=False, exitcode=-9)
    manager = ProcessManager()
    run = _attach_run(manager, process)
    run.stop_status = ProcessOutcomeStatus.KILLED
    tail = Text("tail before forced kill")
    run.renderable_queue.put(tail)

    manager.start_log_queue_handler()
    monitor = manager.thd_log_queue_handler
    assert monitor is not None
    monitor.join(timeout=2)

    assert not monitor.is_alive()
    assert manager.renderables == [tail]
    assert manager.outcome is not None
    assert manager.outcome.status is ProcessOutcomeStatus.KILLED


def test_monitor_reports_missing_child_outcome() -> None:
    process = _Process(alive=False, exitcode=9)
    manager = ProcessManager()
    run = _attach_run(manager, process)
    run.renderable_queue.put(None)

    manager.start_log_queue_handler()
    monitor = manager.thd_log_queue_handler
    assert monitor is not None
    monitor.join(timeout=2)

    assert manager.outcome is not None
    assert manager.outcome.status is ProcessOutcomeStatus.FAILED
    assert manager.outcome.exception_type == "MissingProcessOutcome"
    assert manager.outcome.message == "Process exited without an outcome (exitcode=9)"


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (ProcessOutcomeStatus.FINISHED, 2),
        (ProcessOutcomeStatus.MANUAL_STOP, 2),
        (ProcessOutcomeStatus.FAILED, 3),
        (ProcessOutcomeStatus.KILLED, 3),
    ],
)
def test_state_uses_structured_outcome(status: ProcessOutcomeStatus, expected: int) -> None:
    manager = ProcessManager()
    _attach_run(manager, _Process(alive=False))
    manager.renderables.append("misleading final log: Finish")
    vars(manager)["_outcome"] = _outcome(status)

    assert manager.state == expected


def test_stop_after_completion_preserves_child_outcome() -> None:
    process = _Process(alive=False)
    manager = ProcessManager()
    _attach_run(manager, process, outcome=_outcome(ProcessOutcomeStatus.FINISHED))

    manager.stop()

    assert manager.outcome is not None
    assert manager.outcome.status is ProcessOutcomeStatus.FINISHED
