from types import SimpleNamespace

from module.shop.base import ShopBase


class _FakeDevice:
    def __init__(self) -> None:
        self.image = "image"
        self.screenshot_count = 0

    def screenshot(self) -> None:
        self.screenshot_count += 1


class _FakeGrid:
    def __getitem__(self, _key):
        return SimpleNamespace(area=(0, 100, 0, 0))


class _FakeItem:
    def __init__(self, name, *, known=True, row_y=100) -> None:
        self.name = name
        self.is_known_item = known
        self.button = (0, row_y)

    def __str__(self) -> str:
        return self.name


class _FakeShopItems:
    def __init__(self, item_sequences) -> None:
        self.item_sequences = [list(items) for items in item_sequences]
        self.items = []
        self.grids = _FakeGrid()
        self.predict_calls = []
        self.extract_calls = []

    def predict(self, image, **kwargs) -> None:
        self.predict_calls.append((image, kwargs))
        if self.item_sequences:
            self.items = self.item_sequences.pop(0)

    def extract_template(self, image, folder) -> None:
        self.extract_calls.append((image, folder))


class _FakeShopBase(ShopBase):
    def __init__(self, shop_items, *, extract_template=False, obstruct_results=()) -> None:
        self.device = _FakeDevice()
        self.config = SimpleNamespace(SHOP_EXTRACT_TEMPLATE=extract_template)
        self.shop_template_folder = "templates"
        self._shop_items = shop_items
        self.obstruct_results = list(obstruct_results)
        self.obstruct_calls = 0
        self.has_loaded_calls = []

    def shop_items(self):
        return self._shop_items

    def shop_obstruct_handle(self) -> bool:
        self.obstruct_calls += 1
        if self.obstruct_results:
            return self.obstruct_results.pop(0)
        return False

    def shop_has_loaded(self, items) -> bool:
        self.has_loaded_calls.append(list(items))
        return True


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
    assert shop.has_loaded_calls == [[item]]


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
    assert shop_items.extract_calls == [("image", "templates"), ("image", "templates")]
