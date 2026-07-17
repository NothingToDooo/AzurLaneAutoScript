from typing import TYPE_CHECKING, cast

from module.config.config import name_to_function
from module.gameplay.emotion import EmotionSettings

if TYPE_CHECKING:
    from collections.abc import Mapping

    from module.application import CancellationSource
    from module.config.config import AzurLaneConfig
    from module.config.config_generated import ConfigOverrides
    from module.device.device import Device


class CancellationAwareMumu12Device:
    """为现有 MuMu12 UI primitive 的每个公开 I/O 调用增加取消检查。"""

    __slots__ = ("_cancellation", "_target")

    _cancellation: CancellationSource
    _target: object

    def __init__(self, target: object, cancellation: CancellationSource) -> None:
        if isinstance(cancellation, type) or not callable(getattr(cancellation, "raise_if_requested", None)):
            message = "cancellation must implement raise_if_requested()"
            raise TypeError(message)
        object.__setattr__(self, "_target", target)
        object.__setattr__(self, "_cancellation", cancellation)

    def __getattr__(self, name: str) -> object:
        value = getattr(self._target, name)
        if not callable(value):
            return value

        def checked(*args: object, **kwargs: object) -> object:
            self._cancellation.raise_if_requested()
            return value(*args, **kwargs)

        return checked

    def __setattr__(self, name: str, value: object) -> None:
        self._cancellation.raise_if_requested()
        setattr(self._target, name, value)


def emotion_runtime_overlay(settings: EmotionSettings) -> ConfigOverrides:
    """把统一的心情设置投影为 MuMu12 旧配置字段。"""

    if not isinstance(settings, EmotionSettings):
        message = "emotion overlay requires EmotionSettings"
        raise TypeError(message)
    values: dict[str, object] = {
        "Emotion_Mode": settings.mode.value,
        "Emotion_Fleet1Control": settings.fleet1.control.value,
        "Emotion_Fleet1Recover": settings.fleet1.recover.value,
        "Emotion_Fleet1Oath": settings.fleet1.oath,
        "Emotion_Fleet2Control": settings.fleet2.control.value,
        "Emotion_Fleet2Recover": settings.fleet2.recover.value,
        "Emotion_Fleet2Oath": settings.fleet2.oath,
    }
    return cast("ConfigOverrides", values)


def activate_mumu12_task(
    config: AzurLaneConfig,
    device: Device,
    task_name: str,
    overlay: Mapping[str, object],
    cancellation: CancellationSource,
) -> Device:
    """绑定任务配置并返回带取消检查的设备门面。"""

    cancellation.raise_if_requested()
    config.replace_runtime_overlay()
    task = name_to_function(task_name)
    config.task = task
    config.bind(task)
    values = cast("ConfigOverrides", dict(overlay))
    config.apply_runtime_overlay(**values)
    device.config = config
    return cast("Device", CancellationAwareMumu12Device(device, cancellation))
