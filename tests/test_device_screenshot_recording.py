from types import SimpleNamespace
from typing import TYPE_CHECKING, cast, override

import numpy as np

from module.base.utils import load_image
from module.device.screenshot import Screenshot
from module.replay.recorder import ReplayRecorder

if TYPE_CHECKING:
    from datetime import datetime
    from pathlib import Path

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


class _CountingRecorder(ReplayRecorder):
    def __init__(self) -> None:
        super().__init__(max_frames=4)
        self.record_calls = 0

    @override
    def record_frame(self, image: ImageArray, *, captured_at: datetime | None = None) -> None:
        self.record_calls += 1
        super().record_frame(image, captured_at=captured_at)


class _Screenshot(Screenshot):
    def __init__(self, frames: list[ImageArray]) -> None:
        self.config = cast(
            "AzurLaneConfig",
            SimpleNamespace(Error_SaveError=True, Error_ScreenshotLength=4),
        )
        self.capture = cast("CaptureService", _Capture(frames))
        self.orientation = 0
        self._screenshot_interval = _Timer()
        self._recorder = _CountingRecorder()
        self._black_checks = iter((False, True))

    @property
    @override
    def replay_recorder(self) -> ReplayRecorder:
        return self._recorder

    @property
    def record_calls(self) -> int:
        return self._recorder.record_calls

    @override
    def check_screen_size(self) -> bool:
        return True

    @override
    def check_screen_black(self) -> bool:
        return next(self._black_checks)


def test_screenshot_records_only_the_business_visible_retry_result(tmp_path: Path) -> None:
    first = np.full((720, 1280, 3), 1, dtype=np.uint8)
    second = np.full((720, 1280, 3), 2, dtype=np.uint8)
    screenshot = _Screenshot([first, second])

    result = screenshot.screenshot()
    dump = screenshot.replay_recorder.dump(tmp_path)

    assert result is second
    assert screenshot.record_calls == 1
    assert len(dump.image_paths) == 1
    assert load_image(dump.image_paths[0])[0, 0].tolist() == [2, 2, 2]
