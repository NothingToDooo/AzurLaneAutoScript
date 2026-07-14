from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING

from module.gameplay.market import (
    AwakenLevelCap,
    AwakenPlan,
    AwakenSettings,
    AwakenTask,
    CoreShopPlan,
    GachaPlan,
    GachaPool,
    GachaSettings,
    GachaTask,
    GeneralShopPlan,
    GuildShopPlan,
    MedalShopPlan,
    MeritShopPlan,
    ShipyardPlan,
    ShipyardPurchasePlan,
    ShipyardSettings,
    ShipyardTask,
    ShopFrequentSettings,
    ShopFrequentTask,
    ShopOncePlan,
    ShopOnceSettings,
    ShopOnceTask,
)
from module.runtime import SettingsDecoder, TypedTaskFactory

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


def _awaken_settings(decoder: SettingsDecoder) -> AwakenSettings:
    plan = decoder.object("plan")
    settings = AwakenSettings(
        plan=AwakenPlan(
            level_cap=plan.enum("level_cap", AwakenLevelCap),
            favourite_only=plan.boolean("favourite_only"),
        ),
        schedule=decoder.daily_schedule("schedule"),
    )
    plan.finish()
    return settings


def _purchase_plan(decoder: SettingsDecoder) -> ShipyardPurchasePlan:
    plan = ShipyardPurchasePlan(
        research_series=decoder.integer("research_series", minimum=1),
        ship_index=decoder.integer("ship_index", minimum=0),
        buy_amount=decoder.integer("buy_amount", minimum=0),
    )
    decoder.finish()
    return plan


def _shipyard_settings(decoder: SettingsDecoder) -> ShipyardSettings:
    plan = decoder.object("plan")
    pr = plan.object("pr")
    dr = plan.object("dr")
    settings = ShipyardSettings(
        plan=ShipyardPlan(pr=_purchase_plan(pr), dr=_purchase_plan(dr)),
        schedule=decoder.daily_schedule("schedule"),
    )
    plan.finish()
    return settings


def _gacha_settings(decoder: SettingsDecoder) -> GachaSettings:
    plan = decoder.object("plan")
    settings = GachaSettings(
        plan=GachaPlan(
            pool=plan.enum("pool", GachaPool),
            amount=plan.integer("amount", minimum=1),
            use_ticket=plan.boolean("use_ticket"),
            use_drill=plan.boolean("use_drill"),
        ),
        schedule=decoder.daily_schedule("schedule"),
    )
    plan.finish()
    return settings


def _shop_frequent_settings(decoder: SettingsDecoder) -> ShopFrequentSettings:
    plan = decoder.object("plan")
    settings = ShopFrequentSettings(
        plan=GeneralShopPlan(
            filter=plan.nullable_string("filter"),
            refresh=plan.boolean("refresh"),
            use_gems=plan.boolean("use_gems"),
            consume_coins=plan.boolean("consume_coins"),
            buy_skin_box=plan.boolean("buy_skin_box"),
        ),
        schedule=decoder.daily_schedule("schedule"),
    )
    plan.finish()
    return settings


def _shop_once_settings(decoder: SettingsDecoder) -> ShopOnceSettings:
    plan = decoder.object("plan")
    merit = plan.object("merit")
    guild = plan.object("guild")
    core = plan.object("core")
    medal = plan.object("medal")
    settings = ShopOnceSettings(
        plan=ShopOncePlan(
            merit=MeritShopPlan(
                filter=merit.nullable_string("filter"),
                refresh=merit.boolean("refresh"),
            ),
            guild=GuildShopPlan(
                filter=guild.nullable_string("filter"),
                refresh=guild.boolean("refresh"),
                box_t3=guild.string("box_t3"),
                box_t4=guild.string("box_t4"),
                book_t2=guild.string("book_t2"),
                book_t3=guild.string("book_t3"),
                retrofit_t2=guild.string("retrofit_t2"),
                retrofit_t3=guild.string("retrofit_t3"),
                plate_t2=guild.string("plate_t2"),
                plate_t3=guild.string("plate_t3"),
                plate_t4=guild.string("plate_t4"),
                pr1=guild.string("pr1"),
                pr2=guild.string("pr2"),
                pr3=guild.string("pr3"),
            ),
            core=CoreShopPlan(filter=core.nullable_string("filter")),
            medal=MedalShopPlan(
                filter=medal.nullable_string("filter"),
                retrofit_t1=medal.string("retrofit_t1"),
                retrofit_t2=medal.string("retrofit_t2"),
                retrofit_t3=medal.string("retrofit_t3"),
                plate_t1=medal.string("plate_t1"),
                plate_t2=medal.string("plate_t2"),
                plate_t3=medal.string("plate_t3"),
            ),
        ),
        schedule=decoder.daily_schedule("schedule"),
    )
    merit.finish()
    guild.finish()
    core.finish()
    medal.finish()
    plan.finish()
    return settings


def build_market_factories(workflows: MarketWorkflows) -> Mapping[str, TaskFactory]:
    if not isinstance(workflows, MarketWorkflows):
        message = "workflows must be MarketWorkflows"
        raise TypeError(message)
    factories: dict[str, TaskFactory] = {
        "awaken": TypedTaskFactory(_awaken_settings, lambda settings: AwakenTask(workflows.awaken, settings)),
        "shipyard": TypedTaskFactory(
            _shipyard_settings,
            lambda settings: ShipyardTask(workflows.shipyard, settings),
        ),
        "gacha": TypedTaskFactory(_gacha_settings, lambda settings: GachaTask(workflows.gacha, settings)),
        "shop_frequent": TypedTaskFactory(
            _shop_frequent_settings,
            lambda settings: ShopFrequentTask(workflows.shop_frequent, settings),
        ),
        "shop_once": TypedTaskFactory(
            _shop_once_settings,
            lambda settings: ShopOnceTask(workflows.shop_once, settings),
        ),
    }
    return MappingProxyType(factories)
