from datetime import timedelta

from module.base.time import BEIJING_TIMEZONE, beijing_datetime, beijing_now
from module.config.utils import DEFAULT_TIME, get_server_next_update, server_time_offset


def test_beijing_timezone_is_fixed_utc_plus_8() -> None:
    assert BEIJING_TIMEZONE.utcoffset(None) == timedelta(hours=8)


def test_beijing_helpers_keep_existing_naive_datetime_contract() -> None:
    assert beijing_now().tzinfo is None
    assert beijing_datetime(2020, 1, 1).tzinfo is None
    assert beijing_datetime(2020, 1, 1) == DEFAULT_TIME
    assert get_server_next_update("00:00").tzinfo is None


def test_cn_server_time_has_no_internal_offset() -> None:
    assert server_time_offset() == timedelta()
