import pytest

from module.adapters.campaign_runtime_profile import (
    CampaignRuntimeProfileError,
    RuntimeSessionOutcome,
)
from module.adapters.campaign_runtime_session import (
    RuntimeProfileLease,
    RuntimeProfileLeaseState,
)


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
