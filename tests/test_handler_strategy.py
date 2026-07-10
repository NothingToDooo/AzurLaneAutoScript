from typing import cast

import pytest

from module.handler import assets as handler_assets
from module.handler.strategy import StrategyHandler


class _Device:
    def __init__(self, events: list[tuple[object, ...]]) -> None:
        self.events = events

    def screenshot(self) -> None:
        self.events.append(("screenshot",))


class _Strategy:
    def __init__(self) -> None:
        self.events: list[tuple[object, ...]] = []
        self.device = _Device(self.events)
        self.exit_checks = 0

    def appear_then_click(self, button: object, **kwargs: object) -> bool:
        self.events.append(("appear_then_click", button, kwargs))
        return self.exit_checks == 0

    def handle_popup_confirm(self, name: str) -> bool:
        self.events.append(("handle_popup_confirm", name))
        return self.exit_checks == 0

    def appear(self, button: object, **kwargs: object) -> bool:
        self.events.append(("appear", button, kwargs))
        self.exit_checks += 1
        return self.exit_checks == 2


@pytest.mark.parametrize(
    ("method_name", "click_button"),
    [
        ("strategy_submarine_move_confirm", handler_assets.SUBMARINE_MOVE_CONFIRM),
        ("strategy_submarine_move_cancel", handler_assets.SUBMARINE_MOVE_CANCEL),
    ],
)
def test_strategy_submarine_move_calls_actions_before_each_exit_check(method_name: str, click_button: object) -> None:
    strategy = _Strategy()

    method = getattr(StrategyHandler, method_name)
    method(cast("StrategyHandler", strategy))

    assert strategy.events == [
        ("appear_then_click", click_button, {"offset": (20, 20), "interval": 5}),
        ("handle_popup_confirm", "SUBMARINE_MOVE"),
        ("appear", handler_assets.SUBMARINE_MOVE_ENTER, {"offset": 200}),
        ("screenshot",),
        ("appear_then_click", click_button, {"offset": (20, 20), "interval": 5}),
        ("handle_popup_confirm", "SUBMARINE_MOVE"),
        ("appear", handler_assets.SUBMARINE_MOVE_ENTER, {"offset": 200}),
    ]
