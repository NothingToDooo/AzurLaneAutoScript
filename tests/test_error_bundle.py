import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Never

import numpy as np
import pytest

from module.base.utils import load_image
from module.diagnostics import ErrorBundleContext, ScreenshotHistory, write_error_bundle

if TYPE_CHECKING:
    from pathlib import Path


def _raise_test_error() -> Never:
    message = "boom"
    raise RuntimeError(message)


def test_screenshot_history_is_bounded_and_owns_its_images() -> None:
    history = ScreenshotHistory(max_frames=2)
    captured_at = datetime(2026, 7, 15, 12, tzinfo=UTC)
    images = [np.full((2, 2, 3), value, dtype=np.uint8) for value in (1, 2, 3)]

    for offset, image in enumerate(images):
        history.record(image, captured_at=captured_at + timedelta(seconds=offset))
    images[-1][:] = 9

    snapshot = history.snapshot()
    assert [int(frame.image[0, 0, 0]) for frame in snapshot] == [2, 3]

    snapshot[-1].image[:] = 8
    assert int(history.snapshot()[-1].image[0, 0, 0]) == 3

    history.clear()
    assert history.snapshot() == ()


@pytest.mark.parametrize("max_frames", [True, 0, -1])
def test_screenshot_history_rejects_invalid_bounds(max_frames: int) -> None:
    with pytest.raises(ValueError, match="positive integer"):
        ScreenshotHistory(max_frames=max_frames)


def test_write_error_bundle_saves_trace_log_tail_and_screenshots(tmp_path: Path) -> None:
    captured_at = datetime(2026, 7, 15, 12, 30, tzinfo=UTC)
    history = ScreenshotHistory(max_frames=2)
    history.record(np.full((2, 2, 3), 7, dtype=np.uint8), captured_at=captured_at)
    log_file = tmp_path / "alas.log"
    log_file.write_text("".join(f"line-{index}\n" for index in range(2_005)), encoding="utf-8")
    context = ErrorBundleContext(
        command="alas",
        task_id="main",
        occurred_at=captured_at,
    )

    try:
        _raise_test_error()
    except RuntimeError as error:
        directory = write_error_bundle(
            context,
            error,
            history.snapshot(),
            log_file=log_file,
            root=tmp_path / "error",
        )

    metadata = json.loads((directory / "error.json").read_text(encoding="utf-8"))
    assert metadata == {
        "timestamp": "2026-07-15T12:30:00+00:00",
        "command": "alas",
        "task": "main",
        "exception_type": "RuntimeError",
        "message": "boom",
        "traceback": metadata["traceback"],
        "screenshots": metadata["screenshots"],
    }
    assert "raise RuntimeError(message)" in metadata["traceback"]
    assert metadata["screenshots"] == ["screenshots/000_20260715-123000-000000.png"]
    assert load_image(directory / metadata["screenshots"][0])[0, 0].tolist() == [7, 7, 7]

    log_tail = (directory / "log.txt").read_text(encoding="utf-8")
    assert log_tail.startswith("line-5\n")
    assert log_tail.endswith("line-2004\n")


def test_write_error_bundle_handles_missing_log_and_directory_collision(tmp_path: Path) -> None:
    context = ErrorBundleContext(
        command="benchmark",
        occurred_at=datetime(2026, 7, 15, 12, 30, tzinfo=UTC),
    )
    error = RuntimeError("failed")

    first = write_error_bundle(context, error, (), log_file=tmp_path / "missing.log", root=tmp_path / "error")
    second = write_error_bundle(context, error, (), log_file=None, root=tmp_path / "error")

    assert first != second
    assert second.name == f"{first.name}-1"
    assert (first / "log.txt").read_text(encoding="utf-8") == ""
    assert json.loads((first / "error.json").read_text(encoding="utf-8"))["screenshots"] == []
