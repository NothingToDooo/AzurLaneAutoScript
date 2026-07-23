import datetime as datetime_module
import re
from collections.abc import Mapping
from enum import StrEnum
from typing import TYPE_CHECKING, cast

from module.application.daily_schedule import DailySchedule
from module.application.delay import DelayRange
from module.runtime.errors import SettingsDocumentError

if TYPE_CHECKING:
    from module.runtime.settings import FrozenJsonValue, FrozenTaskSettings


class SettingsDecoder:
    """显式消费一个 task settings object，并在 finish 时拒绝遗漏或未知字段。"""

    __slots__ = ("_consumed", "_path", "_values")

    def __init__(self, values: FrozenTaskSettings, *, path: str) -> None:
        if not isinstance(values, Mapping):
            message = f"{path} must be an object"
            raise TypeError(message)
        if not isinstance(path, str) or not path or path != path.strip():
            message = "path must be trimmed and non-empty"
            raise ValueError(message)
        self._values = values
        self._path = path
        self._consumed: set[str] = set()

    def _take(self, name: str) -> FrozenJsonValue:
        if not isinstance(name, str) or not name or name != name.strip():
            message = "field name must be trimmed and non-empty"
            raise ValueError(message)
        if name in self._consumed:
            message = f"{self._path}.{name} was decoded more than once"
            raise RuntimeError(message)
        try:
            value = self._values[name]
        except KeyError:
            message = f"missing required setting: {self._path}.{name}"
            raise SettingsDocumentError(message) from None
        self._consumed.add(name)
        return value

    def boolean(self, name: str) -> bool:
        value = self._take(name)
        if type(value) is not bool:
            message = f"{self._path}.{name} must be a boolean"
            raise SettingsDocumentError(message)
        return value

    def integer(self, name: str, *, minimum: int | None = None, maximum: int | None = None) -> int:
        value = self._take(name)
        return self._integer_value(value, name=name, minimum=minimum, maximum=maximum)

    def _integer_value(
        self,
        value: FrozenJsonValue,
        *,
        name: str,
        minimum: int | None,
        maximum: int | None,
    ) -> int:
        if type(value) is not int:
            message = f"{self._path}.{name} must be an integer"
            raise SettingsDocumentError(message)
        if minimum is not None and value < minimum:
            message = f"{self._path}.{name} must be at least {minimum}"
            raise SettingsDocumentError(message)
        if maximum is not None and value > maximum:
            message = f"{self._path}.{name} must be at most {maximum}"
            raise SettingsDocumentError(message)
        return value

    def nullable_integer(
        self,
        name: str,
        *,
        minimum: int | None = None,
        maximum: int | None = None,
    ) -> int | None:
        value = self._take(name)
        if value is None:
            return None
        return self._integer_value(value, name=name, minimum=minimum, maximum=maximum)

    def string(self, name: str) -> str:
        value = self._take(name)
        return self._string_value(value, name=name)

    def _string_value(self, value: FrozenJsonValue, *, name: str) -> str:
        if not isinstance(value, str) or not value or value != value.strip():
            message = f"{self._path}.{name} must be a trimmed non-empty string"
            raise SettingsDocumentError(message)
        return value

    def nullable_string(self, name: str) -> str | None:
        value = self._take(name)
        if value is None:
            return None
        return self._string_value(value, name=name)

    def string_tuple(self, name: str, *, allow_empty: bool = True) -> tuple[str, ...]:
        value = self._take(name)
        if not isinstance(value, tuple) or any(
            not isinstance(item, str) or not item or item != item.strip() for item in value
        ):
            message = f"{self._path}.{name} must be an array of trimmed non-empty strings"
            raise SettingsDocumentError(message)
        if not allow_empty and not value:
            message = f"{self._path}.{name} must not be empty"
            raise SettingsDocumentError(message)
        return cast("tuple[str, ...]", value)

    def datetime(self, name: str) -> datetime_module.datetime:
        raw = self.string(name)
        try:
            value = datetime_module.datetime.fromisoformat(raw)
        except ValueError as error:
            message = f"{self._path}.{name} must be an ISO datetime"
            raise SettingsDocumentError(message) from error
        if value.utcoffset() is None:
            message = f"{self._path}.{name} must be timezone-aware"
            raise SettingsDocumentError(message)
        return value.astimezone(datetime_module.UTC)

    def daily_schedule(self, name: str) -> DailySchedule:
        schedule = self.object(name)
        schedule_path = f"{self._path}.{name}"
        timezone_name = schedule.string("timezone")
        raw_triggers = schedule.string_tuple("triggers", allow_empty=False)
        schedule.finish()

        triggers: list[datetime_module.time] = []
        for index, raw_trigger in enumerate(raw_triggers):
            if re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", raw_trigger) is None:
                message = f"{schedule_path}.triggers[{index}] must be HH:MM"
                raise SettingsDocumentError(message)
            triggers.append(datetime_module.time(hour=int(raw_trigger[:2]), minute=int(raw_trigger[3:])))

        try:
            return DailySchedule(timezone_name, tuple(triggers))
        except (TypeError, ValueError) as error:
            message = f"{schedule_path} is not a valid daily schedule: {error}"
            raise SettingsDocumentError(message) from error

    def delay_range(self, name: str) -> DelayRange:
        delay = self.object(name)
        lower_seconds = delay.integer("lower_seconds", minimum=1)
        upper_seconds = delay.integer("upper_seconds", minimum=1)
        delay.finish()
        try:
            return DelayRange(lower_seconds=lower_seconds, upper_seconds=upper_seconds)
        except ValueError as error:
            message = f"{self._path}.{name} is not a valid delay range: {error}"
            raise SettingsDocumentError(message) from error

    def enum[E: StrEnum](self, name: str, enum_type: type[E]) -> E:
        raw = self.string(name)
        try:
            return enum_type(raw)
        except ValueError as error:
            allowed = sorted(item.value for item in enum_type)
            message = f"{self._path}.{name} must be one of {allowed}"
            raise SettingsDocumentError(message) from error

    def object(self, name: str) -> SettingsDecoder:
        value = self._take(name)
        if not isinstance(value, Mapping):
            message = f"{self._path}.{name} must be an object"
            raise SettingsDocumentError(message)
        return SettingsDecoder(cast("FrozenTaskSettings", value), path=f"{self._path}.{name}")

    def nullable_object(self, name: str) -> SettingsDecoder | None:
        value = self._take(name)
        if value is None:
            return None
        if not isinstance(value, Mapping):
            message = f"{self._path}.{name} must be an object or null"
            raise SettingsDocumentError(message)
        return SettingsDecoder(cast("FrozenTaskSettings", value), path=f"{self._path}.{name}")

    def finish(self) -> None:
        unknown = sorted(set(self._values) - self._consumed)
        if unknown:
            message = f"unknown settings at {self._path}: {unknown}"
            raise SettingsDocumentError(message)
