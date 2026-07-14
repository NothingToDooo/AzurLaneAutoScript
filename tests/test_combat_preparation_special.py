from types import SimpleNamespace
from typing import TYPE_CHECKING, override

import numpy as np

from module.combat.assets import BATTLE_PREPARATION
from module.event_hospital.combat import HospitalCombat
from module.raid.raid import Raid

if TYPE_CHECKING:
    from collections.abc import Iterator

    from module.base.button import Button, MatchOffset
    from module.base.timer import Timer
    from module.base.type_alias import ImageArray


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
            Hospital_UseRecommendFleet=True,
        )
        self.appear_results = [True, True]
        self.oil_checks = 0
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
        self.oil_checks += 1
        return 1000

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
    def __init__(self) -> None:
        _SpecialCombatBase.__init__(self)
        self.appear_results = [True]

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


def test_hospital_combat_preparation_checks_oil_once_without_scheduler_control() -> None:
    combat = _HospitalCombat()
    combat.combat_results = [False, True]

    combat.combat_preparation()

    assert combat.oil_checks == 1
    assert not hasattr(combat, "triggered_task_balancer")


def test_raid_combat_preparation_does_not_own_scheduler_stop_conditions() -> None:
    raid = _Raid()
    raid.combat_results = [True]

    raid.combat_preparation()

    assert not hasattr(raid, "triggered_stop_condition")
