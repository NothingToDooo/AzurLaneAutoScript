import re
from typing import TYPE_CHECKING

from module.base.filter import Filter
from module.config.config_generated import GeneratedConfig
from module.os_shop.preset import OS_SHOP

if TYPE_CHECKING:
    from module.config.config import AzurLaneConfig
    from module.os_shop.item import OSShopItem as Item

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
FILTER = Filter(FILTER_REGEX, FILTER_ATTR)


class Selector:
    if TYPE_CHECKING:
        config: AzurLaneConfig
        _shop_yellow_coins: int
        _shop_purple_coins: int

        @property
        def is_cl1_enabled(self) -> bool: ...

    def pretreatment(self, items) -> list[Item]:
        """
        Pretreatment items.

        Args:
            items:

        Returns:
            list[Item]:
        """
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

    def enough_coins_in_akashi(self, item) -> bool:
        """返回明石商店货币是否足够购买物品。"""
        return (item.cost == "YellowCoins" and item.price <= self._shop_yellow_coins) or (
            item.cost == "PurpleCoins" and item.price <= self._shop_purple_coins
        )

    def check_cl1_purple_coins(self, item) -> bool:
        """
        Check if cl1 is enable and item name is PurpleCoins.

        Args:
            item:

        Returns:
            bool: False if cl1 is enable and item name is PurpleCoins.
        """
        return not (self.is_cl1_enabled and item.name == "PurpleCoins")

    def check_item_count(self, item) -> bool:
        """
        Check if the item has a valid count.

        Args:
            item: Irem.

        Returns:
            bool: True if the item has at least one count, the total count is at least one,
                  and the current count does not exceed the total count. False otherwise.
        """
        return item.count >= 1 and item.total_count >= 1 and item.count <= item.total_count

    def items_filter_in_akashi_shop(self, items) -> list[Item]:
        """
        Returns items that can be bought.

        Args:
            items: Irems to be filtered.

        Returns:
            list[Item]:
        """
        items = self.pretreatment(items)
        parser = self.config.OpsiGeneral_AkashiShopFilter
        if not parser.strip():
            parser = GeneratedConfig.OpsiGeneral_AkashiShopFilter
        FILTER.load(parser)
        return FILTER.applys(items, funcs=[self.check_cl1_purple_coins, self.enough_coins_in_akashi])

    def items_filter_in_os_shop(self, items) -> list[Item]:
        """
        Returns items that can be bought.

        Args:
            items: Items to be filtered.

        Returns:
            list[Item]:
        """
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
        return FILTER.applys(items, funcs=[self.check_cl1_purple_coins, self.check_item_count])
