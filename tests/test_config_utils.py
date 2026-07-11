from __future__ import annotations

from datetime import datetime, timedelta, tzinfo
from typing import TYPE_CHECKING

import pytest

import module.config.utils as config_utils
from module.config.utils import (
    alas_template,
    get_server_last_update,
    get_server_next_update,
    parse_value,
    server_time_offset,
)

if TYPE_CHECKING:
    from collections.abc import Callable


class _FixedDatetime(datetime):
    @classmethod
    def now(cls, tz: tzinfo | None = None) -> _FixedDatetime:
        return cls(2026, 7, 10, 11, 30, tzinfo=tz)


def test_cn_personal_branch_uses_local_time_as_server_time() -> None:
    assert server_time_offset() == timedelta()


def test_alas_template_uses_plain_template_name() -> None:
    assert alas_template() == ["template"]


def test_parse_value_uses_default_when_option_is_invalid() -> None:
    data = {"option": ["safe"], "value": "safe"}

    assert parse_value("legacy", data) == "safe"


def test_parse_value_keeps_non_string_values() -> None:
    assert parse_value(["a"], {}) == ["a"]


def test_parse_value_converts_config_strings() -> None:
    values = {
        "": None,
        "true": True,
        "True": True,
        "false": False,
        "False": False,
        "12": 12,
        "12.5": 12.5,
        "2026-07-08T09:10:11": datetime(2026, 7, 8, 9, 10, 11),
        "1e3": "1e3",
        "plain": "plain",
    }

    for raw, expected in values.items():
        assert parse_value(raw, {}) == expected


def test_server_update_selects_nearest_nonempty_trigger(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config_utils, "datetime", _FixedDatetime)

    assert get_server_next_update(["10:00", "12:00"]) == datetime(2026, 7, 10, 12)
    assert get_server_last_update(["10:00", "12:00"]) == datetime(2026, 7, 10, 10)


@pytest.mark.parametrize("get_update", [get_server_next_update, get_server_last_update])
def test_server_update_rejects_empty_trigger(get_update: Callable[[list[str]], datetime]) -> None:
    with pytest.raises(ValueError, match="daily_trigger"):
        get_update([])
