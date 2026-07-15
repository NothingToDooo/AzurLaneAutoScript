from types import SimpleNamespace
from typing import TYPE_CHECKING, cast, override

import numpy as np

from module.device.screenshot import Screenshot
from module.diagnostics import ScreenshotHistory

if TYPE_CHECKING:
    from datetime import datetime

    from module.base.type_alias import ImageArray
    from module.config.config import AzurLaneConfig
    from module.device.contracts import CaptureService


class _Timer:
    def wait(self) -> None:
        pass

    def reset(self) -> None:
        pass


class _Capture:
    def __init__(self, frames: list[ImageArray]) -> None:
        self.frames = frames

    def screenshot(self) -> ImageArray:
        return self.frames.pop(0)


class _CountingHistory(ScreenshotHistory):
    def __init__(self) -> None:
        super().__init__(max_frames=4)
        self.record_calls = 0

    @override
    def record(self, image: ImageArray, *, captured_at: datetime | None = None) -> None:
        self.record_calls += 1
        super().record(image, captured_at=captured_at)


class _Screenshot(Screenshot):
    def __init__(self, frames: list[ImageArray]) -> None:
        self.config = cast(
            "AzurLaneConfig",
            SimpleNamespace(Error_ScreenshotLength=4),
        )
        self.capture = cast("CaptureService", _Capture(frames))
        self.orientation = 0
        self._screenshot_interval = _Timer()
        self._history = _CountingHistory()
        self._black_checks = iter((False, True))

    @property
    @override
    def error_screenshots(self) -> ScreenshotHistory:
        return self._history

    @property
    def record_calls(self) -> int:
        return self._history.record_calls

    @override
    def check_screen_size(self) -> bool:
        return True

    @override
    def check_screen_black(self) -> bool:
        return next(self._black_checks)


def test_screenshot_records_only_the_business_visible_retry_result() -> None:
    first = np.full((720, 1280, 3), 1, dtype=np.uint8)
    second = np.full((720, 1280, 3), 2, dtype=np.uint8)
    screenshot = _Screenshot([first, second])

    result = screenshot.screenshot()
    frames = screenshot.error_screenshots.snapshot()

    assert result is second
    assert screenshot.record_calls == 1
    assert len(frames) == 1
    assert frames[0].image[0, 0].tolist() == [2, 2, 2]
