import pytest

from module.adapters.campaign_mumu12 import DeclarativeCampaignMapRuntime
from module.adapters.campaign_runtime_hard import CampaignClearModeExecutor
from module.adapters.campaign_runtime_profile import (
    CampaignRuntimeProfileError,
    RuntimeSessionOutcome,
)
from module.adapters.campaign_runtime_session import (
    RuntimeProfileLease,
    RuntimeProfileLeaseState,
)
from module.adapters.campaign_submarine import (
    CampaignSubmarineFreshCombatService,
    CampaignSubmarineServices,
)
from module.application import AbortRequested, AbortToken, CancellationSource
from module.base.button import Button
from module.content.campaign_session import CampaignRunVariant


class _SessionManager:
    def __init__(
        self,
        *,
        begin_error: BaseException | None = None,
        end_error: BaseException | None = None,
        reset_error: BaseException | None = None,
    ) -> None:
        self.begin_error = begin_error
        self.end_error = end_error
        self.reset_error = reset_error
        self.calls: list[object] = []
        self.lease: RuntimeProfileLease | None = None
        self.cleanup_states: list[RuntimeProfileLeaseState] = []

    def begin_session(self) -> None:
        self.calls.append("begin")
        if self.begin_error is not None:
            raise self.begin_error

    def end_session(self, outcome: RuntimeSessionOutcome) -> None:
        self.calls.append(("end", outcome))
        if self.lease is not None:
            self.cleanup_states.append(self.lease.state)
        if self.end_error is not None:
            raise self.end_error

    def reset(self) -> None:
        self.calls.append("reset")
        if self.lease is not None:
            self.cleanup_states.append(self.lease.state)
        if self.reset_error is not None:
            raise self.reset_error


def _hard_runtime(manager: _SessionManager) -> DeclarativeCampaignMapRuntime:
    runtime = object.__new__(DeclarativeCampaignMapRuntime)
    lease = RuntimeProfileLease(manager)
    manager.lease = lease
    vars(runtime)["_hard_behavior"] = object.__new__(CampaignClearModeExecutor)
    vars(runtime)["_runtime_profile_lease"] = lease
    return runtime


def _entrance() -> Button:
    return Button(area=(), color=(), button=(1, 2, 3, 4), name="HARD_ENTRANCE")


def test_lease_runs_one_session_and_closes_in_order() -> None:
    manager = _SessionManager()
    lease = RuntimeProfileLease(manager)

    assert lease.state is RuntimeProfileLeaseState.READY
    assert lease.active is False

    lease.start()

    assert lease.state is RuntimeProfileLeaseState.ACTIVE
    assert lease.active is True

    lease.close(RuntimeSessionOutcome.COMPLETED)

    assert lease.state is RuntimeProfileLeaseState.CLOSED
    assert lease.active is False
    assert manager.calls == [
        "begin",
        ("end", RuntimeSessionOutcome.COMPLETED),
        "reset",
    ]
    lease.discard()
    assert manager.calls == [
        "begin",
        ("end", RuntimeSessionOutcome.COMPLETED),
        "reset",
    ]


def test_lease_rejects_invalid_transitions_without_changing_ownership() -> None:
    manager = _SessionManager()
    lease = RuntimeProfileLease(manager)

    with pytest.raises(CampaignRuntimeProfileError, match="cannot close from ready"):
        lease.close(RuntimeSessionOutcome.FAILED)
    assert lease.state is RuntimeProfileLeaseState.READY

    lease.start()
    with pytest.raises(CampaignRuntimeProfileError, match="cannot start from active"):
        lease.start()
    with pytest.raises(CampaignRuntimeProfileError, match="must close before discard"):
        lease.discard()
    assert lease.state is RuntimeProfileLeaseState.ACTIVE

    lease.close(RuntimeSessionOutcome.INTERRUPTED)
    with pytest.raises(CampaignRuntimeProfileError, match="cannot start from closed"):
        lease.start()


def test_lease_begin_failure_closes_before_reset_and_cannot_be_reused() -> None:
    begin_error = RuntimeError("begin failed")
    manager = _SessionManager(begin_error=begin_error)
    lease = RuntimeProfileLease(manager)
    manager.lease = lease

    with pytest.raises(RuntimeError) as raised:
        lease.start()

    assert raised.value is begin_error
    assert lease.state is RuntimeProfileLeaseState.CLOSED
    assert manager.cleanup_states == [RuntimeProfileLeaseState.CLOSED]
    assert manager.calls == ["begin", "reset"]
    lease.discard()
    assert manager.calls == ["begin", "reset"]


def test_lease_preserves_begin_and_reset_failures_in_order() -> None:
    begin_error = RuntimeError("begin failed")
    reset_error = OSError("reset failed")
    manager = _SessionManager(begin_error=begin_error, reset_error=reset_error)
    lease = RuntimeProfileLease(manager)

    with pytest.raises(BaseExceptionGroup) as raised:
        lease.start()

    assert raised.value.exceptions == (begin_error, reset_error)
    assert lease.state is RuntimeProfileLeaseState.CLOSED
    assert manager.calls == ["begin", "reset"]


def test_lease_close_runs_reset_after_end_failure_and_stays_closed() -> None:
    end_error = RuntimeError("end failed")
    manager = _SessionManager(end_error=end_error)
    lease = RuntimeProfileLease(manager)
    lease.start()

    with pytest.raises(RuntimeError) as raised:
        lease.close(RuntimeSessionOutcome.FAILED)

    assert raised.value is end_error
    assert lease.state is RuntimeProfileLeaseState.CLOSED
    assert manager.calls[-2:] == [("end", RuntimeSessionOutcome.FAILED), "reset"]


