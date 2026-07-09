from typing import TypeVar

from module.minigame.minigame import Minigame
from module.ui.assets import ACADEMY_GOTO_GAME_ROOM
from module.ui.page import page_academy, page_game_room

_T = TypeVar("_T")


class _Config:
    def __init__(self) -> None:
        self.delays: list[dict[str, object]] = []

    def task_delay(self, **kwargs: object) -> None:
        self.delays.append(kwargs)


class _Device:
    def __init__(self) -> None:
        self.clicks: list[object] = []

    def click(self, button: object) -> None:
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
        self.calls: list[tuple[object, ...]] = []
        self.page_results: dict[object, list[bool]] = {}
        self.popup_results: list[bool] = []
        self.coin_results: list[int] = []
        self.collect_results: list[bool] = []
        self.minigame_instance: _MinigameInstance | None = None

    def _next_result(self, results: list[_T], *, default: _T) -> _T:
        if results:
            return results.pop(0)
        return default

    def loop(self):
        return range(5)

    def ui_ensure(self, destination: object) -> None:
        self.calls.append(("ui_ensure", destination))

    def ui_page_appear(self, page: object, **kwargs: object) -> bool:
        self.calls.append(("ui_page_appear", page, kwargs))
        return self._next_result(self.page_results.get(page, []), default=False)

    def handle_popup_confirm(self, name: str) -> bool:
        self.calls.append(("handle_popup_confirm", name))
        return self._next_result(self.popup_results, default=False)

    def go_to_main_page(self) -> None:
        self.calls.append(("go_to_main_page",))

    def _create_minigame_instance(self, specific_game_name: str) -> _MinigameInstance | None:
        self.calls.append(("_create_minigame_instance", specific_game_name))
        return self.minigame_instance

    def get_coin_amount(self) -> int:
        self.calls.append(("get_coin_amount",))
        return self._next_result(self.coin_results, default=0)

    def collect_coin(self) -> bool:
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
