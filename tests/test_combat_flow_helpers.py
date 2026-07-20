from types import SimpleNamespace
from typing import TYPE_CHECKING, override

import numpy as np

from module.combat import combat
from module.combat.auto_search_combat import AutoSearchCombat
from module.combat.combat_result_ui import STANDARD_COMBAT_RESULT_UI

if TYPE_CHECKING:
    from collections.abc import Iterator

    from module.base.button import Button, MatchOffset
    from module.base.timer import Timer
    from module.base.type_alias import ImageArray
    from module.combat.combat import CombatEnd
    from module.combat.combat_result_ui import CombatResultRuntime, CombatResultUi


class _FakeDevice:
    def __init__(self) -> None:
        self.clicks: list[Button] = []

    def click(self, button: Button) -> None:
        self.clicks.append(button)


class _EmergencyRepairContext(combat.Combat):
    config: SimpleNamespace
    device: _FakeDevice

    def __init__(
        self,
        *,
        hp: list[int | float],
        appearing: tuple[Button, ...] = (),
        confirm: bool = False,
    ) -> None:
        self.config = SimpleNamespace(
            HpControl_UseEmergencyRepair=True,
            HpControl_RepairUseSingleThreshold=0.2,
            HpControl_RepairUseMultiThreshold=0.5,
        )
        self._hp = {self.fleet_current_index: hp}
        self.appearing = set(appearing)
        self.confirm = confirm
        self.device = _FakeDevice()
        self.wait_disappear_calls: list[tuple[Button, dict[str, MatchOffset | None]]] = []
        self.wait_stable_calls: list[Button] = []
        self.interval_clears: list[Button | list[Button] | tuple[Button, ...] | None] = []

    @override
    def appear_then_click(
        self,
        button: Button,
        offset: MatchOffset | None = 0,
        interval: float = 0,
        similarity: float = 0.85,
        threshold: int = 30,
    ) -> bool:
        del offset, interval, similarity, threshold
        return button == combat.combat_assets.EMERGENCY_REPAIR_CONFIRM and self.confirm

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
        return button in self.appearing

    @override
    def wait_until_disappear(self, button: Button, offset: MatchOffset | None = 0) -> None:
        self.wait_disappear_calls.append((button, {"offset": offset}))

    @override
    def wait_until_stable(
        self,
        button: Button,
        timer: Timer | None = None,
        timeout: Timer | None = None,
        *,
        skip_first_screenshot: bool = True,
    ) -> None:
        del timer, timeout, skip_first_screenshot
        self.wait_stable_calls.append(button)

    @override
    def interval_clear(
        self,
        button: Button | list[Button] | tuple[Button, ...] | None,
        interval: float = 3,
    ) -> None:
        del interval
        self.interval_clears.append(button)


class _CombatLoopContext(combat.Combat):
    device: SimpleNamespace

    def __init__(self, *, iterations: int) -> None:
        self.iterations = iterations
        self.device = SimpleNamespace(
            screenshot_interval_set=lambda *_args, **_kwargs: None,
            stuck_record_clear=lambda: None,
            click_record_clear=lambda: None,
        )

    def loop(self, *, skip_first: bool = True, timeout: float | Timer | None = None) -> Iterator[ImageArray]:
        del skip_first, timeout
        for _ in range(self.iterations):
            yield np.zeros((1, 1, 3), dtype=np.uint8)


class _CombatExecuteContext(_CombatLoopContext):
    def __init__(self) -> None:
        super().__init__(iterations=2)
        self.popup_calls = []
        self.status_calls = 0

    def submarine_call_reset(self) -> None:
        pass

    def combat_auto_reset(self) -> None:
        pass

    def combat_manual_reset(self) -> None:
        pass

    @override
    def handle_combat_automation_confirm(self) -> bool:
        return False

    @override
    def handle_story_skip(self) -> bool:
        return False

    @override
    def handle_combat_auto(self, auto: str) -> bool:
        del auto
        return False

    @override
    def handle_combat_manual(self, auto: str) -> bool:
        del auto
        return False

    @override
    def handle_submarine_call(self, submarine: str = "do_not_use") -> bool:
        del submarine
        return False

    @override
    def handle_popup_confirm(
        self,
        name: str = "",
        offset: MatchOffset | None = None,
        interval: float = 2,
    ) -> bool:
        del offset, interval
        self.popup_calls.append(name)
        return len(self.popup_calls) == 1

    @override
    def handle_urgent_commission(self) -> bool:
        return False

    @override
    def handle_guild_popup_cancel(self) -> bool:
        return False

    @override
    def handle_vote_popup(self) -> bool:
        return False

    @override
    def handle_mission_popup_ack(self) -> bool:
        return False

    def handle_battle_status(self) -> bool:
        self.status_calls += 1
        return True

    @override
    def handle_get_items(self) -> bool:
        return False


