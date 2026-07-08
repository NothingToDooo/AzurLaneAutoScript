from datetime import datetime, timedelta

from module.config.utils import parse_value, server_time_offset


def test_cn_personal_branch_uses_local_time_as_server_time() -> None:
    assert server_time_offset() == timedelta()


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
