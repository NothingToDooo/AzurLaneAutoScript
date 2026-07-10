import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Final, cast

TRACE_VERSION: Final = 1


@dataclass(frozen=True, slots=True)
class ClickAction:
    target: str

    def __post_init__(self) -> None:
        if not self.target.strip():
            message = "click target must not be empty or whitespace"
            raise ValueError(message)


@dataclass(frozen=True, slots=True)
class SwipeAction:
    start: tuple[int, int]
    end: tuple[int, int]

    def __post_init__(self) -> None:
        object.__setattr__(self, "start", _normalize_point(self.start, field_name="start"))
        object.__setattr__(self, "end", _normalize_point(self.end, field_name="end"))


type RecordedAction = ClickAction | SwipeAction


@dataclass(frozen=True, slots=True)
class ReplayFrame:
    image_path: Path
    expected_actions: tuple[RecordedAction, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "image_path", Path(self.image_path))
        object.__setattr__(self, "expected_actions", tuple(self.expected_actions))


def write_trace(trace_path: Path, frames: tuple[ReplayFrame, ...]) -> None:
    trace_path = Path(trace_path)
    payload = {
        "version": TRACE_VERSION,
        "frames": [
            {
                "image_path": _portable_image_path(frame.image_path, trace_path),
                "expected_actions": [_serialize_action(action) for action in frame.expected_actions],
            }
            for frame in frames
        ],
    }
    serialized = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    trace_path.write_text(serialized, encoding="utf-8", newline="\n")


def read_trace(trace_path: Path) -> tuple[ReplayFrame, ...]:
    trace_path = Path(trace_path)
    payload: object = json.loads(trace_path.read_text(encoding="utf-8"))
    root = _require_mapping(payload, location="trace")
    version = root.get("version")
    if version != TRACE_VERSION:
        message = f"unsupported replay trace version: {version!r}"
        raise ValueError(message)
    raw_frames = root.get("frames")
    if not isinstance(raw_frames, list):
        message = "trace.frames must be a list"
        raise TypeError(message)
    return tuple(_parse_frame(raw_frame, trace_path, index) for index, raw_frame in enumerate(raw_frames))


def _normalize_point(point: tuple[int, int], *, field_name: str) -> tuple[int, int]:
    if len(point) != 2:
        message = f"{field_name} must contain exactly two coordinates"
        raise ValueError(message)
    try:
        return int(point[0]), int(point[1])
    except (TypeError, ValueError) as error:
        message = f"{field_name} coordinates must be integers"
        raise ValueError(message) from error


def _portable_image_path(image_path: Path, trace_path: Path) -> str:
    if not image_path.is_absolute():
        return image_path.as_posix()
    try:
        relative_path = Path(os.path.relpath(image_path.resolve(), trace_path.parent.resolve()))
    except ValueError:
        return image_path.as_posix()
    return relative_path.as_posix()


def _serialize_action(action: RecordedAction) -> dict[str, object]:
    if isinstance(action, ClickAction):
        return {"type": "click", "target": action.target}
    if isinstance(action, SwipeAction):
        return {"type": "swipe", "start": list(action.start), "end": list(action.end)}
    message = f"unsupported recorded action: {type(action).__name__}"
    raise TypeError(message)


def _require_mapping(value: object, *, location: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        message = f"{location} must be an object with string keys"
        raise ValueError(message)
    return cast("dict[str, object]", value)


def _parse_frame(value: object, trace_path: Path, index: int) -> ReplayFrame:
    frame = _require_mapping(value, location=f"trace.frames[{index}]")
    raw_image_path = frame.get("image_path")
    if not isinstance(raw_image_path, str) or not raw_image_path:
        message = f"trace.frames[{index}].image_path must be a non-empty string"
        raise ValueError(message)
    image_path = Path(raw_image_path)
    if not image_path.is_absolute():
        image_path = (trace_path.parent / image_path).resolve()

    raw_actions = frame.get("expected_actions")
    if not isinstance(raw_actions, list):
        message = f"trace.frames[{index}].expected_actions must be a list"
        raise TypeError(message)
    actions = tuple(_parse_action(action, index, action_index) for action_index, action in enumerate(raw_actions))
    return ReplayFrame(image_path=image_path, expected_actions=actions)


def _parse_action(value: object, frame_index: int, action_index: int) -> RecordedAction:
    location = f"trace.frames[{frame_index}].expected_actions[{action_index}]"
    action = _require_mapping(value, location=location)
    action_type = action.get("type")
    if action_type == "click":
        target = action.get("target")
        if not isinstance(target, str):
            message = f"{location}.target must be a string"
            raise ValueError(message)
        return ClickAction(target=target)
    if action_type == "swipe":
        return SwipeAction(
            start=_parse_json_point(action.get("start"), location=f"{location}.start"),
            end=_parse_json_point(action.get("end"), location=f"{location}.end"),
        )
    message = f"{location}.type must be 'click' or 'swipe'"
    raise ValueError(message)


def _parse_json_point(value: object, *, location: str) -> tuple[int, int]:
    if (
        not isinstance(value, list)
        or len(value) != 2
        or not all(isinstance(coordinate, int) and not isinstance(coordinate, bool) for coordinate in value)
    ):
        message = f"{location} must contain exactly two integers"
        raise ValueError(message)
    coordinates = cast("list[int]", value)
    return coordinates[0], coordinates[1]
