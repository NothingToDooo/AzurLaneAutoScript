from types import SimpleNamespace

from module.device.screenshot import Screenshot


class _Timer:
    def __init__(self) -> None:
        self.limit = 0.1


class _ScreenshotContext:
    screenshot_interval_set = Screenshot.screenshot_interval_set

    def __init__(self, interval: float) -> None:
        self.config = SimpleNamespace(
            Optimization_ScreenshotInterval=interval,
            Optimization_CombatScreenshotInterval=0.5,
        )
        self._screenshot_interval = _Timer()

    @property
    def interval_limit(self) -> float:
        return self._screenshot_interval.limit


def test_default_screenshot_interval_uses_compiled_value_directly() -> None:
    context = _ScreenshotContext(0.3)

    context.screenshot_interval_set()

    assert context.config.Optimization_ScreenshotInterval == 0.3
    assert context.interval_limit == 0.3
