from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from module.application import (
    AbortToken,
    Cancelled,
    Faulted,
    PreemptionRequest,
    RequestAppRestart,
    RescheduleSelf,
    ScheduleItem,
    Succeeded,
    TaskId,
    TaskResult,
)
from module.supervisor import (
    EmptyTickResult,
    InstanceLoop,
    InstanceLoopExit,
    InstanceLoopExitReason,
    InstanceTickResult,
    ReadyTickResult,
    WaitingTickResult,
)

if TYPE_CHECKING:
    from module.interaction import CancellationSignal

_NOW = datetime(2026, 7, 13, 8, tzinfo=UTC)
_ITEM = ScheduleItem(task_id=TaskId("research"), enabled=True, due_at=_NOW, priority=4)


class _Agent:
    def __init__(
        self,
        results: list[InstanceTickResult],
        *,
        request_preemption: bool = False,
    ) -> None:
        self.results = results
        self.request_preemption = request_preemption
        self.calls = 0

    def tick(
        self,
        now: datetime,
        *,
        abort: AbortToken | None = None,
        preemption: PreemptionRequest | None = None,
    ) -> InstanceTickResult:
        del now, abort
        self.calls += 1
        if self.request_preemption:
            if preemption is None:
                message = "test agent requires a PreemptionRequest"
                raise TypeError(message)
            preemption.request("urgent")
        return self.results.pop(0)


class _Clock:
    def __init__(self, now: datetime, *, abort_during_sleep: bool = False) -> None:
        self.current = now
        self.abort_during_sleep = abort_during_sleep
        self.sleeps: list[float] = []

    def now(self) -> datetime:
        return self.current

    def sleep(self, seconds: float, cancellation: CancellationSignal) -> None:
        self.sleeps.append(seconds)
        if self.abort_during_sleep:
            if not isinstance(cancellation, AbortToken):
                message = "test clock requires an AbortToken"
                raise TypeError(message)
            cancellation.request("stop while waiting")
            cancellation.raise_if_requested()
        self.current += timedelta(seconds=seconds)


def _ready(result: TaskResult) -> ReadyTickResult:
    return ReadyTickResult(_ITEM, result)


def test_loop_waits_runs_serially_and_exits_when_schedule_is_empty() -> None:
    wake_at = _NOW + timedelta(minutes=5)
    success = TaskResult(Succeeded(), (RescheduleSelf(_NOW + timedelta(hours=1)),))
    agent = _Agent([WaitingTickResult(_ITEM, wake_at), _ready(success), EmptyTickResult()])
    clock = _Clock(_NOW)

    result = InstanceLoop(agent, clock).run()

    assert result == InstanceLoopExit(InstanceLoopExitReason.EMPTY, 1, success)
    assert clock.sleeps == [300.0]
    assert agent.calls == 3


def test_loop_stops_after_first_fault_without_busy_retry() -> None:
    fault = TaskResult(Faulted(RuntimeError("recognition failed")))
    agent = _Agent([_ready(fault), EmptyTickResult()])

    result = InstanceLoop(agent, _Clock(_NOW)).run()

    assert result == InstanceLoopExit(InstanceLoopExitReason.FAULTED, 1, fault)
    assert agent.calls == 1


def test_loop_stops_when_task_returns_cancelled() -> None:
    cancelled = TaskResult(Cancelled("manual stop"))
    agent = _Agent([_ready(cancelled), EmptyTickResult()])

    result = InstanceLoop(agent, _Clock(_NOW)).run()

    assert result == InstanceLoopExit(InstanceLoopExitReason.CANCELLED, 1, cancelled)
    assert agent.calls == 1


def test_loop_consumes_a_preexisting_preemption_in_one_tick() -> None:
    success = TaskResult(Succeeded(), (RescheduleSelf(_NOW + timedelta(hours=1)),))
    preemption = PreemptionRequest()
    preemption.request("urgent")
    agent = _Agent([_ready(success), EmptyTickResult()])

    result = InstanceLoop(agent, _Clock(_NOW)).run(preemption=preemption)

    assert result == InstanceLoopExit(InstanceLoopExitReason.PREEMPTED, 1, success)
    assert agent.calls == 1


def test_loop_does_not_reuse_a_preemption_requested_during_a_tick() -> None:
    success = TaskResult(Succeeded(), (RescheduleSelf(_NOW + timedelta(hours=1)),))
    agent = _Agent([_ready(success), EmptyTickResult()], request_preemption=True)

    result = InstanceLoop(agent, _Clock(_NOW)).run()

    assert result == InstanceLoopExit(InstanceLoopExitReason.PREEMPTED, 1, success)
    assert agent.calls == 1


def test_loop_exits_at_restart_request_without_running_the_next_task() -> None:
    restart = TaskResult(
        Succeeded(),
        (
            RescheduleSelf(_NOW + timedelta(hours=1)),
            RequestAppRestart("apply client update"),
        ),
    )
    next_result = TaskResult(Succeeded(), (RescheduleSelf(_NOW + timedelta(hours=2)),))
    agent = _Agent([_ready(restart), _ready(next_result), EmptyTickResult()])

    result = InstanceLoop(agent, _Clock(_NOW)).run()

    assert result == InstanceLoopExit(InstanceLoopExitReason.RESTART_REQUESTED, 1, restart)
    assert agent.calls == 1


def test_abort_before_tick_exits_without_touching_agent() -> None:
    abort = AbortToken()
    abort.request("manual stop")
    agent = _Agent([EmptyTickResult()])

    result = InstanceLoop(agent, _Clock(_NOW)).run(abort=abort)

    assert result == InstanceLoopExit(InstanceLoopExitReason.CANCELLED, 0)
    assert agent.calls == 0


def test_abort_during_wait_exits_without_running_a_task() -> None:
    wake_at = _NOW + timedelta(minutes=5)
    agent = _Agent([WaitingTickResult(_ITEM, wake_at), EmptyTickResult()])

    result = InstanceLoop(agent, _Clock(_NOW, abort_during_sleep=True)).run()

    assert result == InstanceLoopExit(InstanceLoopExitReason.CANCELLED, 0)
    assert agent.calls == 1
