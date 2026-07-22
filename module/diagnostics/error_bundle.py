import json
import re
import traceback
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from module.base.atomic import atomic_write
from module.base.utils import save_image

if TYPE_CHECKING:
    from module.base.type_alias import ImageArray


_LOG_TAIL_LINES = 2_000
_SAFE_COMPONENT_PATTERN = re.compile(r"[^A-Za-z0-9_.-]+")


def _validate_aware_datetime(value: datetime, *, field_name: str) -> None:
    if not isinstance(value, datetime):
        message = f"{field_name} must be a datetime"
        raise TypeError(message)
    if value.utcoffset() is None:
        message = f"{field_name} must be timezone-aware"
        raise ValueError(message)


def _validate_text(value: str, *, field_name: str) -> None:
    if not isinstance(value, str):
        message = f"{field_name} must be a string"
        raise TypeError(message)
    if not value or value != value.strip() or "\r" in value or "\n" in value:
        message = f"{field_name} must be trimmed, non-empty, single-line text"
        raise ValueError(message)


@dataclass(frozen=True, slots=True)
class CapturedScreenshot:
    captured_at: datetime
    image: ImageArray

    def __post_init__(self) -> None:
        _validate_aware_datetime(self.captured_at, field_name="captured_at")
        if not isinstance(self.image, np.ndarray):
            message = "image must be a NumPy array"
            raise TypeError(message)


@dataclass(frozen=True, slots=True)
class ErrorBundleContext:
    command: str
    occurred_at: datetime
    task_id: str | None = None

    def __post_init__(self) -> None:
        _validate_text(self.command, field_name="command")
        _validate_aware_datetime(self.occurred_at, field_name="occurred_at")
        if self.task_id is not None:
            _validate_text(self.task_id, field_name="task_id")


class ScreenshotHistory:
    """在进程内保留最近的有效游戏截图。"""

    __slots__ = ("_frames",)

    def __init__(self, max_frames: int) -> None:
        if type(max_frames) is not int or max_frames < 1:
            message = "max_frames must be a positive integer"
            raise ValueError(message)
        self._frames: deque[CapturedScreenshot] = deque(maxlen=max_frames)

    def record(self, image: ImageArray, *, captured_at: datetime | None = None) -> None:
        if not isinstance(image, np.ndarray):
            message = "image must be a NumPy array"
            raise TypeError(message)
        timestamp = datetime.now().astimezone() if captured_at is None else captured_at
        _validate_aware_datetime(timestamp, field_name="captured_at")
        self._frames.append(CapturedScreenshot(captured_at=timestamp, image=image.copy()))

    def clear(self) -> None:
        self._frames.clear()

    def snapshot(self) -> tuple[CapturedScreenshot, ...]:
        return tuple(
            CapturedScreenshot(captured_at=frame.captured_at, image=frame.image.copy()) for frame in self._frames
        )


def _safe_component(value: str) -> str:
    normalized = _SAFE_COMPONENT_PATTERN.sub("_", value).strip("._")
    return normalized or "unknown"


def _create_bundle_directory(root: Path, context: ErrorBundleContext) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    timestamp = context.occurred_at.strftime("%Y%m%d-%H%M%S-%f")
    task = context.task_id or context.command
    stem = f"{timestamp}_{_safe_component(task)}"
    for collision in range(1_000):
        name = stem if collision == 0 else f"{stem}-{collision}"
        directory = root / name
        try:
            directory.mkdir()
        except FileExistsError:
            continue
        return directory
    message = f"unable to reserve an error bundle directory for {stem!r}"
    raise FileExistsError(message)


def _log_tail(log_file: Path | None) -> str:
    if log_file is None:
        return ""
    try:
        text = Path(log_file).read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return ""
    lines = text.splitlines()
    if not lines:
        return ""
    return "\n".join(lines[-_LOG_TAIL_LINES:]) + "\n"


def write_error_bundle(
    context: ErrorBundleContext,
    error: BaseException,
    screenshots: tuple[CapturedScreenshot, ...],
    *,
    log_file: Path | None,
    root: Path,
) -> Path:
    """落盘最小故障现场；调用方决定旁路失败是否影响原异常。"""

    if not isinstance(context, ErrorBundleContext):
        message = "context must be an ErrorBundleContext"
        raise TypeError(message)
    if not isinstance(error, BaseException):
        message = "error must be a BaseException"
        raise TypeError(message)
    if not isinstance(screenshots, tuple) or any(not isinstance(frame, CapturedScreenshot) for frame in screenshots):
        message = "screenshots must be a tuple of CapturedScreenshot values"
        raise TypeError(message)
    if log_file is not None and not isinstance(log_file, Path):
        message = "log_file must be a Path or None"
        raise TypeError(message)
    if not isinstance(root, Path):
        message = "root must be a Path"
        raise TypeError(message)

    directory = _create_bundle_directory(root, context)
    screenshot_directory = directory / "screenshots"
    screenshot_directory.mkdir()

    image_paths: list[str] = []
    for index, frame in enumerate(screenshots):
        timestamp = frame.captured_at.strftime("%Y%m%d-%H%M%S-%f")
        relative_path = Path("screenshots") / f"{index:03d}_{timestamp}.png"
        save_image(frame.image, directory / relative_path)
        image_paths.append(relative_path.as_posix())

    atomic_write(directory / "log.txt", _log_tail(log_file))
    metadata = {
        "timestamp": context.occurred_at.isoformat(),
        "command": context.command,
        "task": context.task_id,
        "exception_type": type(error).__name__,
        "message": str(error),
        "traceback": "".join(traceback.format_exception(error)),
        "screenshots": image_paths,
    }
    atomic_write(directory / "error.json", json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")
    return directory
