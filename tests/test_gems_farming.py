from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast, override

import pytest

from module.base.button import Button
from module.campaign import gems_farming as gems_module
from module.campaign.gems_farming import (
    GemsEmotion,
    GemsFleetReplacement,
    GemsShipReplacementDisposition,
    GemsShipReplacementFactSink,
    GemsShipReplacementResult,
)
from module.exception import CampaignEnd
from module.retire.scanner import Ship

if TYPE_CHECKING:
    from collections.abc import Iterator

    from module.base.button import MatchOffset
    from module.base.timer import Timer
    from module.base.type_alias import ImageArray
    from module.campaign.campaign_engine import CampaignEngine
    from module.config.config import AzurLaneConfig


class _FleetEmotion:
    value_name = "Emotion_Fleet1Value"

    def __init__(self, *, recovered: datetime) -> None:
        self.current = 100
        self.recovered = recovered
        self.update_count = 0

    @property
    def value(self) -> int:
        return self.current

    def update(self) -> None:
        self.update_count += 1

    def get_recovered(self, expected_reduce: int = 0) -> datetime:
        self.expected_reduce = expected_reduce
        return self.recovered


class _EmotionConfig:
    Emotion_Mode = "calculate"
    Campaign_Use2xBook = False
    GEMS_EMOTION_TRIGGERED = False

    def __init__(self) -> None:
        self.records: list[dict[str, int]] = []

    def set_record(self, **kwargs: int) -> None:
        self.records.append(kwargs)


def test_gems_emotion_tracks_only_attacking_fleet_and_requests_change() -> None:
    emotion = object.__new__(GemsEmotion)
    emotion.config = _EmotionConfig()
    attack = _FleetEmotion(recovered=datetime.now() + timedelta(minutes=10))
    support = _FleetEmotion(recovered=datetime.now() - timedelta(minutes=10))
    emotion.fleet_1 = attack
    emotion.fleet_2 = support
    emotion.fleets = [attack, support]

    with pytest.raises(CampaignEnd, match=gems_module.EMOTION_CONTROL_MESSAGE):
        emotion.check_reduce(3)

    assert attack.update_count == 1
    assert support.update_count == 0
    assert attack.expected_reduce == 6
    assert emotion.config.GEMS_EMOTION_TRIGGERED is True
    assert emotion.config.records == [{"Emotion_Fleet1Value": 100}]


def test_gems_emotion_uses_fleet1_as_logical_ledger_for_second_attack_slot() -> None:
    emotion = object.__new__(GemsEmotion)
    emotion.config = _EmotionConfig()
    attack_ledger = _FleetEmotion(recovered=datetime.now())
    physical_fleet_2_record = _FleetEmotion(recovered=datetime.now())
    emotion.fleet_1 = attack_ledger
    emotion.fleet_2 = physical_fleet_2_record
    emotion.fleets = [attack_ledger, physical_fleet_2_record]
    emotion.total_reduced = 0

    emotion.reduce(fleet_index=2)

    assert attack_ledger.current == 98
    assert physical_fleet_2_record.current == 100
    assert emotion.config.records == [{"Emotion_Fleet1Value": 98}]


class _StageNavigator:
    def __init__(self, entrance: Button) -> None:
        self.entrance = entrance
        self.calls: list[tuple[str, str]] = []

    def select(
        self,
        name: str,
        mode: str = "normal",
        *,
        skip_first_screenshot: bool = True,
    ) -> Button:
        del skip_first_screenshot
        self.calls.append((name, mode))
        return self.entrance


class _ReachedTimer:
    def __init__(self, seconds: float) -> None:
        self.seconds = seconds
        self.reset_count = 0

    def reached(self) -> bool:
        return self.seconds >= 0

    def reset(self) -> None:
        self.reset_count += 1


class _HardFleetNavigationRunner(GemsFleetReplacement):
    def __init__(self, navigator: _StageNavigator) -> None:
        self.config = cast(
            "AzurLaneConfig",
            SimpleNamespace(
                Campaign_Mode="hard",
                Campaign_Name="12-4",
                Fleet_FleetOrder="fleet1_all_fleet2_standby",
            ),
        )
        self.campaign = cast(
            "CampaignEngine",
            SimpleNamespace(
                stage_navigator=navigator,
                handle_map_mode_switch=lambda _mode: False,
                handle_map_preparation=lambda: False,
                handle_retirement=lambda: False,
            ),
        )
        self.fleet_visible = [False, False, True]
        self.clicked: list[Button] = []

    @override
    def loop(self, *, skip_first: bool = True, timeout: float | Timer | None = None) -> Iterator[ImageArray]:
        del skip_first, timeout
        yield cast("ImageArray", object())
        yield cast("ImageArray", object())

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
        return self.fleet_visible.pop(0) if button is gems_module.FLEET_PREPARATION else False

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
        self.clicked.append(button)
        return True


