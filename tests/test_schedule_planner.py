from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta
from typing import get_type_hints

import pytest

from module.config.config import AzurLaneConfig
from module.config.schedule import ScheduleEntry, SchedulePlanner

NOW = datetime(2026, 7, 10, 12, 0)


def _entry(command: str, next_run: object, *, enable: bool = True) -> ScheduleEntry:
    return ScheduleEntry(enable=enable, command=command, next_run=next_run)


def _schedule_config(next_run: object, *, hoarding_minutes: int = 5) -> AzurLaneConfig:
    config = object.__new__(AzurLaneConfig)
    config.data = {
        "Alas": {"Optimization": {"TaskHoardingDuration": hoarding_minutes}},
        "Main": {
            "Scheduler": {
                "Enable": True,
                "Command": "Main",
                "NextRun": next_run,
            }
        },
    }
    config.pending_task = []
    config.waiting_task = []
    config.is_hoarding_task = False
    return config


def test_planner_treats_exact_now_as_waiting() -> None:
    decision = SchedulePlanner.select(
        [_entry("Main", NOW)],
        now=NOW,
        priority={"Main": 0},
    )

    assert decision.state == "waiting"
    assert decision.entry == _entry("Main", NOW)
    assert decision.wake_at == NOW
    assert decision.pending == ()
    assert decision.waiting == (_entry("Main", NOW),)


def test_planner_public_annotations_can_be_resolved() -> None:
    hints = get_type_hints(SchedulePlanner.select)

    assert {"entries", "now", "priority", "return"} == hints.keys()


def test_planner_orders_pending_only_by_stable_priority() -> None:
    entries = [
        _entry("SameFirst", NOW - timedelta(minutes=1)),
        _entry("High", NOW - timedelta(minutes=3)),
        _entry("SameSecond", NOW - timedelta(minutes=2)),
    ]

    decision = SchedulePlanner.select(
        entries,
        now=NOW,
        priority={"High": 0, "SameFirst": 1, "SameSecond": 1},
    )

    assert [entry.command for entry in decision.pending] == ["High", "SameFirst", "SameSecond"]
    assert decision.state == "ready"
    assert decision.entry is entries[1]
    assert decision.wake_at is None


def test_planner_orders_waiting_by_time_then_priority_for_ties() -> None:
    entries = [
        _entry("Later", NOW + timedelta(minutes=2)),
        _entry("TieLow", NOW + timedelta(minutes=1)),
        _entry("TieHigh", NOW + timedelta(minutes=1)),
    ]

    decision = SchedulePlanner.select(
        entries,
        now=NOW,
        priority={"TieHigh": 0, "Later": 1, "TieLow": 2},
    )

    assert [entry.command for entry in decision.waiting] == ["TieHigh", "TieLow", "Later"]
    assert decision.entry is entries[2]


def test_planner_skips_disabled_and_unlisted_commands() -> None:
    decision = SchedulePlanner.select(
        [
            _entry("Disabled", NOW - timedelta(minutes=1), enable=False),
            _entry("Unknown", NOW - timedelta(minutes=1)),
            _entry("Main", NOW + timedelta(minutes=1)),
        ],
        now=NOW,
        priority={"Main": 0},
    )

    assert decision.entry == _entry("Main", NOW + timedelta(minutes=1))
    assert decision.pending == ()
    assert len(decision.waiting) == 1


def test_planner_exposes_invalid_next_run_as_error_decision() -> None:
    invalid = _entry("Main", "not-a-datetime")

    decision = SchedulePlanner.select([invalid], now=NOW, priority={"Main": 0})

    assert decision.state == "error"
    assert decision.entry is invalid
    assert decision.errors == (invalid,)
    assert decision.wake_at is None


def test_planner_rejects_aware_clock_and_entry_time() -> None:
    aware = NOW.replace(tzinfo=UTC)

    with pytest.raises(ValueError, match="naive local datetime"):
        SchedulePlanner.select([], now=aware, priority={})
    with pytest.raises(ValueError, match="naive local datetime"):
        SchedulePlanner.select([_entry("Main", aware)], now=NOW, priority={"Main": 0})


def test_planner_is_immutable_and_does_not_change_entries() -> None:
    entry = _entry("Main", NOW + timedelta(minutes=1))
    decision = SchedulePlanner.select([entry], now=NOW, priority={"Main": 0})

    entry_attribute = "command"
    with pytest.raises(FrozenInstanceError):
        setattr(entry, entry_attribute, "Other")
    decision_attribute = "state"
    with pytest.raises(FrozenInstanceError):
        setattr(decision, decision_attribute, "ready")
    assert entry.next_run == NOW + timedelta(minutes=1)


def test_planner_returns_empty_decision_when_nothing_is_schedulable() -> None:
    decision = SchedulePlanner.select(
        [_entry("Unknown", NOW), _entry("Main", NOW, enable=False)],
        now=NOW,
        priority={"Main": 0},
    )

    assert decision.state == "empty"
    assert decision.entry is None
    assert decision.wake_at is None


def test_config_facade_uses_fake_clock_and_adds_hoarding_only_to_wake_time() -> None:
    config = _schedule_config(NOW)

    decision = config.get_next_decision(now=NOW)

    assert decision.state == "waiting"
    assert decision.wake_at == NOW + timedelta(minutes=5)
    assert config.waiting_task[0].next_run == NOW
    assert config.data["Main"]["Scheduler"]["NextRun"] == NOW
    assert config.is_hoarding_task is True


def test_config_facade_closes_hoarding_when_task_is_pending() -> None:
    config = _schedule_config(NOW - timedelta(minutes=6))
    config.is_hoarding_task = True

    decision = config.get_next_decision(now=NOW)

    assert decision.state == "ready"
    assert decision.command == "Main"
    assert decision.wake_at is None
    assert config.is_hoarding_task is False


def test_config_hoarding_state_is_isolated_between_instances() -> None:
    first = _schedule_config(NOW)
    second = _schedule_config(NOW)

    first.get_next_decision(now=NOW)

    assert first.is_hoarding_task is True
    assert second.is_hoarding_task is False
    first.mark_task_started()
    assert first.is_hoarding_task is False


def test_config_copies_legacy_class_default_into_instance(monkeypatch) -> None:
    monkeypatch.setattr(AzurLaneConfig, "is_hoarding_task", False)
    monkeypatch.setattr(AzurLaneConfig, "init_task", lambda _self, _task=None: None)

    config = AzurLaneConfig("alas")

    assert config.__dict__["is_hoarding_task"] is False
