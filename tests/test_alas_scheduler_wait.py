from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, cast, override

import alas as alas_module
from alas import AzurLaneAutoScript
from module.config.schedule import ScheduleDecision, ScheduleEntry, ScheduleState

if TYPE_CHECKING:
    from collections.abc import Callable

    import pytest

WAIT_METHOD = "_wait_for_next_task"


def _record_deleted_cache(deleted: list[str]) -> Callable[[AzurLaneAutoScript, str], None]:
    def record(obj: AzurLaneAutoScript, name: str) -> None:
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


class _WaitRunner(AzurLaneAutoScript):
    config: _WaitConfig
    device: _WaitDevice

    def __init__(self, method: str, *, wait_result: bool) -> None:
        self.config = _WaitConfig(method)
        self.device = _WaitDevice()
        self.is_first_task = True
        self.wait_calls: list[datetime] = []
        self.run_calls: list[str] = []
        self.wait_result = wait_result

    @override
    def wait_until(self, future: datetime) -> bool:
        self.wait_calls.append(future)
        return self.wait_result

    @override
    def run(self, command: str, *, skip_first_screenshot: bool = False) -> bool:
        del skip_first_screenshot
        self.run_calls.append(command)
        return True


def _make_runner(*, method: str = "stay_there", wait_result: bool = True) -> _WaitRunner:
    return _WaitRunner(method, wait_result=wait_result)


def _decision(command: str, next_run: datetime | str, *, state: ScheduleState = "waiting") -> ScheduleDecision:
    entry = ScheduleEntry(enable=True, command=command, next_run=next_run)
    wake_at = cast("datetime", next_run) if state == "waiting" else None
    return ScheduleDecision(
        state=state,
        entry=entry,
        wake_at=wake_at,
        pending=(entry,) if state == "ready" else (),
        waiting=(entry,) if state == "waiting" else (),
        errors=(entry,) if state == "error" else (),
    )


def _wait_for_next_task(runner: _WaitRunner, decision: ScheduleDecision) -> bool:
    return getattr(runner, WAIT_METHOD)(decision)


def test_wait_for_next_task_runs_ready_task(monkeypatch: pytest.MonkeyPatch) -> None:
    release_calls: list[str] = []
    deleted: list[str] = []
    monkeypatch.setattr(alas_module, "release_resources", lambda: release_calls.append("release"))
    monkeypatch.setattr(alas_module, "del_cached_property", _record_deleted_cache(deleted))
    runner = _make_runner()
    task = _decision("Main", datetime.now() - timedelta(seconds=1), state="ready")

    assert _wait_for_next_task(runner, task)
    assert runner.wait_calls == []
    assert release_calls == []
    assert deleted == []


def test_wait_for_next_task_runs_invalid_time_through_explicit_error_state(monkeypatch: pytest.MonkeyPatch) -> None:
    release_calls: list[str] = []
    monkeypatch.setattr(alas_module, "release_resources", lambda: release_calls.append("release"))
    runner = _make_runner()
    decision = _decision("Main", "invalid", state="error")

    assert _wait_for_next_task(runner, decision)
    assert runner.wait_calls == []
    assert release_calls == []


def test_wait_for_next_task_reloads_config_when_wait_is_interrupted(monkeypatch: pytest.MonkeyPatch) -> None:
    release_calls: list[str] = []
    deleted: list[str] = []
    monkeypatch.setattr(alas_module, "release_resources", lambda: release_calls.append("release"))
    monkeypatch.setattr(alas_module, "del_cached_property", _record_deleted_cache(deleted))
    runner = _make_runner(method="stay_there", wait_result=False)
    task = _decision("Main", datetime.now() + timedelta(minutes=1))

    assert not _wait_for_next_task(runner, task)
    assert release_calls == ["release"]
    assert runner.device.release_calls == 1
    assert deleted == ["config"]


def test_wait_for_next_task_closes_game_and_schedules_restart(monkeypatch: pytest.MonkeyPatch) -> None:
    release_calls: list[str] = []
    deleted: list[str] = []
    monkeypatch.setattr(alas_module, "release_resources", lambda: release_calls.append("release"))
    monkeypatch.setattr(alas_module, "del_cached_property", _record_deleted_cache(deleted))
    runner = _make_runner(method="close_game", wait_result=True)
    task = _decision("Main", datetime.now() + timedelta(minutes=1))

    assert not _wait_for_next_task(runner, task)
    assert runner.device.app_stop_calls == 1
    assert runner.device.release_calls == 1
    assert release_calls == ["release"]
    assert runner.config.task_calls == ["Restart"]
    assert deleted == ["config"]


def test_wait_for_next_task_allows_scheduled_restart_after_close_game(monkeypatch: pytest.MonkeyPatch) -> None:
    release_calls: list[str] = []
    deleted: list[str] = []
    monkeypatch.setattr(alas_module, "release_resources", lambda: release_calls.append("release"))
    monkeypatch.setattr(alas_module, "del_cached_property", _record_deleted_cache(deleted))
    runner = _make_runner(method="close_game", wait_result=True)
    task = _decision("Restart", datetime.now() + timedelta(minutes=1))

    assert _wait_for_next_task(runner, task)
    assert runner.config.task_calls == []
    assert deleted == []


def test_wait_for_next_task_can_return_to_main_page(monkeypatch: pytest.MonkeyPatch) -> None:
    release_calls: list[str] = []
    deleted: list[str] = []
    monkeypatch.setattr(alas_module, "release_resources", lambda: release_calls.append("release"))
    monkeypatch.setattr(alas_module, "del_cached_property", _record_deleted_cache(deleted))
    runner = _make_runner(method="goto_main", wait_result=True)
    task = _decision("Main", datetime.now() + timedelta(minutes=1))

    assert _wait_for_next_task(runner, task)
    assert runner.run_calls == ["goto_main"]
    assert release_calls == ["release"]
    assert runner.device.release_calls == 1
    assert deleted == []
