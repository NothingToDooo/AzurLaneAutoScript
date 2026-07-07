from datetime import datetime, timedelta, timezone

BEIJING_TIMEZONE = timezone(timedelta(hours=8), name="UTC+08:00")


def _drop_timezone(value: datetime) -> datetime:
    return value.replace(tzinfo=None)


def beijing_now() -> datetime:
    """
    返回不带 tzinfo 的北京时间。

    项目配置和调度历史上都使用 naive datetime；这里用显式 UTC+8 获取时间，
    再去掉 tzinfo，避免和已有配置值比较时混用 aware/naive datetime。
    """
    return _drop_timezone(datetime.now(tz=BEIJING_TIMEZONE))


def beijing_datetime(
    year: int,
    month: int,
    day: int,
    hour: int = 0,
    minute: int = 0,
    second: int = 0,
    microsecond: int = 0,
) -> datetime:
    return _drop_timezone(
        datetime(
            year,
            month,
            day,
            hour,
            minute,
            second,
            microsecond,
            tzinfo=BEIJING_TIMEZONE,
        )
    )
