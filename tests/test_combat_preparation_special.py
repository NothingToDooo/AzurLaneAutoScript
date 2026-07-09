from types import SimpleNamespace

from module.combat.assets import BATTLE_PREPARATION
from module.event_hospital.combat import HospitalCombat
from module.raid.raid import Raid


class _Device:
    def __init__(self) -> None:
        self.clicks = []

    def click(self, button) -> None:
        self.clicks.append(button)


class _Emotion:
    def __init__(self) -> None:
        self.reduced = []

    def reduce(self, fleet_index) -> None:
        self.reduced.append(fleet_index)


class _SpecialCombatBase:
    def __init__(self) -> None:
        self.device = _Device()
        self.emotion = _Emotion()
        self.combat_results = []
        self.appear_then_click_results = []
        self.automation_results = []
        self.retirement_results = []
        self.low_emotion_results = []
        self.automation_confirm_results = []
        self.story_results = []

    @staticmethod
    def _next(results):
        if results:
            return results.pop(0)
        return False

    def loop(self):
        yield from range(3)

    def handle_combat_automation_set(self, *, auto):
        assert auto is True
        return self._next(self.automation_results)

    def handle_retirement(self):
        return self._next(self.retirement_results)

    def handle_combat_low_emotion(self):
        return self._next(self.low_emotion_results)

    def appear_then_click(self, _button, **_kwargs):
        return self._next(self.appear_then_click_results)

    def handle_combat_automation_confirm(self):
        return self._next(self.automation_confirm_results)

    def handle_story_skip(self):
        return self._next(self.story_results)

    def is_combat_executing(self):
        return self._next(self.combat_results)


class _HospitalCombat(_SpecialCombatBase, HospitalCombat):
    config: SimpleNamespace

    def __init__(self) -> None:
        super().__init__()
        self.config = SimpleNamespace(
            StopCondition_OilLimit=0,
            TaskBalancer_Enable=True,
            Hospital_UseRecommendFleet=True,
        )
        self.appear_results = [True, True]
        self.task_balancer_results = [True, True]
        self.task_balancer_calls = 0
        self.handle_task_balancer_count = 0
        self.fleet_recommend_results = []
        self.interval_clears = []

    def appear(self, button, **_kwargs):
        if button == BATTLE_PREPARATION:
            return self._next(self.appear_results)
        return False

    def get_oil(self):
        return 1000

    def triggered_task_balancer(self):
        self.task_balancer_calls += 1
        return self._next(self.task_balancer_results)

    def handle_task_balancer(self):
        self.handle_task_balancer_count += 1

    def handle_fleet_recommend(self, *, recommend):
        assert recommend is True
        return self._next(self.fleet_recommend_results)

    def interval_clear(self, button) -> None:
        self.interval_clears.append(button)


class _Raid(_SpecialCombatBase, Raid):
    config: SimpleNamespace

    def __init__(self, *, has_oil_icon: bool) -> None:
        _SpecialCombatBase.__init__(self)
        self.config = SimpleNamespace(task_stop=self._task_stop)
        self.has_oil_icon = has_oil_icon
        self.appear_results = [True]
        self.stop_condition_results = []
        self.stop_condition_calls = []
        self.task_stop_count = 0

    @property
    def _raid_has_oil_icon(self):
        return self.has_oil_icon

    def _task_stop(self) -> None:
        self.task_stop_count += 1

    def appear(self, button, **_kwargs):
        if button == BATTLE_PREPARATION:
            return self._next(self.appear_results)
        return False

    def handle_raid_ticket_use(self):
        return False

    def triggered_stop_condition(self, **kwargs):
        self.stop_condition_calls.append(kwargs)
        return self._next(self.stop_condition_results)


def test_hospital_combat_preparation_checks_task_balancer_once() -> None:
    combat = _HospitalCombat()
    combat.combat_results = [False, True]

    combat.combat_preparation()

    assert combat.task_balancer_calls == 1
    assert combat.handle_task_balancer_count == 1


def test_raid_combat_preparation_checks_stop_condition_once_when_oil_icon_visible() -> None:
    raid = _Raid(has_oil_icon=True)
    raid.stop_condition_results = [True]
    raid.combat_results = [True]

    raid.combat_preparation()

    assert raid.stop_condition_calls == [{"oil_check": True, "coin_check": True}]
    assert raid.task_stop_count == 1


def test_raid_combat_preparation_skips_stop_condition_without_oil_icon() -> None:
    raid = _Raid(has_oil_icon=False)
    raid.combat_results = [True]

    raid.combat_preparation()

    assert raid.stop_condition_calls == []
    assert raid.task_stop_count == 0
