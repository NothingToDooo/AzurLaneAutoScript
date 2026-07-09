from types import SimpleNamespace

from module.combat import combat


class _FakeDevice:
    def __init__(self) -> None:
        self.clicks: list[object] = []

    def click(self, button) -> None:
        self.clicks.append(button)


class _EmergencyRepairContext(combat.Combat):
    config: SimpleNamespace
    device: _FakeDevice

    def __init__(self, *, hp, appearing=(), confirm=False) -> None:
        self.config = SimpleNamespace(
            HpControl_UseEmergencyRepair=True,
            HpControl_RepairUseSingleThreshold=0.2,
            HpControl_RepairUseMultiThreshold=0.5,
        )
        self._hp = {self.fleet_current_index: hp}
        self.appearing = set(appearing)
        self.confirm = confirm
        self.device = _FakeDevice()
        self.wait_disappear_calls = []
        self.wait_stable_calls = []
        self.interval_clears = []

    def appear_then_click(self, button, *_args: object, **_kwargs):
        return button == combat.combat_assets.EMERGENCY_REPAIR_CONFIRM and self.confirm

    def appear(self, button, *_args: object, **_kwargs):
        return button in self.appearing

    def wait_until_disappear(self, button, *_args: object, **kwargs) -> None:
        self.wait_disappear_calls.append((button, kwargs))

    def wait_until_stable(self, button, *_args: object, **_kwargs: object) -> None:
        self.wait_stable_calls.append(button)

    def interval_clear(self, button, *_args: object, **_kwargs: object) -> None:
        self.interval_clears.append(button)


class _CombatLoopContext(combat.Combat):
    device: SimpleNamespace

    def __init__(self, *, iterations) -> None:
        self.iterations = iterations
        self.device = SimpleNamespace(
            screenshot_interval_set=lambda *_args, **_kwargs: None,
            stuck_record_clear=lambda: None,
            click_record_clear=lambda: None,
        )

    def loop(self, *_args: object, **_kwargs: object):
        yield from range(self.iterations)


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

    def handle_combat_automation_confirm(self):
        return False

    def handle_story_skip(self):
        return False

    def handle_combat_auto(self, auto, *_args: object, **_kwargs: object):
        _ = auto
        return False

    def handle_combat_manual(self, auto, *_args: object, **_kwargs: object):
        _ = auto
        return False

    def handle_submarine_call(self, submarine="do_not_use", *_args: object, **_kwargs: object):
        _ = submarine
        return False

    def handle_popup_confirm(self, name="", offset=None, interval=2):
        _ = (name, offset, interval)
        self.popup_calls.append(name)
        return len(self.popup_calls) == 1

    def handle_urgent_commission(self):
        return False

    def handle_guild_popup_cancel(self):
        return False

    def handle_vote_popup(self):
        return False

    def handle_mission_popup_ack(self):
        return False

    def handle_battle_status(self):
        self.status_calls += 1
        return True

    def handle_get_items(self):
        return False


class _CombatStatusContext(_CombatLoopContext):
    config: SimpleNamespace

    def __init__(self, *, iterations=1) -> None:
        super().__init__(iterations=iterations)
        self.config = SimpleNamespace(GET_SHIP_TRIGGERED=False)
        self.story_skip_results = []
        self.get_ship_results = []
        self.get_items_results = []
        self.popup_results = []
        self.battle_status_results = []
        self.exp_info_results = []
        self.in_stage_results = []
        self.enemy_searching_results = []
        self.auto_search_exit_results = []
        self.mis_click_results = []
        self.appear_calls = []
        self.battle_status_calls = 0

    @staticmethod
    def _next(results):
        if results:
            return results.pop(0)
        return False

    def handle_story_skip(self):
        return self._next(self.story_skip_results)

    def handle_get_ship(self):
        return self._next(self.get_ship_results)

    def handle_get_items(self):
        return self._next(self.get_items_results)

    def handle_popup_confirm(self, name="", offset=None, interval=2):
        _ = (name, offset, interval)
        return self._next(self.popup_results)

    def handle_battle_status(self):
        self.battle_status_calls += 1
        return self._next(self.battle_status_results)

    def handle_exp_info(self):
        return self._next(self.exp_info_results)

    def handle_urgent_commission(self):
        return False

    def handle_guild_popup_cancel(self):
        return False

    def handle_vote_popup(self):
        return False

    def handle_mission_popup_ack(self):
        return False

    def handle_auto_search_exit(self):
        return self._next(self.auto_search_exit_results)

    def handle_combat_mis_click(self):
        return self._next(self.mis_click_results)

    def handle_in_stage(self):
        return self._next(self.in_stage_results)

    def handle_in_map_with_enemy_searching(self):
        return self._next(self.enemy_searching_results)

    def handle_in_map_no_enemy_searching(self):
        return False

    def appear(self, button, *_args: object, **kwargs):
        self.appear_calls.append((button, kwargs))
        return button == combat.BACK_ARROW and kwargs == {"offset": (30, 30)}


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
        self.preparation_calls = []
        self.execute_calls = []
        self.status_calls = []

    def combat_preparation(self, *_args: object, **kwargs) -> None:
        self.preparation_calls.append(kwargs)

    def combat_execute(self, *_args: object, **kwargs) -> None:
        self.execute_calls.append(kwargs)

    def combat_status(self, *_args: object, **kwargs) -> None:
        self.status_calls.append(kwargs)


def test_combat_orchestrates_config_defaults_for_selected_fleet() -> None:
    handler = _CombatOrchestrationContext()
    expected_end = object()

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
