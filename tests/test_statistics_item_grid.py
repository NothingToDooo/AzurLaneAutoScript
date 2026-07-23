from typing import TYPE_CHECKING

import numpy as np

from module.base.button import Button
from module.statistics.item import Item, ItemGrid, ItemPredictOptions

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from module.base.type_alias import Area, ImageArray


_LABEL_CODE = {"a": 1, "b": 2, "c": 3}
_NAME_BY_CODE = {1: "Oil_2", 2: "Coin", 3: "Gear"}
SCREEN = np.full((4, 4, 3), 255, dtype=np.uint8)


def _item_image(label: str) -> ImageArray:
    return np.full((4, 4, 3), _LABEL_CODE[label], dtype=np.uint8)


class FakeItem(Item):
    def __init__(self, label: str) -> None:
        self.label = label
        self.image = _item_image(label)
        self.image_raw = self.image
        self._button = Button(area=(0, 0, 4, 4), color=(), button=(0, 0, 4, 4), name=label)
        self.is_valid = True
        self._name = "DefaultItem"
        self.amount = 1
        self._cost = "DefaultCost"
        self.price = 0
        self.tag: str | None = None
        self.group: str | None = None
        self.sub_genre: str | None = None
        self.tier: str | None = None

    def crop(self, area: Area) -> ImageArray:
        del area
        return self.image


class FakeItemGrid(ItemGrid[FakeItem]):
    def __init__(
        self,
        items: Iterable[FakeItem],
        costs: Mapping[str, str | None],
        prices: list[int],
    ) -> None:
        self.source_items = list(items)
        self.items: list[FakeItem] = []
        self.names = _NAME_BY_CODE
        self.costs = costs
        self.prices = prices
        self.amount_area: Area = (0, 0, 4, 4)
        self.price_area: Area = (0, 0, 4, 4)
        self.tag_area: Area = (0, 0, 4, 4)

    def _load_image(self, image: ImageArray) -> None:
        assert np.array_equal(image, SCREEN)
        self.items = list(self.source_items)

    def match_template(self, image: ImageArray, similarity: float | None = None) -> str:
        assert similarity is None
        return self.names[int(image[0, 0, 0])]

    def match_cost_template(self, item: FakeItem) -> str | None:
        return self.costs[item.label]

    @staticmethod
    def predict_tag(image: ImageArray) -> str | None:
        code = int(image[0, 0, 0])
        label = next(label for label, value in _LABEL_CODE.items() if value == code)
        return f"tag-{label}"

    def _predict_amounts(self) -> None:
        for item, amount in zip(self.items, (11, 22, 33), strict=False):
            item.amount = amount

    def _predict_prices(self) -> None:
        for item, price in zip(self.items, self.prices, strict=False):
            item.price = price


def test_item_grid_predict_runs_enabled_stages_and_filters_invalid_price() -> None:
    items = [FakeItem("a"), FakeItem("b"), FakeItem("c")]
    grid = FakeItemGrid(items, costs={"a": "Gem", "b": None, "c": "Coin"}, prices=[5, 0])

    result = grid.predict(SCREEN, options=ItemPredictOptions(cost=True, price=True, tag=True))

    assert result == [items[0]]
    assert items[0].name == "Oil"
    assert items[0].amount == 11
    assert items[0].cost == "Gem"
    assert items[0].price == 5
    assert items[0].tag == "tag-a"


def test_item_grid_predict_keeps_disabled_stages_untouched() -> None:
    item = FakeItem("a")
    grid = FakeItemGrid([item], costs={"a": "Gem"}, prices=[5])

    result = grid.predict(SCREEN, name=False, amount=False, cost=False, price=False, tag=False)

    assert result == [item]
    assert item.name == "DefaultItem"
    assert item.amount == 1
    assert item.cost == "DefaultCost"
    assert item.price == 0
    assert item.tag is None
