from typing import TYPE_CHECKING, Never

from module.base.utils import load_image
from module.interaction.model import ActionReceipt, AppStatus, Frame
from module.replay.session_trace import (
    ActionStep,
    AppStartStep,
    AppStatusStep,
    AppStopStep,
    CaptureStep,
    ReplayStep,
    ReplayTrace,
)

if TYPE_CHECKING:
    from module.interaction.model import Action
    from module.interaction.ports import ActionSink, AppLifecycle, CancellationSignal, FrameSource


class ReplaySessionError(RuntimeError):
    pass


class ReplaySessionMismatchError(ReplaySessionError):
    pass


class ReplaySessionExhaustedError(ReplaySessionError):
    pass


class ReplaySessionIncompleteError(ReplaySessionError):
    pass


class ReplaySessionImageLoadError(ReplaySessionError):
    pass


class ReplayGameSession:
    __slots__ = ("_cursor", "actions", "app", "frames")

    frames: FrameSource
    actions: ActionSink
    app: AppLifecycle

    def __init__(self, trace: ReplayTrace) -> None:
        if not isinstance(trace, ReplayTrace):
            message = "trace must be a ReplayTrace"
            raise TypeError(message)
        self._cursor = _ReplayCursor(trace)
        self.frames = _ReplayFrameSource(self._cursor)
        self.actions = _ReplayActionSink(self._cursor)
        self.app = _ReplayAppLifecycle(self._cursor)

    def assert_complete(self) -> None:
        self._cursor.assert_complete()


class _ReplayCursor:
    __slots__ = ("_action_sequence", "_cursor", "_trace")

    def __init__(self, trace: ReplayTrace) -> None:
        self._trace = trace
        self._cursor = 0
        self._action_sequence = 0

    @property
    def position(self) -> int:
        return self._cursor

    @property
    def action_sequence(self) -> int:
        return self._action_sequence

    def peek(self, *, operation: str) -> ReplayStep:
        if self._cursor >= len(self._trace.steps):
            message = f"replay session exhausted before {operation} at cursor {self._cursor}"
            raise ReplaySessionExhaustedError(message)
        return self._trace.steps[self._cursor]

    def advance(self) -> None:
        self._cursor += 1

    def advance_action(self) -> None:
        self._cursor += 1
        self._action_sequence += 1

    def assert_complete(self) -> None:
        remaining = len(self._trace.steps) - self._cursor
        if remaining:
            message = f"replay session incomplete: {remaining} step(s) remain at cursor {self._cursor}"
            raise ReplaySessionIncompleteError(message)


class _ReplayFrameSource:
    __slots__ = ("_cursor",)

    def __init__(self, cursor: _ReplayCursor) -> None:
        self._cursor = cursor

    def capture(self, cancellation: CancellationSignal) -> Frame:
        cancellation.raise_if_requested()
        step = self._cursor.peek(operation="capture")
        if not isinstance(step, CaptureStep):
            _raise_step_mismatch(self._cursor, expected="capture", actual=step)
        try:
            pixels = load_image(step.image_path)
        except OSError as error:
            message = f"unable to load replay image at step {self._cursor.position}: {step.image_path}"
            raise ReplaySessionImageLoadError(message) from error
        frame = Frame(
            id=step.frame_id,
            captured_at_monotonic=step.captured_at_monotonic,
            captured_at_wall=step.captured_at_wall,
            pixels=pixels,
        )
        self._cursor.advance()
        return frame


class _ReplayActionSink:
    __slots__ = ("_cursor",)

    def __init__(self, cursor: _ReplayCursor) -> None:
        self._cursor = cursor

    def perform(self, action: Action, cancellation: CancellationSignal) -> ActionReceipt:
        cancellation.raise_if_requested()
        step = self._cursor.peek(operation="perform action")
        if not isinstance(step, ActionStep):
            _raise_step_mismatch(self._cursor, expected="action", actual=step)
        if step.action != action:
            message = (
                f"replay action mismatch at step {self._cursor.position}: expected {step.action!r}, got {action!r}"
            )
            raise ReplaySessionMismatchError(message)
        receipt = ActionReceipt(
            sequence=self._cursor.action_sequence,
            action=action,
            issued_at_monotonic=step.issued_at_monotonic,
        )
        self._cursor.advance_action()
        return receipt


class _ReplayAppLifecycle:
    __slots__ = ("_cursor",)

    def __init__(self, cursor: _ReplayCursor) -> None:
        self._cursor = cursor

    def status(self, cancellation: CancellationSignal) -> AppStatus:
        cancellation.raise_if_requested()
        step = self._cursor.peek(operation="read app status")
        if not isinstance(step, AppStatusStep):
            _raise_step_mismatch(self._cursor, expected="app_status", actual=step)
        self._cursor.advance()
        return step.status

    def start(self, cancellation: CancellationSignal) -> None:
        cancellation.raise_if_requested()
        step = self._cursor.peek(operation="start app")
        if not isinstance(step, AppStartStep):
            _raise_step_mismatch(self._cursor, expected="app_start", actual=step)
        self._cursor.advance()

    def stop(self, cancellation: CancellationSignal) -> None:
        cancellation.raise_if_requested()
        step = self._cursor.peek(operation="stop app")
        if not isinstance(step, AppStopStep):
            _raise_step_mismatch(self._cursor, expected="app_stop", actual=step)
        self._cursor.advance()


def _raise_step_mismatch(cursor: _ReplayCursor, *, expected: str, actual: ReplayStep) -> Never:
    message = f"replay step mismatch at cursor {cursor.position}: expected {expected}, got {_step_kind(actual)}"
    raise ReplaySessionMismatchError(message)


def _step_kind(step: ReplayStep) -> str:
    if isinstance(step, CaptureStep):
        return "capture"
    if isinstance(step, ActionStep):
        return "action"
    if isinstance(step, AppStatusStep):
        return "app_status"
    if isinstance(step, AppStartStep):
        return "app_start"
    return "app_stop"
