from typing import TYPE_CHECKING, override

import numpy as np

from module.os import map_operation as os_map_operation
from module.os.globe_zone import Zone
from module.os.map_data import DIC_OS_MAP
from module.os.map_operation import OSMapOperation

if TYPE_CHECKING:
    from collections.abc import Iterator

    import pytest

    from module.base.button import Button, MatchOffset
    from module.base.timer import Timer
    from module.base.type_alias import ImageArray
    from module.device.control import ButtonTarget


class _Timer:
    def __init__(self, results: list[bool]) -> None:
        self.results = list(results)
        self.reset_count = 0
        self.start_count = 0

    def start(self) -> _Timer:
        self.start_count += 1
        return self

    def reached(self) -> bool:
        if not self.results:
            return False
        return self.results.pop(0)

    def reset(self) -> None:
        self.reset_count += 1


class _Device:
    image: ImageArray = np.empty((1, 1, 3), dtype=np.uint8)

    def __init__(self) -> None:
        self.clicks = []

    def click(self, button: ButtonTarget) -> None:
        self.clicks.append(button)


class _OSMapOperation(OSMapOperation):
    device: _Device

    def __init__(self) -> None:
        self.device = _Device()
        self.calls = []
        self.map_event_results = []
        self.reward_results = []
        self.globe_results = []
        self.exchange_results = []
        self.in_map_results = []
        self.os_check_results = []
        self.current_zone_results = []
        self.globe_zone = Zone(2, DIC_OS_MAP[2])

    @staticmethod
    def _next(results: list[bool]) -> bool:
        if results:
            return results.pop(0)
        return False

    @override
    def loop(
        self,
        *,
        skip_first: bool = True,
        timeout: float | Timer | None = None,
    ) -> Iterator[ImageArray]:
        del skip_first, timeout
        for _ in range(3):
            yield self.device.image

    def wait_os_map_buttons(self) -> None:
        self.calls.append(("wait_os_map_buttons",))

    @override
    def handle_map_event(self) -> str:
        result = self.map_event_results.pop(0) if self.map_event_results else ""
        self.calls.append(("handle_map_event", result))
        return result

    @override
    def appear_then_click(
        self,
        button: Button,
        offset: MatchOffset | None = 0,
        interval: float = 0,
        similarity: float = 0.85,
        threshold: int = 30,
    ) -> bool:
        self.calls.append(("appear_then_click", button, offset, interval, similarity, threshold))
        return self._next(self.reward_results)

    @override
    def is_in_globe(self) -> bool:
        result = self._next(self.globe_results)
        self.calls.append(("is_in_globe", result))
        return result

    def os_globe_goto_map(self, *_args: object, **_kwargs: object) -> None:
        self.calls.append(("os_globe_goto_map",))

    @override
    def appear(
        self,
        button: Button,
        offset: MatchOffset | None = 0,
        interval: float = 0,
        similarity: float = 0.85,
        threshold: int = 10,
    ) -> bool:
        self.calls.append(("appear", button, offset, interval, similarity, threshold))
        if button == os_map_operation.EXCHANGE_CHECK:
            return self._next(self.exchange_results)
        if button == os_map_operation.OS_CHECK:
            return self._next(self.os_check_results)
        return False

    @override
    def is_in_map(self) -> bool:
        result = self._next(self.in_map_results)
        self.calls.append(("is_in_map", result))
        return result

    @override
    def wait_until_appear(
        self,
        button: Button,
        offset: MatchOffset | None = 0,
        *,
        skip_first_screenshot: bool = False,
    ) -> None:
        del offset, skip_first_screenshot
        self.calls.append(("wait_until_appear", button))

    @override
    def get_current_zone(self) -> Zone:
        self.calls.append(("get_current_zone",))
        return self.current_zone_results.pop(0)

    @override
    def get_current_zone_from_globe(self) -> Zone:
        self.calls.append(("get_current_zone_from_globe",))
        return self.globe_zone


def test_zone_init_resets_timeout_after_map_event(monkeypatch: pytest.MonkeyPatch) -> None:
    timer = _Timer([False])
    monkeypatch.setattr(os_map_operation, "Timer", lambda *_args, **_kwargs: timer)
    operation = _OSMapOperation()
    operation.map_event_results = ["map_event", ""]
    operation.globe_results = [False]
    operation.exchange_results = [False]
    operation.in_map_results = [True, True]
    operation.os_check_results = [True]
    zone = Zone(1, DIC_OS_MAP[1])
    operation.current_zone_results = [zone]

    assert operation.zone_init() == zone

    assert timer.reset_count == 1
    assert ("get_current_zone",) in operation.calls


def test_zone_init_falls_back_to_globe_zone_after_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    timer = _Timer([True])
    monkeypatch.setattr(os_map_operation, "Timer", lambda *_args, **_kwargs: timer)
    operation = _OSMapOperation()
    operation.globe_results = [False]
    operation.exchange_results = [False]
    operation.in_map_results = [True]
    operation.os_check_results = [True]

    assert operation.zone_init() == operation.globe_zone

    assert ("get_current_zone_from_globe",) in operation.calls


def test_zone_init_returns_none_without_fallback_after_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    timer = _Timer([True])
    monkeypatch.setattr(os_map_operation, "Timer", lambda *_args, **_kwargs: timer)
    operation = _OSMapOperation()
    operation.globe_results = [False]
    operation.exchange_results = [False]
    operation.in_map_results = [True]
    operation.os_check_results = [True]

    assert operation.zone_init(fallback_init=False) is None

    assert ("get_current_zone_from_globe",) not in operation.calls
