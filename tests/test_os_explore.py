import pytest

import module.os.tasks.explore as explore_module
from module.exception import ScriptError
from module.os.tasks.explore import OpsiExplore


class _TaskStopped(Exception):
    pass


class _Zone:
    def __init__(self, zone_id) -> None:
        self.zone_id = int(zone_id)

    def __str__(self) -> str:
        return f"Zone{self.zone_id}"


class _Config:
    def __init__(self) -> None:
        self.OS_EXPLORE_FILTER = "1 > 2"
        self.OpsiExplore_LastZone = 0
        self.OpsiExplore_SpecialRadar = True
        self.OpsiFleet_Fleet = 1
        self.OpsiFleet_Submarine = False
        self.Scheduler_NextRun = "next-run"
        self.calls = []

    def multi_set(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cross_get(self, keys, default=None):
        self.calls.append(("cross_get", keys, default))
        return "old-run"

    def cross_set(self, keys, value):
        self.calls.append(("cross_set", keys, value))

    def task_delay(self, target):
        self.calls.append(("task_delay", target))

    def task_call(self, task, force_call=False):
        self.calls.append(("task_call", task, force_call))

    def task_stop(self):
        self.calls.append(("task_stop", None))
        raise _TaskStopped

    def check_task_switch(self):
        self.calls.append(("check_task_switch", None))


class _Explore(OpsiExplore):
    def __init__(self, *, globe_results, combat_results) -> None:
        self.config = _Config()
        self.globe_results = globe_results
        self.combat_results = combat_results
        self.calls = []
        self._os_explore_failed_zone = []

    @property
    def failed_zones(self):
        return self._os_explore_failed_zone

    def explore_order(self):
        return self._os_explore_order()

    def run_explore(self):
        return self._os_explore()

    def name_to_zone(self, zone):
        if zone == "bad":
            message = "bad zone"
            raise ScriptError(message)
        return _Zone(zone)

    def globe_goto(self, zone, stop_if_safe=False):
        self.calls.append(("globe_goto", zone, stop_if_safe))
        return self.globe_results[zone]

    def tuning_sample_use(self):
        self.calls.append(("tuning_sample_use", None))

    def fleet_set(self, fleet):
        self.calls.append(("fleet_set", fleet))

    def os_order_execute(self, **kwargs):
        self.calls.append(("os_order_execute", kwargs))

    def run_auto_search(self):
        self.calls.append(("run_auto_search", None))
        return self.combat_results.pop(0)

    def handle_after_auto_search(self):
        self.calls.append(("handle_after_auto_search", None))


def test_os_explore_order_resumes_after_last_zone() -> None:
    explore = _Explore(globe_results={}, combat_results=[])
    explore.config.OpsiExplore_LastZone = 1

    assert explore.explore_order() == [2]


def test_os_explore_invalid_last_zone_restarts_from_beginning() -> None:
    explore = _Explore(globe_results={}, combat_results=[])
    explore.config.OpsiExplore_LastZone = "bad"

    assert explore.explore_order() == [1, 2]


def test_os_explore_skips_safe_zone_runs_next_and_finishes(monkeypatch) -> None:
    monkeypatch.setattr(explore_module, "get_os_next_reset", lambda: "next-reset")
    explore = _Explore(globe_results={1: False, 2: True}, combat_results=[0])

    with pytest.raises(_TaskStopped):
        explore.run_explore()

    assert ("globe_goto", 1, True) in explore.calls
    assert ("globe_goto", 2, True) in explore.calls
    assert ("os_order_execute", {"recon_scan": False, "submarine_call": False}) in explore.calls
    assert explore.failed_zones == [2]
    assert explore.config.OpsiExplore_LastZone == 0
    assert ("task_delay", "next-reset") in explore.config.calls
    assert ("task_stop", None) in explore.config.calls
