from typing import TYPE_CHECKING

from module.runtime.decoder import SettingsDecoder
from module.runtime.factories import TaskBuildContext

if TYPE_CHECKING:
    from collections.abc import Callable

    from module.application import Task


class TypedTaskFactory[SettingsT]:
    """把严格 JSON decoder 和已绑定 runtime ports 的 Task builder 组合起来。"""

    __slots__ = ("_build_task", "_decode")

    def __init__(
        self,
        decode: Callable[[SettingsDecoder], SettingsT],
        build_task: Callable[[SettingsT], Task],
    ) -> None:
        if isinstance(decode, type) or not callable(decode):
            message = "decode must be callable"
            raise TypeError(message)
        if not callable(build_task):
            message = "build_task must be callable"
            raise TypeError(message)
        self._decode = decode
        self._build_task = build_task

    def build(self, context: TaskBuildContext) -> Task:
        if not isinstance(context, TaskBuildContext):
            message = "context must be a TaskBuildContext"
            raise TypeError(message)
        decoder = SettingsDecoder(context.settings, path=f"$.tasks.{context.spec.command}")
        settings = self._decode(decoder)
        decoder.finish()
        task = self._build_task(settings)
        if isinstance(task, type) or not callable(getattr(task, "run", None)):
            message = "build_task must return a Task"
            raise TypeError(message)
        return task
