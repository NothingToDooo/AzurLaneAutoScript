from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, Protocol

from module.content.errors import ContentValidationError

type BattlePolicyName = Literal[
    "siren_then_filtered_enemy",
    "filtered_enemy_then_default",
    "fleet_boss",
]


class _FleetBoss(Protocol):
    def clear_boss(self) -> object: ...


class _BattleCampaign(Protocol):
    ENEMY_FILTER: str
    fleet_boss: _FleetBoss

    def clear_siren(self) -> object: ...

    def clear_filter_enemy(self, enemy_filter: str, *, preserve: int) -> object: ...

    def battle_default(self) -> object: ...


type BattleMethod = Callable[[_BattleCampaign], object]

_FILTERED_POLICIES = {"siren_then_filtered_enemy", "filtered_enemy_then_default"}
_POLICY_NAMES = (*_FILTERED_POLICIES, "fleet_boss")


@dataclass(frozen=True, slots=True)
class BattlePolicy:
    name: BattlePolicyName
    preserve: int | None = None

    def __post_init__(self) -> None:
        if self.name not in _POLICY_NAMES:
            message = f"unknown battle policy: {self.name!r}"
            raise ContentValidationError(message)
        if self.name in _FILTERED_POLICIES:
            if type(self.preserve) is not int or self.preserve < 0:
                message = f"battle policy {self.name} preserve must be a non-negative integer"
                raise ContentValidationError(message)
        elif self.preserve is not None:
            message = f"battle policy {self.name} does not accept preserve"
            raise ContentValidationError(message)

    def execute(self, campaign: _BattleCampaign) -> object:
        if self.name == "fleet_boss":
            return campaign.fleet_boss.clear_boss()
        if self.name == "siren_then_filtered_enemy" and campaign.clear_siren():
            return True
        if campaign.clear_filter_enemy(campaign.ENEMY_FILTER, preserve=self._required_preserve()):
            return True
        return campaign.battle_default()

    def as_method(self) -> BattleMethod:
        policy = self

        def battle(campaign: _BattleCampaign) -> object:
            return policy.execute(campaign)

        return battle

    def _required_preserve(self) -> int:
        preserve = self.preserve
        if preserve is None:
            message = f"battle policy {self.name} requires preserve"
            raise RuntimeError(message)
        return preserve
