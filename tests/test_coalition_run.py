import pytest

from module.coalition.coalition import Coalition
from module.exception import ScriptEnd, ScriptError


class _Config:
    def __init__(self):
        self.Campaign_Event = "coalition_event"
        self.Coalition_Mode = "stage"
        self.Coalition_Fleet = "multi"
        self.StopCondition_RunCount = 2
        self.switched = False
        self.calls = []

    def task_stop(self):
        self.calls.append(("task_stop",))

    def task_switched(self):
        self.calls.append(("task_switched",))
        return self.switched


class _Device:
    def __init__(self, calls):
        self.calls = calls

    def stuck_record_clear(self):
        self.calls.append(("stuck_record_clear",))

    def click_record_clear(self):
        self.calls.append(("click_record_clear",))


class _Coalition(Coalition):
    def __init__(self):
        self.calls = []
        self.config = _Config()
        self.device = _Device(self.calls)
        self.stop_on_oil = False
        self.stop_on_pt = False
        self.event_time_limited = False
        self.execute_raises = False

    def event_time_limit_triggered(self):
        self.calls.append(("event_time_limit_triggered",))
        return self.event_time_limited

    def triggered_stop_condition(self, oil_check=False, pt_check=False):
        self.calls.append(("triggered_stop_condition", oil_check, pt_check))
        return (oil_check and self.stop_on_oil) or (pt_check and self.stop_on_pt)

    def ui_goto(self, page):
        self.calls.append(("ui_goto", page.name))

    def ui_goto_coalition(self):
        self.calls.append(("ui_goto_coalition",))

    def disable_event_on_raid(self):
        self.calls.append(("disable_event_on_raid",))

    def coalition_ensure_mode(self, event, mode):
        self.calls.append(("coalition_ensure_mode", event, mode))

    def coalition_execute_once(self, event, stage, fleet):
        self.calls.append(("coalition_execute_once", event, stage, fleet))
        if self.execute_raises:
            message = "stop"
            raise ScriptEnd(message)


def test_coalition_run_requires_arguments() -> None:
    coalition = _Coalition()
    coalition.config.Campaign_Event = ""

    with pytest.raises(ScriptError):
        coalition.run()


def test_coalition_run_executes_until_total() -> None:
    coalition = _Coalition()

    coalition.run(total=1)

    assert coalition.run_count == 1
    assert coalition.config.StopCondition_RunCount == 1
    assert ("coalition_execute_once", "coalition_event", "stage", "multi") in coalition.calls


def test_coalition_run_stops_without_increment_when_script_ends() -> None:
    coalition = _Coalition()
    coalition.execute_raises = True

    coalition.run(total=2)

    assert coalition.run_count == 0
    assert coalition.config.StopCondition_RunCount == 2


def test_coalition_run_checks_oil_before_ui_without_oil_icon() -> None:
    coalition = _Coalition()
    coalition.config.Campaign_Event = "coalition_20260122"
    coalition.stop_on_oil = True

    coalition.run(total=1)

    assert ("triggered_stop_condition", True, False) in coalition.calls
    assert not any(call[0] == "coalition_execute_once" for call in coalition.calls)
