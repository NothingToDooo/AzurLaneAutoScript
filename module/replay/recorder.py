from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from module.base.utils import save_image
from module.replay.trace import RecordedAction, ReplayFrame, write_trace

if TYPE_CHECKING:
    from module.base.type_alias import ImageArray


@dataclass(slots=True)
class _CapturedFrame:
    captured_at: datetime
    image: ImageArray
    actions: list[RecordedAction] = field(default_factory=list)
    unsupported_actions: set[str] = field(default_factory=set)

    @property
    def can_be_replaced(self) -> bool:
        return not self.actions and not self.unsupported_actions


@dataclass(frozen=True, slots=True)
class ReplayDumpResult:
    image_paths: tuple[Path, ...]
    trace_path: Path | None
    blockers: tuple[str, ...]


class ReplayRecorder:
    """在内存中保留最近的业务截图，并把语义动作绑定到动作前截图。"""

    def __init__(self, max_frames: int) -> None:
        if max_frames < 1:
            message = "max_frames must be at least 1"
            raise ValueError(message)
        self._frames: deque[_CapturedFrame] = deque(maxlen=max_frames)
        self._unbound_actions: set[str] = set()

    def record_frame(self, image: ImageArray, *, captured_at: datetime | None = None) -> None:
        frame = _CapturedFrame(
            captured_at=captured_at or datetime.now(),
            image=image.copy(),
        )
        if self._frames and self._frames[-1].can_be_replaced:
            self._frames[-1] = frame
        else:
            self._frames.append(frame)

    def record_action(self, action: RecordedAction) -> None:
        if not self._frames:
            self._unbound_actions.add(type(action).__name__)
            return
        self._frames[-1].actions.append(action)

    def mark_unsupported_action(self, action: str) -> None:
        if not self._frames:
            self._unbound_actions.add(action)
            return
        self._frames[-1].unsupported_actions.add(action)

    def clear(self) -> None:
        self._frames.clear()
        self._unbound_actions.clear()

    def dump(self, directory: Path) -> ReplayDumpResult:
        """先写截图、最后发布 trace；trace 缺失表示当前记录不可完整回放。"""
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        frames = tuple(self._frames)
        blockers = set(self._unbound_actions)
        blockers.update(action for frame in frames for action in frame.unsupported_actions)

        image_paths: list[Path] = []
        replay_frames: list[ReplayFrame] = []
        for index, frame in enumerate(frames):
            filename = f"frame-{index:03d}_{frame.captured_at:%Y-%m-%d_%H-%M-%S-%f}.png"
            image_path = directory / filename
            save_image(frame.image, image_path)
            image_paths.append(image_path)
            replay_frames.append(ReplayFrame(image_path=Path(filename), expected_actions=tuple(frame.actions)))

        trace_path: Path | None = None
        if replay_frames and not blockers:
            trace_path = directory / "trace.json"
            write_trace(trace_path, tuple(replay_frames))

        return ReplayDumpResult(
            image_paths=tuple(image_paths),
            trace_path=trace_path,
            blockers=tuple(sorted(blockers)),
        )
