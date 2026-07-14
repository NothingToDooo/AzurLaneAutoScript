from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol

from module.application import (
    AbortRequested,
    AbortToken,
    Cancelled,
    Faulted,
    PreemptionRequest,
    RequestAppRestart,
    TaskResult,
)
from module.supervisor.instance_agent import EmptyTickResult, InstanceTickResult, ReadyTickResult, WaitingTickResult

if TYPE_CHECKING:
    from datetime import datetime

    from module.interaction import CancellationSignal


class AgentTicker(Protocol):
    def tick(
        self,
        now: datetime,
        *,
        abort: AbortToken | None = None,
        preemption: PreemptionRequest | None = None,
    ) -> InstanceTickResult: ...


class LoopClock(Protocol):
    def now(self) -> datetime: ...

    def sleep(self, seconds: float, cancellation: CancellationSignal) -> None: ...


class InstanceLoopExitReason(StrEnum):
    EMPTY = "empty"
    PREEMPTED = "preempted"
    RESTART_REQUESTED = "restart_requested"
    CANCELLED = "cancelled"
    FAULTED = "faulted"


@dataclass(frozen=True, slots=True)
class InstanceLoopExit:
    reason: InstanceLoopExitReason
    runs_completed: int
    last_result: TaskResult | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.reason, InstanceLoopExitReason):
            message = "reason must be an InstanceLoopExitReason"
            raise TypeError(message)
        if type(self.runs_completed) is not int or self.runs_completed < 0:
            message = "runs_completed must be a non-negative integer"
            raise ValueError(message)
        if self.last_result is not None and not isinstance(self.last_result, TaskResult):
            message = "last_result must be a TaskResult or None"
            raise TypeError(message)
        if self.runs_completed == 0 and self.last_result is not None:
            message = "an empty loop cannot contain a last_result"
            raise ValueError(message)
        if self.runs_completed > 0 and self.last_result is None:
            message = "a loop with completed runs must contain a last_result"
            raise ValueError(message)


def _require_method(value: object, method: str, *, field_name: str) -> None:
    if isinstance(value, type) or not callable(getattr(value, method, None)):
        message = f"{field_name} must implement {method}()"
        raise TypeError(message)


def _control_signals(
    abort: AbortToken | None,
    preemption: PreemptionRequest | None,
) -> tuple[AbortToken, PreemptionRequest]:
    active_abort = AbortToken() if abort is None else abort
    active_preemption = PreemptionRequest() if preemption is None else preemption
    if not isinstance(active_abort, AbortToken):
        message = "abort must be an AbortToken or None"
        raise TypeError(message)
    if not isinstance(active_preemption, PreemptionRequest):
        message = "preemption must be a PreemptionRequest or None"
        raise TypeError(message)
    return active_abort, active_preemption


def _exit_reason_after_run(result: TaskResult, preemption: PreemptionRequest) -> InstanceLoopExitReason | None:
    if preemption.is_requested:
        return InstanceLoopExitReason.PREEMPTED
    if any(isinstance(effect, RequestAppRestart) for effect in result.effects):
        return InstanceLoopExitReason.RESTART_REQUESTED
    if isinstance(result.outcome, Cancelled):
        return InstanceLoopExitReason.CANCELLED
    if isinstance(result.outcome, Faulted):
        return InstanceLoopExitReason.FAULTED
    return None


class InstanceLoop:
    """串行运行 scheduled jobs；所有进程级控制信号都有明确退出点。"""

    __slots__ = ("_agent", "_clock")

    def __init__(self, agent: AgentTicker, clock: LoopClock) -> None:
        _require_method(agent, "tick", field_name="agent")
        _require_method(clock, "now", field_name="clock")
        _require_method(clock, "sleep", field_name="clock")
        self._agent = agent
        self._clock = clock

    def run(
        self,
        *,
        abort: AbortToken | None = None,
        preemption: PreemptionRequest | None = None,
    ) -> InstanceLoopExit:
        active_abort, active_preemption = _control_signals(abort, preemption)

        runs_completed = 0
        last_result: TaskResult | None = None
        while True:
            tick = self._next_tick(active_abort, active_preemption)
            if tick is None:
                return InstanceLoopExit(InstanceLoopExitReason.CANCELLED, runs_completed, last_result)

            if isinstance(tick, EmptyTickResult):
                return InstanceLoopExit(InstanceLoopExitReason.EMPTY, runs_completed, last_result)
            if isinstance(tick, WaitingTickResult):
                if not self._wait_until(tick.wake_at, active_abort):
                    return InstanceLoopExit(InstanceLoopExitReason.CANCELLED, runs_completed, last_result)
                continue
            if not isinstance(tick, ReadyTickResult):
                message = "AgentTicker.tick() must return an InstanceTickResult"
                raise TypeError(message)

            runs_completed += 1
            last_result = tick.result
            exit_reason = _exit_reason_after_run(last_result, active_preemption)
            if exit_reason is not None:
                return InstanceLoopExit(exit_reason, runs_completed, last_result)

    def _next_tick(
        self,
        abort: AbortToken,
        preemption: PreemptionRequest,
    ) -> InstanceTickResult | None:
        try:
            abort.raise_if_requested()
            return self._agent.tick(
                self._clock.now(),
                abort=abort,
                preemption=preemption,
            )
        except AbortRequested:
            return None

    def _wait_until(self, wake_at: datetime, abort: AbortToken) -> bool:
        seconds = max(0.0, (wake_at - self._clock.now()).total_seconds())
        try:
            self._clock.sleep(seconds, abort)
        except AbortRequested:
            return False
        return True
