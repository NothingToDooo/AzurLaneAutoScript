from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

import pytest

from module.application import (
    AbortRequested,
    AbortToken,
    Blocked,
    ExecutionMode,
    PreemptionRequest,
    RunId,
    RunMetadata,
    Succeeded,
    TaskContext,
    TaskId,
    TaskResult,
)
from module.maintenance import (
    BenchmarkCategory,
    BenchmarkMeasurement,
    BenchmarkPreparation,
    BenchmarkReady,
    BenchmarkReport,
    BenchmarkScene,
    BenchmarkSelection,
    BenchmarkSettings,
    BenchmarkTask,
    BenchmarkUnavailable,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from module.interaction import CancellationSignal


class _Engine:
    def __init__(
        self,
        calls: list[str],
        report: BenchmarkReport,
        *,
        after_measure: Callable[[], None] | None = None,
    ) -> None:
        self._calls = calls
        self._report = report
        self._after_measure = after_measure
        self.scene: BenchmarkScene | None = None

    def measure(self, scene: BenchmarkScene, cancellation: CancellationSignal) -> BenchmarkReport:
        cancellation.raise_if_requested()
        self._calls.append("measure")
        self.scene = scene
        if self._after_measure is not None:
            self._after_measure()
        return self._report


class _Environment:
    def __init__(
        self,
        calls: list[str],
        preparation: BenchmarkPreparation | None = None,
        *,
        after_prepare: Callable[[], None] | None = None,
    ) -> None:
        self._calls = calls
        self._preparation = BenchmarkReady() if preparation is None else preparation
        self._after_prepare = after_prepare
        self.safe_stage: str | None = None

    def prepare(self, safe_stage: str, cancellation: CancellationSignal) -> BenchmarkPreparation:
        cancellation.raise_if_requested()
        self._calls.append("prepare")
        self.safe_stage = safe_stage
        if self._after_prepare is not None:
            self._after_prepare()
        return self._preparation


class _Presenter:
    def __init__(self, calls: list[str]) -> None:
        self._calls = calls
        self.report: BenchmarkReport | None = None

    def present(self, report: BenchmarkReport, cancellation: CancellationSignal) -> None:
        cancellation.raise_if_requested()
        self._calls.append("present")
        self.report = report


def _context(abort: AbortToken | None = None) -> TaskContext:
    return TaskContext(
        task_id=TaskId("benchmark"),
        run_id=RunId("run-benchmark"),
        started_at=datetime(2026, 7, 13, tzinfo=UTC),
        mode=ExecutionMode.DIRECT_COMMAND,
        metadata=RunMetadata(settings_revision=1, content_revision="content-1", client_ui_revision="ui-1"),
        abort=AbortToken() if abort is None else abort,
        preemption=PreemptionRequest(),
    )


def _full_report() -> BenchmarkReport:
    return BenchmarkReport(
        measurements=(
            BenchmarkMeasurement(BenchmarkCategory.SCREENSHOT, "nemu_ipc", average_seconds=0.02),
            BenchmarkMeasurement(BenchmarkCategory.CLICK, "minitouch", average_seconds=0.08),
        ),
        selections=(
            BenchmarkSelection(BenchmarkCategory.SCREENSHOT, "nemu_ipc"),
            BenchmarkSelection(BenchmarkCategory.CLICK, "minitouch"),
        ),
    )


def test_benchmark_measures_selected_scene_presents_report_and_succeeds() -> None:
    calls: list[str] = []
    report = _full_report()
    environment = _Environment(calls)
    engine = _Engine(calls, report)
    presenter = _Presenter(calls)
    settings = BenchmarkSettings(BenchmarkScene.SCREENSHOT_AND_CLICK)

    result = BenchmarkTask(environment, engine, presenter, settings).run(_context())

    assert calls == ["prepare", "measure", "present"]
    assert environment.safe_stage == "7-2"
    assert engine.scene is BenchmarkScene.SCREENSHOT_AND_CLICK
    assert presenter.report is report
    assert result == TaskResult(outcome=Succeeded())


def test_benchmark_unavailable_is_an_explicit_blocked_outcome_without_presentation() -> None:
    calls: list[str] = []
    environment = _Environment(calls, BenchmarkUnavailable("campaign scene unavailable"))
    engine = _Engine(calls, _full_report())
    presenter = _Presenter(calls)

    result = BenchmarkTask(
        environment,
        engine,
        presenter,
        BenchmarkSettings(BenchmarkScene.SCREENSHOT),
    ).run(_context())

    assert calls == ["prepare"]
    assert presenter.report is None
    assert result == TaskResult(outcome=Blocked("campaign scene unavailable"))


def test_failed_individual_measurement_is_still_presented_as_a_completed_benchmark() -> None:
    calls: list[str] = []
    report = BenchmarkReport(
        measurements=(BenchmarkMeasurement(BenchmarkCategory.SCREENSHOT, "nemu_ipc", failure_reason="human takeover"),),
        selections=(BenchmarkSelection(BenchmarkCategory.SCREENSHOT, "nemu_ipc"),),
    )

    result = BenchmarkTask(
        _Environment(calls),
        _Engine(calls, report),
        _Presenter(calls),
        BenchmarkSettings(BenchmarkScene.SCREENSHOT),
    ).run(_context())

    assert calls == ["prepare", "measure", "present"]
    assert result == TaskResult(outcome=Succeeded())


def test_benchmark_abort_before_run_prevents_measurement() -> None:
    calls: list[str] = []
    abort = AbortToken()
    abort.request("manual stop")
    task = BenchmarkTask(
        _Environment(calls),
        _Engine(calls, _full_report()),
        _Presenter(calls),
        BenchmarkSettings(BenchmarkScene.SCREENSHOT_AND_CLICK),
    )

    with pytest.raises(AbortRequested, match="manual stop"):
        task.run(_context(abort))

    assert calls == []


def test_benchmark_abort_after_preparation_prevents_measurement_and_presentation() -> None:
    calls: list[str] = []
    abort = AbortToken()

    def request_abort() -> None:
        abort.request("stop requested")

    task = BenchmarkTask(
        _Environment(calls, after_prepare=request_abort),
        _Engine(calls, _full_report()),
        _Presenter(calls),
        BenchmarkSettings(BenchmarkScene.SCREENSHOT_AND_CLICK),
    )

    with pytest.raises(AbortRequested, match="stop requested"):
        task.run(_context(abort))

    assert calls == ["prepare"]


def test_benchmark_abort_after_measurement_prevents_presentation() -> None:
    calls: list[str] = []
    abort = AbortToken()

    def request_abort() -> None:
        abort.request("stop requested")

    task = BenchmarkTask(
        _Environment(calls),
        _Engine(calls, _full_report(), after_measure=request_abort),
        _Presenter(calls),
        BenchmarkSettings(BenchmarkScene.SCREENSHOT_AND_CLICK),
    )

    with pytest.raises(AbortRequested, match="stop requested"):
        task.run(_context(abort))

    assert calls == ["prepare", "measure"]


def test_benchmark_rejects_engine_report_that_does_not_match_the_selected_scene() -> None:
    calls: list[str] = []
    task = BenchmarkTask(
        _Environment(calls),
        _Engine(calls, _full_report()),
        _Presenter(calls),
        BenchmarkSettings(BenchmarkScene.SCREENSHOT),
    )

    with pytest.raises(ValueError, match="exactly match"):
        task.run(_context())

    assert calls == ["prepare", "measure"]


def test_benchmark_contracts_reject_invalid_settings_and_measurements() -> None:
    with pytest.raises(TypeError, match="scene must be a BenchmarkScene"):
        BenchmarkSettings(cast("BenchmarkScene", "screenshot"))

    with pytest.raises(ValueError, match="exactly one"):
        BenchmarkMeasurement(BenchmarkCategory.CLICK, "minitouch")

    with pytest.raises(ValueError, match="finite and non-negative"):
        BenchmarkMeasurement(BenchmarkCategory.CLICK, "minitouch", average_seconds=float("nan"))

    with pytest.raises(ValueError, match="selections must cover"):
        BenchmarkReport(
            measurements=(BenchmarkMeasurement(BenchmarkCategory.CLICK, "minitouch", average_seconds=0.1),),
            selections=(),
        )
