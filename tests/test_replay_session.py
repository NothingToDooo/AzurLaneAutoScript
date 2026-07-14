import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from PIL import Image

from module.application import ExecutionMode, RunId, RunMetadata, TaskId
from module.interaction import (
    Action,
    ActionReceipt,
    AppStatus,
    Click,
    FrameId,
    LongPress,
    ScreenPoint,
    SemanticTarget,
    Swipe,
)
from module.replay import (
    ActionStep,
    AppStartStep,
    AppStatusStep,
    AppStopStep,
    CaptureStep,
    ReplayGameSession,
    ReplaySessionExhaustedError,
    ReplaySessionImageLoadError,
    ReplaySessionIncompleteError,
    ReplaySessionMismatchError,
    ReplayStep,
    ReplayTrace,
    TraceMetadata,
    read_session_trace,
    write_session_trace,
)

if TYPE_CHECKING:
    from pathlib import Path


class _Cancelled(Exception):
    pass


class _Cancellation:
    def __init__(self, *, cancelled: bool = False) -> None:
        self.cancelled = cancelled
        self.checks = 0

    def raise_if_requested(self) -> None:
        self.checks += 1
        if self.cancelled:
            raise _Cancelled


def _metadata() -> TraceMetadata:
    return TraceMetadata(
        run_id=RunId("run-replay-1"),
        task_id=TaskId("campaign"),
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        run_metadata=RunMetadata(
            settings_revision=12,
            content_revision="content-20260713",
            client_ui_revision="ui-cn-3",
        ),
        random_seed=98421,
    )


def _trace(*steps: ReplayStep) -> ReplayTrace:
    return ReplayTrace(metadata=_metadata(), steps=steps)


def _capture(image_path: Path, *, frame_id: int = 0) -> CaptureStep:
    return CaptureStep(
        frame_id=FrameId(frame_id),
        image_path=image_path,
        captured_at_monotonic=10.5 + frame_id,
        captured_at_wall=datetime(2026, 7, 13, 12, frame_id, tzinfo=UTC),
    )


def _actions(frame_id: FrameId | None = None) -> tuple[Action, ...]:
    if frame_id is None:
        frame_id = FrameId(0)
    target = SemanticTarget("interruption.dismiss")
    return (
        Click(target=target, point=ScreenPoint(10, 20), based_on_frame=frame_id),
        LongPress(
            target=SemanticTarget("assist.hold"),
            point=ScreenPoint(30, 40),
            duration_seconds=0.75,
            based_on_frame=frame_id,
        ),
        Swipe(
            target=SemanticTarget("campaign.pan"),
            start=ScreenPoint(50, 60),
            end=ScreenPoint(150, 160),
            based_on_frame=frame_id,
        ),
    )


def _make_image(path: Path, value: int = 7) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (3, 2), (value, value + 1, value + 2)).save(path)


def test_session_trace_round_trip_is_strict_deterministic_and_complete(tmp_path: Path) -> None:
    image_path = tmp_path / "frames" / "frame-000.png"
    trace_path = tmp_path / "trace.json"
    _make_image(image_path)
    click, long_press, swipe = _actions()
    trace = _trace(
        _capture(image_path),
        ActionStep(click, 11.0),
        ActionStep(long_press, 12.0),
        ActionStep(swipe, 13.0),
        AppStatusStep(AppStatus.RUNNING),
        AppStopStep(),
        AppStartStep(),
    )

    write_session_trace(trace_path, trace)
    first_bytes = trace_path.read_bytes()
    write_session_trace(trace_path, trace)

    payload = json.loads(trace_path.read_text(encoding="utf-8"))
    assert trace_path.read_bytes() == first_bytes
    assert set(payload) == {"schema_version", "metadata", "steps"}
    assert payload["schema_version"] == 1
    assert payload["steps"][0]["image_path"] == "frames/frame-000.png"
    assert payload["steps"][2]["action"]["kind"] == "long_press"
    assert read_session_trace(trace_path) == trace


def test_replay_game_session_implements_all_ports_with_one_cursor(tmp_path: Path) -> None:
    image_path = tmp_path / "frame.png"
    _make_image(image_path, value=20)
    actions = _actions()
    trace = _trace(
        _capture(image_path),
        *(ActionStep(action, 20.0 + index) for index, action in enumerate(actions)),
        AppStatusStep(AppStatus.RUNNING),
        AppStopStep(),
        AppStartStep(),
    )
    session = ReplayGameSession(trace)
    cancellation = _Cancellation()

    frame = session.frames.capture(cancellation)
    receipts = tuple(session.actions.perform(action, cancellation) for action in actions)
    status = session.app.status(cancellation)
    session.app.stop(cancellation)
    session.app.start(cancellation)
    session.assert_complete()

    assert frame.id == FrameId(0)
    assert frame.captured_at_monotonic == 10.5
    assert frame.pixels[0, 0].tolist() == [20, 21, 22]
    assert not frame.pixels.flags.writeable
    assert receipts == tuple(
        ActionReceipt(sequence=index, action=action, issued_at_monotonic=20.0 + index)
        for index, action in enumerate(actions)
    )
    assert status is AppStatus.RUNNING
    assert cancellation.checks == 7


