import math
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

import numpy as np
from numpy.typing import NDArray

type ImagePixels = NDArray[np.uint8]


@dataclass(frozen=True, slots=True, order=True)
class FrameId:
    value: int

    def __post_init__(self) -> None:
        if type(self.value) is not int:
            message = "frame id must be an integer"
            raise TypeError(message)
        if self.value < 0:
            message = "frame id must be a non-negative integer"
            raise ValueError(message)


@dataclass(frozen=True, slots=True)
class Frame:
    id: FrameId
    captured_at_monotonic: float
    captured_at_wall: datetime
    pixels: ImagePixels

    def __post_init__(self) -> None:
        if isinstance(self.captured_at_monotonic, bool) or not isinstance(self.captured_at_monotonic, int | float):
            message = "frame monotonic timestamp must be a number"
            raise TypeError(message)
        if not math.isfinite(self.captured_at_monotonic) or self.captured_at_monotonic < 0:
            message = "frame monotonic timestamp must be non-negative"
            raise ValueError(message)
        if not isinstance(self.captured_at_wall, datetime):
            message = "frame wall timestamp must be a datetime"
            raise TypeError(message)
        if self.captured_at_wall.tzinfo is None or self.captured_at_wall.utcoffset() is None:
            message = "frame wall timestamp must include a timezone"
            raise ValueError(message)
        if not isinstance(self.pixels, np.ndarray):
            message = "frame pixels must be a numpy array"
            raise TypeError(message)
        if self.pixels.dtype != np.uint8:
            message = "frame pixels must use uint8"
            raise TypeError(message)
        if self.pixels.ndim not in (2, 3) or any(dimension <= 0 for dimension in self.pixels.shape):
            message = "frame pixels must be a non-empty 2D or 3D image"
            raise ValueError(message)

        # Frame 独占像素副本，避免截图服务和识别器通过共享 ndarray 隐式改写彼此状态。
        owned_pixels = np.array(self.pixels, dtype=np.uint8, copy=True, order="C")
        owned_pixels.setflags(write=False)
        object.__setattr__(self, "pixels", owned_pixels)


@dataclass(frozen=True, slots=True, order=True)
class ScreenPoint:
    x: int
    y: int

    def __post_init__(self) -> None:
        if type(self.x) is not int or type(self.y) is not int:
            message = "screen coordinates must be integers"
            raise TypeError(message)
        if self.x < 0 or self.y < 0:
            message = "screen coordinates must be non-negative integers"
            raise ValueError(message)


@dataclass(frozen=True, slots=True, order=True)
class SemanticTarget:
    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str):
            message = "semantic target must be a string"
            raise TypeError(message)
        if not self.value or self.value != self.value.strip():
            message = "semantic target must not be empty or contain surrounding whitespace"
            raise ValueError(message)


def _validate_action_fields(
    target: SemanticTarget,
    based_on_frame: FrameId,
    *points: ScreenPoint,
) -> None:
    if not isinstance(target, SemanticTarget):
        message = "action target must be a SemanticTarget"
        raise TypeError(message)
    if not isinstance(based_on_frame, FrameId):
        message = "action based_on_frame must be a FrameId"
        raise TypeError(message)
    if any(not isinstance(point, ScreenPoint) for point in points):
        message = "action points must be ScreenPoint values"
        raise TypeError(message)


@dataclass(frozen=True, slots=True)
class Click:
    target: SemanticTarget
    point: ScreenPoint
    based_on_frame: FrameId

    def __post_init__(self) -> None:
        _validate_action_fields(self.target, self.based_on_frame, self.point)


@dataclass(frozen=True, slots=True)
class LongPress:
    target: SemanticTarget
    point: ScreenPoint
    duration_seconds: float
    based_on_frame: FrameId

    def __post_init__(self) -> None:
        _validate_action_fields(self.target, self.based_on_frame, self.point)
        if isinstance(self.duration_seconds, bool) or not isinstance(self.duration_seconds, int | float):
            message = "long-press duration must be a number"
            raise TypeError(message)
        if not math.isfinite(self.duration_seconds) or self.duration_seconds <= 0:
            message = "long-press duration must be positive"
            raise ValueError(message)


@dataclass(frozen=True, slots=True)
class Swipe:
    target: SemanticTarget
    start: ScreenPoint
    end: ScreenPoint
    based_on_frame: FrameId

    def __post_init__(self) -> None:
        _validate_action_fields(self.target, self.based_on_frame, self.start, self.end)
        if self.start == self.end:
            message = "swipe start and end must differ"
            raise ValueError(message)


type Action = Click | LongPress | Swipe


@dataclass(frozen=True, slots=True)
class ActionReceipt:
    sequence: int
    action: Action
    issued_at_monotonic: float

    def __post_init__(self) -> None:
        if type(self.sequence) is not int:
            message = "action sequence must be an integer"
            raise TypeError(message)
        if self.sequence < 0:
            message = "action sequence must be a non-negative integer"
            raise ValueError(message)
        if not isinstance(self.action, Click | LongPress | Swipe):
            message = "receipt action must be an Action"
            raise TypeError(message)
        if isinstance(self.issued_at_monotonic, bool) or not isinstance(self.issued_at_monotonic, int | float):
            message = "action timestamp must be a number"
            raise TypeError(message)
        if not math.isfinite(self.issued_at_monotonic) or self.issued_at_monotonic < 0:
            message = "action timestamp must be non-negative"
            raise ValueError(message)


class AppStatus(StrEnum):
    RUNNING = "running"
    STOPPED = "stopped"
    UNKNOWN = "unknown"