class _CombatStatusContext(_CombatLoopContext):
    config: SimpleNamespace

    def __init__(self, *, iterations: int = 1) -> None:
        super().__init__(iterations=iterations)
        self.config = SimpleNamespace(GET_SHIP_TRIGGERED=False)
        self.story_skip_results: list[bool] = []
        self.get_ship_results: list[bool] = []
        self.get_items_results: list[bool] = []
        self.popup_results: list[bool] = []
        self.battle_status_results: list[bool] = []
        self.exp_info_results: list[bool] = []
        self.in_stage_results: list[bool] = []
        self.enemy_searching_results: list[bool] = []
        self.auto_search_exit_results: list[bool] = []
        self.mis_click_results: list[bool] = []
        self.appear_calls: list[tuple[Button, dict[str, MatchOffset | None]]] = []
        self.battle_status_calls = 0

    @staticmethod
    def _next(results: list[bool]) -> bool:
        if results:
            return results.pop(0)
        return False

    def handle_story_skip(self) -> bool:
        return self._next(self.story_skip_results)

    def handle_get_ship(self) -> bool:
        return self._next(self.get_ship_results)

    def handle_get_items(self) -> bool:
        return self._next(self.get_items_results)

    def handle_popup_confirm(
        self,
        name: str = "",
        offset: MatchOffset | None = None,
        interval: float = 2,
    ) -> bool:
        del name, offset, interval
        return self._next(self.popup_results)

    def handle_battle_status(self) -> bool:
        self.battle_status_calls += 1
        return self._next(self.battle_status_results)

    def handle_exp_info(self) -> bool:
        return self._next(self.exp_info_results)

    @override
    def handle_urgent_commission(self) -> bool:
        return False

    @override
    def handle_guild_popup_cancel(self) -> bool:
        return False

    @override
    def handle_vote_popup(self) -> bool:
        return False

    @override
    def handle_mission_popup_ack(self) -> bool:
        return False

    def handle_auto_search_exit(self) -> bool:
        return self._next(self.auto_search_exit_results)

    def handle_combat_mis_click(self) -> bool:
        return self._next(self.mis_click_results)

    def handle_in_stage(self) -> bool:
        return self._next(self.in_stage_results)

    def handle_in_map_with_enemy_searching(self) -> bool:
        return self._next(self.enemy_searching_results)

    @override
    def handle_in_map_no_enemy_searching(self) -> bool:
        return False

    def appear(
        self,
        button: Button,
        offset: MatchOffset | None = 0,
        interval: float = 0,
        similarity: float = 0.85,
        threshold: int = 10,
    ) -> bool:
        del interval, similarity, threshold
        self.appear_calls.append((button, {"offset": offset}))
        return button == combat.BACK_ARROW and offset == (30, 30)

    def install_combat_result_ui(self, result_ui: CombatResultUi) -> None:
        self._combat_result_ui = result_ui

    def handle_status_progress(
        self,
        *,
        battle_status: bool,
        exp_info: bool,
    ) -> tuple[bool, bool, bool]:
        return self._handle_combat_status_progress(
            battle_status=battle_status,
            exp_info=exp_info,
        )


class _CombatResultProbe:
    def __init__(self, *, results: tuple[bool, ...]) -> None:
        self.results = list(results)
        self.calls: list[CombatResultRuntime] = []

    def handle_experience_result(self, runtime: CombatResultRuntime) -> bool:
        self.calls.append(runtime)
        return self.results.pop(0)


class _AutoSearchResultContext(AutoSearchCombat):
    def __init__(self, result_ui: CombatResultUi) -> None:
        self._combat_result_ui = result_ui
        self._auto_search_status_confirm = True
        self.exp_info_hook_calls = 0

    @override
    def handle_get_ship(self) -> bool:
        return False

    @override
    def handle_get_items(self) -> bool:
        return False

    @override
    def handle_battle_status(self) -> bool:
        return False

    @override
    def handle_popup_confirm(
        self,
        name: str = "",
        offset: MatchOffset | None = None,
        interval: float = 2,
    ) -> bool:
        del name, offset, interval
        return False

    def handle_exp_info(self) -> bool:
        self.exp_info_hook_calls += 1
        return True

    def handle_status_confirm(self) -> tuple[bool, bool]:
        return self._handle_auto_search_status_confirm(exp_info=False)


class _CombatOrchestrationContext(combat.Combat):
    config: SimpleNamespace

    def __init__(self) -> None:
        self.config = SimpleNamespace(
            HpControl_UseHpBalance=True,
            Fleet_Fleet1Mode="combat_auto",
            Fleet_Fleet2Mode="combat_manual",
            Submarine_Fleet=True,
            Submarine_Mode="every_combat",
        )
        vars(self)["emotion"] = SimpleNamespace(is_calculate=False)
        self.preparation_calls: list[dict[str, bool | str | int]] = []
        self.execute_calls: list[dict[str, str]] = []
        self.status_calls: list[dict[str, CombatEnd | None]] = []

    def combat_preparation(
        self,
        *,
        balance_hp: bool = False,
        emotion_reduce: bool = False,
        auto: str = "combat_auto",
        fleet_index: int = 1,
    ) -> None:
        self.preparation_calls.append(
            {
                "balance_hp": balance_hp,
                "emotion_reduce": emotion_reduce,
                "auto": auto,
                "fleet_index": fleet_index,
            }
        )

    def combat_execute(self, *, auto: str = "combat_auto", submarine: str = "do_not_use") -> None:
        self.execute_calls.append({"auto": auto, "submarine": submarine})

    def combat_status(self, expected_end: CombatEnd | None = None) -> None:
        self.status_calls.append({"expected_end": expected_end})


