from typing import ClassVar, TypeVar

import pytest

from module.private_quarters import assets as pq_assets
from module.private_quarters import interact as interact_module
from module.private_quarters.interact import PQInteract

_T = TypeVar("_T")


def button_key(button: object) -> str:
    return getattr(button, "name", repr(button))


class _Timer:
    next_index: ClassVar[int] = 0
    reached_results: ClassVar[dict[int, list[bool]]] = {}

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


class _PrivateQuarters(PQInteract):
    device: _Device

    def __init__(self) -> None:
        self.device = _Device()
        self.calls: list[tuple[object, ...]] = []
        self.appear_results: dict[str, list[bool]] = {}
        self.appear_then_click_results: dict[str, list[bool]] = {}

    def wait_interact_button(self) -> None:
        self._pq_wait_interact_button()

    def interact_once(self) -> None:
        self._pq_interact_once()

    @staticmethod
    def _next_result(results: list[_T], *, default: _T) -> _T:
        if results:
            return results.pop(0)
        return default

    def appear(self, button: object, *_args: object, **kwargs: object) -> bool:
        key = button_key(button)
        self.calls.append(("appear", key, kwargs))
        return self._next_result(self.appear_results.get(key, []), default=False)

    def appear_then_click(self, button: object, *_args: object, **kwargs: object) -> bool:
        key = button_key(button)
        self.calls.append(("appear_then_click", key, kwargs))
        return self._next_result(self.appear_then_click_results.get(key, []), default=False)

    def interval_clear(self, button: object, *_args: object, **_kwargs: object) -> None:
        self.calls.append(("interval_clear", button))


class _TrackingPrivateQuarters(PQInteract):
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def interact(self) -> None:
        self.pq_interact()

    def _pq_wait_interact_button(self) -> None:
        self.calls.append(("_pq_wait_interact_button",))

    def _pq_interact_once(self) -> None:
        self.calls.append(("_pq_interact_once",))

    def _pq_goto_room_exit(self) -> None:
        self.calls.append(("_pq_goto_room_exit",))


@pytest.fixture(autouse=True)
def _patch_timer(monkeypatch: pytest.MonkeyPatch) -> None:
    _Timer.next_index = 0
    _Timer.reached_results = {}
    monkeypatch.setattr(interact_module, "Timer", _Timer)


def test_pq_wait_interact_button_clicks_target_until_ready() -> None:
    pq = _PrivateQuarters()
    pq.appear_results[button_key(pq_assets.PRIVATE_QUARTERS_INTERACT)] = [False, True]
    _Timer.reached_results = {0: [True]}

    pq.wait_interact_button()

    assert pq.device.clicks == [pq_assets.PRIVATE_QUARTERS_ROOM_TARGET_CLICK_AREA]
    assert pq.device.screenshot_count == 1


def test_pq_interact_once_enters_and_leaves_confirm() -> None:
    pq = _PrivateQuarters()
    pq.appear_results[button_key(pq_assets.PRIVATE_QUARTERS_INTERACT_CHECK)] = [False, True, True]
    pq.appear_results[button_key(pq_assets.PRIVATE_QUARTERS_INTERACT)] = [False, True]
    pq.appear_then_click_results[button_key(pq_assets.PRIVATE_QUARTERS_INTERACT)] = [True]

    pq.interact_once()

    assert (
        "interval_clear",
        [pq_assets.PRIVATE_QUARTERS_INTERACT_CHECK, pq_assets.PRIVATE_QUARTERS_INTERACT],
    ) in pq.calls
    assert pq_assets.PRIVATE_QUARTERS_ROOM_BACK in pq.device.clicks


def test_pq_interact_runs_three_rounds_then_exits() -> None:
    pq = _TrackingPrivateQuarters()

    pq.interact()

    assert pq.calls == [
        ("_pq_wait_interact_button",),
        ("_pq_interact_once",),
        ("_pq_interact_once",),
        ("_pq_interact_once",),
        ("_pq_goto_room_exit",),
    ]
