from datetime import timedelta
from typing import TYPE_CHECKING, ClassVar, TypeVar

import numpy as np
import pytest

from module.commission import assets as commission_assets
from module.commission import commission as commission_module
from module.commission.commission import RewardCommission
from module.commission.project import Commission
from module.exception import GameStuckError
from module.map.map_grids import SelectedGrids

if TYPE_CHECKING:
    from module.base.button import MatchOffset
    from module.base.type_alias import Area

_T = TypeVar("_T")


def button_key(button: object) -> str:
    return getattr(button, "name", repr(button))


class _Timer:
    next_index: ClassVar[int] = 0
    reached_results: ClassVar[dict[int, list[bool]]] = {}

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        self.index = _Timer.next_index
        _Timer.next_index += 1

    def reached(self) -> bool:
        results = _Timer.reached_results.get(self.index)
        if results:
            return results.pop(0)
        return False

    def reset(self) -> None:
        pass


class _Device:
    def __init__(self) -> None:
        self.image = np.zeros((720, 1280, 3), dtype=np.uint8)
        self.clicks: list[object] = []
        self.sleeps: list[float] = []
        self.screenshot_count = 0

    def click(self, button: object) -> None:
        self.clicks.append(button)

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)

    def screenshot(self) -> None:
        self.screenshot_count += 1


def _commission(name: str) -> Commission:
    commission = Commission.__new__(Commission)
    commission.name = name
    commission.button = commission_assets.COMMISSION_ADVICE
    commission.valid = True
    commission.genre = f"daily_{name}"
    commission.status = "pending"
    commission.category_str = "daily"
    commission.genre_str = name
    commission.duration = timedelta(hours=1)
    commission.expire = timedelta()
    commission.repeat_count = 1
    commission.suffix_image = None
    commission.suffix_hash = ""
    return commission


class _CommissionUI(RewardCommission):
    device: _Device

    def __init__(self) -> None:
        self.device = _Device()
        self.calls: list[tuple[object, ...]] = []
        self.info_bar_results: list[bool] = []
        self.match_results: dict[str, list[bool]] = {}
        self.appear_results: dict[str, list[bool]] = {}
        self.popup_results: list[bool] = []
        self.detect_results: list[SelectedGrids[Commission]] = []

    def start_click(self, comm: Commission, *, is_urgent: bool = False) -> bool:
        return self._commission_start_click(comm, is_urgent=is_urgent)

    @staticmethod
    def _next_result(results: list[_T], *, default: _T) -> _T:
        if results:
            return results.pop(0)
        return default

    def interval_clear(self, button: object, *_args: object, **_kwargs: object) -> None:
        self.calls.append(("interval_clear", button))

    def interval_reset(self, button: object, *_args: object, **_kwargs: object) -> None:
        self.calls.append(("interval_reset", button))

    def info_bar_count(self) -> bool:
        self.calls.append(("info_bar_count",))
        return self._next_result(self.info_bar_results, default=False)

    def match_template_color(self, button: object, *_args: object, **kwargs: object) -> bool:
        key = button_key(button)
        self.calls.append(("match_template_color", key, kwargs))
        return self._next_result(self.match_results.get(key, []), default=False)

    def handle_popup_confirm(
        self,
        name: str = "",
        offset: MatchOffset | None = None,
        interval: float = 2,
    ) -> bool:
        _ = (name, offset, interval)
        self.calls.append(("handle_popup_confirm", name))
        return self._next_result(self.popup_results, default=False)

    def appear(self, button: object, *_args: object, **kwargs: object) -> bool:
        key = button_key(button)
        self.calls.append(("appear", key, kwargs))
        return self._next_result(self.appear_results.get(key, []), default=False)

    def commission_detect(
        self,
        trial: int = 1,
        area: Area | None = None,
        *,
        skip_first_screenshot: bool = True,
    ) -> SelectedGrids[Commission]:
        self.calls.append(
            (
                "commission_detect",
                {"trial": trial, "area": area, "skip_first_screenshot": skip_first_screenshot},
            )
        )
        return self.detect_results.pop(0)


@pytest.fixture(autouse=True)
def _patch_timer(monkeypatch: pytest.MonkeyPatch) -> None:
    _Timer.next_index = 0
    _Timer.reached_results = {}
    monkeypatch.setattr(commission_module, "Timer", _Timer)


def test_commission_start_click_uses_start_button() -> None:
    ui = _CommissionUI()
    comm = _commission("daily")
    ui.info_bar_results = [False, True]
    ui.match_results[button_key(commission_assets.COMMISSION_START)] = [True]

    result = ui.start_click(comm)

    assert result is True
    assert commission_assets.COMMISSION_START in ui.device.clicks
    assert ("interval_reset", commission_assets.COMMISSION_ADVICE) in ui.calls


def test_commission_start_click_returns_false_for_wrong_advice() -> None:
    ui = _CommissionUI()
    comm = _commission("target")
    ui.appear_results[button_key(commission_assets.COMMISSION_ADVICE)] = [True]
    ui.detect_results = [SelectedGrids([_commission("other")])]

    result = ui.start_click(comm)

    assert result is False
    assert commission_assets.COMMISSION_ADVICE not in ui.device.clicks


def test_commission_start_click_enters_commission_when_timer_reaches() -> None:
    ui = _CommissionUI()
    comm = _commission("daily")
    ui.info_bar_results = [False, True]
    _Timer.reached_results = {0: [True]}

    result = ui.start_click(comm)

    assert result is True
    assert comm.button in ui.device.clicks
    assert ui.device.sleeps == [0.3]


def test_commission_start_click_raises_on_flashing_advice() -> None:
    ui = _CommissionUI()
    comm = _commission("daily")
    ui.appear_results[button_key(commission_assets.COMMISSION_ADVICE)] = [True, True, True]
    ui.detect_results = [SelectedGrids([]), SelectedGrids([]), SelectedGrids([])]

    with pytest.raises(GameStuckError):
        ui.start_click(comm)