def test_combat_orchestrates_config_defaults_for_selected_fleet() -> None:
    handler = _CombatOrchestrationContext()

    def expected_end() -> bool:
        return False

    handler.combat(expected_end=expected_end, fleet_index=2)

    assert handler.preparation_calls == [
        {
            "balance_hp": True,
            "emotion_reduce": False,
            "auto": "combat_manual",
            "fleet_index": 2,
        }
    ]
    assert handler.execute_calls == [{"auto": "combat_manual", "submarine": "every_combat"}]
    assert handler.status_calls == [{"expected_end": expected_end}]


def test_handle_emergency_repair_use_clicks_when_hp_crosses_threshold() -> None:
    context = _EmergencyRepairContext(
        hp=[0.1, 1, 1, 1, 1, 1],
        appearing=(
            combat.combat_assets.BATTLE_PREPARATION,
            combat.combat_assets.EMERGENCY_REPAIR_AVAILABLE,
        ),
    )

    assert combat.Combat.handle_emergency_repair_use(context) is True
    assert context.device.clicks == [combat.combat_assets.EMERGENCY_REPAIR_AVAILABLE]
    assert context.interval_clears == [combat.combat_assets.EMERGENCY_REPAIR_CONFIRM]
    assert context.wait_disappear_calls == [(combat.combat_assets.MAIN_FLEET_POWER_ZERO, {"offset": (20, 20)})]
    assert len(context.wait_stable_calls) == 1


def test_handle_emergency_repair_use_keeps_confirm_popup_fast_path() -> None:
    context = _EmergencyRepairContext(hp=[1, 1, 1, 1, 1, 1], confirm=True)

    assert combat.Combat.handle_emergency_repair_use(context) is True
    assert context.wait_disappear_calls == []
    assert context.device.clicks == []


def test_combat_execute_uses_common_popup_handler_before_status_end() -> None:
    handler = _CombatExecuteContext()

    handler.combat_execute(auto="combat_auto", submarine="every_combat")

    assert handler.popup_calls == ["COMBAT_EXECUTE", "COMBAT_EXECUTE"]
    assert handler.status_calls == 1


def test_combat_status_expected_end_uses_named_handlers() -> None:
    handler = _CombatStatusContext()
    handler.enemy_searching_results = [True]

    handler.combat_status(expected_end="with_searching")

    assert handler.enemy_searching_results == []
    assert handler.battle_status_calls == 0


def test_combat_status_expected_end_supports_in_ui() -> None:
    handler = _CombatStatusContext()

    handler.combat_status(expected_end="in_ui")

    assert handler.appear_calls == [(combat.BACK_ARROW, {"offset": (30, 30)})]
    assert handler.battle_status_calls == 0


def test_combat_status_locks_new_ship_after_status_popup() -> None:
    handler = _CombatStatusContext(iterations=3)
    handler.battle_status_results = [True]
    handler.popup_results = [False, True]
    expected_results = [False, False, True]

    handler.combat_status(expected_end=lambda: expected_results.pop(0))

    assert handler.config.GET_SHIP_TRIGGERED is True


def test_combat_status_checks_exp_info_first_after_battle_status() -> None:
    handler = _CombatStatusContext(iterations=3)
    handler.battle_status_results = [True, True]
    handler.exp_info_results = [True]
    expected_results = [False, False, True]

    handler.combat_status(expected_end=lambda: expected_results.pop(0))

    assert handler.battle_status_calls == 1


def test_standard_combat_result_uses_non_declarative_virtual_override() -> None:
    handler = _CombatStatusContext()
    handler.exp_info_results = [True]

    assert STANDARD_COMBAT_RESULT_UI.handle_experience_result(handler)
    assert handler.exp_info_results == []


def test_combat_status_progress_uses_injected_result_ui_in_both_branches() -> None:
    handler = _CombatStatusContext()
    probe = _CombatResultProbe(results=(True, True))
    handler.install_combat_result_ui(probe)
    handler.exp_info_results = [True]

    assert handler.handle_status_progress(battle_status=True, exp_info=False) == (True, True, True)
    handler.battle_status_results = [False]
    assert handler.handle_status_progress(battle_status=False, exp_info=False) == (True, False, True)

    assert probe.calls == [handler, handler]
    assert handler.exp_info_results == [True]


def test_auto_search_status_confirm_uses_injected_result_ui() -> None:
    probe = _CombatResultProbe(results=(True,))
    handler = _AutoSearchResultContext(probe)

    assert handler.handle_status_confirm() == (True, True)
    assert probe.calls == [handler]
    assert handler.exp_info_hook_calls == 0
