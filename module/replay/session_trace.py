import json
import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Final, Never, cast

from module.application import ExecutionMode, RunId, RunMetadata, TaskId
from module.interaction.model import (
    Action,
    AppStatus,
    Click,
    FrameId,
    LongPress,
    ScreenPoint,
    SemanticTarget,
    Swipe,
)

_SCHEMA_VERSION: Final = 1


@dataclass(frozen=True, slots=True)
class TraceMetadata:
    run_id: RunId
    task_id: TaskId
    execution_mode: ExecutionMode
    run_metadata: RunMetadata
    random_seed: int

    def __post_init__(self) -> None:
        expected = (
            ("run_id", self.run_id, RunId),
            ("task_id", self.task_id, TaskId),
            ("execution_mode", self.execution_mode, ExecutionMode),
            ("run_metadata", self.run_metadata, RunMetadata),
        )
        for name, value, expected_type in expected:
            if not isinstance(value, expected_type):
                message = f"{name} must be a {expected_type.__name__}"
                raise TypeError(message)
        if type(self.random_seed) is not int:
            message = "random_seed must be an integer"
            raise TypeError(message)


@dataclass(frozen=True, slots=True)
class CaptureStep:
    frame_id: FrameId
    image_path: Path
    captured_at_monotonic: float
    captured_at_wall: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.frame_id, FrameId):
            message = "frame_id must be a FrameId"
            raise TypeError(message)
        if not isinstance(self.image_path, Path):
            message = "image_path must be a Path"
            raise TypeError(message)
        if self.image_path == Path():
            message = "image_path must identify a file"
            raise ValueError(message)
        object.__setattr__(
            self,
            "captured_at_monotonic",
            _normalize_non_negative_number(self.captured_at_monotonic, field="captured_at_monotonic"),
        )
        if not isinstance(self.captured_at_wall, datetime):
            message = "captured_at_wall must be a datetime"
            raise TypeError(message)
        if self.captured_at_wall.tzinfo is None or self.captured_at_wall.utcoffset() is None:
            message = "captured_at_wall must include a timezone"
            raise ValueError(message)


@dataclass(frozen=True, slots=True)
class ActionStep:
    action: Action
    issued_at_monotonic: float

    def __post_init__(self) -> None:
        if not isinstance(self.action, Click | LongPress | Swipe):
            message = "action must be an Action"
            raise TypeError(message)
        object.__setattr__(
            self,
            "issued_at_monotonic",
            _normalize_non_negative_number(self.issued_at_monotonic, field="issued_at_monotonic"),
        )


@dataclass(frozen=True, slots=True)
class AppStatusStep:
    status: AppStatus

    def __post_init__(self) -> None:
        if not isinstance(self.status, AppStatus):
            message = "status must be an AppStatus"
            raise TypeError(message)


@dataclass(frozen=True, slots=True)
class AppStartStep:
    pass


@dataclass(frozen=True, slots=True)
class AppStopStep:
    pass


type ReplayStep = CaptureStep | ActionStep | AppStatusStep | AppStartStep | AppStopStep


@dataclass(frozen=True, slots=True)
class ReplayTrace:
    metadata: TraceMetadata
    steps: tuple[ReplayStep, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.metadata, TraceMetadata):
            message = "metadata must be TraceMetadata"
            raise TypeError(message)
        if not isinstance(self.steps, tuple):
            message = "steps must be a tuple"
            raise TypeError(message)
        if any(
            not isinstance(step, CaptureStep | ActionStep | AppStatusStep | AppStartStep | AppStopStep)
            for step in self.steps
        ):
            message = "steps must contain only ReplayStep values"
            raise TypeError(message)


