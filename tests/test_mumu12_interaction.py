from datetime import UTC, datetime

import numpy as np
import pytest

from module.application import AbortRequested, AbortToken
from module.interaction import (
    AppStatus,
    Click,
    FrameId,
    LongPress,
    Mumu12GameSession,
    ScreenPoint,
    SemanticTarget,
    Swipe,
)


class _Clock:
    def __init__(self) -> None:
        self.value = 10.0

    def monotonic(self) -> float:
        self.value += 1
        return self.value

    @staticmethod
    def now() -> datetime:
        return datetime(2026, 7, 13, tzinfo=UTC)


class _Capture:
    def __init__(self) -> None:
        self.image = np.zeros((2, 3, 3), dtype=np.uint8)

    def screenshot(self) -> np.ndarray:
        return self.image

    def release(self) -> None:
        pass


class _Controller:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def click(self, x: int, y: int) -> None:
        self.calls.append(("click", x, y))

    def long_click(self, x: int, y: int, duration: float = 1.0) -> None:
        self.calls.append(("long_click", x, y, duration))

    def swipe(self, p1: tuple[int, int], p2: tuple[int, int]) -> None:
        self.calls.append(("swipe", p1, p2))


class _App:
    def __init__(self) -> None:
        self.running = False
        self.calls: list[str] = []

    def is_running(self) -> bool:
        return self.running

    def start(self) -> None:
        self.calls.append("start")
        self.running = True

    def stop(self) -> None:
        self.calls.append("stop")
        self.running = False


def _session() -> tuple[Mumu12GameSession, _Capture, _Controller, _App, AbortToken]:
    capture = _Capture()
    controller = _Controller()
    app = _App()
    session = Mumu12GameSession.from_services(
        capture=capture,
        controller=controller,
        app=app,
        clock=_Clock(),
    )
    return session, capture, controller, app, AbortToken()


def test_frame_source_is_pure_and_numbers_frames() -> None:
    session, capture, controller, app, abort = _session()

    first = session.frames.capture(abort)
    second = session.frames.capture(abort)
    capture.image[0, 0, 0] = 9

    assert first.id == FrameId(0)
    assert second.id == FrameId(1)
    assert first.pixels[0, 0, 0] == 0
    assert controller.calls == []
    assert app.calls == []


def test_action_sink_dispatches_typed_actions_and_returns_sequence() -> None:
    session, _, controller, _, abort = _session()
    target = SemanticTarget("test.target")

    first = session.actions.perform(Click(target, ScreenPoint(1, 2), FrameId(0)), abort)
    second = session.actions.perform(LongPress(target, ScreenPoint(3, 4), 0.5, FrameId(0)), abort)
    third = session.actions.perform(
        Swipe(target, ScreenPoint(5, 6), ScreenPoint(7, 8), FrameId(0)),
        abort,
    )

    assert (first.sequence, second.sequence, third.sequence) == (0, 1, 2)
    assert controller.calls == [
        ("click", 1, 2),
        ("long_click", 3, 4, 0.5),
        ("swipe", (5, 6), (7, 8)),
    ]


def test_action_sink_rejects_points_outside_fixed_viewport() -> None:
    session, _, controller, _, abort = _session()
    action = Click(SemanticTarget("outside"), ScreenPoint(1280, 10), FrameId(0))

    with pytest.raises(ValueError, match="outside the 1280x720 viewport"):
        session.actions.perform(action, abort)

    assert controller.calls == []


def test_every_live_io_boundary_checks_abort_before_side_effect() -> None:
    session, _, controller, app, abort = _session()
    abort.request("manual stop")

    with pytest.raises(AbortRequested, match="manual stop"):
        session.frames.capture(abort)
    with pytest.raises(AbortRequested, match="manual stop"):
        session.actions.perform(
            Click(SemanticTarget("target"), ScreenPoint(1, 2), FrameId(0)),
            abort,
        )
    with pytest.raises(AbortRequested, match="manual stop"):
        session.app.start(abort)

    assert controller.calls == []
    assert app.calls == []


def test_app_lifecycle_uses_the_same_cancelled_session() -> None:
    session, _, _, app, abort = _session()

    assert session.app.status(abort) is AppStatus.STOPPED
    session.app.start(abort)
    assert session.app.status(abort) is AppStatus.RUNNING
    session.app.stop(abort)

    assert app.calls == ["start", "stop"]
