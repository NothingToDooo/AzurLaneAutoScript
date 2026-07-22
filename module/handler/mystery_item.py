from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol, override

from module.base.utils import area_cross_area
from module.combat.assets import GET_ITEMS_1
from module.handler.assets import MYSTERY_ITEM
from module.logger import logger

if TYPE_CHECKING:
    from module.base.button import Button, MatchOffset
    from module.config.config import AzurLaneConfig
    from module.device.device import Device
    from module.map_detection.grid import Grid


@dataclass(frozen=True, slots=True)
class MysteryItemRequest:
    button: Grid | None = None


@dataclass(frozen=True, slots=True)
class MysteryItemOutcome:
    handled: bool
    counts_toward_mystery: bool

    def __post_init__(self) -> None:
        if type(self.handled) is not bool or type(self.counts_toward_mystery) is not bool:
            message = "mystery item outcome flags must be booleans"
            raise TypeError(message)
        if self.counts_toward_mystery and not self.handled:
            message = "unhandled mystery item outcome cannot count toward mystery"
            raise ValueError(message)


class MysteryKind(StrEnum):
    GET_ITEM = "get_item"
    GET_AMMO = "get_ammo"
    GET_CARRIER = "get_carrier"


@dataclass(frozen=True, slots=True)
class MysteryResult:
    kind: MysteryKind
    counts_toward_mystery: bool

    def __post_init__(self) -> None:
        if not isinstance(self.kind, MysteryKind):
            message = "mystery result kind must be a MysteryKind"
            raise TypeError(message)
        if type(self.counts_toward_mystery) is not bool:
            message = "mystery result count flag must be a boolean"
            raise TypeError(message)


class MysteryItemRuntime(Protocol):
    config: AzurLaneConfig
    device: Device

    def appear(
        self,
        button: Button,
        offset: MatchOffset | None = 0,
        interval: float = 0,
        similarity: float = 0.85,
        threshold: int = 10,
    ) -> bool: ...

    def strategy_close(self, *, skip_first_screenshot: bool = True) -> None: ...


class MysteryItemService(Protocol):
    def handle(
        self,
        runtime: MysteryItemRuntime,
        request: MysteryItemRequest,
    ) -> MysteryItemOutcome: ...


class _StandardMysteryItemService(MysteryItemService):
    @override
    def handle(
        self,
        runtime: MysteryItemRuntime,
        request: MysteryItemRequest,
    ) -> MysteryItemOutcome:
        button = request.button
        if (
            not runtime.config.MAP_MYSTERY_MAP_CLICK
            or button is None
            or area_cross_area(button.button, MYSTERY_ITEM.area, threshold=5)
        ):
            click_target = MYSTERY_ITEM
        else:
            click_target = button

        if not runtime.appear(GET_ITEMS_1, offset=5):
            return MysteryItemOutcome(handled=False, counts_toward_mystery=False)

        logger.attr("Mystery", "Get item")
        runtime.device.click(click_target)
        runtime.device.sleep(0.5)
        runtime.device.screenshot()
        runtime.strategy_close()
        return MysteryItemOutcome(handled=True, counts_toward_mystery=True)


STANDARD_MYSTERY_ITEM_SERVICE: MysteryItemService = _StandardMysteryItemService()
