from datetime import datetime, timedelta
from types import SimpleNamespace

import alas as alas_module
from alas import AzurLaneAutoScript

WAIT_METHOD = "_wait_for_next_task"


def _record_deleted_cache(deleted: list[str]):
    def record(obj, name) -> None:
        del obj
        deleted.append(name)

    return record


class _WaitDevice:
    def __init__(self) -> None:
        self.app_stop_calls = 0
        self.release_calls = 0

    def app_stop(self) -> None:
        self.app_stop_calls += 1

    def release_during_wait(self) -> None:
        self.release_calls += 1


class _WaitConfig:
    def __init__(self, method: str) -> None:
        self.Optimization_WhenTaskQueueEmpty = method
        self.task_calls: list[str] = []

    def task_call(self, task: str) -> None:
        self.task_calls.append(task)


def _make_runner(*, method: str = "stay_there", wait_result: bool = True):
    runner = object.__new__(AzurLaneAutoScript)
    runner.config = _WaitConfig(method)
    runner.device = _WaitDevice()
    runner.is_first_task = True
    runner.wait_calls: list[datetime] = []
    runner.run_calls: list[str] = []

    def wait_until(future: datetime) -> bool:
        runner.wait_calls.append(future)
        return wait_result

    def run(command: str) -> bool:
        runner.run_calls.append(command)
        return True

    runner.wait_until = wait_until
    runner.run = run
    return runner


def _task(command: str, next_run: datetime):
    return SimpleNamespace(command=command, next_run=next_run)


def _wait_for_next_task(runner, task) -> bool:
    return getattr(runner, WAIT_METHOD)(task)


def test_wait_for_next_task_runs_ready_task(monkeypatch) -> None:
    release_calls: list[str] = []
    deleted: list[str] = []
    monkeypatch.setattr(alas_module, "release_resources", lambda: release_calls.append("release"))
    monkeypatch.setattr(alas_module, "del_cached_property", _record_deleted_cache(deleted))
    runner = _make_runner()
    task = _task("Main", datetime.now() - timedelta(seconds=1))

    assert _wait_for_next_task(runner, task)
    assert runner.wait_calls == []
    assert release_calls == []
    assert deleted == []


def test_wait_for_next_task_reloads_config_when_wait_is_interrupted(monkeypatch) -> None:
    release_calls: list[str] = []
    deleted: list[str] = []
    monkeypatch.setattr(alas_module, "release_resources", lambda: release_calls.append("release"))
    monkeypatch.setattr(alas_module, "del_cached_property", _record_deleted_cache(deleted))
    runner = _make_runner(method="stay_there", wait_result=False)
    task = _task("Main", datetime.now() + timedelta(minutes=1))

    assert not _wait_for_next_task(runner, task)
    assert release_calls == ["release"]
    assert runner.device.release_calls == 1
    assert deleted == ["config"]


def test_wait_for_next_task_closes_game_and_schedules_restart(monkeypatch) -> None:
    release_calls: list[str] = []
    deleted: list[str] = []
    monkeypatch.setattr(alas_module, "release_resources", lambda: release_calls.append("release"))
    monkeypatch.setattr(alas_module, "del_cached_property", _record_deleted_cache(deleted))
    runner = _make_runner(method="close_game", wait_result=True)
    task = _task("Main", datetime.now() + timedelta(minutes=1))

    assert not _wait_for_next_task(runner, task)
    assert runner.device.app_stop_calls == 1
    assert runner.device.release_calls == 1
    assert release_calls == ["release"]
    assert runner.config.task_calls == ["Restart"]
    assert deleted == ["config"]


def test_wait_for_next_task_allows_scheduled_restart_after_close_game(monkeypatch) -> None:
    release_calls: list[str] = []
    deleted: list[str] = []
    monkeypatch.setattr(alas_module, "release_resources", lambda: release_calls.append("release"))
    monkeypatch.setattr(alas_module, "del_cached_property", _record_deleted_cache(deleted))
    runner = _make_runner(method="close_game", wait_result=True)
    task = _task("Restart", datetime.now() + timedelta(minutes=1))

    assert _wait_for_next_task(runner, task)
    assert runner.config.task_calls == []
    assert deleted == []


def test_wait_for_next_task_can_return_to_main_page(monkeypatch) -> None:
    release_calls: list[str] = []
    deleted: list[str] = []
    monkeypatch.setattr(alas_module, "release_resources", lambda: release_calls.append("release"))
    monkeypatch.setattr(alas_module, "del_cached_property", _record_deleted_cache(deleted))
    runner = _make_runner(method="goto_main", wait_result=True)
    task = _task("Main", datetime.now() + timedelta(minutes=1))

    assert _wait_for_next_task(runner, task)
    assert runner.run_calls == ["goto_main"]
    assert release_calls == ["release"]
    assert runner.device.release_calls == 1
    assert deleted == []
