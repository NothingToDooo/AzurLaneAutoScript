from typing import TYPE_CHECKING, TypeVar, override

import numpy as np

from module.minigame.minigame import Minigame, MinigamePlayer
from module.ui.assets import ACADEMY_GOTO_GAME_ROOM
from module.ui.page import page_academy, page_game_room

if TYPE_CHECKING:
    from collections.abc import Iterator

    from module.base.button import Button, MatchOffset
    from module.base.timer import Timer
    from module.base.type_alias import ImageArray
    from module.ui.page import Page

_T = TypeVar("_T")

type _Call = tuple[str] | tuple[str, str] | tuple[str, Page] | tuple[str, Page, MatchOffset | None, float]


class _Config:
    def __init__(self) -> None:
        self.delays: list[dict[str, bool]] = []

    def task_delay(self, **kwargs: bool) -> None:
        self.delays.append(kwargs)


class _Device:
    def __init__(self) -> None:
        self.clicks: list[Button] = []
        self.image = np.zeros((2, 2, 3), dtype=np.uint8)

    def click(self, button: Button) -> None:
        self.clicks.append(button)


class _MinigameInstance:
    def __init__(self, results: list[bool]) -> None:
        self.results = results
        self.run_count = 0

    def minigame_run(self) -> bool:
        self.run_count += 1
        if self.results:
            return self.results.pop(0)
        return False


class _Minigame(Minigame):
    config: _Config
    device: _Device

    def __init__(self) -> None:
        self.config = _Config()
        self.device = _Device()
        self.calls: list[_Call] = []
        self.page_results: dict[Page, list[bool]] = {}
        self.popup_results: list[bool] = []
        self.coin_results: list[int] = []
        self.collect_results: list[bool] = []
        self.minigame_instance: _MinigameInstance | None = None

    @staticmethod
    def _next_result(results: list[_T], *, default: _T) -> _T:
        if results:
            return results.pop(0)
        return default

    @override
    def loop(
        self,
        *,
        skip_first: bool = True,
        timeout: float | Timer | None = None,
    ) -> Iterator[ImageArray]:
        del skip_first, timeout
        return iter([self.device.image] * 5)

    @override
    def ui_ensure(self, destination: Page, *, skip_first_screenshot: bool = True) -> bool:
        del skip_first_screenshot
        self.calls.append(("ui_ensure", destination))
        return False

    @override
    def ui_page_appear(
        self,
        page: Page,
        offset: MatchOffset | None = (30, 30),
        interval: float = 0,
    ) -> bool:
        self.calls.append(("ui_page_appear", page, offset, interval))
        return self._next_result(self.page_results.get(page, []), default=False)

    @override
    def handle_popup_confirm(
        self,
        name: str = "",
        offset: MatchOffset | None = None,
        interval: float = 2,
    ) -> bool:
        del offset, interval
        self.calls.append(("handle_popup_confirm", name))
        return self._next_result(self.popup_results, default=False)

    @override
    def go_to_main_page(self, *, skip_first_screenshot: bool = True) -> None:
        del skip_first_screenshot
        self.calls.append(("go_to_main_page",))

    @override
    def _create_minigame_instance(self, specific_game_name: str) -> MinigamePlayer | None:
        self.calls.append(("_create_minigame_instance", specific_game_name))
        return self.minigame_instance

    @override
    def get_coin_amount(self, *, skip_first_screenshot: bool = True) -> int:
        del skip_first_screenshot
        self.calls.append(("get_coin_amount",))
        return self._next_result(self.coin_results, default=0)

    @override
    def collect_coin(self, *, skip_first_screenshot: bool = True) -> bool:
        del skip_first_screenshot
        self.calls.append(("collect_coin",))
        return self._next_result(self.collect_results, default=False)


def test_minigame_run_enters_game_room_then_finishes_without_coin() -> None:
    minigame = _Minigame()
    minigame.page_results[page_game_room] = [False, True]
    minigame.page_results[page_academy] = [True]
    minigame.coin_results = [0]

    minigame.run()

    assert ("ui_ensure", page_academy) in minigame.calls
    assert minigame.device.clicks == [ACADEMY_GOTO_GAME_ROOM]
    assert ("go_to_main_page",) in minigame.calls
    assert minigame.config.delays == [{"server_update": True}]


def test_minigame_run_collects_coin_then_plays_once() -> None:
    minigame = _Minigame()
    minigame.page_results[page_game_room] = [True]
    minigame.coin_results = [20, 1, 0]
    minigame.collect_results = [True]
    minigame.minigame_instance = _MinigameInstance([True])

    minigame.run()

    assert ("collect_coin",) in minigame.calls
    assert minigame.minigame_instance.run_count == 1
    assert minigame.config.delays == [{"server_update": True}]
