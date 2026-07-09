from module.os import map_operation as os_map_operation
from module.os.map_operation import OSMapOperation


class _Timer:
    def __init__(self, results):
        self.results = list(results)
        self.reset_count = 0
        self.start_count = 0

    def start(self):
        self.start_count += 1
        return self

    def reached(self):
        if not self.results:
            return False
        return self.results.pop(0)

    def reset(self):
        self.reset_count += 1


class _Device:
    def __init__(self) -> None:
        self.clicks = []

    def click(self, button) -> None:
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
        self.globe_zone = "globe-zone"

    @staticmethod
    def _next(results):
        if results:
            return results.pop(0)
        return False

    def loop(self):
        yield from range(3)

    def wait_os_map_buttons(self) -> None:
        self.calls.append(("wait_os_map_buttons",))

    def handle_map_event(self):
        result = self._next(self.map_event_results)
        self.calls.append(("handle_map_event", result))
        return result

    def appear_then_click(self, button, **kwargs):
        self.calls.append(("appear_then_click", button, kwargs))
        return self._next(self.reward_results)

    def is_in_globe(self):
        result = self._next(self.globe_results)
        self.calls.append(("is_in_globe", result))
        return result

    def os_globe_goto_map(self) -> None:
        self.calls.append(("os_globe_goto_map",))

    def appear(self, button, **kwargs):
        self.calls.append(("appear", button, kwargs))
        if button == os_map_operation.EXCHANGE_CHECK:
            return self._next(self.exchange_results)
        if button == os_map_operation.OS_CHECK:
            return self._next(self.os_check_results)
        return False

    def is_in_map(self):
        result = self._next(self.in_map_results)
        self.calls.append(("is_in_map", result))
        return result

    def wait_until_appear(self, button) -> None:
        self.calls.append(("wait_until_appear", button))

    def get_current_zone(self):
        self.calls.append(("get_current_zone",))
        return self.current_zone_results.pop(0)

    def get_current_zone_from_globe(self):
        self.calls.append(("get_current_zone_from_globe",))
        return self.globe_zone


def test_zone_init_resets_timeout_after_map_event(monkeypatch) -> None:
    timer = _Timer([False])
    monkeypatch.setattr(os_map_operation, "Timer", lambda *_args, **_kwargs: timer)
    operation = _OSMapOperation()
    operation.map_event_results = [True, False]
    operation.globe_results = [False]
    operation.exchange_results = [False]
    operation.in_map_results = [True, True]
    operation.os_check_results = [True]
    operation.current_zone_results = ["zone"]

    assert operation.zone_init() == "zone"

    assert timer.reset_count == 1
    assert ("get_current_zone",) in operation.calls


def test_zone_init_falls_back_to_globe_zone_after_timeout(monkeypatch) -> None:
    timer = _Timer([True])
    monkeypatch.setattr(os_map_operation, "Timer", lambda *_args, **_kwargs: timer)
    operation = _OSMapOperation()
    operation.globe_results = [False]
    operation.exchange_results = [False]
    operation.in_map_results = [True]
    operation.os_check_results = [True]

    assert operation.zone_init() == "globe-zone"

    assert ("get_current_zone_from_globe",) in operation.calls


def test_zone_init_returns_none_without_fallback_after_timeout(monkeypatch) -> None:
    timer = _Timer([True])
    monkeypatch.setattr(os_map_operation, "Timer", lambda *_args, **_kwargs: timer)
    operation = _OSMapOperation()
    operation.globe_results = [False]
    operation.exchange_results = [False]
    operation.in_map_results = [True]
    operation.os_check_results = [True]

    assert operation.zone_init(fallback_init=False) is None

    assert ("get_current_zone_from_globe",) not in operation.calls
