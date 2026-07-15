import pytest

from module.device.device import Device


def _device(*, enabled: bool) -> Device:
    device = object.__new__(Device)
    device.stuck_detection_enabled = enabled
    return device


def test_stuck_detection_scope_restores_state_after_nested_use() -> None:
    device = _device(enabled=True)

    with device.suspend_stuck_detection():
        assert not device.stuck_detection_enabled
        with device.suspend_stuck_detection():
            assert not device.stuck_detection_enabled
        assert not device.stuck_detection_enabled

    assert device.stuck_detection_enabled


def test_stuck_detection_scope_preserves_an_existing_disabled_state() -> None:
    device = _device(enabled=False)

    with device.suspend_stuck_detection():
        assert not device.stuck_detection_enabled

    assert not device.stuck_detection_enabled


def test_stuck_detection_scope_restores_state_after_failure() -> None:
    device = _device(enabled=True)
    message = "failed"

    with pytest.raises(RuntimeError, match=message), device.suspend_stuck_detection():
        raise RuntimeError(message)

    assert device.stuck_detection_enabled
