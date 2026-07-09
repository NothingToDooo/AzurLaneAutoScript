import queue
import threading

import module.webui.process_manager as process_manager_module
from module.webui.process_manager import KILL_JOIN_SECONDS, STOP_GRACE_SECONDS, ProcessManager


def _patch_process_boundary(monkeypatch, calls: list[tuple]):
    class _Logger:
        def critical(self, message):
            calls.append(("critical", message))

        def info(self, message):
            calls.append(("info", message))

        def exception(self, error):
            calls.append(("exception", str(error)))

    monkeypatch.setattr(process_manager_module, "set_file_logger", lambda name: calls.append(("file_logger", name)))
    monkeypatch.setattr(process_manager_module, "set_func_logger", lambda func: calls.append(("func_logger", func)))
    monkeypatch.setattr(process_manager_module, "remove_fake_pil_module", lambda: calls.append(("remove_fake_pil",)))
    monkeypatch.setattr(process_manager_module, "logger", _Logger())


class _StopEvent:
    def __init__(self) -> None:
        self.set_calls = 0

    def set(self) -> None:
        self.set_calls += 1

    def is_set(self) -> bool:
        return self.set_calls > 0


class _Process:
    def __init__(self, *, exits_on_join: bool = False) -> None:
        self._alive = True
        self.exits_on_join = exits_on_join
        self.join_calls: list[int | None] = []
        self.kill_calls = 0

    def is_alive(self) -> bool:
        return self._alive

    def join(self, timeout=None) -> None:
        self.join_calls.append(timeout)
        if self.exits_on_join:
            self._alive = False

    def kill(self) -> None:
        self.kill_calls += 1
        self._alive = False


class _LogThread:
    def __init__(self) -> None:
        self.join_calls: list[int | None] = []

    def join(self, timeout=None) -> None:
        self.join_calls.append(timeout)

    def is_alive(self) -> bool:
        return False


def _make_manager(process=None, stop_event=None):
    manager = object.__new__(ProcessManager)
    manager.config_name = "alas"
    manager.renderables = []
    manager.renderables_max_length = 400
    manager.renderables_reduce_length = 80
    manager.thd_log_queue_handler = None
    vars(manager).update(
        {
            "_renderable_queue": queue.Queue(),
            "_process": process,
            "_stop_event": stop_event,
            "_stop_lock": threading.Lock(),
        }
    )
    return manager


def test_run_process_runs_alas_loop(monkeypatch) -> None:
    calls = []
    _patch_process_boundary(monkeypatch, calls)

    class _Alas:
        stop_event = None

        def __init__(self, config_name):
            calls.append(("init", config_name))

        def loop(self):
            calls.append(("loop",))

    monkeypatch.setattr(process_manager_module, "AzurLaneAutoScript", _Alas)

    ProcessManager.run_process("alas", "alas", queue.Queue())

    assert ("init", "alas") in calls
    assert ("loop",) in calls
    assert ("info", "[alas] exited. Reason: Finish\n") in calls


def test_run_process_wires_stop_event(monkeypatch) -> None:
    calls = []
    stop_event = _StopEvent()
    _patch_process_boundary(monkeypatch, calls)

    class _Alas:
        stop_event = None

        def __init__(self, config_name):
            calls.append(("init", config_name))

        def loop(self):
            calls.append(("alas_stop_event", _Alas.stop_event is stop_event))
            calls.append(("config_stop_event", process_manager_module.AzurLaneConfig.stop_event is stop_event))

    monkeypatch.setattr(process_manager_module, "AzurLaneAutoScript", _Alas)

    ProcessManager.run_process("alas", "alas", queue.Queue(), stop_event)

    assert ("alas_stop_event", True) in calls
    assert ("config_stop_event", True) in calls


def test_run_process_runs_builtin_task(monkeypatch) -> None:
    calls = []
    _patch_process_boundary(monkeypatch, calls)

    class _Alas:
        def __init__(self, config_name):
            calls.append(("init", config_name))

        def run(self, task, skip_first_screenshot=False):
            calls.append(("run", task, skip_first_screenshot))

    monkeypatch.setattr(process_manager_module, "AzurLaneAutoScript", _Alas)

    ProcessManager.run_process("alas", "Benchmark", queue.Queue())

    assert ("run", "benchmark", True) in calls


def test_run_process_rejects_unknown_func(monkeypatch) -> None:
    calls = []
    _patch_process_boundary(monkeypatch, calls)

    ProcessManager.run_process("alas", "MissingMod", queue.Queue())

    assert ("critical", "No function matched: MissingMod") in calls


def test_start_creates_stop_event_and_passes_it_to_child(monkeypatch) -> None:
    created_event = _StopEvent()
    calls = []

    class _StartedProcess:
        def __init__(self, target, args):
            del target
            calls.append(("process_args", args))

        def start(self) -> None:
            calls.append(("start",))

        def is_alive(self) -> bool:
            return False

    monkeypatch.setattr(process_manager_module, "Event", lambda: created_event)
    monkeypatch.setattr(process_manager_module, "Process", _StartedProcess)
    monkeypatch.setattr(
        ProcessManager, "start_log_queue_handler", lambda self: calls.append(("log_thread", self.config_name))
    )
    manager = _make_manager()

    manager.start(None)

    assert vars(manager)["_stop_event"] is created_event
    assert calls[0][0] == "process_args"
    assert calls[0][1][0:2] == ("alas", "alas")
    assert calls[0][1][3] is created_event
    assert ("start",) in calls
    assert ("log_thread", "alas") in calls


def test_stop_requests_event_and_does_not_kill_when_process_exits() -> None:
    stop_event = _StopEvent()
    process = _Process(exits_on_join=True)
    log_thread = _LogThread()
    manager = _make_manager(process=process, stop_event=stop_event)
    manager.thd_log_queue_handler = log_thread

    manager.stop()

    assert stop_event.set_calls == 1
    assert process.join_calls == [STOP_GRACE_SECONDS]
    assert process.kill_calls == 0
    assert vars(manager)["_stop_event"] is None
    assert manager.renderables == ["[alas] exited. Reason: Manual stop\n"]
    assert log_thread.join_calls == [1]


def test_stop_kills_process_after_grace_timeout() -> None:
    stop_event = _StopEvent()
    process = _Process(exits_on_join=False)
    manager = _make_manager(process=process, stop_event=stop_event)

    manager.stop()

    assert stop_event.set_calls == 1
    assert process.join_calls == [STOP_GRACE_SECONDS, KILL_JOIN_SECONDS]
    assert process.kill_calls == 1
    assert vars(manager)["_stop_event"] is None
    assert manager.renderables == ["[alas] exited. Reason: Manual stop\n"]
