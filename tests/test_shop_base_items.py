from types import SimpleNamespace
from typing import TYPE_CHECKING, Unpack, override

import numpy as np

from module.base.button import ButtonGrid
from module.shop.base import ShopBase, ShopItemGrid
from module.statistics.item import Item, ItemPredictOptions, ItemPredictSettings

if TYPE_CHECKING:
    from collections.abc import Iterable

    from module.base.type_alias import Area, FilePath, ImageArray


class _FakeDevice:
    def __init__(self) -> None:
        self.image = np.zeros((1, 1, 3), dtype=np.uint8)
        self.screenshot_count = 0

    def screenshot(self) -> None:
        self.screenshot_count += 1


class _FakeItem(Item):
    def __init__(self, name: str, *, known: bool = True, row_y: int = 100) -> None:
        self._name = name
        self._is_known_item = known
        self._row_y = row_y

    @property
    @override
    def button(self) -> Area:
        return (0, self._row_y, 1, self._row_y + 1)

    def is_known_item(self) -> bool:
        return self._is_known_item

    def __str__(self) -> str:
        return self.name


class _FakeShopItems(ShopItemGrid):
    def __init__(self, item_sequences: Iterable[Iterable[Item]]) -> None:
        grids = ButtonGrid(
            origin=(0, 100),
            delta=(1, 1),
            button_shape=(1, 1),
            grid_shape=(1, 1),
            name="FAKE_SHOP_GRID",
        )
        super().__init__(grids, templates={})
        self.item_sequences = [list(items) for items in item_sequences]
        self.predict_calls: list[ImageArray] = []
        self.extract_calls: list[tuple[ImageArray, FilePath | None]] = []

    @override
    def predict(
        self,
        image: ImageArray,
        options: ItemPredictOptions | None = None,
        **settings: Unpack[ItemPredictSettings],
    ) -> list[Item]:
        del options
        self.predict_calls.append(image)
        if self.item_sequences:
            self.items = self.item_sequences.pop(0)
        return self.items

    @override
    def extract_template(self, image: ImageArray, folder: FilePath | None = None) -> dict[str, ImageArray]:
        self.extract_calls.append((image, folder))
        return {}


class _FakeShopBase(ShopBase):
    config: SimpleNamespace
    device: _FakeDevice

    def __init__(
        self,
        shop_items: _FakeShopItems | None,
        *,
        extract_template: bool = False,
        obstruct_results: Iterable[bool] = (),
    ) -> None:
        self.device = _FakeDevice()
        self.config = SimpleNamespace(SHOP_EXTRACT_TEMPLATE=extract_template)
        self.shop_template_folder = "templates"
        self._shop_items = shop_items
        self.obstruct_results = list(obstruct_results)
        self.obstruct_calls = 0

    def shop_items(self) -> _FakeShopItems | None:
        return self._shop_items

    def shop_obstruct_handle(self) -> bool:
        self.obstruct_calls += 1
        if self.obstruct_results:
            return self.obstruct_results.pop(0)
        return False


def test_shop_grid_is_the_fixed_cn_layout_and_cached() -> None:
    shop = _FakeShopBase(None)

    grid = shop.shop_grid

    np.testing.assert_array_equal(grid.origin, (265, 238))
    np.testing.assert_array_equal(grid.delta, (169, 223))
    np.testing.assert_array_equal(grid.button_shape, (64, 64))
    np.testing.assert_array_equal(grid.grid_shape, (5, 2))
    assert grid[0, 0].button == (265, 238, 329, 302)
    assert grid.name == "SHOP_GRID"
    assert shop.shop_grid is grid


def test_shop_get_items_returns_empty_without_item_grid() -> None:
    shop = _FakeShopBase(None)

    assert shop.shop_get_items() == []


def test_shop_get_items_waits_until_known_count_is_stable() -> None:
    item = _FakeItem("coin")
    shop_items = _FakeShopItems([[item], [item]])
    shop = _FakeShopBase(shop_items)

    assert shop.shop_get_items() == [item]
    assert len(shop_items.predict_calls) == 2
    assert shop.device.screenshot_count == 1


def test_shop_get_items_handles_obstruction_before_prediction() -> None:
    item = _FakeItem("book")
    shop_items = _FakeShopItems([[item], [item]])
    shop = _FakeShopBase(shop_items, obstruct_results=[True, False, False])

    assert shop.shop_get_items() == [item]
    assert shop.obstruct_calls == 3
    assert len(shop_items.predict_calls) == 2


def test_shop_get_items_extracts_templates_while_waiting() -> None:
    item = _FakeItem("plate")
    shop_items = _FakeShopItems([[item], [item]])
    shop = _FakeShopBase(shop_items, extract_template=True)

    assert shop.shop_get_items() == [item]
    assert len(shop_items.extract_calls) == 2
    assert all(image is shop.device.image for image, _ in shop_items.extract_calls)
    assert [folder for _, folder in shop_items.extract_calls] == ["templates", "templates"]
