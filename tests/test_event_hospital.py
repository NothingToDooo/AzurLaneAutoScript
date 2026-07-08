import pytest

from module.event_hospital import assets as hospital_assets
from module.event_hospital import hospital as hospital_module
from module.event_hospital.hospital import Hospital
from module.ui.page import page_hospital


class _NeverReachedTimer:
    def __init__(self, *_args: object, **_kwargs: object) -> None:
        pass

    def start(self) -> _NeverReachedTimer:
        return self

    def reached(self) -> bool:
        return False

    def reset(self) -> None:
        pass


class _Device:
    def __init__(self) -> None:
        self.clicks: list[object] = []
        self.screenshot_count = 0

    def click(self, button: object) -> None:
        self.clicks.append(button)

    def screenshot(self) -> None:
        self.screenshot_count += 1


class _Hospital(Hospital):
    def __init__(self) -> None:
        self.device = _Device()
        self.calls: list[tuple[object, ...]] = []
        self.red_dot = True
        self.in_daily_results: list[bool] = []
        self.page_results: list[bool] = []
        self.receive_appear_results: list[bool] = []
        self.get_items_results: list[bool] = []

    def daily_red_dot_appear(self) -> bool:
        self.calls.append(("daily_red_dot_appear",))
        return self.red_dot

    def interval_clear(self, button: object, interval: float = 0) -> None:
        self.calls.append(("interval_clear", button, interval))

    def is_in_daily_reward(self, interval: float = 0) -> bool:
        self.calls.append(("is_in_daily_reward", interval))
        return self.in_daily_results.pop(0)

    def ui_page_appear(self, page: object, interval: float = 0) -> bool:
        self.calls.append(("ui_page_appear", page, interval))
        return self.page_results.pop(0)

    def daily_reward_receive_appear(self) -> bool:
        self.calls.append(("daily_reward_receive_appear",))
        return self.receive_appear_results.pop(0)

    def handle_get_items(self) -> bool:
        self.calls.append(("handle_get_items",))
        return self.get_items_results.pop(0)


@pytest.fixture(autouse=True)
def _patch_timer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hospital_module, "Timer", _NeverReachedTimer)


def test_daily_reward_receive_returns_false_without_red_dot() -> None:
    hospital = _Hospital()
    hospital.red_dot = False

    assert hospital.daily_reward_receive() is False
    assert hospital.device.clicks == []


def test_daily_reward_receive_enters_claims_and_exits() -> None:
    hospital = _Hospital()
    hospital.in_daily_results = [False, True, True, True, True, True]
    hospital.page_results = [True, False, True]
    hospital.receive_appear_results = [True, False, False]
    hospital.get_items_results = [True]

    assert hospital.daily_reward_receive() is True

    assert hospital.device.clicks == [
        hospital_assets.HOSPITAL_GOTO_DAILY,
        hospital_assets.DAILY_REWARD_RECEIVE,
        hospital_assets.HOSIPITAL_CLUE_CHECK,
    ]
    assert ("interval_clear", page_hospital.check_button, 0) in hospital.calls
    assert hospital.calls.count(("interval_clear", hospital_assets.HOSIPITAL_CLUE_CHECK, 0)) == 2
