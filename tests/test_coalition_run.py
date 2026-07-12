from typing import TYPE_CHECKING, override

import pytest

from module.coalition.coalition import Coalition
from module.exception import CampaignNameError, ScriptEnd, ScriptError

if TYPE_CHECKING:
    from module.base.button import MatchOffset
    from module.coalition.contracts import CoalitionEvent, CoalitionFleetMode, CoalitionPageMode, CoalitionStage
    from module.ui.page import Page


type _Call = tuple[str] | tuple[str, str] | tuple[str, str, str] | tuple[str, str, str, str] | tuple[str, bool, bool]


class _Config:
    def __init__(self) -> None:
        self.Campaign_Event = "coalition_20230323"
        self.Coalition_Mode = "tc1"
        self.Coalition_Fleet = "multi"
        self.StopCondition_RunCount = 2
        self.switched = False
        self.calls: list[tuple[str]] = []

    def task_stop(self) -> None:
        self.calls.append(("task_stop",))

    def task_switched(self) -> bool:
        self.calls.append(("task_switched",))
        return self.switched


class _Device:
    def __init__(self, calls: list[_Call]) -> None:
        self.calls = calls

    def stuck_record_clear(self) -> None:
        self.calls.append(("stuck_record_clear",))

    def click_record_clear(self) -> None:
        self.calls.append(("click_record_clear",))


class _Coalition(Coalition):
    config: _Config
    device: _Device

    def __init__(self) -> None:
        self.calls: list[_Call] = []
        self.config = _Config()
        self.device = _Device(self.calls)
        self.stop_on_oil = False
        self.stop_on_pt = False
        self.event_time_limited = False
        self.execute_raises = False

    def event_time_limit_triggered(self) -> bool:
        self.calls.append(("event_time_limit_triggered",))
        return self.event_time_limited

    @override
    def triggered_stop_condition(self, *, oil_check: bool = False, pt_check: bool = False) -> bool:
        self.calls.append(("triggered_stop_condition", oil_check, pt_check))
        return (oil_check and self.stop_on_oil) or (pt_check and self.stop_on_pt)

    @override
    def ui_goto(
        self,
        destination: Page,
        *,
        get_ship: bool = True,
        offset: MatchOffset | None = (30, 30),
        skip_first_screenshot: bool = True,
    ) -> None:
        del get_ship, offset, skip_first_screenshot
        self.calls.append(("ui_goto", destination.name))

    @override
    def ui_goto_coalition(self) -> bool:
        self.calls.append(("ui_goto_coalition",))
        return True

    @override
    def disable_event_on_raid(self) -> bool:
        self.calls.append(("disable_event_on_raid",))
        return True

    @override
    def coalition_ensure_mode(self, event: CoalitionEvent, mode: CoalitionPageMode) -> None:
        self.calls.append(("coalition_ensure_mode", event, mode))

    @override
    def coalition_execute_once(
        self,
        *,
        event: CoalitionEvent,
        stage: CoalitionStage,
        fleet: CoalitionFleetMode,
    ) -> None:
        self.calls.append(("coalition_execute_once", event, stage, fleet))
        if self.execute_raises:
            message = "stop"
            raise ScriptEnd(message)


def test_coalition_run_requires_arguments() -> None:
    coalition = _Coalition()
    coalition.config.Campaign_Event = ""

    with pytest.raises(ScriptError):
        coalition.run()


def test_coalition_run_rejects_unknown_event() -> None:
    coalition = _Coalition()
    coalition.config.Campaign_Event = "coalition_unknown"

    with pytest.raises(ScriptError, match="Unsupported coalition event"):
        coalition.run()


def test_coalition_run_rejects_unknown_stage() -> None:
    coalition = _Coalition()
    coalition.config.Coalition_Mode = "unknown"

    with pytest.raises(CampaignNameError, match="unknown"):
        coalition.run()


def test_coalition_run_rejects_unknown_fleet_mode() -> None:
    coalition = _Coalition()
    coalition.config.Coalition_Fleet = "unknown"

    with pytest.raises(ScriptError, match="Unsupported coalition fleet mode"):
        coalition.run()


def test_coalition_stage_name_normalizes_frostfall_alias() -> None:
    assert Coalition.handle_stage_name("coalition_20230323", " T-C3\n") == ("coalition_20230323", "tc3")


def test_coalition_run_executes_until_total() -> None:
    coalition = _Coalition()

    coalition.run(total=1)

    assert coalition.run_count == 1
    assert coalition.config.StopCondition_RunCount == 1
    assert ("coalition_execute_once", "coalition_20230323", "tc1", "multi") in coalition.calls


def test_coalition_run_stops_without_increment_when_script_ends() -> None:
    coalition = _Coalition()
    coalition.execute_raises = True

    coalition.run(total=2)

    assert coalition.run_count == 0
    assert coalition.config.StopCondition_RunCount == 2


def test_coalition_run_checks_oil_before_ui_without_oil_icon() -> None:
    coalition = _Coalition()
    coalition.config.Campaign_Event = "coalition_20260122"
    coalition.config.Coalition_Mode = "easy"
    coalition.stop_on_oil = True

    coalition.run(total=1)

    assert ("triggered_stop_condition", True, False) in coalition.calls
    assert not any(call[0] == "coalition_execute_once" for call in coalition.calls)
