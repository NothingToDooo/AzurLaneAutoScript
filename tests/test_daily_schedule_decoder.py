from datetime import time
from types import MappingProxyType
from typing import cast

import pytest

from module.runtime import DailySchedule, FrozenTaskSettings, SettingsDecoder, SettingsDocumentError


def _decoder(schedule: object) -> SettingsDecoder:
    values = cast("FrozenTaskSettings", MappingProxyType({"schedule": schedule}))
    return SettingsDecoder(values, path="$.task")


def _schedule(**overrides: object) -> MappingProxyType[str, object]:
    values: dict[str, object] = {
        "timezone": "Asia/Hong_Kong",
        "triggers": ("04:00", "12:30"),
    }
    values.update(overrides)
    return MappingProxyType(values)


def test_decoder_decodes_a_daily_schedule_and_consumes_the_whole_object() -> None:
    decoder = _decoder(_schedule())

    schedule = decoder.daily_schedule("schedule")
    decoder.finish()

    assert schedule == DailySchedule("Asia/Hong_Kong", (time(4), time(12, 30)))


@pytest.mark.parametrize(
    ("schedule", "match"),
    [
        (_schedule(timezone="Removed/Timezone"), "IANA timezone"),
        (_schedule(triggers=()), "must not be empty"),
        (_schedule(triggers=("4:00",)), "must be HH:MM"),
        (_schedule(triggers=("24:00",)), "must be HH:MM"),
        (_schedule(triggers=("04:60",)), "must be HH:MM"),
        (_schedule(triggers=("04:00:00",)), "must be HH:MM"),
        (_schedule(triggers=("12:00", "04:00")), "unique and sorted"),
        (_schedule(triggers=("04:00", "04:00")), "unique and sorted"),
        (MappingProxyType({"triggers": ("04:00",)}), "missing required setting"),
        (MappingProxyType({"timezone": "UTC"}), "missing required setting"),
        (_schedule(unknown=True), "unknown settings"),
    ],
)
def test_decoder_rejects_invalid_daily_schedule(schedule: object, match: str) -> None:
    with pytest.raises(SettingsDocumentError, match=match):
        _decoder(schedule).daily_schedule("schedule")
