from collections.abc import Sequence

import cv2
import numpy as np

from module.replay.trace import ClickAction, RecordedAction, ReplayFrame, SwipeAction

type ImageArray = np.ndarray
type PointInput = Sequence[int | float]


class ReplayError(RuntimeError):
    """截图回放失败。"""


class ReplayActionMismatchError(ReplayError):
    """实际语义动作与记录不一致。"""


class ReplayFrameIncompleteError(ReplayError):
    """上一帧仍有动作未消费。"""


class ReplayFramesExhaustedError(ReplayError):
    """没有更多可激活的截图帧。"""


class ReplayIncompleteError(ReplayError):
    """回放结束时仍有帧或动作未消费。"""


class ReplayFrameNotActiveError(ReplayError):
    """语义动作发生前尚未激活截图帧。"""


class ReplayImageLoadError(ReplayError):
    """回放截图无法读取。"""


class ReplayDevice:
    __slots__ = ("_active_frame_index", "_frames", "_next_action_index", "_next_frame_index", "image")

    image: ImageArray

    def __init__(self, frames: tuple[ReplayFrame, ...]) -> None:
        self._frames = tuple(frames)
        self._next_frame_index = 0
        self._active_frame_index: int | None = None
        self._next_action_index = 0

    def screenshot(self) -> ImageArray:
        self._reject_incomplete_active_frame()
        if self._next_frame_index >= len(self._frames):
            message = "Replay frames exhausted"
            raise ReplayFramesExhaustedError(message)

        frame_index = self._next_frame_index
        frame = self._frames[frame_index]
        image = cv2.imread(str(frame.image_path), cv2.IMREAD_COLOR)
        if image is None:
            message = f"Unable to load replay frame {frame_index}: {frame.image_path}"
            raise ReplayImageLoadError(message)

        self.image = image
        self._active_frame_index = frame_index
        self._next_frame_index += 1
        self._next_action_index = 0
        return image

    def click(self, button: object) -> None:
        target = str(button)
        expected = self._next_expected_action(actual=f"click {target!r}")
        if not isinstance(expected, ClickAction) or expected.target != target:
            self._raise_action_mismatch(expected=expected, actual=f"click {target!r}")
        self._next_action_index += 1

    def swipe(self, start: PointInput, end: PointInput) -> None:
        normalized_start = _normalize_point(start, field_name="start")
        normalized_end = _normalize_point(end, field_name="end")
        actual_action = SwipeAction(start=normalized_start, end=normalized_end)
        expected = self._next_expected_action(actual=_describe_action(actual_action))
        if not isinstance(expected, SwipeAction) or expected != actual_action:
            self._raise_action_mismatch(expected=expected, actual=_describe_action(actual_action))
        self._next_action_index += 1

    def assert_complete(self) -> None:
        if self._active_frame_index is not None:
            active_frame = self._frames[self._active_frame_index]
            remaining_actions = len(active_frame.expected_actions) - self._next_action_index
            if remaining_actions:
                message = (
                    f"Replay incomplete: frame {self._active_frame_index} has {remaining_actions} unconsumed action(s)"
                )
                raise ReplayIncompleteError(message)
        remaining_frames = len(self._frames) - self._next_frame_index
        if remaining_frames:
            message = f"Replay incomplete: {remaining_frames} frame(s) were not activated"
            raise ReplayIncompleteError(message)

    def _reject_incomplete_active_frame(self) -> None:
        if self._active_frame_index is None:
            return
        active_frame = self._frames[self._active_frame_index]
        remaining_actions = len(active_frame.expected_actions) - self._next_action_index
        if remaining_actions:
            message = (
                f"Cannot activate next frame: frame {self._active_frame_index} has "
                f"{remaining_actions} unconsumed action(s)"
            )
            raise ReplayFrameIncompleteError(message)

    def _next_expected_action(self, *, actual: str) -> RecordedAction:
        if self._active_frame_index is None:
            message = f"No active replay frame for {actual}; call screenshot() first"
            raise ReplayFrameNotActiveError(message)
        active_frame = self._frames[self._active_frame_index]
        if self._next_action_index >= len(active_frame.expected_actions):
            message = f"Frame {self._active_frame_index} has no remaining actions; got {actual}"
            raise ReplayActionMismatchError(message)
        return active_frame.expected_actions[self._next_action_index]

    def _raise_action_mismatch(self, *, expected: RecordedAction, actual: str) -> None:
        message = (
            f"Frame {self._active_frame_index} action {self._next_action_index} mismatch: "
            f"expected {_describe_action(expected)}, got {actual}"
        )
        raise ReplayActionMismatchError(message)


def _normalize_point(point: PointInput, *, field_name: str) -> tuple[int, int]:
    if len(point) != 2:
        message = f"{field_name} must contain exactly two coordinates"
        raise ValueError(message)
    try:
        return int(point[0]), int(point[1])
    except (TypeError, ValueError) as error:
        message = f"{field_name} coordinates must be numeric"
        raise ValueError(message) from error


def _describe_action(action: RecordedAction) -> str:
    if isinstance(action, ClickAction):
        return f"click {action.target!r}"
    return f"swipe {action.start!r} -> {action.end!r}"
