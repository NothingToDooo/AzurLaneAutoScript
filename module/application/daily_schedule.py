import datetime as datetime_module
from dataclasses import dataclass
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


@dataclass(frozen=True, slots=True)
class DailySchedule:
    """按指定时区的本地钟表时间生成可重放的每日触发时刻。"""

    timezone_name: str
    triggers: tuple[datetime_module.time, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.timezone_name, str):
            message = "timezone_name must be a string"
            raise TypeError(message)
        if not self.timezone_name or self.timezone_name != self.timezone_name.strip():
            message = "timezone_name must be trimmed and non-empty"
            raise ValueError(message)
        try:
            ZoneInfo(self.timezone_name)
        except (ValueError, ZoneInfoNotFoundError) as error:
            message = f"timezone_name must identify an IANA timezone: {self.timezone_name!r}"
            raise ValueError(message) from error

        if not isinstance(self.triggers, tuple):
            message = "triggers must be a tuple"
            raise TypeError(message)
        if not self.triggers:
            message = "triggers must not be empty"
            raise ValueError(message)
        for trigger in self.triggers:
            if not isinstance(trigger, datetime_module.time):
                message = "triggers must contain datetime.time values"
                raise TypeError(message)
            if trigger.utcoffset() is not None:
                message = "triggers must contain naive datetime.time values"
                raise ValueError(message)
        if any(self.triggers[index] >= self.triggers[index + 1] for index in range(len(self.triggers) - 1)):
            message = "triggers must be unique and sorted"
            raise ValueError(message)

    def next_after(self, value: datetime_module.datetime) -> datetime_module.datetime:
        """返回严格晚于 ``value`` 的下一个触发时刻，并统一为 UTC。"""
        if not isinstance(value, datetime_module.datetime):
            message = "value must be a datetime"
            raise TypeError(message)
        if value.utcoffset() is None:
            message = "value must be timezone-aware"
            raise ValueError(message)

        threshold = value.astimezone(datetime_module.UTC)
        timezone = ZoneInfo(self.timezone_name)
        local_date = threshold.astimezone(timezone).date()

        while True:
            candidates = {
                candidate for trigger in self.triggers for candidate in _utc_candidates(local_date, trigger, timezone)
            }
            for candidate in sorted(candidates):
                if candidate > threshold:
                    return candidate
            local_date += datetime_module.timedelta(days=1)


def _utc_candidates(
    local_date: datetime_module.date,
    trigger: datetime_module.time,
    timezone: ZoneInfo,
) -> tuple[datetime_module.datetime, ...]:
    """将一个 wall-clock trigger 映射到当天所有真实存在的 UTC instant。"""
    wall_time = datetime_module.datetime.combine(local_date, trigger).replace(tzinfo=None)
    candidates: set[datetime_module.datetime] = set()
    for fold in (0, 1):
        local = wall_time.replace(tzinfo=timezone, fold=fold)
        candidate = local.astimezone(datetime_module.UTC)
        round_trip = candidate.astimezone(timezone)
        if round_trip.replace(tzinfo=None) == wall_time and round_trip.fold == fold:
            candidates.add(candidate)
    return tuple(sorted(candidates))
