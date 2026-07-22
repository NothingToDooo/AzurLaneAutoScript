from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING

from module.gameplay.market import (
    AwakenSettings,
    AwakenTask,
    GachaSettings,
    GachaTask,
    ShipyardSettings,
    ShipyardTask,
    ShopFrequentSettings,
    ShopFrequentTask,
    ShopOnceSettings,
    ShopOnceTask,
)
from module.runtime import ConfiguredTaskFactory

if TYPE_CHECKING:
    from collections.abc import Mapping

    from module.gameplay.market import (
        AwakenWorkflow,
        GachaWorkflow,
        ShipyardWorkflow,
        ShopFrequentWorkflow,
        ShopOnceWorkflow,
    )
    from module.runtime import TaskFactory


def _require_execute(value: object, *, field_name: str) -> None:
    if isinstance(value, type) or not callable(getattr(value, "execute", None)):
        message = f"{field_name} must implement execute()"
        raise TypeError(message)


@dataclass(frozen=True, slots=True)
class MarketWorkflows:
    awaken: AwakenWorkflow
    shipyard: ShipyardWorkflow
    gacha: GachaWorkflow
    shop_frequent: ShopFrequentWorkflow
    shop_once: ShopOnceWorkflow

    def __post_init__(self) -> None:
        for field_name in ("awaken", "shipyard", "gacha", "shop_frequent", "shop_once"):
            _require_execute(getattr(self, field_name), field_name=field_name)


def build_market_factories(workflows: MarketWorkflows) -> Mapping[str, TaskFactory]:
    if not isinstance(workflows, MarketWorkflows):
        message = "workflows must be MarketWorkflows"
        raise TypeError(message)
    factories: dict[str, TaskFactory] = {
        "awaken": ConfiguredTaskFactory(AwakenSettings, lambda settings: AwakenTask(workflows.awaken, settings)),
        "shipyard": ConfiguredTaskFactory(
            ShipyardSettings,
            lambda settings: ShipyardTask(workflows.shipyard, settings),
        ),
        "gacha": ConfiguredTaskFactory(GachaSettings, lambda settings: GachaTask(workflows.gacha, settings)),
        "shop_frequent": ConfiguredTaskFactory(
            ShopFrequentSettings,
            lambda settings: ShopFrequentTask(workflows.shop_frequent, settings),
        ),
        "shop_once": ConfiguredTaskFactory(
            ShopOnceSettings,
            lambda settings: ShopOnceTask(workflows.shop_once, settings),
        ),
    }
    return MappingProxyType(factories)
