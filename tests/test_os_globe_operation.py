from typing import TYPE_CHECKING, ClassVar, Literal, TypeVar, override

import numpy as np
import pytest

from module.os import assets as os_assets
from module.os import globe_operation as globe_operation_module
from module.os.globe_operation import GlobeOperation, OSExploreError, RewardUncollectedError
from module.os.globe_zone import Zone

_T = TypeVar("_T")

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from module.base.button import Button
    from module.base.timer import Timer
    from module.base.type_alias import ImageArray
    from module.os.globe_operation import ZoneType


def _zone(zone_id: int = 1) -> Zone:
    return Zone(
        zone_id,
        {
            "shape": "A1",
            "hazard_level": 1,
            "cn": f"zone-{zone_id}",
            "area_pos": (0, 0),
            "offset_pos": (0, 0),
            "region": 1,
        },
    )


def _zone_type_for_button(button: Button) -> ZoneType:
    if button is os_assets.SELECT_DANGEROUS:
        return "DANGEROUS"
    if button is os_assets.SELECT_SAFE:
        return "SAFE"
    if button is os_assets.SELECT_OBSCURE:
        return "OBSCURE"
    if button is os_assets.SELECT_ABYSSAL:
        return "ABYSSAL"
    if button is os_assets.SELECT_STRONGHOLD:
        return "STRONGHOLD"
    if button is os_assets.SELECT_ARCHIVE:
        return "ARCHIVE"
    raise AssertionError


def button_key(button: object) -> str:
    return str(getattr(button, "name", repr(button)))


class _Timer:
    next_index: ClassVar[int] = 0
    reached_results: ClassVar[dict[int, list[bool]]] = {}
    reset_count: ClassVar[int] = 0
    clear_count: ClassVar[int] = 0

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        self.index = _Timer.next_index
        _Timer.next_index += 1

    def start(self) -> _Timer:
        return self

    def reached(self) -> bool:
        results = _Timer.reached_results.get(self.index)
        if results:
            return results.pop(0)
        return False

    def reset(self) -> _Timer:
        _Timer.reset_count += 1
        return self

    def clear(self) -> _Timer:
        _Timer.clear_count += 1
        return self


class _Device:
    def __init__(self) -> None:
        self.image = np.zeros((2, 2, 3), dtype=np.uint8)
        self.clicks: list[Button] = []

    def click(self, button: Button) -> None:
        self.clicks.append(button)


class _GlobeOperation(GlobeOperation):
    device: _Device

    def __init__(self) -> None:
        self.has_switch = True
        self.pinned_name: ZoneType | Literal[""] = ""
        self.selection_results: list[list[Button]] = []
        self.executed_buttons: list[Button] = []
        self.enter_count = 0
        self.update_pinned_on_execute = True
        self.device = _Device()
        self.calls: list[tuple[object, ...]] = []
        self.loop_count = 10
        self.in_globe_results: list[bool] = []
        self.in_map_results: list[bool] = []
        self.appear_then_click_results: dict[str, list[bool]] = {}
        self.appear_results: dict[str, list[bool]] = {}
        self.map_event_results: list[str] = []
        self.popup_results: list[bool] = []
        self.action_point_results: list[bool] = []
        self.handle_zone_pinned_results: list[bool] = []
        self.zone_pinned_results: list[bool] = []
        self.interval_resets: list[str] = []

    def select_zone_type(self, types: ZoneType | Sequence[ZoneType] = ("SAFE", "DANGEROUS")) -> bool:
        return self.zone_type_select(types)

    def goto_globe(self, *, unpin: bool = True) -> None:
        self.os_map_goto_globe(unpin=unpin)

    def enter_globe(self, zone: Zone) -> None:
        self.globe_enter(zone)

    @staticmethod
    def _next_result(results: list[_T], *, default: _T) -> _T:
        if results:
            return results.pop(0)
        return default

    @override
    def loop(
        self,
        *,
        skip_first: bool = True,
        timeout: float | Timer | None = None,
    ) -> Iterator[ImageArray]:
        del skip_first, timeout
        return iter([self.device.image] * self.loop_count)

    def zone_has_switch(self) -> bool:
        return self.has_switch

    @override
    def get_zone_pinned_name(self) -> ZoneType | Literal[""]:
        return self.pinned_name

    def zone_select_enter(self) -> None:
        self.enter_count += 1

    @override
    def ensure_zone_select_expanded(self) -> list[Button]:
        if self.selection_results:
            return self.selection_results.pop(0)
        return []

    @override
    def zone_select_execute(self, button: Button) -> None:
        self.executed_buttons.append(button)
        if self.update_pinned_on_execute:
            self.pinned_name = _zone_type_for_button(button)

    def is_in_globe(self) -> bool:
        self.calls.append(("is_in_globe",))
        return self._next_result(self.in_globe_results, default=False)

    def is_in_map(self) -> bool:
        self.calls.append(("is_in_map",))
        return self._next_result(self.in_map_results, default=False)

    def appear_then_click(self, button: object, *_args: object, **kwargs: object) -> bool:
        key = button_key(button)
        self.calls.append(("appear_then_click", key, kwargs))
        return self._next_result(self.appear_then_click_results.get(key, []), default=False)

    def appear(self, button: object, *_args: object, **kwargs: object) -> bool:
        key = button_key(button)
        self.calls.append(("appear", key, kwargs))
        return self._next_result(self.appear_results.get(key, []), default=False)

    def interval_reset(self, button: object, *_args: object, **_kwargs: object) -> None:
        key = button_key(button)
        self.calls.append(("interval_reset", key))
        self.interval_resets.append(key)

    @override
    def handle_map_event(self) -> str:
        self.calls.append(("handle_map_event",))
        return self._next_result(self.map_event_results, default="")

    def handle_popup_confirm(self, name: str = "", *_args: object, **_kwargs: object) -> bool:
        self.calls.append(("handle_popup_confirm", name))
        return self._next_result(self.popup_results, default=False)

    def handle_action_point(self, *_args: object, **kwargs: object) -> bool:
        self.calls.append(("handle_action_point", kwargs))
        return self._next_result(self.action_point_results, default=False)

    def handle_zone_pinned(self) -> bool:
        self.calls.append(("handle_zone_pinned",))
        return self._next_result(self.handle_zone_pinned_results, default=False)

    def is_zone_pinned(self) -> bool:
        self.calls.append(("is_zone_pinned",))
        return self._next_result(self.zone_pinned_results, default=False)


