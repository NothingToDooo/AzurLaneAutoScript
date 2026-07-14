from dataclasses import dataclass
from enum import StrEnum

from module.content.battle_policy import BossStrategy


class HardModeEquipmentCleanup(StrEnum):
    KEEP = "keep"
    TAKE_OFF_WHEN_FINISHED = "take_off_when_finished"


@dataclass(frozen=True, slots=True)
class HardModeRuntimePolicy:
    boss_strategy: BossStrategy
    equipment_cleanup: HardModeEquipmentCleanup

    def __post_init__(self) -> None:
        if not isinstance(self.boss_strategy, BossStrategy):
            message = "hard-mode boss strategy must be a BossStrategy"
            raise TypeError(message)
        if not isinstance(self.equipment_cleanup, HardModeEquipmentCleanup):
            message = "hard-mode equipment cleanup must be a HardModeEquipmentCleanup"
            raise TypeError(message)
