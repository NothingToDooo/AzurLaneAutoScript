from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import TYPE_CHECKING, TypeVar, cast, override

import pytest

from module.campaign import gems_farming as gems_module
from module.campaign.campaign_base import CampaignBase
from module.campaign.gems_farming import GemsCampaignOverride, GemsEmotion, GemsFarming
from module.campaign.run import CampaignRun
from module.content.legacy_stage import LoadedStage
from module.exception import CampaignEnd, HardNotSatisfied
from module.handler.assets import AUTO_SEARCH_MAP_OPTION_OFF
from module.map.map_base import CampaignMap
from module.retire.scanner import Ship
from module.ui.assets import BACK_ARROW

if TYPE_CHECKING:
    from module.base.button import Button
    from module.config.config import AzurLaneConfig

_T = TypeVar("_T")


def button_key(button: object) -> str:
    return getattr(button, "name", repr(button))


class _Config:
    GemsFarming_ChangeVanguard = "disabled"
    GEMS_EMOTION_TRIGGERED = False


class _Device:
    def __init__(self) -> None:
        self.clicks: list[object] = []
        self.screenshot_count = 0

    def click(self, button: object) -> None:
        self.clicks.append(button)

    def screenshot(self) -> None:
        self.screenshot_count += 1


class _GemsCampaign(GemsCampaignOverride):
    config: _Config
    device: _Device

    def __init__(self) -> None:
        self.config = _Config()
        self.device = _Device()
        self.calls: list[tuple[object, ...]] = []
        self.confirm_results: list[bool] = []
        self.cancel_results: list[bool] = []
        self.story_results: list[bool] = []
        self.appear_results: dict[str, list[bool]] = {}
        self.auto_search_results: list[bool] = []
        self.stage_results: list[bool] = []
        self.map_results: list[bool] = []

    @staticmethod
    def _next_result(results: list[_T], *, default: _T) -> _T:
        if results:
            return results.pop(0)
        return default

    def handle_popup_confirm(self, name: str = "", *_args: object, **_kwargs: object) -> bool:
        self.calls.append(("handle_popup_confirm", name))
        return self._next_result(self.confirm_results, default=False)

    def handle_popup_cancel(self, name: str = "", *_args: object, **_kwargs: object) -> bool:
        self.calls.append(("handle_popup_cancel", name))
        return self._next_result(self.cancel_results, default=False)

    def interval_reset(self, button: object, *_args: object, **_kwargs: object) -> None:
        self.calls.append(("interval_reset", button))

    def handle_story_skip(self) -> bool:
        self.calls.append(("handle_story_skip",))
        return self._next_result(self.story_results, default=False)

    def appear(self, button: object, *_args: object, **kwargs: object) -> bool:
        key = button_key(button)
        self.calls.append(("appear", key, kwargs))
        return self._next_result(self.appear_results.get(key, []), default=False)

    def handle_auto_search_exit(self) -> bool:
        self.calls.append(("handle_auto_search_exit",))
        return self._next_result(self.auto_search_results, default=False)

    def is_in_stage(self) -> bool:
        self.calls.append(("is_in_stage",))
        return self._next_result(self.stage_results, default=False)

    def is_in_map(self) -> bool:
        self.calls.append(("is_in_map",))
        return self._next_result(self.map_results, default=False)


class _TestLoadedCampaign(CampaignBase):
    def __init__(self, *, config: object, device: object) -> None:
        self.test_config = config
        self.test_device = device
        vars(self)["config"] = config
        vars(self)["device"] = device


class _MergedCampaignConfig:
    def __init__(self) -> None:
        self.overrides: list[dict[str, object]] = []

    def override(self, **kwargs: object) -> None:
        self.overrides.append(kwargs)