def test_hard_fleet_navigation_uses_the_explicit_selected_entrance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entrance = Button(area=(), color=(), button=(1, 2, 3, 4), name="hard")
    navigator = _StageNavigator(entrance)
    runner = _HardFleetNavigationRunner(navigator)
    monkeypatch.setattr(gems_module, "Timer", _ReachedTimer)

    runner._goto_hard_fleet()  # ruff:ignore[private-member-access] - 验证换舰 UI 的入口传递边界。

    assert navigator.calls == [("12-4", "hard")]
    assert runner.clicked == [entrance]
    assert entrance.area == entrance.button


class _HardFleetPrepareResultRunner(GemsFleetReplacement):
    def __init__(
        self,
        *,
        flagship_result: GemsShipReplacementResult,
        vanguard_result: GemsShipReplacementResult,
        current_emotion: int = 100,
    ) -> None:
        self.records: list[dict[str, int]] = []

        def set_record(**kwargs: int) -> None:
            self.records.append(kwargs)

        config = SimpleNamespace(
            Campaign_Mode="hard",
            Fleet_FleetOrder="fleet1_all_fleet2_standby",
            set_record=set_record,
        )
        self.config = cast(
            "AzurLaneConfig",
            config,
        )
        self.campaign = cast(
            "CampaignEngine",
            SimpleNamespace(
                config=config,
                emotion=SimpleNamespace(
                    fleet_1=SimpleNamespace(current=current_emotion),
                    update=lambda: None,
                ),
            ),
        )
        self.flagship_result = flagship_result
        self.vanguard_result = vanguard_result
        self.change_calls: list[str] = []

    @override
    def appear(self, *_args: object, **_kwargs: object) -> bool:
        return True

    @override
    def flagship_change(self, fact_sink: GemsShipReplacementFactSink) -> GemsShipReplacementResult:
        self.change_calls.append("flagship")
        fact_sink(self.flagship_result)
        return self.flagship_result

    @override
    def vanguard_change(self, fact_sink: GemsShipReplacementFactSink) -> GemsShipReplacementResult:
        self.change_calls.append("vanguard")
        fact_sink(self.vanguard_result)
        return self.vanguard_result


def _replacement_result(
    disposition: GemsShipReplacementDisposition,
    emotion: int | None,
) -> GemsShipReplacementResult:
    return GemsShipReplacementResult(disposition, emotion)


@pytest.mark.parametrize(
    ("flagship_result", "vanguard_result", "expected"),
    [
        (
            _replacement_result(GemsShipReplacementDisposition.POLICY_SATISFIED, 120),
            _replacement_result(GemsShipReplacementDisposition.POLICY_SATISFIED, 110),
            True,
        ),
        (
            _replacement_result(GemsShipReplacementDisposition.FALLBACK_USED, 80),
            _replacement_result(GemsShipReplacementDisposition.POLICY_SATISFIED, 110),
            False,
        ),
        (
            _replacement_result(GemsShipReplacementDisposition.POLICY_SATISFIED, 120),
            _replacement_result(GemsShipReplacementDisposition.NO_CANDIDATE, None),
            False,
        ),
    ],
)
def test_hard_fleet_prepare_returns_every_typed_replacement(
    *,
    flagship_result: GemsShipReplacementResult,
    vanguard_result: GemsShipReplacementResult,
    expected: bool,
) -> None:
    runner = _HardFleetPrepareResultRunner(
        flagship_result=flagship_result,
        vanguard_result=vanguard_result,
    )

    facts: list[GemsShipReplacementResult] = []
    results = tuple(runner.hard_fleet_prepare(facts.append))

    assert results == (flagship_result, vanguard_result)
    assert facts == list(results)
    assert all(result.disposition is GemsShipReplacementDisposition.POLICY_SATISFIED for result in results) is expected
    assert runner.change_calls == ["flagship", "vanguard"]


