import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING, Protocol

from module.interaction.model import Click, Frame, LongPress, Swipe

if TYPE_CHECKING:
    from collections.abc import Sequence

    from module.interaction.model import Action
    from module.interaction.ports import ActionSink, CancellationSignal, FrameSource

type _EventValue = str | int | float | bool | None


class InteractionScope(StrEnum):
    LOGIN = "login"
    MENU = "menu"
    CAMPAIGN = "campaign"
    COMBAT = "combat"
    ASSIST = "assist"


@dataclass(frozen=True, slots=True)
class InteractionEvent:
    kind: str
    payload: Mapping[str, _EventValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.kind, str):
            message = "event kind must be a string"
            raise TypeError(message)
        if not self.kind.strip() or self.kind != self.kind.strip():
            message = "event kind must not be blank or contain surrounding whitespace"
            raise ValueError(message)
        if not isinstance(self.payload, Mapping):
            message = "event payload must be a mapping"
            raise TypeError(message)

        payload = dict(self.payload)
        for key, value in payload.items():
            if not isinstance(key, str):
                message = "event payload keys must be strings"
                raise TypeError(message)
            if not key.strip() or key != key.strip():
                message = "event payload keys must not be blank or contain surrounding whitespace"
                raise ValueError(message)
            if value is not None and not isinstance(value, str | int | float | bool):
                message = "event payload values must be scalar"
                raise TypeError(message)
            if isinstance(value, float) and not math.isfinite(value):
                message = "event payload numbers must be finite"
                raise ValueError(message)

        object.__setattr__(self, "payload", MappingProxyType(payload))


@dataclass(frozen=True, slots=True)
class InterruptionDecision:
    action: Action | None = None
    events: tuple[InteractionEvent, ...] = ()

    def __post_init__(self) -> None:
        if self.action is not None and not isinstance(self.action, Click | LongPress | Swipe):
            message = "action must be an Action or None"
            raise TypeError(message)
        if not isinstance(self.events, tuple):
            message = "events must be a tuple"
            raise TypeError(message)
        if any(not isinstance(event, InteractionEvent) for event in self.events):
            message = "events must contain only InteractionEvent values"
            raise TypeError(message)
        if self.action is None and not self.events:
            message = "an interruption decision must contain an action or at least one event"
            raise ValueError(message)


class InterruptionHandler(Protocol):
    scopes: frozenset[InteractionScope]

    def inspect(self, frame: Frame, scope: InteractionScope) -> InterruptionDecision | None: ...


@dataclass(frozen=True, slots=True)
class PollResult:
    frame: Frame
    events: tuple[InteractionEvent, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.frame, Frame):
            message = "frame must be a Frame"
            raise TypeError(message)
        if not isinstance(self.events, tuple):
            message = "events must be a tuple"
            raise TypeError(message)
        if any(not isinstance(event, InteractionEvent) for event in self.events):
            message = "events must contain only InteractionEvent values"
            raise TypeError(message)


class InterruptionLoopError(RuntimeError):
    pass


class Poller:
    __slots__ = ("_action_sink", "_frame_source", "_handlers", "_max_actions")

    def __init__(
        self,
        frame_source: FrameSource,
        action_sink: ActionSink,
        handlers: Sequence[InterruptionHandler],
        *,
        max_actions: int = 16,
    ) -> None:
        if type(max_actions) is not int:
            message = "max_actions must be an integer"
            raise TypeError(message)
        if max_actions < 0:
            message = "max_actions must be non-negative"
            raise ValueError(message)

        self._frame_source = frame_source
        self._action_sink = action_sink
        normalized_handlers = tuple(handlers)
        for handler in normalized_handlers:
            scopes = getattr(handler, "scopes", None)
            if not isinstance(scopes, frozenset) or any(not isinstance(scope, InteractionScope) for scope in scopes):
                message = "handler scopes must be a frozenset of InteractionScope values"
                raise TypeError(message)
            if not callable(getattr(handler, "inspect", None)):
                message = "handlers must implement inspect()"
                raise TypeError(message)
        self._handlers = normalized_handlers
        self._max_actions = max_actions

    def poll(self, scope: InteractionScope, cancellation: CancellationSignal) -> PollResult:
        if not isinstance(scope, InteractionScope):
            message = "scope must be an InteractionScope"
            raise TypeError(message)

        frame = self._frame_source.capture(cancellation)
        events: list[InteractionEvent] = []
        action_count = 0

        while True:
            action = self._inspect_handlers(frame, scope, events)
            if action is None:
                return PollResult(frame=frame, events=tuple(events))
            if action.based_on_frame != frame.id:
                message = (
                    f"interruption action is based on frame {action.based_on_frame.value}, "
                    f"but the current frame is {frame.id.value}"
                )
                raise InterruptionLoopError(message)
            if action_count >= self._max_actions:
                message = f"interruption handlers exceeded max_actions={self._max_actions}"
                raise InterruptionLoopError(message)

            self._action_sink.perform(action, cancellation)
            action_count += 1
            frame = self._frame_source.capture(cancellation)

    def _inspect_handlers(
        self,
        frame: Frame,
        scope: InteractionScope,
        events: list[InteractionEvent],
    ) -> Action | None:
        for handler in self._handlers:
            if scope not in handler.scopes:
                continue
            decision = handler.inspect(frame, scope)
            if decision is None:
                continue
            events.extend(decision.events)
            if decision.action is not None:
                return decision.action
        return None
