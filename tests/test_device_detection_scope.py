import collections

import pytest

from module.base.timer import Timer
from module.device.device import Device


def _device(*, enabled: bool) -> Device:
    device = object.__new__(Device)
    device.detect_record = set()
    device.click_record = collections.deque(maxlen=15)
    device.stuck_detection_enabled = enabled
    device.stuck_timer = Timer(60, count=60).start()
    device.stuck_timer_long = Timer(180, count=180).start()
    return device


def _fail_during_suspension(device: Device, message: str) -> None:
    with device.suspend_stuck_detection():
        device.stuck_record_add("IGNORED")
        device.click_record_add("IGNORED")
        device.stuck_timer.clear()
        raise RuntimeError(message)


def test_stuck_detection_scope_restores_state_after_nested_use() -> None:
    device = _device(enabled=True)

    with device.suspend_stuck_detection():
        assert not device.stuck_detection_enabled
        device.stuck_record_add("IGNORED")
        device.click_record_add("IGNORED")
        device.stuck_timer.reached()
        with device.suspend_stuck_detection():
            assert not device.stuck_detection_enabled
        assert device.detect_record == {"IGNORED"}
        assert list(device.click_record) == ["IGNORED"]
        assert device.stuck_timer.current_count() == 1
        assert not device.stuck_detection_enabled

    assert device.stuck_detection_enabled
    assert device.detect_record == set()
    assert list(device.click_record) == []
    assert device.stuck_timer.current_count() == 0


def test_stuck_detection_scope_preserves_an_existing_disabled_state() -> None:
    device = _device(enabled=False)
    device.stuck_record_add("EXISTING")
    device.click_record_add("EXISTING")
    device.stuck_timer.clear()

    with device.suspend_stuck_detection():
        assert not device.stuck_detection_enabled

    assert not device.stuck_detection_enabled
    assert device.detect_record == {"EXISTING"}
    assert list(device.click_record) == ["EXISTING"]
    assert not device.stuck_timer.started()


def test_stuck_detection_scope_discards_ignored_clicks_before_restoring() -> None:
    device = _device(enabled=True)

    with device.suspend_stuck_detection():
        for _ in range(12):
            device.click_record_add("IGNORED")
            assert device.click_record_check() is False

    device.handle_control_check("NORMAL")

    assert list(device.click_record) == ["NORMAL"]


def test_stuck_detection_scope_resets_expired_timers_before_restoring() -> None:
    device = _device(enabled=True)

    with device.suspend_stuck_detection():
        device.stuck_record_add("IGNORED")
        device.stuck_timer.clear()
        device.stuck_timer_long.clear()
        assert device.stuck_record_check() is False

    assert device.detect_record == set()
    assert device.stuck_timer.started()
    assert device.stuck_timer_long.started()
    assert device.stuck_record_check() is False


def test_stuck_detection_scope_restores_state_after_failure() -> None:
    device = _device(enabled=True)
    message = "failed"

    with pytest.raises(RuntimeError, match=message):
        _fail_during_suspension(device, message)

    assert device.stuck_detection_enabled
    assert device.detect_record == set()
    assert list(device.click_record) == []
    assert device.stuck_timer.started()
