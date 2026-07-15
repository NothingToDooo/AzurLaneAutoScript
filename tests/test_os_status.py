from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from module.os_handler.os_status import OpsiCooldown, nearest_opsi_cooldown

if TYPE_CHECKING:
    from module.config.deep import MutableDeepData, MutableDeepValue

_NOW = datetime(2026, 7, 15, 12, 0)
_SERVER_UPDATE = datetime(2026, 7, 16, 0, 0)


def _task(*, enabled: bool, next_run: datetime) -> dict[str, MutableDeepValue]:
    return {"Scheduler": {"Enable": enabled, "NextRun": next_run}}


def test_nearest_opsi_cooldown_reads_current_config_sections() -> None:
    data: MutableDeepData = {
        "OpsiObscure": _task(enabled=True, next_run=_NOW + timedelta(minutes=40)),
        "OpsiAbyssal": _task(enabled=True, next_run=_NOW + timedelta(minutes=15)),
        "OpsiStronghold": _task(enabled=False, next_run=_NOW + timedelta(minutes=5)),
    }

    result = nearest_opsi_cooldown(data, now=_NOW, server_update=_SERVER_UPDATE)

    assert result == OpsiCooldown(command="OpsiAbyssal", ready_at=_NOW + timedelta(minutes=15))


def test_nearest_opsi_cooldown_ignores_non_cooldown_times() -> None:
    data: MutableDeepData = {
        "OpsiObscure": _task(enabled=True, next_run=_NOW - timedelta(seconds=1)),
        "OpsiAbyssal": _task(enabled=True, next_run=_NOW + timedelta(minutes=61)),
        "OpsiStronghold": _task(enabled=True, next_run=_SERVER_UPDATE),
        "OpsiDaily": {"Scheduler": {"Enable": True, "NextRun": "invalid"}},
    }

    result = nearest_opsi_cooldown(data, now=_NOW, server_update=_SERVER_UPDATE)

    assert result is None