def test_hard_fleet_prepare_leaves_emotion_persistence_to_its_adapter() -> None:
    runner = _HardFleetPrepareResultRunner(
        flagship_result=_replacement_result(GemsShipReplacementDisposition.POLICY_SATISFIED, 120),
        vanguard_result=_replacement_result(GemsShipReplacementDisposition.POLICY_SATISFIED, 30),
        current_emotion=80,
    )

    assert tuple(runner.hard_fleet_prepare(lambda _result: None)) == (
        _replacement_result(GemsShipReplacementDisposition.POLICY_SATISFIED, 120),
        _replacement_result(GemsShipReplacementDisposition.POLICY_SATISFIED, 30),
    )
    assert runner.records == []


@pytest.mark.parametrize("current_emotion", [0, 80])
def test_hard_fleet_prepare_returns_zero_emotion_without_persisting_it(current_emotion: int) -> None:
    runner = _HardFleetPrepareResultRunner(
        flagship_result=_replacement_result(GemsShipReplacementDisposition.FALLBACK_USED, 0),
        vanguard_result=_replacement_result(GemsShipReplacementDisposition.POLICY_SATISFIED, 120),
        current_emotion=current_emotion,
    )

    assert tuple(runner.hard_fleet_prepare(lambda _result: None)) == (
        _replacement_result(GemsShipReplacementDisposition.FALLBACK_USED, 0),
        _replacement_result(GemsShipReplacementDisposition.POLICY_SATISFIED, 120),
    )
    assert runner.records == []


class _EquipmentChangeRunner(GemsFleetReplacement):
    def __init__(
        self,
        *,
        appear_results: list[bool] | None = None,
        change_result: GemsShipReplacementResult | None = None,
        mode: str = "normal",
        take_on_error: RuntimeError | None = None,
    ) -> None:
        self.config = cast(
            "AzurLaneConfig",
            SimpleNamespace(
                Campaign_Mode=mode,
                Fleet_FleetOrder="fleet1_all_fleet2_standby",
                Fleet_Fleet1=1,
                Fleet_Fleet2=2,
                GemsFarming_ChangeFlagship="ship_equip",
                GemsFarming_ChangeVanguard="ship_equip",
            ),
        )
        self.operations: list[str] = []
        self.appear_results = list(appear_results or [])
        self.change_result = change_result or _replacement_result(
            GemsShipReplacementDisposition.POLICY_SATISFIED,
            100,
        )
        self.take_on_error = take_on_error

    def _goto_fleet(self) -> None:
        self.operations.append("goto")

    @override
    def appear(self, *_args: object, **_kwargs: object) -> bool:
        if self.appear_results:
            return self.appear_results.pop(0)
        return False

    def _change_equipment(self, *_args: object, take_on: bool, **_kwargs: object) -> None:
        self.operations.append("take_on" if take_on else "take_off")
        if take_on and self.take_on_error is not None:
            raise self.take_on_error

    def flagship_change_execute(self) -> GemsShipReplacementResult:
        self.operations.append("change_ship")
        return self.change_result

    def vanguard_change_execute(self) -> GemsShipReplacementResult:
        self.operations.append("change_ship")
        return self.change_result


def test_flagship_change_wraps_ship_replacement_with_equipment_code() -> None:
    runner = _EquipmentChangeRunner()
    facts: list[GemsShipReplacementResult] = []

    assert runner.flagship_change(facts.append) == _replacement_result(
        GemsShipReplacementDisposition.POLICY_SATISFIED,
        100,
    )
    assert facts == [_replacement_result(GemsShipReplacementDisposition.POLICY_SATISFIED, 100)]
    assert runner.operations == ["goto", "take_off", "change_ship", "take_on"]


@pytest.mark.parametrize("position", ["flagship", "vanguard"])
def test_hard_empty_slot_does_not_mount_equipment_without_take_off(position: str) -> None:
    runner = _EquipmentChangeRunner(appear_results=[True, False], mode="hard")
    facts: list[GemsShipReplacementResult] = []

    change = runner.flagship_change if position == "flagship" else runner.vanguard_change
    assert change(facts.append).disposition is GemsShipReplacementDisposition.POLICY_SATISFIED
    assert len(facts) == 1
    assert runner.operations == ["goto", "change_ship"]
    assert runner.appear_results == [False]