def test_step_order_mismatch_does_not_consume_and_exhaustion_is_distinct(tmp_path: Path) -> None:
    image_path = tmp_path / "frame.png"
    _make_image(image_path)
    session = ReplayGameSession(_trace(_capture(image_path)))
    cancellation = _Cancellation()

    with pytest.raises(ReplaySessionMismatchError, match="expected app_status, got capture"):
        session.app.status(cancellation)

    session.frames.capture(cancellation)
    session.assert_complete()
    with pytest.raises(ReplaySessionExhaustedError, match="exhausted before capture"):
        session.frames.capture(cancellation)


def test_action_mismatch_compares_the_complete_action_without_consuming() -> None:
    expected = _actions()[0]
    assert isinstance(expected, Click)
    actual = Click(
        target=expected.target,
        point=ScreenPoint(expected.point.x + 1, expected.point.y),
        based_on_frame=expected.based_on_frame,
    )
    session = ReplayGameSession(_trace(ActionStep(expected, 33.0)))
    cancellation = _Cancellation()

    with pytest.raises(ReplaySessionMismatchError, match="replay action mismatch"):
        session.actions.perform(actual, cancellation)

    assert session.actions.perform(expected, cancellation) == ActionReceipt(
        sequence=0,
        action=expected,
        issued_at_monotonic=33.0,
    )
    session.assert_complete()


def test_cancellation_is_checked_before_the_cursor_is_consumed(tmp_path: Path) -> None:
    image_path = tmp_path / "frame.png"
    _make_image(image_path)
    session = ReplayGameSession(_trace(_capture(image_path)))
    cancelled = _Cancellation(cancelled=True)

    with pytest.raises(_Cancelled):
        session.frames.capture(cancelled)

    frame = session.frames.capture(_Cancellation())
    assert frame.id == FrameId(0)
    session.assert_complete()


def test_read_session_trace_rejects_image_path_traversal(tmp_path: Path) -> None:
    image_path = tmp_path / "frame.png"
    trace_path = tmp_path / "trace.json"
    _make_image(image_path)
    write_session_trace(trace_path, _trace(_capture(image_path)))
    payload = json.loads(trace_path.read_text(encoding="utf-8"))
    payload["steps"][0]["image_path"] = "../outside.png"
    trace_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="inside trace directory"):
        read_session_trace(trace_path)


def test_write_session_trace_rejects_images_outside_trace_directory(tmp_path: Path) -> None:
    trace_directory = tmp_path / "bundle"
    trace_directory.mkdir()
    outside_image = tmp_path / "outside.png"
    _make_image(outside_image)

    with pytest.raises(ValueError, match="inside trace directory"):
        write_session_trace(trace_directory / "trace.json", _trace(_capture(outside_image)))


def test_read_session_trace_rejects_unknown_fields_and_other_versions(tmp_path: Path) -> None:
    trace_path = tmp_path / "trace.json"
    write_session_trace(trace_path, _trace())
    payload = json.loads(trace_path.read_text(encoding="utf-8"))
    payload["unexpected"] = True
    trace_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="exactly these keys"):
        read_session_trace(trace_path)

    del payload["unexpected"]
    payload["schema_version"] = 2
    trace_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="schema_version must be 1"):
        read_session_trace(trace_path)


def test_assert_complete_reports_unconsumed_linear_steps(tmp_path: Path) -> None:
    image_path = tmp_path / "frame.png"
    session = ReplayGameSession(
        _trace(
            _capture(image_path),
            AppStatusStep(AppStatus.UNKNOWN),
        )
    )

    with pytest.raises(ReplaySessionIncompleteError, match=r"2 step\(s\) remain at cursor 0"):
        session.assert_complete()


def test_image_load_failure_is_distinct_and_does_not_consume(tmp_path: Path) -> None:
    image_path = tmp_path / "late.png"
    session = ReplayGameSession(_trace(_capture(image_path)))
    cancellation = _Cancellation()

    with pytest.raises(ReplaySessionImageLoadError, match="unable to load replay image"):
        session.frames.capture(cancellation)

    _make_image(image_path)
    assert session.frames.capture(cancellation).id == FrameId(0)
    session.assert_complete()
