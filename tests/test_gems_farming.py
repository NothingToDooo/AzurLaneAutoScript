from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast, override

import pytest

from module.campaign import gems_farming as gems_module
from module.campaign.gems_farming import GemsEmotion, GemsFleetReplacement
from module.exception import CampaignEnd
from module.retire.scanner import Ship

if TYPE_CHECKING:
    from module.base.button import Button
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


class _HardFleetPrepareResultRunner(GemsFleetReplacement):
    def __init__(
        self,
        *,
        flagship_result: bool,
        vanguard_result: bool,
        current_emotion: int = 100,
        flagship_emotion: int | None = None,
        vanguard_emotion: int | None = None,
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
        self.flagship_emotion = flagship_emotion
        self.vanguard_emotion = vanguard_emotion
        self.change_calls: list[str] = []

    @override
    def appear(self, *_args: object, **_kwargs: object) -> bool:
        return True

    @override
    def flagship_change(self) -> bool:
        self.change_calls.append("flagship")
        if self.flagship_emotion is not None:
            ship = Ship(button=cast("Button", object()), level=1, emotion=self.flagship_emotion)
            self._record_new_ship_emotion(ship)
        return self.flagship_result

    @override
    def vanguard_change(self) -> bool:
        self.change_calls.append("vanguard")
        if self.vanguard_emotion is not None:
            ship = Ship(button=cast("Button", object()), level=100, emotion=self.vanguard_emotion)
            self._record_new_ship_emotion(ship)
        return self.vanguard_result


@pytest.mark.parametrize(
    ("flagship_result", "vanguard_result", "expected"),
    [
        (True, True, True),
        (False, True, False),
        (True, False, False),
    ],
)
def test_hard_fleet_prepare_requires_every_replacement_to_succeed(
    *,
    flagship_result: bool,
    vanguard_result: bool,
    expected: bool,
) -> None:
    runner = _HardFleetPrepareResultRunner(
        flagship_result=flagship_result,
        vanguard_result=vanguard_result,
    )

    assert runner.hard_fleet_prepare() is expected
    assert runner.change_calls == ["flagship", "vanguard"]


def test_hard_fleet_prepare_records_lowest_current_and_replacement_emotion() -> None:
    runner = _HardFleetPrepareResultRunner(
        flagship_result=True,
        vanguard_result=True,
        current_emotion=80,
        flagship_emotion=120,
        vanguard_emotion=30,
    )

    assert runner.hard_fleet_prepare() is True
    assert runner.records == [{"Emotion_Fleet1Value": 30}]


@pytest.mark.parametrize("current_emotion", [0, 80])
def test_hard_fleet_prepare_keeps_zero_as_lowest_emotion(current_emotion: int) -> None:
    runner = _HardFleetPrepareResultRunner(
        flagship_result=False,
        vanguard_result=True,
        current_emotion=current_emotion,
        flagship_emotion=0,
        vanguard_emotion=120,
    )

    assert runner.hard_fleet_prepare() is False
    assert runner.records == [{"Emotion_Fleet1Value": 0}]


class _EquipmentChangeRunner(GemsFleetReplacement):
    def __init__(
        self,
        *,
        appear_results: list[bool] | None = None,
        change_result: bool = True,
        mode: str = "normal",
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
        self.change_result = change_result

    def _goto_fleet(self) -> None:
        self.operations.append("goto")

    @override
    def appear(self, *_args: object, **_kwargs: object) -> bool:
        if self.appear_results:
            return self.appear_results.pop(0)
        return False

    def _change_equipment(self, *_args: object, take_on: bool, **_kwargs: object) -> None:
        self.operations.append("take_on" if take_on else "take_off")

    def flagship_change_execute(self) -> bool:
        self.operations.append("change_ship")
        return self.change_result

    def vanguard_change_execute(self) -> bool:
        self.operations.append("change_ship")
        return self.change_result


def test_flagship_change_wraps_ship_replacement_with_equipment_code() -> None:
    runner = _EquipmentChangeRunner()

    assert runner.flagship_change() is True
    assert runner.operations == ["goto", "take_off", "change_ship", "take_on"]


@pytest.mark.parametrize("position", ["flagship", "vanguard"])
def test_hard_empty_slot_does_not_mount_equipment_without_take_off(position: str) -> None:
    runner = _EquipmentChangeRunner(appear_results=[True, False], mode="hard")

    change = runner.flagship_change if position == "flagship" else runner.vanguard_change
    assert change() is True
    assert runner.operations == ["goto", "change_ship"]
    assert runner.appear_results == [False]


@pytest.mark.parametrize("position", ["flagship", "vanguard"])
def test_normal_mode_treats_ship_entry_template_as_occupied(position: str) -> None:
    runner = _EquipmentChangeRunner(appear_results=[True, True])

    change = runner.flagship_change if position == "flagship" else runner.vanguard_change
    assert change() is True
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
        change_result=False,
        mode="hard",
    )

    change = runner.flagship_change if position == "flagship" else runner.vanguard_change
    assert change() is False
    assert runner.operations == expected_operations


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


class _FlagshipSelectionRunner(GemsFleetReplacement):
    def __init__(self, *, mode: str) -> None:
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
        self.candidates = [
            Ship(button=cast("Button", object()), level=1, emotion=20),
            Ship(button=self.low_ready_button, level=1, emotion=100),
            Ship(button=cast("Button", object()), level=31, emotion=150),
        ]
        self.selected_button: Button | None = None
        self._new_fleet_emotion = 150

    @override
    def ship_info_enter(self, *_args: object, **_kwargs: object) -> None:
        pass

    def get_common_rarity_cv(self, *, max_level: int = 31, min_emotion: int = 0) -> list[Ship]:
        del max_level, min_emotion
        return self.candidates

    def _ship_change_confirm(self, button: Button, *, check_button: Button) -> None:
        del check_button
        self.selected_button = button

    @override
    def _hard_unmount(self, button: Button, *, ship_name: str) -> None:
        del button, ship_name

    @override
    def _enter_hard_dock(self, button: Button) -> None:
        del button


@pytest.mark.parametrize("mode", ["normal", "hard"])
def test_flagship_change_prefers_low_level_then_high_emotion(mode: str) -> None:
    runner = _FlagshipSelectionRunner(mode=mode)

    assert runner.flagship_change_execute() is True
    assert runner.selected_button is runner.low_ready_button
