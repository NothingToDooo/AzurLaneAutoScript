import re
from typing import TYPE_CHECKING

from module.base.filter import Filter
from module.config.config_generated import GeneratedConfig
from module.os_shop.item import OSShopItem as Item
from module.os_shop.preset import OS_SHOP

if TYPE_CHECKING:
    from module.config.config import AzurLaneConfig

FILTER_REGEX = re.compile(
    r"^(actionpoint|crystallizedheatresistantsteel|developmentmaterial"
    r"|energystoragedevice|geardesignplan|gearpart|logger|metaredbook"
    r"|nanoceramicalloy|neuroplasticprostheticarm|ordnancetestingreport"
    r"|platerandom|purplecoins|repairpack|supercavitationgenerator|tuningsample"
    r"|tuning)"
    r"(20|50|100|prototype|specialized|abyssal|obscure|full2|full|triple2|triple|2"
    r"|combat|offence|survival)?"
    r"(t[1-6])?$",
    flags=re.IGNORECASE,
)
FILTER_ATTR = ("group", "sub_genre", "tier")
FILTER = Filter[Item](FILTER_REGEX, FILTER_ATTR)
UNEXPECTED_FILTER_PRESET_MESSAGE = "OS shop filter returned a preset token"


class Selector:
    if TYPE_CHECKING:
        config: AzurLaneConfig
        _shop_yellow_coins: int
        _shop_purple_coins: int

        @property
        def is_cl1_enabled(self) -> bool: ...

    @staticmethod
    def pretreatment(items: list[Item]) -> list[Item]:
        matching_items = []
        for item in items:
            item.group, item.sub_genre, item.tier = None, None, None
            result = re.search(FILTER_REGEX, item.name.lower())
            if result:
                item.group, item.sub_genre, item.tier = [
                    group.lower() if group is not None else None for group in result.groups()
                ]
                matching_items.append(item)

        return matching_items

    def enough_coins_in_akashi(self, item: Item) -> bool:
        return (item.cost == "YellowCoins" and item.price <= self._shop_yellow_coins) or (
            item.cost == "PurpleCoins" and item.price <= self._shop_purple_coins
        )

    def check_cl1_purple_coins(self, item: Item) -> bool:
        """启用 CL1 刷图时保留 PurpleCoins，不在商店购买。"""
        return not (self.is_cl1_enabled and item.name == "PurpleCoins")

    @staticmethod
    def check_item_count(item: Item) -> bool:
        """当前和总数量都至少为 1，且当前数量不得超过总数量。"""
        return item.count >= 1 and item.total_count >= 1 and item.count <= item.total_count

    @staticmethod
    def _require_items(filtered: list[Item | str]) -> list[Item]:
        items = [item for item in filtered if isinstance(item, Item)]
        if len(items) != len(filtered):
            raise RuntimeError(UNEXPECTED_FILTER_PRESET_MESSAGE)
        return items

    def items_filter_in_akashi_shop(self, items: list[Item]) -> list[Item]:
        items = self.pretreatment(items)
        parser = self.config.OpsiGeneral_AkashiShopFilter
        if not parser.strip():
            parser = GeneratedConfig.OpsiGeneral_AkashiShopFilter
        FILTER.load(parser)
        filtered = FILTER.applys(items, funcs=[self.check_cl1_purple_coins, self.enough_coins_in_akashi])
        return self._require_items(filtered)

    def items_filter_in_os_shop(self, items: list[Item]) -> list[Item]:
        items = self.pretreatment(items)
        preset = self.config.OpsiShop_PresetFilter
        parser = ""
        if preset == "custom":
            parser = self.config.OpsiShop_CustomFilter
            if not parser.strip():
                parser = OS_SHOP[GeneratedConfig.OpsiShop_PresetFilter]
        else:
            parser = OS_SHOP[preset]
        FILTER.load(parser)
        filtered = FILTER.applys(items, funcs=[self.check_cl1_purple_coins, self.check_item_count])
        return self._require_items(filtered)