def test_gems_farming_uses_loaded_stage_campaign_class(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = object.__new__(GemsFarming)
    runner.config = SimpleNamespace(GemsFarming_ChangeVanguard="disabled")
    merged_config = _MergedCampaignConfig()
    device = object()
    runner.module = None

    def load_stage(_self: CampaignRun, name: str, folder: str = "campaign_main") -> bool:
        _ = (name, folder)
        runner.loaded_stage = LoadedStage(_Config, _TestLoadedCampaign, CampaignMap("TEST"))
        runner.campaign = _TestLoadedCampaign(config=merged_config, device=device)
        return True

    monkeypatch.setattr(CampaignRun, "load_campaign", load_stage)

    runner.load_campaign("t1", folder="event_test")

    assert isinstance(runner.campaign, _TestLoadedCampaign)
    assert runner.campaign.test_device is device
    assert runner.campaign.test_config is merged_config
    assert runner.campaign.gems_farming is runner
    assert merged_config.overrides == [
        {"Emotion_Mode": "ignore"},
        {"EnemyPriority_EnemyScaleBalanceWeight": "S1_enemy_first"},
    ]


def test_gems_farming_keeps_emotion_control_when_vanguard_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = object.__new__(GemsFarming)
    runner.config = SimpleNamespace(GemsFarming_ChangeVanguard="ship")
    merged_config = _MergedCampaignConfig()
    device = object()

    def load_stage(_self: CampaignRun, name: str, folder: str = "campaign_main") -> bool:
        _ = (name, folder)
        runner.loaded_stage = LoadedStage(_Config, _TestLoadedCampaign, CampaignMap("TEST"))
        runner.campaign = _TestLoadedCampaign(config=merged_config, device=device)
        return True

    monkeypatch.setattr(CampaignRun, "load_campaign", load_stage)

    runner.load_campaign("t1", folder="event_test")

    assert merged_config.overrides == [
        {"EnemyPriority_EnemyScaleBalanceWeight": "S1_enemy_first"},
    ]


def test_low_emotion_disabled_confirms_ignore() -> None:
    campaign = _GemsCampaign()
    campaign.confirm_results = [True]

    result = campaign.handle_combat_low_emotion()

    assert result is True
    assert ("interval_reset", AUTO_SEARCH_MAP_OPTION_OFF) in campaign.calls


def test_low_emotion_enabled_returns_false_without_cancel_popup() -> None:
    campaign = _GemsCampaign()
    campaign.config.GemsFarming_ChangeVanguard = "enabled"

    result = campaign.handle_combat_low_emotion()

    assert result is False
    assert campaign.config.GEMS_EMOTION_TRIGGERED is False


def test_low_emotion_withdraw_raises_after_stage_return() -> None:
    campaign = _GemsCampaign()
    campaign.config.GemsFarming_ChangeVanguard = "enabled"
    campaign.cancel_results = [True, False]
    campaign.stage_results = [True]

    with pytest.raises(CampaignEnd, match=gems_module.EMOTION_WITHDRAW_MESSAGE):
        campaign.handle_combat_low_emotion()

    assert campaign.config.GEMS_EMOTION_TRIGGERED is True
    assert campaign.device.screenshot_count == 1


def test_low_emotion_withdraw_backs_out_then_withdraws_from_map(monkeypatch: pytest.MonkeyPatch) -> None:
    campaign = _GemsCampaign()
    campaign.config.GemsFarming_ChangeVanguard = "enabled"
    campaign.cancel_results = [True, False, False]
    campaign.appear_results[button_key(gems_module.BATTLE_PREPARATION)] = [True, False]
    campaign.stage_results = [False]
    campaign.map_results = [True]
    monkeypatch.setattr(campaign, "withdraw", lambda **_kwargs: campaign.calls.append(("withdraw",)))

    with pytest.raises(CampaignEnd, match=gems_module.EMOTION_WITHDRAW_MESSAGE):
        campaign.handle_combat_low_emotion()

    assert campaign.device.clicks == [BACK_ARROW]
    assert ("withdraw",) in campaign.calls


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


class _HardCampaign(CampaignBase):
    preparation_calls: int

    def fleet_preparation(self) -> bool:
        self.preparation_calls += 1
        if self.preparation_calls == 1:
            raise HardNotSatisfied
        return True


class _HardRunner(GemsFarming):
    def __init__(self) -> None:
        self.prepare_calls = 0
        self.config = cast("AzurLaneConfig", SimpleNamespace())

    def build_campaign_class(self) -> type[GemsCampaignOverride]:
        return self._campaign_with_gems_override(_HardCampaign)

    def hard_fleet_prepare(self) -> bool:
        self.prepare_calls += 1
        return True


def test_hard_fleet_preparation_fills_empty_slots_then_retries() -> None:
    runner = _HardRunner()
    campaign_class = runner.build_campaign_class()
    campaign = object.__new__(campaign_class)
    campaign.preparation_calls = 0
    campaign.bind_gems_farming(runner)

    assert campaign.fleet_preparation() is True
    assert campaign.preparation_calls == 2
    assert runner.prepare_calls == 1


class _HardFleetPrepareResultRunner(GemsFarming):
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
            "CampaignBase",
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
            self._new_fleet_emotion = min(self._new_fleet_emotion, self.flagship_emotion)
        return self.flagship_result

    @override
    def vanguard_change(self) -> bool:
        self.change_calls.append("vanguard")
        if self.vanguard_emotion is not None:
            self._new_fleet_emotion = min(self._new_fleet_emotion, self.vanguard_emotion)
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


class _EquipmentChangeRunner(GemsFarming):
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
def test_empty_slot_does_not_mount_equipment_without_take_off(position: str) -> None:
    runner = _EquipmentChangeRunner(appear_results=[True, False])

    change = runner.flagship_change if position == "flagship" else runner.vanguard_change
    assert change() is True
    assert runner.operations == ["goto", "change_ship"]
    assert runner.appear_results == [False]


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


class _CvSearchRunner(GemsFarming):
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


class _FlagshipSelectionRunner(GemsFarming):
    def __init__(self, *, mode: str) -> None:
        self.config = cast(
            "AzurLaneConfig",
            SimpleNamespace(
                Campaign_Mode=mode,
                Fleet_FleetOrder="fleet1_all_fleet2_standby",
            ),
        )
        self.campaign = cast(
            "CampaignBase",
            SimpleNamespace(map_battle_count=0, emotion=SimpleNamespace(reduce_per_battle=2)),
        )
        self.low_ready_button = cast("Button", object())
        self.candidates = [
            Ship(button=cast("Button", object()), level=1, emotion=20),
            Ship(button=self.low_ready_button, level=1, emotion=100),
            Ship(button=cast("Button", object()), level=31, emotion=150),
        ]
        self.selected_button: Button | None = None
        self._new_fleet_emotion = 0

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


class _RunCountGemsFarming(GemsFarming):
    def __init__(self) -> None:
        self.config = cast(
            "AzurLaneConfig",
            SimpleNamespace(
                StopCondition_RunCount=1,
                Scheduler_Enable=True,
                GemsFarming_ChangeVanguard="disabled",
                override=lambda **_kwargs: None,
            ),
        )
        self.campaign = cast(
            "CampaignBase",
            SimpleNamespace(
                config=SimpleNamespace(
                    LV32_TRIGGERED=False,
                    GEMS_EMOTION_TRIGGERED=False,
                    set_record=lambda **_kwargs: None,
                )
            ),
        )
        self.notifications: list[str] = []

    @override
    def flagship_change(self) -> bool:
        return True

    @override
    def _notify_campaign_finished(self, reason: str) -> None:
        self.notifications.append(reason)

    def trigger_rotation(self) -> None:
        self._trigger_emotion = True
        self.config.StopCondition_RunCount = 0


def test_gems_rotation_keeps_run_count_notification(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = _RunCountGemsFarming()

    def trigger_rotation(
        current: CampaignRun,
        *,
        name: str,
        folder: str,
        mode: str,
        total: int,
    ) -> None:
        del name, folder, mode, total
        cast("_RunCountGemsFarming", current).trigger_rotation()

    monkeypatch.setattr(CampaignRun, "run", trigger_rotation)

    runner.run("2-4")

    assert runner.notifications == ["reached run count limit"]
    assert runner.config.Scheduler_Enable is False
