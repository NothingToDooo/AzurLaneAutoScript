from types import SimpleNamespace

import pytest

from module.campaign.run import CampaignRun

AFTER_RUN_METHOD = "_handle_campaign_after_run"
ENSURE_UI_METHOD = "_ensure_campaign_run_ui"


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


class _RunDevice:
    def __init__(self) -> None:
        self.has_cached_image = True
        self.image = "cached"
        self.stuck_clear_calls = 0
        self.click_clear_calls = 0
        self.screenshot_calls = 0

    def stuck_record_clear(self) -> None:
        self.stuck_clear_calls += 1

    def click_record_clear(self) -> None:
        self.click_clear_calls += 1

    def screenshot(self) -> None:
        self.screenshot_calls += 1
        self.has_cached_image = True
        self.image = "fresh"


class _RunCampaign:
    def __init__(self) -> None:
        self.device = SimpleNamespace(image=None)
        self.in_map = False
        self.in_auto_search_menu = False
        self.withdraw_calls = 0
        self.ensure_calls: list[tuple[str, str]] = []

    def is_in_map(self) -> bool:
        return self.in_map

    def is_in_auto_search_menu(self) -> bool:
        return self.in_auto_search_menu

    def withdraw(self) -> None:
        self.withdraw_calls += 1

    def ensure_campaign_ui(self, *, name: str, mode: str) -> None:
        self.ensure_calls.append((name, mode))


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


def _make_ui_runner(*, auto_search_continue: bool = False):
    runner = object.__new__(CampaignRun)
    runner.device = _RunDevice()
    runner.campaign = _RunCampaign()
    runner.stage = "d3"
    runner.disable_raid_calls = 0
    runner.commission_notice_calls = 0

    def can_use_auto_search_continue() -> bool:
        return auto_search_continue

    def disable_raid_on_event() -> None:
        runner.disable_raid_calls += 1

    def handle_commission_notice() -> None:
        runner.commission_notice_calls += 1

    runner.can_use_auto_search_continue = can_use_auto_search_continue
    runner.disable_raid_on_event = disable_raid_on_event
    runner.handle_commission_notice = handle_commission_notice
    return runner


def _handle_after_run(runner) -> bool:
    return getattr(runner, AFTER_RUN_METHOD)()


def _ensure_run_ui(runner, mode: str = "normal") -> None:
    getattr(runner, ENSURE_UI_METHOD)(mode)


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


def test_ensure_run_ui_takes_fresh_screenshot_when_needed() -> None:
    runner = _make_ui_runner()
    runner.device.has_cached_image = False

    _ensure_run_ui(runner, mode="hard")

    assert runner.device.stuck_clear_calls == 1
    assert runner.device.click_clear_calls == 1
    assert runner.device.screenshot_calls == 1
    assert runner.campaign.device.image == "fresh"
    assert runner.campaign.ensure_calls == [("d3", "hard")]
    assert runner.disable_raid_calls == 1
    assert runner.commission_notice_calls == 1


def test_ensure_run_ui_retreats_when_already_in_map() -> None:
    runner = _make_ui_runner()
    runner.campaign.in_map = True

    _ensure_run_ui(runner)

    assert runner.campaign.withdraw_calls == 1
    assert runner.campaign.ensure_calls == [("d3", "normal")]


def test_ensure_run_ui_keeps_usable_auto_search_menu() -> None:
    runner = _make_ui_runner(auto_search_continue=True)
    runner.campaign.in_auto_search_menu = True

    _ensure_run_ui(runner)

    assert runner.campaign.ensure_calls == []


def test_ensure_run_ui_closes_unusable_auto_search_menu() -> None:
    runner = _make_ui_runner(auto_search_continue=False)
    runner.campaign.in_auto_search_menu = True

    _ensure_run_ui(runner)

    assert runner.campaign.ensure_calls == [("d3", "normal")]