@pytest.fixture(autouse=True)
def _patch_timer(monkeypatch: pytest.MonkeyPatch) -> None:
    _Timer.next_index = 0
    _Timer.reached_results = {}
    _Timer.reset_count = 0
    _Timer.clear_count = 0
    monkeypatch.setattr(globe_operation_module, "Timer", _Timer)


def test_zone_type_select_skips_zone_without_switch() -> None:
    operation = _GlobeOperation()
    operation.has_switch = False

    result = operation.select_zone_type("SAFE")

    assert result is True
    assert operation.enter_count == 0


def test_zone_type_select_keeps_matching_pinned_type() -> None:
    operation = _GlobeOperation()
    operation.pinned_name = "SAFE"

    result = operation.select_zone_type(("SAFE", "DANGEROUS"))

    assert result is True
    assert operation.executed_buttons == []


def test_zone_type_select_accepts_string_type() -> None:
    operation = _GlobeOperation()
    operation.selection_results = [[os_assets.SELECT_SAFE, os_assets.SELECT_DANGEROUS]]

    result = operation.select_zone_type("SAFE")

    assert result is True
    assert operation.executed_buttons == [os_assets.SELECT_SAFE]


def test_zone_type_select_falls_back_to_default_types() -> None:
    operation = _GlobeOperation()
    operation.selection_results = [[os_assets.SELECT_DANGEROUS, os_assets.SELECT_SAFE]]

    result = operation.select_zone_type(("ARCHIVE",))

    assert result is True
    assert operation.executed_buttons == [os_assets.SELECT_SAFE]


def test_zone_type_select_returns_false_after_retry_failure() -> None:
    operation = _GlobeOperation()
    operation.update_pinned_on_execute = False
    operation.selection_results = [
        [os_assets.SELECT_SAFE],
        [os_assets.SELECT_SAFE],
        [os_assets.SELECT_SAFE],
    ]

    result = operation.select_zone_type("SAFE")

    assert result is False
    assert operation.enter_count == 3
    assert operation.executed_buttons == [os_assets.SELECT_SAFE] * 3


def test_os_map_goto_globe_clicks_map_button_and_confirms_unpinned() -> None:
    operation = _GlobeOperation()
    operation.in_globe_results = [False, True]
    operation.appear_then_click_results[button_key(os_assets.MAP_GOTO_GLOBE)] = [True]
    operation.handle_zone_pinned_results = [True, False]
    _Timer.reached_results = {0: [True]}

    operation.goto_globe()

    assert operation.interval_resets == [button_key(os_assets.MAP_GOTO_GLOBE_FOG)]
    assert _Timer.reset_count == 1
    assert operation.device.clicks == []


def test_os_map_goto_globe_raises_after_repeated_blocked_clicks() -> None:
    operation = _GlobeOperation()
    operation.in_globe_results = [False] * 5
    operation.appear_then_click_results[button_key(os_assets.MAP_GOTO_GLOBE)] = [True] * 5

    with pytest.raises(RewardUncollectedError):
        operation.goto_globe()

    assert operation.interval_resets == [button_key(os_assets.MAP_GOTO_GLOBE_FOG)] * 5


def test_os_map_goto_globe_can_keep_zone_pinned() -> None:
    operation = _GlobeOperation()
    operation.in_globe_results = [True]
    operation.zone_pinned_results = [False, True]

    operation.goto_globe(unpin=False)

    assert ("is_zone_pinned",) in operation.calls
    assert ("handle_zone_pinned",) not in operation.calls


def test_globe_enter_clicks_zone_entrance() -> None:
    operation = _GlobeOperation()
    operation.pinned_name = "SAFE"
    operation.in_map_results = [False, True]
    operation.zone_pinned_results = [True]
    _Timer.reached_results = {0: [True]}

    operation.enter_globe(zone=_zone())

    assert operation.device.clicks == [os_assets.ZONE_ENTRANCE]
    assert _Timer.reset_count == 1


def test_globe_enter_raises_when_zone_locked() -> None:
    operation = _GlobeOperation()
    operation.in_map_results = [False]
    operation.zone_pinned_results = [True]
    operation.appear_results[button_key(os_assets.ZONE_LOCKED)] = [True]

    with pytest.raises(OSExploreError):
        operation.enter_globe(zone=_zone())

    assert operation.device.clicks == []


def test_globe_enter_clears_click_timer_after_action_point_handler() -> None:
    operation = _GlobeOperation()
    operation.pinned_name = "DANGEROUS"
    operation.in_map_results = [False, True]
    operation.zone_pinned_results = [False]
    operation.action_point_results = [True]

    zone = _zone()
    operation.enter_globe(zone=zone)

    assert _Timer.clear_count == 1
    assert (
        "handle_action_point",
        {
            "zone": zone,
            "pinned": "DANGEROUS",
        },
    ) in operation.calls
