from types import SimpleNamespace
from typing import TYPE_CHECKING, Never, override

import numpy as np
import pytest

from module.combat.assets import BATTLE_PREPARATION
from module.event_hospital.combat import HospitalCombat
from module.raid.raid import Raid

if TYPE_CHECKING:
    from collections.abc import Iterator

    from module.base.button import Button, MatchOffset
    from module.base.timer import Timer
    from module.base.type_alias import ImageArray


class _TaskBalanced(Exception):
    pass


class _Device:
    def __init__(self) -> None:
        self.clicks: list[Button] = []

    def click(self, button: Button) -> None:
        self.clicks.append(button)


class _Emotion:
    def __init__(self) -> None:
        self.reduced: list[int] = []

    def reduce(self, fleet_index: int) -> None:
        self.reduced.append(fleet_index)


class _SpecialCombatBase:
    def __init__(self) -> None:
        self.device = _Device()
        self.emotion = _Emotion()
        self.iterations = 3
        self.combat_results: list[bool] = []
        self.appear_then_click_results: list[bool] = []
        self.automation_results: list[bool] = []
        self.retirement_results: list[bool] = []
        self.low_emotion_results: list[bool] = []
        self.automation_confirm_results: list[bool] = []
        self.story_results: list[bool] = []

    @staticmethod
    def _next(results: list[bool]) -> bool:
        if results:
            return results.pop(0)
        return False

    def loop(self, *, skip_first: bool = True, timeout: float | Timer | None = None) -> Iterator[ImageArray]:
        del skip_first, timeout
        for _ in range(self.iterations):
            yield np.zeros((1, 1, 3), dtype=np.uint8)

    def handle_combat_automation_set(self, *, auto: bool) -> bool:
        assert auto is True
        return self._next(self.automation_results)

    def handle_retirement(self) -> bool:
        return self._next(self.retirement_results)

    def handle_combat_low_emotion(self) -> bool:
        return self._next(self.low_emotion_results)

    def appear_then_click(
        self,
        _button: Button,
        offset: MatchOffset | None = 0,
        interval: float = 0,
        similarity: float = 0.85,
        threshold: int = 30,
    ) -> bool:
        del offset, interval, similarity, threshold
        return self._next(self.appear_then_click_results)

    def handle_combat_automation_confirm(self) -> bool:
        return self._next(self.automation_confirm_results)

    def handle_story_skip(self) -> bool:
        return self._next(self.story_results)

    def is_combat_executing(self) -> bool:
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
        self.fleet_recommend_results: list[bool] = []
        self.interval_clears: list[Button | list[Button] | tuple[Button, ...] | None] = []

    @override
    def appear(
        self,
        button: Button,
        offset: MatchOffset | None = 0,
        interval: float = 0,
        similarity: float = 0.85,
        threshold: int = 10,
    ) -> bool:
        del offset, interval, similarity, threshold
        if button == BATTLE_PREPARATION:
            return self._next(self.appear_results)
        return False

    @override
    def get_oil(self, *, skip_first_screenshot: bool = True) -> int:
        del skip_first_screenshot
        return 1000

    def triggered_task_balancer(self) -> bool:
        self.task_balancer_calls += 1
        return self._next(self.task_balancer_results)

    @override
    def handle_task_balancer(self) -> Never:
        self.handle_task_balancer_count += 1
        raise _TaskBalanced

    @override
    def handle_fleet_recommend(self, *, recommend: bool = True) -> bool:
        assert recommend is True
        return self._next(self.fleet_recommend_results)

    @override
    def interval_clear(
        self,
        button: Button | list[Button] | tuple[Button, ...] | None,
        interval: float = 3,
    ) -> None:
        del interval
        self.interval_clears.append(button)


class _Raid(_SpecialCombatBase, Raid):
    config: SimpleNamespace

    def __init__(self, *, has_oil_icon: bool) -> None:
        _SpecialCombatBase.__init__(self)
        self.config = SimpleNamespace(task_stop=self._task_stop)
        self.has_oil_icon = has_oil_icon
        self.appear_results = [True]
        self.stop_condition_results: list[bool] = []
        self.stop_condition_calls: list[dict[str, bool]] = []
        self.task_stop_count = 0

    @property
    def _raid_has_oil_icon(self) -> bool:
        return self.has_oil_icon

    def _task_stop(self) -> None:
        self.task_stop_count += 1

    @override
    def appear(
        self,
        button: Button,
        offset: MatchOffset | None = 0,
        interval: float = 0,
        similarity: float = 0.85,
        threshold: int = 10,
    ) -> bool:
        del offset, interval, similarity, threshold
        if button == BATTLE_PREPARATION:
            return self._next(self.appear_results)
        return False

    @override
    def handle_raid_ticket_use(self) -> bool:
        return False

    @override
    def triggered_stop_condition(
        self,
        *,
        oil_check: bool = False,
        pt_check: bool = False,
        coin_check: bool = False,
    ) -> bool:
        checks = {"oil_check": oil_check, "pt_check": pt_check, "coin_check": coin_check}
        self.stop_condition_calls.append({name: enabled for name, enabled in checks.items() if enabled})
        return self._next(self.stop_condition_results)


def test_hospital_combat_preparation_checks_task_balancer_once() -> None:
    combat = _HospitalCombat()
    combat.combat_results = [False, True]

    with pytest.raises(_TaskBalanced):
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
