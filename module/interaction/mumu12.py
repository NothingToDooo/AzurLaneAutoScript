from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from module.interaction.model import (
    Action,
    ActionReceipt,
    AppStatus,
    Click,
    Frame,
    FrameId,
    LongPress,
    ScreenPoint,
    Swipe,
)

if TYPE_CHECKING:
    from datetime import datetime

    from module.interaction.model import ImagePixels
    from module.interaction.ports import CancellationSignal


class _CaptureService(Protocol):
    def screenshot(self) -> ImagePixels: ...


class _ControllerService(Protocol):
    def click(self, x: int, y: int) -> None: ...

    def long_click(self, x: int, y: int, duration: float = 1.0) -> None: ...

    def swipe(self, p1: tuple[int, int], p2: tuple[int, int]) -> None: ...


class _AppControllerService(Protocol):
    def is_running(self) -> bool: ...

    def start(self) -> None: ...

    def stop(self) -> None: ...


class _TimestampSource(Protocol):
    def monotonic(self) -> float: ...

    def now(self) -> datetime: ...


_VIEWPORT_WIDTH = 1280
_VIEWPORT_HEIGHT = 720


class Mumu12FrameSource:
    __slots__ = ("_capture", "_clock", "_next_frame_id")

    def __init__(self, capture: _CaptureService, clock: _TimestampSource) -> None:
        self._capture = capture
        self._clock = clock
        self._next_frame_id = 0

    def capture(self, cancellation: CancellationSignal) -> Frame:
        cancellation.raise_if_requested()
        pixels = self._capture.screenshot()
        cancellation.raise_if_requested()
        frame = Frame(
            id=FrameId(self._next_frame_id),
            captured_at_monotonic=self._clock.monotonic(),
            captured_at_wall=self._clock.now(),
            pixels=pixels,
        )
        self._next_frame_id += 1
        return frame


class Mumu12ActionSink:
    __slots__ = ("_clock", "_controller", "_next_sequence")

    def __init__(self, controller: _ControllerService, clock: _TimestampSource) -> None:
        self._controller = controller
        self._clock = clock
        self._next_sequence = 0

    def perform(self, action: Action, cancellation: CancellationSignal) -> ActionReceipt:
        cancellation.raise_if_requested()
        if isinstance(action, Click):
            _validate_viewport_point(action.point)
            self._controller.click(action.point.x, action.point.y)
        elif isinstance(action, LongPress):
            _validate_viewport_point(action.point)
            self._controller.long_click(action.point.x, action.point.y, action.duration_seconds)
        elif isinstance(action, Swipe):
            _validate_viewport_point(action.start)
            _validate_viewport_point(action.end)
            self._controller.swipe((action.start.x, action.start.y), (action.end.x, action.end.y))
        else:
            message = f"unsupported action: {type(action).__name__}"
            raise TypeError(message)

        receipt = ActionReceipt(
            sequence=self._next_sequence,
            action=action,
            issued_at_monotonic=self._clock.monotonic(),
        )
        self._next_sequence += 1
        return receipt


class Mumu12AppLifecycle:
    __slots__ = ("_app",)

    def __init__(self, app: _AppControllerService) -> None:
        self._app = app

    def status(self, cancellation: CancellationSignal) -> AppStatus:
        cancellation.raise_if_requested()
        return AppStatus.RUNNING if self._app.is_running() else AppStatus.STOPPED

    def start(self, cancellation: CancellationSignal) -> None:
        cancellation.raise_if_requested()
        self._app.start()

    def stop(self, cancellation: CancellationSignal) -> None:
        cancellation.raise_if_requested()
        self._app.stop()


@dataclass(frozen=True, slots=True)
class Mumu12GameSession:
    frames: Mumu12FrameSource
    actions: Mumu12ActionSink
    app: Mumu12AppLifecycle

    @classmethod
    def from_services(
        cls,
        *,
        capture: _CaptureService,
        controller: _ControllerService,
        app: _AppControllerService,
        clock: _TimestampSource,
    ) -> Mumu12GameSession:
        return cls(
            frames=Mumu12FrameSource(capture, clock),
            actions=Mumu12ActionSink(controller, clock),
            app=Mumu12AppLifecycle(app),
        )


def _validate_viewport_point(point: ScreenPoint) -> None:
    if point.x >= _VIEWPORT_WIDTH or point.y >= _VIEWPORT_HEIGHT:
        message = f"point is outside the 1280x720 viewport: ({point.x}, {point.y})"
        raise ValueError(message)