def test_lease_preserves_end_and_reset_failures_in_order() -> None:
    end_error = RuntimeError("end failed")
    reset_error = OSError("reset failed")
    manager = _SessionManager(end_error=end_error, reset_error=reset_error)
    lease = RuntimeProfileLease(manager)
    manager.lease = lease
    lease.start()

    with pytest.raises(BaseExceptionGroup) as raised:
        lease.close(RuntimeSessionOutcome.FAILED)

    assert raised.value.exceptions == (end_error, reset_error)
    assert lease.state is RuntimeProfileLeaseState.CLOSED
    assert manager.cleanup_states == [
        RuntimeProfileLeaseState.CLOSED,
        RuntimeProfileLeaseState.CLOSED,
    ]
    assert manager.calls[-2:] == [("end", RuntimeSessionOutcome.FAILED), "reset"]


def test_lease_discard_is_one_shot_even_when_reset_fails() -> None:
    reset_error = OSError("reset failed")
    manager = _SessionManager(reset_error=reset_error)
    lease = RuntimeProfileLease(manager)

    with pytest.raises(OSError, match="reset failed") as raised:
        lease.discard()

    assert raised.value is reset_error
    assert lease.state is RuntimeProfileLeaseState.CLOSED
    lease.discard()
    assert manager.calls == ["reset"]


def test_lease_validates_contract_values_before_mutating_state() -> None:
    with pytest.raises(TypeError, match="session lifecycle contract"):
        RuntimeProfileLease(object())  # ty: ignore[invalid-argument-type] - 验证运行时边界。

    lease = RuntimeProfileLease(_SessionManager())
    lease.start()
    with pytest.raises(TypeError, match="RuntimeSessionOutcome"):
        lease.close("failed")  # ty: ignore[invalid-argument-type] - 验证运行时边界。
    assert lease.state is RuntimeProfileLeaseState.ACTIVE


def test_hard_attempt_uses_a_direct_loop_session_and_completes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _SessionManager()
    runtime = _hard_runtime(manager)
    body_calls: list[tuple[Button, CancellationSource]] = []
    fresh_combat_calls: list[object] = []
    vars(runtime)["_submarine_services"] = CampaignSubmarineServices(
        fresh_combat=CampaignSubmarineFreshCombatService(fresh_combat_calls.append),
    )

    def complete_body(
        _runtime: DeclarativeCampaignMapRuntime,
        entrance: Button,
        cancellation: CancellationSource,
    ) -> None:
        body_calls.append((entrance, cancellation))

    monkeypatch.setattr(DeclarativeCampaignMapRuntime, "_execute_hard_attempt_body", complete_body)
    entrance = _entrance()
    cancellation = AbortToken()

    runtime.execute_hard_attempt(entrance, cancellation)

    assert body_calls == [(entrance, cancellation)]
    assert fresh_combat_calls == []
    assert manager.calls == [
        "begin",
        ("end", RuntimeSessionOutcome.COMPLETED),
        "reset",
    ]
    assert runtime.session_variant is CampaignRunVariant.LOOP
    assert runtime.map_is_clear_mode is True
    assert manager.lease is not None
    assert manager.lease.active is False


def test_hard_attempt_maps_abort_to_interrupted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    abort = AbortRequested("hard attempt cancelled")
    manager = _SessionManager()
    runtime = _hard_runtime(manager)

    def abort_body(
        _runtime: DeclarativeCampaignMapRuntime,
        entrance: Button,
        cancellation: CancellationSource,
    ) -> None:
        del entrance, cancellation
        raise abort

    monkeypatch.setattr(DeclarativeCampaignMapRuntime, "_execute_hard_attempt_body", abort_body)

    with pytest.raises(AbortRequested) as raised:
        runtime.execute_hard_attempt(_entrance(), AbortToken())

    assert raised.value is abort
    assert manager.calls[-2:] == [("end", RuntimeSessionOutcome.INTERRUPTED), "reset"]
    assert manager.lease is not None
    assert manager.lease.active is False


def test_hard_attempt_maps_other_errors_to_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failure = RuntimeError("hard attempt failed")
    manager = _SessionManager()
    runtime = _hard_runtime(manager)

    def fail_body(
        _runtime: DeclarativeCampaignMapRuntime,
        entrance: Button,
        cancellation: CancellationSource,
    ) -> None:
        del entrance, cancellation
        raise failure

    monkeypatch.setattr(DeclarativeCampaignMapRuntime, "_execute_hard_attempt_body", fail_body)

    with pytest.raises(RuntimeError) as raised:
        runtime.execute_hard_attempt(_entrance(), AbortToken())

    assert raised.value is failure
    assert manager.calls[-2:] == [("end", RuntimeSessionOutcome.FAILED), "reset"]
    assert manager.lease is not None
    assert manager.lease.active is False


def test_hard_attempt_preserves_body_and_cleanup_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body_error = RuntimeError("hard attempt failed")
    cleanup_error = OSError("hard cleanup failed")
    manager = _SessionManager(end_error=cleanup_error)
    runtime = _hard_runtime(manager)

    def fail_body(
        _runtime: DeclarativeCampaignMapRuntime,
        entrance: Button,
        cancellation: CancellationSource,
    ) -> None:
        del entrance, cancellation
        raise body_error

    monkeypatch.setattr(DeclarativeCampaignMapRuntime, "_execute_hard_attempt_body", fail_body)

    with pytest.raises(BaseExceptionGroup) as raised:
        runtime.execute_hard_attempt(_entrance(), AbortToken())

    assert raised.value.exceptions == (body_error, cleanup_error)
    assert manager.calls[-2:] == [("end", RuntimeSessionOutcome.FAILED), "reset"]
    assert manager.lease is not None
    assert manager.lease.active is False
