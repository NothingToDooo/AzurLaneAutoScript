from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Protocol, override

from module.gameplay.facility import (
    CommissionReport,
    CommissionSettings,
    CommissionWorkflow,
    ResearchReport,
    ResearchSettings,
    ResearchWorkflow,
    TacticalReport,
    TacticalSettings,
    TacticalWorkflow,
)

if TYPE_CHECKING:
    from module.interaction import CancellationSignal


def _validate_datetime(value: datetime, *, field_name: str) -> None:
    if not isinstance(value, datetime):
        message = f"{field_name} must be a datetime"
        raise TypeError(message)


def _aware_local(value: datetime) -> datetime:
    _validate_datetime(value, field_name="datetime value")
    if value.tzinfo is None or value.utcoffset() is None:
        return value.astimezone()
    return value


def _validate_count(value: int, *, field_name: str, maximum: int | None = None) -> None:
    if type(value) is not int:
        message = f"{field_name} must be an integer"
        raise TypeError(message)
    if value < 0 or (maximum is not None and value > maximum):
        suffix = "non-negative" if maximum is None else f"between zero and {maximum}"
        message = f"{field_name} must be {suffix}"
        raise ValueError(message)


@dataclass(frozen=True, slots=True)
class ResearchQueueEvidence:
    available_slots: int
    first_finish_at: datetime | None

    def __post_init__(self) -> None:
        _validate_count(self.available_slots, field_name="available_slots", maximum=5)
        if self.available_slots == 5:
            if self.first_finish_at is not None:
                message = "an empty research queue must not have a first finish time"
                raise ValueError(message)
            return
        if self.first_finish_at is None:
            message = "a non-empty research queue must have a first finish time"
            raise ValueError(message)
        _validate_datetime(self.first_finish_at, field_name="first_finish_at")


@dataclass(frozen=True, slots=True)
class CommissionEvidence:
    finish_times: tuple[datetime, ...]
    daily_pending: int
    filtered_urgent_pending: int

    def __post_init__(self) -> None:
        if not isinstance(self.finish_times, tuple):
            message = "finish_times must be a tuple"
            raise TypeError(message)
        for finish_at in self.finish_times:
            _validate_datetime(finish_at, field_name="finish_times item")
        _validate_count(self.daily_pending, field_name="daily_pending")
        _validate_count(self.filtered_urgent_pending, field_name="filtered_urgent_pending")


@dataclass(frozen=True, slots=True)
class TacticalEvidence:
    finish_times: tuple[datetime, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.finish_times, tuple):
            message = "finish_times must be a tuple"
            raise TypeError(message)
        for finish_at in self.finish_times:
            _validate_datetime(finish_at, field_name="finish_times item")


class ResearchUiDriver(Protocol):
    def execute(self, settings: ResearchSettings, cancellation: CancellationSignal) -> ResearchQueueEvidence: ...


class CommissionUiDriver(Protocol):
    def execute(self, settings: CommissionSettings, cancellation: CancellationSignal) -> CommissionEvidence: ...


class TacticalUiDriver(Protocol):
    def execute(self, settings: TacticalSettings, cancellation: CancellationSignal) -> TacticalEvidence: ...


class FacilityClock(Protocol):
    def now(self) -> datetime: ...


class SystemFacilityClock:
    @staticmethod
    def now() -> datetime:
        return datetime.now().astimezone()


def _require_method(value: object, method_name: str, *, field_name: str) -> None:
    if isinstance(value, type) or not callable(getattr(value, method_name, None)):
        message = f"{field_name} must implement {method_name}()"
        raise TypeError(message)


class LiveResearchWorkflow(ResearchWorkflow):
    __slots__ = ("_clock", "_driver")

    def __init__(self, driver: ResearchUiDriver, clock: FacilityClock | None = None) -> None:
        selected_clock = SystemFacilityClock() if clock is None else clock
        _require_method(driver, "execute", field_name="driver")
        _require_method(selected_clock, "now", field_name="clock")
        self._driver = driver
        self._clock = selected_clock

    @override
    def execute(self, settings: ResearchSettings, cancellation: CancellationSignal) -> ResearchReport:
        if not isinstance(settings, ResearchSettings):
            message = "settings must be ResearchSettings"
            raise TypeError(message)
        cancellation.raise_if_requested()
        evidence = self._driver.execute(settings, cancellation)
        if not isinstance(evidence, ResearchQueueEvidence):
            message = "ResearchUiDriver.execute() must return ResearchQueueEvidence"
            raise TypeError(message)
        finish_at = None if evidence.first_finish_at is None else _aware_local(evidence.first_finish_at)
        return ResearchReport(
            observed_at=_aware_local(self._clock.now()),
            available_slots=evidence.available_slots,
            first_finish_at=finish_at,
        )


class LiveCommissionWorkflow(CommissionWorkflow):
    __slots__ = ("_clock", "_driver")

    def __init__(self, driver: CommissionUiDriver, clock: FacilityClock | None = None) -> None:
        selected_clock = SystemFacilityClock() if clock is None else clock
        _require_method(driver, "execute", field_name="driver")
        _require_method(selected_clock, "now", field_name="clock")
        self._driver = driver
        self._clock = selected_clock

    @override
    def execute(self, settings: CommissionSettings, cancellation: CancellationSignal) -> CommissionReport:
        if not isinstance(settings, CommissionSettings):
            message = "settings must be CommissionSettings"
            raise TypeError(message)
        cancellation.raise_if_requested()
        evidence = self._driver.execute(settings, cancellation)
        if not isinstance(evidence, CommissionEvidence):
            message = "CommissionUiDriver.execute() must return CommissionEvidence"
            raise TypeError(message)
        observed_at = _aware_local(self._clock.now())
        return CommissionReport(
            observed_at=observed_at,
            finish_times=tuple(_aware_local(finish_at) for finish_at in evidence.finish_times),
            daily_pending=evidence.daily_pending,
            filtered_urgent_pending=evidence.filtered_urgent_pending,
        )


class LiveTacticalWorkflow(TacticalWorkflow):
    __slots__ = ("_clock", "_driver")

    def __init__(self, driver: TacticalUiDriver, clock: FacilityClock | None = None) -> None:
        selected_clock = SystemFacilityClock() if clock is None else clock
        _require_method(driver, "execute", field_name="driver")
        _require_method(selected_clock, "now", field_name="clock")
        self._driver = driver
        self._clock = selected_clock

    @override
    def execute(self, settings: TacticalSettings, cancellation: CancellationSignal) -> TacticalReport:
        if not isinstance(settings, TacticalSettings):
            message = "settings must be TacticalSettings"
            raise TypeError(message)
        cancellation.raise_if_requested()
        evidence = self._driver.execute(settings, cancellation)
        if not isinstance(evidence, TacticalEvidence):
            message = "TacticalUiDriver.execute() must return TacticalEvidence"
            raise TypeError(message)
        finish_times = tuple(_aware_local(finish_at) for finish_at in evidence.finish_times)
        return TacticalReport(
            observed_at=_aware_local(self._clock.now()),
            finish_at=min(finish_times, default=None),
        )
