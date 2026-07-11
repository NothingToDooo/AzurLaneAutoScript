from typing import TYPE_CHECKING

import pytest

from module.exception import ScriptEnd, ScriptError
from module.ocr.ocr import Digit, DigitCounter
from module.raid.raid import (
    HuanChangCounter,
    HuanChangPtOcr,
    RaidCounter,
    RaidMode,
    pt_ocr,
    raid_name_shorten,
    raid_ocr,
)
from module.raid.run import RaidRun
from module.ui.page import Page, page_campaign_menu, page_raid, page_rpg_stage

if TYPE_CHECKING:
    from types import TracebackType
    from typing import Self

type RaidCall = (
    tuple[str] | tuple[str, Page] | tuple[str, RaidMode] | tuple[str, bool, bool, bool] | tuple[str, RaidMode, str]
)


class _Device:
    def __init__(self) -> None:
        self.stuck_clear_count = 0
        self.click_clear_count = 0

    def stuck_record_clear(self) -> None:
        self.stuck_clear_count += 1

    def click_record_clear(self) -> None:
        self.click_clear_count += 1


class _MultiSet:
    def __init__(self, calls: list[tuple[str]]) -> None:
        self.calls = calls

    def __enter__(self) -> Self:
        self.calls.append(("multi_set_enter",))
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc, traceback
        self.calls.append(("multi_set_exit",))


class _Config:
    def __init__(self) -> None:
        self.Campaign_Event = "raid_20200624"
        self.Raid_Mode = "hard"
        self.StopCondition_RunCount = 2
        self.Scheduler_Enable = True
        self.task = type("Task", (), {"command": "Raid"})()
        self.calls = []
        self.is_task_switched = False

    def task_stop(self) -> None:
        self.calls.append(("task_stop",))

    def task_switched(self) -> bool:
        self.calls.append(("task_switched",))
        return self.is_task_switched

    def multi_set(self) -> _MultiSet:
        return _MultiSet(self.calls)


class _RaidRun(RaidRun):
    config: _Config
    device: _Device

    def __init__(self) -> None:
        self.config = _Config()
        self.device = _Device()
        self.calls: list[RaidCall] = []
        self.stop_condition_results = []
        self.remain_result = 1
        self.is_rpg = False
        self.has_oil_icon = False
        self.raise_script_end = False

    @property
    def _raid_has_oil_icon(self) -> bool:
        return self.has_oil_icon

    def event_time_limit_triggered(self) -> bool:
        self.calls.append(("event_time_limit",))
        return False

    def ui_ensure(self, destination: Page, *, skip_first_screenshot: bool = True) -> bool:
        del skip_first_screenshot
        self.calls.append(("ui_ensure", destination))
        return True

    def triggered_stop_condition(
        self, *, oil_check: bool = False, pt_check: bool = False, coin_check: bool = False
    ) -> bool:
        self.calls.append(("stop_condition", oil_check, pt_check, coin_check))
        if self.stop_condition_results:
            return self.stop_condition_results.pop(0)
        return False

    def is_raid_rpg(self) -> bool:
        self.calls.append(("is_raid_rpg",))
        return self.is_rpg

    def raid_rpg_swipe(self, *, skip_first_screenshot: bool = True) -> None:
        del skip_first_screenshot
        self.calls.append(("raid_rpg_swipe",))

    def disable_event_on_raid(self) -> bool:
        self.calls.append(("disable_event_on_raid",))
        return True

    def get_remain(self, mode: RaidMode, *, skip_first_screenshot: bool = True) -> int:
        del skip_first_screenshot
        self.calls.append(("get_remain", mode))
        return self.remain_result

    def raid_execute_once(self, *, mode: RaidMode, raid: str) -> None:
        self.calls.append(("raid_execute_once", mode, raid))
        if self.raise_script_end:
            message = "end"
            raise ScriptEnd(message)


def test_raid_name_shorten_returns_asset_prefix() -> None:
    assert raid_name_shorten("raid_20200624") == "ESSEX"
    assert raid_name_shorten("raid_20260212") == "CHANGWU"


def test_raid_name_shorten_rejects_unknown_raid() -> None:
    with pytest.raises(ScriptError):
        raid_name_shorten("raid_unknown")


def test_raid_ocr_uses_configured_counter_class() -> None:
    assert isinstance(raid_ocr("raid_20200624", "easy"), RaidCounter)
    assert isinstance(raid_ocr("raid_20230118", "normal"), DigitCounter)
    assert isinstance(raid_ocr("raid_20230118", "ex"), Digit)


def test_raid_ocr_rejects_ex_without_single_value_counter() -> None:
    with pytest.raises(ScriptError, match="mode=ex"):
        raid_ocr("raid_20200624", "ex")


def test_huanchang_counter_preserves_vertical_counter_shape() -> None:
    counter = raid_ocr("raid_20240130", "hard")

    assert isinstance(counter, HuanChangCounter)
    assert counter.alphabet == "0123456789IDSB"
    assert counter.after_process("9") == (9, 0, 15)


def test_pt_ocr_uses_configured_counter_class() -> None:
    assert isinstance(pt_ocr("raid_20220630"), Digit)
    assert isinstance(pt_ocr("raid_20240130"), HuanChangPtOcr)


def test_raid_run_requires_name_and_mode() -> None:
    raid = _RaidRun()
    raid.config.Campaign_Event = ""

    with pytest.raises(ScriptError, match="arguments unfilled"):
        raid.run()


def test_raid_run_rejects_unknown_mode() -> None:
    raid = _RaidRun()
    raid.config.Raid_Mode = "nightmare"

    with pytest.raises(ScriptError, match="Invalid RaidRun mode"):
        raid.run()


def test_raid_run_executes_once_and_updates_count() -> None:
    raid = _RaidRun()
    raid.config.is_task_switched = True

    raid.run(total=1)

    assert raid.run_count == 1
    assert raid.config.StopCondition_RunCount == 1
    assert ("ui_ensure", page_campaign_menu) in raid.calls
    assert ("ui_ensure", page_raid) in raid.calls
    assert ("raid_execute_once", "hard", "raid_20200624") in raid.calls
    assert raid.config.calls == [("task_switched",), ("task_stop",)]


def test_raid_run_skips_campaign_menu_when_oil_icon_exists() -> None:
    raid = _RaidRun()
    raid.has_oil_icon = True

    raid.run(total=1)

    assert ("ui_ensure", page_campaign_menu) not in raid.calls
    assert ("ui_ensure", page_raid) in raid.calls


def test_raid_run_uses_rpg_stage_entry() -> None:
    raid = _RaidRun()
    raid.is_rpg = True

    raid.run(total=1)

    assert ("ui_ensure", page_rpg_stage) in raid.calls
    assert ("raid_rpg_swipe",) in raid.calls


def test_raid_run_stops_ex_without_ticket() -> None:
    raid = _RaidRun()
    raid.config.Raid_Mode = "ex"
    raid.remain_result = 0

    raid.run()

    assert ("get_remain", "ex") in raid.calls
    assert not [call for call in raid.calls if call[0] == "raid_execute_once"]
    assert raid.config.StopCondition_RunCount == 0
    assert raid.config.Scheduler_Enable is False
    assert raid.config.calls == [("multi_set_enter",), ("multi_set_exit",)]


def test_raid_run_breaks_on_script_end_without_counting_run() -> None:
    raid = _RaidRun()
    raid.raise_script_end = True

    raid.run()

    assert raid.run_count == 0
    assert raid.config.StopCondition_RunCount == 2
