import pytest

from module.application import AbortRequested, AbortToken, SafeUnitCancellation


def test_safe_unit_is_cancellable_before_commit() -> None:
    source = AbortToken()
    gate = SafeUnitCancellation(source)
    source.request("stop before unit")

    with pytest.raises(AbortRequested, match="stop before unit"):
        gate.raise_if_requested()

    with pytest.raises(AbortRequested, match="stop before unit"):
        gate.commit()

    assert not gate.committed


def test_safe_unit_defers_requests_after_commit() -> None:
    source = AbortToken()
    gate = SafeUnitCancellation(source)

    assert gate.commit()
    assert not gate.commit()
    source.request("defer until checkpoint")

    gate.raise_if_requested()
    assert gate.committed
