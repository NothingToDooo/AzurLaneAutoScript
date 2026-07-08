from types import SimpleNamespace

import pytest

from module.campaign.run import CampaignRun

AFTER_RUN_METHOD = "_handle_campaign_after_run"


class _TaskStopped(Exception):
    pass


class _AfterRunConfig:
    def __init__(self) -> None:
        self.StopCondition_RunCount = 0
        self.is_task_switched = False
        self.task_stop_calls = 0

    def task_switched(self) -> bool:
        return self.is_task_switched

    def task_stop(self) -> None:
        self.task_stop_calls += 1
        raise _TaskStopped


class _AfterRunCampaign:
    def __init__(self) -> None:
        self.config = SimpleNamespace(MAP_IS_ONE_TIME_STAGE=False)
        self.map_stop_calls = 0
        self.auto_search_exit_calls = 0

    def handle_map_stop(self) -> None:
        self.map_stop_calls += 1

    def ensure_auto_search_exit(self) -> None:
        self.auto_search_exit_calls += 1


def _make_runner(*, stop_triggered: bool = False):
    runner = object.__new__(CampaignRun)
    runner.config = _AfterRunConfig()
    runner.campaign = _AfterRunCampaign()
    runner.run_count = 0
    runner.is_stage_loop = False
    runner.stop_oil_checks = []

    def triggered_stop_condition(*, oil_check: bool = True) -> bool:
        runner.stop_oil_checks.append(oil_check)
        return stop_triggered

    runner.triggered_stop_condition = triggered_stop_condition
    return runner


def _handle_after_run(runner) -> bool:
    return getattr(runner, AFTER_RUN_METHOD)()


def test_after_run_updates_run_count() -> None:
    runner = _make_runner()
    runner.config.StopCondition_RunCount = 2

    assert not _handle_after_run(runner)
    assert runner.run_count == 1
    assert runner.config.StopCondition_RunCount == 1


def test_after_run_stops_when_stop_condition_triggers() -> None:
    runner = _make_runner(stop_triggered=True)
    runner.config.StopCondition_RunCount = 2

    assert _handle_after_run(runner)
    assert runner.run_count == 1
    assert runner.config.StopCondition_RunCount == 1


def test_after_run_stops_on_one_time_stage() -> None:
    runner = _make_runner()
    runner.campaign.config.MAP_IS_ONE_TIME_STAGE = True

    assert _handle_after_run(runner)
    assert runner.campaign.map_stop_calls == 1


def test_after_run_stops_on_stage_loop() -> None:
    runner = _make_runner()
    runner.is_stage_loop = True

    assert _handle_after_run(runner)


def test_after_run_stops_on_scheduler_switch() -> None:
    runner = _make_runner()
    runner.config.is_task_switched = True

    with pytest.raises(_TaskStopped):
        _handle_after_run(runner)

    assert runner.campaign.auto_search_exit_calls == 1
    assert runner.config.task_stop_calls == 1