@pytest.mark.parametrize("position", ["flagship", "vanguard"])
def test_normal_mode_treats_ship_entry_template_as_occupied(position: str) -> None:
    runner = _EquipmentChangeRunner(appear_results=[True, True])
    facts: list[GemsShipReplacementResult] = []

    change = runner.flagship_change if position == "flagship" else runner.vanguard_change
    assert change(facts.append).disposition is GemsShipReplacementDisposition.POLICY_SATISFIED
    assert len(facts) == 1
    assert runner.operations == ["goto", "take_off", "change_ship", "take_on"]
    assert runner.appear_results == [True, True]


@pytest.mark.parametrize(
    ("position", "slot_is_empty", "expected_operations"),
    [
        ("flagship", True, ["goto", "take_off", "change_ship"]),
        ("vanguard", True, ["goto", "take_off", "change_ship"]),
        ("flagship", False, ["goto", "take_off", "change_ship", "take_on"]),
        ("vanguard", False, ["goto", "take_off", "change_ship", "take_on"]),
    ],
)
def test_hard_mode_mounts_equipment_only_when_replacement_occupies_slot(
    position: str,
    *,
    slot_is_empty: bool,
    expected_operations: list[str],
) -> None:
    runner = _EquipmentChangeRunner(
        appear_results=[False, slot_is_empty],
        change_result=_replacement_result(GemsShipReplacementDisposition.FALLBACK_USED, 20),
        mode="hard",
    )
    facts: list[GemsShipReplacementResult] = []

    change = runner.flagship_change if position == "flagship" else runner.vanguard_change
    assert change(facts.append).disposition is GemsShipReplacementDisposition.FALLBACK_USED
    assert len(facts) == 1
    assert runner.operations == expected_operations


@pytest.mark.parametrize("position", ["flagship", "vanguard"])
def test_replacement_fact_is_delivered_before_take_on_failure(position: str) -> None:
    take_on_error = RuntimeError("equipment restoration failed")
    runner = _EquipmentChangeRunner(take_on_error=take_on_error)
    facts: list[GemsShipReplacementResult] = []
    change = runner.flagship_change if position == "flagship" else runner.vanguard_change

    with pytest.raises(RuntimeError) as raised:
        change(facts.append)

    assert raised.value is take_on_error
    assert facts == [_replacement_result(GemsShipReplacementDisposition.POLICY_SATISFIED, 100)]
    assert runner.operations == ["goto", "take_off", "change_ship", "take_on"]


@pytest.mark.parametrize("position", ["flagship", "vanguard"])
def test_fact_sink_failure_still_restores_equipment_and_preserves_original_error(position: str) -> None:
    fact_error = RuntimeError("fact persistence failed")
    runner = _EquipmentChangeRunner()
    change = runner.flagship_change if position == "flagship" else runner.vanguard_change

    def fail_fact(_result: GemsShipReplacementResult) -> None:
        raise fact_error

    with pytest.raises(RuntimeError) as raised:
        change(fail_fact)

    assert raised.value is fact_error
    assert runner.operations == ["goto", "take_off", "change_ship", "take_on"]


@pytest.mark.parametrize("position", ["flagship", "vanguard"])
def test_fact_and_equipment_restoration_failures_are_both_preserved(position: str) -> None:
    fact_error = RuntimeError("fact persistence failed")
    take_on_error = RuntimeError("equipment restoration failed")
    runner = _EquipmentChangeRunner(take_on_error=take_on_error)
    change = runner.flagship_change if position == "flagship" else runner.vanguard_change

    def fail_fact(_result: GemsShipReplacementResult) -> None:
        raise fact_error

    with pytest.raises(BaseExceptionGroup) as raised:
        change(fail_fact)

    assert raised.value.exceptions == (fact_error, take_on_error)
    assert runner.operations == ["goto", "take_off", "change_ship", "take_on"]


class _CvSearchRunner(GemsFleetReplacement):
    def __init__(self, *, find_results: list[list[Ship]]) -> None:
        self.config = cast(
            "AzurLaneConfig",
            SimpleNamespace(
                GemsFarming_CommonCV="bogue",
                Fleet_FleetOrder="fleet1_all_fleet2_standby",
                Fleet_Fleet1=1,
                Fleet_Fleet2=2,
            ),
        )
        self.find_results = find_results
        self.sort_orders: list[bool] = []

    @override
    def dock_favourite_set(self, *, enable: bool = False, wait_loading: bool = True) -> None:
        del enable, wait_loading

    def dock_sort_method_dsc_set(self, *, enable: bool = True, wait_loading: bool = True) -> None:
        del wait_loading
        self.sort_orders.append(enable)

    @override
    def dock_filter_set(self, options: object = None, **settings: object) -> None:
        del options, settings

    def find_candidates(self, *_args: object, **_kwargs: object) -> list[Ship]:
        return self.find_results.pop(0)


