from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

import numpy as np
import pytest

from module.application import AbortRequested, AbortToken
from module.interaction import (
    ActionReceipt,
    Click,
    Frame,
    FrameId,
    LongPress,
    ScreenPoint,
    SemanticTarget,
    Swipe,
    SystemClock,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from module.interaction import Action


def _frame(pixels: np.ndarray) -> Frame:
    return Frame(
        id=FrameId(3),
        captured_at_monotonic=12.5,
        captured_at_wall=datetime(2026, 7, 13, tzinfo=UTC),
        pixels=pixels,
    )


def test_frame_owns_read_only_pixels() -> None:
    source = np.zeros((2, 3, 3), dtype=np.uint8)

    frame = _frame(source)
    source[0, 0, 0] = 7

    assert frame.pixels[0, 0, 0] == 0
    assert frame.pixels.flags.c_contiguous
    assert not frame.pixels.flags.writeable
    with pytest.raises(ValueError, match="read-only"):
        frame.pixels[0, 0, 0] = 9


@pytest.mark.parametrize(
    ("pixels", "error_type", "message"),
    [
        (np.zeros((2, 2), dtype=np.float32), TypeError, "uint8"),
        (np.zeros((0, 2), dtype=np.uint8), ValueError, "non-empty"),
        (np.zeros((1,), dtype=np.uint8), ValueError, "2D or 3D"),
    ],
)
def test_frame_rejects_invalid_images(pixels: np.ndarray, error_type: type[Exception], message: str) -> None:
    with pytest.raises(error_type, match=message):
        _frame(pixels)


def test_frame_requires_timezone_aware_wall_time() -> None:
    with pytest.raises(ValueError, match="timezone"):
        Frame(
            id=FrameId(0),
            captured_at_monotonic=0,
            captured_at_wall=datetime(2026, 7, 13),
            pixels=np.zeros((1, 1), dtype=np.uint8),
        )


def test_actions_keep_semantic_target_coordinates_and_source_frame() -> None:
    target = SemanticTarget("campaign.enemy.A1")
    frame_id = FrameId(8)

    click = Click(target=target, point=ScreenPoint(10, 20), based_on_frame=frame_id)
    long_press = LongPress(
        target=target,
        point=ScreenPoint(10, 20),
        duration_seconds=0.8,
        based_on_frame=frame_id,
    )
    swipe = Swipe(
        target=SemanticTarget("campaign.pan.right"),
        start=ScreenPoint(10, 20),
        end=ScreenPoint(50, 20),
        based_on_frame=frame_id,
    )

    assert click.based_on_frame == frame_id
    assert long_press.duration_seconds == 0.8
    assert swipe.start != swipe.end
    assert ActionReceipt(sequence=2, action=click, issued_at_monotonic=13).action is click


@pytest.mark.parametrize(
    ("factory", "message"),
    [
        (lambda: SemanticTarget(" "), "semantic target"),
        (lambda: ScreenPoint(-1, 0), "screen coordinates"),
        (
            lambda: LongPress(
                target=SemanticTarget("target"),
                point=ScreenPoint(0, 0),
                duration_seconds=0,
                based_on_frame=FrameId(0),
            ),
            "long-press duration",
        ),
        (
            lambda: Swipe(
                target=SemanticTarget("target"),
                start=ScreenPoint(0, 0),
                end=ScreenPoint(0, 0),
                based_on_frame=FrameId(0),
            ),
            "swipe start",
        ),
    ],
)
def test_interaction_values_reject_ambiguous_input(factory: Callable[[], object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        factory()


def test_semantic_target_rejects_surrounding_whitespace() -> None:
    with pytest.raises(ValueError, match="surrounding whitespace"):
        SemanticTarget(" campaign.start ")


@pytest.mark.parametrize(
    "factory",
    [
        lambda: Click(cast("SemanticTarget", "bad"), ScreenPoint(1, 2), FrameId(0)),
        lambda: Click(
            SemanticTarget("target"),
            cast("ScreenPoint", (1, 2)),
            FrameId(0),
        ),
        lambda: Click(
            SemanticTarget("target"),
            ScreenPoint(1, 2),
            cast("FrameId", 0),
        ),
        lambda: LongPress(
            SemanticTarget("target"),
            cast("ScreenPoint", (1, 2)),
            1.0,
            FrameId(0),
        ),
        lambda: Swipe(
            SemanticTarget("target"),
            ScreenPoint(1, 2),
            cast("ScreenPoint", (3, 4)),
            FrameId(0),
        ),
    ],
)
def test_actions_reject_untyped_fields(factory: Callable[[], object]) -> None:
    with pytest.raises(TypeError):
        factory()


def test_action_receipt_rejects_untyped_action() -> None:
    with pytest.raises(TypeError, match="receipt action"):
        ActionReceipt(
            sequence=0,
            action=cast("Action", object()),
            issued_at_monotonic=1.0,
        )


@pytest.mark.parametrize("seconds", [-1, float("inf"), float("nan")])
def test_system_clock_rejects_invalid_sleep_duration(seconds: float) -> None:
    with pytest.raises(ValueError, match="finite non-negative"):
        SystemClock().sleep(seconds, AbortToken())


def test_system_clock_checks_abort_even_for_zero_duration() -> None:
    abort = AbortToken()
    abort.request("manual stop")

    with pytest.raises(AbortRequested, match="manual stop"):
        SystemClock().sleep(0, abort)
