from typing import TYPE_CHECKING, cast

import pytest

from module.adapters.mumu12 import (
    CancellationAwareMumu12Device,
    activate_mumu12_task,
    emotion_runtime_overlay,
)
from module.application import AbortRequested, AbortToken
from module.gameplay.emotion import (
    EmotionControl,
    EmotionMode,
    EmotionRecoverLocation,
    EmotionSettings,
    FleetEmotionSettings,
)

if TYPE_CHECKING:
    from module.config.config import AzurLaneConfig, Function
    from module.device.device import Device


class _Config:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.task: Function

    def replace_runtime_overlay(self) -> None:
        self.calls.append(("replace", None))

    def bind(self, task: Function) -> None:
        self.calls.append(("bind", task.command))

    def apply_runtime_overlay(self, **values: object) -> None:
        self.calls.append(("overlay", values))


class _Device:
    def __init__(self) -> None:
        self.config: object | None = None


def test_emotion_runtime_overlay_projects_the_shared_value_object() -> None:
    settings = EmotionSettings(
        mode=EmotionMode.CALCULATE_IGNORE,
        fleet1=FleetEmotionSettings(
            control=EmotionControl.PREVENT_GREEN_FACE,
            recover=EmotionRecoverLocation.NOT_IN_DORMITORY,
            oath=False,
        ),
        fleet2=FleetEmotionSettings(
            control=EmotionControl.KEEP_EXP_BONUS,
            recover=EmotionRecoverLocation.DORMITORY_FLOOR_2,
            oath=True,
        ),
    )

    assert emotion_runtime_overlay(settings) == {
        "Emotion_Mode": "calculate_ignore",
        "Emotion_Fleet1Control": "prevent_green_face",
        "Emotion_Fleet1Recover": "not_in_dormitory",
        "Emotion_Fleet1Oath": False,
        "Emotion_Fleet2Control": "keep_exp_bonus",
        "Emotion_Fleet2Recover": "dormitory_floor_2",
        "Emotion_Fleet2Oath": True,
    }


def test_activate_mumu12_task_binds_overlay_before_exposing_device() -> None:
    config = _Config()
    device = _Device()

    activated = activate_mumu12_task(
        cast("AzurLaneConfig", config),
        cast("Device", device),
        "Event",
        {"Campaign_Name": "d3"},
        AbortToken(),
    )

    assert config.task.command == "Event"
    assert config.calls == [
        ("replace", None),
        ("bind", "Event"),
        ("overlay", {"Campaign_Name": "d3"}),
    ]
    assert device.config is config
    assert isinstance(activated, CancellationAwareMumu12Device)


def test_activate_mumu12_task_honors_cancellation_before_mutating_runtime() -> None:
    config = _Config()
    device = _Device()
    cancellation = AbortToken()
    cancellation.request("stop")

    with pytest.raises(AbortRequested, match="stop"):
        activate_mumu12_task(
            cast("AzurLaneConfig", config),
            cast("Device", device),
            "Event",
            {},
            cancellation,
        )

    assert config.calls == []
    assert device.config is None
