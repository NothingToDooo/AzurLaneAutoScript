from datetime import datetime
from typing import TYPE_CHECKING

import numpy as np
import pytest

from module.base.utils import load_image
from module.replay import ClickAction, ReplayDevice, SwipeAction, read_trace
from module.replay.recorder import ReplayRecorder

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


def _image(value: int) -> np.ndarray:
    return np.full((8, 12, 3), value, dtype=np.uint8)


def _captured_at(second: int) -> datetime:
    return datetime(2026, 7, 12, 12, 0, second)


def test_recorder_coalesces_idle_frames_and_binds_actions_to_previous_frame(tmp_path: Path) -> None:
    recorder = ReplayRecorder(max_frames=4)
    recorder.record_frame(_image(1), captured_at=_captured_at(1))
    recorder.record_frame(_image(2), captured_at=_captured_at(2))
    recorder.record_action(ClickAction(target="POPUP_CONFIRM_TEST"))
    recorder.record_action(SwipeAction(start=(10, 20), end=(30, 40)))
    recorder.record_frame(_image(3), captured_at=_captured_at(3))
    recorder.record_frame(_image(4), captured_at=_captured_at(4))

    result = recorder.dump(tmp_path)

    assert result.trace_path == tmp_path / "trace.json"
    trace_path = result.trace_path
    assert trace_path is not None
    frames = read_trace(trace_path)
    assert len(frames) == 2
    assert frames[0].expected_actions == (
        ClickAction(target="POPUP_CONFIRM_TEST"),
        SwipeAction(start=(10, 20), end=(30, 40)),
    )
    assert frames[1].expected_actions == ()
    assert load_image(frames[0].image_path)[0, 0].tolist() == [2, 2, 2]
    assert load_image(frames[1].image_path)[0, 0].tolist() == [4, 4, 4]

    replay = ReplayDevice(frames)
    replay.screenshot()
    replay.click("POPUP_CONFIRM_TEST")
    replay.swipe((10, 20), (30, 40))
    replay.screenshot()
    replay.assert_complete()


def test_recorder_ring_keeps_recent_action_frames(tmp_path: Path) -> None:
    recorder = ReplayRecorder(max_frames=2)
    for index, target in enumerate(("FIRST", "SECOND", "THIRD"), start=1):
        recorder.record_frame(_image(index), captured_at=_captured_at(index))
        recorder.record_action(ClickAction(target=target))

    result = recorder.dump(tmp_path)

    assert result.trace_path is not None
    frames = read_trace(result.trace_path)
    assert [frame.expected_actions for frame in frames] == [
        (ClickAction(target="SECOND"),),
        (ClickAction(target="THIRD"),),
    ]


@pytest.mark.parametrize(
    ("record_blocker", "expected"),
    [
        (lambda recorder: recorder.mark_unsupported_action("long_click"), ("long_click",)),
        (lambda recorder: recorder.record_action(ClickAction(target="UNBOUND")), ("ClickAction",)),
    ],
)
def test_recorder_does_not_publish_incomplete_trace(
    tmp_path: Path,
    record_blocker: Callable[[ReplayRecorder], None],
    expected: tuple[str, ...],
) -> None:
    recorder = ReplayRecorder(max_frames=2)
    if expected == ("long_click",):
        recorder.record_frame(_image(1), captured_at=_captured_at(1))
    record_blocker(recorder)
    if expected == ("ClickAction",):
        recorder.record_frame(_image(1), captured_at=_captured_at(1))

    result = recorder.dump(tmp_path)

    assert result.trace_path is None
    assert result.blockers == expected
    assert not (tmp_path / "trace.json").exists()
    assert len(result.image_paths) == 1


def test_recorded_image_is_independent_from_capture_buffer(tmp_path: Path) -> None:
    source = _image(7)
    recorder = ReplayRecorder(max_frames=1)
    recorder.record_frame(source, captured_at=_captured_at(1))
    source[:] = 0

    result = recorder.dump(tmp_path)

    assert source[0, 0].tolist() == [0, 0, 0]
    assert load_image(result.image_paths[0])[0, 0].tolist() == [7, 7, 7]


def test_dump_publishes_trace_only_after_all_images_are_written(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = ReplayRecorder(max_frames=1)
    recorder.record_frame(_image(1), captured_at=_captured_at(1))
    message = "disk full"

    def fail_save(_image_value: np.ndarray, _path: Path) -> None:
        raise OSError(message)

    monkeypatch.setattr("module.replay.recorder.save_image", fail_save)

    with pytest.raises(OSError, match="disk full"):
        recorder.dump(tmp_path)

    assert not (tmp_path / "trace.json").exists()
