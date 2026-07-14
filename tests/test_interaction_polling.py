from datetime import UTC, datetime
from typing import TYPE_CHECKING, ClassVar, cast

import numpy as np
import pytest

from module.interaction import (
    Action,
    ActionReceipt,
    CancellationSignal,
    Click,
    Frame,
    FrameId,
    InteractionEvent,
    InteractionScope,
    InterruptionDecision,
    InterruptionLoopError,
    Poller,
    PollResult,
    ScreenPoint,
    SemanticTarget,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from module.interaction import InterruptionHandler


class _Cancellation:
    def __init__(self) -> None:
        self.checks = 0

    def raise_if_requested(self) -> None:
        self.checks += 1


class _FrameSource:
    def __init__(self) -> None:
        self.frames: list[Frame] = []
        self.captures = 0

    def capture(self, cancellation: CancellationSignal) -> Frame:
        cancellation.raise_if_requested()
        frame = _frame(self.captures)
        self.frames.append(frame)
        self.captures += 1
        return frame


class _ActionSink:
    def __init__(self) -> None:
        self.actions: list[Action] = []

    def perform(self, action: Action, cancellation: CancellationSignal) -> ActionReceipt:
        cancellation.raise_if_requested()
        self.actions.append(action)
        return ActionReceipt(sequence=len(self.actions) - 1, action=action, issued_at_monotonic=1)


class _Handler:
    def __init__(
        self,
        name: str,
        scopes: frozenset[InteractionScope],
        inspect: Callable[[Frame, InteractionScope], InterruptionDecision | None],
        calls: list[str],
    ) -> None:
        self.name = name
        self.scopes = scopes
        self._inspect = inspect
        self._calls = calls

    def inspect(self, frame: Frame, scope: InteractionScope) -> InterruptionDecision | None:
        self._calls.append(f"{self.name}:{scope.value}:{frame.id.value}")
        return self._inspect(frame, scope)


def _frame(value: int) -> Frame:
    return Frame(
        id=FrameId(value),
        captured_at_monotonic=float(value),
        captured_at_wall=datetime(2026, 7, 13, tzinfo=UTC),
        pixels=np.zeros((1, 1, 3), dtype=np.uint8),
    )


def _click(frame: Frame) -> Click:
    return Click(
        target=SemanticTarget("interruption.dismiss"),
        point=ScreenPoint(10, 20),
        based_on_frame=frame.id,
    )


def test_interaction_event_owns_a_read_only_payload_copy() -> None:
    payload = {"phase": "login", "attempt": 2}

    event = InteractionEvent("login.observed", payload)
    payload["attempt"] = 3

    assert event.payload == {"phase": "login", "attempt": 2}
    with pytest.raises(TypeError):
        cast("dict[str, str | int | float | bool | None]", event.payload)["attempt"] = 4


def test_interaction_event_rejects_non_finite_payload_number() -> None:
    with pytest.raises(ValueError, match="finite"):
        InteractionEvent("bad", {"value": float("nan")})


def test_poller_rejects_invalid_handler_contract() -> None:
    class _BadScopes:
        scopes: ClassVar = {InteractionScope.MENU}

        @staticmethod
        def inspect(frame: Frame, scope: InteractionScope) -> None:
            del frame, scope

    with pytest.raises(TypeError, match="handler scopes"):
        Poller(
            _FrameSource(),
            _ActionSink(),
            (cast("InterruptionHandler", _BadScopes()),),
        )


def test_interruption_decision_must_describe_work_or_an_event() -> None:
    with pytest.raises(ValueError, match="action or at least one event"):
        InterruptionDecision()


def test_poll_without_handling_returns_the_captured_frame() -> None:
    source = _FrameSource()
    sink = _ActionSink()
    cancellation = _Cancellation()

    result = Poller(source, sink, ()).poll(InteractionScope.LOGIN, cancellation)

    assert result == PollResult(frame=source.frames[0])
    assert result.frame is source.frames[0]
    assert source.captures == 1
    assert sink.actions == []
    assert cancellation.checks == 1


def test_poll_runs_only_matching_handlers_in_registration_order() -> None:
    calls: list[str] = []
    source = _FrameSource()
    sink = _ActionSink()
    event = InteractionEvent("combat.observed")
    handlers = (
        _Handler("login", frozenset({InteractionScope.LOGIN}), lambda _frame, _scope: None, calls),
        _Handler("first", frozenset({InteractionScope.COMBAT}), lambda _frame, _scope: None, calls),
        _Handler(
            "second",
            frozenset({InteractionScope.COMBAT, InteractionScope.ASSIST}),
            lambda _frame, _scope: InterruptionDecision(events=(event,)),
            calls,
        ),
    )

    result = Poller(source, sink, handlers).poll(InteractionScope.COMBAT, _Cancellation())

    assert calls == ["first:combat:0", "second:combat:0"]
    assert result.events == (event,)


def test_event_only_handlers_accumulate_and_return_the_same_frame() -> None:
    calls: list[str] = []
    source = _FrameSource()
    sink = _ActionSink()
    first = InteractionEvent("notice.first")
    second = InteractionEvent("notice.second")
    handlers = (
        _Handler(
            "first",
            frozenset({InteractionScope.MENU}),
            lambda _frame, _scope: InterruptionDecision(events=(first,)),
            calls,
        ),
        _Handler(
            "second",
            frozenset({InteractionScope.MENU}),
            lambda _frame, _scope: InterruptionDecision(events=(second,)),
            calls,
        ),
    )

    result = Poller(source, sink, handlers).poll(InteractionScope.MENU, _Cancellation())

    assert result == PollResult(frame=source.frames[0], events=(first, second))
    assert result.frame is source.frames[0]
    assert source.captures == 1
    assert sink.actions == []


def test_action_restarts_handler_order_on_a_fresh_frame() -> None:
    calls: list[str] = []
    source = _FrameSource()
    sink = _ActionSink()

    def dismiss_once(frame: Frame, scope: InteractionScope) -> InterruptionDecision | None:
        del scope
        if frame.id == FrameId(0):
            return InterruptionDecision(action=_click(frame))
        return None

    handlers = (
        _Handler("dismiss", frozenset({InteractionScope.CAMPAIGN}), dismiss_once, calls),
        _Handler("observe", frozenset({InteractionScope.CAMPAIGN}), lambda _frame, _scope: None, calls),
    )
    cancellation = _Cancellation()

    result = Poller(source, sink, handlers).poll(InteractionScope.CAMPAIGN, cancellation)

    assert calls == ["dismiss:campaign:0", "dismiss:campaign:1", "observe:campaign:1"]
    assert result.frame is source.frames[1]
    assert [action.based_on_frame for action in sink.actions] == [FrameId(0)]
    assert source.captures == 2
    assert cancellation.checks == 3


def test_poll_rejects_an_action_based_on_a_different_frame() -> None:
    calls: list[str] = []
    source = _FrameSource()
    sink = _ActionSink()
    stale_action = Click(
        target=SemanticTarget("stale"),
        point=ScreenPoint(0, 0),
        based_on_frame=FrameId(99),
    )
    handler = _Handler(
        "stale",
        frozenset({InteractionScope.LOGIN}),
        lambda _frame, _scope: InterruptionDecision(action=stale_action),
        calls,
    )

    with pytest.raises(InterruptionLoopError, match=r"based on frame 99.*current frame is 0"):
        Poller(source, sink, (handler,)).poll(InteractionScope.LOGIN, _Cancellation())

    assert sink.actions == []
    assert source.captures == 1


def test_poll_fails_before_an_infinite_handler_exceeds_the_action_budget() -> None:
    calls: list[str] = []
    source = _FrameSource()
    sink = _ActionSink()
    handler = _Handler(
        "infinite",
        frozenset({InteractionScope.ASSIST}),
        lambda frame, _scope: InterruptionDecision(action=_click(frame)),
        calls,
    )

    with pytest.raises(InterruptionLoopError, match="exceeded max_actions=2"):
        Poller(source, sink, (handler,), max_actions=2).poll(InteractionScope.ASSIST, _Cancellation())

    assert len(sink.actions) == 2
    assert source.captures == 3
    assert len(calls) == 3
