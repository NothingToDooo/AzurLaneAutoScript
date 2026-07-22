from typing import TYPE_CHECKING, cast, override

import pytest

from module.exception import GameStuckError
from module.handler import assets as handler_assets
from module.handler.strategy import STRATEGY_TRANSITION_BUDGET, StrategyHandler

if TYPE_CHECKING:
    from collections.abc import Iterator


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
        self.loop_timeout: float | None = None

    def loop(self, *, skip_first: bool = True, timeout: float | None = None) -> Iterator[object]:
        self.loop_timeout = timeout
        for index in range(3):
            if index or not skip_first:
                self.device.screenshot()
            yield object()

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
    assert strategy.loop_timeout == STRATEGY_TRANSITION_BUDGET


class _NeverTransitions(_Strategy, StrategyHandler):
    @override
    def appear_then_click(self, button: object, **kwargs: object) -> bool:
        del button, kwargs
        return False

    @override
    def appear(self, button: object, **kwargs: object) -> bool:
        del button, kwargs
        return False


@pytest.mark.parametrize(
    ("method_name", "operation"),
    [
        ("strategy_open", "open"),
        ("strategy_close", "close"),
        ("strategy_submarine_move_enter", "enter submarine move"),
        ("strategy_submarine_move_confirm", "confirm submarine move"),
        ("strategy_submarine_move_cancel", "cancel submarine move"),
        ("strategy_mob_move_enter", "enter enemy move"),
        ("strategy_mob_move_cancel", "cancel enemy move"),
        ("strategy_air_strike_enter", "enter air strike"),
        ("strategy_air_strike_cancel", "cancel air strike"),
    ],
)
def test_strategy_transition_exhaustion_raises_typed_stuck_error(method_name: str, operation: str) -> None:
    strategy = _NeverTransitions()

    with pytest.raises(GameStuckError, match=rf"{operation}; transition budget exhausted \(30-second baseline\)"):
        getattr(StrategyHandler, method_name)(cast("StrategyHandler", strategy))

    assert strategy.loop_timeout == STRATEGY_TRANSITION_BUDGET


class _CloseEvidenceStrategy(_Strategy):
    @override
    def appear_then_click(self, button: object, **kwargs: object) -> bool:
        self.events.append(("appear_then_click", button, kwargs))
        return False

    @override
    def appear(self, button: object, **kwargs: object) -> bool:
        self.events.append(("appear", button, kwargs))
        assert button is handler_assets.IN_MAP
        self.exit_checks += 1
        return self.exit_checks == 3


def test_strategy_close_waits_for_positive_map_evidence() -> None:
    strategy = _CloseEvidenceStrategy()

    StrategyHandler.strategy_close(cast("StrategyHandler", strategy))

    assert strategy.events == [
        ("appear_then_click", handler_assets.STRATEGY_OPENED, {"offset": 200, "interval": 5}),
        ("appear", handler_assets.IN_MAP, {"offset": 200}),
        ("screenshot",),
        ("appear_then_click", handler_assets.STRATEGY_OPENED, {"offset": 200, "interval": 5}),
        ("appear", handler_assets.IN_MAP, {"offset": 200}),
        ("screenshot",),
        ("appear_then_click", handler_assets.STRATEGY_OPENED, {"offset": 200, "interval": 5}),
        ("appear", handler_assets.IN_MAP, {"offset": 200}),
    ]
