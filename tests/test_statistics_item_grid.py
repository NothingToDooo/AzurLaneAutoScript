from typing import TYPE_CHECKING

from module.statistics.item import ItemGrid, ItemGridAreas, ItemPredictOptions, item_grid_areas

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence


class FakeOcr:
    def __init__(self, values: list[int]) -> None:
        self.values = values
        self.images = None

    def ocr_many(self, images: Sequence[str]) -> list[int]:
        self.images = images
        return self.values


class FakeItem:
    def __init__(self, label: str) -> None:
        self.label = label
        self.image = f"image-{label}"
        self.name = "DefaultItem"
        self.amount = 1
        self.cost = "DefaultCost"
        self.price = 0
        self.tag = None

    def crop(self, area: str) -> tuple[str, str]:
        return (self.label, area)


class FakeItemGrid(ItemGrid):
    def __init__(
        self,
        items: Iterable[FakeItem],
        costs: Mapping[str, str | None],
        prices: list[int],
    ) -> None:
        self.source_items = items
        self.items = []
        self.costs = costs
        self.amount_area = "amount_area"
        self.price_area = "price_area"
        self.tag_area = "tag_area"
        self.amount_ocr = FakeOcr([11, 22, 33])
        self.price_ocr = FakeOcr(prices)

    def _load_image(self, image: str) -> None:
        assert image == "screen"
        self.items = list(self.source_items)

    @staticmethod
    def match_template(image: str, similarity: float | None = None) -> str:
        assert similarity is None
        return {
            "image-a": "Oil_2",
            "image-b": "Coin",
            "image-c": "Gear",
        }[image]

    def match_cost_template(self, item: FakeItem) -> str | None:
        return self.costs[item.label]

    @staticmethod
    def predict_tag(image: tuple[str, str]) -> str:
        return f"tag-{image[0]}"


def test_item_grid_predict_runs_enabled_stages_and_filters_invalid_price() -> None:
    items = [FakeItem("a"), FakeItem("b"), FakeItem("c")]
    grid = FakeItemGrid(items, costs={"a": "Gem", "b": None, "c": "Coin"}, prices=[5, 0])

    result = grid.predict("screen", options=ItemPredictOptions(cost=True, price=True, tag=True))

    assert result == [items[0]]
    assert items[0].name == "Oil_2"
    assert items[0].amount == 11
    assert items[0].cost == "Gem"
    assert items[0].price == 5
    assert items[0].tag == "tag-a"


def test_item_grid_predict_keeps_disabled_stages_untouched() -> None:
    item = FakeItem("a")
    grid = FakeItemGrid([item], costs={"a": "Gem"}, prices=[5])

    result = grid.predict("screen", name=False, amount=False, cost=False, price=False, tag=False)

    assert result == [item]
    assert item.name == "DefaultItem"
    assert item.amount == 1
    assert item.cost == "DefaultCost"
    assert item.price == 0
    assert item.tag is None


def test_item_grid_area_settings_override_options() -> None:
    areas = item_grid_areas(ItemGridAreas(amount_area=(1, 2, 3, 4)), {"price_area": (5, 6, 7, 8)})

    assert areas.amount_area == (1, 2, 3, 4)
    assert areas.price_area == (5, 6, 7, 8)
