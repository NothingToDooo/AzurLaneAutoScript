import json
from pathlib import Path
from typing import get_type_hints

import pytest
from PIL import Image

from module.replay import (
    ClickAction,
    ReplayActionMismatchError,
    ReplayDevice,
    ReplayFrame,
    ReplayFrameIncompleteError,
    ReplayFramesExhaustedError,
    ReplayIncompleteError,
    SwipeAction,
    read_trace,
    write_trace,
)


class _Button:
    def __init__(self, name: str) -> None:
        self.name = name

    def __str__(self) -> str:
        return self.name


def _make_image(path: Path, color: tuple[int, int, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (1280, 720), color).save(path)


def _write_trace_payload(trace_path: Path, payload: object) -> None:
    trace_path.write_text(json.dumps(payload), encoding="utf-8")


def test_trace_round_trip_is_deterministic_and_uses_relative_image_paths(tmp_path: Path) -> None:
    image_path = tmp_path / "frames" / "frame-001.png"
    trace_path = tmp_path / "trace.json"
    _make_image(image_path, (10, 20, 30))
    frames = (
        ReplayFrame(
            image_path=image_path,
            expected_actions=(
                ClickAction(target="BATTLE_PREPARATION"),
                SwipeAction(start=(100, 200), end=(300, 400)),
            ),
        ),
    )

    write_trace(trace_path, frames)
    first_bytes = trace_path.read_bytes()
    write_trace(trace_path, frames)

    payload = json.loads(trace_path.read_text(encoding="utf-8"))
    assert trace_path.read_bytes() == first_bytes
    assert payload["version"] == 1
    assert payload["frames"][0]["image_path"] == "frames/frame-001.png"
    assert read_trace(trace_path) == frames


def test_write_trace_canonicalizes_relative_image_path(tmp_path: Path) -> None:
    trace_directory = tmp_path / "bundle"
    trace_directory.mkdir()
    image_path = trace_directory / "frame.png"
    trace_path = trace_directory / "trace.json"
    _make_image(image_path, (10, 20, 30))

    write_trace(trace_path, (ReplayFrame(Path("frames/../frame.png")),))

    payload = json.loads(trace_path.read_text(encoding="utf-8"))
    assert payload["frames"][0]["image_path"] == "frame.png"


def test_write_trace_rejects_absolute_image_outside_trace_directory(tmp_path: Path) -> None:
    trace_directory = tmp_path / "bundle"
    trace_directory.mkdir()
    outside_image = tmp_path / "outside.png"
    _make_image(outside_image, (10, 20, 30))

    with pytest.raises(ValueError, match="inside trace directory"):
        write_trace(trace_directory / "trace.json", (ReplayFrame(outside_image),))


def test_write_trace_rejects_escaping_relative_image_path(tmp_path: Path) -> None:
    trace_directory = tmp_path / "bundle"
    trace_directory.mkdir()

    with pytest.raises(ValueError, match="inside trace directory"):
        write_trace(trace_directory / "trace.json", (ReplayFrame(Path("../outside.png")),))


def test_read_trace_rejects_absolute_image_path(tmp_path: Path) -> None:
    trace_path = tmp_path / "trace.json"
    outside_image = tmp_path.parent / "outside.png"
    _write_trace_payload(
        trace_path,
        {
            "version": 1,
            "frames": [{"image_path": outside_image.as_posix(), "expected_actions": []}],
        },
    )

    with pytest.raises(ValueError, match="relative"):
        read_trace(trace_path)


def test_read_trace_rejects_escaping_image_path(tmp_path: Path) -> None:
    trace_path = tmp_path / "trace.json"
    _write_trace_payload(
        trace_path,
        {
            "version": 1,
            "frames": [{"image_path": "../outside.png", "expected_actions": []}],
        },
    )

    with pytest.raises(ValueError, match="inside trace directory"):
        read_trace(trace_path)


def test_read_trace_rejects_noncanonical_parent_component(tmp_path: Path) -> None:
    trace_path = tmp_path / "trace.json"
    _write_trace_payload(
        trace_path,
        {
            "version": 1,
            "frames": [{"image_path": "frames/../frame.png", "expected_actions": []}],
        },
    )

    with pytest.raises(ValueError, match="canonical"):
        read_trace(trace_path)


@pytest.mark.parametrize("version", [True, 1.0])
def test_read_trace_rejects_non_integer_version(tmp_path: Path, version: object) -> None:
    trace_path = tmp_path / "trace.json"
    _write_trace_payload(trace_path, {"version": version, "frames": []})

    with pytest.raises(ValueError, match="integer 1"):
        read_trace(trace_path)


def test_replay_device_public_annotations_can_be_resolved() -> None:
    assert "image" in get_type_hints(ReplayDevice)
    assert "return" in get_type_hints(ReplayDevice.screenshot)
    assert {"p1", "p2", "return"} <= get_type_hints(ReplayDevice.swipe).keys()


def test_screenshot_activates_next_frame_and_sets_image(tmp_path: Path) -> None:
    image_path = tmp_path / "frame.png"
    _make_image(image_path, (1, 2, 3))
    device = ReplayDevice((ReplayFrame(image_path=image_path),))

    image = device.screenshot()

    assert device.image is image
    assert image.shape == (720, 1280, 3)


def test_click_and_swipe_consume_semantic_actions_in_order(tmp_path: Path) -> None:
    image_path = tmp_path / "frame.png"
    _make_image(image_path, (1, 2, 3))
    frame = ReplayFrame(
        image_path=image_path,
        expected_actions=(
            ClickAction(target="BATTLE_PREPARATION"),
            SwipeAction(start=(100, 200), end=(300, 400)),
        ),
    )
    device = ReplayDevice((frame,))
    device.screenshot()

    device.click(_Button("BATTLE_PREPARATION"))
    device.swipe((100.9, 200.1), (300.8, 400.2))

    device.assert_complete()


def test_click_accepts_device_control_check_argument(tmp_path: Path) -> None:
    image_path = tmp_path / "frame.png"
    _make_image(image_path, (1, 2, 3))
    device = ReplayDevice(
        (
            ReplayFrame(
                image_path=image_path,
                expected_actions=(ClickAction(target="CONTINUE"),),
            ),
        )
    )
    device.screenshot()

    device.click(_Button("CONTINUE"), control_check=False)

    device.assert_complete()


def test_swipe_accepts_scroll_call_keywords(tmp_path: Path) -> None:
    image_path = tmp_path / "frame.png"
    _make_image(image_path, (1, 2, 3))
    device = ReplayDevice(
        (
            ReplayFrame(
                image_path=image_path,
                expected_actions=(SwipeAction(start=(100, 200), end=(300, 400)),),
            ),
        )
    )
    device.screenshot()

    device.swipe(
        p1=(100, 200),
        p2=(300, 400),
        duration=(0.1, 0.2),
        name="SHOP_SCROLL",
        distance_check=True,
    )

    device.assert_complete()


def test_short_swipe_only_consumes_action_when_distance_check_is_disabled(tmp_path: Path) -> None:
    image_path = tmp_path / "frame.png"
    _make_image(image_path, (1, 2, 3))
    device = ReplayDevice(
        (
            ReplayFrame(
                image_path=image_path,
                expected_actions=(SwipeAction(start=(100, 200), end=(105, 205)),),
            ),
        )
    )
    device.screenshot()

    device.swipe((100, 200), (105, 205), distance_check=True)
    with pytest.raises(ReplayIncompleteError, match="unconsumed action"):
        device.assert_complete()

    device.swipe((100, 200), (105, 205), distance_check=False)
    device.assert_complete()


def test_action_mismatch_does_not_consume_expected_action(tmp_path: Path) -> None:
    image_path = tmp_path / "frame.png"
    _make_image(image_path, (1, 2, 3))
    device = ReplayDevice(
        (
            ReplayFrame(
                image_path=image_path,
                expected_actions=(ClickAction(target="EXPECTED_BUTTON"),),
            ),
        )
    )
    device.screenshot()

    with pytest.raises(ReplayActionMismatchError, match="EXPECTED_BUTTON"):
        device.click(_Button("OTHER_BUTTON"))

    device.click(_Button("EXPECTED_BUTTON"))
    device.assert_complete()


def test_action_kind_must_follow_recorded_order(tmp_path: Path) -> None:
    image_path = tmp_path / "frame.png"
    _make_image(image_path, (1, 2, 3))
    device = ReplayDevice(
        (
            ReplayFrame(
                image_path=image_path,
                expected_actions=(ClickAction(target="EXPECTED_BUTTON"),),
            ),
        )
    )
    device.screenshot()

    with pytest.raises(ReplayActionMismatchError, match="click"):
        device.swipe((1, 2), (3, 4), distance_check=False)


def test_screenshot_rejects_incomplete_previous_frame(tmp_path: Path) -> None:
    first_path = tmp_path / "first.png"
    second_path = tmp_path / "second.png"
    _make_image(first_path, (1, 2, 3))
    _make_image(second_path, (4, 5, 6))
    device = ReplayDevice(
        (
            ReplayFrame(first_path, (ClickAction(target="CONTINUE"),)),
            ReplayFrame(second_path),
        )
    )
    device.screenshot()

    with pytest.raises(ReplayFrameIncompleteError, match="frame 0"):
        device.screenshot()

    device.click(_Button("CONTINUE"))
    device.screenshot()
    device.assert_complete()


def test_screenshot_raises_when_frames_are_exhausted(tmp_path: Path) -> None:
    image_path = tmp_path / "frame.png"
    _make_image(image_path, (1, 2, 3))
    device = ReplayDevice((ReplayFrame(image_path),))
    device.screenshot()

    with pytest.raises(ReplayFramesExhaustedError, match="exhausted"):
        device.screenshot()

    device.assert_complete()


def test_assert_complete_rejects_unconsumed_actions(tmp_path: Path) -> None:
    image_path = tmp_path / "frame.png"
    _make_image(image_path, (1, 2, 3))
    device = ReplayDevice((ReplayFrame(image_path, (ClickAction(target="CONTINUE"),)),))
    device.screenshot()

    with pytest.raises(ReplayIncompleteError, match="frame 0"):
        device.assert_complete()


def test_assert_complete_rejects_unseen_frames(tmp_path: Path) -> None:
    image_path = tmp_path / "frame.png"
    _make_image(image_path, (1, 2, 3))
    device = ReplayDevice((ReplayFrame(image_path),))

    with pytest.raises(ReplayIncompleteError, match="1 frame"):
        device.assert_complete()
