from dataclasses import dataclass
from enum import StrEnum

from module.gameplay.validation import validate_bool


class EmotionMode(StrEnum):
    CALCULATE = "calculate"
    IGNORE = "ignore"
    CALCULATE_IGNORE = "calculate_ignore"


class EmotionControl(StrEnum):
    KEEP_EXP_BONUS = "keep_exp_bonus"
    PREVENT_GREEN_FACE = "prevent_green_face"
    PREVENT_YELLOW_FACE = "prevent_yellow_face"
    PREVENT_RED_FACE = "prevent_red_face"


class EmotionRecoverLocation(StrEnum):
    NOT_IN_DORMITORY = "not_in_dormitory"
    DORMITORY_FLOOR_1 = "dormitory_floor_1"
    DORMITORY_FLOOR_2 = "dormitory_floor_2"


@dataclass(frozen=True, slots=True)
class FleetEmotionSettings:
    control: EmotionControl
    recover: EmotionRecoverLocation
    oath: bool

    def __post_init__(self) -> None:
        if not isinstance(self.control, EmotionControl):
            message = "control must be an EmotionControl"
            raise TypeError(message)
        if not isinstance(self.recover, EmotionRecoverLocation):
            message = "recover must be an EmotionRecoverLocation"
            raise TypeError(message)
        validate_bool(value=self.oath, field_name="oath")


@dataclass(frozen=True, slots=True)
class EmotionSettings:
    mode: EmotionMode
    fleet1: FleetEmotionSettings
    fleet2: FleetEmotionSettings

    def __post_init__(self) -> None:
        if not isinstance(self.mode, EmotionMode):
            message = "mode must be an EmotionMode"
            raise TypeError(message)
        if not isinstance(self.fleet1, FleetEmotionSettings):
            message = "fleet1 must be FleetEmotionSettings"
            raise TypeError(message)
        if not isinstance(self.fleet2, FleetEmotionSettings):
            message = "fleet2 must be FleetEmotionSettings"
            raise TypeError(message)
