import pytest

from module.exception import CampaignEnd
from module.maritime_escort.result import MaritimeEscortExecutionResult, MaritimeEscortExecutionStatus
from module.maritime_escort.run import MaritimeEscort


def test_execute_once_reports_completed_withdrawal(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def enter_map(_self: MaritimeEscort, _entrance: object, *, mode: str) -> None:
        assert mode == "escort"
        calls.append("enter")

    def withdraw(_self: MaritimeEscort) -> None:
        calls.append("withdraw")
        raise CampaignEnd

    monkeypatch.setattr(MaritimeEscort, "enter_map", enter_map)
    monkeypatch.setattr(MaritimeEscort, "withdraw", withdraw)

    result = object.__new__(MaritimeEscort).execute_once()

    assert result == MaritimeEscortExecutionResult(MaritimeEscortExecutionStatus.WITHDRAWAL_COMPLETED)
    assert calls == ["enter", "withdraw"]


def test_execute_once_reports_exhausted_attempts_without_withdrawal(monkeypatch: pytest.MonkeyPatch) -> None:
    def enter_map(_self: MaritimeEscort, _entrance: object, *, mode: str) -> None:
        assert mode == "escort"
        raise CampaignEnd

    def withdraw(_self: MaritimeEscort) -> None:
        pytest.fail("withdraw must not run after exhausted attempts")

    monkeypatch.setattr(MaritimeEscort, "enter_map", enter_map)
    monkeypatch.setattr(MaritimeEscort, "withdraw", withdraw)

    result = object.__new__(MaritimeEscort).execute_once()

    assert result == MaritimeEscortExecutionResult(MaritimeEscortExecutionStatus.ATTEMPTS_EXHAUSTED)
