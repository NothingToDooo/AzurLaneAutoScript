from typing import TYPE_CHECKING, override

from module.combat.assets import GET_ITEMS_1, GET_ITEMS_2
from module.os_handler import assets as os_assets
from module.os_handler.map_event import MapEventHandler

if TYPE_CHECKING:
    from module.base.button import Button, MatchOffset
    from module.device.control import ButtonTarget


class _FakeDevice:
    def __init__(self) -> None:
        self.clicks = []

    def click(self, button: ButtonTarget) -> None:
        self.clicks.append(button)


class _MapGetItemsContext(MapEventHandler):
    device: _FakeDevice

    def __init__(self, *, in_map: bool = False, appearing: tuple[Button, ...] = ()) -> None:
        self._in_map = in_map
        self.appearing = set(appearing)
        self.appear_calls = []
        self.device = _FakeDevice()

    @override
    def is_in_map(self) -> bool:
        return self._in_map

    @override
    def appear(
        self,
        button: Button,
        offset: MatchOffset | None = 0,
        interval: float = 0,
        similarity: float = 0.85,
        threshold: int = 10,
    ) -> bool:
        del offset, similarity, threshold
        self.appear_calls.append((button, {"interval": interval}))
        return button in self.appearing


class _MapEventContext(MapEventHandler):
    def __init__(self, results: dict[str, bool]) -> None:
        self.results = results
        self.calls = []

    def _handle(self, name: str) -> bool:
        self.calls.append(name)
        return self.results.get(name, False)

    @override
    def handle_map_get_items(self, interval: float = 5) -> bool:
        del interval
        return self._handle("map_get_items")

    @override
    def handle_os_game_tips(self) -> bool:
        return self._handle("os_game_tips")

    @override
    def handle_map_archives(self) -> bool:
        return self._handle("map_archives")

    @override
    def handle_guild_popup_cancel(self) -> bool:
        return self._handle("guild_popup_cancel")

    @override
    def handle_ash_popup(self) -> bool:
        return self._handle("ash_popup")

    @override
    def handle_urgent_commission(self) -> bool:
        return self._handle("urgent_commission")

    @override
    def handle_story_skip(self) -> bool:
        return self._handle("story_skip")


def test_handle_map_get_items_clicks_first_visible_item_popup() -> None:
    context = _MapGetItemsContext(appearing=(GET_ITEMS_2,))

    assert context.handle_map_get_items(interval=4) is True
    assert context.appear_calls == [
        (GET_ITEMS_1, {"interval": 4}),
        (GET_ITEMS_2, {"interval": 4}),
    ]
    assert context.device.clicks == [os_assets.CLICK_SAFE_AREA]


def test_handle_map_get_items_skips_when_already_in_map() -> None:
    context = _MapGetItemsContext(in_map=True, appearing=(GET_ITEMS_1,))

    assert context.handle_map_get_items() is False
    assert context.appear_calls == []
    assert context.device.clicks == []


def test_handle_map_event_returns_first_handled_event() -> None:
    context = _MapEventContext({"map_archives": True, "story_skip": True})

    assert context.handle_map_event() == "map_archives"
    assert context.calls == [
        "map_get_items",
        "os_game_tips",
        "map_archives",
    ]


def test_handle_map_event_returns_empty_string_without_event() -> None:
    context = _MapEventContext({})

    assert context.handle_map_event() == ""
    assert context.calls == [
        "map_get_items",
        "os_game_tips",
        "map_archives",
        "guild_popup_cancel",
        "ash_popup",
        "urgent_commission",
        "story_skip",
    ]