def test_cv_search_starts_at_low_levels_before_reversing_specific_fallback() -> None:
    candidate = Ship(button=cast("Button", object()), level=1, emotion=100)
    runner = _CvSearchRunner(find_results=[[], [], [candidate]])

    assert runner.get_common_rarity_cv() == [candidate]
    assert runner.sort_orders == [False, True]


class _ShipSelectionRunner(GemsFleetReplacement):
    def __init__(self, *, mode: str, find_results: list[list[Ship]] | None = None) -> None:
        self.config = cast(
            "AzurLaneConfig",
            SimpleNamespace(
                Campaign_Mode=mode,
                Fleet_FleetOrder="fleet1_all_fleet2_standby",
            ),
        )
        self.campaign = cast(
            "CampaignEngine",
            SimpleNamespace(map_battle_count=0, emotion=SimpleNamespace(reduce_per_battle=2)),
        )
        self.low_ready_button = cast("Button", object())
        candidates = [
            Ship(button=cast("Button", object()), level=1, emotion=20),
            Ship(button=self.low_ready_button, level=1, emotion=100),
            Ship(button=cast("Button", object()), level=31, emotion=150),
        ]
        self.find_results = [candidates] if find_results is None else find_results
        self.selected_button: Button | None = None

    @override
    def ship_info_enter(self, *_args: object, **_kwargs: object) -> None:
        pass

    def get_common_rarity_cv(self, *, max_level: int = 31, min_emotion: int = 0) -> list[Ship]:
        del max_level, min_emotion
        return self.find_results.pop(0)

    def get_common_rarity_dd(self, *, min_emotion: int = 0) -> list[Ship]:
        del min_emotion
        return self.find_results.pop(0)

    def _ship_change_confirm(self, button: Button, *, check_button: Button) -> None:
        del check_button
        self.selected_button = button

    @override
    def _hard_unmount(self, button: Button, *, ship_name: str) -> None:
        del button, ship_name

    @override
    def _enter_hard_dock(self, button: Button) -> None:
        del button

    def _dock_reset(self) -> None:
        pass

    @override
    def ui_back(
        self,
        check_button: object,
        appear_button: object | None = None,
        offset: object | None = (30, 30),
        retry_wait: float = 10,
        *,
        skip_first_screenshot: bool = False,
    ) -> None:
        del check_button, appear_button, offset, retry_wait, skip_first_screenshot


@pytest.mark.parametrize("mode", ["normal", "hard"])
def test_flagship_change_prefers_low_level_then_high_emotion(mode: str) -> None:
    runner = _ShipSelectionRunner(mode=mode)

    assert runner.flagship_change_execute() == _replacement_result(
        GemsShipReplacementDisposition.POLICY_SATISFIED,
        100,
    )
    assert runner.selected_button is runner.low_ready_button


@pytest.mark.parametrize("position", ["flagship", "vanguard"])
def test_hard_ship_change_reports_fallback_ship_and_emotion(position: str) -> None:
    fallback = Ship(button=cast("Button", object()), level=80, emotion=17)
    runner = _ShipSelectionRunner(mode="hard", find_results=[[], [fallback]])
    execute = runner.flagship_change_execute if position == "flagship" else runner.vanguard_change_execute

    result = execute()

    assert result == _replacement_result(GemsShipReplacementDisposition.FALLBACK_USED, 17)
    assert runner.selected_button is fallback.button


@pytest.mark.parametrize("position", ["flagship", "vanguard"])
def test_hard_ship_change_reports_no_candidate_without_fake_emotion(position: str) -> None:
    runner = _ShipSelectionRunner(mode="hard", find_results=[[], []])
    execute = runner.flagship_change_execute if position == "flagship" else runner.vanguard_change_execute

    result = execute()

    assert result == _replacement_result(GemsShipReplacementDisposition.NO_CANDIDATE, None)
