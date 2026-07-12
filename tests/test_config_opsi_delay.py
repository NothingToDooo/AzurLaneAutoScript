from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import module.config.config as config_module
from module.config.config import AzurLaneConfig

if TYPE_CHECKING:
    import pytest

    from module.config.deep import MutableDeepData


def _config(data: MutableDeepData) -> tuple[AzurLaneConfig, list[str]]:
    calls: list[str] = []
    config = object.__new__(AzurLaneConfig)
    config.data = data
    config.modified = {}
    config.update = lambda: calls.append("update")
    return config, calls


def test_opsi_task_delay_without_reason_does_nothing() -> None:
    config, calls = _config({})

    config.opsi_task_delay()

    assert config.modified == {}
    assert calls == []


def test_opsi_task_delay_recon_scan_skips_force_run_and_special_radar() -> None:
    config, calls = _config(
        {
            "OpsiExplore": {"OpsiExplore": {"ForceRun": True}},
            "OpsiObscure": {},
            "OpsiStronghold": {"OpsiExplore": {"SpecialRadar": True}},
        }
    )

    config.opsi_task_delay(recon_scan=True)

    assert list(config.modified) == ["OpsiObscure.Scheduler.NextRun"]
    assert calls == ["update"]


def test_opsi_task_delay_submarine_call_skips_force_run_tasks() -> None:
    config, calls = _config(
        {
            "OpsiExplore": {"OpsiFleet": {"Submarine": True}},
            "OpsiDaily": {"OpsiFleetFilter": {"Filter": "submarine"}},
            "OpsiObscure": {
                "OpsiFleet": {"Submarine": True},
                "OpsiObscure": {"ForceRun": True},
            },
        }
    )

    config.opsi_task_delay(submarine_call=True)

    assert set(config.modified) == {
        "OpsiExplore.Scheduler.NextRun",
        "OpsiDaily.Scheduler.NextRun",
    }
    assert calls == ["update"]


def test_opsi_task_delay_ap_limit_uses_short_delay_near_reset(monkeypatch: pytest.MonkeyPatch) -> None:
    config, calls = _config({})
    monkeypatch.setattr(config_module, "get_os_reset_remain", lambda: 0)

    config.opsi_task_delay(ap_limit=True)

    next_run = config.modified["OpsiExplore.Scheduler.NextRun"]
    assert isinstance(next_run, datetime)
    assert timedelta(minutes=149) < next_run - datetime.now() < timedelta(minutes=151)
    assert calls == ["update"]
