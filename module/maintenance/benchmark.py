import math
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol, override

from module.application import Blocked, Succeeded, Task, TaskContext, TaskResult

if TYPE_CHECKING:
    from module.interaction import CancellationSignal


def _validate_non_empty_text(value: str, *, field_name: str) -> None:
    if not isinstance(value, str):
        message = f"{field_name} must be a string"
        raise TypeError(message)
    if not value or value != value.strip():
        message = f"{field_name} must be non-empty and have no surrounding whitespace"
        raise ValueError(message)


class BenchmarkScene(StrEnum):
    SCREENSHOT_AND_CLICK = "screenshot_click"
    SCREENSHOT = "screenshot"
    CLICK = "click"

    @property
    def categories(self) -> frozenset[BenchmarkCategory]:
        if self is BenchmarkScene.SCREENSHOT:
            return frozenset({BenchmarkCategory.SCREENSHOT})
        if self is BenchmarkScene.CLICK:
            return frozenset({BenchmarkCategory.CLICK})
        return frozenset(BenchmarkCategory)


class BenchmarkCategory(StrEnum):
    SCREENSHOT = "screenshot"
    CLICK = "click"


@dataclass(frozen=True, slots=True)
class BenchmarkSettings:
    scene: BenchmarkScene
    safe_stage: str = "7-2"

    def __post_init__(self) -> None:
        if not isinstance(self.scene, BenchmarkScene):
            message = "scene must be a BenchmarkScene"
            raise TypeError(message)
        _validate_non_empty_text(self.safe_stage, field_name="safe_stage")


@dataclass(frozen=True, slots=True)
class BenchmarkMeasurement:
    category: BenchmarkCategory
    method: str
    average_seconds: float | None = None
    failure_reason: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.category, BenchmarkCategory):
            message = "category must be a BenchmarkCategory"
            raise TypeError(message)
        _validate_non_empty_text(self.method, field_name="method")
        has_average = self.average_seconds is not None
        has_failure = self.failure_reason is not None
        if has_average == has_failure:
            message = "measurement must contain exactly one of average_seconds or failure_reason"
            raise ValueError(message)
        if has_average:
            average_seconds = self.average_seconds
            if not isinstance(average_seconds, float):
                message = "average_seconds must be a float"
                raise TypeError(message)
            if not math.isfinite(average_seconds) or average_seconds < 0:
                message = "average_seconds must be finite and non-negative"
                raise ValueError(message)
        else:
            failure_reason = self.failure_reason
            if failure_reason is None:
                message = "failure_reason must be present"
                raise ValueError(message)
            _validate_non_empty_text(failure_reason, field_name="failure_reason")


@dataclass(frozen=True, slots=True)
class BenchmarkSelection:
    category: BenchmarkCategory
    method: str

    def __post_init__(self) -> None:
        if not isinstance(self.category, BenchmarkCategory):
            message = "category must be a BenchmarkCategory"
            raise TypeError(message)
        _validate_non_empty_text(self.method, field_name="method")


@dataclass(frozen=True, slots=True)
class BenchmarkReport:
    measurements: tuple[BenchmarkMeasurement, ...]
    selections: tuple[BenchmarkSelection, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.measurements, tuple) or any(
            not isinstance(measurement, BenchmarkMeasurement) for measurement in self.measurements
        ):
            message = "measurements must be a tuple of BenchmarkMeasurement values"
            raise TypeError(message)
        if not self.measurements:
            message = "measurements must not be empty"
            raise ValueError(message)
        if not isinstance(self.selections, tuple) or any(
            not isinstance(selection, BenchmarkSelection) for selection in self.selections
        ):
            message = "selections must be a tuple of BenchmarkSelection values"
            raise TypeError(message)

        measurement_keys = tuple((measurement.category, measurement.method) for measurement in self.measurements)
        if len(set(measurement_keys)) != len(measurement_keys):
            message = "measurements must not contain duplicate category and method pairs"
            raise ValueError(message)

        selection_categories = tuple(selection.category for selection in self.selections)
        if len(set(selection_categories)) != len(selection_categories):
            message = "selections must contain at most one method per category"
            raise ValueError(message)
        if any((selection.category, selection.method) not in measurement_keys for selection in self.selections):
            message = "each selection must reference a measurement"
            raise ValueError(message)

        measurement_categories = {measurement.category for measurement in self.measurements}
        if set(selection_categories) != measurement_categories:
            message = "selections must cover every measured category"
            raise ValueError(message)


@dataclass(frozen=True, slots=True)
class BenchmarkReady:
    pass


@dataclass(frozen=True, slots=True)
class BenchmarkUnavailable:
    reason: str

    def __post_init__(self) -> None:
        _validate_non_empty_text(self.reason, field_name="reason")


type BenchmarkPreparation = BenchmarkReady | BenchmarkUnavailable


class BenchmarkEnvironment(Protocol):
    def prepare(self, safe_stage: str, cancellation: CancellationSignal) -> BenchmarkPreparation: ...


class BenchmarkEngine(Protocol):
    def measure(self, scene: BenchmarkScene, cancellation: CancellationSignal) -> BenchmarkReport: ...


class BenchmarkPresenter(Protocol):
    def present(self, report: BenchmarkReport, cancellation: CancellationSignal) -> None: ...


class BenchmarkTask(Task):
    __slots__ = ("_engine", "_environment", "_presenter", "_settings")

    def __init__(
        self,
        environment: BenchmarkEnvironment,
        engine: BenchmarkEngine,
        presenter: BenchmarkPresenter,
        settings: BenchmarkSettings,
    ) -> None:
        if not isinstance(settings, BenchmarkSettings):
            message = "settings must be BenchmarkSettings"
            raise TypeError(message)
        self._environment = environment
        self._engine = engine
        self._presenter = presenter
        self._settings = settings

    @override
    def run(self, context: TaskContext) -> TaskResult:
        context.abort.raise_if_requested()
        preparation = self._environment.prepare(self._settings.safe_stage, context.abort)
        if not isinstance(preparation, BenchmarkReady | BenchmarkUnavailable):
            message = "BenchmarkEnvironment.prepare() must return BenchmarkReady or BenchmarkUnavailable"
            raise TypeError(message)
        context.abort.raise_if_requested()

        if isinstance(preparation, BenchmarkUnavailable):
            return TaskResult(outcome=Blocked(preparation.reason))

        report = self._engine.measure(self._settings.scene, context.abort)
        if not isinstance(report, BenchmarkReport):
            message = "BenchmarkEngine.measure() must return a BenchmarkReport"
            raise TypeError(message)
        context.abort.raise_if_requested()

        categories = {measurement.category for measurement in report.measurements}
        if categories != set(self._settings.scene.categories):
            message = "benchmark report categories must exactly match the configured scene"
            raise ValueError(message)

        self._presenter.present(report, context.abort)
        context.abort.raise_if_requested()
        return TaskResult(outcome=Succeeded())