def write_session_trace(trace_path: Path, trace: ReplayTrace) -> None:
    trace_path = Path(trace_path)
    if not isinstance(trace, ReplayTrace):
        message = "trace must be a ReplayTrace"
        raise TypeError(message)
    payload = {
        "schema_version": _SCHEMA_VERSION,
        "metadata": _serialize_metadata(trace.metadata),
        "steps": [_serialize_step(step, trace_path) for step in trace.steps],
    }
    serialized = json.dumps(payload, allow_nan=False, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    trace_path.write_text(serialized, encoding="utf-8", newline="\n")


def read_session_trace(trace_path: Path) -> ReplayTrace:
    trace_path = Path(trace_path)
    payload: object = json.loads(
        trace_path.read_text(encoding="utf-8"),
        object_pairs_hook=_object_without_duplicate_keys,
        parse_constant=_reject_non_json_constant,
    )
    root = _require_object(payload, location="trace")
    _require_exact_keys(root, {"schema_version", "metadata", "steps"}, location="trace")
    version = _require_integer(root["schema_version"], location="trace.schema_version")
    if version != _SCHEMA_VERSION:
        message = f"trace.schema_version must be {_SCHEMA_VERSION}"
        raise ValueError(message)
    metadata = _parse_metadata(root["metadata"])
    raw_steps = _require_list(root["steps"], location="trace.steps")
    steps = tuple(_parse_step(step, trace_path, index) for index, step in enumerate(raw_steps))
    return ReplayTrace(metadata=metadata, steps=steps)


def _normalize_non_negative_number(value: float, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        message = f"{field} must be a number"
        raise TypeError(message)
    normalized = float(value)
    if not math.isfinite(normalized) or normalized < 0:
        message = f"{field} must be finite and non-negative"
        raise ValueError(message)
    return normalized


def _serialize_metadata(metadata: TraceMetadata) -> dict[str, object]:
    return {
        "run_id": metadata.run_id.value,
        "task_id": metadata.task_id.value,
        "execution_mode": metadata.execution_mode.value,
        "run_metadata": {
            "settings_revision": metadata.run_metadata.settings_revision,
            "content_revision": metadata.run_metadata.content_revision,
            "client_ui_revision": metadata.run_metadata.client_ui_revision,
        },
        "random_seed": metadata.random_seed,
    }


def _serialize_step(step: ReplayStep, trace_path: Path) -> dict[str, object]:
    if isinstance(step, CaptureStep):
        return {
            "kind": "capture",
            "frame_id": step.frame_id.value,
            "image_path": _portable_image_path(step.image_path, trace_path),
            "captured_at_monotonic": step.captured_at_monotonic,
            "captured_at_wall": step.captured_at_wall.isoformat(),
        }
    if isinstance(step, ActionStep):
        return {
            "kind": "action",
            "action": _serialize_action(step.action),
            "issued_at_monotonic": step.issued_at_monotonic,
        }
    if isinstance(step, AppStatusStep):
        return {"kind": "app_status", "status": step.status.value}
    if isinstance(step, AppStartStep):
        return {"kind": "app_start"}
    if isinstance(step, AppStopStep):
        return {"kind": "app_stop"}
    message = f"unsupported replay step: {type(step).__name__}"
    raise TypeError(message)


def _serialize_action(action: Action) -> dict[str, object]:
    common: dict[str, object] = {
        "target": action.target.value,
        "based_on_frame": action.based_on_frame.value,
    }
    if isinstance(action, Click):
        return {"kind": "click", **common, "point": _serialize_point(action.point)}
    if isinstance(action, LongPress):
        return {
            "kind": "long_press",
            **common,
            "point": _serialize_point(action.point),
            "duration_seconds": action.duration_seconds,
        }
    if isinstance(action, Swipe):
        return {
            "kind": "swipe",
            **common,
            "start": _serialize_point(action.start),
            "end": _serialize_point(action.end),
        }
    message = f"unsupported action: {type(action).__name__}"
    raise TypeError(message)


def _serialize_point(point: ScreenPoint) -> dict[str, int]:
    return {"x": point.x, "y": point.y}


def _portable_image_path(image_path: Path, trace_path: Path) -> str:
    trace_directory = trace_path.parent.resolve()
    resolved_path = image_path.resolve() if image_path.is_absolute() else (trace_directory / image_path).resolve()
    if not resolved_path.is_relative_to(trace_directory):
        message = f"capture image path must be inside trace directory: {image_path}"
        raise ValueError(message)
    return resolved_path.relative_to(trace_directory).as_posix()


def _parse_metadata(value: object) -> TraceMetadata:
    metadata = _require_object(value, location="trace.metadata")
    _require_exact_keys(
        metadata,
        {"run_id", "task_id", "execution_mode", "run_metadata", "random_seed"},
        location="trace.metadata",
    )
    raw_run_metadata = _require_object(metadata["run_metadata"], location="trace.metadata.run_metadata")
    _require_exact_keys(
        raw_run_metadata,
        {"settings_revision", "content_revision", "client_ui_revision"},
        location="trace.metadata.run_metadata",
    )
    mode_value = _require_string(metadata["execution_mode"], location="trace.metadata.execution_mode")
    try:
        execution_mode = ExecutionMode(mode_value)
    except ValueError as error:
        message = "trace.metadata.execution_mode is not a valid ExecutionMode"
        raise ValueError(message) from error
    return TraceMetadata(
        run_id=RunId(_require_string(metadata["run_id"], location="trace.metadata.run_id")),
        task_id=TaskId(_require_string(metadata["task_id"], location="trace.metadata.task_id")),
        execution_mode=execution_mode,
        run_metadata=RunMetadata(
            settings_revision=_require_integer(
                raw_run_metadata["settings_revision"],
                location="trace.metadata.run_metadata.settings_revision",
            ),
            content_revision=_require_string(
                raw_run_metadata["content_revision"],
                location="trace.metadata.run_metadata.content_revision",
            ),
            client_ui_revision=_require_string(
                raw_run_metadata["client_ui_revision"],
                location="trace.metadata.run_metadata.client_ui_revision",
            ),
        ),
        random_seed=_require_integer(metadata["random_seed"], location="trace.metadata.random_seed"),
    )


def _parse_step(value: object, trace_path: Path, index: int) -> ReplayStep:
    location = f"trace.steps[{index}]"
    step = _require_object(value, location=location)
    kind = _require_string(step.get("kind"), location=f"{location}.kind")
    if kind == "capture":
        _require_exact_keys(
            step,
            {"kind", "frame_id", "image_path", "captured_at_monotonic", "captured_at_wall"},
            location=location,
        )
        return CaptureStep(
            frame_id=FrameId(_require_integer(step["frame_id"], location=f"{location}.frame_id")),
            image_path=_parse_image_path(
                _require_string(step["image_path"], location=f"{location}.image_path"),
                trace_path,
                location=f"{location}.image_path",
            ),
            captured_at_monotonic=_require_number(
                step["captured_at_monotonic"],
                location=f"{location}.captured_at_monotonic",
            ),
            captured_at_wall=_parse_datetime(step["captured_at_wall"], location=f"{location}.captured_at_wall"),
        )
    if kind == "action":
        _require_exact_keys(step, {"kind", "action", "issued_at_monotonic"}, location=location)
        return ActionStep(
            action=_parse_action(step["action"], location=f"{location}.action"),
            issued_at_monotonic=_require_number(
                step["issued_at_monotonic"],
                location=f"{location}.issued_at_monotonic",
            ),
        )
    if kind == "app_status":
        _require_exact_keys(step, {"kind", "status"}, location=location)
        status_value = _require_string(step["status"], location=f"{location}.status")
        try:
            return AppStatusStep(AppStatus(status_value))
        except ValueError as error:
            message = f"{location}.status is not a valid AppStatus"
            raise ValueError(message) from error
    if kind == "app_start":
        _require_exact_keys(step, {"kind"}, location=location)
        return AppStartStep()
    if kind == "app_stop":
        _require_exact_keys(step, {"kind"}, location=location)
        return AppStopStep()
    message = f"{location}.kind is not a supported replay step"
    raise ValueError(message)


def _parse_action(value: object, *, location: str) -> Action:
    action = _require_object(value, location=location)
    kind = _require_string(action.get("kind"), location=f"{location}.kind")
    if kind == "click":
        _require_exact_keys(action, {"kind", "target", "point", "based_on_frame"}, location=location)
        return Click(
            target=_parse_target(action["target"], location=f"{location}.target"),
            point=_parse_point(action["point"], location=f"{location}.point"),
            based_on_frame=_parse_frame_id(action["based_on_frame"], location=f"{location}.based_on_frame"),
        )
    if kind == "long_press":
        _require_exact_keys(
            action,
            {"kind", "target", "point", "duration_seconds", "based_on_frame"},
            location=location,
        )
        return LongPress(
            target=_parse_target(action["target"], location=f"{location}.target"),
            point=_parse_point(action["point"], location=f"{location}.point"),
            duration_seconds=_require_number(action["duration_seconds"], location=f"{location}.duration_seconds"),
            based_on_frame=_parse_frame_id(action["based_on_frame"], location=f"{location}.based_on_frame"),
        )
    if kind == "swipe":
        _require_exact_keys(
            action,
            {"kind", "target", "start", "end", "based_on_frame"},
            location=location,
        )
        return Swipe(
            target=_parse_target(action["target"], location=f"{location}.target"),
            start=_parse_point(action["start"], location=f"{location}.start"),
            end=_parse_point(action["end"], location=f"{location}.end"),
            based_on_frame=_parse_frame_id(action["based_on_frame"], location=f"{location}.based_on_frame"),
        )
    message = f"{location}.kind is not a supported Action"
    raise ValueError(message)


def _parse_target(value: object, *, location: str) -> SemanticTarget:
    return SemanticTarget(_require_string(value, location=location))


def _parse_frame_id(value: object, *, location: str) -> FrameId:
    return FrameId(_require_integer(value, location=location))


def _parse_point(value: object, *, location: str) -> ScreenPoint:
    point = _require_object(value, location=location)
    _require_exact_keys(point, {"x", "y"}, location=location)
    return ScreenPoint(
        x=_require_integer(point["x"], location=f"{location}.x"),
        y=_require_integer(point["y"], location=f"{location}.y"),
    )


def _parse_datetime(value: object, *, location: str) -> datetime:
    serialized = _require_string(value, location=location)
    try:
        parsed = datetime.fromisoformat(serialized)
    except ValueError as error:
        message = f"{location} must be an ISO 8601 datetime"
        raise ValueError(message) from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        message = f"{location} must include a timezone"
        raise ValueError(message)
    if parsed.isoformat() != serialized:
        message = f"{location} must use canonical ISO 8601 formatting"
        raise ValueError(message)
    return parsed


def _parse_image_path(raw_path: str, trace_path: Path, *, location: str) -> Path:
    relative_path = Path(raw_path)
    if relative_path.is_absolute() or relative_path.anchor:
        message = f"{location} must be a relative path"
        raise ValueError(message)
    trace_directory = trace_path.parent.resolve()
    resolved_path = (trace_directory / relative_path).resolve()
    if not resolved_path.is_relative_to(trace_directory):
        message = f"{location} must resolve inside trace directory"
        raise ValueError(message)
    if ".." in relative_path.parts or raw_path != relative_path.as_posix():
        message = f"{location} must be a canonical relative path"
        raise ValueError(message)
    return resolved_path


def _object_without_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            message = f"duplicate JSON key: {key}"
            raise ValueError(message)
        result[key] = value
    return result


def _reject_non_json_constant(value: str) -> Never:
    message = f"invalid JSON constant: {value}"
    raise ValueError(message)


def _require_object(value: object, *, location: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        message = f"{location} must be an object with string keys"
        raise TypeError(message)
    return cast("dict[str, object]", value)


def _require_exact_keys(value: dict[str, object], expected: set[str], *, location: str) -> None:
    if value.keys() != expected:
        message = f"{location} must contain exactly these keys: {', '.join(sorted(expected))}"
        raise ValueError(message)


def _require_list(value: object, *, location: str) -> list[object]:
    if not isinstance(value, list):
        message = f"{location} must be a list"
        raise TypeError(message)
    return cast("list[object]", value)


def _require_string(value: object, *, location: str) -> str:
    if not isinstance(value, str):
        message = f"{location} must be a string"
        raise TypeError(message)
    return value


def _require_integer(value: object, *, location: str) -> int:
    if type(value) is not int:
        message = f"{location} must be an integer"
        raise TypeError(message)
    return value


def _require_number(value: object, *, location: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        message = f"{location} must be a number"
        raise TypeError(message)
    normalized = float(value)
    if not math.isfinite(normalized):
        message = f"{location} must be finite"
        raise ValueError(message)
    return normalized
