from typing import TypeVar

import pytest

from module.os_handler import assets as os_assets
from module.os_handler import strategic as strategic_module
from module.os_handler.strategic import StrategicSearchHandler

_T = TypeVar("_T")


def button_key(button: object) -> str:
    return str(getattr(button, "name", repr(button)))


class _Device:
    def __init__(self) -> None:
        self.clicks: list[object] = []

    def click(self, button: object) -> None:
        self.clicks.append(button)


class _Scroll:
    def __init__(self, appear_results: list[bool] | None = None) -> None:
        self.appear_results = appear_results or []
        self.drag_threshold = 0.0
        self.edge_add: tuple[float, float] | None = None
        self.set_calls: list[tuple[float, object]] = []
        self.set_bottom_calls: list[object] = []
        self.appear_calls: list[object] = []

    def set(self, value: float, *, main: object) -> None:
        self.set_calls.append((value, main))

    def set_bottom(self, *, main: object) -> None:
        self.set_bottom_calls.append(main)

    def appear(self, *, main: object) -> bool:
        self.appear_calls.append(main)
        if self.appear_results:
            return self.appear_results.pop(0)
        return True


class _StrategicSearch(StrategicSearchHandler):
    def __init__(self) -> None:
        self.device = _Device()
        self.selected_results: dict[str, list[bool]] = {}
        self.appear_calls: list[tuple[str, dict[str, object]]] = []
        self.loop_timeouts: list[int | None] = []

    def set_option(self) -> bool:
        return self.strategic_search_set_option()

    def loop(self, timeout: int | None = None) -> range:
        self.loop_timeouts.append(timeout)
        return range(5)

    def _next_result(self, results: list[_T], *, default: _T) -> _T:
        if results:
            return results.pop(0)
        return default

    def _strategy_option_selected(self, button: object) -> bool:
        return self._next_result(self.selected_results.get(button_key(button), []), default=False)

    def appear(self, button: object, **kwargs: object) -> bool:
        self.appear_calls.append((button_key(button), kwargs))
        return True


@pytest.fixture
def offset_calls(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    calls: list[tuple[str, str]] = []

    def patch(button: object) -> None:
        def load_offset(reference: object) -> None:
            calls.append((button_key(button), button_key(reference)))

        monkeypatch.setattr(button, "load_offset", load_offset)

    patch(os_assets.STRATEGIC_SEARCH_DEVICE_STOP)
    patch(os_assets.STRATEGIC_SEARCH_DEVICE_CONTINUE)
    patch(os_assets.STRATEGIC_SEARCH_SUBMIT_OFF)
    patch(os_assets.STRATEGIC_SEARCH_SUBMIT_ON)
    return calls


def test_strategic_search_set_option_keeps_selected_options(
    monkeypatch: pytest.MonkeyPatch, offset_calls: list[tuple[str, str]]
) -> None:
    search = _StrategicSearch()
    search.selected_results = {
        button_key(os_assets.STRATEGIC_SEARCH_ZONEMODE_REPEAT): [True],
        button_key(os_assets.STRATEGIC_SEARCH_MERCHANT_STOP): [True],
        button_key(os_assets.STRATEGIC_SEARCH_DEVICE_STOP): [True],
        button_key(os_assets.STRATEGIC_SEARCH_SUBMIT_ON): [True],
    }
    scroll = _Scroll([True, True])
    monkeypatch.setattr(strategic_module, "STRATEGIC_SEARCH_SCROLL", scroll)

    result = search.set_option()

    assert result is True
    assert search.device.clicks == []
    assert scroll.set_calls == [(0.5, search)]
    assert scroll.set_bottom_calls == [search]
    assert offset_calls == [
        (
            button_key(os_assets.STRATEGIC_SEARCH_DEVICE_STOP),
            button_key(os_assets.STRATEGIC_SEARCH_DEVICE_CHECK),
        ),
        (
            button_key(os_assets.STRATEGIC_SEARCH_DEVICE_CONTINUE),
            button_key(os_assets.STRATEGIC_SEARCH_DEVICE_CHECK),
        ),
        (
            button_key(os_assets.STRATEGIC_SEARCH_SUBMIT_OFF),
            button_key(os_assets.STRATEGIC_SEARCH_SUBMIT_CHECK),
        ),
        (
            button_key(os_assets.STRATEGIC_SEARCH_SUBMIT_ON),
            button_key(os_assets.STRATEGIC_SEARCH_SUBMIT_CHECK),
        ),
    ]


def test_strategic_search_set_option_clicks_unselected_options(
    monkeypatch: pytest.MonkeyPatch, offset_calls: list[tuple[str, str]]
) -> None:
    search = _StrategicSearch()
    search.selected_results = {
        button_key(os_assets.STRATEGIC_SEARCH_ZONEMODE_REPEAT): [False, True, True],
        button_key(os_assets.STRATEGIC_SEARCH_ZONEMODE_RANDOM): [True],
        button_key(os_assets.STRATEGIC_SEARCH_MERCHANT_STOP): [False, True],
        button_key(os_assets.STRATEGIC_SEARCH_MERCHANT_CONTINUE): [True],
        button_key(os_assets.STRATEGIC_SEARCH_DEVICE_STOP): [False, True],
        button_key(os_assets.STRATEGIC_SEARCH_DEVICE_CONTINUE): [True],
        button_key(os_assets.STRATEGIC_SEARCH_SUBMIT_ON): [False, True],
        button_key(os_assets.STRATEGIC_SEARCH_SUBMIT_OFF): [True],
    }
    scroll = _Scroll([True, True])
    monkeypatch.setattr(strategic_module, "STRATEGIC_SEARCH_SCROLL", scroll)

    result = search.set_option()

    assert result is True
    assert [button_key(button) for button in search.device.clicks] == [
        button_key(os_assets.STRATEGIC_SEARCH_ZONEMODE_REPEAT),
        button_key(os_assets.STRATEGIC_SEARCH_MERCHANT_STOP),
        button_key(os_assets.STRATEGIC_SEARCH_DEVICE_STOP),
        button_key(os_assets.STRATEGIC_SEARCH_SUBMIT_ON),
    ]
    assert len(offset_calls) == 8


def test_strategic_search_set_option_fails_when_scroll_disappears(
    monkeypatch: pytest.MonkeyPatch, offset_calls: list[tuple[str, str]]
) -> None:
    search = _StrategicSearch()
    search.selected_results = {
        button_key(os_assets.STRATEGIC_SEARCH_ZONEMODE_REPEAT): [True],
        button_key(os_assets.STRATEGIC_SEARCH_MERCHANT_STOP): [True],
    }
    scroll = _Scroll([False, False, False, False, False])
    monkeypatch.setattr(strategic_module, "STRATEGIC_SEARCH_SCROLL", scroll)

    result = search.set_option()

    assert result is False
    assert search.device.clicks == []
    assert offset_calls == []
